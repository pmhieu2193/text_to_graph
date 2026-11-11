# Alembic

- `alembic upgrade head`: apply all migrations.
- `alembic revision --autogenerate -m "message"`: generate a new migration from model changes.
- Review generated scripts before applying them.
- Never rewrite an already deployed revision.
- Back up the SQLite database before migration.
