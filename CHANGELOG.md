# Changelog

## v0.2.0 - 2026-07-14

- Replace global database singletons with explicit async PostgreSQL instances.
- Separate non-committing sessions from transactional scopes.
- Add Redis coordination locks with bounded waiting, renewal, and lease-loss cancellation.
- Move ORM metadata and Alembic revisions to consuming services.
- Remove global logging configuration and legacy utility base classes.
- Add strict typing, CI, and real PostgreSQL/Redis integration tests.

## v0.1.0 - 2026-07-14

- Preserve the original logging, synchronous/asynchronous database, model loading, and PostgreSQL
  advisory-lock implementation as the pre-refactor baseline.
