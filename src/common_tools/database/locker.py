from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import text

from .engine import AsyncDatabase, Database


@contextmanager
def pg_advisory_lock(lock_id: int):
    """PostgreSQL advisory lock context manager.

    嘗試取得 advisory lock，若成功則 yield True，否則 yield False。
    鎖在離開 context 時自動釋放。
    """
    db = Database()
    if db.engine.dialect.name != "postgresql":
        raise RuntimeError("pg_advisory_lock 僅支援 PostgreSQL")

    session = db.get_session()
    acquired = False
    try:
        acquired = session.execute(
            text("SELECT pg_try_advisory_lock(:id)"),
            {"id": lock_id},
        ).scalar()
        session.commit()
        yield acquired
    finally:
        if acquired:
            try:
                session.execute(
                    text("SELECT pg_advisory_unlock(:id)"),
                    {"id": lock_id},
                )
                session.commit()
            except Exception:
                session.rollback()
        session.close()


@asynccontextmanager
async def async_pg_advisory_lock(lock_id: int):
    """PostgreSQL async advisory lock context manager.

    嘗試取得 advisory lock，若成功則 yield True，否則 yield False。
    鎖在離開 context 時自動釋放。
    """
    db = AsyncDatabase()
    if db.engine.dialect.name != "postgresql":
        raise RuntimeError("async_pg_advisory_lock 僅支援 PostgreSQL")

    async with db.get_session() as session:
        acquired = False
        try:
            acquired = (await session.execute(
                text("SELECT pg_try_advisory_lock(:id)"),
                {"id": lock_id},
            )).scalar()
            await session.commit()
            yield acquired
        finally:
            if acquired:
                try:
                    await session.execute(
                        text("SELECT pg_advisory_unlock(:id)"),
                        {"id": lock_id},
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
