import importlib.util
import sys
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from .base import Base
from .engine import AsyncDatabase, Database


def _import_models(models_dir: str) -> None:
    """動態載入資料夾下所有 .py 檔，確保繼承 Base 的 Model 都被註冊。"""
    already_loaded = {
        getattr(m, "__file__", None)
        for m in sys.modules.values()
    }
    for path in Path(models_dir).glob("*.py"):
        if path.stem.startswith("_"):
            continue
        if str(path.resolve()) in already_loaded:
            continue
        module_name = f"_common_tools_models_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)


def create_all_tables(models_dir: str) -> None:
    """載入 models_dir 下所有 Model 並建立對應的資料表。"""
    _import_models(models_dir)
    Base.metadata.create_all(bind=Database().engine)


async def async_create_all_tables(models_dir: str) -> None:
    """載入 models_dir 下所有 Model 並以非同步方式建立對應的資料表。"""
    _import_models(models_dir)
    async with AsyncDatabase().engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@contextmanager
def db_session():
    """Provide a transactional scope around a series of operations."""
    session = Database().get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@asynccontextmanager
async def async_db_session():
    """Provide an async transactional scope around a series of operations."""
    async with AsyncDatabase().get_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
