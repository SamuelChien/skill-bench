"""Data models for benchmark tasks, recordings, and scores."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class AssertionType(Enum):
    FILE_EXISTS = "file_exists"
    FILE_CONTAINS = "file_contains"
    FILE_NOT_CONTAINS = "file_not_contains"
    COMMAND_EXIT_CODE = "command_exit_code"
    COMMAND_OUTPUT_CONTAINS = "command_output_contains"
    DIRECTORY_EXISTS = "directory_exists"
    LLM_JUDGE = "llm_judge"
    RESPONSE_CONTAINS = "response_contains"
    RESPONSE_NOT_CONTAINS = "response_not_contains"
    RESPONSE_MATCHES_REGEX = "response_matches_regex"
    CODE_BLOCK_CONTAINS = "code_block_contains"


@dataclass
class Assertion:
    type: AssertionType
    target: str  # file path, command, or judge prompt
    expected: Any = None
    weight: float = 1.0


@dataclass
class Turn:
    role: str  # "user" or "system_event"
    content: str
    wait_for_completion: bool = True


@dataclass
class TaskSetup:
    repo_url: str | None = None
    repo_scaffold: dict[str, str] | None = None  # filename -> content
    commands: list[str] = field(default_factory=list)
    skills_dir: str | None = None  # path to skills to mount


@dataclass
class BenchmarkTask:
    id: str
    name: str
    description: str
    setup: TaskSetup
    turns: list[Turn]
    assertions: list[Assertion]
    tags: list[str] = field(default_factory=list)
    timeout_seconds: int = 300
    model: str = "claude-sonnet-4-6"


@dataclass
class ToolCall:
    tool_name: str
    input: dict[str, Any]
    output: str
    duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class TurnRecord:
    turn_index: int
    user_input: str
    assistant_response: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class Recording:
    task_id: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    turns: list[TurnRecord] = field(default_factory=list)
    total_duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    error: str | None = None
    skills_snapshot: dict[str, str] | None = None  # skill_name -> content hash


@dataclass
class AssertionResult:
    assertion: Assertion
    passed: bool
    actual: Any = None
    details: str = ""


@dataclass
class JudgeResult:
    prompt: str
    score: float  # 0.0 - 1.0
    reasoning: str = ""


@dataclass
class TaskScore:
    task_id: str
    run_id: str
    assertion_results: list[AssertionResult] = field(default_factory=list)
    judge_results: list[JudgeResult] = field(default_factory=list)
    overall_score: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def compute_overall(self) -> float:
        scores: list[tuple[float, float]] = []
        for ar in self.assertion_results:
            scores.append((1.0 if ar.passed else 0.0, ar.assertion.weight))
        for jr in self.judge_results:
            scores.append((jr.score, 1.0))
        if not scores:
            return 0.0
        total_weight = sum(w for _, w in scores)
        if total_weight == 0:
            return 0.0
        self.overall_score = sum(s * w for s, w in scores) / total_weight
        return self.overall_score
