"""家庭重点待办：面板 CRUD 与 home agent 提醒接口。"""
import json
import os
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()

_PRIORITIES = {"high", "medium", "low"}
_STATUSES = {"open", "done"}
_REPEATS = {"none", "once", "daily", "weekly"}
_PRIORITY_SQL = "CASE priority WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END"


class TodoIn(BaseModel):
    title: str
    note: str | None = None
    priority: str = "medium"
    due_date: str | None = None
    assignee: str | None = None
    remind_at: str | None = None
    remind_channels: list[str] | None = None
    remind_repeat: str | None = "none"
    external_ref: str | None = None


class TodoPatch(BaseModel):
    title: str | None = None
    note: str | None = None
    priority: str | None = None
    due_date: str | None = None
    assignee: str | None = None
    remind_at: str | None = None
    remind_channels: list[str] | None = None
    remind_repeat: str | None = None
    external_ref: str | None = None


class RemindFiredIn(BaseModel):
    channel: str | None = None
    delivered_at: str | None = None
    external_ref: str | None = None


class ReminderPatch(BaseModel):
    remind_at: str | None = None
    remind_channels: list[str] | None = None
    remind_repeat: str | None = None
    external_ref: str | None = None


def _now() -> datetime:
    try:
        return datetime.now(ZoneInfo(os.getenv("NOTIFY_TZ", "Asia/Shanghai"))).replace(tzinfo=None)
    except (ValueError, KeyError):
        return datetime.now()


def _parse_datetime(value: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, f"{field} 必须是 ISO 时间") from exc


def _validate_due_date(value: str | None) -> None:
    if value is None:
        return
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, "due_date 必须是 YYYY-MM-DD") from exc


def _validate_fields(data: dict) -> None:
    title = data.get("title")
    if "title" in data and (title is None or not title.strip()):
        raise HTTPException(400, "标题不能为空")
    if data.get("priority") is not None and data["priority"] not in _PRIORITIES:
        raise HTTPException(400, "priority 只能是 high、medium 或 low")
    if data.get("remind_repeat") is not None and data["remind_repeat"] not in _REPEATS:
        raise HTTPException(400, "remind_repeat 只能是 none、once、daily 或 weekly")
    _validate_due_date(data.get("due_date"))
    if data.get("remind_at") is not None:
        _parse_datetime(data["remind_at"], "remind_at")


def _decode_channels(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        channels = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(channel) for channel in channels] if isinstance(channels, list) else []


def _todo_dict(row) -> dict:
    item = dict(row)
    item["remind_channels"] = _decode_channels(item["remind_channels"])
    item["overdue"] = (
        item["status"] == "open"
        and bool(item["due_date"])
        and item["due_date"] < date.today().isoformat()
    )
    return item


def _message(todo: dict) -> str:
    priority = {"high": "高", "medium": "中", "low": "低"}[todo["priority"]]
    details = [f"截止 {todo['due_date'] or '未设置'}", f"{priority}优先级"]
    if todo.get("assignee"):
        details.append(todo["assignee"])
    message = f"【HomeDash 待办】{todo['title']}\n" + " · ".join(details)
    return f"{message}\n{todo['note']}" if todo.get("note") else message


