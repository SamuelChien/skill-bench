"""Comprehensive tracing system for observability: timestamps, API calls, call stacks, step traces."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from contextvars import ContextVar
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Optional, Callable, Awaitable, TypeVar

logger = logging.getLogger("skill-bench.tracing")

T = TypeVar("T")

_trace_context: ContextVar[Optional[TraceContext]] = ContextVar("trace_context", default=None)


@dataclass
class APICall:
    """Record of a single API call with request/response details."""
    id: str
    timestamp: str
    endpoint: str
    method: str
    request_body: dict[str, Any]
    response_body: dict[str, Any]
    status_code: int
    duration_ms: float
    tokens_used: dict[str, int] = field(default_factory=dict)
    error: Optional[str] = None
    call_stack: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepTrace:
    """A single step in execution with inputs, outputs, and metadata."""
    id: str
    timestamp: str
    name: str
    step_type: str  # e.g., "api_call", "computation", "tool_execution"
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    duration_ms: float
    parent_step_id: Optional[str] = None
    api_call_ids: list[str] = field(default_factory=list)
    error: Optional[str] = None
    call_stack: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TurnTrace:
    """Complete trace for a single conversation turn."""
    id: str
    timestamp: str
    turn_index: int
    user_input: str
    start_time_ms: float
    end_time_ms: float
    duration_ms: float

    api_calls: list[APICall] = field(default_factory=list)
    steps: list[StepTrace] = field(default_factory=list)
    thinking_trace: Optional[str] = None

    assistant_response: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["api_calls"] = [call.to_dict() for call in self.api_calls]
        data["steps"] = [step.to_dict() for step in self.steps]
        return data


@dataclass
class TraceContext:
    """Context for tracking all tracing information."""
    id: str
    timestamp: str
    job_id: str
    task_id: Optional[str] = None

    current_turn: Optional[TurnTrace] = None
    current_step: Optional[StepTrace] = None

    api_calls: list[APICall] = field(default_factory=list)
    steps: list[StepTrace] = field(default_factory=list)
    turns: list[TurnTrace] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["api_calls"] = [call.to_dict() for call in self.api_calls]
        data["steps"] = [step.to_dict() for step in self.steps]
        data["turns"] = [turn.to_dict() for turn in self.turns]
        if self.current_turn:
            data["current_turn"] = self.current_turn.to_dict()
        if self.current_step:
            data["current_step"] = self.current_step.to_dict()
        return data


def start_trace(job_id: str, task_id: Optional[str] = None) -> TraceContext:
    """Initialize a new trace context."""
    import uuid
    ctx = TraceContext(
        id=uuid.uuid4().hex[:16],
        timestamp=datetime.now(timezone.utc).isoformat(),
        job_id=job_id,
        task_id=task_id,
    )
    _trace_context.set(ctx)
    return ctx


def get_trace_context() -> Optional[TraceContext]:
    """Get the current trace context."""
    return _trace_context.get()


def start_turn_trace(turn_index: int, user_input: str) -> TurnTrace:
    """Start tracing a new conversation turn."""
    import uuid
    ctx = get_trace_context()
    if not ctx:
        return None

    turn_trace = TurnTrace(
        id=uuid.uuid4().hex[:16],
        timestamp=datetime.now(timezone.utc).isoformat(),
        turn_index=turn_index,
        user_input=user_input,
        start_time_ms=time.time() * 1000,
        end_time_ms=0,
        duration_ms=0,
    )
    ctx.current_turn = turn_trace
    return turn_trace


def end_turn_trace() -> Optional[TurnTrace]:
    """Complete the current turn trace and add it to context."""
    ctx = get_trace_context()
    if not ctx or not ctx.current_turn:
        return None

    turn_trace = ctx.current_turn
    turn_trace.end_time_ms = time.time() * 1000
    turn_trace.duration_ms = turn_trace.end_time_ms - turn_trace.start_time_ms
    ctx.turns.append(turn_trace)
    ctx.current_turn = None
    return turn_trace


def start_step_trace(name: str, step_type: str, input_data: dict[str, Any]) -> StepTrace:
    """Start tracing a computation/operation step."""
    import uuid
    ctx = get_trace_context()
    if not ctx:
        return None

    step = StepTrace(
        id=uuid.uuid4().hex[:16],
        timestamp=datetime.now(timezone.utc).isoformat(),
        name=name,
        step_type=step_type,
        input_data=input_data,
        output_data={},
        duration_ms=0,
        parent_step_id=ctx.current_step.id if ctx.current_step else None,
        call_stack=_get_call_stack(),
    )

    old_step = ctx.current_step
    ctx.current_step = step
    return step


def end_step_trace(output_data: dict[str, Any]) -> Optional[StepTrace]:
    """Complete the current step trace."""
    ctx = get_trace_context()
    if not ctx or not ctx.current_step:
        return None

    step = ctx.current_step
    step.output_data = output_data
    step.duration_ms = (time.time() * 1000) - (
        datetime.fromisoformat(step.timestamp).timestamp() * 1000
    )

    # Add to turn if available
    if ctx.current_turn:
        ctx.current_turn.steps.append(step)
    else:
        ctx.steps.append(step)

    return step


def record_api_call(
    endpoint: str,
    method: str,
    request_body: dict[str, Any],
    response_body: dict[str, Any],
    status_code: int,
    duration_ms: float,
    tokens_used: Optional[dict[str, int]] = None,
    error: Optional[str] = None,
) -> APICall:
    """Record an API call with full details."""
    import uuid
    ctx = get_trace_context()
    if not ctx:
        return None

    api_call = APICall(
        id=uuid.uuid4().hex[:12],
        timestamp=datetime.now(timezone.utc).isoformat(),
        endpoint=endpoint,
        method=method,
        request_body=_sanitize_for_logging(request_body),
        response_body=_sanitize_for_logging(response_body),
        status_code=status_code,
        duration_ms=duration_ms,
        tokens_used=tokens_used or {},
        error=error,
        call_stack=_get_call_stack(),
    )

    ctx.api_calls.append(api_call)

    # Also add to current turn if available
    if ctx.current_turn:
        ctx.current_turn.api_calls.append(api_call)
        if tokens_used:
            ctx.current_turn.input_tokens += tokens_used.get("input", 0)
            ctx.current_turn.output_tokens += tokens_used.get("output", 0)

    # Add to current step if available
    if ctx.current_step:
        ctx.current_step.api_call_ids.append(api_call.id)

    return api_call


def _get_call_stack(depth: int = 10) -> list[str]:
    """Extract call stack for debugging."""
    stack = traceback.extract_stack()[:-1]
    result = []
    for frame in stack[-depth:]:
        result.append(f"{frame.filename}:{frame.lineno} in {frame.name}")
    return result


def _sanitize_for_logging(obj: Any, max_depth: int = 3) -> Any:
    """Sanitize objects for logging (remove sensitive data, truncate large strings)."""
    if max_depth <= 0:
        return "[truncated]"

    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            # Skip sensitive keys
            if k.lower() in ("api_key", "token", "password", "secret"):
                result[k] = "[redacted]"
            else:
                result[k] = _sanitize_for_logging(v, max_depth - 1)
        return result
    elif isinstance(obj, list):
        return [_sanitize_for_logging(item, max_depth - 1) for item in obj[:100]]
    elif isinstance(obj, str):
        if len(obj) > 5000:
            return obj[:5000] + f"... [truncated {len(obj) - 5000} chars]"
        return obj
    else:
        return obj


async def trace_async_call(
    name: str,
    coro: Awaitable[T],
    input_data: dict[str, Any] | None = None,
) -> T:
    """Trace an async function call with timing."""
    step = start_step_trace(name, "async_call", input_data or {})

    try:
        result = await coro
        end_step_trace({"result": str(result)[:500]})
        return result
    except Exception as e:
        if step:
            step.error = str(e)
            end_step_trace({"error": str(e)})
        raise


def trace_call(
    name: str,
    func: Callable[..., T],
    *args,
    **kwargs,
) -> T:
    """Trace a function call with timing."""
    step = start_step_trace(
        name,
        "function_call",
        {"args": str(args)[:500], "kwargs": str(kwargs)[:500]},
    )

    try:
        result = func(*args, **kwargs)
        end_step_trace({"result": str(result)[:500]})
        return result
    except Exception as e:
        if step:
            step.error = str(e)
            end_step_trace({"error": str(e)})
        raise


def export_trace_json(trace_context: TraceContext) -> str:
    """Export complete trace as JSON."""
    return json.dumps(trace_context.to_dict(), indent=2, default=str)


def export_trace_timeline(trace_context: TraceContext) -> str:
    """Export trace as a chronological timeline."""
    events = []

    for turn in trace_context.turns:
        events.append({
            "timestamp": turn.timestamp,
            "type": "turn_start",
            "turn_index": turn.turn_index,
            "duration_ms": turn.duration_ms,
        })

        for api_call in turn.api_calls:
            events.append({
                "timestamp": api_call.timestamp,
                "type": "api_call",
                "endpoint": api_call.endpoint,
                "duration_ms": api_call.duration_ms,
                "status_code": api_call.status_code,
                "tokens": api_call.tokens_used,
            })

        for step in turn.steps:
            events.append({
                "timestamp": step.timestamp,
                "type": "step",
                "name": step.name,
                "duration_ms": step.duration_ms,
            })

    # Sort by timestamp
    events.sort(key=lambda e: e["timestamp"])
    return json.dumps(events, indent=2, default=str)
