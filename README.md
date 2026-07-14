# common-tools

Internal Python 3.12+ infrastructure primitives for application logging, async PostgreSQL, and
Redis coordination.

## Installation

Production services must install an immutable Git tag instead of following `main`:

```bash
pip install "common-tools[postgres] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.2.1"
pip install "common-tools[redis] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.2.1"
pip install "common-tools[logging] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.2.1"
pip install "common-tools[all] @ git+ssh://git@github.com/Ming-Yi/common-tools.git@v0.2.1"
```

## Application logging

Install the `logging` extra, then configure standard-library logging once near the beginning of
the application entry point. Logger objects created before configuration will use the new handlers
for records emitted afterward; records emitted before configuration are not retained.

```python
import logging

from common_tools.logging import configure_logging

configure_logging(
    filename="billing-api",
    log_dir="logs",
    retention_days=30,
    max_file_size_mb=100,
)

logger = logging.getLogger(__name__)
logger.info("payment completed")
```

The default configuration writes the same fixed text format to a UTF-8 file and to `stderr`.
Interactive terminals receive ANSI colors; redirected console output and files never do. Timestamps,
daily rotation, archive dates, and retention use `Asia/Taipei` unless another IANA timezone is
configured.

```text
2026-07-15T14:32:08.481+08:00 INFO [billing.payment] [pid=1842 thread=MainThread] service.py:42 payment completed
```

The active file keeps a stable name across restarts and processes. Rotation is lazy: the first log
record after midnight performs the daily rollover. Setting `max_file_size_mb` additionally rolls
over when the active file reaches the configured soft limit.

```text
logs/billing-api.log
logs/billing-api.2026-07-15.001.log
logs/billing-api.2026-07-15.002.log
```

All processes on one host may write the same active file. The handler uses a process lock for both
writes and rotation, and reinitializes its resources after `fork()`. Shared network filesystems and
multiple hosts are outside the supported reliability boundary; use console collection for those
deployments.

Explicit arguments override environment variables:

| Argument | Environment variable | Default |
|---|---|---|
| `filename` | `LOG_FILENAME` | `app` |
| `log_dir` | `LOG_DIR` | `./logs` |
| `level` | `LOG_LEVEL` | `INFO` |
| `retention_days` | `LOG_RETENTION_DAYS` | `30` |
| `max_file_size_mb` | `LOG_MAX_FILE_SIZE_MB` | disabled |
| `timezone` | `LOG_TIMEZONE` | `Asia/Taipei` |
| `compression` | `LOG_COMPRESSION` | disabled |

Use `None` explicitly to disable retention, size rotation, or compression even when its environment
variable is set. Compression accepts only `"gzip"`. The log directory is created automatically;
an invalid configuration or unwritable directory fails application startup.

`configure_logging()` replaces root, Uvicorn, and Gunicorn handlers so records are not duplicated.
Calling it again with the same effective settings is a no-op; changing settings requires an explicit
`shutdown_logging()` first.

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
