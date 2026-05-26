from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BenchmarkConfig(BaseModel):
    judge_model: str = "claude-sonnet-4-6"
    enable_thinking: bool = True
    thinking_budget: int = 10000


class HillClimbConfig(BaseModel):
    max_iterations: int = 5
    improvement_threshold: float = 0.03
    strategy: Literal["greedy", "beam", "gradient"] = "greedy"
    beam_width: int = 3
    judge_model: str = "claude-sonnet-4-6"
    enable_thinking: bool = True
    thinking_budget: int = 10000


class JobSubmit(BaseModel):
    type: Literal["benchmark", "hill_climb"]
    task_ids: list[str] | None = None
    skill_id: str | None = None
    model: str = "claude-sonnet-4-6"
    config: BenchmarkConfig | HillClimbConfig = Field(default_factory=BenchmarkConfig)


class JobProgress(BaseModel):
    completed: int = 0
    total: int = 0
    current_task: str | None = None


class JobResponse(BaseModel):
    id: str
    type: str
    status: str
    skill_id: str | None
    model: str
    config: dict
    task_ids: list[str] | None
    progress: JobProgress
    summary: dict
    error: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None


class JobListItem(BaseModel):
    id: str
    type: str
    status: str
    model: str
    created_at: str
    started_at: str | None
    completed_at: str | None
