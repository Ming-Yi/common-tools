# Changelog

## v0.3.1 - 2026-07-18

- Add a complete Traditional Chinese README and move the Alembic setup, development, deployment,
  and dual-database guidance directly into both READMEs.
- Split application logging into focused configuration, formatting, handler, runtime, and exception
  modules while preserving the existing `common_tools.logging` interface.
- Register reusable Redis Lua scripts for atomic, ownership-checked lock renewal and release.

## v0.3.0 - 2026-07-15

- Add async SQL Server 2019+ support through `SqlServerConfig`, `aioodbc`, and Microsoft ODBC
  Driver 18.
- Add a separate `sqlserver` dependency extra and real SQL Server 2019 integration coverage.
- Add `AsyncDatabase.check_connection()` for explicit `SELECT 1` health checks.
- Support independent PostgreSQL and SQL Server instances in one FastAPI application without
  cross-database transaction coordination or library-owned retry tasks.
- Stop setting and verifying the PostgreSQL session timezone during startup; applications now own
  UTC value handling.

## v0.2.3 - 2026-07-15

- Declare explicit `__all__` public exports in the database and locking source modules and cover
  them with module-export tests.

## v0.2.2 - 2026-07-15

- Add `common_tools.settings.SettingsProvider` for a process-wide settings instance with
  context-local test overrides, independent of any settings library.
- Document application settings ownership and FastAPI lifespan, `app.state`, and dependency
  integration in the README.

## v0.2.1 - 2026-07-15

- Add explicit standard-library logging configuration with colored console output and a fixed
  timezone-aware text format.
- Add process-safe daily and optional size rotation, calendar-day retention, optional gzip
  compression, and safe fork reinitialization through the `logging` extra.

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
