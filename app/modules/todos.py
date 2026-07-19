"""家庭重点待办：面板 CRUD 与 home agent 提醒接口。"""
import json
import os
import secrets
import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()

_PRIORITIES = {"high", "medium", "low"}
_STATUSES = {"open", "done"}
_REPEATS = {"none", "once", "daily", "weekly"}
_PRIORITY_SQL = "CASE priority WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END"
_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
_EXT_TO_TYPE = {ext: ctype for ctype, ext in _IMAGE_TYPES.items()}
_TODO_IMAGES_DIR = Path("data/todo_images")
_MAX_IMAGES_PER_TODO = 5
_MAX_IMAGE_SIZE = 10 * 1024 * 1024
# 串行化 todos.images 列的读-改-写：单连接 aiosqlite 只串行单条语句，
# 无法覆盖「读 images → 写文件 → 整列覆写」之间的 await 间隙。
_IMAGES_LOCK = asyncio.Lock()


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


def _decode_images(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        images = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(images, list):
        return []
    return [image for image in images if isinstance(image, dict) and image.get("id") and image.get("filename")]


def _sniff_image(data: bytes) -> str | None:
    """按文件头判定真实图片类型并返回扩展名；不信任客户端声明的 content_type。"""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _todo_dict(row) -> dict:
    item = dict(row)
    item["remind_channels"] = _decode_channels(item["remind_channels"])
    item["images"] = _decode_images(item.get("images"))
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


def _next_remind_at(remind_at: datetime, repeat: str, now: datetime) -> datetime | None:
    if repeat not in {"daily", "weekly"}:
        return None
    step = timedelta(days=1 if repeat == "daily" else 7)
    next_at = remind_at + step
    while next_at <= now:
        next_at += step
    return next_at


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


async def _safe_unlink(path: Path) -> None:
    """best-effort 删除：吞 OSError（Windows 文件被占用等），不掩盖业务异常、不阻断流程。"""
    try:
        await asyncio.to_thread(path.unlink, missing_ok=True)
    except OSError:
        pass


async def delete_todo_record(db, todo_id: int) -> None:
    # 与 upload/delete_image 共用同一把锁：整行删除也属 images 变更，
    # 串行化后并发上传不会把文件写到「正在被删的待办」上。
    async with _IMAGES_LOCK:
        todo = _todo_dict(await _get_todo(db, todo_id))
        await db.execute("DELETE FROM todos WHERE id=?", (todo_id,))
        await db.commit()
    # DB 已提交后，文件删除只能 best-effort：Windows 下文件被占用会抛 PermissionError，
    # 吞掉避免「待办已删却返回 500」；孤儿文件可接受，不应阻断删除。
    for image in todo["images"]:
        await _safe_unlink(_TODO_IMAGES_DIR / image["filename"])


async def _save_upload(upload: UploadFile, path: Path) -> str:
    """流式写盘并在写入过程中校验大小与真实图片类型，返回 sniff 出的扩展名。

    全程不把整张图缓存进内存；任意失败（含 open 处的取消、超大、非图片、IO 错）都清掉半成品文件。
    """
    file = None
    extension: str | None = None
    try:
        file = await asyncio.to_thread(path.open, "wb")
        total = 0
        while chunk := await upload.read(1024 * 1024):
            if extension is None:
                extension = _sniff_image(chunk)
                if not extension:
                    raise HTTPException(400, "仅支持 JPG、PNG、GIF 或 WebP 图片")
            total += len(chunk)
            if total > _MAX_IMAGE_SIZE:
                raise HTTPException(400, "单张图片不能超过 10MB")
            await asyncio.to_thread(file.write, chunk)
    except BaseException:
        # close 与 unlink 各自兜底：一个失败不能掩盖原始业务异常或跳过另一个。
        if file is not None:
            try:
                await asyncio.to_thread(file.close)
            except OSError:
                pass
        await _safe_unlink(path)
        raise
    try:
        await asyncio.to_thread(file.close)
    except OSError:
        pass
    if extension is None:
        # 空上传：没有数据块进入循环
        await _safe_unlink(path)
        raise HTTPException(400, "图片内容为空")
    return extension


@router.post("/todos/{todo_id}/images")
async def upload_todo_image(todo_id: int, image: UploadFile = File(...), db=Depends(get_db)):
    await _get_todo(db, todo_id)  # 404 if missing
    content_type = (image.content_type or "").lower()
    if content_type not in _IMAGE_TYPES:
        raise HTTPException(400, "仅支持 JPG、PNG、GIF 或 WebP 图片")
    await asyncio.to_thread(_TODO_IMAGES_DIR.mkdir, parents=True, exist_ok=True)
    image_id = uuid4().hex
    # 先落盘到临时名，sniff 出真实扩展名后再 rename；文件名唯一，不与并发冲突。
    tmp_path = _TODO_IMAGES_DIR / f"{todo_id}_{image_id}.upload"
    extension = await _save_upload(image, tmp_path)
    final_filename = f"{todo_id}_{image_id}{extension}"
    final_path = _TODO_IMAGES_DIR / final_filename
    committed = False
    try:
        # rename 放进 try：Windows 下被占用等失败要回收 tmp_path，并返回干净的 400 而非 500。
        if tmp_path != final_path:
            try:
                await asyncio.to_thread(tmp_path.rename, final_path)
            except OSError:
                await _safe_unlink(tmp_path)
                raise HTTPException(400, "图片保存失败，请重试")
        # 锁内做 images 列的读-改-写，避免并发覆写丢图。
        async with _IMAGES_LOCK:
            todo = _todo_dict(await _get_todo(db, todo_id))
            if len(todo["images"]) >= _MAX_IMAGES_PER_TODO:
                raise HTTPException(400, f"每个待办最多上传 {_MAX_IMAGES_PER_TODO} 张图片")
            images = [*todo["images"], {"id": image_id, "filename": final_filename, "content_type": _EXT_TO_TYPE[extension]}]
            await db.execute("UPDATE todos SET images=?, updated_at=? WHERE id=?", (json.dumps(images, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), todo_id))
            await db.commit()
            committed = True
    except BaseException:
        # 仅在尚未提交时回收文件：commit 成功后即便客户端断连(CancelledError)也不删，
        # 否则会删掉 DB 已引用的文件造成悬空 404。
        if not committed:
            await _safe_unlink(final_path)
        raise
    return _todo_dict(await _get_todo(db, todo_id))


@router.get("/todos/{todo_id}/images/{image_id}")
async def get_todo_image(todo_id: int, image_id: str, db=Depends(get_db)):
    cur = await db.execute("SELECT images FROM todos WHERE id=?", (todo_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "待办不存在")
    image = next((item for item in _decode_images(row["images"]) if item["id"] == image_id), None)
    if not image:
        raise HTTPException(404, "图片不存在")
    path = _TODO_IMAGES_DIR / image["filename"]
    # 一次性读出全部字节再构造响应：避免 FileResponse「先发 200 再开文件」与并发删除
    # 之间的 TOCTOU（200 空 body）；read_bytes 要么完整读出要么 FileNotFoundError。
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError:
        raise HTTPException(404, "图片文件不存在")
    except OSError:
        raise HTTPException(500, "读取图片失败")
    return Response(
        content=data,
        media_type=image.get("content_type") or "application/octet-stream",
        # image_id 是 uuid、永不复用：删除后该 URL 不再被任何卡片引用，短缓存安全且能省去重复全量读。
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


@router.delete("/todos/{todo_id}/images/{image_id}")
async def delete_todo_image(todo_id: int, image_id: str, db=Depends(get_db)):
    async with _IMAGES_LOCK:
        todo = _todo_dict(await _get_todo(db, todo_id))
        image = next((item for item in todo["images"] if item["id"] == image_id), None)
        if not image:
            raise HTTPException(404, "图片不存在")
        images = [item for item in todo["images"] if item["id"] != image_id]
        await db.execute("UPDATE todos SET images=?, updated_at=? WHERE id=?", (json.dumps(images, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), todo_id))
        await db.commit()
        filename = image["filename"]
        updated = _todo_dict(await _get_todo(db, todo_id))
    # DB 已提交，文件删除 best-effort（同 delete_todo_record）。
    await _safe_unlink(_TODO_IMAGES_DIR / filename)
    return updated


async def _verify_agent_token(
    x_homedash_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    from app.modules.setup import _agent_token
    token = _agent_token()
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
    next_remind_at = _next_remind_at(remind_at, repeat, _now())
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
    assert _decode_images('[{"id":"image-1","filename":"test.png"}]')[0]["id"] == "image-1"
    assert _decode_images("invalid") == []
    assert _sniff_image(b"\xff\xd8\xff\xe0") == ".jpg"
    assert _sniff_image(b"\x89PNG\r\n\x1a\n") == ".png"
    assert _sniff_image(b"GIF89a") == ".gif"
    assert _sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ".webp"
    assert _sniff_image(b"<html><script>x</script>") is None
    assert _EXT_TO_TYPE[".png"] == "image/png"
    sample = {
        "title": "换净水器滤芯",
        "priority": "high",
        "due_date": "2026-07-31",
        "assignee": "双方",
        "note": "柜下 3M",
    }
    assert "高优先级" in _message(sample)
    assert _parse_datetime("2026-07-20T09:00:00", "now").hour == 9
    assert _next_remind_at(datetime(2026, 7, 1, 9), "daily", datetime(2026, 7, 3, 10)) == datetime(2026, 7, 4, 9)
    print("todos.py 自检通过：提醒/图片 JSON、消息模板与时间解析正确。")
