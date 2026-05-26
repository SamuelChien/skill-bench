from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from service import db
from service.models.tasks import TaskCreate, TaskResponse, TaskUpdate

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def _row_to_response(row: dict) -> TaskResponse:
    return TaskResponse(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        turns=json.loads(row["turns_json"]),
        assertions=json.loads(row["assertions_json"]),
        tools=json.loads(row["tools_json"]),
        tags=json.loads(row["tags_json"]),
        timeout_seconds=row["timeout_seconds"],
        model=row["model"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(body: TaskCreate):
    existing = await db.fetch_one("SELECT id FROM tasks WHERE id = ?", (body.id,))
    if existing:
        raise HTTPException(409, f"Task '{body.id}' already exists")

    await db.insert("tasks", {
        "id": body.id,
        "name": body.name,
        "description": body.description,
        "turns_json": db.to_json([t.model_dump() for t in body.turns]),
        "assertions_json": db.to_json([a.model_dump() for a in body.assertions]),
        "tools_json": db.to_json([t.model_dump() for t in body.tools]),
        "tags_json": db.to_json(body.tags),
        "timeout_seconds": body.timeout_seconds,
        "model": body.model,
    })

    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (body.id,))
    return _row_to_response(row)


@router.get("", response_model=list[TaskResponse])
async def list_tasks(tag: str | None = None):
    if tag:
        rows = await db.fetch_all(
            "SELECT * FROM tasks WHERE tags_json LIKE ? ORDER BY id",
            (f'%"{tag}"%',),
        )
    else:
        rows = await db.fetch_all("SELECT * FROM tasks ORDER BY id")
    return [_row_to_response(r) for r in rows]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if not row:
        raise HTTPException(404, f"Task '{task_id}' not found")
    return _row_to_response(row)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, body: TaskUpdate):
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if not row:
        raise HTTPException(404, f"Task '{task_id}' not found")

    updates: dict = {"updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.turns is not None:
        updates["turns_json"] = db.to_json([t.model_dump() for t in body.turns])
    if body.assertions is not None:
        updates["assertions_json"] = db.to_json([a.model_dump() for a in body.assertions])
    if body.tools is not None:
        updates["tools_json"] = db.to_json([t.model_dump() for t in body.tools])
    if body.tags is not None:
        updates["tags_json"] = db.to_json(body.tags)
    if body.timeout_seconds is not None:
        updates["timeout_seconds"] = body.timeout_seconds
    if body.model is not None:
        updates["model"] = body.model

    await db.update("tasks", updates, "id = ?", (task_id,))
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    return _row_to_response(row)


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str):
    count = await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    if count == 0:
        raise HTTPException(404, f"Task '{task_id}' not found")


@router.post("/import", response_model=list[TaskResponse], status_code=201)
async def import_tasks(directory: str = "tasks"):
    from engine.loader import load_suite

    path = Path(directory)
    if not path.is_dir():
        raise HTTPException(400, f"Directory '{directory}' not found")

    tasks = load_suite(path)
    results = []
    for task in tasks:
        existing = await db.fetch_one("SELECT id FROM tasks WHERE id = ?", (task.id,))
        if existing:
            continue

        turns = [{"role": t.role, "content": t.content, "wait_for_completion": t.wait_for_completion}
                 for t in task.turns]
        assertions = [{"type": a.type.value, "target": a.target, "expected": a.expected,
                        "weight": a.weight} for a in task.assertions]

        await db.insert("tasks", {
            "id": task.id,
            "name": task.name,
            "description": task.description,
            "turns_json": db.to_json(turns),
            "assertions_json": db.to_json(assertions),
            "tools_json": "[]",
            "tags_json": db.to_json(task.tags),
            "timeout_seconds": task.timeout_seconds,
            "model": task.model,
        })

        row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task.id,))
        results.append(_row_to_response(row))
    return results
