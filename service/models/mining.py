from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScanResult(BaseModel):
    project: str
    sessions: list[SessionInfo]
    total: int


class SessionInfo(BaseModel):
    session_id: str
    file: str
    size_bytes: int
    modified: float


class MineRequest(BaseModel):
    max_sessions: int = 50


class EpisodeResponse(BaseModel):
    id: str
    session_id: str
    project: str
    user_intent: str
    turns: list[dict[str, Any]]
    original_response: str
    tool_calls: list[dict[str, Any]]
    tokens: dict[str, Any]
    timestamp: str | None
    cwd: str | None
    tags: list[str]
    promoted_task_id: str | None
    created_at: str


class PromoteRequest(BaseModel):
    task_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    auto_judge: bool = True
