"""Exercise backup/restore as a CLI against real, isolated PostgreSQL containers."""

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get("RECOVERY_APP_IMAGE", "serentable-foundation:local")


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, **kwargs)


def main():
    os.umask(0o077)
    source = "serentable-source-" + uuid.uuid4().hex[:12]
    directory = ROOT / ".local-backups" / ("rehearsal-" + uuid.uuid4().hex[:12])
    directory.mkdir(parents=True, mode=0o700)
    password = secrets.token_hex(24)
    environment = {**os.environ, "POSTGRES_PASSWORD": password, "PGPASSWORD": password}
    command = [sys.executable, str(ROOT / "scripts/postgres_recovery.py")]
    try:
        run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                source,
                "--env",
                "POSTGRES_PASSWORD",
                "--env",
                "PGPASSWORD",
                "--env",
                "POSTGRES_USER=serentable",
                "--env",
                "PGUSER=serentable",
                "--env",
                "POSTGRES_DB=source_test",
                "--env",
                "PGDATABASE=source_test",
                "postgres:18-alpine",
            ],
            env=environment,
        )
        for _ in range(30):
            result = subprocess.run(
                ["docker", "exec", source, "pg_isready", "-U", "serentable"],
                capture_output=True,
            )
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Source fixture did not start")
        app_environment = {
            **os.environ,
            "DATABASE_URL": f"postgresql://serentable:{password}@127.0.0.1:5432/source_test",
        }
        runtime = [
            "docker",
            "run",
            "--rm",
            "--network",
            f"container:{source}",
            "--env",
            "DATABASE_URL",
            IMAGE,
        ]
        run([*runtime, "alembic", "upgrade", "head"], env=app_environment)
        run([*runtime, "python", "-m", "serentable.worker", "--once"], env=app_environment)
        query = [
            "docker",
            "exec",
            source,
            "psql",
            "-U",
            "serentable",
            "-d",
            "source_test",
            "-At",
            "-c",
            "SELECT name, last_seen FROM worker_heartbeat ORDER BY name;",
        ]
        before = run(query).stdout
        dump = directory / "source.dump"
        backup = [*command, "backup", "--local-source", source, "--output", str(dump)]
        run(backup, cwd=ROOT)
        unsafe = ROOT / "frontend" / "public" / ("unsafe-" + uuid.uuid4().hex + ".dump")
        assert (
            subprocess.run(
                [*command, "backup", "--local-source", source, "--output", str(unsafe)],
                capture_output=True,
            ).returncode
            != 0
        )
        assert not unsafe.exists()
        digest = hashlib.sha256(dump.read_bytes()).hexdigest()
        assert dump.stat().st_mode & 0o777 == 0o600
        assert subprocess.run(backup, cwd=ROOT, capture_output=True).returncode != 0
        assert hashlib.sha256(dump.read_bytes()).hexdigest() == digest
        partial_dump = directory / "collision.dump"
        partial = partial_dump.with_suffix(".partial")
        partial.write_bytes(b"preserve an existing unfinished backup")
        collision = [*command, "backup", "--local-source", source, "--output", str(partial_dump)]
        assert subprocess.run(collision, cwd=ROOT, capture_output=True).returncode != 0
        assert partial.read_bytes() == b"preserve an existing unfinished backup"
        result = run([*command, "restore", "--dump", str(dump), "--app-image", IMAGE])
        report = json.loads(result.stdout)
        assert report["restore"] == "passed"
        assert report["sha256"] == digest
        assert report["restored_heartbeat_rows_before_worker"] == 1
        assert run(query).stdout == before, "Restoration must not modify its source"
        corrupt = directory / "corrupt.dump"
        corrupt.write_bytes(b"not a PostgreSQL archive")
        assert (
            subprocess.run(
                [*command, "restore", "--dump", str(corrupt), "--app-image", IMAGE],
                capture_output=True,
            ).returncode
            != 0
        )
        print(
            json.dumps(
                {
                    "backup_restore_rehearsal": "passed",
                    "api_readiness_and_worker": "passed",
                    "source_unchanged": True,
                    "existing_dump_and_partial_preserved": True,
                    "corrupt_archive_rejected": True,
                    "public_asset_output_rejected": True,
                    "dump_mode": "0600",
                    "scope": "local PostgreSQL 18 foundation fixture; not Railway data",
                }
            )
        )
    finally:
        subprocess.run(["docker", "rm", "--force", "--volumes", source], capture_output=True)


if __name__ == "__main__":
    main()
