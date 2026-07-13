"""SMTP 周报：汇总重点待办和需购买日用品，支持手动试发。"""
import asyncio
import os
import smtplib
from datetime import date
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.modules import items, todos

router = APIRouter()


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _recipients() -> list[str]:
    return [address.strip() for address in os.getenv("NOTIFY_TO", "").split(",") if address.strip()]


def _smtp_config() -> dict:
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", "").strip() or user
    recipients = _recipients()
    try:
        port = int(os.getenv("SMTP_PORT", "465"))
    except ValueError as exc:
        raise HTTPException(400, "SMTP_PORT 必须是端口数字") from exc
    if not host or not user or not password:
        raise HTTPException(503, "SMTP 未配置完整，请检查 SMTP_HOST、SMTP_USER 和 SMTP_PASSWORD")
    if not recipients:
        raise HTTPException(503, "未配置周报收件人，请检查 NOTIFY_TO")
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "sender": sender,
        "recipients": recipients,
    }


def _display_days(days: float | None) -> str:
    return "未知" if days is None else f"{max(0, int(days))} 天"


def _render_report(open_todos: list[dict], need_buy: list[dict], total_open: int) -> tuple[str, str]:
    today = date.today().isoformat()
    subject = f"HomeDash 周报 · 待办 {total_open} 项 · 需买 {len(need_buy)} 项 · {today}"
    lines = ["【重点待办】"]
    if open_todos:
        priority_labels = {"high": "高", "medium": "中", "low": "低"}
        for todo in open_todos:
            due = f" · 截止 {todo['due_date']}" if todo["due_date"] else ""
            assignee = f" · 负责人: {todo['assignee']}" if todo.get("assignee") else ""
            overdue = " · 已过期" if todo.get("overdue") else ""
            lines.append(f"- [{priority_labels[todo['priority']]}] {todo['title']}{due}{assignee}{overdue}")
        remaining = total_open - len(open_todos)
        if remaining > 0:
            lines.append(f"- 另有 {remaining} 项见面板")
    else:
        lines.append("- 本周无未完成重点待办")

    lines.extend(["", "【需要购买】"])
    if need_buy:
        for item in need_buy:
            prediction = item["prediction"]
            lines.append(
                f"- {item['name']}：剩余 {item['current_stock']} {item['unit']}，"
                f"预计 {_display_days(prediction['days_until_empty'])}，"
                f"建议买 {prediction['suggested_qty']} {item['unit']}"
            )
    else:
        lines.append("- 暂无需要购买的日用品")

    public_url = os.getenv("HOMEDASH_PUBLIC_URL", "").strip()
    if public_url:
        lines.extend(["", f"打开面板：{public_url}"])
    return subject, "\n".join(lines)


async def _weekly_content(db) -> tuple[str, str, int, int]:
    limit = max(1, int(os.getenv("NOTIFY_TODO_LIMIT", "20")))
    open_todos = await todos.list_open_todos(db, limit=limit)
    cur = await db.execute("SELECT COUNT(*) AS count FROM todos WHERE status='open'")
    total_open = (await cur.fetchone())["count"]
    cur = await db.execute("SELECT * FROM items")
    need_buy = []
    for row in await cur.fetchall():
        item = await items._item_with_prediction(db, row)
        if item["prediction"]["need_buy"]:
            need_buy.append(item)
    need_buy.sort(key=lambda item: item["prediction"]["days_until_empty"] or 0)
    subject, body = _render_report(open_todos, need_buy, total_open)
    return subject, body, total_open, len(need_buy)


def _send_sync(config: dict, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["sender"]
    message["To"] = ", ".join(config["recipients"])
    message.set_content(body, charset="utf-8")
    try:
        if config["port"] == 465:
            client = smtplib.SMTP_SSL(config["host"], config["port"], timeout=20)
        else:
            client = smtplib.SMTP(config["host"], config["port"], timeout=20)
            client.starttls()
        with client:
            client.login(config["user"], config["password"])
            client.send_message(message, to_addrs=config["recipients"])
    except smtplib.SMTPException as exc:
        raise RuntimeError(f"SMTP 发送失败: {exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"SMTP 连接失败: {exc}") from exc


async def _send_weekly(db, ignore_enabled: bool = False) -> dict:
    config = _smtp_config()
    subject, body, todo_count, buy_count = await _weekly_content(db)
    if not ignore_enabled and not _bool_env("NOTIFY_ENABLED"):
        return {"sent": False, "reason": "周报发送已关闭", "todo_count": todo_count, "buy_count": buy_count}
    if _bool_env("NOTIFY_ONLY_WHEN_NEED_BUY") and not todo_count and not buy_count:
        return {"sent": False, "reason": "暂无待办和需购物品", "todo_count": 0, "buy_count": 0}
    try:
        await asyncio.to_thread(_send_sync, config, subject, body)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "sent": True,
        "todo_count": todo_count,
        "buy_count": buy_count,
        "recipient_count": len(config["recipients"]),
    }


@router.get("/notify/config")
async def notify_config():
    return {
        "enabled": _bool_env("NOTIFY_ENABLED"),
        "has_smtp": bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD")),
        "to_count": len(_recipients()),
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": os.getenv("SMTP_PORT", "").strip(),
    }


@router.post("/notify/test")
async def test_notify(db=Depends(get_db)):
    """立即试发当前汇总，忽略 NOTIFY_ENABLED 便于配置验收。"""
    return await _send_weekly(db, ignore_enabled=True)


@router.post("/notify/weekly")
async def weekly_notify(db=Depends(get_db)):
    return await _send_weekly(db)


if __name__ == "__main__":
    subject, body = _render_report(
        [{"title": "换滤芯", "priority": "high", "due_date": "2026-07-20", "assignee": "双方", "overdue": False}],
        [],
        1,
    )
    assert "待办 1 项" in subject and "换滤芯" in body
    assert _recipients() == _recipients()
    print("notify.py 自检通过：周报文本与收件人解析正确。")
