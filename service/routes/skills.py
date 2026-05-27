from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

from service import db
from service.models.skills import SkillCreate, SkillResponse, SkillUpdate, SkillVersionResponse

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


def _row_to_response(row: dict) -> SkillResponse:
    return SkillResponse(
        id=row["id"],
        name=row["name"],
        content=row["content"],
        version=row["version"],
        parent_id=row["parent_id"],
        metadata=json.loads(row["metadata_json"]),
        created_at=row["created_at"],
    )


@router.post("", response_model=SkillResponse, status_code=201)
async def create_skill(body: SkillCreate):
    existing = await db.fetch_one("SELECT id FROM skills WHERE id = ?", (body.id,))
    if existing:
        raise HTTPException(409, f"Skill '{body.id}' already exists")

    await db.insert("skills", {
        "id": body.id,
        "name": body.name,
        "content": body.content,
        "version": 1,
        "parent_id": None,
        "metadata_json": db.to_json(body.metadata),
    })

    row = await db.fetch_one("SELECT * FROM skills WHERE id = ?", (body.id,))
    return _row_to_response(row)


@router.get("", response_model=list[SkillResponse])
async def list_skills():
    rows = await db.fetch_all("SELECT * FROM skills ORDER BY name, version DESC")
    return [_row_to_response(r) for r in rows]


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str):
    row = await db.fetch_one("SELECT * FROM skills WHERE id = ?", (skill_id,))
    if not row:
        raise HTTPException(404, f"Skill '{skill_id}' not found")
    return _row_to_response(row)


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(skill_id: str, body: SkillUpdate):
    row = await db.fetch_one("SELECT * FROM skills WHERE id = ?", (skill_id,))
    if not row:
        raise HTTPException(404, f"Skill '{skill_id}' not found")

    new_id = f"{row['name']}_v{row['version'] + 1}_{uuid.uuid4().hex[:6]}"

    await db.insert("skills", {
        "id": new_id,
        "name": body.name or row["name"],
        "content": body.content or row["content"],
        "version": row["version"] + 1,
        "parent_id": skill_id,
        "metadata_json": db.to_json(body.metadata) if body.metadata else row["metadata_json"],
    })

    new_row = await db.fetch_one("SELECT * FROM skills WHERE id = ?", (new_id,))
    return _row_to_response(new_row)


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: str):
    count = await db.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
    if count == 0:
        raise HTTPException(404, f"Skill '{skill_id}' not found")


@router.get("/{skill_id}/versions", response_model=list[SkillVersionResponse])
async def list_versions(skill_id: str):
    row = await db.fetch_one("SELECT name FROM skills WHERE id = ?", (skill_id,))
    if not row:
        raise HTTPException(404, f"Skill '{skill_id}' not found")

    rows = await db.fetch_all(
        "SELECT * FROM skills WHERE name = ? ORDER BY version DESC",
        (row["name"],),
    )
    return [
        SkillVersionResponse(
            id=r["id"], name=r["name"], version=r["version"],
            parent_id=r["parent_id"], created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("/import-files")
async def import_skill_files(directory: str | None = None, pattern: str = "*.md", limit: int = 50):
    skill_dir = Path(os.path.expanduser(directory or "~/.claude/commands"))
    if not skill_dir.is_dir():
        raise HTTPException(400, f"Directory not found: {skill_dir}")

    imported = 0
    for path in sorted(skill_dir.glob(pattern))[:limit]:
        try:
            content = path.read_text(errors="replace")
        except Exception:
            continue

        name, description = _parse_frontmatter(content)
        skill_id = name or path.stem

        existing = await db.fetch_one("SELECT id FROM skills WHERE id = ?", (skill_id,))
        if existing:
            continue

        await db.insert("skills", {
            "id": skill_id,
            "name": name or path.stem,
            "content": content,
            "version": 1,
            "metadata_json": db.to_json({"description": description, "file": path.name}),
            "file_path": str(path),
        })
        imported += 1

    return {"imported": imported, "directory": str(skill_dir)}


@router.post("/{skill_id}/export")
async def export_skill(skill_id: str):
    row = await db.fetch_one("SELECT * FROM skills WHERE id = ?", (skill_id,))
    if not row:
        raise HTTPException(404, f"Skill '{skill_id}' not found")
    file_path = row.get("file_path")
    if not file_path:
        raise HTTPException(400, "Skill has no file_path — cannot export to disk")
    Path(file_path).write_text(row["content"])
    return {"exported": file_path}


def _parse_frontmatter(content: str) -> tuple[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return "", ""
    fm = match.group(1)
    name = ""
    desc = ""
    for line in fm.split("\n"):
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip("'\"")
        elif line.startswith("description:"):
            desc = line.split(":", 1)[1].strip().strip("'\"")
    return name, desc
