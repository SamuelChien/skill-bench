"""Scorer: evaluate conversation results using response-based assertions + LLM judge."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import anthropic

from service.config import settings

logger = logging.getLogger("skill-bench.scorer")


async def score_conversation(
    conversation: dict[str, Any],
    assertions: list[dict[str, Any]],
    judge_model: str | None = None,
) -> dict[str, Any]:
    """Score a conversation result against a list of assertions.

    Returns dict with overall_score, assertion_results, judge_results.
    """
    judge_model = judge_model or settings.default_judge_model
    assertion_results: list[dict[str, Any]] = []
    judge_results: list[dict[str, Any]] = []

    full_response = _get_full_response(conversation)

    for assertion in assertions:
        atype = assertion["type"]
        if atype == "llm_judge":
            result = await _run_judge(assertion, conversation, judge_model)
            judge_results.append(result)
        else:
            result = _check_assertion(assertion, full_response, conversation)
            assertion_results.append(result)

    overall = _compute_overall(assertion_results, judge_results)
    return {
        "overall_score": overall,
        "assertion_results": assertion_results,
        "judge_results": judge_results,
    }


def _get_full_response(conversation: dict[str, Any]) -> str:
    parts = []
    for turn in conversation.get("turns", []):
        parts.append(turn.get("assistant_response", ""))
    return "\n\n".join(parts)


def _extract_code_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)


def _check_assertion(
    assertion: dict[str, Any], full_response: str, conversation: dict[str, Any]
) -> dict[str, Any]:
    atype = assertion["type"]
    target = assertion.get("target", "")
    expected = assertion.get("expected", "")
    weight = assertion.get("weight", 1.0)

    match atype:
        case "response_contains":
            found = expected.lower() in full_response.lower()
            return {
                "type": atype, "target": target, "expected": expected, "weight": weight,
                "passed": found, "actual": None,
                "details": f"{'Found' if found else 'Not found'}: {expected!r}",
            }

        case "response_not_contains":
            found = expected.lower() in full_response.lower()
            return {
                "type": atype, "target": target, "expected": expected, "weight": weight,
                "passed": not found, "actual": None,
                "details": f"{'Still contains' if found else 'Correctly absent'}: {expected!r}",
            }

        case "response_matches_regex":
            pattern = expected
            matched = bool(re.search(pattern, full_response))
            return {
                "type": atype, "target": target, "expected": expected, "weight": weight,
                "passed": matched, "actual": None,
                "details": f"{'Matched' if matched else 'No match'}: {pattern}",
            }

        case "code_block_contains":
            blocks = _extract_code_blocks(full_response)
            found = any(expected in block for block in blocks)
            return {
                "type": atype, "target": target, "expected": expected, "weight": weight,
                "passed": found,
                "actual": f"{len(blocks)} code blocks found",
                "details": f"{'Found' if found else 'Not found'} in code blocks: {expected!r}",
            }

        case _:
            return {
                "type": atype, "target": target, "expected": expected, "weight": weight,
                "passed": False, "actual": None,
                "details": f"Unknown assertion type: {atype}",
            }


async def _run_judge(
    assertion: dict[str, Any], conversation: dict[str, Any], judge_model: str
) -> dict[str, Any]:
    conversation_log = ""
    for turn in conversation.get("turns", []):
        conversation_log += f"USER: {turn['user_input']}\n"
        response_preview = turn.get("assistant_response", "")[:1000]
        conversation_log += f"ASSISTANT: {response_preview}\n"
        tc = turn.get("tool_calls", [])
        if tc:
            tool_names = ", ".join(t["tool_name"] for t in tc)
            conversation_log += f"  [Tools used: {tool_names}]\n"
        thinking = turn.get("thinking_trace", "")
        if thinking:
            conversation_log += f"  [Thinking: {thinking[:500]}]\n"
        conversation_log += "\n"

    prompt = f"""You are an evaluation judge. Score the following conversation on how well it accomplished the task.

EVALUATION CRITERIA:
{assertion.get('target', '')}

CONVERSATION LOG:
{conversation_log}

Respond in JSON format:
{{"score": <float 0.0-1.0>, "reasoning": "<brief explanation>"}}

Score 1.0 = perfectly accomplished, 0.0 = completely failed."""

    return await _run_judge_cli(assertion, prompt, judge_model)


async def _run_judge_api(
    assertion: dict[str, Any], prompt: str, judge_model: str, api_key: str
) -> dict[str, Any]:
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=judge_model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=60.0,
        )
        if not response.content:
            return {"prompt": assertion.get("target", ""), "score": 0.5, "reasoning": "Empty response"}
        text = response.content[0].text
        return _parse_judge_response(assertion, text)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        return {"prompt": assertion.get("target", ""), "score": 0.5, "reasoning": f"Parse error: {e}"}
    except Exception as e:
        logger.exception("Judge API call failed")
        return {"prompt": assertion.get("target", ""), "score": 0.0, "reasoning": f"API error: {e}"}


async def _run_judge_cli(
    assertion: dict[str, Any], prompt: str, judge_model: str
) -> dict[str, Any]:
    from service.sandbox_cli import _clean_env
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--model", judge_model, "--output-format", "text",
            "--max-turns", "1", "--verbose",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=_clean_env(),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        text = stdout.decode().strip()
        return _parse_judge_response(assertion, text)
    except Exception as e:
        logger.exception("Judge CLI call failed")
        return {
            "prompt": assertion.get("target", ""),
            "score": 0.0,
            "reasoning": f"API error: {e}",
        }


def _parse_judge_response(assertion: dict[str, Any], text: str) -> dict[str, Any]:
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
        else:
            data = json.loads(text)
        return {
            "prompt": assertion.get("target", ""),
            "score": float(data.get("score", 0.5)),
            "reasoning": data.get("reasoning", ""),
        }
    except (json.JSONDecodeError, ValueError):
        return {
            "prompt": assertion.get("target", ""),
            "score": 0.5,
            "reasoning": f"Could not parse judge response: {text[:200]}",
        }


def _compute_overall(
    assertion_results: list[dict[str, Any]], judge_results: list[dict[str, Any]]
) -> float:
    scores: list[tuple[float, float]] = []
    for ar in assertion_results:
        scores.append((1.0 if ar["passed"] else 0.0, ar.get("weight", 1.0)))
    for jr in judge_results:
        scores.append((jr["score"], 1.0))
    if not scores:
        return 0.0
    total_weight = sum(w for _, w in scores)
    if total_weight == 0:
        return 0.0
    return sum(s * w for s, w in scores) / total_weight
