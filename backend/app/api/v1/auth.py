"""/api/v1/auth —— 簡易帳號註冊/登入（個人用）。

密碼用 pbkdf2_hmac 雜湊（標準函式庫，免額外套件）。登入成功回傳 user_id，
前端存於 localStorage 並用於後續 API。user_id 為 UUID（不可猜），密碼把關註冊/登入。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

logger = logging.getLogger("ptcg.auth")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_ITER = 120_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:  # noqa: BLE001
        return False


class AuthRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=4, max_length=128)


class AuthResult(BaseModel):
    user_id: str
    username: str


@router.post("/register", response_model=AuthResult, status_code=status.HTTP_201_CREATED)
async def register(payload: AuthRequest, session: AsyncSession = Depends(get_db)) -> AuthResult:
    uname = payload.username.strip()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO users (username, password_hash) "
                    "VALUES (:u, :p) RETURNING user_id"
                ),
                {"u": uname, "p": hash_password(payload.password)},
            )
        ).first()
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "帳號已存在")
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("register 失敗")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "註冊失敗，請稍後再試")
    return AuthResult(user_id=str(row[0]), username=uname)


@router.post("/login", response_model=AuthResult)
async def login(payload: AuthRequest, session: AsyncSession = Depends(get_db)) -> AuthResult:
    try:
        row = (
            await session.execute(
                text("SELECT user_id, password_hash FROM users WHERE username = :u"),
                {"u": payload.username.strip()},
            )
        ).first()
    except SQLAlchemyError:
        logger.exception("login 失敗")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "登入失敗，請稍後再試")
    if row is None or not verify_password(payload.password, row[1]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "帳號或密碼錯誤")
    return AuthResult(user_id=str(row[0]), username=payload.username.strip())
