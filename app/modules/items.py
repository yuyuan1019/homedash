"""日用品管理：CRUD + 消耗/购买记录 + EWMA 预测 + 多图。无 ORM。"""
import asyncio
import json
import math
import statistics
from datetime import datetime, date, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Depends, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.modules import image_store

router = APIRouter()
_ITEM_IMAGES_DIR = Path("data/item_images")

TARGET_DAYS = 30          # 默认建议购买数量覆盖的目标周期
BUY_THRESHOLD = 7         # 少于该天数则标记需要购买
EWMA_ALPHA = 0.35         # 近期消耗记录的权重
LEAD_DAYS = 3             # 网购到货缓冲天数
MIN_USAGE_FOR_EWMA = 2    # 至少两条记录才按区间速率计算 EWMA

# 根据物品类别智能调整建议购买天数
CATEGORY_TARGET_DAYS = {
    "食品": 7,              # 鸡蛋、面包等易腐食品，建议7天量
    "生鲜": 7,              # 新鲜食材，建议7天量
    "冷冻": 14,             # 冷冻食品，建议14天量
    "饮料": 14,             # 啤酒、饮料等，建议14天量
    "速食": 14,             # 方便面等，建议14天量
    "纸品": 30,             # 卫生纸、抽纸等，建议30天量
    "洗护": 30,             # 洗发水、沐浴露等，建议30天量
    "清洁": 30,             # 清洁用品，建议30天量
    "宠物": 30,             # 宠物用品，建议30天量
}

# ponytail: 两口之家冷启动粗略先验，真实 usage 达到三条后完全由 EWMA 覆盖。
CATEGORY_PRIORS = {
    "纸品": 0.15,
    "洗护": 0.03,
    "清洁": 0.05,
    "宠物": 0.05,
    "冷冻": 0.1,
    "食品": 0.5,           # 食品类消耗较快
    "生鲜": 0.3,           # 生鲜消耗适中
    "饮料": 0.2,           # 饮料消耗适中
    "速食": 0.1,           # 速食消耗较慢
}

# 表单下拉的冷启动默认值；与运行库去重值合并后供前端 datalist 使用
DEFAULT_CATEGORIES = ("纸品", "洗护", "清洁", "厨房", "宠物", "冷冻", "药品", "其他")
DEFAULT_UNITS = ("个", "瓶", "袋", "盒", "包", "卷", "提", "箱", "罐", "块", "kg", "L")


class ItemIn(BaseModel):
    name: str
    category: Optional[str] = None
    unit: str = "个"
    current_stock: float = 0
    min_stock: float = 1
    location: Optional[str] = None
    expires_at: Optional[str] = None


