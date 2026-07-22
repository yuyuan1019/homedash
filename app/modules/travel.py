"""旅游计划：目的地推荐引擎 + 非网红玩法 + 天气行李推荐。

- /travel/plans CRUD（行程）
- /travel/suggest：按出发城市/交通方式/策略/标签推荐候选目的地（避开网红、度假·性价比优先），
  可选 Brave 联网 + 高德地图精确交通时长
- /travel/plans/{id}/spots：选定目的地后生成「非网红具体玩法」清单
- /travel/plans/{id}/recommend：结合天气生成行李清单（原有）
"""
import asyncio
import json
import math
import os
from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
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
    _safe_audit,
    _sse,
)

router = APIRouter()

# 推荐上限（写进 prompt，也在归一化循环里兜底截断）
_MAX_DESTINATIONS = 8
_MAX_SPOTS = 12

_TRANSPORT_MODES = {"高铁", "自驾", "飞机", "不限"}
_STRATEGIES = {"度假优先", "性价比优先", "不网红优先", "综合"}
_BUDGET_TIERS = {"经济", "舒适", "不限"}

# 高德地理编码 / 驾车路径规划
_AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
_AMAP_DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"
# 高铁/飞机高德无跨城铁路·航司时刻，用直线距离 × 模式速度估算（km/h）
_SPEED_KMH = {"高铁": 250.0, "飞机": 800.0, "不限": 80.0}


def _amap_config() -> dict | None:
    """读取高德配置：环境变量 AMAP_API_KEY 优先，其次 data/amap_config.json。与 brave 同构。"""
    env_key = os.getenv("AMAP_API_KEY", "").strip()
    if env_key:
        return {"api_key": env_key}
    path = "data/amap_config.json"
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _amap_api_key() -> str | None:
    cfg = _amap_config()
    if cfg and cfg.get("api_key"):
        return str(cfg["api_key"]).strip()
    return None


