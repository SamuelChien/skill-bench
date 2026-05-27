"""Optimizer: hill-climb, beam search, and gradient-inspired skill optimization."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from service import db
from service.config import settings
from service.events import emit_event
from service.scorer import score_conversation


def _get_sandbox():
    from service.config import settings
    if settings.get_api_key():
        from service.sandbox import run_conversation
        return run_conversation
    from service.sandbox_cli import run_conversation_cli
    return run_conversation_cli

logger = logging.getLogger("skill-bench.optimizer")


async def run_optimization(
    job_id: str,
    skill_content: str,
    skill_id: str,
    tasks: list[dict[str, Any]],
    model: str,
    config: dict[str, Any],
) -> None:
    strategy = config.get("strategy", "greedy")
    max_iterations = config.get("max_iterations", 5)
    threshold = config.get("improvement_threshold", 0.03)
    beam_width = config.get("beam_width", 3)
    judge_model = config.get("judge_model", settings.default_judge_model)
    enable_thinking = config.get("enable_thinking", True)
    thinking_budget = config.get("thinking_budget", 10000)

    current_content = skill_content
    current_scores = await _evaluate_all(
        current_content, tasks, model, judge_model, enable_thinking, thinking_budget
    )
    current_avg = _avg(current_scores)

    await db.insert("hill_climb_iterations", {
        "job_id": job_id,
        "iteration_number": 0,
        "skill_content": current_content,
        "avg_score": current_avg,
        "per_task_scores_json": db.to_json(current_scores),
        "change_summary": "Baseline",
        "accepted": 1,
    })
    await emit_event(job_id, "iteration_complete", {
        "iteration": 0, "avg_score": current_avg, "accepted": True, "summary": "Baseline",
    })

    initial_avg = current_avg
    total = max_iterations

    for iteration in range(1, max_iterations + 1):
        from service.worker import is_cancelled
        if is_cancelled(job_id):
            break

        await db.update("jobs", {
            "progress_json": db.to_json({
                "completed": iteration - 1, "total": total,
                "current_task": f"iteration_{iteration}",
            }),
        }, "id = ?", (job_id,))

        weak_tasks = _find_weakest(current_scores, tasks)
        if not weak_tasks:
            logger.info("No weak tasks remaining (all >= 0.8)")
            break

        if strategy == "beam":
            best_content, best_scores, summary = await _beam_step(
                current_content, current_scores, weak_tasks, tasks, model,
                judge_model, enable_thinking, thinking_budget, beam_width,
            )
        elif strategy == "gradient":
            best_content, best_scores, summary = await _gradient_step(
                current_content, current_scores, weak_tasks, tasks, model,
                judge_model, enable_thinking, thinking_budget,
            )
        else:
            best_content, best_scores, summary = await _greedy_step(
                current_content, current_scores, weak_tasks, tasks, model,
                judge_model, enable_thinking, thinking_budget,
            )

        best_avg = _avg(best_scores)
        accepted = best_avg > current_avg + threshold

        if accepted:
            current_content = best_content
            current_scores = best_scores
            current_avg = best_avg

        await db.insert("hill_climb_iterations", {
            "job_id": job_id,
            "iteration_number": iteration,
            "skill_content": best_content if accepted else current_content,
            "avg_score": current_avg,
            "per_task_scores_json": db.to_json(current_scores),
            "change_summary": summary,
            "accepted": 1 if accepted else 0,
        })
        await emit_event(job_id, "iteration_complete", {
            "iteration": iteration, "avg_score": current_avg,
            "accepted": accepted, "summary": summary,
        })

    new_skill_id = f"{skill_id}_optimized_{uuid.uuid4().hex[:6]}"
    skill_row = await db.fetch_one("SELECT * FROM skills WHERE id = ?", (skill_id,))
    await db.insert("skills", {
        "id": new_skill_id,
        "name": skill_row["name"] if skill_row else skill_id,
        "content": current_content,
        "version": (skill_row["version"] + 1) if skill_row else 2,
        "parent_id": skill_id,
        "metadata_json": db.to_json({"optimized_from": skill_id, "strategy": strategy}),
    })

    await db.update("jobs", {
        "progress_json": db.to_json({"completed": total, "total": total}),
        "summary_json": db.to_json({
            "initial_avg": initial_avg,
            "final_avg": current_avg,
            "improvement": current_avg - initial_avg,
            "new_skill_id": new_skill_id,
        }),
    }, "id = ?", (job_id,))


async def _evaluate_all(
    skill_content: str,
    tasks: list[dict[str, Any]],
    model: str,
    judge_model: str,
    enable_thinking: bool,
    thinking_budget: int,
) -> dict[str, float]:
    run_conversation = _get_sandbox()
    scores = {}
    for task in tasks:
        task_id = task["id"]
        turns = json.loads(task["turns_json"])
        assertions = json.loads(task["assertions_json"])
        tools = json.loads(task["tools_json"])

        try:
            conversation = await run_conversation(
                system_prompt=skill_content,
                turns=[{"role": t.get("role", "user"), "content": t["content"]} for t in turns],
                model=model,
                tools=tools or None,
                enable_thinking=enable_thinking,
                thinking_budget=thinking_budget,
            )
            result = await score_conversation(conversation, assertions, judge_model)
            scores[task_id] = result["overall_score"]
        except Exception as e:
            logger.exception("Failed to evaluate task %s", task_id)
            scores[task_id] = 0.0
    return scores


# Store full conversation results for gradient signal
async def _evaluate_all_with_details(
    skill_content: str,
    tasks: list[dict[str, Any]],
    model: str,
    judge_model: str,
    enable_thinking: bool,
    thinking_budget: int,
) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    run_conversation = _get_sandbox()
    scores = {}
    details = {}
    for task in tasks:
        task_id = task["id"]
        turns = json.loads(task["turns_json"])
        assertions = json.loads(task["assertions_json"])
        tools = json.loads(task["tools_json"])

        try:
            conversation = await run_conversation(
                system_prompt=skill_content,
                turns=[{"role": t.get("role", "user"), "content": t["content"]} for t in turns],
                model=model,
                tools=tools or None,
                enable_thinking=enable_thinking,
                thinking_budget=thinking_budget,
            )
            result = await score_conversation(conversation, assertions, judge_model)
            scores[task_id] = result["overall_score"]
            details[task_id] = {
                "score": result,
                "conversation": conversation,
            }
        except Exception as e:
            logger.exception("Failed to evaluate task %s", task_id)
            scores[task_id] = 0.0
            details[task_id] = {"error": str(e)}
    return scores, details


def _avg(scores: dict[str, float]) -> float:
    if not scores:
        return 0.0
    return sum(scores.values()) / len(scores)


def _find_weakest(
    scores: dict[str, float], tasks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    weak = []
    for task in tasks:
        tid = task["id"]
        score = scores.get(tid, 0.0)
        if score < 0.8:
            weak.append({**task, "_score": score})
    weak.sort(key=lambda t: t["_score"])
    return weak[:3]


async def _suggest_improvements(
    current_content: str,
    scores: dict[str, float],
    weak_tasks: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    k: int = 1,
    extra_context: str = "",
) -> list[dict[str, Any]]:
    task_descriptions = []
    for task in weak_tasks:
        task_descriptions.append(
            f"- {task['name']} (score: {task['_score']:.2f}): {task['description']}"
        )

    prompt = f"""You are improving a system prompt (skill) to perform better on benchmark tasks.

