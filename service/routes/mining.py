from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException

from service import db
from service.miner import extract_episodes, mine_project, read_session, scan_sessions
from service.models.mining import EpisodeResponse, MineRequest, PromoteRequest, ScanResult

router = APIRouter(prefix="/api/v1/mining", tags=["mining"])


@router.post("/scan", response_model=ScanResult)
async def scan():
    result = scan_sessions()
    return ScanResult(**result)


@router.post("/mine")
async def mine(body: MineRequest | None = None):
    max_sessions = body.max_sessions if body else 50
    episodes = await mine_project(max_sessions=max_sessions)

    stored = 0
    for ep in episodes:
        existing = await db.fetch_one(
            "SELECT id FROM mined_episodes WHERE session_id = ? AND user_intent = ?",
            (ep["session_id"], ep["user_intent"][:500]),
        )
        if existing:
            continue

        await db.insert("mined_episodes", {
            "id": ep["id"],
            "session_id": ep["session_id"],
            "project": ep.get("cwd", ""),
            "user_intent": ep["user_intent"],
            "turns_json": db.to_json(ep["turns"]),
            "original_response": ep["original_response"],
            "tool_calls_json": db.to_json(ep["tool_calls"]),
            "tokens_json": db.to_json(ep["tokens"]),
            "timestamp": ep.get("timestamp"),
            "cwd": ep.get("cwd"),
            "tags_json": db.to_json(ep.get("tags", [])),
        })
        stored += 1

    return {"mined": len(episodes), "stored": stored}


@router.get("/episodes", response_model=list[EpisodeResponse])
async def list_episodes(tag: str | None = None, promoted: bool | None = None, limit: int = 100):
    conditions = []
    params: list = []

    if tag:
        conditions.append("tags_json LIKE ?")
        params.append(f'%"{tag}"%')
    if promoted is True:
        conditions.append("promoted_task_id IS NOT NULL")
    elif promoted is False:
        conditions.append("promoted_task_id IS NULL")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await db.fetch_all(
        f"SELECT * FROM mined_episodes {where} ORDER BY created_at DESC LIMIT ?",
        (*params, limit),
    )
    return [_row_to_episode(r) for r in rows]


@router.get("/episodes/{episode_id}", response_model=EpisodeResponse)
async def get_episode(episode_id: str):
    row = await db.fetch_one("SELECT * FROM mined_episodes WHERE id = ?", (episode_id,))
    if not row:
        raise HTTPException(404, "Episode not found")
    return _row_to_episode(row)


@router.post("/episodes/{episode_id}/promote")
async def promote_episode(episode_id: str, body: PromoteRequest):
    row = await db.fetch_one("SELECT * FROM mined_episodes WHERE id = ?", (episode_id,))
    if not row:
        raise HTTPException(404, "Episode not found")
    if row["promoted_task_id"]:
        raise HTTPException(409, f"Already promoted to task '{row['promoted_task_id']}'")

    task_id = body.task_id or f"mined_{episode_id[:8]}"
    turns = json.loads(row["turns_json"])

    task_turns = []
    for t in turns:
        if t.get("role") == "user":
            task_turns.append({"role": "user", "content": t["content"], "wait_for_completion": True})

    if not task_turns:
        raise HTTPException(400, "No user turns found in episode")

    assertions = []
    if body.auto_judge:
        assertions.append({
            "type": "llm_judge",
            "target": f"Evaluate how well the assistant handled this task: {row['user_intent'][:200]}. "
                      f"The original successful response covered: {row['original_response'][:300]}. "
                      f"Score based on correctness, completeness, and quality.",
            "expected": None,
            "weight": 3.0,
        })

    tags = list(set(body.tags + json.loads(row["tags_json"])))

    await db.insert("tasks", {
        "id": task_id,
        "name": row["user_intent"][:100],
        "description": f"Mined from session {row['session_id'][:8]}",
        "turns_json": db.to_json(task_turns),
        "assertions_json": db.to_json(assertions),
        "tools_json": "[]",
        "tags_json": db.to_json(tags + ["mined"]),
        "timeout_seconds": 300,
        "model": "claude-sonnet-4-6",
    })

    await db.update("mined_episodes", {"promoted_task_id": task_id}, "id = ?", (episode_id,))

    return {"task_id": task_id, "turns": len(task_turns), "assertions": len(assertions)}


def _row_to_episode(row: dict) -> EpisodeResponse:
    return EpisodeResponse(
        id=row["id"],
        session_id=row["session_id"],
        project=row["project"],
        user_intent=row["user_intent"],
        turns=json.loads(row["turns_json"]),
        original_response=row["original_response"],
        tool_calls=json.loads(row["tool_calls_json"]),
        tokens=json.loads(row["tokens_json"]),
        timestamp=row["timestamp"],
        cwd=row["cwd"],
        tags=json.loads(row["tags_json"]),
        promoted_task_id=row["promoted_task_id"],
        created_at=row["created_at"],
    )
