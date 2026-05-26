from __future__ import annotations

from pydantic import BaseModel, Field


class SkillCreate(BaseModel):
    id: str
    name: str
    content: str
    metadata: dict = Field(default_factory=dict)


class SkillUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    metadata: dict | None = None


class SkillResponse(BaseModel):
    id: str
    name: str
    content: str
    version: int
    parent_id: str | None
    metadata: dict
    created_at: str


class SkillVersionResponse(BaseModel):
    id: str
    name: str
    version: int
    parent_id: str | None
    created_at: str
