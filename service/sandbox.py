"""Sandbox: run multi-turn conversations via Anthropic SDK with tool use + thinking traces."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Awaitable

import anthropic

from service.config import settings
from service import tracing

logger = logging.getLogger("skill-bench.sandbox")

ToolHandler = Callable[[str, dict[str, Any]], Awaitable[str]]

API_TIMEOUT_SECONDS = 120


async def _default_tool_handler(tool_name: str, tool_input: dict[str, Any]) -> str:
    return json.dumps({"error": f"No handler registered for tool '{tool_name}'"})


def _content_blocks_to_dicts(content: list) -> list[dict[str, Any]]:
    result = []
    for block in content:
        if hasattr(block, "type"):
            if block.type == "text":
                result.append({"type": "text", "text": block.text})
            elif block.type == "thinking":
                result.append({
                    "type": "thinking", "thinking": block.thinking,
                    "signature": getattr(block, "signature", ""),
                })
            elif block.type == "tool_use":
                result.append({
                    "type": "tool_use", "id": block.id,
                    "name": block.name, "input": block.input,
                })
            elif block.type == "tool_result":
                result.append({
                    "type": "tool_result", "tool_use_id": block.tool_use_id,
                    "content": block.content,
                })
            else:
                result.append({"type": block.type})
        elif isinstance(block, dict):
            result.append(block)
    return result


def _extract_text(response: Any) -> str:
    if not response or not hasattr(response, "content"):
        return ""
    return "".join(
        block.text for block in response.content
        if hasattr(block, "type") and block.type == "text"
    )


async def run_conversation(
    system_prompt: str,
    turns: list[dict[str, str]],
    model: str | None = None,
    tools: list[dict] | None = None,
    tool_handler: ToolHandler | None = None,
    enable_thinking: bool = True,
    thinking_budget: int = 10000,
    max_tokens: int = 16000,
) -> dict[str, Any]:
    model = model or settings.default_model
    handler = tool_handler or _default_tool_handler
    client = anthropic.AsyncAnthropic(api_key=settings.get_api_key() or None)

    messages: list[dict[str, Any]] = []
    turn_records: list[dict[str, Any]] = []
    total_input = 0
    total_output = 0
    total_start = time.monotonic()
    error = None

    api_tools = None
    if tools:
        api_tools = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]

    for turn_idx, turn in enumerate(turns):
        turn_start = time.monotonic()
        user_content = turn["content"]
        messages.append({"role": "user", "content": user_content})

        assistant_text = ""
        thinking_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        turn_input_tokens = 0
        turn_output_tokens = 0

        # Start tracing for this turn
        turn_trace = tracing.start_turn_trace(turn_idx, user_content)

        try:
            final_response, accumulated_tokens = await _complete_with_tool_loop(
                client=client,
                model=model,
                system_prompt=system_prompt,
                messages=messages,
                tools=api_tools,
                handler=handler,
                enable_thinking=enable_thinking,
                thinking_budget=thinking_budget,
                max_tokens=max_tokens,
                tool_calls_out=tool_calls,
                thinking_parts_out=thinking_parts,
            )

            if final_response and hasattr(final_response, "content"):
                for block in final_response.content:
                    if block.type == "text":
                        assistant_text += block.text
                    elif block.type == "thinking":
                        thinking_parts.append(block.thinking)

            if final_response and hasattr(final_response, "usage"):
                turn_input_tokens = accumulated_tokens["input"] + final_response.usage.input_tokens
                turn_output_tokens = accumulated_tokens["output"] + final_response.usage.output_tokens
            else:
                turn_input_tokens = accumulated_tokens["input"]
                turn_output_tokens = accumulated_tokens["output"]

            total_input += turn_input_tokens
            total_output += turn_output_tokens

            if final_response and hasattr(final_response, "content"):
                messages.append({
                    "role": "assistant",
                    "content": _content_blocks_to_dicts(final_response.content),
                })

        except Exception as e:
            logger.exception("Error on turn %d", turn_idx)
            error = str(e)
            assistant_text = f"[ERROR: {e}]"

        turn_duration = int((time.monotonic() - turn_start) * 1000)
        thinking_text = "\n\n".join(thinking_parts) if thinking_parts else None

        # Update turn trace with final data
        if turn_trace:
            turn_trace.assistant_response = assistant_text
            turn_trace.thinking_trace = thinking_text
            turn_trace.tool_calls = tool_calls
            turn_trace.input_tokens = turn_input_tokens
            turn_trace.output_tokens = turn_output_tokens
            tracing.end_turn_trace()

        turn_records.append({
            "turn_index": turn_idx,
            "user_input": user_content,
            "assistant_response": assistant_text,
            "thinking_trace": thinking_text,
            "tool_calls": tool_calls,
            "input_tokens": turn_input_tokens,
            "output_tokens": turn_output_tokens,
            "duration_ms": turn_duration,
        })

        if error:
            break

    total_duration = int((time.monotonic() - total_start) * 1000)

    # Get complete trace context
    trace_context = tracing.get_trace_context()

    return {
        "turns": turn_records,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_duration_ms": total_duration,
        "error": error,
        "trace": trace_context.to_dict() if trace_context else None,
    }


async def _complete_with_tool_loop(
    client: anthropic.AsyncAnthropic,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict] | None,
    handler: ToolHandler,
    enable_thinking: bool,
    thinking_budget: int,
    max_tokens: int,
    tool_calls_out: list[dict[str, Any]],
    thinking_parts_out: list[str],
    max_tool_rounds: int = 20,
) -> tuple[Any, dict[str, int]]:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
    if enable_thinking and thinking_budget > 0:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

    accumulated = {"input": 0, "output": 0}

    for _round in range(max_tool_rounds):
        api_call_start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                client.messages.create(**kwargs),
                timeout=API_TIMEOUT_SECONDS,
            )
            api_call_duration = (time.monotonic() - api_call_start) * 1000

            # Record the API call
            tracing.record_api_call(
                endpoint="/messages",
                method="POST",
                request_body={
                    "model": model,
                    "max_tokens": max_tokens,
                    "system_prompt_length": len(system_prompt),
                    "num_messages": len(messages),
                    "tools": [t.get("name") for t in tools] if tools else None,
                    "thinking_enabled": enable_thinking,
                },
                response_body={
                    "stop_reason": response.stop_reason,
                    "content_blocks": len(response.content),
                },
                status_code=200,
                duration_ms=api_call_duration,
                tokens_used={
                    "input": response.usage.input_tokens,
                    "output": response.usage.output_tokens,
                },
            )
        except Exception as e:
            api_call_duration = (time.monotonic() - api_call_start) * 1000
            tracing.record_api_call(
                endpoint="/messages",
                method="POST",
                request_body={"model": model},
                response_body={},
                status_code=500,
                duration_ms=api_call_duration,
                error=str(e),
            )
            raise

        has_tool_use = any(
            block.type == "tool_use" for block in response.content
            if hasattr(block, "type")
        )

        if not has_tool_use:
            return response, accumulated

        for block in response.content:
            if hasattr(block, "type") and block.type == "thinking":
                thinking_parts_out.append(block.thinking)

        accumulated["input"] += response.usage.input_tokens
        accumulated["output"] += response.usage.output_tokens

        tool_results = []
        for block in response.content:
            if not (hasattr(block, "type") and block.type == "tool_use"):
                continue

            tc_start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    handler(block.name, block.input),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                result = json.dumps({"error": f"Tool '{block.name}' timed out"})
            except Exception as e:
                result = json.dumps({"error": str(e)})

            tc_duration = int((time.monotonic() - tc_start) * 1000)
            tool_calls_out.append({
                "tool_name": block.name,
                "input": block.input,
                "output": result[:5000],
                "duration_ms": tc_duration,
            })

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({
            "role": "assistant",
            "content": _content_blocks_to_dicts(response.content),
        })
        messages.append({"role": "user", "content": tool_results})

    logger.warning("Tool loop exhausted %d rounds — forcing text extraction", max_tool_rounds)
    accumulated["input"] += response.usage.input_tokens
    accumulated["output"] += response.usage.output_tokens
    return response, accumulated