async def _get_todo(db, todo_id: int):
    cur = await db.execute("SELECT * FROM todos WHERE id=?", (todo_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "待办不存在")
    return row


async def list_open_todos(db, limit: int = 20) -> list[dict]:
    """供周报模块复用的未完成待办查询。"""
    cur = await db.execute(
        f"SELECT * FROM todos WHERE status='open' "
        f"ORDER BY {_PRIORITY_SQL} DESC, due_date IS NULL, due_date ASC, id DESC LIMIT ?",
        (limit,),
    )
    return [_todo_dict(row) for row in await cur.fetchall()]


async def _create_todo(db, data: dict) -> int:
    _validate_fields(data)
    values = {
        "title": data["title"].strip(),
        "note": data.get("note"),
        "priority": data.get("priority", "medium"),
        "due_date": data.get("due_date"),
        "assignee": data.get("assignee"),
        "remind_at": data.get("remind_at"),
        "remind_channels": json.dumps(data.get("remind_channels") or [], ensure_ascii=False),
        "remind_repeat": data.get("remind_repeat") or "none",
        "external_ref": data.get("external_ref"),
    }
    cur = await db.execute(
        "INSERT INTO todos(title,note,priority,due_date,assignee,remind_at,remind_channels,"
        "remind_repeat,external_ref) VALUES(:title,:note,:priority,:due_date,:assignee,:remind_at,"
        ":remind_channels,:remind_repeat,:external_ref)",
        values,
    )
    await db.commit()
    return cur.lastrowid


async def _update_todo(db, todo_id: int, data: dict) -> dict:
    await _get_todo(db, todo_id)
    _validate_fields(data)
    fields = dict(data)
    if not fields:
        raise HTTPException(400, "无更新字段")
    if "title" in fields:
        fields["title"] = fields["title"].strip()
    if "remind_channels" in fields:
        fields["remind_channels"] = json.dumps(fields["remind_channels"], ensure_ascii=False)
    fields["updated_at"] = datetime.now().isoformat(timespec="seconds")
    sets = ", ".join(f"{key}=?" for key in fields)
    await db.execute(f"UPDATE todos SET {sets} WHERE id=?", (*fields.values(), todo_id))
    await db.commit()
    return _todo_dict(await _get_todo(db, todo_id))


async def _set_status(db, todo_id: int, status: str) -> dict:
    await _get_todo(db, todo_id)
    completed_at = datetime.now().isoformat(timespec="seconds") if status == "done" else None
    await db.execute(
        "UPDATE todos SET status=?, completed_at=?, updated_at=? WHERE id=?",
        (status, completed_at, datetime.now().isoformat(timespec="seconds"), todo_id),
    )
    await db.commit()
    return _todo_dict(await _get_todo(db, todo_id))


async def delete_todo_record(db, todo_id: int) -> None:
    await _get_todo(db, todo_id)
    await db.execute("DELETE FROM todos WHERE id=?", (todo_id,))
    await db.commit()


async def _verify_agent_token(
    x_homedash_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    token = os.getenv("AGENT_API_TOKEN", "")
    if not token:
        return
    bearer = authorization.removeprefix("Bearer ") if authorization else ""
    if not (secrets.compare_digest(x_homedash_token or "", token) or secrets.compare_digest(bearer, token)):
        raise HTTPException(401, "agent 接口鉴权失败")


@router.get("/todos")
async def list_todos(status: str = "open", db=Depends(get_db)):
    if status not in {"open", "done", "all"}:
        raise HTTPException(400, "status 只能是 open、done 或 all")
    where = "" if status == "all" else "WHERE status=?"
    params = () if status == "all" else (status,)
    cur = await db.execute(
        f"SELECT * FROM todos {where} ORDER BY "
        f"CASE WHEN status='open' THEN 0 ELSE 1 END, {_PRIORITY_SQL} DESC, "
        "due_date IS NULL, due_date ASC, id DESC",
        params,
    )
    return [_todo_dict(row) for row in await cur.fetchall()]


@router.post("/todos")
async def create_todo(payload: TodoIn, db=Depends(get_db)):
    todo_id = await _create_todo(db, payload.model_dump())
    return _todo_dict(await _get_todo(db, todo_id))


@router.get("/todos/summary")
async def todo_summary(db=Depends(get_db)):
    open_todos = await list_open_todos(db, limit=5)
    cur = await db.execute(
        "SELECT COUNT(*) AS count FROM todos WHERE status='open' AND due_date < ?",
        (date.today().isoformat(),),
    )
    row = await cur.fetchone()
    cur = await db.execute("SELECT COUNT(*) AS count FROM todos WHERE status='open'")
    open_count = (await cur.fetchone())["count"]
    return {"open_count": open_count, "overdue_count": row["count"], "top": open_todos}


@router.get("/todos/{todo_id}")
async def get_todo(todo_id: int, db=Depends(get_db)):
    return _todo_dict(await _get_todo(db, todo_id))


@router.put("/todos/{todo_id}")
async def update_todo(todo_id: int, payload: TodoPatch, db=Depends(get_db)):
    return await _update_todo(db, todo_id, payload.model_dump(exclude_unset=True))


@router.post("/todos/{todo_id}/done")
async def complete_todo(todo_id: int, db=Depends(get_db)):
    return await _set_status(db, todo_id, "done")


@router.post("/todos/{todo_id}/reopen")
async def reopen_todo(todo_id: int, db=Depends(get_db)):
    return await _set_status(db, todo_id, "open")


@router.delete("/todos/{todo_id}")
async def delete_todo(todo_id: int, db=Depends(get_db)):
    await delete_todo_record(db, todo_id)
    return {"deleted": todo_id}


@router.get("/agent/todos/open", dependencies=[Depends(_verify_agent_token)])
async def agent_open_todos(priority: str | None = None, db=Depends(get_db)):
    if priority is not None and priority not in _PRIORITIES:
        raise HTTPException(400, "priority 只能是 high、medium 或 low")
    todos = await list_open_todos(db, limit=200)
    if priority:
        todos = [todo for todo in todos if todo["priority"] == priority]
    return {"items": todos}


@router.get("/agent/todos/due", dependencies=[Depends(_verify_agent_token)])
async def due_todos(
    now: str | None = None,
    within_minutes: int = 15,
    channel: str | None = None,
    db=Depends(get_db),
):
    if not 1 <= within_minutes <= 24 * 60:
        raise HTTPException(400, "within_minutes 必须在 1 到 1440 之间")
    server_time = _parse_datetime(now, "now") if now else _now()
    cutoff = server_time + timedelta(minutes=within_minutes)
    cur = await db.execute(
        "SELECT * FROM todos WHERE status='open' AND remind_at IS NOT NULL AND remind_at <= ? "
        f"ORDER BY {_PRIORITY_SQL} DESC, remind_at ASC, id DESC",
        (cutoff.isoformat(timespec="seconds"),),
    )
    items = []
    for row in await cur.fetchall():
        todo = _todo_dict(row)
        if channel and channel not in todo["remind_channels"]:
            continue
        todo["message"] = _message(todo)
        items.append(todo)
    return {"server_time": server_time.isoformat(timespec="seconds"), "items": items}


@router.post("/agent/todos", dependencies=[Depends(_verify_agent_token)])
async def agent_create_todo(payload: TodoIn, db=Depends(get_db)):
    todo_id = await _create_todo(db, payload.model_dump())
    return _todo_dict(await _get_todo(db, todo_id))


@router.post("/agent/todos/{todo_id}/done", dependencies=[Depends(_verify_agent_token)])
async def agent_complete_todo(todo_id: int, db=Depends(get_db)):
    return await _set_status(db, todo_id, "done")


@router.put("/agent/todos/{todo_id}/remind", dependencies=[Depends(_verify_agent_token)])
async def update_reminder(todo_id: int, payload: ReminderPatch, db=Depends(get_db)):
    return await _update_todo(db, todo_id, payload.model_dump(exclude_unset=True))


@router.post("/agent/todos/{todo_id}/remind-fired", dependencies=[Depends(_verify_agent_token)])
async def remind_fired(todo_id: int, payload: RemindFiredIn, db=Depends(get_db)):
    todo = _todo_dict(await _get_todo(db, todo_id))
    if todo["status"] != "open" or not todo["remind_at"]:
        raise HTTPException(400, "该待办当前无需标记提醒")
    if payload.channel and todo["remind_channels"] and payload.channel not in todo["remind_channels"]:
        raise HTTPException(400, "提醒频道不匹配")
    remind_at = _parse_datetime(todo["remind_at"], "remind_at")
    repeat = todo["remind_repeat"] or "none"
    if repeat == "daily":
        next_remind_at = remind_at + timedelta(days=1)
    elif repeat == "weekly":
        next_remind_at = remind_at + timedelta(days=7)
    else:
        next_remind_at = None
    result = await _update_todo(
        db,
        todo_id,
        {
            "remind_at": next_remind_at.isoformat(timespec="seconds") if next_remind_at else None,
            "external_ref": payload.external_ref if payload.external_ref is not None else todo["external_ref"],
        },
    )
    return result


if __name__ == "__main__":
    assert _decode_channels('["qq", "wechat"]') == ["qq", "wechat"]
    assert _decode_channels("invalid") == []
    sample = {
        "title": "换净水器滤芯",
        "priority": "high",
        "due_date": "2026-07-31",
        "assignee": "双方",
        "note": "柜下 3M",
    }
    assert "高优先级" in _message(sample)
    assert _parse_datetime("2026-07-20T09:00:00", "now").hour == 9
    print("todos.py 自检通过：提醒 JSON、消息模板与时间解析正确。")
