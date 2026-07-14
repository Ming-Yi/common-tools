import pytest
from sqlalchemy import text

from common_tools.database import AsyncDatabase, DatabaseNotStartedError, PostgresConfig


def test_postgres_config_rejects_non_async_postgresql_urls() -> None:
    with pytest.raises(ValueError, match=r"postgresql\+asyncpg"):
        PostgresConfig(url="sqlite+aiosqlite:///:memory:")


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"pool_size": 0}, "pool_size"),
        ({"max_overflow": -1}, "max_overflow"),
        ({"pool_timeout": 0}, "pool_timeout"),
        ({"pool_recycle": 0}, "pool_recycle"),
    ],
)
def test_postgres_config_rejects_unusable_pool_settings(
    overrides: dict[str, int],
    field: str,
) -> None:
    with pytest.raises(ValueError, match=field):
        PostgresConfig(
            url="postgresql+asyncpg://user:secret@localhost/app",
            **overrides,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_database_rejects_sessions_before_start() -> None:
    database = AsyncDatabase(PostgresConfig(url="postgresql+asyncpg://user:secret@localhost/app"))

    with pytest.raises(DatabaseNotStartedError):
        async with database.session():
            pass


@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_context_provides_utc_sessions(postgres_url: str) -> None:
    async with (
        AsyncDatabase(PostgresConfig(url=postgres_url)) as database,
        database.session() as session,
    ):
        timezone = await session.scalar(text("SHOW timezone"))

    assert timezone == "UTC"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_transaction_commits_successful_work(postgres_url: str) -> None:
    async with AsyncDatabase(PostgresConfig(url=postgres_url)) as database:
        async with database.transaction() as session:
            await session.execute(text("CREATE TABLE transaction_probe (value integer NOT NULL)"))
            await session.execute(text("INSERT INTO transaction_probe VALUES (7)"))

        async with database.session() as session:
            stored_value = await session.scalar(text("SELECT value FROM transaction_probe"))

    assert stored_value == 7
