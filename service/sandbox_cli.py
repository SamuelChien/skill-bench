"""CLI sandbox backend: uses `claude -p` when no API key is available."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from service.config import settings

logger = logging.getLogger("skill-bench.sandbox_cli")


async def run_conversation_cli(
    system_prompt: str,
    turns: list[dict[str, str]],
    model: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    model = model or settings.default_model
    turn_records: list[dict[str, Any]] = []
    total_input = 0
    total_output = 0
    total_start = time.monotonic()
    error = None

    conversation_history: list[str] = []

    for turn_idx, turn in enumerate(turns):
        turn_start = time.monotonic()
        user_content = turn["content"]

        prompt_parts = []
        if system_prompt:
            prompt_parts.append(f"[System prompt]: {system_prompt}\n")
        for i, prev in enumerate(conversation_history):
            prompt_parts.append(f"[Previous turn {i + 1}]: {prev}\n")
        prompt_parts.append(f"[Current request]: {user_content}")
        full_prompt = "\n".join(prompt_parts)

        assistant_text = ""
        try:
            cmd = [
                "claude", "-p", full_prompt,
                "--model", model,
                "--output-format", "text",
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=120.0
            )

            if proc.returncode == 0 and stdout:
                assistant_text = stdout.decode().strip()
            elif stdout:
                assistant_text = stdout.decode().strip()
            else:
                error = stderr.decode().strip() if stderr else f"Exit code {proc.returncode}"
                assistant_text = f"[ERROR: {error}]"

        except asyncio.TimeoutError:
            error = "Claude CLI timed out after 120s"
            assistant_text = f"[ERROR: {error}]"
        except Exception as e:
            logger.exception("CLI error on turn %d", turn_idx)
            error = str(e)
            assistant_text = f"[ERROR: {e}]"

        conversation_history.append(f"User: {user_content}\nAssistant: {assistant_text[:500]}")

        turn_duration = int((time.monotonic() - turn_start) * 1000)
        turn_records.append({
            "turn_index": turn_idx,
            "user_input": user_content,
            "assistant_response": assistant_text,
            "thinking_trace": None,
            "tool_calls": [],
            "input_tokens": 0,
            "output_tokens": 0,
            "duration_ms": turn_duration,
        })

        if error:
            break

    total_duration = int((time.monotonic() - total_start) * 1000)
    return {
        "turns": turn_records,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_duration_ms": total_duration,
        "error": error,
    }