class ItemPatch(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    current_stock: Optional[float] = None
    min_stock: Optional[float] = None
    location: Optional[str] = None
    expires_at: Optional[str] = None


class UsageIn(BaseModel):
    amount: float
    note: Optional[str] = None
    logged_at: Optional[str] = None  # ISO 格式，缺省用现在


class PurchaseIn(BaseModel):
    amount: float
    price: Optional[float] = None
    note: Optional[str] = None
    purchased_at: Optional[str] = None


def _parse_date(s: str) -> datetime:
    return datetime.fromisoformat(s.split()[0] if " " in s else s)


def predict_item(logs: list[dict], current_stock: float,
                 today: date | None = None, category: str | None = None,
                 min_stock: float = 1.0,
                 purchases: list[dict] | None = None) -> dict:
    """纯函数预测：EWMA 消耗率、安全库存与冷启动兜底。

    logs / purchases 均可任意排序。多条 usage 时，最早记录只作区间时间锚点，
    避免把未知跨度的首条记录误当作一天消耗而抬高预测。
    """
    today = today or date.today()
    usage = sorted(logs, key=lambda row: _parse_date(row["logged_at"]))
    purchase_rows = sorted(
        purchases or [], key=lambda row: _parse_date(row["purchased_at"])
    )
    usage_count = len(usage)
    daily_rate = 0.0
    method = "none"
    days_until_empty = None

    if usage_count >= MIN_USAGE_FOR_EWMA:
        # 首条没有前序消费时间，故仅用它确定第二条的区间起点。
        previous_date = _parse_date(usage[0]["logged_at"]).date()
        for index, row in enumerate(usage[1:]):
            current_date = _parse_date(row["logged_at"]).date()
            interval_rate = row["amount"] / max(1, (current_date - previous_date).days)
            daily_rate = (
                interval_rate
                if index == 0
                else EWMA_ALPHA * interval_rate + (1 - EWMA_ALPHA) * daily_rate
            )
            previous_date = current_date
        method = "ewma"
    elif len(purchase_rows) >= 2:
        purchase_dates = [_parse_date(row["purchased_at"]).date() for row in purchase_rows]
        intervals = [
            max(1, (later - earlier).days)
            for earlier, later in zip(purchase_dates, purchase_dates[1:])
        ]
        interval_days = statistics.median(intervals)
        last_purchase = purchase_rows[-1]
        last_purchase_date = purchase_dates[-1]
        daily_rate = last_purchase["amount"] / interval_days
        days_until_empty = (last_purchase_date + timedelta(days=interval_days) - today).days
        method = "purchase_interval"
    elif usage_count <= 1 and category in CATEGORY_PRIORS:
        # 0 或 1 条消耗记录都算不出区间速率：用品类先验给一个保守消耗率，
        # 不再把单笔记录的数量当作「一天消耗完」而虚高触发紧急补货。
        daily_rate = CATEGORY_PRIORS[category]
        method = "category_prior"
    elif min_stock > 0:
        method = "min_stock_only"

    if daily_rate > 0 and days_until_empty is None:
        days_until_empty = current_stock / daily_rate

    est_empty_date = (
        (today + timedelta(days=days_until_empty)).isoformat()
        if days_until_empty is not None else None
    )
    safety_stock = max(min_stock, daily_rate * LEAD_DAYS)
    need_buy = (
        current_stock <= 0
        or current_stock < safety_stock
        or (days_until_empty is not None and days_until_empty < BUY_THRESHOLD)
    )

    # 根据类别智能调整建议购买天数
    target_days = CATEGORY_TARGET_DAYS.get(category, TARGET_DAYS)
    suggested_qty = max(0, math.ceil(daily_rate * target_days - current_stock)) if need_buy else 0

    if usage_count >= 6:
        confidence = "high"
    elif usage_count >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "daily_rate": round(daily_rate, 4),
        "days_until_empty": round(days_until_empty, 2) if days_until_empty is not None else None,
        "est_empty_date": est_empty_date,
        "need_buy": need_buy,
        "suggested_qty": suggested_qty,
        "confidence": confidence,
        "method": method,
        "safety_stock": round(safety_stock, 4),
    }