CURRENT SYSTEM PROMPT:
{current_content[:5000]}

WEAK TASKS (need improvement):
{chr(10).join(task_descriptions)}

ALL TASK SCORES:
{json.dumps(scores, indent=2)}
{extra_context}

Suggest {k} different improved version{"s" if k > 1 else ""} of the system prompt.
{"Each should take a different approach to improvement." if k > 1 else ""}

Respond in JSON {"array" if k > 1 else ""} format:
{{"suggestions": [{{"new_content": "the full new system prompt", "summary": "what changed and why"}}]}}"""

    import os
    clean_env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE")}
    clean_env["FORCE_COLOR"] = "0"

    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--model", "claude-sonnet-4-6",
        "--output-format", "text",
        "--max-turns", "1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=clean_env,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120.0)
    text = stdout.decode().strip() if stdout else ""

    try:
        if not text:
            return []
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            return []
        data = json.loads(text[start:end])
        return data.get("suggestions", [])[:k]
    except (json.JSONDecodeError, ValueError, KeyError):
        logger.error("Failed to parse improvement suggestion: %s", text[:200])
        return []


async def _greedy_step(
    current_content: str,
    current_scores: dict[str, float],
    weak_tasks: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    model: str,
    judge_model: str,
    enable_thinking: bool,
    thinking_budget: int,
) -> tuple[str, dict[str, float], str]:
    suggestions = await _suggest_improvements(
        current_content, current_scores, weak_tasks, tasks, k=1
    )
    if not suggestions:
        return current_content, current_scores, "No suggestion generated"

    s = suggestions[0]
    new_scores = await _evaluate_all(
        s["new_content"], tasks, model, judge_model, enable_thinking, thinking_budget
    )
    return s["new_content"], new_scores, s.get("summary", "Greedy update")


async def _beam_step(
    current_content: str,
    current_scores: dict[str, float],
    weak_tasks: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    model: str,
    judge_model: str,
    enable_thinking: bool,
    thinking_budget: int,
    beam_width: int,
) -> tuple[str, dict[str, float], str]:
    suggestions = await _suggest_improvements(
        current_content, current_scores, weak_tasks, tasks, k=beam_width
    )
    if not suggestions:
        return current_content, current_scores, "No suggestions generated"

    evals = await asyncio.gather(*[
        _evaluate_all(s["new_content"], tasks, model, judge_model, enable_thinking, thinking_budget)
        for s in suggestions
    ])

    best_idx = max(range(len(evals)), key=lambda i: _avg(evals[i]))
    return (
        suggestions[best_idx]["new_content"],
        evals[best_idx],
        suggestions[best_idx].get("summary", f"Beam search (best of {len(suggestions)})"),
    )


async def _gradient_step(
    current_content: str,
    current_scores: dict[str, float],
    weak_tasks: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    model: str,
    judge_model: str,
    enable_thinking: bool,
    thinking_budget: int,
) -> tuple[str, dict[str, float], str]:
    _, details = await _evaluate_all_with_details(
        current_content, weak_tasks, model, judge_model, enable_thinking, thinking_budget
    )

    gradient_context = "\n\nGRADIENT SIGNAL (why tasks failed):\n"
    for task in weak_tasks:
        tid = task["id"]
        detail = details.get(tid, {})
        if "error" in detail:
            gradient_context += f"\n{task['name']} - ERROR: {detail['error']}\n"
            continue

        score_info = detail.get("score", {})
        conv = detail.get("conversation", {})

        for ar in score_info.get("assertion_results", []):
            if not ar.get("passed"):
                gradient_context += f"\n{task['name']} - FAILED assertion: {ar['details']}\n"

        for jr in score_info.get("judge_results", []):
            if jr.get("score", 1.0) < 0.7:
                gradient_context += (
                    f"\n{task['name']} - Judge ({jr['score']:.2f}): {jr['reasoning']}\n"
                )

        for turn in conv.get("turns", [])[:2]:
            assistant = turn.get("assistant_response", "")[:300]
            gradient_context += f"\n{task['name']} - Model response preview: {assistant}\n"

    suggestions = await _suggest_improvements(
        current_content, current_scores, weak_tasks, tasks, k=1,
        extra_context=gradient_context,
    )
    if not suggestions:
        return current_content, current_scores, "No suggestion generated"

    s = suggestions[0]
    new_scores = await _evaluate_all(
        s["new_content"], tasks, model, judge_model, enable_thinking, thinking_budget
    )
    return s["new_content"], new_scores, s.get("summary", "Gradient-inspired update")
