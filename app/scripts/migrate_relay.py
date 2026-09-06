"""One-shot schema patch: add the relay-disconnect columns to `meters`.

    python -m app.scripts.migrate_relay

This project has no migration tool — the schema is `Base.metadata.create_all`,
which creates missing *tables* but never alters existing ones. A database
created before the remote-disconnect feature therefore lacks
`meters.relay_state` / `meters.relay_updated_at`; this adds them.

Idempotent and safe to re-run. A brand-new database (first `create_all` after
this feature landed) already has both columns and doesn't need this.
"""

from sqlalchemy import text

from app.database import engine

DDL = [
    # CREATE TYPE has no IF NOT EXISTS — swallow the duplicate.
    "DO $$ BEGIN "
    "  CREATE TYPE relay_state AS ENUM ('connected', 'disconnected'); "
    "EXCEPTION WHEN duplicate_object THEN NULL; "
    "END $$;",
    "ALTER TABLE meters ADD COLUMN IF NOT EXISTS relay_state relay_state "
    "NOT NULL DEFAULT 'connected';",
    "ALTER TABLE meters ADD COLUMN IF NOT EXISTS relay_updated_at timestamptz;",
]


def main() -> None:
    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))
    print("OK — meters.relay_state and meters.relay_updated_at are present.")


if __name__ == "__main__":
    main()
