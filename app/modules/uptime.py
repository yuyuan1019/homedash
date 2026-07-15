"""Uptime Kuma 对接：直读 SQLite，60s 缓存。文件缺失则返回空。"""
import asyncio
import json
import os
import sqlite3
import time

from fastapi import APIRouter

router = APIRouter()

KUMA_DB_PATH = os.getenv("KUMA_DB_PATH", "/data/kuma.db")
APP_CONFIG_FILE = "data/app_config.json"
_REFRESH = 60  # 秒

_cache: dict = {"data": [], "ts": 0.0, "available": False}


def _fetch() -> list[dict]:
    if not os.path.isfile(KUMA_DB_PATH):
        return []
    # ponytail: read-only + uri mode 避免锁竞争
    con = sqlite3.connect(f"file:{KUMA_DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT m.id, m.name, m.url, h.status, h.msg, h.ping, h.time "
            "FROM monitor m LEFT JOIN heartbeat h ON h.monitor_id = m.id "
            "WHERE h.id = (SELECT MAX(id) FROM heartbeat WHERE monitor_id = m.id)"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _public_url() -> str:
    if os.getenv("KUMA_PUBLIC_URL"):
        return os.getenv("KUMA_PUBLIC_URL", "").rstrip("/")
    try:
        with open(APP_CONFIG_FILE) as f:
            return str(json.load(f).get("kuma_public_url", "")).rstrip("/")
    except (OSError, json.JSONDecodeError):
        return ""


async def _refresh_if_stale() -> None:
    if time.time() - _cache["ts"] < _REFRESH:
        return
    try:
        data = await asyncio.to_thread(_fetch)
        _cache["data"] = data
        _cache["available"] = True
    except Exception:
        pass  # ponytail: 读失败保留旧缓存，下次再试
    _cache["ts"] = time.time()


@router.on_event("startup")
async def _startup() -> None:
    await _refresh_if_stale()


@router.get("/uptime/status")
async def status():
    await _refresh_if_stale()
    return {
        "monitors": _cache["data"],
        "available": _cache["available"],
        "source": os.path.isfile(KUMA_DB_PATH) and "sqlite" or "unavailable",
        "public_url": _public_url(),
    }


if __name__ == "__main__":
    # 自检：无 DB 文件时返回空且不报错
    result = _fetch()
    assert isinstance(result, list)
    print(f"uptime.py 自检通过：DB={'存在' if os.path.isfile(KUMA_DB_PATH) else '不存在'}，返回 {len(result)} 条。")
