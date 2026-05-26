from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from service.config import settings

_db: aiosqlite.Connection | None = None
_SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


async def init_db() -> aiosqlite.Connection:
    global _db
    _db = await aiosqlite.connect(settings.database_path)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(_SCHEMA)
    await _db.commit()
    return _db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def get_db() -> aiosqlite.Connection:
    assert _db is not None, "Database not initialized — call init_db() first"
    return _db


async def fetch_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    db = get_db()
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def fetch_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    db = get_db()
    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def execute(sql: str, params: tuple = ()) -> int:
    db = get_db()
    async with db.execute(sql, params) as cursor:
        await db.commit()
        return cursor.rowcount


async def insert(table: str, data: dict[str, Any]) -> None:
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
    db = get_db()
    await db.execute(sql, tuple(data.values()))
    await db.commit()


async def update(table: str, data: dict[str, Any], where: str, params: tuple = ()) -> int:
    sets = ", ".join(f"{k} = ?" for k in data)
    sql = f"UPDATE {table} SET {sets} WHERE {where}"
    db = get_db()
    async with db.execute(sql, (*data.values(), *params)) as cursor:
        await db.commit()
        return cursor.rowcount


def to_json(obj: Any) -> str:
    return json.dumps(obj, default=str)
