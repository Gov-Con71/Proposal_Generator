# init_scripts/ — frozen

**These files are the historical record, not the schema's source of truth.
That is now `backend/migrations/` (Alembic).**

They remain here, and remain mounted at `docker-entrypoint-initdb.d` in both
compose files, for one reason: a fresh local Postgres container comes up with a
usable schema without anyone remembering to run a command. Postgres executes
them exactly once, on first initialisation of an empty data directory — which is
also why they were never a deployment mechanism. A managed RDS instance never
runs them, so before Alembic a production database had no tables at all
(`GAP_ANALYSIS.md` §3.2).

## Do not add files here

Every schema change from now on is an Alembic revision:

```bash
cd backend
alembic revision -m "add rfp_documents.failure_reason"   # then edit the file
alembic upgrade head
```

`migrations/versions/0001_baseline_schema.py` contains all eight files below,
squashed, in the lexicographic order Postgres applied them. It is idempotent, so
it can be applied to an already-provisioned database as a no-op.

Adding a ninth `.sql` file here would apply to fresh local containers and
nowhere else — silent drift between your machine and production, which is the
exact failure this directory was retired for.

## Adopting an existing database

A database that already has the schema (a long-running dev container, or a
pre-Alembic environment) needs to be told what it is, once:

```bash
alembic stamp 0001_baseline   # records the revision, applies nothing
alembic current               # → 0001_baseline (head)
```

`alembic upgrade head` is also safe there — every statement in the baseline is
guarded — but `stamp` states the intent more clearly.

## Verifying a change

The baseline was validated by building one database each way and diffing
`pg_dump --schema-only`; they were byte-identical across 27 objects. That is a
cheap check worth repeating whenever the baseline is touched.
