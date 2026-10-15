# backend/src/db/database.py
from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base

DEFAULT_DB = Path(__file__).resolve().parents[2] / "jword.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DEFAULT_DB}")


def make_engine(url: str = DATABASE_URL) -> AsyncEngine:
    engine = create_async_engine(url, future=True)

    if url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.close()

    return engine


engine = make_engine()
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def create_tables(target: AsyncEngine = engine) -> None:
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """
    Request-scoped session.
    Commits on success, rolls back on exception.
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
