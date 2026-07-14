import pytest
from sqlalchemy import text

from common_tools.database import (
    AsyncDatabase,
    DatabaseNotStartedError,
    PostgresConfig,
    SqlServerConfig,
)


def test_postgres_config_rejects_non_async_postgresql_urls() -> None:
    with pytest.raises(ValueError, match=r"postgresql\+asyncpg"):
        PostgresConfig(url="sqlite+aiosqlite:///:memory:")


def test_sql_server_config_rejects_non_async_sql_server_urls() -> None:
    with pytest.raises(ValueError, match=r"mssql\+aioodbc"):
        SqlServerConfig(
            url="mssql+pyodbc://user:secret@localhost/app?driver=ODBC+Driver+18+for+SQL+Server"
        )


def test_sql_server_config_requires_odbc_driver_18() -> None:
    with pytest.raises(ValueError, match="ODBC Driver 18 for SQL Server"):
        SqlServerConfig(url="mssql+aioodbc://user:secret@localhost/app")


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


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"pool_size": 0}, "pool_size"),
        ({"max_overflow": -1}, "max_overflow"),
        ({"pool_timeout": 0}, "pool_timeout"),
        ({"pool_recycle": 0}, "pool_recycle"),
    ],
)
def test_sql_server_config_rejects_unusable_pool_settings(
    overrides: dict[str, int],
    field: str,
) -> None:
    with pytest.raises(ValueError, match=field):
        SqlServerConfig(
            url="mssql+aioodbc://user:secret@localhost/app?driver=ODBC+Driver+18+for+SQL+Server",
            **overrides,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_database_rejects_sessions_before_start() -> None:
    database = AsyncDatabase(PostgresConfig(url="postgresql+asyncpg://user:secret@localhost/app"))

    with pytest.raises(DatabaseNotStartedError):
        async with database.session():
            pass


@pytest.mark.asyncio
async def test_database_rejects_connection_checks_before_start() -> None:
    database = AsyncDatabase(PostgresConfig(url="postgresql+asyncpg://user:secret@localhost/app"))

    with pytest.raises(DatabaseNotStartedError):
        await database.check_connection()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_database_connects(postgres_url: str) -> None:
    async with AsyncDatabase(PostgresConfig(url=postgres_url)) as database:
        await database.check_connection()


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_server_transaction_commits_successful_work(sql_server_url: str) -> None:
    async with AsyncDatabase(SqlServerConfig(url=sql_server_url)) as database:
        await database.check_connection()
        async with database.transaction() as session:
            await session.execute(text("CREATE TABLE transaction_probe (value integer NOT NULL)"))
            await session.execute(text("INSERT INTO transaction_probe VALUES (7)"))

        async with database.session() as session:
            stored_value = await session.scalar(text("SELECT value FROM transaction_probe"))

    assert stored_value == 7


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_server_transaction_rolls_back_failed_work(sql_server_url: str) -> None:
    async with AsyncDatabase(SqlServerConfig(url=sql_server_url)) as database:
        async with database.transaction() as session:
            await session.execute(text("CREATE TABLE rollback_probe (value integer NOT NULL)"))

        with pytest.raises(RuntimeError, match="abort transaction"):
            async with database.transaction() as session:
                await session.execute(text("INSERT INTO rollback_probe VALUES (9)"))
                raise RuntimeError("abort transaction")

        async with database.session() as session:
            stored_value = await session.scalar(text("SELECT value FROM rollback_probe"))

    assert stored_value is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_and_sql_server_instances_are_independent(
    postgres_url: str,
    sql_server_url: str,
) -> None:
    async with (
        AsyncDatabase(PostgresConfig(url=postgres_url)) as postgres,
        AsyncDatabase(SqlServerConfig(url=sql_server_url)) as sql_server,
    ):
        await postgres.check_connection()
        await sql_server.check_connection()

        async with postgres.session() as postgres_session:
            postgres_value = await postgres_session.scalar(text("SELECT 11"))
        async with sql_server.session() as sql_server_session:
            sql_server_value = await sql_server_session.scalar(text("SELECT 22"))

    assert postgres_value == 11
    assert sql_server_value == 22
