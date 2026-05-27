# Tracing Quick Reference

## What You Now Have

✅ **Timestamps** - Every operation has ISO 8601 timestamps  
✅ **API Calls** - Complete request/response bodies, status codes, tokens, duration  
✅ **Call Stacks** - Where each API call originated from  
✅ **Step Traces** - Detailed steps with input/output data  
✅ **Timeline Views** - Chronological ordering of all operations  

## Access Trace Data

### Via API (Recommended)

```bash
# Get complete trace for a result
curl http://localhost:8000/api/v1/results/result123/trace

# Get chronological timeline
curl http://localhost:8000/api/v1/results/result123/trace/timeline

# Get summary metrics
curl http://localhost:8000/api/v1/results/result123/trace/summary

# Get HTML report
curl http://localhost:8000/api/v1/results/result123/trace/html > report.html

# Get trace for specific turn
curl http://localhost:8000/api/v1/results/result123/turns/0/trace
```

### Via Python

```python
import json
from service import db, trace_formatter

# Fetch a result's trace
result = await db.fetch_one("SELECT trace_json FROM results WHERE id = ?", ("result_id",))
trace = json.loads(result["trace_json"])

# Get summary
summary = trace_formatter.get_trace_summary(trace)
print(f"API calls: {summary['total_api_calls']}")
print(f"Duration: {summary['total_duration_ms']}ms")
print(f"Tokens: {summary['total_input_tokens']}/{summary['total_output_tokens']}")
print(f"Errors: {len(summary['api_errors']) + len(summary['step_errors'])}")

# Get timeline
timelines = trace_formatter.extract_turn_timelines(trace)
for turn in timelines:
    for event in turn['events']:
        print(f"{event['timestamp']} - {event['type']}: {event.get('endpoint', event.get('name'))}")
```

## Trace Structure

```
Trace
├── APICall
│   ├── timestamp
│   ├── endpoint
│   ├── request_body
│   ├── response_body
│   ├── status_code
│   ├── duration_ms
│   ├── tokens_used
│   ├── error
│   └── call_stack
├── StepTrace
│   ├── timestamp
│   ├── name
│   ├── step_type
│   ├── input_data
│   ├── output_data
│   ├── duration_ms
│   ├── api_call_ids
│   └── call_stack
└── TurnTrace
    ├── timestamp
    ├── turn_index
    ├── duration_ms
    ├── api_calls[]
    ├── steps[]
    └── thinking_trace
```

## Example: Debugging a Slow Response

```python
import json
from service import db, trace_formatter

async def debug_slow_result(result_id):
    result = await db.fetch_one("SELECT trace_json FROM results WHERE id = ?", (result_id,))
    trace = json.loads(result["trace_json"])
    
    summary = trace_formatter.get_trace_summary(trace)
    
    # Find slowest turn
    turn_timelines = trace_formatter.extract_turn_timelines(trace)
    slowest_turn = max(turn_timelines, key=lambda t: t['duration_ms'])
    
    print(f"Slowest turn: {slowest_turn['turn_index']} ({slowest_turn['duration_ms']:.0f}ms)")
    
    # Find slowest API call in that turn
    slowest_call = max(
        [e for e in slowest_turn['events'] if e['type'] == 'api_call'],
        key=lambda e: e['duration_ms']
    )
    
    print(f"Slowest API call: {slowest_call['endpoint']} ({slowest_call['duration_ms']:.0f}ms)")
```

## Example: Comparing Jobs

```python
import json
from service import db, trace_formatter

async def compare_traces(job_id_1, job_id_2):
    for job_id in [job_id_1, job_id_2]:
        results = await db.fetch_all("SELECT trace_json FROM results WHERE job_id = ?", (job_id,))
        for result in results:
            trace = json.loads(result["trace_json"])
            summary = trace_formatter.get_trace_summary(trace)
            print(f"Job {job_id}:")
            print(f"  API calls: {summary['total_api_calls']}")
            print(f"  Duration: {summary['total_duration_ms']:.0f}ms")
            print(f"  Tokens: {summary['total_input_tokens']}")
```

## Key Fields in Traces

### APICall
- `timestamp` - When the API call was made (ISO 8601)
- `endpoint` - API endpoint (e.g., "/messages")
- `request_body` - What was sent (sanitized)
- `response_body` - What was received
- `duration_ms` - How long the call took
- `tokens_used` - `{input: N, output: M}`
- `call_stack` - Where this was called from

### StepTrace
- `timestamp` - When the step started
- `name` - Step name for debugging
- `step_type` - "api_call", "computation", "tool_execution", etc
- `input_data` - Input to the step
- `output_data` - Result of the step
- `duration_ms` - Execution time
- `api_call_ids` - Which API calls this step made

### TurnTrace
- `timestamp` - When the turn started
- `turn_index` - 0-indexed turn number
- `duration_ms` - Total turn time
- `api_calls` - All API calls made during this turn
- `steps` - All computation steps
- `thinking_trace` - Claude's thinking (if enabled)

## Exporting Data

```bash
# Export as JSON
curl http://localhost:8000/api/v1/results/result123/trace > trace.json

# Export as formatted HTML
curl http://localhost:8000/api/v1/results/result123/trace/html > report.html

# Export as timeline
curl http://localhost:8000/api/v1/results/result123/trace/timeline | jq
```

## Database Queries

```sql
-- Find slowest result
SELECT id, overall_score, json_extract(trace_json, '$.turns[0].duration_ms') as first_turn_ms
FROM results
WHERE trace_json IS NOT NULL
ORDER BY json_extract(trace_json, '$.turns[0].duration_ms') DESC
LIMIT 1;

-- Count API calls per job
SELECT job_id, COUNT(*) as api_calls
FROM (
  SELECT job_id, json_each.key
  FROM results
  JOIN json_each(trace_json, '$.api_calls')
  WHERE trace_json IS NOT NULL
)
GROUP BY job_id;

-- Find errored API calls
SELECT id, json_extract(trace_json, '$.api_calls[?(@.error)]')
FROM results
WHERE trace_json IS NOT NULL
AND json_extract(trace_json, '$.api_calls[?(@.error)]') IS NOT NULL;
```

## What's Captured per API Call?

1. **When** - ISO 8601 timestamp
2. **What** - Endpoint, method, request body
3. **How long** - Duration in milliseconds
4. **Status** - HTTP status code
5. **Result** - Response body
6. **Tokens** - Input and output tokens used
7. **Where** - Full call stack showing which function called the API
8. **Error** - If it failed, what was the error

## What's NOT Captured

- System prompts (for privacy)
- Full raw API keys (for security)
- Streaming token-by-token (only final counts)
- Wall-clock time between turns (only duration)
