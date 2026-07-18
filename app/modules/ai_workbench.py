"""AI 工作台：OpenAI-compatible 解析、白名单校验、审计。"""
import json
import math
import os
import time
from typing import Any

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


class ChatIn(BaseModel):
    text: str
    session_id: str | None = None
    history: list[dict] | None = None


class CategoryIn(BaseModel):
    name: str


def _llm_file_config() -> dict | None:
    path = "data/llm_config.json"
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _llm_config_value(key: str, default: Any = "") -> Any:
    """读取 LLM 配置：环境变量优先，其次 data/llm_config.json。"""
    env_map = {
        "base_url": "LLM_BASE_URL",
        "api_key": "LLM_API_KEY",
        "model": "LLM_MODEL",
        "timeout_sec": "LLM_TIMEOUT_SEC",
        "enabled": "AI_ENABLED",
        "confirm_required": "AI_CONFIRM_REQUIRED",
        "max_actions": "AI_MAX_ACTIONS",
    }
    env_name = env_map.get(key)
    if env_name:
        env_val = os.getenv(env_name)
        if env_val is not None and env_val != "":
            return env_val
    cfg = _llm_file_config()
    if cfg and key in cfg and cfg[key] is not None and cfg[key] != "":
        return cfg[key]
    return default


def _brave_config() -> dict | None:
    """读取 Brave Search 配置：环境变量 BRAVE_API_KEY 优先，其次 data/brave_config.json。"""
    env_key = os.getenv("BRAVE_API_KEY", "").strip()
    if env_key:
        return {"api_key": env_key}
    path = "data/brave_config.json"
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _brave_api_key() -> str | None:
    cfg = _brave_config()
    if cfg and cfg.get("api_key"):
        return str(cfg["api_key"]).strip()
    return None


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

BRAVE_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "brave_web_search",
        "description": "使用 Brave Search 搜索互联网获取实时信息，如天气、新闻、百科知识、最新趋势等。当用户询问需要实时数据或超出你知识范围的问题时使用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，使用中文或英文",
                }
            },
            "required": ["query"],
        },
    },
}


async def _brave_search(query: str, count: int = 5) -> list[dict]:
    """调用 Brave Search API，返回简化结果列表。"""
    api_key = _brave_api_key()
    if not api_key:
        return []
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            BRAVE_SEARCH_URL,
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
            },
            params={"q": query, "count": str(min(count, 10))},
        )
    if response.status_code >= 400:
        return []
    data = response.json()
    web = data.get("web", {}) if isinstance(data, dict) else {}
    results = web.get("results", [])
    if not isinstance(results, list):
        return []
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")}
        for r in results[:count]
    ]


def _enabled() -> bool:
    value = _llm_config_value("enabled", os.getenv("AI_ENABLED", "true"))
    return str(value).lower() in {"1", "true", "yes", "on"}


def _max_actions() -> int:
    return max(1, int(_llm_config_value("max_actions", os.getenv("AI_MAX_ACTIONS", "8"))))


def _normalize_item_name(action: dict) -> None:
    """LLM 可能输出 item_name 而非 name，统一归一到 name 便于下游执行。"""
    if "name" not in action or not str(action.get("name") or "").strip():
        item_name = str(action.get("item_name") or "").strip()
        if item_name:
            action["name"] = item_name


def _has_item_identity(action: dict) -> bool:
    return action.get("item_id") is not None or bool(str(action.get("name") or action.get("item_name") or "").strip())


def _validate(actions: list[dict]) -> list[dict]:
    if not isinstance(actions, list) or len(actions) > _max_actions():
        raise HTTPException(400, f"actions 必须是最多 {_max_actions()} 条的数组")
    for action in actions:
        if not isinstance(action, dict) or action.get("op") not in ALL_OPS:
            raise HTTPException(400, "AI 返回了不支持的操作")
        if any(word in json.dumps(action, ensure_ascii=False).lower() for word in ("select ", "insert ", "update ", "delete ", "drop ", "sqlite", "execute_sql")):
            raise HTTPException(400, "AI 操作中不能包含 SQL 或数据库指令")
        # 物品名归一化：item_name -> name，必须在数量/库存校验前完成。
        _normalize_item_name(action)
        if action["op"] in {"item.purchase", "item.usage"}:
            amount = action.get("amount")
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                amount = 0
            if not math.isfinite(amount) or amount <= 0:
                raise HTTPException(400, "购买或消耗数量必须是大于 0 的数字")
            action["amount"] = amount
            if not _has_item_identity(action):
                raise HTTPException(400, "购买或消耗操作缺少物品标识（name/item_id）")
        if action["op"] == "item.create" and any(key in action for key in ("amount", "quantity")):
            raise HTTPException(400, "新建物品不能携带数量；加库存必须使用 item.purchase")
        if action["op"] in {"item.set_stock", "item.update"}:
            if not _has_item_identity(action):
                raise HTTPException(400, "该操作缺少物品标识（name/item_id）")
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


