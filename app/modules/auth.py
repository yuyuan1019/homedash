"""面板登录与长期会话：密码散列、首个管理员、登录/退出。"""
import asyncio
import base64
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()

COOKIE_NAME = "homedash_session"
SESSION_DAYS = 180
RENEW_AFTER_DAYS = 7
_USERNAME_RE = re.compile(r"^[\w.\-\u4e00-\u9fff]+$", re.UNICODE)
_ROLES = {"user", "admin"}


class CredentialsIn(BaseModel):
    username: str
    password: str


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def validate_username(value: str) -> str:
    username = value.strip()
    if not 2 <= len(username) <= 32:
        raise HTTPException(400, "用户名长度必须为 2 到 32 个字符")
    if not _USERNAME_RE.fullmatch(username):
        raise HTTPException(400, "用户名只能包含中文、字母、数字、下划线、点或短横线")
    return username


def validate_password(value: str) -> str:
    if not 8 <= len(value) <= 128:
        raise HTTPException(400, "密码长度必须为 8 到 128 个字符")
    return value


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return base64.b64encode(digest).decode("ascii"), base64.b64encode(salt).decode("ascii")


def verify_password(password: str, encoded_hash: str, encoded_salt: str) -> bool:
    try:
        salt = base64.b64decode(encoded_salt, validate=True)
        actual_hash, _ = hash_password(password, salt)
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(actual_hash, encoded_hash)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_login_at": row["last_login_at"],
    }


def set_session_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


async def create_session(db, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    await db.execute(
        "INSERT INTO auth_sessions(user_id,token_hash,created_at,last_seen_at,expires_at) VALUES(?,?,?,?,?)",
        (user_id, _token_hash(token), _iso(now), _iso(now), _iso(now + timedelta(days=SESSION_DAYS))),
    )
    await db.commit()
    return token


async def session_user(db, token: str) -> tuple[dict | None, bool]:
    """返回会话用户与是否需要续期；数据库只匹配 token 摘要。"""
    if not token:
        return None, False
    now = _now()
    cur = await db.execute(
        "SELECT u.*, s.id AS session_id, s.last_seen_at, s.expires_at "
        "FROM auth_sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1",
        (_token_hash(token), _iso(now)),
    )
    row = await cur.fetchone()
    if not row:
        return None, False
    try:
        last_seen = datetime.fromisoformat(row["last_seen_at"])
    except (TypeError, ValueError):
        last_seen = datetime.min
    renew = now - last_seen >= timedelta(days=RENEW_AFTER_DAYS)
    if renew:
        await db.execute(
            "UPDATE auth_sessions SET last_seen_at=?, expires_at=? WHERE id=?",
            (_iso(now), _iso(now + timedelta(days=SESSION_DAYS)), row["session_id"]),
        )
        await db.commit()
    return public_user(row), renew


def current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "请先登录")
    return user


def require_admin(request: Request) -> dict:
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "当前账户无权执行此操作")
    return user


@router.get("/auth/bootstrap-status")
async def bootstrap_status(db=Depends(get_db)):
    cur = await db.execute("SELECT COUNT(*) AS count FROM users")
    return {"required": (await cur.fetchone())["count"] == 0}


@router.post("/auth/bootstrap-admin")
async def bootstrap_admin(payload: CredentialsIn, response: Response, request: Request, db=Depends(get_db)):
    username = validate_username(payload.username)
    password = validate_password(payload.password)
    password_hash, password_salt = await asyncio.to_thread(hash_password, password)
    try:
        await db.execute("BEGIN IMMEDIATE")
        cur = await db.execute("SELECT COUNT(*) AS count FROM users")
        if (await cur.fetchone())["count"]:
            await db.rollback()
            raise HTTPException(409, "系统已经完成管理员初始化")
        now = _iso(_now())
        cur = await db.execute(
            "INSERT INTO users(username,password_hash,password_salt,role,enabled,created_at,updated_at,last_login_at) "
            "VALUES(?,?,?,?,1,?,?,?)",
            (username, password_hash, password_salt, "admin", now, now, now),
        )
        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise
    token = await create_session(db, cur.lastrowid)
    set_session_cookie(response, token, request)
    cur = await db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,))
    return public_user(await cur.fetchone())


@router.post("/auth/login")
async def login(payload: CredentialsIn, response: Response, request: Request, db=Depends(get_db)):
    username = payload.username.strip()
    cur = await db.execute("SELECT * FROM users WHERE username=? AND enabled=1", (username,))
    row = await cur.fetchone()
    valid = bool(row) and await asyncio.to_thread(
        verify_password, payload.password, row["password_hash"], row["password_salt"]
    )
    if not valid:
        raise HTTPException(401, "用户名或密码错误")
    now = _iso(_now())
    await db.execute("UPDATE users SET last_login_at=?, updated_at=? WHERE id=?", (now, now, row["id"]))
    await db.commit()
    token = await create_session(db, row["id"])
    set_session_cookie(response, token, request)
    cur = await db.execute("SELECT * FROM users WHERE id=?", (row["id"],))
    return public_user(await cur.fetchone())


@router.post("/auth/logout")
async def logout(request: Request, response: Response, db=Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        await db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (_token_hash(token),))
        await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
    return {"ok": True}


@router.get("/auth/me")
async def me(user=Depends(current_user)):
    return user


if __name__ == "__main__":
    password_hash, password_salt = hash_password("自检密码-123")
    assert verify_password("自检密码-123", password_hash, password_salt)
    assert not verify_password("错误密码", password_hash, password_salt)
    assert _token_hash("session") != "session"
    assert validate_username("家庭管理员") == "家庭管理员"
    assert _ROLES == {"user", "admin"}
    print("auth.py 自检通过：密码散列、会话摘要与用户名校验正确。")
