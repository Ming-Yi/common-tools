from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .base import DatabaseConnectionError
from ..base_classes import SingletonMeta
from ..logger import Logging


class Database(metaclass=SingletonMeta):

    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self.DatabaseURL = None

    def initialise(self, database_url: str) -> "Database":
        if self.engine is not None:
            return self

        self.DatabaseURL = database_url
        self.engine = create_engine(self.DatabaseURL, future=True)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.check_database_status()

        # 設定資料庫時區為 UTC
        self.set_timezone()
        return self

    def check_database_status(self):
        try:
            session = self.get_session()
            session.execute(text("SELECT 1"))
            session.commit()
        except Exception:
            raise DatabaseConnectionError("Database connection unavailable")

    def set_timezone(self):
        """
        設定資料庫時區為 UTC
        """
        try:
            session = self.SessionLocal()
            try:
                session.execute(text("SET timezone = 'UTC'"))
                session.commit()
            except Exception as e:
                session.rollback()
                Logging.error(f"設定資料庫時區失敗：{e}")
            finally:
                session.close()
        except Exception as e:
            Logging.error(f"設定資料庫時區時發生錯誤：{e}")

    def get_session(self):
        if self.SessionLocal is None:
            raise RuntimeError("Database not initialized. Call initialise() first.")
        return self.SessionLocal()


class AsyncDatabase(metaclass=SingletonMeta):

    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self.DatabaseURL = None

    async def initialise(self, database_url: str) -> "AsyncDatabase":
        if self.engine is not None:
            return self

        self.DatabaseURL = database_url
        self.engine = create_async_engine(self.DatabaseURL, future=True)
        self.SessionLocal = sessionmaker(self.engine, class_=AsyncSession, autoflush=False, expire_on_commit=False)
        await self.check_database_status()

        # 設定資料庫時區為 UTC
        await self.set_timezone()
        return self

    async def check_database_status(self):
        try:
            async with self.SessionLocal() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            raise DatabaseConnectionError("Database connection unavailable")

    async def set_timezone(self):
        """
        設定資料庫時區為 UTC
        """
        try:
            async with self.SessionLocal() as session:
                try:
                    await session.execute(text("SET timezone = 'UTC'"))
                    await session.commit()
                except Exception as e:
                    await session.rollback()
                    Logging.error(f"設定資料庫時區失敗：{e}")
        except Exception as e:
            Logging.error(f"設定資料庫時區時發生錯誤：{e}")

    def get_session(self) -> AsyncSession:
        if self.SessionLocal is None:
            raise RuntimeError("AsyncDatabase not initialized. Call initialise() first.")
        return self.SessionLocal()
