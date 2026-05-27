"""CLI sandbox: runs claude -p with --add-dir for skill testing, parses stream-json output."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from service.config import settings

logger = logging.getLogger("skill-bench.sandbox_cli")


def _clean_env() -> dict[str, str]:
    """Strip API key and CLAUDECODE so CLI uses subscription OAuth."""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE")}
    env["FORCE_COLOR"] = "0"
    oauth = settings.get_api_key()
    if oauth and oauth.startswith("oauth-"):
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth
    return env


async def run_conversation_cli(
    system_prompt: str,
    turns: list[dict[str, str]],
    model: str | None = None,
    skills_dir: str | None = None,
    skill_content: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    model = model or settings.default_model
    turn_records: list[dict[str, Any]] = []
    total_input = 0
    total_output = 0
    total_start = time.monotonic()
    error = None
    conversation_history: list[str] = []

    tmp_skill_dir = None
    effective_skills_dir = skills_dir

    if not skills_dir and (skill_content or system_prompt):
        content = skill_content or system_prompt
        if content and content.strip():
            tmp_skill_dir = tempfile.mkdtemp(prefix="skillbench-")
            skill_path = Path(tmp_skill_dir) / "bench_skill.md"
            frontmatter = "---\nname: bench-skill\ndescription: Benchmark skill under test\n---\n\n"
            skill_path.write_text(frontmatter + content)
            effective_skills_dir = tmp_skill_dir

    try:
        for turn_idx, turn in enumerate(turns):
            turn_start = time.monotonic()
            user_content = turn["content"]

            result = await _execute_turn(
                user_message=user_content,
                conversation_history=conversation_history,
                model=model,
                skills_dir=effective_skills_dir,
            )

            assistant_text = result.get("response", "")
            thinking_text = result.get("thinking", "")
            tool_calls = result.get("tool_calls", [])
            usage = result.get("usage", {})

            if result.get("error") and not assistant_text:
                error = result["error"]
                assistant_text = f"[ERROR: {error}]"

            turn_input = usage.get("input_tokens", 0)
            turn_output = usage.get("output_tokens", 0)
            total_input += turn_input
            total_output += turn_output

            conversation_history.append(f"User: {user_content}\nAssistant: {assistant_text[:500]}")

            turn_duration = int((time.monotonic() - turn_start) * 1000)
            turn_records.append({
                "turn_index": turn_idx,
                "user_input": user_content,
                "assistant_response": assistant_text,
                "thinking_trace": thinking_text or None,
                "tool_calls": tool_calls,
                "input_tokens": turn_input,
                "output_tokens": turn_output,
                "duration_ms": turn_duration,
            })

            if error:
                break

    finally:
        if tmp_skill_dir:
            shutil.rmtree(tmp_skill_dir, ignore_errors=True)

    total_duration = int((time.monotonic() - total_start) * 1000)
    return {
        "turns": turn_records,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_duration_ms": total_duration,
        "error": error,
    }


async def _execute_turn(
    user_message: str,
    conversation_history: list[str],
    model: str,
    skills_dir: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    if conversation_history:
        context = "\n".join(
            f"[Previous turn {i+1}]: {msg}" for i, msg in enumerate(conversation_history)
        )
        prompt = f"{context}\n\n[Current request]: {user_message}"
    else:
        prompt = user_message

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--model", model,
    ]

    if skills_dir:
        cmd.extend(["--add-dir", str(skills_dir)])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_clean_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 30)
    except asyncio.TimeoutError:
        return {"error": f"Turn timed out after {timeout}s", "response": "", "tool_calls": [], "usage": {}}
    except Exception as e:
        return {"error": str(e), "response": "", "tool_calls": [], "usage": {}}

    if stderr:
        err_text = stderr.decode().strip()
        if err_text and "Error:" in err_text:
            logger.error("CLI stderr: %s", err_text[:300])

    return _parse_stream_json(stdout.decode() if stdout else "")


def _parse_stream_json(output: str) -> dict[str, Any]:
    response_text = ""
    thinking_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, Any] = {}
    error = None

    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")

        if etype == "assistant" and "message" in event:
            msg = event["message"]
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    btype = block.get("type", "")
                    if btype == "text":
                        response_text += block.get("text", "")
                    elif btype == "thinking":
                        thinking_parts.append(block.get("thinking", ""))
                    elif btype == "tool_use":
                        tool_calls.append({
                            "tool_name": block.get("name", ""),
                            "input": block.get("input", {}),
                            "output": "",
                            "duration_ms": 0,
                        })

        elif etype == "tool_result":
            content = event.get("content", "")
            if tool_calls:
                if isinstance(content, list):
                    parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                    tool_calls[-1]["output"] = "\n".join(parts)[:3000]
                elif isinstance(content, str):
                    tool_calls[-1]["output"] = content[:3000]

        elif etype == "result":
            result_text = event.get("result", "")
            if result_text and not response_text:
                response_text = result_text
            usage = event.get("usage", {})
            if event.get("is_error"):
                error = response_text or "Unknown error"

    return {
        "response": response_text,
        "thinking": "\n\n".join(thinking_parts).strip(),
        "tool_calls": tool_calls,
        "usage": usage,
        "error": error,
    }
