"""AI 白名单动作执行器：只调用领域业务函数，禁止任意 SQL。"""
from fastapi import HTTPException

from app.modules import items, todos


def _item_name(action: dict) -> str:
    """归一化物品名：LLM 可能输出 name 或 item_name，统一取 name。"""
    return str(action.get("name") or action.get("item_name") or "").strip()


async def _item_id(db, action: dict) -> int:
    item_id = action.get("item_id")
    if item_id is not None:
        await items._get_item(db, item_id)
        return item_id
    name = _item_name(action)
    if not name:
        # ponytail: 双保险，正常流程已被 ai_workbench._validate 拦截。
        raise HTTPException(400, "缺少物品标识（name/item_name/item_id）")
    cur = await db.execute("SELECT id FROM items WHERE name=?", (name,))
    row = await cur.fetchone()
    if row:
        return row["id"]
    if not action.get("create_if_missing"):
        raise HTTPException(400, f"未找到物品: {name}")
    return await items.create_item_record(db, {
        "name": name,
        "unit": action.get("unit") or "个",
        "category": action.get("category"),
        "current_stock": 0,
        "min_stock": action.get("min_stock", 1),
        "location": action.get("location"),
        "expires_at": action.get("expires_at"),
    })


async def execute_action(db, action: dict) -> dict:
    """执行已由 ai_workbench 校验过的一条写操作。"""
    op = action["op"]
    if op == "item.create":
        item_id = await items.create_item_record(db, action)
        return {"op": op, "ok": True, "item_id": item_id}
    if op == "item.purchase":
        item_id = await _item_id(db, action)
        result = await items.purchase_item_record(db, item_id, action["amount"], action.get("note"))
        return {"op": op, "ok": True, **result}
    if op == "item.usage":
        item_id = await _item_id(db, action)
        result = await items.usage_item_record(db, item_id, action["amount"], action.get("note"))
        return {"op": op, "ok": True, **result}
    if op == "item.set_stock":
        item_id = await _item_id(db, action)
        result = await items.set_item_stock(db, item_id, action["current_stock"])
        return {"op": op, "ok": True, **result}
    if op == "item.update":
        item_id = await _item_id(db, action)
        result = await items.update_item_record(db, item_id, action)
        return {"op": op, "ok": True, **result}
    if op == "todo.create":
        todo_id = await todos._create_todo(db, action)
        return {"op": op, "ok": True, "todo_id": todo_id}
    todo_id = action.get("todo_id")
    if not isinstance(todo_id, int):
        raise HTTPException(400, f"{op} 缺少 todo_id")
    if op == "todo.complete":
        await todos._set_status(db, todo_id, "done")
    elif op == "todo.reopen":
        await todos._set_status(db, todo_id, "open")
    elif op == "todo.update":
        await todos._update_todo(db, todo_id, {key: action[key] for key in todos.TodoPatch.model_fields if key in action})
    elif op == "todo.delete":
        await todos.delete_todo_record(db, todo_id)
    else:
        raise HTTPException(400, f"不支持的 AI 操作: {op}")
    return {"op": op, "ok": True, "todo_id": todo_id}


if __name__ == "__main__":
    assert _item_name({"name": "纸巾"}) == "纸巾"
    assert _item_name({"item_name": "纸巾"}) == "纸巾"
    assert _item_name({"name": " 纸巾 ", "item_name": "忽略"}) == "纸巾"
    assert _item_name({}) == ""
    print("ai_executor.py 自检通过：物品名归一化正确。")
