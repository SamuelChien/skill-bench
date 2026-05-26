from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AssertionResultResponse(BaseModel):
    type: str
    target: str
    expected: Any = None
    weight: float
    passed: bool
    actual: Any = None
    details: str


class JudgeResultResponse(BaseModel):
    prompt: str
    score: float
    reasoning: str


class ToolCallResponse(BaseModel):
    tool_name: str
    input: dict
    output: str
    duration_ms: int


class TurnResponse(BaseModel):
    turn_index: int
    user_input: str
    assistant_response: str
    thinking_trace: str | None
    tool_calls: list[ToolCallResponse]
    input_tokens: int
    output_tokens: int
    duration_ms: int


class ResultSummary(BaseModel):
    id: str
    task_id: str
    run_id: str
    overall_score: float
    assertions_passed: int
    assertions_total: int
    created_at: str


class ResultDetail(BaseModel):
    id: str
    job_id: str
    task_id: str
    run_id: str
    overall_score: float
    assertion_results: list[AssertionResultResponse]
    judge_results: list[JudgeResultResponse]
    turns: list[TurnResponse]
    created_at: str


class IterationResponse(BaseModel):
    iteration_number: int
    avg_score: float
    per_task_scores: dict[str, float]
    change_summary: str | None
    accepted: bool
    skill_content: str
    created_at: str


class CompareEntry(BaseModel):
    job_id: str
    task_id: str
    overall_score: float
    assertion_results: list[AssertionResultResponse]
    judge_results: list[JudgeResultResponse]
