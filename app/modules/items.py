"""日用品管理：CRUD + 消耗/购买记录 + 线性预测。无 ORM。"""
import math
from datetime import datetime, date, timedelta

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from app.database import get_db

router = APIRouter()

TARGET_DAYS = 30   # 建议购买数量覆盖的目标周期
BUY_THRESHOLD = 7  # 少于该天数则标记需要购买


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
                 today: date | None = None) -> dict:
    """纯函数预测：日均消耗率 -> 耗尽日期 -> 是否需购买 + 建议数量。

    logs: [{logged_at, amount}, ...] 任意顺序。
    无用量记录时无法预测，返回空预测。
    """
    today = today or date.today()
    if not logs:
        return {
            "daily_rate": 0.0,
            "days_until_empty": None,
            "est_empty_date": None,
            "need_buy": current_stock <= 0,
            "suggested_qty": 0,
        }

    dates = sorted(_parse_date(r["logged_at"]).date() for r in logs)
    total_consumed = sum(r["amount"] for r in logs)
    span_days = (dates[-1] - dates[0]).days
    if span_days <= 0:  # ponytail: 单条记录或同日多条，跨度按 1 天兜底
        span_days = 1
    daily_rate = total_consumed / span_days

    if daily_rate <= 0:
        days_until_empty = None
        est_empty_date = None
        need_buy = current_stock <= 0
    else:
        days_until_empty = current_stock / daily_rate
        est_empty_date = (today + timedelta(days=days_until_empty)).isoformat()
        need_buy = days_until_empty < BUY_THRESHOLD

    suggested_qty = max(0, math.ceil(daily_rate * TARGET_DAYS - current_stock))
    if not need_buy:
        suggested_qty = 0
    return {
        "daily_rate": round(daily_rate, 4),
        "days_until_empty": round(days_until_empty, 2) if days_until_empty is not None else None,
        "est_empty_date": est_empty_date,
        "need_buy": need_buy,
        "suggested_qty": suggested_qty,
    }


async def _load_logs(db, item_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT logged_at, amount FROM usage_logs WHERE item_id=? ORDER BY logged_at",
        (item_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def _item_with_prediction(db, row) -> dict:
    item = dict(row)
    logs = await _load_logs(db, item["id"])
    item["prediction"] = predict_item(logs, item["current_stock"])
    return item


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
    cur = await db.execute(
        "INSERT INTO items(name,category,unit,current_stock,min_stock) VALUES(?,?,?,?,?)",
        (payload.name, payload.category, payload.unit, payload.current_stock, payload.min_stock),
    )
    await db.commit()
    return {"id": cur.lastrowid}


@router.put("/items/{item_id}")
async def update_item(item_id: int, payload: ItemPatch, db=Depends(get_db)):
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "无更新字段")
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
    cur = await db.execute("SELECT current_stock FROM items WHERE id=?", (item_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "物品不存在")
    logged_at = payload.logged_at or datetime.now().isoformat(timespec="seconds")
    await db.execute(
        "INSERT INTO usage_logs(item_id,amount,logged_at,note) VALUES(?,?,?,?)",
        (item_id, payload.amount, logged_at, payload.note),
    )
    await db.execute(
        "UPDATE items SET current_stock=current_stock-? WHERE id=?",
        (payload.amount, item_id),
    )
    await db.commit()
    return {"item_id": item_id, "consumed": payload.amount,
            "current_stock": row["current_stock"] - payload.amount}


@router.post("/items/{item_id}/purchase")
async def log_purchase(item_id: int, payload: PurchaseIn, db=Depends(get_db)):
    cur = await db.execute("SELECT current_stock FROM items WHERE id=?", (item_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "物品不存在")
    purchased_at = payload.purchased_at or datetime.now().isoformat(timespec="seconds")
    await db.execute(
        "INSERT INTO purchase_logs(item_id,amount,price,purchased_at,note) VALUES(?,?,?,?,?)",
        (item_id, payload.amount, payload.price, purchased_at, payload.note),
    )
    await db.execute(
        "UPDATE items SET current_stock=current_stock+? WHERE id=?",
        (payload.amount, item_id),
    )
    await db.commit()
    return {"item_id": item_id, "purchased": payload.amount,
            "current_stock": row["current_stock"] + payload.amount}


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
    # 自检：用样例数据验证预测数学。

    today = date(2026, 7, 12)

    # 场景1：10 天消耗 20，日均 2.0；库存 14 -> 7 天耗尽 -> 不需购买
    logs1 = [
        {"logged_at": "2026-07-02", "amount": 10},
        {"logged_at": "2026-07-12", "amount": 10},
    ]
    p1 = predict_item(logs1, 14, today)
    assert p1["daily_rate"] == 2.0, p1
    assert p1["days_until_empty"] == 7.0, p1
    assert p1["need_buy"] is False, p1  # 7 不小于 7
    assert p1["suggested_qty"] == 0, p1
    assert p1["est_empty_date"] == "2026-07-19", p1

    # 场景2：库存 6 -> 3 天耗尽 -> 需购买；建议 ceil(2*30-6)=54
    p2 = predict_item(logs1, 6, today)
    assert p2["days_until_empty"] == 3.0, p2
    assert p2["need_buy"] is True, p2
    assert p2["suggested_qty"] == 54, p2

    # 场景3：无用量记录 -> 无法预测，空库存才需购买
    p3 = predict_item([], 5, today)
    assert p3["daily_rate"] == 0.0 and p3["days_until_empty"] is None, p3
    assert p3["need_buy"] is False, p3
    p3b = predict_item([], 0, today)
    assert p3b["need_buy"] is True, p3b

    # 场景4：单条记录 -> 跨度兜底 1 天，日均=该条 amount
    p4 = predict_item([{"logged_at": "2026-07-10", "amount": 5}], 5, today)
    assert p4["daily_rate"] == 5.0, p4
    assert p4["days_until_empty"] == 1.0, p4
    assert p4["need_buy"] is True, p4

    print("items.py 自检通过：预测数学正确。")
