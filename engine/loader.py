"""Load benchmark tasks from YAML definitions."""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import Assertion, AssertionType, BenchmarkTask, TaskSetup, Turn


def load_task(path: Path) -> BenchmarkTask:
    with open(path) as f:
        raw = yaml.safe_load(f)

    setup_raw = raw.get("setup", {})
    setup = TaskSetup(
        repo_url=setup_raw.get("repo_url"),
        repo_scaffold=setup_raw.get("scaffold"),
        commands=setup_raw.get("commands", []),
        skills_dir=setup_raw.get("skills_dir"),
    )

    turns = []
    for t in raw.get("turns", []):
        turns.append(Turn(
            role=t.get("role", "user"),
            content=t["content"],
            wait_for_completion=t.get("wait_for_completion", True),
        ))

    assertions = []
    for a in raw.get("assertions", []):
        assertions.append(Assertion(
            type=AssertionType(a["type"]),
            target=a["target"],
            expected=a.get("expected"),
            weight=a.get("weight", 1.0),
        ))

    return BenchmarkTask(
        id=raw.get("id", path.stem),
        name=raw["name"],
        description=raw.get("description", ""),
        setup=setup,
        turns=turns,
        assertions=assertions,
        tags=raw.get("tags", []),
        timeout_seconds=raw.get("timeout_seconds", 300),
        model=raw.get("model", "claude-sonnet-4-6"),
    )


def load_suite(directory: Path) -> list[BenchmarkTask]:
    tasks = []
    for path in sorted(directory.glob("*.yaml")):
        tasks.append(load_task(path))
    for path in sorted(directory.glob("*.yml")):
        tasks.append(load_task(path))
    return tasks
