"""管理员用户管理：新增、角色/状态、重置密码与删除。"""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.modules.auth import _ROLES, hash_password, public_user, require_admin, validate_password, validate_username

router = APIRouter(dependencies=[Depends(require_admin)])


class UserCreateIn(BaseModel):
    username: str
    password: str
    role: str = "user"


class UserUpdateIn(BaseModel):
    role: str | None = None
    enabled: bool | None = None


class PasswordResetIn(BaseModel):
    password: str


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _validate_role(role: str) -> str:
    if role not in _ROLES:
        raise HTTPException(400, "角色只能是 user 或 admin")
    return role


async def _get_user(db, user_id: int):
    cur = await db.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "用户不存在")
    return row


async def _enabled_admin_count(db) -> int:
    cur = await db.execute("SELECT COUNT(*) AS count FROM users WHERE role='admin' AND enabled=1")
    return (await cur.fetchone())["count"]


def _removes_admin(row, role: str | None = None, enabled: bool | None = None) -> bool:
    next_role = role if role is not None else row["role"]
    next_enabled = enabled if enabled is not None else bool(row["enabled"])
    return row["role"] == "admin" and bool(row["enabled"]) and (next_role != "admin" or not next_enabled)


@router.get("/admin/users")
async def list_users(db=Depends(get_db)):
    cur = await db.execute("SELECT * FROM users ORDER BY role='admin' DESC, id ASC")
    return [public_user(row) for row in await cur.fetchall()]


@router.post("/admin/users")
async def create_user(payload: UserCreateIn, db=Depends(get_db)):
    username = validate_username(payload.username)
    password = validate_password(payload.password)
    role = _validate_role(payload.role)
    password_hash, password_salt = await asyncio.to_thread(hash_password, password)
    now = _now()
    try:
        cur = await db.execute(
            "INSERT INTO users(username,password_hash,password_salt,role,enabled,created_at,updated_at) "
            "VALUES(?,?,?,?,1,?,?)",
            (username, password_hash, password_salt, role, now, now),
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(409, "用户名已存在") from exc
        raise
    return public_user(await _get_user(db, cur.lastrowid))


@router.put("/admin/users/{user_id}")
async def update_user(user_id: int, payload: UserUpdateIn, admin=Depends(require_admin), db=Depends(get_db)):
    row = await _get_user(db, user_id)
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "无更新字段")
    role = _validate_role(fields["role"]) if "role" in fields else None
    enabled = fields.get("enabled")
    if user_id == admin["id"] and ((role is not None and role != "admin") or enabled is False):
        raise HTTPException(400, "不能禁用或降级当前登录的管理员")
    if _removes_admin(row, role, enabled) and await _enabled_admin_count(db) <= 1:
        raise HTTPException(400, "系统必须至少保留一个启用的管理员")
    updates = {}
    if role is not None:
        updates["role"] = role
    if enabled is not None:
        updates["enabled"] = int(enabled)
    updates["updated_at"] = _now()
    sets = ", ".join(f"{key}=?" for key in updates)
    await db.execute(f"UPDATE users SET {sets} WHERE id=?", (*updates.values(), user_id))
    if enabled is False:
        await db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
    await db.commit()
    return public_user(await _get_user(db, user_id))


@router.put("/admin/users/{user_id}/password")
async def reset_password(user_id: int, payload: PasswordResetIn, db=Depends(get_db)):
    await _get_user(db, user_id)
    password = validate_password(payload.password)
    password_hash, password_salt = await asyncio.to_thread(hash_password, password)
    await db.execute(
        "UPDATE users SET password_hash=?, password_salt=?, updated_at=? WHERE id=?",
        (password_hash, password_salt, _now(), user_id),
    )
    await db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
    await db.commit()
    return {"ok": True, "user_id": user_id}


@router.delete("/admin/users/{user_id}")
async def delete_user(user_id: int, admin=Depends(require_admin), db=Depends(get_db)):
    row = await _get_user(db, user_id)
    if user_id == admin["id"]:
        raise HTTPException(400, "不能删除当前登录的管理员")
    if _removes_admin(row, enabled=False) and await _enabled_admin_count(db) <= 1:
        raise HTTPException(400, "系统必须至少保留一个启用的管理员")
    await db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
    await db.execute("DELETE FROM users WHERE id=?", (user_id,))
    await db.commit()
    return {"deleted": user_id}


if __name__ == "__main__":
    sample = {"role": "admin", "enabled": 1}
    assert _removes_admin(sample, role="user")
    assert _removes_admin(sample, enabled=False)
    assert not _removes_admin(sample, role="admin", enabled=True)
    assert _validate_role("user") == "user"
    print("users.py 自检通过：角色校验与最后管理员保护判断正确。")
