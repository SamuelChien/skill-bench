"""Scorer: evaluates task results using file assertions + LLM-as-judge."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import anthropic

from .models import (
    Assertion,
    AssertionResult,
    AssertionType,
    BenchmarkTask,
    JudgeResult,
    Recording,
    TaskScore,
)


class Scorer:
    def __init__(self, judge_model: str = "claude-sonnet-4-6"):
        self.judge_model = judge_model
        self.client = anthropic.Anthropic()

    def score(self, task: BenchmarkTask, recording: Recording, workspace: Path) -> TaskScore:
        result = TaskScore(task_id=task.id, run_id=recording.run_id)

        for assertion in task.assertions:
            if assertion.type == AssertionType.LLM_JUDGE:
                judge = self._run_judge(assertion, recording)
                result.judge_results.append(judge)
            else:
                ar = self._check_assertion(assertion, workspace)
                result.assertion_results.append(ar)

        result.compute_overall()
        return result

    def _check_assertion(self, assertion: Assertion, workspace: Path) -> AssertionResult:
        match assertion.type:
            case AssertionType.FILE_EXISTS:
                path = workspace / assertion.target
                exists = path.exists()
                return AssertionResult(
                    assertion=assertion,
                    passed=exists,
                    actual=str(path),
                    details=f"{'Found' if exists else 'Missing'}: {assertion.target}",
                )

            case AssertionType.FILE_CONTAINS:
                path = workspace / assertion.target
                if not path.exists():
                    return AssertionResult(
                        assertion=assertion, passed=False, details=f"File not found: {assertion.target}"
                    )
                content = path.read_text()
                found = assertion.expected in content
                return AssertionResult(
                    assertion=assertion,
                    passed=found,
                    actual=content[:200],
                    details=f"{'Found' if found else 'Not found'}: {assertion.expected!r}",
                )

            case AssertionType.FILE_NOT_CONTAINS:
                path = workspace / assertion.target
                if not path.exists():
                    return AssertionResult(assertion=assertion, passed=True, details="File not found (pass)")
                content = path.read_text()
                found = assertion.expected in content
                return AssertionResult(
                    assertion=assertion,
                    passed=not found,
                    actual=content[:200],
                    details=f"{'Still contains' if found else 'Correctly absent'}: {assertion.expected!r}",
                )

            case AssertionType.COMMAND_EXIT_CODE:
                result = subprocess.run(
                    assertion.target, shell=True, cwd=workspace, capture_output=True, timeout=30
                )
                expected_code = int(assertion.expected) if assertion.expected is not None else 0
                passed = result.returncode == expected_code
                return AssertionResult(
                    assertion=assertion,
                    passed=passed,
                    actual=result.returncode,
                    details=f"Exit code {result.returncode} (expected {expected_code})",
                )

            case AssertionType.COMMAND_OUTPUT_CONTAINS:
                result = subprocess.run(
                    assertion.target, shell=True, cwd=workspace, capture_output=True, text=True, timeout=30
                )
                found = assertion.expected in result.stdout
                return AssertionResult(
                    assertion=assertion,
                    passed=found,
                    actual=result.stdout[:200],
                    details=f"{'Found' if found else 'Not found'} in output",
                )

            case AssertionType.DIRECTORY_EXISTS:
                path = workspace / assertion.target
                exists = path.is_dir()
                return AssertionResult(
                    assertion=assertion, passed=exists, details=f"{'Found' if exists else 'Missing'} dir"
                )

            case _:
                return AssertionResult(assertion=assertion, passed=False, details="Unknown assertion type")

    def _run_judge(self, assertion: Assertion, recording: Recording) -> JudgeResult:
        conversation_log = ""
        for turn in recording.turns:
            conversation_log += f"USER: {turn.user_input}\n"
            conversation_log += f"ASSISTANT: {turn.assistant_response[:500]}\n"
            if turn.tool_calls:
                conversation_log += f"  [Tools used: {', '.join(tc.tool_name for tc in turn.tool_calls)}]\n"
            conversation_log += "\n"

        prompt = f"""You are an evaluation judge. Score the following Claude Code session on how well it accomplished the task.

EVALUATION CRITERIA:
{assertion.target}

CONVERSATION LOG:
{conversation_log}

Respond in JSON format:
{{"score": <float 0.0-1.0>, "reasoning": "<brief explanation>"}}

Score 1.0 = perfectly accomplished, 0.0 = completely failed."""

        response = self.client.messages.create(
            model=self.judge_model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text
        try:
            data = json.loads(text)
            return JudgeResult(
                prompt=assertion.target,
                score=float(data["score"]),
                reasoning=data.get("reasoning", ""),
            )
        except (json.JSONDecodeError, KeyError):
            return JudgeResult(prompt=assertion.target, score=0.5, reasoning=f"Parse error: {text[:100]}")
