"""日用品管理：CRUD + 消耗/购买记录 + EWMA 预测。无 ORM。"""
import math
import statistics
from datetime import datetime, date, timedelta

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from app.database import get_db

router = APIRouter()

TARGET_DAYS = 30          # 建议购买数量覆盖的目标周期
BUY_THRESHOLD = 7         # 少于该天数则标记需要购买
EWMA_ALPHA = 0.35         # 近期消耗记录的权重
LEAD_DAYS = 3             # 网购到货缓冲天数
MIN_USAGE_FOR_EWMA = 2    # 至少两条记录才按区间速率计算 EWMA

# ponytail: 两口之家冷启动粗略先验，真实 usage 达到三条后完全由 EWMA 覆盖。
CATEGORY_PRIORS = {
    "纸品": 0.15,
    "洗护": 0.03,
    "清洁": 0.05,
    "宠物": 0.05,
    "冷冻": 0.1,
}


class ItemIn(BaseModel):
    name: str
    category: Optional[str] = None
    unit: str = "个"
    current_stock: float = 0
    min_stock: float = 1


class ItemPatch(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    current_stock: Optional[float] = None
    min_stock: Optional[float] = None


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
    elif usage_count == 1:
        # ponytail: 单条记录没有时间跨度，沿用原先按一天计算的保守兜底。
        daily_rate = usage[0]["amount"]
        method = "ewma"
    elif usage_count == 0 and category in CATEGORY_PRIORS:
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
    suggested_qty = max(0, math.ceil(daily_rate * TARGET_DAYS - current_stock)) if need_buy else 0

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


async def _item_with_prediction(db, row) -> dict:
    item = dict(row)
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
    cur = await db.execute(
        "INSERT INTO items(name,category,unit,current_stock,min_stock) VALUES(?,?,?,?,?)",
        (data["name"].strip(), data.get("category"), data.get("unit") or "个",
         data.get("current_stock", 0), data.get("min_stock", 1)),
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
    allowed = {key: fields[key] for key in ("name", "unit", "category", "min_stock") if key in fields}
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
        item = await _item_with_prediction(db, row)
        (buy if item["prediction"]["need_buy"] else ok).append(item)
    buy.sort(key=lambda x: x["prediction"]["days_until_empty"] or 0)
    return {"need_buy": buy, "sufficient": ok}


@router.get("/items")
async def list_items(db=Depends(get_db)):
    cur = await db.execute("SELECT * FROM items ORDER BY id")
    return [await _item_with_prediction(db, r) for r in await cur.fetchall()]


@router.post("/items")
async def create_item(payload: ItemIn, db=Depends(get_db)):
    return {"id": await create_item_record(db, payload.model_dump())}


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
    await db.execute("DELETE FROM usage_logs WHERE item_id=?", (item_id,))
    await db.execute("DELETE FROM purchase_logs WHERE item_id=?", (item_id,))
    await db.execute("DELETE FROM items WHERE id=?", (item_id,))
    await db.commit()
    return {"deleted": item_id}


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

    print("items.py 自检通过：EWMA、安全库存与冷启动预测正确。")
