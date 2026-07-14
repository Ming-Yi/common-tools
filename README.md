# common-tools

Internal Python 3.12+ infrastructure primitives for async PostgreSQL and Redis coordination.

## Installation

Production services must install an immutable Git tag instead of following `main`:

```bash
pip install "common-tools[postgres] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.2.0"
pip install "common-tools[redis] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.2.0"
pip install "common-tools[all] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.2.0"
```

## Async PostgreSQL

Each `AsyncDatabase` owns exactly one SQLAlchemy engine. Create one instance per database,
start it at application startup, and close it at shutdown. Every pooled connection uses UTC.

```python
from common_tools.database import AsyncDatabase, PostgresConfig

database = AsyncDatabase(
    PostgresConfig(
        url="postgresql+asyncpg://user:password@localhost/app",
        pool_size=5,
        max_overflow=10,
    )
)

async with database:
    async with database.session() as session:
        # No implicit commit. Suitable for reads or caller-managed transactions.
        result = await session.execute(...)

    async with database.transaction() as session:
        # Commits on success and rolls back on failure.
        session.add(...)
```

Framework applications can call `await database.start()` and the idempotent
`await database.close()` from their lifespan hooks. The package does not keep a global database
instance or perform tenant routing.

### Application-owned ORM metadata

Each consuming service owns its declarative base and Alembic history. `common-tools` only provides
an optional repr mixin and stable constraint names:

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from common_tools.database import NAMING_CONVENTION, ReprMixin


class AppBase(ReprMixin, DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

See [Alembic integration](docs/alembic.md). Runtime model scanning and `create_all()` are
intentionally not part of this package.

## Redis coordination locks

`RedisLockManager` uses an application-owned `redis.asyncio.Redis` client. Locks reduce duplicate
work; database constraints, idempotency keys, and transactions must still protect business
correctness.

```python
from redis.asyncio import Redis

from common_tools.locking import RedisLockManager

redis = Redis.from_url("redis://localhost:6379/0")
locks = RedisLockManager(redis, namespace="prod:billing")

# Skip when another worker owns the lock.
async with locks.try_acquire("daily-report", ttl=30, max_hold=600) as acquired:
    if acquired:
        await build_report()

# Wait for a bounded period, then raise LockAcquisitionTimeout.
async with locks.acquire(
    "daily-report",
    ttl=30,
    max_hold=600,
    wait_timeout=10,
):
    await build_report()

await redis.aclose()
```

The manager renews a held lease every `ttl / 3`. It verifies a unique ownership token on renew and
release. Reaching `max_hold`, losing ownership, or failing to renew cancels the protected task and
raises `LockLostError`. Initial Redis failures raise `LockBackendUnavailable` (fail-closed).

## Development

```bash
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not integration"
uv run pytest -m integration
uv build
```

Integration tests use Testcontainers and require a running Docker daemon.

## Releases

Versions are derived from Git tags. The pre-refactor code is preserved as `v0.1.0`; this breaking
rewrite is released as `v0.2.0`. See [release procedure](docs/releasing.md).
