from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TurnDef(BaseModel):
    role: str = "user"
    content: str
    wait_for_completion: bool = True


class AssertionDef(BaseModel):
    type: str
    target: str
    expected: Any = None
    weight: float = 1.0


class ToolDef(BaseModel):
    name: str
    description: str
    input_schema: dict = Field(default_factory=dict)


class TaskCreate(BaseModel):
    id: str
    name: str
    description: str = ""
    turns: list[TurnDef]
    assertions: list[AssertionDef] = Field(default_factory=list)
    tools: list[ToolDef] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    timeout_seconds: int = 300
    model: str = "claude-sonnet-4-6"


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    turns: list[TurnDef] | None = None
    assertions: list[AssertionDef] | None = None
    tools: list[ToolDef] | None = None
    tags: list[str] | None = None
    timeout_seconds: int | None = None
    model: str | None = None


class TaskResponse(BaseModel):
    id: str
    name: str
    description: str
    turns: list[TurnDef]
    assertions: list[AssertionDef]
    tools: list[ToolDef]
    tags: list[str]
    timeout_seconds: int
    model: str
    created_at: str
    updated_at: str
