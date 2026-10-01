"""Apply numbered SQL migrations in file-name order, once each.

Usage: python -m weir.migrate   (reads DATABASE_URL and WEIR_MIGRATIONS_DIR)
"""
import os
from pathlib import Path

import psycopg


def apply_migrations(url: str, directory: Path) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "create table if not exists public.schema_migrations ("
            " version text primary key,"
            " applied_at timestamptz not null default now())"
        )
        done = {r[0] for r in conn.execute("select version from public.schema_migrations")}
        for path in sorted(directory.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "insert into public.schema_migrations (version) values (%s)", (path.name,)
                )
            applied.append(path.name)
    return applied


def main() -> None:
    url = os.environ["DATABASE_URL"]
    directory = Path(os.environ.get("WEIR_MIGRATIONS_DIR", "/app/db/migrations"))
    applied = apply_migrations(url, directory)
    print(f"applied {len(applied)} migration(s): {', '.join(applied) or 'none'}")


if __name__ == "__main__":
    main()
