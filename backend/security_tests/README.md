# Authentication security regression tests

This suite uses a minimal FastAPI app with the real auth routes and services.
It never uses the configured project database. Set `TEST_DATABASE_URL` to a
disposable PostgreSQL instance; each run creates and removes its own schema.
Install `backend/requirements.txt`, then run from the project root:

```sh
TEST_DATABASE_URL=postgresql://postgres:password@localhost:55432/postgres \
  PYTHONPATH=backend python -m pytest backend/security_tests -q
```

Database tests skip if `TEST_DATABASE_URL` is absent. Configuration tests still
run. Coverage includes rotation races, transactional rollback, password-change
revocation, immediate access-token invalidation, CSRF, sensitive-action limits,
validation redaction, TOTP encryption/replay, and migration of existing secrets.