class PlanIn(BaseModel):
    destination: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    travelers: int = Field(default=1, ge=1, le=30)
    activities: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    # 待办 16 新增：行程偏好（均可选，向后兼容旧前端/旧库）
    origin_city: str | None = Field(default=None, max_length=60)
    transport_mode: str | None = Field(default=None)
    budget_tier: str | None = Field(default=None)
    strategy: str | None = Field(default=None)
    tags: list[str] = Field(default_factory=list)

    @field_validator("destination")
    @classmethod
    def _non_empty_destination(cls, value: str) -> str:
        # min_length 按 code point 计数，挡不住纯空格；这里去空白后兜底拒绝
        value = value.strip()
        if not value:
            raise ValueError("目的地不能为空")
        return value

    @field_validator("origin_city")
    @classmethod
    def _clean_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("transport_mode")
    @classmethod
    def _valid_transport(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in _TRANSPORT_MODES:
            raise ValueError("交通方式必须是 高铁 / 自驾 / 飞机 / 不限")
        return value

    @field_validator("budget_tier")
    @classmethod
    def _valid_budget(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in _BUDGET_TIERS:
            raise ValueError("预算档必须是 经济 / 舒适 / 不限")
        return value

    @field_validator("strategy")
    @classmethod
    def _valid_strategy(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in _STRATEGIES:
            raise ValueError("策略必须是 度假优先 / 性价比优先 / 不网红优先 / 综合")
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def _clean_tags(cls, value) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned = [str(t).strip() for t in value if str(t).strip()]
        return cleaned[:12]


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


class SuggestIn(BaseModel):
    origin_city: str = Field(min_length=1, max_length=60)
    transport_mode: str = Field(default="不限")
    days: int = Field(default=3, ge=1, le=90)
    travelers: int = Field(default=2, ge=1, le=30)
    strategy: str = Field(default="综合")
    tags: list[str] = Field(default_factory=list)
    budget_tier: str = Field(default="不限")
    month: int | None = Field(default=None, ge=1, le=12)

    @field_validator("origin_city")
    @classmethod
    def _non_empty_origin(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("出发城市不能为空")
        return value

    @field_validator("transport_mode")
    @classmethod
    def _valid_transport(cls, value: str) -> str:
        if value not in _TRANSPORT_MODES:
            raise ValueError("交通方式必须是 高铁 / 自驾 / 飞机 / 不限")
        return value

    @field_validator("strategy")
    @classmethod
    def _valid_strategy(cls, value: str) -> str:
        if value not in _STRATEGIES:
            raise ValueError("策略必须是 度假优先 / 性价比优先 / 不网红优先 / 综合")
        return value

    @field_validator("budget_tier")
    @classmethod
    def _valid_budget(cls, value: str) -> str:
        if value not in _BUDGET_TIERS:
            raise ValueError("预算档必须是 经济 / 舒适 / 不限")
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def _clean_tags(cls, value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(t).strip() for t in value if str(t).strip()][:12]


class TransportInfo(BaseModel):
    mode: str
    duration_hours: float | None = None
    distance_km: float | None = None
    note: str = ""
    accuracy: str = "LLM 估算"  # 高德精确 | 距离估算 | LLM 估算


class DestinationSuggestion(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    region: str = Field(default="", max_length=80)
    vibe: str = Field(default="", max_length=300)
    why_not_viral: str = Field(default="", max_length=300)
    highlights: list[str] = Field(default=[])
    est_budget_per_person: str = Field(default="", max_length=60)
    best_days: str = Field(default="", max_length=40)
    season: str = Field(default="", max_length=60)
    tags: list[str] = Field(default=[])
    caveats: str = Field(default="", max_length=300)
    transport_note: str = Field(default="", max_length=200)  # LLM 定性描述，供无高德时兜底
    transport: TransportInfo | None = None

    @field_validator("transport", mode="before")
    @classmethod
    def _coerce_transport(cls, value):
        if value is None or isinstance(value, dict):
            return value
        return None

    @field_validator("region", "vibe", "why_not_viral", "est_budget_per_person",
                     "best_days", "season", "caveats", "transport_note", mode="before")
    @classmethod
    def _coerce_text(cls, value):
        if value is None:
            return ""
        return value if isinstance(value, str) else str(value)

    @field_validator("highlights", "tags", mode="before")
    @classmethod
    def _coerce_list(cls, value):
        if not isinstance(value, list):
            return []
        return [str(x).strip() for x in value if str(x).strip()][:8]


class SpotItem(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: str = Field(default="景点", max_length=30)  # 景点|美食|体验|住宿|其他
    why: str = Field(default="", max_length=300)
    duration_hours: float | None = Field(default=None, ge=0, le=48)
    cost: str = Field(default="", max_length=60)
    booked: bool = False

    @field_validator("type", "why", "cost", mode="before")
    @classmethod
    def _coerce_text(cls, value):
        if value is None:
            return ""
        return value if isinstance(value, str) else str(value)


class SpotsIn(BaseModel):
    items: list[SpotItem] = Field(max_length=60)


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
    try:
        data["spots"] = json.loads(data.pop("spots_json") or "[]")
    except json.JSONDecodeError:
        data["spots"] = []
    try:
        tags = json.loads(data.get("tags") or "[]")
        data["tags"] = tags if isinstance(tags, list) else []
    except (json.JSONDecodeError, TypeError):
        data["tags"] = []
    return data


async def _get_plan(db, plan_id: int):
    row = await (await db.execute("SELECT * FROM travel_plans WHERE id=?", (plan_id,))).fetchone()
    if not row:
        raise HTTPException(404, "旅游计划不存在")
    return row


def _tags_json(payload: PlanIn) -> str:
    return json.dumps(payload.tags or [], ensure_ascii=False)


@router.get("/travel/plans")
async def list_plans(db=Depends(get_db)):
    rows = await (await db.execute("SELECT * FROM travel_plans ORDER BY start_date DESC, id DESC")).fetchall()
    return [_row(row) for row in rows]


@router.post("/travel/plans")
async def create_plan(payload: PlanIn, db=Depends(get_db)):
    _validate_dates(payload)
    cur = await db.execute(
        "INSERT INTO travel_plans(destination,start_date,end_date,travelers,activities,notes,"
        "origin_city,transport_mode,budget_tier,strategy,tags) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (payload.destination, str(payload.start_date), str(payload.end_date), payload.travelers,
         (payload.activities or "").strip(), (payload.notes or "").strip(),
         payload.origin_city, payload.transport_mode, payload.budget_tier,
         payload.strategy, _tags_json(payload)),
    )
    await db.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.put("/travel/plans/{plan_id}")
async def update_plan(plan_id: int, payload: PlanIn, db=Depends(get_db)):
    prev = await _get_plan(db, plan_id)  # 先确认存在：缺失返回 404，而不是日期校验错误
    _validate_dates(payload)
    await db.execute(
        "UPDATE travel_plans SET destination=?,start_date=?,end_date=?,travelers=?,activities=?,notes=?,"
        "origin_city=?,transport_mode=?,budget_tier=?,strategy=?,tags=?,"
        "updated_at=datetime('now','localtime') WHERE id=?",
        (payload.destination, str(payload.start_date), str(payload.end_date), payload.travelers,
         (payload.activities or "").strip(), (payload.notes or "").strip(),
         payload.origin_city, payload.transport_mode, payload.budget_tier,
         payload.strategy, _tags_json(payload), plan_id),
    )
    # ponytail: 日期一旦变化，旧 weather 不再适用；这里直接清空，避免在新日期旁展示误导性天气。
    if str(prev["start_date"]) != str(payload.start_date) or str(prev["end_date"]) != str(payload.end_date):
        await db.execute("UPDATE travel_plans SET weather_summary=NULL, weather_source=NULL WHERE id=?", (plan_id,))
    # 目的地变了，旧的「非网红玩法」清单与旧天气都作废（weather 同样绑定目的地）
    if str(prev["destination"]) != payload.destination:
        await db.execute(
            "UPDATE travel_plans SET spots_json='[]', weather_summary=NULL, weather_source=NULL WHERE id=?",
            (plan_id,),
        )
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


@router.put("/travel/plans/{plan_id}/spots")
async def save_spots(plan_id: int, payload: SpotsIn, db=Depends(get_db)):
    """保存用户编辑/勾选后的玩法清单（与 packing 平行）。"""
    await _get_plan(db, plan_id)
    items = [item.model_dump() for item in payload.items]
    await db.execute(
        "UPDATE travel_plans SET spots_json=?,updated_at=datetime('now','localtime') WHERE id=?",
        (json.dumps(items, ensure_ascii=False), plan_id),
    )
    await db.commit()
    return {"ok": True}


# ============ 高德地图：交通时长精确化（可选增强，失败一律降级） ============

def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """两点（lng,lat）之间的球面直线距离，单位 km。用标准库 math，无新依赖。"""
    radius_km = 6371.0
    lng1, lat1 = math.radians(a[0]), math.radians(a[1])
    lng2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlng, dlat = lng2 - lng1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(h))


async def _amap_geocode(client: httpx.AsyncClient, key: str, address: str, city: str | None = None):
    """地址/景区名 → (lng, lat)。失败返回 None（status 非 '1'、无 geocodes、location 缺失）。"""
    params = {"key": key, "address": address}
    if city:
        params["city"] = city
    resp = await client.get(_AMAP_GEOCODE_URL, params=params)
    if resp.status_code >= 400:
        return None
    data = resp.json()  # 高德非 JSON（验证码页）时抛 ValueError，由调用方捕获
    if not isinstance(data, dict):
        return None
    if str(data.get("status")) != "1":  # ponytail: 高德 status 是字符串 "1"
        return None
    geocodes = data.get("geocodes") or []
    if not geocodes:
        return None
    loc = geocodes[0].get("location") or ""
    if "," not in loc:
        return None
    lng_s, lat_s = loc.split(",", 1)
    return (float(lng_s), float(lat_s))


async def _amap_driving(client: httpx.AsyncClient, key: str, origin, dest):
    """驾车路径规划 → {duration_hours, distance_km}。失败返回 None。"""
    resp = await client.get(_AMAP_DRIVING_URL, params={
        "key": key,
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{dest[0]},{dest[1]}",
        "strategy": "0",  # 速度优先
    })
    if resp.status_code >= 400:
        return None
    data = resp.json()
    if not isinstance(data, dict):
        return None
    if str(data.get("status")) != "1":
        return None
    paths = (data.get("route") or {}).get("paths") or []
    if not paths:
        return None
    p = paths[0]
    duration_sec = float(p.get("duration") or 0)
    distance_m = float(p.get("distance") or 0)
    return {"duration_hours": duration_sec / 3600.0, "distance_km": distance_m / 1000.0}


async def _compute_transport(client, key, origin_coord, dest_address, dest_region, mode, llm_note):
    """为一个候选目的地算出 TransportInfo。无高德 key / 无出发坐标 / 任一步失败 → 降级 LLM 估算。"""
    fallback = TransportInfo(mode=mode or "不限", note=llm_note, accuracy="LLM 估算")
    if not key or origin_coord is None or not dest_address:
        return fallback
    try:
        dest_coord = await _amap_geocode(client, key, dest_address, city=dest_region or None)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        dest_coord = None
    if dest_coord is None:
        return fallback
    try:
        if mode == "自驾":
            drv = await _amap_driving(client, key, origin_coord, dest_coord)
            if drv:
                return TransportInfo(mode="自驾", duration_hours=round(drv["duration_hours"], 1),
                                     distance_km=round(drv["distance_km"], 1), note=llm_note, accuracy="高德精确")
            return fallback
        # 高铁/飞机/不限：高德无跨城铁路·航司时刻，用直线距离 × 模式速度估算
        km = _haversine_km(origin_coord, dest_coord)
        speed = _SPEED_KMH.get(mode or "不限", 80.0)
        hours = km / speed if speed else None
        return TransportInfo(mode=mode or "不限", duration_hours=round(hours, 1) if hours is not None else None,
                             distance_km=round(km, 1), note=llm_note, accuracy="距离估算")
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError):
        return fallback


# ============ 目的地推荐 ============

_SUGGEST_PROMPT = (
    "你是资深且克制的中文旅行规划师，专长是为厌倦网红打卡的家庭推荐「小众、有度假感、性价比高」的目的地。"
    "根据出发城市、交通方式、天数、人数、主策略与标签，推荐真实存在的中国境内目的地。"
    "硬性原则：① 只推荐真实地名（省/市/县/景区），绝不编造；② 主动避开热门网红打卡地与节假日人挤人的景区，"
    "优先淡季可达、本地人常去、松弛感强的地方；③ 按主策略排序；④ 每个候选必须给出「为什么不网红/为什么值得」的具体理由；"
    "⑤ highlights 为该地 2-4 个具体非网红地点或体验，不要泛泛而谈；⑥ est_budget_per_person 给人均区间（含往返交通+住宿+餐饮）；"
    "⑦ transport_note 只写出发城市到该地的「大致交通方式与定性耗时」（如「成都自驾约 4h」），精确时长由系统另行计算，不要瞎编精确分钟。"
    "只输出一个 JSON 对象，不要 Markdown："
    '{"strategy_note":"一句话说明本次筛选逻辑","candidates":['
    '{"name":"目的地名","region":"省/市","vibe":"为什么适合度假/性价比，一句话",'
    '"why_not_viral":"为什么不网红/差异化理由","highlights":["具体地点1","具体地点2"],'
    '"est_budget_per_person":"800-1200 元","best_days":"3-4天","season":"最佳季节或月份",'
    '"tags":["温泉","自然"],"caveats":"注意点（海拔/天气/限行等）","transport_note":"出发城市到该地定性交通"}]}。'
    f"最多 {_MAX_DESTINATIONS} 个候选；不要推荐危险或非法场所。"
)


async def _suggest_destinations(payload: SuggestIn) -> tuple[list[dict], str, str]:
    """调 LLM 生成候选；可选 Brave 联网；返回 (candidates, strategy_note, web_source_tag)。"""
    base_url, api_key, model, timeout_sec = _llm_config()
    # 可选 Brave：搜「出发城市周边小众目的地」辅助（失败容忍，沿用 /recommend 模式）
    web_results: list[dict] = []
    if _brave_api_key():
        query = f"{payload.origin_city} 周边小众 避开网红 度假 性价比 目的地推荐"
        try:
            web_results = await _brave_search(query, 6)
        except (httpx.HTTPError, ValueError):
            web_results = []
    web_ctx = json.dumps(web_results, ensure_ascii=False) if web_results else "无联网资料，请按常识推荐，并说明非实时。"
    user = json.dumps({
        "出发城市": payload.origin_city, "交通方式": payload.transport_mode, "天数": payload.days,
        "人数": payload.travelers, "主策略": payload.strategy, "标签": payload.tags or [],
        "预算档": payload.budget_tier, "出行月份": payload.month or "未指定", "联网资料": web_ctx,
    }, ensure_ascii=False)
    async with httpx.AsyncClient(timeout=max(timeout_sec, 90)) as client:
        response = await _chat_completion(client, base_url, api_key, {
            "model": model,
            "messages": [{"role": "system", "content": _SUGGEST_PROMPT}, {"role": "user", "content": user}],
            "temperature": 0.4,  # 略高于行李清单，鼓励目的地多样性
        }, json_mode=False)
    if response.status_code >= 400:
        raise HTTPException(502, _llm_error_message(response.status_code))
    data = _loads_json_object(_response_json(response)["choices"][0]["message"]["content"])
    candidates: list[dict] = []
    for raw in (data.get("candidates") or []):
        if len(candidates) >= _MAX_DESTINATIONS:
            break
        try:
            candidates.append(DestinationSuggestion.model_validate(raw).model_dump())
        except (ValueError, TypeError):
            continue  # 单项格式异常就跳过，不连累整批
    if not candidates:
        raise ValueError("推荐候选为空")
    raw_note = data.get("strategy_note")
    note = str(raw_note).strip()[:500] if isinstance(raw_note, str) else ""
    return candidates, note, ("Brave 联网检索 + " if web_results else "") + "LLM"


@router.post("/travel/suggest")
async def suggest(payload: SuggestIn, db=Depends(get_db)):
    """按交通方式/策略推荐候选目的地；可选高德精确交通时长。无状态，不落库。"""
    if not _enabled():
        raise HTTPException(503, "AI 功能未开启")
    amap_key = _amap_api_key()
    try:
        candidates, strategy_note, llm_source = await _suggest_destinations(payload)
    except HTTPException:
        raise
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        await _safe_audit(db, raw_text=payload.origin_city, ok=False, stage="travel_suggest", error=str(exc) or exc.__class__.__name__)
        raise HTTPException(502, "模型未返回有效的目的地推荐，请稍后重试") from exc
    except ValueError as exc:
        await _safe_audit(db, raw_text=payload.origin_city, ok=False, stage="travel_suggest", error=str(exc))
        raise HTTPException(502, str(exc) or "模型未返回有效的目的地推荐") from exc
    # 高德交通时长 enrichment：geocode 出发城市一次，并发算各候选
    async with httpx.AsyncClient(timeout=15.0) as geo_client:
        origin_coord = None
        if amap_key:
            try:
                origin_coord = await _amap_geocode(geo_client, amap_key, payload.origin_city)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                origin_coord = None
        results = await asyncio.gather(*[
            _compute_transport(geo_client, amap_key, origin_coord, c.get("name") or "",
                               c.get("region") or "", payload.transport_mode, c.get("transport_note") or "")
            for c in candidates
        ], return_exceptions=True)
    for cand, res in zip(candidates, results):
        info = res if isinstance(res, TransportInfo) else TransportInfo(mode=payload.transport_mode, accuracy="LLM 估算")
        cand["transport"] = info.model_dump()
    amap_tag = "高德交通时长" if any(
        ((cand.get("transport") or {}).get("accuracy") in {"高德精确", "距离估算"}) for cand in candidates
    ) else "LLM 交通估算"
    source = " + ".join([llm_source, amap_tag])
    await _safe_audit(db, raw_text=payload.origin_city, ok=True, stage="travel_suggest",
                      actions={"count": len(candidates), "strategy": payload.strategy}, llm_model=None)
    return {"ok": True, "strategy_note": strategy_note, "source": source,
            "origin_city": payload.origin_city, "transport_mode": payload.transport_mode,
            "candidates": candidates}


@router.post("/travel/suggest/stream")
async def suggest_stream(payload: SuggestIn, db=Depends(get_db)):
    """流式版目的地推荐：分阶段推送进度（联网 → AI 生成 → 交通时长），最后推 done(候选)。
    LLM 本身仍非流式（输出 JSON，逐字显示无意义）；阶段可见即可缓解长等待。
    # ponytail: 阶段为预判顺序，未拆分 _suggest_destinations 内部 brave/llm 以保持最小改动。
    """
    if not _enabled():
        raise HTTPException(503, "AI 功能未开启")
    amap_key = _amap_api_key()
    brave_on = _brave_api_key() is not None

    async def event_gen():
        try:
            if brave_on:
                yield _sse("stage", {"stage": "brave", "text": "正在联网搜索小众目的地参考…"})
            yield _sse("stage", {"stage": "llm", "text": "AI 正在筛选并生成候选目的地，约需 1 分钟…"})
            candidates, strategy_note, llm_source = await _suggest_destinations(payload)
            yield _sse("stage", {"stage": "amap", "text": "正在计算出发地到各候选的交通时长…"})
            # 高德 enrichment：与 suggest() 同构，geocode 出发城市一次后并发算各候选
            async with httpx.AsyncClient(timeout=15.0) as geo_client:
                origin_coord = None
                if amap_key:
                    try:
                        origin_coord = await _amap_geocode(geo_client, amap_key, payload.origin_city)
                    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                        origin_coord = None
                results = await asyncio.gather(*[
                    _compute_transport(geo_client, amap_key, origin_coord, c.get("name") or "",
                                       c.get("region") or "", payload.transport_mode, c.get("transport_note") or "")
                    for c in candidates
                ], return_exceptions=True)
            for cand, res in zip(candidates, results):
                info = res if isinstance(res, TransportInfo) else TransportInfo(mode=payload.transport_mode, accuracy="LLM 估算")
                cand["transport"] = info.model_dump()
            amap_tag = "高德交通时长" if any(
                ((cand.get("transport") or {}).get("accuracy") in {"高德精确", "距离估算"}) for cand in candidates
            ) else "LLM 交通估算"
            source = " + ".join([llm_source, amap_tag])
            await _safe_audit(db, raw_text=payload.origin_city, ok=True, stage="travel_suggest",
                              actions={"count": len(candidates), "strategy": payload.strategy}, llm_model=None)
            yield _sse("done", {"ok": True, "strategy_note": strategy_note, "source": source,
                                "origin_city": payload.origin_city, "transport_mode": payload.transport_mode,
                                "candidates": candidates})
        except HTTPException as exc:
            await _safe_audit(db, raw_text=payload.origin_city, ok=False, stage="travel_suggest",
                              error=str(exc.detail) if exc.detail else "推荐失败")
            yield _sse("error", {"detail": str(exc.detail) if exc.detail else "推荐失败"})
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            await _safe_audit(db, raw_text=payload.origin_city, ok=False, stage="travel_suggest",
                              error=str(exc) or exc.__class__.__name__)
            yield _sse("error", {"detail": "模型未返回有效的目的地推荐，请稍后重试"})
        except ValueError as exc:
            await _safe_audit(db, raw_text=payload.origin_city, ok=False, stage="travel_suggest",
                              error=str(exc))
            yield _sse("error", {"detail": str(exc) or "模型未返回有效的目的地推荐"})

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============ 非网红玩法（行程深化） ============

_SPOTS_PROMPT = (
    "你是熟悉当地的中文旅行向导。为指定目的地生成一份「避开网红打卡、本地感强」的具体玩法清单。"
    "硬性原则：① 只推荐真实存在的地点/店铺/体验，不编造；② 主动避开小红书式热门打卡点，优先本地人常去、"
    "淡季体验好、不赶场的地方；③ why 写清「为什么值得 / 为什么冷门」；④ duration_hours 为单项建议耗时（小时）；"
    "⑤ cost 写「免费」或大致花费区间。只输出一个 JSON 对象，不要 Markdown："
    '{"summary":"一句话行程建议","spots":[{"name":"地点或体验","type":"景点|美食|体验|住宿|其他",'
    '"why":"为什么值得/为什么冷门","duration_hours":2,"cost":"免费或约X元","booked":false}]}。'
    f"最多 {_MAX_SPOTS} 项；不要推荐危险或非法场所。"
)


@router.post("/travel/plans/{plan_id}/spots")
async def recommend_spots(plan_id: int, db=Depends(get_db)):
    """为已选目的地生成非网红具体玩法清单，存 spots_json。"""
    if not _enabled():
        raise HTTPException(503, "AI 功能未开启")
    plan = dict(await _get_plan(db, plan_id))
    base_url, api_key, model, timeout_sec = _llm_config()
    # 可选 Brave：搜该目的地小众玩法（失败容忍）
    web_results: list[dict] = []
    if _brave_api_key():
        query = f"{plan['destination']} 小众 避开网红 本地人 玩法 推荐"
        try:
            web_results = await _brave_search(query, 6)
        except (httpx.HTTPError, ValueError):
            web_results = []
    web_ctx = json.dumps(web_results, ensure_ascii=False) if web_results else "无联网资料，请按常识推荐，并说明非实时。"
    user = json.dumps({
        "目的地": plan["destination"], "省/区域": plan.get("region") or "",
        "开始日期": plan["start_date"], "结束日期": plan["end_date"], "人数": plan["travelers"],
        "活动偏好": plan["activities"], "出行策略": plan.get("strategy") or "综合",
        "联网资料": web_ctx,
    }, ensure_ascii=False)
    try:
        async with httpx.AsyncClient(timeout=max(timeout_sec, 90)) as client:
            response = await _chat_completion(client, base_url, api_key, {
                "model": model,
                "messages": [{"role": "system", "content": _SPOTS_PROMPT}, {"role": "user", "content": user}],
                "temperature": 0.3,
            }, json_mode=False)
        if response.status_code >= 400:
            raise HTTPException(502, _llm_error_message(response.status_code))
        data = _loads_json_object(_response_json(response)["choices"][0]["message"]["content"])
        spots: list[dict] = []
        for raw in (data.get("spots") or []):
            if len(spots) >= _MAX_SPOTS:
                break
            try:
                spots.append(SpotItem.model_validate(raw).model_dump())
            except (ValueError, TypeError):
                continue
        if not spots:
            raise ValueError("玩法清单为空")
        raw_summary = data.get("summary")
        summary = str(raw_summary).strip()[:500] if isinstance(raw_summary, str) else ""
    except HTTPException:
        raise
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "模型未返回有效的玩法清单，请稍后重试") from exc
    except ValueError as exc:
        raise HTTPException(502, str(exc) or "模型未返回有效的玩法清单") from exc
    # 保留用户已勾选的进度：按地点名匹配旧 spots 的 booked
    try:
        previous = {str(row.get("name") or "").strip(): bool(row.get("booked"))
                    for row in (json.loads(plan.get("spots_json") or "[]") or [])}
    except (json.JSONDecodeError, TypeError, AttributeError):
        previous = {}
    for spot in spots:
        spot["booked"] = previous.get(str(spot.get("name") or "").strip(), False)
    source = ("Brave 网络搜索 + " if web_results else "") + "LLM"
    await db.execute(
        "UPDATE travel_plans SET spots_json=?,updated_at=datetime('now','localtime') WHERE id=?",
        (json.dumps(spots, ensure_ascii=False), plan_id),
    )
    await db.commit()
    return {"ok": True, "summary": summary, "source": source, "spots": spots}


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
    # 新增偏好字段校验
    assert good.origin_city is None and good.tags == []
    pref = PlanIn(destination="海螺沟", start_date="2026-10-01", end_date="2026-10-04",
                  origin_city="  成都  ", transport_mode="自驾", strategy="度假优先",
                  budget_tier="经济", tags=["温泉", "  自然  ", ""])
    assert pref.origin_city == "成都"
    assert pref.transport_mode == "自驾" and pref.strategy == "度假优先"
    assert pref.tags == ["温泉", "自然"], f"标签应去空白去空值：{pref.tags}"
    for bad_mode in ("步行", "高铁 "):  # 空串视为未设置→None，属合法，不在此列
        try:
            PlanIn(destination="x", start_date="2026-08-01", end_date="2026-08-03", transport_mode=bad_mode)
        except ValidationError:
            continue
        raise AssertionError(f"非法交通方式必须被拒绝：{bad_mode!r}")
    si = SuggestIn(origin_city="成都", transport_mode="高铁", strategy="不网红优先", tags=["温泉"])
    assert si.transport_mode == "高铁" and si.strategy == "不网红优先"
    # DestinationSuggestion 容错：数字/非列表字段不崩
    ds = DestinationSuggestion.model_validate({
        "name": "海螺沟", "region": "四川甘孜", "vibe": 123, "highlights": "不是列表",
        "tags": ["温泉", 7], "transport_note": None,
    })
    assert ds.vibe == "123" and ds.highlights == [] and ds.tags == ["温泉", "7"] and ds.transport_note == ""
    assert ds.transport is None
    ds2 = DestinationSuggestion.model_validate({"name": "海螺沟", "transport": "成都自驾约4小时"})
    assert ds2.transport is None
    # SpotItem 容错
    sp = SpotItem.model_validate({"name": "贡嘎神汤温泉", "type": 5, "duration_hours": 2})
    assert sp.type == "5" and sp.duration_hours == 2.0 and sp.booked is False
    # haversine：成都↔上海约 1660km 量级
    chengdu, shanghai = (104.07, 30.67), (121.47, 31.23)
    km = _haversine_km(chengdu, shanghai)
    assert 1500 < km < 1800, f"成都-上海直线距离应在 1500-1800km，实得 {km}"
    # TransportInfo 默认降级
    ti = TransportInfo(mode="高铁")
    assert ti.accuracy == "LLM 估算" and ti.duration_hours is None
    # _row 解析 spots/tags
    row_like = {"spots_json": '[{"name":"x","booked":true}]', "tags": '["a"]', "packing_json": "[]"}
    parsed = _row(row_like)
    assert parsed["spots"] == [{"name": "x", "booked": True}] and parsed["tags"] == ["a"]
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
    print("travel.py 自检通过：行程偏好字段、目的地推荐模型、玩法模型、高德 haversine/geocode 降级与日期边界正确。")
