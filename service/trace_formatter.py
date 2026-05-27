"""Format and analyze trace data for visualization and debugging."""

from __future__ import annotations

import json
from typing import Any
from datetime import datetime


def extract_api_calls_timeline(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract all API calls from a trace and format as timeline."""
    if not trace or "api_calls" not in trace:
        return []

    calls = []
    for api_call in trace["api_calls"]:
        calls.append({
            "timestamp": api_call["timestamp"],
            "endpoint": api_call["endpoint"],
            "method": api_call["method"],
            "duration_ms": api_call["duration_ms"],
            "status_code": api_call["status_code"],
            "tokens_input": api_call["tokens_used"].get("input", 0),
            "tokens_output": api_call["tokens_used"].get("output", 0),
            "error": api_call.get("error"),
        })

    calls.sort(key=lambda x: x["timestamp"])
    return calls


def extract_steps_timeline(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract all steps from a trace and format as timeline."""
    if not trace or "steps" not in trace:
        return []

    steps = []
    for step in trace["steps"]:
        steps.append({
            "timestamp": step["timestamp"],
            "name": step["name"],
            "type": step["step_type"],
            "duration_ms": step["duration_ms"],
            "error": step.get("error"),
        })

    steps.sort(key=lambda x: x["timestamp"])
    return steps


def extract_turn_timelines(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract timeline for each turn."""
    if not trace or "turns" not in trace:
        return []

    turn_timelines = []
    for turn in trace["turns"]:
        events = []

        # Add turn start
        events.append({
            "timestamp": turn["timestamp"],
            "type": "turn_start",
            "turn_index": turn["turn_index"],
        })

        # Add API calls
        for api_call in turn.get("api_calls", []):
            events.append({
                "timestamp": api_call["timestamp"],
                "type": "api_call",
                "endpoint": api_call["endpoint"],
                "duration_ms": api_call["duration_ms"],
                "tokens": api_call["tokens_used"],
            })

        # Add steps
        for step in turn.get("steps", []):
            events.append({
                "timestamp": step["timestamp"],
                "type": "step",
                "name": step["name"],
                "duration_ms": step["duration_ms"],
            })

        # Sort events by timestamp
        events.sort(key=lambda x: x["timestamp"])

        turn_timelines.append({
            "turn_index": turn["turn_index"],
            "duration_ms": turn["duration_ms"],
            "tokens_input": turn.get("input_tokens", 0),
            "tokens_output": turn.get("output_tokens", 0),
            "events": events,
        })

    return turn_timelines


def format_call_stack(call_stack: list[str]) -> str:
    """Format a call stack for display."""
    if not call_stack:
        return "No stack trace available"
    return "\n".join(f"  {line}" for line in call_stack)


def get_trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    """Generate a summary of trace metrics."""
    if not trace:
        return {}

    total_api_calls = len(trace.get("api_calls", []))
    total_steps = len(trace.get("steps", []))
    total_turns = len(trace.get("turns", []))

    total_input_tokens = sum(
        api_call["tokens_used"].get("input", 0)
        for api_call in trace.get("api_calls", [])
    )
    total_output_tokens = sum(
        api_call["tokens_used"].get("output", 0)
        for api_call in trace.get("api_calls", [])
    )

    total_duration_ms = 0
    for turn in trace.get("turns", []):
        total_duration_ms += turn.get("duration_ms", 0)

    api_errors = [
        {
            "endpoint": call["endpoint"],
            "error": call["error"],
            "timestamp": call["timestamp"],
        }
        for call in trace.get("api_calls", [])
        if call.get("error")
    ]

    step_errors = [
        {
            "name": step["name"],
            "error": step["error"],
            "timestamp": step["timestamp"],
        }
        for step in trace.get("steps", [])
        if step.get("error")
    ]

    return {
        "total_api_calls": total_api_calls,
        "total_steps": total_steps,
        "total_turns": total_turns,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_duration_ms": total_duration_ms,
        "api_errors": api_errors,
        "step_errors": step_errors,
        "has_errors": bool(api_errors or step_errors),
    }


def export_trace_html(trace: dict[str, Any]) -> str:
    """Export trace as an HTML report."""
    summary = get_trace_summary(trace)
    turn_timelines = extract_turn_timelines(trace)

    html = f"""
    <html>
    <head>
        <title>Trace Report</title>
        <style>
            body {{ font-family: monospace; margin: 20px; }}
            h1 {{ color: #333; }}
            .summary {{ background: #f5f5f5; padding: 10px; margin: 10px 0; }}
            .turn {{ background: #e8f4f8; padding: 10px; margin: 10px 0; border-left: 3px solid #0066cc; }}
            .event {{ margin-left: 20px; padding: 5px; font-size: 0.9em; }}
            .api-call {{ color: #0066cc; }}
            .step {{ color: #006600; }}
            .error {{ color: #cc0000; }}
            table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
            td, th {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
        </style>
    </head>
    <body>
        <h1>Trace Report</h1>
        <div class="summary">
            <h2>Summary</h2>
            <p>Total Turns: {summary['total_turns']}</p>
            <p>Total API Calls: {summary['total_api_calls']}</p>
            <p>Total Steps: {summary['total_steps']}</p>
            <p>Total Input Tokens: {summary['total_input_tokens']}</p>
            <p>Total Output Tokens: {summary['total_output_tokens']}</p>
            <p>Total Duration: {summary['total_duration_ms']:.0f}ms</p>
            {'<p style="color: red;">Errors Found: ' + str(len(summary.get("api_errors", [])) + len(summary.get("step_errors", []))) + '</p>' if summary.get("has_errors") else ""}
        </div>

        <h2>Turn-by-Turn Timeline</h2>
    """

    for turn in turn_timelines:
        html += f"""
        <div class="turn">
            <h3>Turn {turn['turn_index']}</h3>
            <p>Duration: {turn['duration_ms']:.0f}ms | Input Tokens: {turn['tokens_input']} | Output Tokens: {turn['tokens_output']}</p>
            <div>
        """

        for event in turn["events"]:
            if event["type"] == "turn_start":
                html += f'<div class="event">▶ Turn Started</div>'
            elif event["type"] == "api_call":
                html += f'<div class="event api-call">→ API Call: {event["endpoint"]} ({event["duration_ms"]:.0f}ms) Tokens: {event["tokens"]["input"]}/{event["tokens"]["output"]}</div>'
            elif event["type"] == "step":
                html += f'<div class="event step">• Step: {event["name"]} ({event["duration_ms"]:.0f}ms)</div>'

        html += """
            </div>
        </div>
        """

    html += """
    </body>
    </html>
    """

    return html
