"""Session miner: extract task episodes from Claude Code session history."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from service.config import settings

logger = logging.getLogger("skill-bench.miner")


def get_claude_dir() -> Path:
    return Path(os.path.expanduser(getattr(settings, "claude_dir", "~/.claude")))


def get_project_dir(project_path: str | None = None) -> Path:
    claude_dir = get_claude_dir()
    if project_path:
        encoded = project_path.replace("/", "-")
        return claude_dir / "projects" / encoded
    cwd = os.getcwd()
    encoded = cwd.replace("/", "-")
    return claude_dir / "projects" / encoded


def scan_sessions(project_path: str | None = None) -> dict[str, Any]:
    project_dir = get_project_dir(project_path)
    if not project_dir.exists():
        return {"project": str(project_dir), "sessions": [], "total": 0}

    sessions = []
    for f in sorted(project_dir.glob("*.jsonl")):
        if f.name == "CLAUDE.md":
            continue
        stat = f.stat()
        sessions.append({
            "session_id": f.stem,
            "file": str(f),
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime,
        })

    return {
        "project": str(project_dir),
        "sessions": sessions,
        "total": len(sessions),
    }


def read_session(session_file: str | Path) -> list[dict[str, Any]]:
    events = []
    with open(session_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def extract_episodes(events: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]]:
    user_assistant_events = [
        e for e in events if e.get("type") in ("user", "assistant")
    ]

    if not user_assistant_events:
        return []

    episodes = []
    current_episode: dict[str, Any] | None = None

    for event in user_assistant_events:
        etype = event.get("type")
        msg = event.get("message", {})
        content = msg.get("content", "")

        if etype == "user" and isinstance(content, str) and len(content.strip()) > 5:
            if _is_meta_message(content):
                continue

            if current_episode:
                episodes.append(_finalize_episode(current_episode, session_id))

            current_episode = {
                "user_intent": content.strip(),
                "turns": [],
                "tool_calls": [],
                "tokens": {"input": 0, "output": 0},
                "timestamp": event.get("timestamp"),
                "cwd": event.get("cwd"),
                "git_branch": event.get("gitBranch"),
            }
            current_episode["turns"].append({
                "role": "user",
                "content": content.strip(),
            })

        elif etype == "user" and isinstance(content, list):
            if current_episode:
                for block in content:
                    if block.get("type") == "tool_result":
                        current_episode["turns"].append({
                            "role": "tool_result",
                            "tool_use_id": block.get("tool_use_id"),
                            "content": str(block.get("content", ""))[:2000],
                            "is_error": block.get("is_error", False),
                        })

        elif etype == "assistant":
            if not current_episode:
                continue
            content_blocks = msg.get("content", [])
            if not isinstance(content_blocks, list):
                continue

            usage = msg.get("usage", {})
            current_episode["tokens"]["input"] += usage.get("input_tokens", 0)
            current_episode["tokens"]["output"] += usage.get("output_tokens", 0)

            for block in content_blocks:
                btype = block.get("type")
                if btype == "text":
                    current_episode["turns"].append({
                        "role": "assistant",
                        "content": block.get("text", ""),
                    })
                elif btype == "thinking":
                    current_episode["turns"].append({
                        "role": "thinking",
                        "content": block.get("thinking", ""),
                    })
                elif btype == "tool_use":
                    tc = {
                        "tool_name": block.get("name", ""),
                        "tool_use_id": block.get("id", ""),
                        "input": block.get("input", {}),
                    }
                    current_episode["tool_calls"].append(tc)
                    current_episode["turns"].append({
                        "role": "tool_use",
                        "tool_name": block.get("name", ""),
                        "input": block.get("input", {}),
                    })

    if current_episode:
        episodes.append(_finalize_episode(current_episode, session_id))

    return [e for e in episodes if _is_valid_episode(e)]


def _is_meta_message(content: str) -> bool:
    meta_patterns = [
        "<command-name>", "<local-command-caveat>", "<local-command-stdout>",
        "/exit", "/model", "/effort", "/clear", "/help", "/config",
        "/compact", "/cost", "/doctor", "/login", "/logout",
    ]
    content_lower = content.strip().lower()
    for p in meta_patterns:
        if content_lower.startswith(p.lower()) or p.lower() in content_lower[:50]:
            return True
    return False


def _is_valid_episode(episode: dict[str, Any]) -> bool:
    if len(episode.get("user_intent", "")) < 10:
        return False
    assistant_turns = [t for t in episode.get("turns", []) if t.get("role") == "assistant"]
    if not assistant_turns:
        return False
    return True


def _finalize_episode(episode: dict[str, Any], session_id: str) -> dict[str, Any]:
    assistant_texts = [
        t["content"] for t in episode.get("turns", [])
        if t.get("role") == "assistant"
    ]
    return {
        "id": uuid.uuid4().hex[:16],
        "session_id": session_id,
        "user_intent": episode["user_intent"][:500],
        "turns": episode["turns"],
        "original_response": "\n\n".join(assistant_texts)[:5000],
        "tool_calls": episode["tool_calls"],
        "tokens": episode["tokens"],
        "timestamp": episode.get("timestamp"),
        "cwd": episode.get("cwd"),
        "tags": _auto_tag(episode),
    }


def _auto_tag(episode: dict[str, Any]) -> list[str]:
    tags = []
    intent = episode.get("user_intent", "").lower()
    tools_used = {tc.get("tool_name", "") for tc in episode.get("tool_calls", [])}

    if "debug" in intent or "fix" in intent or "error" in intent:
        tags.append("debugging")
    if "test" in intent:
        tags.append("testing")
    if "refactor" in intent or "clean" in intent:
        tags.append("refactoring")
    if "explain" in intent or "what" in intent or "how" in intent:
        tags.append("explanation")
    if "create" in intent or "build" in intent or "add" in intent or "implement" in intent:
        tags.append("code-generation")
    if "Bash" in tools_used:
        tags.append("shell")
    if "Edit" in tools_used or "Write" in tools_used:
        tags.append("file-editing")
    if "Read" in tools_used:
        tags.append("code-reading")

    return tags


async def mine_project(project_path: str | None = None, max_sessions: int = 50) -> list[dict[str, Any]]:
    scan = scan_sessions(project_path)
    all_episodes = []

    for session_info in scan["sessions"][:max_sessions]:
        try:
            events = read_session(session_info["file"])
            episodes = extract_episodes(events, session_info["session_id"])
            all_episodes.extend(episodes)
            logger.info("Mined %d episodes from session %s", len(episodes), session_info["session_id"][:8])
        except Exception:
            logger.exception("Error mining session %s", session_info["session_id"][:8])

    logger.info("Total: %d episodes from %d sessions", len(all_episodes), len(scan["sessions"]))
    return all_episodes
