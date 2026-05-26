from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from service import db
from service.models.jobs import JobListItem, JobResponse, JobProgress, JobSubmit

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _row_to_response(row: dict) -> JobResponse:
    return JobResponse(
        id=row["id"],
        type=row["type"],
        status=row["status"],
        skill_id=row["skill_id"],
        model=row["model"],
        config=json.loads(row["config_json"]),
        task_ids=json.loads(row["task_ids_json"]) if row["task_ids_json"] else None,
        progress=JobProgress(**json.loads(row["progress_json"])) if row["progress_json"] != "{}" else JobProgress(),
        summary=json.loads(row["summary_json"]),
        error=row["error"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


@router.post("", response_model=JobResponse, status_code=201)
async def submit_job(body: JobSubmit):
    if body.skill_id:
        skill = await db.fetch_one("SELECT id FROM skills WHERE id = ?", (body.skill_id,))
        if not skill:
            raise HTTPException(404, f"Skill '{body.skill_id}' not found")

    if body.task_ids:
        for tid in body.task_ids:
            task = await db.fetch_one("SELECT id FROM tasks WHERE id = ?", (tid,))
            if not task:
                raise HTTPException(404, f"Task '{tid}' not found")

    job_id = uuid.uuid4().hex[:16]
    await db.insert("jobs", {
        "id": job_id,
        "type": body.type,
        "status": "pending",
        "skill_id": body.skill_id,
        "model": body.model,
        "config_json": db.to_json(body.config.model_dump()),
        "task_ids_json": db.to_json(body.task_ids) if body.task_ids else None,
        "progress_json": "{}",
        "summary_json": "{}",
    })

    from service.worker import enqueue_job
    await enqueue_job(job_id)

    row = await db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    return _row_to_response(row)


@router.get("", response_model=list[JobListItem])
async def list_jobs(status: str | None = None, type: str | None = None):
    conditions = []
    params = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if type:
        conditions.append("type = ?")
        params.append(type)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await db.fetch_all(
        f"SELECT * FROM jobs {where} ORDER BY created_at DESC", tuple(params)
    )
    return [
        JobListItem(
            id=r["id"], type=r["type"], status=r["status"], model=r["model"],
            created_at=r["created_at"], started_at=r["started_at"],
            completed_at=r["completed_at"],
        )
        for r in rows
    ]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    row = await db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not row:
        raise HTTPException(404, f"Job '{job_id}' not found")
    return _row_to_response(row)


@router.delete("/{job_id}", status_code=204)
async def cancel_job(job_id: str):
    row = await db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not row:
        raise HTTPException(404, f"Job '{job_id}' not found")
    if row["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(400, f"Job is already {row['status']}")

    from service.worker import cancel_job as do_cancel
    do_cancel(job_id)

    await db.update("jobs", {"status": "cancelled"}, "id = ?", (job_id,))


@router.get("/{job_id}/events")
async def stream_events(job_id: str):
    row = await db.fetch_one("SELECT id FROM jobs WHERE id = ?", (job_id,))
    if not row:
        raise HTTPException(404, f"Job '{job_id}' not found")

    from service.events import event_stream
    return StreamingResponse(
        event_stream(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
