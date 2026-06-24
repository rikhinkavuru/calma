"""control_plane.migrate — apply control_plane/migrations/*.sql in order, idempotently.

Tracks applied migrations in a `schema_migrations` table, so re-running is a no-op. Each .sql file owns
its own BEGIN/COMMIT, so a failed migration rolls back atomically (no partial schema). Run:

    control_plane/.venv/bin/python control_plane/migrate.py          # apply pending
    control_plane/.venv/bin/python control_plane/migrate.py --status # show applied + table list
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import db  # noqa: E402

MIGRATIONS = os.path.join(HERE, "migrations")


def _applied(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                 "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}


def _tables(conn):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY table_name").fetchall()
    return [r[0] for r in rows]


def status():
    with db.connect() as conn:
        applied = sorted(_applied(conn))
        print("applied migrations: %s" % (", ".join(applied) or "(none)"))
        print("public tables (%d): %s" % (len(_tables(conn)), ", ".join(_tables(conn)) or "(none)"))


def migrate():
    files = sorted(glob.glob(os.path.join(MIGRATIONS, "*.sql")))
    if not files:
        print("no migration files found in %s" % MIGRATIONS)
        return 0
    with db.connect() as conn:
        applied = _applied(conn)
        pending = [f for f in files if os.path.basename(f) not in applied]
        if not pending:
            print("up to date — %d migration(s) already applied" % len(applied))
            return 0
        for f in pending:
            version = os.path.basename(f)
            sql = open(f).read()
            print("applying %s ..." % version, end=" ", flush=True)
            try:
                conn.execute(sql)                       # the file wraps its own BEGIN/COMMIT (atomic)
                conn.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (version,))
            except Exception as e:
                print("FAILED")
                print("  %s: %s" % (type(e).__name__, e))
                return 1
            print("ok")
        print("\ndone. public tables (%d): %s" % (len(_tables(conn)), ", ".join(_tables(conn))))
    return 0


if __name__ == "__main__":
    if "--status" in sys.argv:
        status()
    else:
        sys.exit(migrate())
