# Comprehensive Tracing Guide

This document explains the new observability system that captures detailed traces of all operations: timestamps, API calls, call stacks, and step-by-step execution data.

## Overview

The tracing system captures:

1. **Timestamps** - ISO 8601 timestamps for every operation
2. **API Calls** - Full details of each Claude API call:
   - Request body (sanitized)
   - Response body
   - Status code
   - Duration (ms)
   - Tokens used (input/output)
   - Call stack (where the API was called from)
   - Errors
3. **Steps** - Granular execution steps:
   - Step name and type
   - Input/output data
   - Duration
   - Parent-child relationships
   - Associated API calls
4. **Call Stacks** - Full call stacks for debugging which function called what

## Architecture

### Core Components

- **`service/tracing.py`** - Main tracing module with context management
- **`service/trace_formatter.py`** - Utilities for formatting and analyzing traces
- **`service/sandbox.py`** - Integration with Claude API calls (modified)
- **`service/worker.py`** - Job execution with trace context (modified)
- **Database** - New `trace_json` columns in `results` and `turns` tables

### Data Model

```
TraceContext
├── APICall[]
├── StepTrace[]
└── TurnTrace[]
    ├── APICall[]
    ├── StepTrace[]
    └── metadata
```

## Usage

### Starting a Trace

```python
from service import tracing

# Start a trace for a job/task
trace_ctx = tracing.start_trace(job_id="job123", task_id="task456")
```

### Tracing Turns

```python
# Begin turn
turn_trace = tracing.start_turn_trace(turn_index=0, user_input="Hello")

# ... do work ...

# End turn - automatically saved to trace context
end_turn_trace()
```

### Recording API Calls

```python
tracing.record_api_call(
    endpoint="/messages",
    method="POST",
    request_body={...},
    response_body={...},
    status_code=200,
    duration_ms=150.5,
    tokens_used={"input": 100, "output": 50},
    error=None,
)
```

### Tracing Steps

```python
# Start a step
step = tracing.start_step_trace(
    name="score_assertion",
    step_type="computation",
    input_data={"assertion": {...}}
)

# ... do work ...

# End step
tracing.end_step_trace(output_data={"passed": True})
```

### Accessing Trace Data

```python
# Get current context
ctx = tracing.get_trace_context()

# Export as JSON
json_str = tracing.export_trace_json(ctx)

# Export as timeline
timeline = tracing.export_trace_timeline(ctx)
```

## API Endpoints

### Get Result Trace

```
GET /api/v1/results/{result_id}/trace
```

Returns complete trace data as JSON.

### Get Trace Timeline

```
GET /api/v1/results/{result_id}/trace/timeline
```

Returns chronological timeline of:
- API calls with duration and tokens
- Steps with duration
- Turns with nested events

Example response:
```json
{
  "api_calls": [
    {
      "timestamp": "2026-05-27T12:34:56.789Z",
      "endpoint": "/messages",
      "method": "POST",
      "duration_ms": 150.5,
      "status_code": 200,
      "tokens_input": 100,
      "tokens_output": 50
    }
  ],
  "steps": [...],
  "turns": [
    {
      "turn_index": 0,
      "duration_ms": 200,
      "tokens_input": 100,
      "tokens_output": 50,
      "events": [
        {
          "timestamp": "...",
          "type": "api_call",
          "endpoint": "/messages",
          "duration_ms": 150
        }
      ]
    }
  ]
}
```

### Get Trace Summary

```
GET /api/v1/results/{result_id}/trace/summary
```

Returns high-level metrics:
- Total API calls, steps, turns
- Total tokens (input/output)
- Total duration
- Errors (if any)

### Get Trace HTML Report

```
GET /api/v1/results/{result_id}/trace/html
```

Returns formatted HTML report with:
- Summary statistics
- Turn-by-turn timeline visualization
- All events chronologically ordered

### Get Turn Trace

```
GET /api/v1/results/{result_id}/turns/{turn_index}/trace
```

Returns detailed trace for a specific turn including:
- All API calls for that turn
- All steps
- Timestamps for each operation
- Call stacks

## Data Storage

### Results Table

- `trace_json` (TEXT) - Complete trace context for the result

### Turns Table

- `trace_json` (TEXT) - Detailed trace for this turn

## Example: Analyzing a Trace

```python
import json
from service import trace_formatter, db

# Fetch a result
result = await db.fetch_one("SELECT trace_json FROM results WHERE id = ?", ("result123",))
trace = json.loads(result["trace_json"])

# Get summary
summary = trace_formatter.get_trace_summary(trace)
print(f"Total API calls: {summary['total_api_calls']}")
print(f"Total duration: {summary['total_duration_ms']}ms")
print(f"Total tokens: {summary['total_input_tokens']}/{summary['total_output_tokens']}")

# Get turn timelines
timelines = trace_formatter.extract_turn_timelines(trace)
for turn in timelines:
    print(f"\nTurn {turn['turn_index']}:")
    for event in turn['events']:
        if event['type'] == 'api_call':
            print(f"  → {event['endpoint']} ({event['duration_ms']:.0f}ms)")

# Export as HTML
html = trace_formatter.export_trace_html(trace)
```

## Call Stack Information

Every API call and step records the call stack, showing exactly which function called it:

```json
{
  "call_stack": [
    "/service/sandbox.py:207 in _complete_with_tool_loop",
    "/service/sandbox.py:107 in run_conversation",
    "/service/worker.py:170 in _run_benchmark"
  ]
}
```

This helps debug exactly where API calls are being made from.

## Timestamp Ordering

All timestamps are ISO 8601 format (`YYYY-MM-DDTHH:MM:SS.fffZ`), making it trivial to sort events chronologically:

```python
events.sort(key=lambda e: e["timestamp"])
```

## Privacy & Security

Traces are automatically sanitized to remove sensitive data:
- API keys are redacted
- Passwords/tokens are redacted
- Large strings (>5000 chars) are truncated

System prompts are not included in request bodies by design.

## Performance Considerations

- Tracing adds minimal overhead (microseconds per operation)
- Trace data is stored efficiently in JSON columns
- Call stacks are limited to 10 frames by default
- Large response bodies are truncated to 5000 chars

## Future Enhancements

- [ ] Real-time trace streaming to dashboard
- [ ] Comparative analysis across jobs
- [ ] Performance bottleneck detection
- [ ] Distributed tracing across multiple workers
- [ ] Custom trace filtering/querying