def _loads_json_object(content: Any) -> dict:
    if not isinstance(content, str):
        raise ValueError("模型返回内容不是文本")
    text = content.strip()
    candidates = [text]
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        candidates.append("\n".join(lines[1:-1]).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("模型未返回合法 JSON")


def _llm_error_message(status_code: int) -> str:
    if status_code in {401, 403}:
        return "LLM API Key 无效或无权限"
    if status_code == 404:
        return "LLM 地址或模型不存在"
    if status_code == 429:
        return "LLM 限流或余额不足"
    if status_code in {502, 503, 504}:
        return "LLM 网关可用，但上游模型请求失败，请换模型或稍后重试"
    return "AI 解析请求失败，请检查 LLM 配置"


def _response_json(response: httpx.Response) -> dict:
    content_type = response.headers.get("content-type", "")
    if "html" in content_type or response.text.lstrip().startswith("<"):
        raise ValueError("LLM Base URL 似乎是网页地址，请改成 OpenAI-compatible API 地址（通常以 /v1 结尾）")
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("上游响应格式不是 OpenAI Chat Completions")
    return data


async def _chat_completion(client: httpx.AsyncClient, base_url: str, api_key: str, body: dict) -> httpx.Response:
    headers = {"Authorization": f"Bearer {api_key}"}
    with_json = {**body, "response_format": {"type": "json_object"}}
    response = await client.post(f"{base_url}/chat/completions", headers=headers, json=with_json)
    if response.status_code == 400 and "response_format" in response.text:
        response = await client.post(f"{base_url}/chat/completions", headers=headers, json=body)
    return response


def _llm_config() -> tuple[str, str, str, float]:
    base_url = str(_llm_config_value("base_url", "")).rstrip("/")
    api_key = str(_llm_config_value("api_key", ""))
    model = str(_llm_config_value("model", ""))
    timeout_sec = float(_llm_config_value("timeout_sec", "30"))
    if not base_url or not api_key or not model:
        raise HTTPException(503, "AI 未配置，请检查 LLM_BASE_URL、LLM_API_KEY 和 LLM_MODEL，或到设置页录入")
    return base_url, api_key, model, timeout_sec


async def _snapshot(db) -> dict:
    cur = await db.execute("SELECT id,name,unit,current_stock,category,location,expires_at FROM items ORDER BY id LIMIT 80")
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


def _dumps(value) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def _exc_message(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(detail)


async def _snapshot_target(db, action: dict, result: dict | None = None) -> dict:
    """抓取单条 action 目标对象的当前快照，用于 before/after 溯源。"""
    op = action.get("op", "")
    if op.startswith("item."):
        item_id = (result or {}).get("item_id") or action.get("item_id")
        if not item_id:
            name = str(action.get("name") or action.get("item_name") or "").strip()
            cur = await db.execute("SELECT * FROM items WHERE name=?", (name,))
            row = await cur.fetchone()
            return {"op": op, "item_id": row["id"] if row else None, "row": dict(row) if row else None}
        cur = await db.execute("SELECT * FROM items WHERE id=?", (item_id,))
        row = await cur.fetchone()
        return {"op": op, "item_id": item_id, "row": dict(row) if row else None}
    if op.startswith("todo."):
        todo_id = (result or {}).get("todo_id") or action.get("todo_id")
        if todo_id:
            cur = await db.execute("SELECT * FROM todos WHERE id=?", (todo_id,))
            row = await cur.fetchone()
            return {"op": op, "todo_id": todo_id, "row": dict(row) if row else None}
    return {"op": op}


async def _audit(db, *, raw_text=None, actions=None, results=None, ok: bool, stage: str,
                 session_id: str | None = None, llm_model: str | None = None,
                 llm_reply: str | None = None, confidence: str | None = None,
                 duration_ms: int | None = None, error: str | None = None,
                 before_json: str | None = None, after_json: str | None = None) -> int:
    cur = await db.execute(
        "INSERT INTO ai_audit(raw_text,actions_json,results_json,ok,stage,session_id,"
        "llm_model,llm_reply,confidence,duration_ms,error,before_json,after_json) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (raw_text, _dumps(actions), _dumps(results), int(ok), stage, session_id,
         llm_model, llm_reply, confidence, duration_ms, error, before_json, after_json),
    )
    await db.commit()
    return cur.lastrowid


async def _safe_audit(db, **kwargs) -> None:
    """审计落库失败不得影响业务流程或吞掉原始异常。"""
    try:
        await _audit(db, **kwargs)
    except Exception:
        pass


@router.post("/ai/parse")
async def parse(payload: ParseIn, db=Depends(get_db)):
    if not _enabled():
        raise HTTPException(503, "AI 工作台未开启")
    if not payload.text.strip():
        raise HTTPException(400, "请输入指令")
    base_url, api_key, model, timeout_sec = _llm_config()
    prompt = (
        "你是 HomeDash 家庭数据操作助手。只能输出一个 JSON 对象，不要 Markdown 或解释。"
        "格式严格为 {\"reply\":\"中文简短说明\",\"confidence\":\"high|medium|low\",\"actions\":[...]}. "
        "actions 必须至少有一项，且 op 只能是：item.purchase,item.usage,item.set_stock,item.create,item.update,"
        "todo.create,todo.complete,todo.reopen,todo.update,todo.delete,query.need_buy,query.items,"
        "query.open_todos,query.overdue_todos。用户说加、买、入库某物品时必须输出 item.purchase，"
        "并使用 amount 数字字段；不存在时加 create_if_missing:true。item.create 仅用于零库存新建物品，不能带数量。"
        "物品名称字段固定写 name（不要用 item_name 或其它变体）。"
        "item.create 和 item.update 可带 category,unit,min_stock,location,expires_at；expires_at 用 YYYY-MM。"
        "用户问要买什么时必须输出 {\"op\":\"query.need_buy\"}，"
        "问未完成待办时必须输出 {\"op\":\"query.open_todos\"}。禁止 SQL、表名、路径和设备控制。"
        "上下文：" + json.dumps(await _snapshot(db), ensure_ascii=False)
    )
    started = time.perf_counter()
    llm_reply = None
    confidence = None
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await _chat_completion(client, base_url, api_key, {"model": model, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": payload.text}]})
        if response.status_code >= 400:
            raise HTTPException(502, _llm_error_message(response.status_code))
        data = _loads_json_object(_response_json(response)["choices"][0]["message"]["content"])
        llm_reply = data.get("reply")
        confidence = _confidence(data.get("confidence"))
        actions = _validate(data.get("actions", []))
        if not actions:
            raise HTTPException(502, "AI 未返回可执行或查询动作，未写入任何数据")
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        err = _exc_message(exc) if isinstance(exc, HTTPException) else str(exc) or exc.__class__.__name__
        await _safe_audit(db, raw_text=payload.text, ok=False, stage="parse",
                          session_id=payload.session_id, llm_model=model,
                          llm_reply=llm_reply, confidence=confidence,
                          duration_ms=duration_ms, error=err)
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, ValueError):
            raise HTTPException(502, str(exc)) from exc
        raise HTTPException(502, "模型未返回合法 JSON，请换支持结构化输出的模型或重试") from exc
    duration_ms = int((time.perf_counter() - started) * 1000)
    await _safe_audit(db, raw_text=payload.text, actions=actions, ok=True, stage="parse",
                      session_id=payload.session_id, llm_model=model,
                      llm_reply=llm_reply, confidence=confidence, duration_ms=duration_ms)
    read_results = [await _query(db, action) for action in actions if action["op"] in QUERY_OPS]
    return {"ok": True, "reply": data.get("reply", "已生成操作预览。"), "confidence": confidence, "actions": actions, "read_results": read_results or None, "needs_disambiguation": None}


@router.post("/ai/chat")
async def chat(payload: ChatIn, db=Depends(get_db)):
    if not _enabled():
        raise HTTPException(503, "AI 工作台未开启")
    if not payload.text.strip():
        raise HTTPException(400, "请输入内容")
    base_url, api_key, model, timeout_sec = _llm_config()
    brave_available = _brave_api_key() is not None
    chat_prompt = (
        "你是 HomeDash 家庭管理顾问，一个友好、简洁的中文助手。你可以帮助用户：\n"
        "- 解答关于家庭物品管理、库存预测的问题\n"
        "- 提供家务和家庭管理的建议\n"
        "- 解释 HomeDash 面板的功能和使用方法\n"
        "- 根据下方上下文快照回答用户关于当前库存数量、待办状态等问题\n"
        + ("- 如需查询实时信息（天气、新闻、百科等），可使用 brave_web_search 工具搜索网络\n" if brave_available else "")
        + "回复用中文，简洁清晰，不要 Markdown 格式。如果不知道答案，诚实说明。"
        "上下文：" + json.dumps(await _snapshot(db), ensure_ascii=False)
    )
    messages = [{"role": "system", "content": chat_prompt}]
    if payload.history and isinstance(payload.history, list):
        for msg in payload.history[-20:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": str(content)})
    messages.append({"role": "user", "content": payload.text})

    tools = [BRAVE_SEARCH_TOOL] if brave_available else None
    started = time.perf_counter()
    final_reply = ""
    max_turns = 5
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            headers = {"Authorization": f"Bearer {api_key}"}
            for _ in range(max_turns):
                body: dict = {"model": model, "messages": messages}
                if tools:
                    body["tools"] = tools
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=body,
                )
                if response.status_code >= 400:
                    raise HTTPException(502, _llm_error_message(response.status_code))
                data = _response_json(response)
                msg = data["choices"][0]["message"]
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    messages.append({
                        "role": "assistant",
                        "content": msg.get("content"),
                        "tool_calls": tool_calls,
                    })
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        if func.get("name") == "brave_web_search":
                            args_str = func.get("arguments", "{}")
                            try:
                                args = json.loads(args_str) if isinstance(args_str, str) else args_str
                            except json.JSONDecodeError:
                                args = {}
                            query = args.get("query", "")
                            if query:
                                results = await _brave_search(query)
                                result_text = json.dumps(results, ensure_ascii=False) if results else "未找到相关搜索结果"
                            else:
                                result_text = "搜索关键词为空，请提供有效的搜索词"
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.get("id", ""),
                                "content": result_text,
                            })
                    continue

                content = msg.get("content", "")
                if not isinstance(content, str):
                    content = str(content)
                final_reply = content.strip()
                break
    except HTTPException:
        raise
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        err = str(exc) or exc.__class__.__name__
        await _safe_audit(db, raw_text=payload.text, ok=False, stage="chat",
                          session_id=payload.session_id, llm_model=model,
                          duration_ms=duration_ms, error=err)
        if isinstance(exc, ValueError):
            raise HTTPException(502, str(exc)) from exc
        raise HTTPException(502, "模型调用失败，请检查 LLM 配置或稍后重试") from exc

    if not final_reply:
        raise HTTPException(502, "模型未返回有效回复")

    duration_ms = int((time.perf_counter() - started) * 1000)
    await _safe_audit(db, raw_text=payload.text, ok=True, stage="chat",
                      session_id=payload.session_id, llm_model=model,
                      llm_reply=final_reply, duration_ms=duration_ms)
    return {"ok": True, "reply": final_reply, "session_id": payload.session_id}


