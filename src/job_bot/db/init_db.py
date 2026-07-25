from __future__ import annotations

from job_bot.db.database import create_database_engine, create_schema


def main() -> None:
    engine = create_database_engine()
    try:
        create_schema(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
