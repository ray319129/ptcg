"""資料庫與快取連線管理。

- PostgreSQL 使用 SQLAlchemy 2.0 async (asyncpg driver)。
- Redis 用於每日市場價快取與掃描串流去重。
- 透過 FastAPI 依賴注入提供 session / redis client，確保連線正確釋放。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---- 連線字串 ----------------------------------------------------------------
# 生產環境務必由環境變數注入，不在程式碼硬編密碼。
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://ptcg:ptcg@localhost:5432/ptcg",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# pool_pre_ping 避免拿到被資料庫端關閉的死連線；pool_size 依機器調整。
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Redis 連線池（解碼為 str，方便直接存讀 JSON 字串）。
redis_pool = aioredis.ConnectionPool.from_url(
    REDIS_URL, decode_responses=True, max_connections=50
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依賴：產出一個請求範圍的 DB session，結束時保證關閉。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            # 任何例外都先 rollback，避免污染連線池中的下一個請求。
            await session.rollback()
            raise


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI 依賴：產出 Redis client。"""
    client = aioredis.Redis(connection_pool=redis_pool)
    try:
        yield client
    finally:
        # 不關閉底層 pool，只釋放此 client 物件即可。
        await client.aclose()


@asynccontextmanager
async def lifespan_db():
    """App 啟動 / 關閉時的資源生命週期掛勾。"""
    try:
        yield
    finally:
        await engine.dispose()
        await redis_pool.aclose()
