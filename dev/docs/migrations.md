# Writing migrations

The Alembic migrations ship inside the package, in `kohle/db/migrations/`.
From the repo root:

```bash
alembic revision --autogenerate -m "..."
```

This compares the models with the ledger at the resolved location (or
`KOHLE_DB`). `alembic upgrade` is a developer tool; users upgrade a ledger with
`kohle-cli migrate`.

Every new migration changes the Alembic head, so the user guide's Getting
started page fails its checked output until that output is updated. That is
intended.
