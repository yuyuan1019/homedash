"""AI 工作台：OpenAI-compatible 解析、白名单校验、审计。"""
import json
import math
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_db
from app.modules import ai_executor, items, todos

router = APIRouter()
WRITE_OPS = {"item.purchase", "item.usage", "item.set_stock", "item.create", "item.update", "todo.create", "todo.complete", "todo.reopen", "todo.update", "todo.delete"}
QUERY_OPS = {"query.need_buy", "query.items", "query.open_todos", "query.overdue_todos"}
ALL_OPS = WRITE_OPS | QUERY_OPS


class ParseIn(BaseModel):
    text: str
    session_id: str | None = None


class ApplyIn(BaseModel):
    actions: list[dict]
    raw_text: str | None = None
    session_id: str | None = None
    confidence: str = "low"


def _enabled() -> bool:
    return os.getenv("AI_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def _max_actions() -> int:
    return max(1, int(os.getenv("AI_MAX_ACTIONS", "8")))


def _validate(actions: list[dict]) -> list[dict]:
    if not isinstance(actions, list) or len(actions) > _max_actions():
        raise HTTPException(400, f"actions 必须是最多 {_max_actions()} 条的数组")
    for action in actions:
        if not isinstance(action, dict) or action.get("op") not in ALL_OPS:
            raise HTTPException(400, "AI 返回了不支持的操作")
        if any(word in json.dumps(action, ensure_ascii=False).lower() for word in ("select ", "insert ", "update ", "delete ", "drop ", "sqlite", "execute_sql")):
            raise HTTPException(400, "AI 操作中不能包含 SQL 或数据库指令")
        if action["op"] in {"item.purchase", "item.usage"}:
            amount = action.get("amount")
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                amount = 0
            if not math.isfinite(amount) or amount <= 0:
                raise HTTPException(400, "购买或消耗数量必须是大于 0 的数字")
            action["amount"] = amount
        if action["op"] == "item.create" and any(key in action for key in ("amount", "quantity")):
            raise HTTPException(400, "新建物品不能携带数量；加库存必须使用 item.purchase")
        if action["op"] == "item.set_stock":
            stock = action.get("current_stock")
            try:
                stock = float(stock)
            except (TypeError, ValueError):
                stock = -1
            if not math.isfinite(stock) or stock < 0:
                raise HTTPException(400, "盘点库存必须是非负数字")
            action["current_stock"] = stock
        if action["op"] in {"item.create", "todo.create"} and not str(action.get("name") or action.get("title") or "").strip():
            raise HTTPException(400, "创建操作缺少名称或标题")
    return actions


def _confidence(value) -> str:
    if value in {"high", "medium", "low"}:
        return value
    if isinstance(value, (int, float)):
        return "high" if value >= 0.8 else "medium" if value >= 0.5 else "low"
    return "low"


async def _snapshot(db) -> dict:
    cur = await db.execute("SELECT id,name,unit,current_stock,category FROM items ORDER BY id LIMIT 80")
    item_rows = [dict(row) for row in await cur.fetchall()]
    todo_rows = await todos.list_open_todos(db, 30)
    return {"items": item_rows, "todos_open": [{key: todo[key] for key in ("id", "title", "priority", "due_date")} for todo in todo_rows]}


async def _query(db, action: dict):
    op = action["op"]
    if op == "query.need_buy":
        cur = await db.execute("SELECT * FROM items")
        output = []
        for row in await cur.fetchall():
            item = await items._item_with_prediction(db, row)
            if item["prediction"]["need_buy"]:
                output.append(item)
        return output
    if op == "query.items":
        keyword = str(action.get("name", ""))
        cur = await db.execute("SELECT * FROM items WHERE name LIKE ? ORDER BY id LIMIT 20", (f"%{keyword}%",))
        return [dict(row) for row in await cur.fetchall()]
    open_todos = await todos.list_open_todos(db, 50)
    return [todo for todo in open_todos if op != "query.overdue_todos" or todo["overdue"]]


async def _audit(db, raw_text, actions, results, ok):
    await db.execute("INSERT INTO ai_audit(raw_text,actions_json,results_json,ok) VALUES(?,?,?,?)", (raw_text, json.dumps(actions, ensure_ascii=False), json.dumps(results, ensure_ascii=False), int(ok)))
    await db.commit()


@router.post("/ai/parse")
async def parse(payload: ParseIn, db=Depends(get_db)):
    if not _enabled():
        raise HTTPException(503, "AI 工作台未开启")
    if not payload.text.strip():
        raise HTTPException(400, "请输入指令")
    base_url, api_key, model = (os.getenv("LLM_BASE_URL", "").rstrip("/"), os.getenv("LLM_API_KEY", ""), os.getenv("LLM_MODEL", ""))
    if not base_url or not api_key or not model:
        raise HTTPException(503, "AI 未配置，请检查 LLM_BASE_URL、LLM_API_KEY 和 LLM_MODEL")
    prompt = (
        "你是 HomeDash 家庭数据操作助手。只能输出一个 JSON 对象，不要 Markdown 或解释。"
        "格式严格为 {\"reply\":\"中文简短说明\",\"confidence\":\"high|medium|low\",\"actions\":[...]}. "
        "actions 必须至少有一项，且 op 只能是：item.purchase,item.usage,item.set_stock,item.create,item.update,"
        "todo.create,todo.complete,todo.reopen,todo.update,todo.delete,query.need_buy,query.items,"
        "query.open_todos,query.overdue_todos。用户说加、买、入库某物品时必须输出 item.purchase，"
        "并使用 amount 数字字段；不存在时加 create_if_missing:true。item.create 仅用于零库存新建物品，不能带数量。"
        "用户问要买什么时必须输出 {\"op\":\"query.need_buy\"}，"
        "问未完成待办时必须输出 {\"op\":\"query.open_todos\"}。禁止 SQL、表名、路径和设备控制。"
        "上下文：" + json.dumps(await _snapshot(db), ensure_ascii=False)
    )
    try:
        async with httpx.AsyncClient(timeout=float(os.getenv("LLM_TIMEOUT_SEC", "30"))) as client:
            response = await client.post(f"{base_url}/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json={"model": model, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": payload.text}]})
            response.raise_for_status()
        data = json.loads(response.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise HTTPException(502, "AI 解析失败，未写入任何数据") from exc
    actions = _validate(data.get("actions", []))
    if not actions:
        raise HTTPException(502, "AI 未返回可执行或查询动作，未写入任何数据")
    read_results = [await _query(db, action) for action in actions if action["op"] in QUERY_OPS]
    return {"ok": True, "reply": data.get("reply", "已生成操作预览。"), "confidence": _confidence(data.get("confidence")), "actions": actions, "read_results": read_results or None, "needs_disambiguation": None}


@router.post("/ai/apply")
async def apply(payload: ApplyIn, db=Depends(get_db)):
    if not _enabled():
        raise HTTPException(503, "AI 工作台未开启")
    actions = _validate(payload.actions)
    writes = [action for action in actions if action["op"] in WRITE_OPS]
    if any(action["op"] == "todo.delete" for action in writes) and payload.confidence != "high":
        raise HTTPException(400, "删除待办必须由高置信度 AI 结果确认")
    results = []
    try:
        for action in writes:
            results.append(await ai_executor.execute_action(db, action))
    except HTTPException as exc:
        await _audit(db, payload.raw_text, actions, results, False)
        raise exc
    await _audit(db, payload.raw_text, actions, results, True)
    return {"ok": True, "results": results}


@router.get("/ai/audit")
async def audit(limit: int = 50, db=Depends(get_db)):
    cur = await db.execute("SELECT * FROM ai_audit ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),))
    return [dict(row) for row in await cur.fetchall()]


if __name__ == "__main__":
    assert _validate([{"op": "item.purchase", "name": "方便面", "amount": 1}])[0]["op"] == "item.purchase"
    try:
        _validate([{"op": "execute_sql", "sql": "DELETE FROM items"}])
    except HTTPException:
        pass
    else:
        raise AssertionError("非法操作必须被拒绝")
    print("ai_workbench.py 自检通过：白名单与数值校验正确。")
