from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import StreamingResponse

from service import db
from service import trace_formatter
from service.models.results import (
    AssertionResultResponse,
    CompareEntry,
    IterationResponse,
    JudgeResultResponse,
    ResultDetail,
    ResultSummary,
    ToolCallResponse,
    TurnResponse,
)
from starlette.responses import HTMLResponse

router = APIRouter(tags=["results"])


def _parse_assertion_results(raw: str) -> list[AssertionResultResponse]:
    return [AssertionResultResponse(**a) for a in json.loads(raw)]


def _parse_judge_results(raw: str) -> list[JudgeResultResponse]:
    return [JudgeResultResponse(**j) for j in json.loads(raw)]


@router.get("/api/v1/jobs/{job_id}/results", response_model=list[ResultSummary])
async def list_results(job_id: str):
    job = await db.fetch_one("SELECT id FROM jobs WHERE id = ?", (job_id,))
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")

    rows = await db.fetch_all(
        "SELECT * FROM results WHERE job_id = ? ORDER BY task_id", (job_id,)
    )
    results = []
    for r in rows:
        ar = json.loads(r["assertion_results_json"])
        passed = sum(1 for a in ar if a.get("passed"))
        results.append(ResultSummary(
            id=r["id"], task_id=r["task_id"], run_id=r["run_id"],
            overall_score=r["overall_score"], assertions_passed=passed,
            assertions_total=len(ar), created_at=r["created_at"],
        ))
    return results


@router.get("/api/v1/jobs/{job_id}/results/{task_id}", response_model=ResultDetail)
async def get_result(job_id: str, task_id: str):
    result = await db.fetch_one(
        "SELECT * FROM results WHERE job_id = ? AND task_id = ?", (job_id, task_id)
    )
    if not result:
        raise HTTPException(404, "Result not found")

    turn_rows = await db.fetch_all(
        "SELECT * FROM turns WHERE result_id = ? ORDER BY turn_index",
        (result["id"],),
    )
    turns = [
        TurnResponse(
            turn_index=t["turn_index"],
            user_input=t["user_input"],
            assistant_response=t["assistant_response"],
            thinking_trace=t["thinking_trace"],
            tool_calls=[ToolCallResponse(**tc) for tc in json.loads(t["tool_calls_json"])],
            input_tokens=t["input_tokens"],
            output_tokens=t["output_tokens"],
            duration_ms=t["duration_ms"],
        )
        for t in turn_rows
    ]

    return ResultDetail(
        id=result["id"],
        job_id=job_id,
        task_id=task_id,
        run_id=result["run_id"],
        overall_score=result["overall_score"],
        assertion_results=_parse_assertion_results(result["assertion_results_json"]),
        judge_results=_parse_judge_results(result["judge_results_json"]),
        turns=turns,
        created_at=result["created_at"],
    )


@router.get("/api/v1/results/compare", response_model=list[CompareEntry])
async def compare_results(job_ids: str = Query(..., description="Comma-separated job IDs")):
    ids = [j.strip() for j in job_ids.split(",")]
    entries = []
    for jid in ids:
        rows = await db.fetch_all(
            "SELECT * FROM results WHERE job_id = ? ORDER BY task_id", (jid,)
        )
        for r in rows:
            entries.append(CompareEntry(
                job_id=jid,
                task_id=r["task_id"],
                overall_score=r["overall_score"],
                assertion_results=_parse_assertion_results(r["assertion_results_json"]),
                judge_results=_parse_judge_results(r["judge_results_json"]),
            ))
    return entries