async def _load_logs(db, item_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT logged_at, amount FROM usage_logs WHERE item_id=? ORDER BY logged_at",
        (item_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def _load_purchases(db, item_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT purchased_at, amount FROM purchase_logs WHERE item_id=? ORDER BY purchased_at",
        (item_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def _item_with_prediction(db, row, include_images: bool = True) -> dict:
    item = dict(row)
    raw_images = item.pop("images", None)
    # 列表只回 has_images 布尔（保持轻量、不泄露文件名）；详情回完整 images 数组
    decoded = image_store.decode_images(raw_images)
    if include_images:
        item["images"] = decoded
    else:
        item["has_images"] = bool(decoded)
    logs = await _load_logs(db, item["id"])
    purchases = await _load_purchases(db, item["id"])
    item["prediction"] = predict_item(
        logs,
        item["current_stock"],
        category=item["category"],
        min_stock=item["min_stock"],
        purchases=purchases,
    )
    return item


async def _get_item(db, item_id: int):
    cur = await db.execute("SELECT * FROM items WHERE id=?", (item_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "物品不存在")
    return row


async def create_item_record(db, data: dict) -> int:
    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "物品名称不能为空")
    cur = await db.execute(
        "INSERT INTO items(name,category,unit,current_stock,min_stock,location,expires_at) VALUES(?,?,?,?,?,?,?)",
        (name, data.get("category"), data.get("unit") or "个",
         data.get("current_stock", 0), data.get("min_stock", 1),
         data.get("location"), data.get("expires_at")),
    )
    await db.commit()
    return cur.lastrowid


async def purchase_item_record(db, item_id: int, amount: float, note: str | None = None) -> dict:
    row = await _get_item(db, item_id)
    if amount <= 0:
        raise HTTPException(400, "购买数量必须大于 0")
    now = datetime.now().isoformat(timespec="seconds")
    await db.execute("INSERT INTO purchase_logs(item_id,amount,purchased_at,note) VALUES(?,?,?,?)", (item_id, amount, now, note))
    await db.execute("UPDATE items SET current_stock=current_stock+? WHERE id=?", (amount, item_id))
    await db.commit()
    return {"item_id": item_id, "current_stock": row["current_stock"] + amount}


async def usage_item_record(db, item_id: int, amount: float, note: str | None = None) -> dict:
    row = await _get_item(db, item_id)
    if amount <= 0:
        raise HTTPException(400, "消耗数量必须大于 0")
    now = datetime.now().isoformat(timespec="seconds")
    await db.execute("INSERT INTO usage_logs(item_id,amount,logged_at,note) VALUES(?,?,?,?)", (item_id, amount, now, note))
    await db.execute("UPDATE items SET current_stock=current_stock-? WHERE id=?", (amount, item_id))
    await db.commit()
    return {"item_id": item_id, "current_stock": row["current_stock"] - amount}


async def set_item_stock(db, item_id: int, current_stock: float) -> dict:
    await _get_item(db, item_id)
    if current_stock < 0:
        raise HTTPException(400, "库存不能小于 0")
    await db.execute("UPDATE items SET current_stock=? WHERE id=?", (current_stock, item_id))
    await db.commit()
    return {"item_id": item_id, "current_stock": current_stock}


async def update_item_record(db, item_id: int, fields: dict) -> dict:
    await _get_item(db, item_id)
    allowed = {key: fields[key] for key in ("name", "unit", "category", "min_stock", "location", "expires_at") if key in fields}
    if not allowed:
        raise HTTPException(400, "无更新字段")
    sets = ", ".join(f"{key}=?" for key in allowed)
    await db.execute(f"UPDATE items SET {sets} WHERE id=?", (*allowed.values(), item_id))
    await db.commit()
    return {"item_id": item_id}


@router.get("/items/predictions")
async def all_predictions(db=Depends(get_db)):
    """全部预测汇总 + 购买建议。"""
    cur = await db.execute("SELECT * FROM items")
    rows = await cur.fetchall()
    buy, ok = [], []
    for row in rows:
        item = await _item_with_prediction(db, row, include_images=False)
        (buy if item["prediction"]["need_buy"] else ok).append(item)
    buy.sort(key=lambda x: x["prediction"]["days_until_empty"] or 0)
    return {"need_buy": buy, "sufficient": ok}


@router.get("/items")
async def list_items(db=Depends(get_db)):
    cur = await db.execute("SELECT * FROM items ORDER BY id")
    return [await _item_with_prediction(db, r, include_images=False) for r in await cur.fetchall()]


@router.post("/items")
async def create_item(payload: ItemIn, db=Depends(get_db)):
    return {"id": await create_item_record(db, payload.model_dump())}


@router.get("/items/facets")
async def item_facets(db=Depends(get_db)):
    """表单下拉候选：分类/单位/存放地点（均按使用频次降序去重）+ 冷启动默认值。
    必须注册在 `/items/{item_id}` 之前，否则 FastAPI 会把 "facets" 当 int 解析报 422。"""
    async def _distinct(col: str) -> list[str]:
        # col 是本函数内硬编码字面量，非用户输入，拼接安全
        cur = await db.execute(
            f"SELECT {col} AS v FROM items WHERE {col} IS NOT NULL AND {col} != '' "
            f"GROUP BY {col} ORDER BY COUNT(*) DESC, {col} ASC"
        )
        return [row["v"] for row in await cur.fetchall()]

    return {
        "categories": await _distinct("category"),
        "units": await _distinct("unit"),
        "locations": await _distinct("location"),
        "defaults": {"categories": list(DEFAULT_CATEGORIES), "units": list(DEFAULT_UNITS)},
    }


@router.get("/items/{item_id}")
async def get_item(item_id: int, db=Depends(get_db)):
    return await _item_with_prediction(db, await _get_item(db, item_id))


@router.put("/items/{item_id}")
async def update_item(item_id: int, payload: ItemPatch, db=Depends(get_db)):
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "无更新字段")
    await _get_item(db, item_id)
    sets = ", ".join(f"{k}=?" for k in fields)
    await db.execute(f"UPDATE items SET {sets} WHERE id=?", (*fields.values(), item_id))
    await db.commit()
    cur = await db.execute("SELECT * FROM items WHERE id=?", (item_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "物品不存在")
    return dict(row)


@router.delete("/items/{item_id}")
async def delete_item(item_id: int, db=Depends(get_db)):
    async with image_store.images_lock():
        row = await _get_item(db, item_id)
        images = image_store.decode_images(row["images"]) if "images" in row.keys() else []
        await db.execute("DELETE FROM usage_logs WHERE item_id=?", (item_id,))
        await db.execute("DELETE FROM purchase_logs WHERE item_id=?", (item_id,))
        await db.execute("DELETE FROM items WHERE id=?", (item_id,))
        await db.commit()
    # DB 已提交后文件删除 best-effort：不阻断删除（同 todos）
    for image in images:
        await image_store.safe_unlink(_ITEM_IMAGES_DIR / image["filename"])
    return {"deleted": item_id}


@router.post("/items/{item_id}/images")
async def upload_item_image(item_id: int, image: UploadFile = File(...), db=Depends(get_db)):
    await _get_item(db, item_id)  # 404 if missing
    content_type = (image.content_type or "").lower()
    if content_type not in image_store.IMAGE_TYPES:
        raise HTTPException(400, "仅支持 JPG、PNG、GIF 或 WebP 图片")
    await asyncio.to_thread(_ITEM_IMAGES_DIR.mkdir, parents=True, exist_ok=True)
    image_id = uuid4().hex
    tmp_path = _ITEM_IMAGES_DIR / f"{item_id}_{image_id}.upload"
    extension = await image_store.save_upload(image, tmp_path)
    final_filename = f"{item_id}_{image_id}{extension}"
    final_path = _ITEM_IMAGES_DIR / final_filename
    committed = False
    try:
        if tmp_path != final_path:
            try:
                await asyncio.to_thread(tmp_path.rename, final_path)
            except OSError:
                await image_store.safe_unlink(tmp_path)
                raise HTTPException(400, "图片保存失败，请重试")
        # 锁内做 images 列的读-改-写，避免并发覆写丢图
        async with image_store.images_lock():
            row = await _get_item(db, item_id)
            images = image_store.decode_images(row["images"]) if "images" in row.keys() else []
            if len(images) >= image_store.MAX_IMAGES_PER_ROW:
                raise HTTPException(400, f"每个物品最多上传 {image_store.MAX_IMAGES_PER_ROW} 张图片")
            images = [*images, {"id": image_id, "filename": final_filename,
                                "content_type": image_store.EXT_TO_TYPE[extension]}]
            await db.execute("UPDATE items SET images=? WHERE id=?", (json.dumps(images, ensure_ascii=False), item_id))
            await db.commit()
            committed = True
    except BaseException:
        # 仅在尚未提交时回收文件：commit 成功后即便客户端断连也不删，避免悬空 404
        if not committed:
            await image_store.safe_unlink(final_path)
        raise
    return await _item_with_prediction(db, await _get_item(db, item_id))


@router.get("/items/{item_id}/images/{image_id}")
async def get_item_image(item_id: int, image_id: str, db=Depends(get_db)):
    cur = await db.execute("SELECT images FROM items WHERE id=?", (item_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "物品不存在")
    image = next((i for i in image_store.decode_images(row["images"]) if i["id"] == image_id), None)
    if not image:
        raise HTTPException(404, "图片不存在")
    path = _ITEM_IMAGES_DIR / image["filename"]
    # 一次性读出全部字节再构造响应，避免 FileResponse 与并发删除之间的 TOCTOU（同 todos）
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError:
        raise HTTPException(404, "图片文件不存在")
    except OSError:
        raise HTTPException(500, "读取图片失败")
    return Response(content=data, media_type=image.get("content_type") or "application/octet-stream",
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"})


@router.delete("/items/{item_id}/images/{image_id}")
async def delete_item_image(item_id: int, image_id: str, db=Depends(get_db)):
    async with image_store.images_lock():
        row = await _get_item(db, item_id)
        images = image_store.decode_images(row["images"]) if "images" in row.keys() else []
        target = next((i for i in images if i["id"] == image_id), None)
        if not target:
            raise HTTPException(404, "图片不存在")
        remaining = [i for i in images if i["id"] != image_id]
        await db.execute("UPDATE items SET images=? WHERE id=?", (json.dumps(remaining, ensure_ascii=False), item_id))
        await db.commit()
        filename = target["filename"]
        updated = await _item_with_prediction(db, await _get_item(db, item_id))
    # DB 已提交，文件删除 best-effort（同 todos）
    await image_store.safe_unlink(_ITEM_IMAGES_DIR / filename)
    return updated


@router.post("/items/{item_id}/usage")
async def log_usage(item_id: int, payload: UsageIn, db=Depends(get_db)):
    result = await usage_item_record(db, item_id, payload.amount, payload.note)
    return {**result, "consumed": payload.amount}


@router.post("/items/{item_id}/purchase")
async def log_purchase(item_id: int, payload: PurchaseIn, db=Depends(get_db)):
    result = await purchase_item_record(db, item_id, payload.amount, payload.note)
    return {**result, "purchased": payload.amount}


@router.get("/items/{item_id}/history")
async def item_history(item_id: int, db=Depends(get_db)):
    cur = await db.execute("SELECT id FROM items WHERE id=?", (item_id,))
    if not await cur.fetchone():
        raise HTTPException(404, "物品不存在")
    cur = await db.execute(
        "SELECT 'usage' AS type, id, amount, logged_at AS at, note FROM usage_logs "
        "WHERE item_id=? UNION ALL "
        "SELECT 'purchase' AS type, id, amount, purchased_at AS at, note FROM purchase_logs "
        "WHERE item_id=? ORDER BY at",
        (item_id, item_id),
    )
    return [dict(r) for r in await cur.fetchall()]


if __name__ == "__main__":
    # 自检：覆盖 EWMA、安全库存、冷启动和旧字段兼容。

    today = date(2026, 7, 22)

    # 多条用量按相邻区间 EWMA，首条仅作时间锚点，结果不同于全历史平均。
    logs1 = [
        {"logged_at": "2026-07-01", "amount": 2},
        {"logged_at": "2026-07-03", "amount": 4},
        {"logged_at": "2026-07-04", "amount": 1},
    ]
    p1 = predict_item(logs1, 20, today)
    assert p1["daily_rate"] == 1.65, p1  # 2.0 -> 0.35 * 1.0 + 0.65 * 2.0
    assert p1["daily_rate"] != round(7 / 3, 4), p1
    assert p1["method"] == "ewma" and p1["confidence"] == "medium", p1

    # 库存虽可覆盖很久，但低于明确安全库存时仍必须购买。
    slow_logs = [
        {"logged_at": "2026-07-01", "amount": 1},
        {"logged_at": "2026-07-11", "amount": 1},
    ]
    p2 = predict_item(slow_logs, 4, today, min_stock=5)
    assert p2["days_until_empty"] == 40.0, p2
    assert p2["safety_stock"] == 5 and p2["need_buy"] is True, p2

    # 无用量时可由最低库存单独触发提醒，也不会伪造消耗率。
    p3 = predict_item([], 0.5, today, min_stock=1)
    assert p3["daily_rate"] == 0.0 and p3["method"] == "min_stock_only", p3
    assert p3["need_buy"] is True and p3["suggested_qty"] == 0, p3

    # 冷冻食品近期脉冲消耗应比全历史均值更接近近期记录。
    frozen_logs = [
        {"logged_at": "2026-07-01", "amount": 1},
        {"logged_at": "2026-07-11", "amount": 1},
        {"logged_at": "2026-07-12", "amount": 5},
    ]
    p4 = predict_item(frozen_logs, 20, today, category="冷冻")
    assert p4["daily_rate"] == 1.815 and p4["daily_rate"] > round(7 / 11, 4), p4

    # 无 usage 且有两次以上购买时，使用购买间隔预测下次补货窗口。
    purchases = [
        {"purchased_at": "2026-07-01", "amount": 10},
        {"purchased_at": "2026-07-11", "amount": 10},
        {"purchased_at": "2026-07-21", "amount": 10},
    ]
    p5 = predict_item([], 10, today, purchases=purchases)
    assert p5["method"] == "purchase_interval" and p5["days_until_empty"] == 9.0, p5

    # 冷启动品类先验与旧调用方字段均可用。
    p6 = predict_item([], 2, today, category="纸品")
    assert p6["method"] == "category_prior" and p6["daily_rate"] == 0.15, p6
    for field in ("daily_rate", "days_until_empty", "est_empty_date", "need_buy", "suggested_qty"):
        assert field in p6, p6

    # 单条消耗记录不再被当作「一天消耗完」虚高速率：库存高于最低值时不应触发紧急
    single = predict_item([{"logged_at": "2026-07-10", "amount": 5}], 5, today, category="饮料", min_stock=2)
    assert single["method"] == "category_prior" and single["daily_rate"] == 0.2, single
    assert single["need_buy"] is False, single  # 库存 5 > 最低 2：单条记录不应标红

    # 表单下拉默认值齐备
    assert len(DEFAULT_CATEGORIES) == 8 and "纸品" in DEFAULT_CATEGORIES
    assert "个" in DEFAULT_UNITS

    # 图片 decode 兼容旧库：images 列为 NULL/缺列/非法 JSON 时都返回空 list
    assert image_store.decode_images(None) == []
    assert image_store.decode_images("not json") == []
    assert image_store.decode_images('[{"id":"i","filename":"a.png"}]')[0]["id"] == "i"

    print("items.py 自检通过：EWMA、安全库存与冷启动预测正确。")
