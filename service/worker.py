from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from service import db
from service.config import settings
from service.events import emit_event

logger = logging.getLogger("skill-bench.worker")

_queue: asyncio.Queue[str] = asyncio.Queue()
_cancelled: set[str] = set()
_workers: list[asyncio.Task] = []


async def enqueue_job(job_id: str) -> None:
    await _queue.put(job_id)


def cancel_job(job_id: str) -> None:
    _cancelled.add(job_id)


def is_cancelled(job_id: str) -> bool:
    return job_id in _cancelled


async def start_workers(num_workers: int | None = None) -> None:
    n = num_workers or settings.num_workers
    for i in range(n):
        task = asyncio.create_task(_worker(i))
        _workers.append(task)
    logger.info("Started %d workers", n)

    stalled = await db.fetch_all(
        "SELECT id FROM jobs WHERE status = 'running' AND started_at < datetime('now', '-30 minutes')"
    )
    for row in stalled:
        logger.warning("Resetting stalled job %s to pending", row["id"])
        await db.update("jobs", {"status": "pending", "started_at": None}, "id = ?", (row["id"],))

    pending = await db.fetch_all(
        "SELECT id FROM jobs WHERE status IN ('pending', 'running') ORDER BY created_at"
    )
    for row in pending:
        logger.info("Re-queuing job %s", row["id"])
        await _queue.put(row["id"])


async def stop_workers() -> None:
    for w in _workers:
        w.cancel()
    _workers.clear()


async def _worker(worker_id: int) -> None:
    logger.info("Worker %d started", worker_id)
    while True:
        try:
            job_id = await _queue.get()

            if is_cancelled(job_id):
                _cancelled.discard(job_id)
                _queue.task_done()
                continue

            job = await db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
            if not job or job["status"] in ("completed", "failed", "cancelled"):
                _queue.task_done()
                continue

            now = datetime.now(timezone.utc).isoformat()
            await db.update("jobs", {"status": "running", "started_at": now}, "id = ?", (job_id,))
            await emit_event(job_id, "job_started")

            try:
                if job["type"] == "benchmark":
                    await _run_benchmark(job)
                elif job["type"] == "hill_climb":
                    await _run_hill_climb(job)
                elif job["type"] == "mine":
                    await _run_mine(job)

                now = datetime.now(timezone.utc).isoformat()
                await db.update(
                    "jobs", {"status": "completed", "completed_at": now}, "id = ?", (job_id,)
                )
                await emit_event(job_id, "job_completed")

            except Exception as e:
                logger.exception("Job %s failed", job_id)
                now = datetime.now(timezone.utc).isoformat()
                await db.update(
                    "jobs",
                    {"status": "failed", "error": str(e), "completed_at": now},
                    "id = ?", (job_id,),
                )
                await emit_event(job_id, "job_failed", {"error": str(e)})

            finally:
                _cancelled.discard(job_id)
                _queue.task_done()

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Worker %d unexpected error", worker_id)


def _get_sandbox(use_cli: bool = False):
    if use_cli:
        from service.sandbox_cli import run_conversation_cli
        return run_conversation_cli
    from service.config import settings
    if settings.get_api_key():
        from service.sandbox import run_conversation
        return run_conversation
    from service.sandbox_cli import run_conversation_cli
    logger.info("No API key — using Claude CLI sandbox backend")
    return run_conversation_cli