@router.get("/api/v1/jobs/{job_id}/iterations", response_model=list[IterationResponse])
async def list_iterations(job_id: str):
    job = await db.fetch_one("SELECT id FROM jobs WHERE id = ?", (job_id,))
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")

    rows = await db.fetch_all(
        "SELECT * FROM hill_climb_iterations WHERE job_id = ? ORDER BY iteration_number",
        (job_id,),
    )
    return [
        IterationResponse(
            iteration_number=r["iteration_number"],
            avg_score=r["avg_score"],
            per_task_scores=json.loads(r["per_task_scores_json"]),
            change_summary=r["change_summary"],
            accepted=bool(r["accepted"]),
            skill_content=r["skill_content"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("/api/v1/jobs/{job_id}/iterations/{n}", response_model=IterationResponse)
async def get_iteration(job_id: str, n: int):
    row = await db.fetch_one(
        "SELECT * FROM hill_climb_iterations WHERE job_id = ? AND iteration_number = ?",
        (job_id, n),
    )
    if not row:
        raise HTTPException(404, "Iteration not found")
    return IterationResponse(
        iteration_number=row["iteration_number"],
        avg_score=row["avg_score"],
        per_task_scores=json.loads(row["per_task_scores_json"]),
        change_summary=row["change_summary"],
        accepted=bool(row["accepted"]),
        skill_content=row["skill_content"],
        created_at=row["created_at"],
    )


@router.get("/api/v1/jobs/{job_id}/export")
async def export_jsonl(job_id: str):
    job = await db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")

    async def generate():
        results = await db.fetch_all(
            "SELECT * FROM results WHERE job_id = ? ORDER BY task_id", (job_id,)
        )
        for r in results:
            turn_rows = await db.fetch_all(
                "SELECT * FROM turns WHERE result_id = ? ORDER BY turn_index", (r["id"],)
            )
            entry = {
                "task_id": r["task_id"],
                "run_id": r["run_id"],
                "score": r["overall_score"],
                "assertion_results": json.loads(r["assertion_results_json"]),
                "judge_results": json.loads(r["judge_results_json"]),
                "turns": [
                    {
                        "turn_index": t["turn_index"],
                        "user_input": t["user_input"],
                        "assistant_response": t["assistant_response"],
                        "thinking_trace": t["thinking_trace"],
                        "tool_calls": json.loads(t["tool_calls_json"]),
                        "input_tokens": t["input_tokens"],
                        "output_tokens": t["output_tokens"],
                        "duration_ms": t["duration_ms"],
                    }
                    for t in turn_rows
                ],
            }
            yield json.dumps(entry, default=str) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f"attachment; filename=job_{job_id}.jsonl"},
    )


@router.get("/api/v1/results/{result_id}/trace")
async def get_result_trace(result_id: str):
    """Get complete trace data for a result."""
    result = await db.fetch_one("SELECT trace_json FROM results WHERE id = ?", (result_id,))
    if not result:
        raise HTTPException(404, "Result not found")

    trace_data = json.loads(result["trace_json"]) if result["trace_json"] else None
    if not trace_data:
        raise HTTPException(404, "No trace data available")

    return trace_data


@router.get("/api/v1/results/{result_id}/trace/timeline")
async def get_result_trace_timeline(result_id: str):
    """Get API calls and steps as a chronological timeline."""
    result = await db.fetch_one("SELECT trace_json FROM results WHERE id = ?", (result_id,))
    if not result:
        raise HTTPException(404, "Result not found")

    trace_data = json.loads(result["trace_json"]) if result["trace_json"] else None
    if not trace_data:
        raise HTTPException(404, "No trace data available")

    return {
        "api_calls": trace_formatter.extract_api_calls_timeline(trace_data),
        "steps": trace_formatter.extract_steps_timeline(trace_data),
        "turns": trace_formatter.extract_turn_timelines(trace_data),
    }


@router.get("/api/v1/results/{result_id}/trace/summary")
async def get_result_trace_summary(result_id: str):
    """Get a summary of trace metrics."""
    result = await db.fetch_one("SELECT trace_json FROM results WHERE id = ?", (result_id,))
    if not result:
        raise HTTPException(404, "Result not found")

    trace_data = json.loads(result["trace_json"]) if result["trace_json"] else None
    if not trace_data:
        raise HTTPException(404, "No trace data available")

    return trace_formatter.get_trace_summary(trace_data)


@router.get("/api/v1/results/{result_id}/trace/html", response_class=HTMLResponse)
async def get_result_trace_html(result_id: str):
    """Export trace as an HTML report."""
    result = await db.fetch_one("SELECT trace_json FROM results WHERE id = ?", (result_id,))
    if not result:
        raise HTTPException(404, "Result not found")

    trace_data = json.loads(result["trace_json"]) if result["trace_json"] else None
    if not trace_data:
        raise HTTPException(404, "No trace data available")

    return trace_formatter.export_trace_html(trace_data)


@router.get("/api/v1/results/{result_id}/turns/{turn_index}/trace")
async def get_turn_trace(result_id: str, turn_index: int):
    """Get complete trace data for a specific turn."""
    turn = await db.fetch_one(
        "SELECT trace_json FROM turns WHERE result_id = ? AND turn_index = ?",
        (result_id, turn_index),
    )
    if not turn:
        raise HTTPException(404, "Turn not found")

    trace_data = json.loads(turn["trace_json"]) if turn["trace_json"] else None
    if not trace_data:
        raise HTTPException(404, "No trace data available for this turn")

    return trace_data
