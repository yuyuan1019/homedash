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
    location TEXT,
    expires_at TEXT,
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
    stage TEXT,
    session_id TEXT,
    llm_model TEXT,
    llm_reply TEXT,
    confidence TEXT,
    duration_ms INTEGER,
    error TEXT,
    before_json TEXT,
    after_json TEXT,
    reverted INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS device_preferences (
    device_name TEXT PRIMARY KEY,
    hidden INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER,
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now')),
    last_seen_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);
"""

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        await init_db()
    return _db


async def _ensure_columns(db, table: str, columns: dict[str, str]) -> None:
    """对已有库补列：CREATE TABLE IF NOT EXISTS 不会改旧表结构，需 ALTER 容错。"""
    cur = await db.execute(f"PRAGMA table_info({table})")
    existing = {row["name"] for row in await cur.fetchall()}
    for col, decl in columns.items():
        if col not in existing:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


async def init_db() -> None:
    global _db
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _ensure_columns(_db, "items", {"location": "TEXT", "expires_at": "TEXT"})
    await _ensure_columns(_db, "device_preferences", {"sort_order": "INTEGER"})
    await _ensure_columns(_db, "ai_audit", {
        "stage": "TEXT", "session_id": "TEXT", "llm_model": "TEXT",
        "llm_reply": "TEXT", "confidence": "TEXT", "duration_ms": "INTEGER",
        "error": "TEXT", "before_json": "TEXT", "after_json": "TEXT",
        "reverted": "INTEGER DEFAULT 0",
    })
    await _db.commit()