@router.post("/ai/item-category")
async def item_category(payload: CategoryIn):
    if not _enabled():
        raise HTTPException(503, "AI 工作台未开启")
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "物品名称必填")
    base_url, api_key, model, timeout_sec = _llm_config()
    prompt = (
        "你只做日用品分类。只能输出 JSON：{\"category\":\"纸品|洗护|清洁|厨房|宠物|冷冻|药品|其他\"}。"
        "无法判断时输出其他。"
    )
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await _chat_completion(client, base_url, api_key, {"model": model, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": name}], "max_tokens": 30})
        if response.status_code >= 400:
            raise HTTPException(502, _llm_error_message(response.status_code))
        data = _loads_json_object(_response_json(response)["choices"][0]["message"]["content"])
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise HTTPException(502, "模型未返回合法分类 JSON，请手动填写分类") from exc
    category = str(data.get("category", "其他")).strip()
    if category not in {"纸品", "洗护", "清洁", "厨房", "宠物", "冷冻", "药品", "其他"}:
        category = "其他"
    return {"ok": True, "category": category}


@router.post("/ai/apply")
async def apply(payload: ApplyIn, db=Depends(get_db)):
    if not _enabled():
        raise HTTPException(503, "AI 工作台未开启")
    started = time.perf_counter()
    try:
        actions = _validate(payload.actions)
        writes = [action for action in actions if action["op"] in WRITE_OPS]
        if any(action["op"] == "todo.delete" for action in writes) and payload.confidence != "high":
            raise HTTPException(400, "删除待办必须由高置信度 AI 结果确认")
    except HTTPException as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        await _safe_audit(db, raw_text=payload.raw_text, actions=payload.actions, ok=False,
                          stage="apply", session_id=payload.session_id,
                          confidence=payload.confidence, duration_ms=duration_ms,
                          error=_exc_message(exc))
        raise
    results = []
    before_snapshots = []
    after_snapshots = []
    try:
        for action in writes:
            before_snapshots.append(await _snapshot_target(db, action))
            result = await ai_executor.execute_action(db, action)
            results.append(result)
            after_snapshots.append(await _snapshot_target(db, action, result))
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        err = _exc_message(exc) if isinstance(exc, HTTPException) else str(exc) or exc.__class__.__name__
        await _safe_audit(db, raw_text=payload.raw_text, actions=actions, results=results, ok=False,
                          stage="apply", session_id=payload.session_id, confidence=payload.confidence,
                          duration_ms=duration_ms, error=err,
                          before_json=_dumps(before_snapshots), after_json=_dumps(after_snapshots))
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, f"执行失败: {exc}") from exc
    duration_ms = int((time.perf_counter() - started) * 1000)
    audit_id = await _audit(db, raw_text=payload.raw_text, actions=actions, results=results, ok=True,
                            stage="apply", session_id=payload.session_id, confidence=payload.confidence,
                            duration_ms=duration_ms,
                            before_json=_dumps(before_snapshots), after_json=_dumps(after_snapshots))
    return {"ok": True, "results": results, "action_id": audit_id}


@router.post("/ai/revert/{action_id}")
async def revert(action_id: int, db=Depends(get_db)):
    if not _enabled():
        raise HTTPException(503, "AI 工作台未开启")
    cur = await db.execute(
        "SELECT * FROM ai_audit WHERE id=? AND ok=1 AND (reverted=0 OR reverted IS NULL) AND (stage='apply' OR stage IS NULL)",
        (action_id,),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "无可撤回的操作")
    actions = json.loads(row["actions_json"])
    results = json.loads(row["results_json"])
    # 逆序撤回写操作
    try:
        for action, result in zip(reversed(actions), reversed(results)):
            await _revert_action(db, action, result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"撤回失败: {exc}") from exc
    await db.execute("UPDATE ai_audit SET reverted=1 WHERE id=?", (action_id,))
    await db.commit()
    return {"ok": True, "reverted": action_id}


async def _revert_action(db, action: dict, result: dict) -> None:
    op = action["op"]
    if op == "item.purchase":
        item_id = result.get("item_id")
        amount = action.get("amount", 0)
        if item_id:
            await db.execute("UPDATE items SET current_stock=current_stock-? WHERE id=?", (amount, item_id))
    elif op == "item.usage":
        item_id = result.get("item_id")
        amount = action.get("amount", 0)
        if item_id:
            await db.execute("UPDATE items SET current_stock=current_stock+? WHERE id=?", (amount, item_id))
    elif op == "item.set_stock":
        item_id = result.get("item_id")
        before = action.get("before", {})
        if item_id and "current_stock" in before:
            await db.execute("UPDATE items SET current_stock=? WHERE id=?", (before["current_stock"], item_id))
    elif op == "item.create":
        item_id = result.get("item_id")
        if item_id:
            await db.execute("DELETE FROM items WHERE id=?", (item_id,))
    elif op == "todo.create":
        todo_id = result.get("todo_id")
        if todo_id:
            await db.execute("DELETE FROM todos WHERE id=?", (todo_id,))
    elif op == "todo.complete":
        todo_id = result.get("todo_id")
        if todo_id:
            await db.execute("UPDATE todos SET status='open', completed_at=NULL WHERE id=?", (todo_id,))
    elif op == "todo.reopen":
        todo_id = result.get("todo_id")
        if todo_id:
            await db.execute("UPDATE todos SET status='done', completed_at=datetime('now') WHERE id=?", (todo_id,))
    elif op == "todo.delete":
        # 删除的待办无法安全恢复，跳过
        pass
    elif op == "item.update":
        item_id = result.get("item_id")
        before = action.get("before", {})
        if item_id and before:
            sets = ", ".join(f"{k}=?" for k in before)
            await db.execute(f"UPDATE items SET {sets} WHERE id=?", (*before.values(), item_id))


@router.get("/ai/audit")
async def audit(limit: int = 20, offset: int = 0, db=Depends(get_db)):
    count_cur = await db.execute("SELECT COUNT(*) FROM ai_audit")
    total = (await count_cur.fetchone())[0]
    cur = await db.execute(
        "SELECT * FROM ai_audit ORDER BY id DESC LIMIT ? OFFSET ?",
        (max(1, min(limit, 100)), max(0, offset)),
    )
    rows = [dict(row) for row in await cur.fetchall()]
    return {"rows": rows, "total": total, "has_more": offset + len(rows) < total}


@router.get("/ai/suggested-chips")
async def suggested_chips(days: int = 30, count: int = 4, db=Depends(get_db)):
    """分析近 N 天常用操作文本，返回推荐快捷按钮文案。"""
    if not _enabled():
        raise HTTPException(503, "AI 工作台未开启")
    days = max(1, min(days, 90))
    count = max(2, min(count, 8))
    cur = await db.execute(
        "SELECT raw_text FROM ai_audit "
        "WHERE stage='parse' AND ok=1 AND raw_text IS NOT NULL AND raw_text != '' "
        "AND created_at >= datetime('now', ?) "
        "ORDER BY id DESC LIMIT 200",
        (f"-{days} days",),
    )
    rows = await cur.fetchall()
    defaults = ["加 10 包方便面", "用掉 2 卷卫生纸", "新建待办换滤芯", "现在有什么要买的"]
    if not rows:
        return {"chips": defaults[:count]}

    text_counts: dict[str, int] = {}
    for row in rows:
        text = (row["raw_text"] or "").strip()
        if text:
            key = text[:30]
            text_counts[key] = text_counts.get(key, 0) + 1

    sorted_texts = sorted(text_counts.items(), key=lambda x: -x[1])
    chips = [text for text, _ in sorted_texts[:count]]

    while len(chips) < 2:
        for d in defaults:
            if d not in chips:
                chips.append(d)
                break

    return {"chips": chips[:count]}


if __name__ == "__main__":
    assert _validate([{"op": "item.purchase", "name": "方便面", "amount": 1}])[0]["op"] == "item.purchase"
    assert _loads_json_object('```json\n{"ok": true}\n```')["ok"] is True
    assert _loads_json_object('好的 {"ok": true}')["ok"] is True
    try:
        _validate([{"op": "execute_sql", "sql": "DELETE FROM items"}])
    except HTTPException:
        pass
    else:
        raise AssertionError("非法操作必须被拒绝")
    # LLM 输出 item_name 时归一化到 name
    a = _validate([{"op": "item.purchase", "item_name": "纸巾", "amount": 2, "create_if_missing": True}])[0]
    assert a["name"] == "纸巾" and a["amount"] == 2.0, a
    # 缺物品标识的写操作必须被拒绝
    for bad in ({"op": "item.purchase", "amount": 1},
                {"op": "item.usage", "amount": 1},
                {"op": "item.set_stock", "current_stock": 3},
                {"op": "item.update", "min_stock": 2}):
        try:
            _validate([bad])
        except HTTPException:
            pass
        else:
            raise AssertionError(f"缺标识操作必须被拒绝: {bad}")
    # set_stock 带 name 正常通过
    b = _validate([{"op": "item.set_stock", "name": "纸巾", "current_stock": 3}])[0]
    assert b["current_stock"] == 3.0 and b["name"] == "纸巾", b
    # ChatIn model
    c = ChatIn(text="你好", session_id="s1", history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}])
    assert c.text == "你好" and len(c.history) == 2
    print("ai_workbench.py 自检通过：白名单、字段归一、缺标识校验与 ChatIn 模型正确。")
