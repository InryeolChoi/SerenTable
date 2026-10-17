// Recreates the E2E database schema (alembic downgrade base, then upgrade head) so every
// browser run starts from empty tables. Destructive, so it refuses any DATABASE_URL whose
// host is not this machine.
import { execFileSync } from "node:child_process";

const local = new Set(["127.0.0.1", "localhost"]);
let host = "";
try {
  host = new URL(process.env.DATABASE_URL ?? "").hostname;
} catch {
  // An unparsable URL is refused below.
}
if (!local.has(host)) {
  console.error(
    `E2E schema reset refused: DATABASE_URL must point to 127.0.0.1 or localhost (got host "${host}").`,
  );
  process.exit(1);
}
execFileSync("uv", ["run", "python", "-c", `
from sqlalchemy import text
from serentable.database import database_engine
with database_engine().begin() as connection:
    if connection.execute(text("SELECT to_regclass('public.event_slot')")).scalar():
        tables = "event_slot, application" if connection.execute(text("SELECT to_regclass('public.application')")).scalar() else "event_slot"
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))
`], { cwd: "..", env: { ...process.env, PYTHONPATH: "backend" }, stdio: "inherit" });
for (const step of [
  ["downgrade", "base"],
  ["upgrade", "head"],
]) {
  // alembic.ini resolves migrations and backend relative to the repository root.
  execFileSync("uv", ["run", "alembic", ...step], {
    cwd: "..",
    stdio: "inherit",
  });
}