async def _run_benchmark(job: dict) -> None:
    from service.scorer import score_conversation

    config = json.loads(job["config_json"])
    use_cli = config.get("use_cli_sandbox", True)
    run_conversation = _get_sandbox(use_cli=use_cli)

    skill_content = None
    skills_dir = None
    if job["skill_id"]:
        skill_row = await db.fetch_one("SELECT * FROM skills WHERE id = ?", (job["skill_id"],))
        if skill_row:
            skill_content = skill_row["content"]
            if skill_row.get("file_path"):
                from pathlib import Path
                skills_dir = str(Path(skill_row["file_path"]).parent)

    task_ids = json.loads(job["task_ids_json"]) if job["task_ids_json"] else None
    if task_ids:
        tasks = [await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (tid,))
                 for tid in task_ids]
        tasks = [t for t in tasks if t]
    else:
        tasks = await db.fetch_all("SELECT * FROM tasks ORDER BY id")

    total = len(tasks)
    scores = []

    for i, task in enumerate(tasks):
        if is_cancelled(job["id"]):
            now = datetime.now(timezone.utc).isoformat()
            await db.update("jobs", {"status": "cancelled", "completed_at": now}, "id = ?", (job["id"],))
            await emit_event(job["id"], "job_cancelled")
            return

        task_id = task["id"]
        turns = json.loads(task["turns_json"])
        tools = json.loads(task["tools_json"])
        assertions = json.loads(task["assertions_json"])

        await db.update("jobs", {
            "progress_json": db.to_json({"completed": i, "total": total, "current_task": task_id})
        }, "id = ?", (job["id"],))
        await emit_event(job["id"], "task_started", {"task_id": task_id, "index": i, "total": total})

        conversation = await run_conversation(
            system_prompt=skill_content or "",
            turns=[{"role": t.get("role", "user"), "content": t["content"]} for t in turns],
            model=job["model"],
            skills_dir=skills_dir,
            tools=tools or None,
            enable_thinking=config.get("enable_thinking", True),
            thinking_budget=config.get("thinking_budget", 10000),
        )

        task_score = await score_conversation(
            conversation=conversation,
            assertions=assertions,
            judge_model=config.get("judge_model", settings.default_judge_model),
        )

        run_id = uuid.uuid4().hex[:12]
        result_id = uuid.uuid4().hex[:16]
        await db.insert("results", {
            "id": result_id,
            "job_id": job["id"],
            "task_id": task_id,
            "run_id": run_id,
            "overall_score": task_score["overall_score"],
            "assertion_results_json": db.to_json(task_score["assertion_results"]),
            "judge_results_json": db.to_json(task_score["judge_results"]),
        })

        for turn_rec in conversation["turns"]:
            await db.insert("turns", {
                "result_id": result_id,
                "turn_index": turn_rec["turn_index"],
                "user_input": turn_rec["user_input"],
                "assistant_response": turn_rec["assistant_response"],
                "thinking_trace": turn_rec.get("thinking_trace"),
                "tool_calls_json": db.to_json(turn_rec.get("tool_calls", [])),
                "input_tokens": turn_rec.get("input_tokens", 0),
                "output_tokens": turn_rec.get("output_tokens", 0),
                "duration_ms": turn_rec.get("duration_ms", 0),
            })

        scores.append(task_score["overall_score"])
        await emit_event(job["id"], "task_scored", {
            "task_id": task_id, "score": task_score["overall_score"],
        })

    avg_score = sum(scores) / len(scores) if scores else 0.0
    await db.update("jobs", {
        "progress_json": db.to_json({"completed": total, "total": total}),
        "summary_json": db.to_json({"avg_score": avg_score, "num_tasks": total}),
    }, "id = ?", (job["id"],))


async def _run_hill_climb(job: dict) -> None:
    from service.optimizer import run_optimization

    config = json.loads(job["config_json"])
    skill_row = await db.fetch_one("SELECT * FROM skills WHERE id = ?", (job["skill_id"],))
    if not skill_row:
        raise ValueError(f"Skill '{job['skill_id']}' not found")

    task_ids = json.loads(job["task_ids_json"]) if job["task_ids_json"] else None
    if task_ids:
        tasks = [await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (tid,))
                 for tid in task_ids]
        tasks = [t for t in tasks if t]
    else:
        tasks = await db.fetch_all("SELECT * FROM tasks ORDER BY id")

    await run_optimization(
        job_id=job["id"],
        skill_content=skill_row["content"],
        skill_id=job["skill_id"],
        tasks=tasks,
        model=job["model"],
        config=config,
    )


async def _run_mine(job: dict) -> None:
    from service.miner import mine_project

    config = json.loads(job["config_json"])
    max_sessions = config.get("max_sessions", 50)

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
        await emit_event(job["id"], "episode_mined", {
            "intent": ep["user_intent"][:100], "stored": stored,
        })

    await db.update("jobs", {
        "summary_json": db.to_json({"total_episodes": len(episodes), "stored": stored}),
    }, "id = ?", (job["id"],))
