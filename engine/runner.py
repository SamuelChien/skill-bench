"""Task runner: drives Claude Code CLI through multi-turn benchmark tasks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .models import BenchmarkTask, Recording, ToolCall, TurnRecord


@dataclass
class RunResult:
    recording: Recording
    workspace: Path
    _cleanup: bool = True

    def cleanup(self):
        if self._cleanup and self.workspace.exists():
            shutil.rmtree(self.workspace, ignore_errors=True)


def _setup_workspace(task: BenchmarkTask) -> Path:
    workspace = Path(tempfile.mkdtemp(prefix=f"bench_{task.id}_"))

    if task.setup.repo_scaffold:
        for filename, content in task.setup.repo_scaffold.items():
            filepath = workspace / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)

    subprocess.run(["git", "init"], cwd=workspace, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=workspace, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial", "--allow-empty"],
        cwd=workspace,
        capture_output=True,
    )

    for cmd in task.setup.commands:
        subprocess.run(cmd, shell=True, cwd=workspace, capture_output=True)

    return workspace


class Runner:
    def __init__(
        self,
        skills_dir: Path | None = None,
        model: str | None = None,
    ):
        self.skills_dir = skills_dir
        self.model_override = model

    def run_task(self, task: BenchmarkTask) -> RunResult:
        """Run a task and return result with workspace still alive for scoring."""
        workspace = _setup_workspace(task)
        recording = Recording(task_id=task.id)
        start = time.time()

        conversation_history: list[str] = []
        model = self.model_override or task.model

        for i, turn in enumerate(task.turns):
            turn_start = time.time()

            result = self._execute_turn(
                workspace=workspace,
                user_message=turn.content,
                conversation_history=conversation_history,
                model=model,
                timeout=task.timeout_seconds,
            )

            if result.get("error"):
                recording.error = result["error"]
                break

            tool_calls = []
            for tc in result.get("tool_calls", []):
                tool_calls.append(ToolCall(
                    tool_name=tc.get("tool", "unknown"),
                    input=tc.get("input", {}),
                    output=tc.get("output", ""),
                ))

            turn_record = TurnRecord(
                turn_index=i,
                user_input=turn.content,
                assistant_response=result.get("response", ""),
                tool_calls=tool_calls,
                duration_ms=int((time.time() - turn_start) * 1000),
            )
            recording.turns.append(turn_record)

            conversation_history.append(turn.content)

            usage = result.get("usage", {})
            recording.total_input_tokens += usage.get("input_tokens", 0)
            recording.total_output_tokens += usage.get("output_tokens", 0)

        recording.total_duration_ms = int((time.time() - start) * 1000)
        return RunResult(recording=recording, workspace=workspace)

    def _execute_turn(
        self,
        workspace: Path,
        user_message: str,
        conversation_history: list[str],
        model: str,
        timeout: int,
    ) -> dict:
        """Call claude CLI in print mode with stream-json output."""
        if conversation_history:
            context = "\n".join(
                f"[Previous turn {i+1}]: {msg}"
                for i, msg in enumerate(conversation_history)
            )
            prompt = f"{context}\n\n[Current request]: {user_message}"
        else:
            prompt = user_message

        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
            "--model", model,
            "--bare",
        ]

        if self.skills_dir:
            cmd.extend(["--add-dir", str(self.skills_dir)])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 30,
                cwd=workspace,
                env={
                    **os.environ,
                    "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
                },
            )
        except subprocess.TimeoutExpired:
            return {"error": f"Turn timed out after {timeout}s"}

        response_text = ""
        tool_calls = []
        usage = {}

        for line in proc.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")

            if etype == "assistant" and "message" in event:
                msg = event["message"]
                if isinstance(msg.get("content"), list):
                    for block in msg["content"]:
                        if block.get("type") == "text":
                            response_text += block.get("text", "")
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "tool": block.get("name", "unknown"),
                                "input": block.get("input", {}),
                                "output": "",
                            })

            elif etype == "tool_result":
                content = event.get("content", "")
                if tool_calls:
                    if isinstance(content, list):
                        parts = []
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                parts.append(c.get("text", ""))
                        tool_calls[-1]["output"] = "\n".join(parts)[:2000]
                    elif isinstance(content, str):
                        tool_calls[-1]["output"] = content[:2000]

            elif etype == "result":
                response_text = event.get("result", response_text)
                usage = event.get("usage", {})
                if event.get("is_error"):
                    return {
                        "error": response_text,
                        "response": response_text,
                        "tool_calls": tool_calls,
                        "usage": usage,
                    }

        return {
            "response": response_text,
            "tool_calls": tool_calls,
            "usage": usage,
        }
