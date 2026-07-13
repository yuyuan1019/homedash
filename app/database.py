"""SQLite 异步连接与表初始化。无 ORM，直接 SQL。"""
import os
import aiosqlite

DB_PATH = "data/homedash.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    unit TEXT DEFAULT '个',
    current_stock REAL DEFAULT 0,
    min_stock REAL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS usage_logs (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    logged_at TEXT DEFAULT (datetime('now')),
    note TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id)
);
CREATE TABLE IF NOT EXISTS purchase_logs (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    price REAL,
    purchased_at TEXT DEFAULT (datetime('now')),
    note TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id)
);
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    note TEXT,
    priority TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'open',
    due_date TEXT,
    assignee TEXT,
    remind_at TEXT,
    remind_channels TEXT,
    remind_repeat TEXT,
    external_ref TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ai_audit (
    id INTEGER PRIMARY KEY,
    raw_text TEXT,
    actions_json TEXT,
    results_json TEXT,
    ok INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS device_preferences (
    device_name TEXT PRIMARY KEY,
    hidden INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        await init_db()
    return _db


async def init_db() -> None:
    global _db
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.commit()
