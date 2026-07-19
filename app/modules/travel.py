"""旅游计划与基于天气的 AI 行李推荐。"""
import json
from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.database import get_db
from app.modules.ai_workbench import (
    _brave_api_key,
    _brave_search,
    _chat_completion,
    _enabled,
    _llm_config,
    _llm_error_message,
    _loads_json_object,
    _response_json,
)

router = APIRouter()


class PlanIn(BaseModel):
    destination: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    travelers: int = Field(default=1, ge=1, le=30)
    activities: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("destination")
    @classmethod
    def _non_empty_destination(cls, value: str) -> str:
        # min_length 按 code point 计数，挡不住纯空格；这里去空白后兜底拒绝
        value = value.strip()
        if not value:
            raise ValueError("目的地不能为空")
        return value


class PackingItem(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category: str = Field(default="其他", max_length=30)
    quantity: str = Field(default="1", max_length=30)
    note: str = Field(default="", max_length=200)
    packed: bool = False

    @field_validator("name", "category", "quantity", "note", mode="before")
    @classmethod
    def _coerce_text(cls, value):
        # LLM 可能返回数字型数量/类别，统一收成字符串，避免整项被校验丢弃
        if value is None:
            return ""
        return value if isinstance(value, str) else str(value)


class PackingIn(BaseModel):
    items: list[PackingItem] = Field(max_length=100)


def _validate_dates(payload: PlanIn) -> None:
    if payload.end_date < payload.start_date:
        raise HTTPException(400, "结束日期不能早于开始日期")
    if (payload.end_date - payload.start_date).days > 90:
        raise HTTPException(400, "单次行程最长支持 90 天")


def _row(row) -> dict:
    data = dict(row)
    try:
        data["packing_items"] = json.loads(data.pop("packing_json") or "[]")
    except json.JSONDecodeError:
        data["packing_items"] = []
    return data


async def _get_plan(db, plan_id: int):
    row = await (await db.execute("SELECT * FROM travel_plans WHERE id=?", (plan_id,))).fetchone()
    if not row:
        raise HTTPException(404, "旅游计划不存在")
    return row


@router.get("/travel/plans")
async def list_plans(db=Depends(get_db)):
    rows = await (await db.execute("SELECT * FROM travel_plans ORDER BY start_date DESC, id DESC")).fetchall()
    return [_row(row) for row in rows]


@router.post("/travel/plans")
async def create_plan(payload: PlanIn, db=Depends(get_db)):
    _validate_dates(payload)
    cur = await db.execute(
        "INSERT INTO travel_plans(destination,start_date,end_date,travelers,activities,notes) VALUES(?,?,?,?,?,?)",
        (payload.destination, str(payload.start_date), str(payload.end_date), payload.travelers,
         (payload.activities or "").strip(), (payload.notes or "").strip()),
    )
    await db.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.put("/travel/plans/{plan_id}")
async def update_plan(plan_id: int, payload: PlanIn, db=Depends(get_db)):
    prev = await _get_plan(db, plan_id)  # 先确认存在：缺失返回 404，而不是日期校验错误
    _validate_dates(payload)
    await db.execute(
        "UPDATE travel_plans SET destination=?,start_date=?,end_date=?,travelers=?,activities=?,notes=?,updated_at=datetime('now','localtime') WHERE id=?",
        (payload.destination, str(payload.start_date), str(payload.end_date), payload.travelers,
         (payload.activities or "").strip(), (payload.notes or "").strip(), plan_id),
    )
    # ponytail: 日期一旦变化，旧 weather 不再适用；这里直接清空，避免在新日期旁展示误导性天气。
    if str(prev["start_date"]) != str(payload.start_date) or str(prev["end_date"]) != str(payload.end_date):
        await db.execute("UPDATE travel_plans SET weather_summary=NULL, weather_source=NULL WHERE id=?", (plan_id,))
    await db.commit()
    return {"ok": True}


@router.delete("/travel/plans/{plan_id}")
async def delete_plan(plan_id: int, db=Depends(get_db)):
    await _get_plan(db, plan_id)
    await db.execute("DELETE FROM travel_plans WHERE id=?", (plan_id,))
    await db.commit()
    return {"ok": True}


@router.put("/travel/plans/{plan_id}/packing")
async def save_packing(plan_id: int, payload: PackingIn, db=Depends(get_db)):
    await _get_plan(db, plan_id)
    items = [item.model_dump() for item in payload.items]
    await db.execute(
        "UPDATE travel_plans SET packing_json=?,updated_at=datetime('now','localtime') WHERE id=?",
        (json.dumps(items, ensure_ascii=False), plan_id),
    )
    await db.commit()
    return {"ok": True}


@router.post("/travel/plans/{plan_id}/recommend")
async def recommend(plan_id: int, db=Depends(get_db)):
    if not _enabled():
        raise HTTPException(503, "AI 功能未开启")
    plan = dict(await _get_plan(db, plan_id))
    base_url, api_key, model, timeout_sec = _llm_config()
    weather_results: list[dict] = []
    if _brave_api_key():
        query = f"{plan['destination']} {plan['start_date']} 至 {plan['end_date']} 天气预报 温度 降雨"
        try:
            weather_results = await _brave_search(query, 6)
        except (httpx.HTTPError, ValueError):
            # ponytail: 搜索是可选增强；网络失败或 Brave 返回非 JSON（验证码/HTML 200）时继续让 LLM 按季节常识生成并标注来源。
            weather_results = []
    weather_context = json.dumps(weather_results, ensure_ascii=False) if weather_results else "无联网天气资料，请按目的地、日期和季节常识估算，并明确说明非实时天气。"
    prompt = (
        "你是严谨的中文旅行行李助手。根据行程和天气资料生成行李建议。"
        "只输出一个 JSON 对象，不要 Markdown："
        '{"weather_summary":"简短天气说明及不确定性","items":[{"name":"物品","category":"证件|衣物|洗护|电子|药品|户外|其他","quantity":"数量","note":"携带理由","packed":false}]}。'
        "最多 20 项；避免推荐危险品；药品只给常规提醒，不作诊断；数量要结合天数和人数。"
    )
    user = json.dumps({
        "目的地": plan["destination"], "开始日期": plan["start_date"], "结束日期": plan["end_date"],
        "人数": plan["travelers"], "活动": plan["activities"], "备注": plan["notes"], "天气资料": weather_context,
    }, ensure_ascii=False)
    try:
        # 推理模型（如 qwen3.7-plus）生成行李清单约需 50–60s：超时放宽到至少 90s；
        # 且这类模型在长输出下用 response_format=json_object 会触发上游 500，
        # 故 json_mode=False（prompt 已要求只输出 JSON，_loads_json_object 容错解析）。
        async with httpx.AsyncClient(timeout=max(timeout_sec, 90)) as client:
            response = await _chat_completion(client, base_url, api_key, {
                "model": model,
                "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                "temperature": 0.2,
            }, json_mode=False)
        if response.status_code >= 400:
            raise HTTPException(502, _llm_error_message(response.status_code))
        data = _loads_json_object(_response_json(response)["choices"][0]["message"]["content"])
        items: list[dict] = []
        for raw in (data.get("items") or []):  # items 为 null 时降级为空列表，避免 None[:35] 报错
            if len(items) >= 35:
                break
            try:
                items.append(PackingItem.model_validate(raw).model_dump())
            except (ValueError, TypeError):
                continue  # 单项格式异常就跳过，不连累整张清单
        if not items:
            raise ValueError("推荐清单为空")
        raw_summary = data.get("weather_summary")
        summary = str(raw_summary).strip() if isinstance(raw_summary, str) else ""
        summary = summary[:1000] or "未提供天气摘要"
    except HTTPException:
        raise
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise HTTPException(502, "模型未返回有效的行李清单，请稍后重试") from exc
    except ValueError as exc:
        # 透传 _response_json / _loads_json_object 的具体中文提示（如 Base URL 像网页地址），便于排查
        raise HTTPException(502, str(exc) or "模型未返回有效的行李清单，请稍后重试") from exc
    # 保留用户已勾选的进度：按物品名匹配旧清单的 packed 标记，重新生成不丢已备好的物品
    try:
        previous = {str(row.get("name") or "").strip(): bool(row.get("packed"))
                    for row in (json.loads(plan.get("packing_json") or "[]") or [])}
    except (json.JSONDecodeError, TypeError, AttributeError):
        previous = {}
    for item in items:
        item["packed"] = previous.get(str(item.get("name") or "").strip(), False)
    source = "Brave 网络搜索 + LLM" if weather_results else "LLM 季节常识估算"
    await db.execute(
        "UPDATE travel_plans SET weather_summary=?,weather_source=?,packing_json=?,updated_at=datetime('now','localtime') WHERE id=?",
        (summary, source, json.dumps(items, ensure_ascii=False), plan_id),
    )
    await db.commit()
    return {"ok": True, "weather_summary": summary, "weather_source": source, "items": items}


if __name__ == "__main__":
    good = PlanIn(destination="  上海  ", start_date="2026-08-01", end_date="2026-08-03", travelers=2)
    _validate_dates(good)
    assert good.destination == "上海", "目的地应去前后空白"
    assert PackingItem(name="雨伞", quantity="1把").packed is False
    assert PackingItem(name="袜子", quantity=2).quantity == "2", "数字型数量应收成字符串"
    try:
        _validate_dates(PlanIn(destination="上海", start_date="2026-08-03", end_date="2026-08-01"))
    except HTTPException:
        pass
    else:
        raise AssertionError("倒置日期必须被拒绝")
    for blank in ("", "   "):
        try:
            PlanIn(destination=blank, start_date="2026-08-01", end_date="2026-08-03")
        except ValidationError:
            continue
        raise AssertionError(f"空白目的地必须被拒绝：{blank!r}")
    print("travel.py 自检通过：日期边界、目的地非空校验与行李条目模型正确。")
