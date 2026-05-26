"""CLI entrypoint for skill-bench."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import click
import jsonlines
from rich.console import Console
from rich.table import Table

from .hill_climb import HillClimber
from .loader import load_suite, load_task
from .models import TaskScore
from .runner import Runner
from .scorer import Scorer

console = Console()


def _save_recording(recording, score: TaskScore, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / "recordings.jsonl"
    entry = {
        "task_id": recording.task_id,
        "run_id": recording.run_id,
        "score": score.overall_score,
        "assertion_results": [
            {
                "type": ar.assertion.type.value,
                "target": ar.assertion.target,
                "passed": ar.passed,
                "details": ar.details,
            }
            for ar in score.assertion_results
        ],
        "judge_results": [
            {"prompt": jr.prompt, "score": jr.score, "reasoning": jr.reasoning}
            for jr in score.judge_results
        ],
        "turns": [
            {
                "turn_index": t.turn_index,
                "user_input": t.user_input,
                "assistant_response": t.assistant_response[:1000],
                "tool_calls": [
                    {"tool": tc.tool_name, "input_keys": list(tc.input.keys())}
                    for tc in t.tool_calls
                ],
                "duration_ms": t.duration_ms,
            }
            for t in recording.turns
        ],
        "total_duration_ms": recording.total_duration_ms,
        "total_input_tokens": recording.total_input_tokens,
        "total_output_tokens": recording.total_output_tokens,
        "error": recording.error,
        "timestamp": time.time(),
    }
    with jsonlines.open(filepath, mode="a") as writer:
        writer.write(entry)


@click.group()
def main():
    """skill-bench: Benchmark and hill-climb Claude Code skills."""
    pass


@main.command()
@click.argument("tasks_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--skills", "-s", type=click.Path(exists=True, path_type=Path), help="Skills directory to test")
@click.option("--model", "-m", default="claude-sonnet-4-6", help="Model to use")
@click.option("--output", "-o", type=click.Path(path_type=Path), default="./results", help="Output directory")
@click.option("--judge-model", default="claude-sonnet-4-6", help="Model for LLM judge scoring")
def run(tasks_dir: Path, skills: Path | None, model: str, output: Path, judge_model: str):
    """Run benchmark suite against a skills directory."""
    output.mkdir(parents=True, exist_ok=True)
    tasks = load_suite(tasks_dir)
    console.print(f"[bold]Loaded {len(tasks)} tasks[/bold]")

    runner = Runner(skills_dir=skills, model=model)
    scorer = Scorer(judge_model=judge_model)

    results = []
    for task in tasks:
        console.print(f"  Running: {task.name}...", end=" ")
        run_result = runner.run_task(task)

        if run_result.recording.error:
            console.print(f"[red]ERROR[/red]: {run_result.recording.error[:80]}")
            score = TaskScore(task_id=task.id, run_id=run_result.recording.run_id)
            results.append({"task": task.id, "score": 0.0, "error": run_result.recording.error})
        else:
            score = scorer.score(task, run_result.recording, run_result.workspace)
            console.print(f"[green]{score.overall_score:.2f}[/green]")
            results.append({
                "task": task.id,
                "score": score.overall_score,
                "turns": len(run_result.recording.turns),
                "assertions_passed": sum(1 for a in score.assertion_results if a.passed),
                "assertions_total": len(score.assertion_results),
            })

        _save_recording(run_result.recording, score, output)
        run_result.cleanup()

    table = Table(title="Benchmark Results")
    table.add_column("Task", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Assertions", justify="right")
    table.add_column("Status")

    for r in results:
        status = "[green]PASS[/green]" if r["score"] >= 0.8 else "[red]FAIL[/red]"
        assertions = f"{r.get('assertions_passed', 0)}/{r.get('assertions_total', 0)}"
        table.add_row(r["task"], f"{r['score']:.2f}", assertions, status)

    console.print(table)

    avg = sum(r["score"] for r in results) / len(results) if results else 0
    console.print(f"\n[bold]Average Score: {avg:.2f}[/bold]")

    results_file = output / "summary.json"
    results_file.write_text(json.dumps({"avg_score": avg, "tasks": results}, indent=2))
    console.print(f"Results saved to {output}/")


@main.command()
@click.argument("tasks_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("skills_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--model", "-m", default="claude-sonnet-4-6")
@click.option("--iterations", "-n", default=5, help="Max hill-climb iterations")
@click.option("--output", "-o", type=click.Path(path_type=Path), default="./results")
def climb(tasks_dir: Path, skills_dir: Path, model: str, iterations: int, output: Path):
    """Hill-climb: iteratively improve skills based on benchmark scores."""
    output.mkdir(parents=True, exist_ok=True)

    climber = HillClimber(
        skills_dir=skills_dir,
        tasks_dir=tasks_dir,
        results_dir=output,
        model=model,
        max_iterations=iterations,
    )

    console.print("[bold]Starting hill-climb optimization...[/bold]")
    result = climber.run()

    console.print(f"\n[bold]Hill-Climb Complete[/bold]")
    console.print(f"  Iterations: {result.iterations}")
    console.print(f"  Initial score: {result.initial_avg_score:.2f}")
    console.print(f"  Final score: {result.final_avg_score:.2f}")
    console.print(f"  Improvement: {result.final_avg_score - result.initial_avg_score:+.2f}")

    if result.improvements:
        console.print("\n[bold]Improvements:[/bold]")
        for imp in result.improvements:
            console.print(f"  [{imp['iteration']}] {imp['change_summary'][:80]}")


@main.command()
@click.argument("task_file", type=click.Path(exists=True, path_type=Path))
def inspect(task_file: Path):
    """Inspect a task definition."""
    task = load_task(task_file)
    console.print(f"[bold]{task.name}[/bold] ({task.id})")
    console.print(f"  Description: {task.description}")
    console.print(f"  Turns: {len(task.turns)}")
    console.print(f"  Assertions: {len(task.assertions)}")
    for a in task.assertions:
        console.print(f"    - {a.type.value}: {a.target[:60]} (weight={a.weight})")
    console.print(f"  Tags: {', '.join(task.tags)}")
    console.print(f"  Timeout: {task.timeout_seconds}s")
    console.print(f"  Model: {task.model}")


@main.command()
@click.argument("recordings_file", type=click.Path(exists=True, path_type=Path))
def replay(recordings_file: Path):
    """Replay and display results from a recordings JSONL file."""
    with jsonlines.open(recordings_file) as reader:
        for entry in reader:
            score = entry.get("score", 0)
            status = "[green]PASS[/green]" if score >= 0.8 else "[red]FAIL[/red]"
            console.print(f"  {entry['task_id']} ({entry['run_id']}): {score:.2f} {status}")
            for ar in entry.get("assertion_results", []):
                icon = "[green]v[/green]" if ar["passed"] else "[red]x[/red]"
                console.print(f"    {icon} {ar['type']}: {ar['details'][:60]}")
            for jr in entry.get("judge_results", []):
                console.print(f"    [blue]judge[/blue] {jr['score']:.2f}: {jr['reasoning'][:60]}")


if __name__ == "__main__":
    main()
