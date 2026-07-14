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

from .config import PostgresConfig
from .exceptions import DatabaseConnectionError, DatabaseNotStartedError


class AsyncDatabase:
    """Owns one async PostgreSQL engine and its session lifecycle."""

    def __init__(self, config: PostgresConfig) -> None:
        self.config = config
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def started(self) -> bool:
        return self._engine is not None

    async def start(self) -> Self:
        if self.started:
            return self

        engine = create_async_engine(
            self.config.url,
            pool_size=self.config.pool_size,
            max_overflow=self.config.max_overflow,
            pool_timeout=self.config.pool_timeout,
            pool_recycle=self.config.pool_recycle,
            pool_pre_ping=self.config.pool_pre_ping,
            connect_args={"server_settings": {"timezone": "UTC"}},
        )
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                timezone = await connection.scalar(text("SHOW timezone"))
                if timezone != "UTC":
                    raise RuntimeError("PostgreSQL connection timezone is not UTC")
        except Exception as error:
            await engine.dispose()
            raise DatabaseConnectionError("PostgreSQL connection unavailable") from error

        self._engine = engine
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)
        return self

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

        async with session_factory() as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        session_factory = self._session_factory
        if session_factory is None:
            raise DatabaseNotStartedError("database is not started")

        async with session_factory.begin() as session:
            yield session
