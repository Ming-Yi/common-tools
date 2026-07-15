from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import PostgresConfig, SqlServerConfig
from .exceptions import DatabaseConnectionError, DatabaseNotStartedError

__all__ = ["AsyncDatabase"]


class AsyncDatabase:
    """Owns one async database engine and its session lifecycle."""

    def __init__(self, config: PostgresConfig | SqlServerConfig) -> None:
        self.config = config
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def started(self) -> bool:
        return self._engine is not None

    async def start(self) -> Self:
        if self.started:
            return self

        engine: AsyncEngine | None = None
        try:
            engine = create_async_engine(
                self.config.url,
                pool_size=self.config.pool_size,
                max_overflow=self.config.max_overflow,
                pool_timeout=self.config.pool_timeout,
                pool_recycle=self.config.pool_recycle,
                pool_pre_ping=self.config.pool_pre_ping,
            )
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as error:
            if engine is not None:
                await engine.dispose()
            raise DatabaseConnectionError(f"{self._backend_name} connection unavailable") from error

        self._engine = engine
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)
        return self

    @property
    def _backend_name(self) -> str:
        if isinstance(self.config, PostgresConfig):
            return "PostgreSQL"
        return "SQL Server"

    async def check_connection(self) -> None:
        """Verify that a started database can currently serve a connection."""
        engine = self._engine
        if engine is None:
            raise DatabaseNotStartedError("database is not started")

        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as error:
            raise DatabaseConnectionError(f"{self._backend_name} connection unavailable") from error

    async def close(self) -> None:
        engine = self._engine
        self._engine = None
        self._session_factory = None
        if engine is not None:
            await engine.dispose()

    async def __aenter__(self) -> Self:
        return await self.start()

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
    ) -> None:
        await self.close()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        session_factory = self._session_factory
        if session_factory is None:
            raise DatabaseNotStartedError("database is not started")

        async with session_factory.begin() as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        session_factory = self._session_factory
        if session_factory is None:
            raise DatabaseNotStartedError("database is not started")

        async with session_factory.begin() as session:
            yield session
