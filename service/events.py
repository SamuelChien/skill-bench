from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, AsyncGenerator

from service import db

_listeners: dict[str, list[asyncio.Event]] = defaultdict(list)


async def emit_event(job_id: str, event_type: str, data: dict[str, Any] | None = None) -> None:
    await db.insert("job_events", {
        "job_id": job_id,
        "event_type": event_type,
        "data_json": db.to_json(data or {}),
    })
    for event in _listeners.get(job_id, []):
        event.set()


async def event_stream(job_id: str) -> AsyncGenerator[str, None]:
    last_id = 0
    notify = asyncio.Event()
    _listeners[job_id].append(notify)

    try:
        while True:
            rows = await db.fetch_all(
                "SELECT * FROM job_events WHERE job_id = ? AND id > ? ORDER BY id",
                (job_id, last_id),
            )

            for row in rows:
                last_id = row["id"]
                payload = json.dumps({
                    "event": row["event_type"],
                    "data": json.loads(row["data_json"]),
                })
                yield f"data: {payload}\n\n"

            job = await db.fetch_one("SELECT status FROM jobs WHERE id = ?", (job_id,))
            if job and job["status"] in ("completed", "failed", "cancelled"):
                yield f"data: {json.dumps({'event': 'done', 'data': {'status': job['status']}})}\n\n"
                break

            notify.clear()
            try:
                await asyncio.wait_for(notify.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        _listeners[job_id].remove(notify)
        if not _listeners[job_id]:
            del _listeners[job_id]
