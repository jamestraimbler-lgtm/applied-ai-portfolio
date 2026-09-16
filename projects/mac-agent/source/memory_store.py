#!/usr/bin/env python3
"""
Shared Memory Store — persistent knowledge base for all agents
==============================================================
SQLite-backed key-value store with categories, TTL, and full-text search.
Thread-safe. Every agent imports this as the shared brain.

Usage (Python):
    from memory_store import store, recall, search, list_recent, delete

Usage (CLI):
    python3 memory_store.py set <key> <value> [--category <cat>] [--ttl <hours>]
    python3 memory_store.py get <key>
    python3 memory_store.py search <query> [--category <cat>]
    python3 memory_store.py recent [--limit <n>]
    python3 memory_store.py categories
    python3 memory_store.py delete <key>
"""

import argparse
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone, timedelta

DB_PATH = os.environ.get("MAC_AGENT_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.db"))

VALID_CATEGORIES = {"portfolio", "projects", "preferences", "daily", "system", "creative", "general"}

_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, timeout=10)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


def _init_db():
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            category   TEXT NOT NULL DEFAULT 'general',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
        CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at);

        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            key, value, category,
            content='memories',
            content_rowid='rowid'
        );

        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, key, value, category)
            VALUES (new.rowid, new.key, new.value, new.category);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, key, value, category)
            VALUES ('delete', old.rowid, old.key, old.value, old.category);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, key, value, category)
            VALUES ('delete', old.rowid, old.key, old.value, old.category);
            INSERT INTO memories_fts(rowid, key, value, category)
            VALUES (new.rowid, new.key, new.value, new.category);
        END;
    """)
    conn.commit()


_init_db()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _clean_expired():
    """Remove expired entries."""
    conn = _conn()
    conn.execute("DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?", (_now_iso(),))
    conn.commit()


def store(key: str, value, category: str = "general", ttl_hours: float = None):
    """Store a value. value is JSON-serialized (supports dict, list, str, number)."""
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category '{category}'. Valid: {VALID_CATEGORIES}")

    now = _now_iso()
    expires = None
    if ttl_hours is not None:
        expires = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()

    val_json = json.dumps(value, ensure_ascii=False)
    conn = _conn()
    conn.execute("""
        INSERT INTO memories (key, value, category, created_at, updated_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            category=excluded.category,
            updated_at=excluded.updated_at,
            expires_at=excluded.expires_at
    """, (key, val_json, category, now, now, expires))
    conn.commit()


def recall(key: str):
    """Retrieve by exact key. Returns None if not found or expired."""
    _clean_expired()
    conn = _conn()
    row = conn.execute("SELECT value FROM memories WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    return json.loads(row["value"])


def search(query: str, category: str = None, limit: int = 10) -> list[dict]:
    """Fuzzy text search across keys and values. Returns list of {key, value, category, updated_at}."""
    _clean_expired()
    conn = _conn()
    if category:
        rows = conn.execute("""
            SELECT m.key, m.value, m.category, m.updated_at
            FROM memories_fts f
            JOIN memories m ON m.rowid = f.rowid
            WHERE memories_fts MATCH ? AND m.category = ?
            ORDER BY rank
            LIMIT ?
        """, (query, category, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT m.key, m.value, m.category, m.updated_at
            FROM memories_fts f
            JOIN memories m ON m.rowid = f.rowid
            WHERE memories_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()

    return [
        {"key": r["key"], "value": json.loads(r["value"]),
         "category": r["category"], "updated_at": r["updated_at"]}
        for r in rows
    ]


def list_recent(n: int = 20) -> list[dict]:
    """Most recently updated entries."""
    _clean_expired()
    conn = _conn()
    rows = conn.execute(
        "SELECT key, value, category, updated_at FROM memories ORDER BY updated_at DESC LIMIT ?",
        (n,)
    ).fetchall()
    return [
        {"key": r["key"], "value": json.loads(r["value"]),
         "category": r["category"], "updated_at": r["updated_at"]}
        for r in rows
    ]


def delete(key: str) -> bool:
    """Delete by key. Returns True if found and deleted."""
    conn = _conn()
    cursor = conn.execute("DELETE FROM memories WHERE key = ?", (key,))
    conn.commit()
    return cursor.rowcount > 0


def categories() -> list[str]:
    """List all categories that have entries."""
    conn = _conn()
    rows = conn.execute("SELECT DISTINCT category FROM memories ORDER BY category").fetchall()
    return [r["category"] for r in rows]


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Memory Store CLI")
    sub = parser.add_subparsers(dest="command")

    p_set = sub.add_parser("set", help="Store a value")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--category", "-c", default="general")
    p_set.add_argument("--ttl", type=float, default=None, help="TTL in hours")

    p_get = sub.add_parser("get", help="Retrieve a value")
    p_get.add_argument("key")

    p_search = sub.add_parser("search", help="Search entries")
    p_search.add_argument("query")
    p_search.add_argument("--category", "-c", default=None)
    p_search.add_argument("--limit", "-n", type=int, default=10)

    p_recent = sub.add_parser("recent", help="List recent entries")
    p_recent.add_argument("--limit", "-n", type=int, default=20)

    sub.add_parser("categories", help="List categories")

    p_del = sub.add_parser("delete", help="Delete an entry")
    p_del.add_argument("key")

    args = parser.parse_args()

    if args.command == "set":
        try:
            val = json.loads(args.value)
        except json.JSONDecodeError:
            val = args.value
        store(args.key, val, category=args.category, ttl_hours=args.ttl)
        print(f"Stored: {args.key}")

    elif args.command == "get":
        val = recall(args.key)
        if val is None:
            print(f"Not found: {args.key}")
        else:
            print(json.dumps(val, indent=2) if isinstance(val, (dict, list)) else str(val))

    elif args.command == "search":
        results = search(args.query, category=args.category, limit=args.limit)
        if not results:
            print("No results.")
        for r in results:
            print(f"  [{r['category']}] {r['key']}: {json.dumps(r['value'])[:80]}")

    elif args.command == "recent":
        for r in list_recent(args.limit):
            print(f"  [{r['category']}] {r['key']}: {json.dumps(r['value'])[:80]}")

    elif args.command == "categories":
        cats = categories()
        print(f"Categories with data: {', '.join(cats) if cats else '(none)'}")
        print(f"All valid categories: {', '.join(sorted(VALID_CATEGORIES))}")

    elif args.command == "delete":
        if delete(args.key):
            print(f"Deleted: {args.key}")
        else:
            print(f"Not found: {args.key}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
