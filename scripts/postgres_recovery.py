"""Read-only export; restoration is restricted to a new, isolated local container."""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROJECT = "e10b5d09-4b75-43c4-b46b-13414b96f11f"
ENVIRONMENT = "ec632dcd-2bc7-450c-9a98-bfc291c25338"
POSTGRES = "4b44361f-f461-4a2f-9c42-39612907cd58"
IMAGE = "postgres:18-alpine"
RAILWAY = ["npm", "exec", "--yes", "--package=@railway/cli@5.69.0", "--", "railway"]


def run(
    command, *, stdin=None, stdout=subprocess.PIPE, env=None, timeout=120, stage="external command"
):
    try:
        return subprocess.run(
            command,
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            env=env,
            check=True,
            timeout=timeout,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        # Provider/driver diagnostics can contain credentials or record contents.
        raise RuntimeError(f"{stage} failed; raw diagnostics withheld") from None


def validate_dump(path):
    with path.open("rb") as stream:
        if stream.read(5) != b"PGDMP":
            raise RuntimeError("Expected a PostgreSQL custom-format archive")
    with path.open("rb") as stream:
        run(["docker", "run", "--rm", "-i", IMAGE, "pg_restore", "--list"], stdin=stream)


def backup(args):
    destination = args.output.resolve()
    if not destination.is_relative_to(ROOT / ".local-backups"):
        raise RuntimeError("Backup output must be inside the private .local-backups directory")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Both dump and temporary file must be ignored, outside public assets and Git.
    for candidate in [destination, destination.with_suffix(".partial")]:
        run(["git", "-C", str(ROOT), "check-ignore", "--quiet", str(candidate)])
    temporary = destination.with_suffix(".partial")
    if destination.exists():
        raise RuntimeError("Backup destination already exists")
    command = [
        "pg_dump",
        "--host=127.0.0.1",
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--lock-wait-timeout=10s",
    ]
    if args.local_source:
        # Local rehearsal only. This source container is never a restore target.
        command = ["docker", "exec", args.local_source, *command]
    else:
        command = [
            *RAILWAY,
            "ssh",
            "--project",
            PROJECT,
            "--environment",
            ENVIRONMENT,
            "--service",
            POSTGRES,
            *(["--identity-file", str(args.identity_file)] if args.identity_file else []),
            "--",
            *command,
        ]
    owned_temporary = False
    try:
        with temporary.open("xb") as stream, open(os.devnull, "rb") as empty:
            owned_temporary = True
            os.chmod(temporary, 0o600)
            run(command, stdin=empty, stdout=stream, timeout=600)
        validate_dump(temporary)
        # Exclusive destination creation also protects against an intervening file.
        os.link(temporary, destination)
        print(json.dumps({"backup": str(destination), "bytes": destination.stat().st_size}))
    finally:
        if owned_temporary:
            temporary.unlink(missing_ok=True)


def restore(args):
    archive = args.dump.resolve()
    validate_dump(archive)
    suffix = uuid.uuid4().hex[:12]
    database = f"serentable-restore-{suffix}"
    application = f"serentable-restore-app-{suffix}"
    password = secrets.token_hex(24)
    environment = {**os.environ, "POSTGRES_PASSWORD": password}
    app_environment = {
        **os.environ,
        "DATABASE_URL": f"postgresql://serentable:{password}@127.0.0.1:5432/restore_test",
    }
    started = []
    try:
        # No published port, no existing volume, no arbitrary destination URL.
        run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                database,
                "--label",
                "serentable.purpose=restore-drill",
                "--env",
                "POSTGRES_PASSWORD",
                "--env",
                "POSTGRES_USER=serentable",
                "--env",
                "POSTGRES_DB=restore_test",
                IMAGE,
            ],
            env=environment,
            stage="restore database creation",
        )
        started.append(database)
        for _ in range(30):
            try:
                run(["docker", "exec", database, "pg_isready", "-U", "serentable"])
                break
            except RuntimeError:
                time.sleep(1)
        else:
            raise RuntimeError("Restore database did not become ready")
        with archive.open("rb") as stream:
            run(
                [
                    "docker",
                    "exec",
                    "-i",
                    database,
                    "pg_restore",
                    "--username=serentable",
                    "--dbname=restore_test",
                    "--no-owner",
                    "--no-acl",
                    "--exit-on-error",
                    "--single-transaction",
                ],
                stdin=stream,
                stage="archive restore",
            )
        count = (
            run(
                [
                    "docker",
                    "exec",
                    database,
                    "psql",
                    "-U",
                    "serentable",
                    "-d",
                    "restore_test",
                    "-At",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    "SELECT count(*) FROM worker_heartbeat;",
                ]
            )
            .decode()
            .strip()
        )
        app_command = [
            "docker",
            "run",
            "--network",
            f"container:{database}",
            "--env",
            "DATABASE_URL",
        ]
        run(
            [
                *app_command,
                "--detach",
                "--name",
                application,
                args.app_image,
                "python",
                "-m",
                "serentable.server",
            ],
            env=app_environment,
            stage="restored application launch",
        )
        started.append(application)
        # Refresh the restored heartbeat, since the saved one may be old.
        run(
            [
                *app_command,
                "--rm",
                args.app_image,
                "python",
                "-m",
                "serentable.worker",
                "--once",
            ],
            env=app_environment,
            stage="restored worker execution",
        )
        probe = (
            "import json,urllib.request; "
            "r=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/readiness')); "
            "w=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/worker-health')); "
            "assert r=={'status':'ready','database':'connected'},r; "
            "assert w=={'status':'alive'},w; print('restored_api_worker_ok')"
        )
        for _ in range(15):
            try:
                run(
                    [*app_command, "--rm", args.app_image, "python", "-c", probe],
                    env=app_environment,
                )
                break
            except RuntimeError:
                time.sleep(1)
        else:
            raise RuntimeError("Restored API/worker did not pass HTTP checks")
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        checksum = digest.hexdigest()
        report = {
            "restore": "passed",
            "postgres_image": IMAGE,
            "sha256": checksum,
            "restored_heartbeat_rows_before_worker": int(count),
            "readiness": "ready",
            "worker_health": "alive",
            "scope": "foundation heartbeat only; no business data validated",
        }
    finally:
        for name in reversed(started):
            # Only containers created by this invocation; remove their anonymous volumes.
            run(["docker", "rm", "--force", "--volumes", name])
    print(json.dumps(report))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("backup")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--local-source", help="Existing local fixture container for rehearsal")
    export.add_argument("--identity-file", type=Path, help="Dedicated local Railway SSH key")
    export.set_defaults(action=backup)
    verify = commands.add_parser("restore")
    verify.add_argument("--dump", type=Path, required=True)
    verify.add_argument("--app-image", default="serentable-foundation:local")
    verify.set_defaults(action=restore)
    args = parser.parse_args()
    try:
        args.action(args)
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(
            1,
            f"Recovery check failed: {str(error) if isinstance(error, RuntimeError) else type(error).__name__}; "
            "verify Docker, CLI login, source and archive. No raw secrets logged.\n",
        )


if __name__ == "__main__":
    main()
