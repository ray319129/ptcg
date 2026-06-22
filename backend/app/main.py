"""FastAPI 應用組裝進入點。

啟動：  uvicorn app.main:app --reload
文件：  http://localhost:8000/docs
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth, cards, match, packs, parser, portfolio
from app.db import engine, redis_pool

logging.basicConfig(level=logging.INFO)


async def _lifespan(app: FastAPI):
    # 啟動：可在此做連線預熱 / 健檢；關閉：釋放連線池。
    yield
    await engine.dispose()
    await redis_pool.aclose()


app = FastAPI(
    title="卡匣 PTCG Asset API",
    version="0.1.0",
    lifespan=_lifespan,
)

# 開發期允許前端 PWA 跨來源呼叫；生產請收斂 allow_origins。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(parser.router)
app.include_router(packs.router)
app.include_router(portfolio.router)
app.include_router(cards.router)
app.include_router(match.router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
