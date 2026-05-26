"""Hill-climb loop: iteratively improves skills based on benchmark scores."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from .loader import load_suite
from .models import BenchmarkTask, TaskScore
from .runner import Runner
from .scorer import Scorer


@dataclass
class HillClimbResult:
    iterations: int
    initial_avg_score: float
    final_avg_score: float
    improvements: list[dict]


class HillClimber:
    def __init__(
        self,
        skills_dir: Path,
        tasks_dir: Path,
        results_dir: Path,
        model: str = "claude-sonnet-4-6",
        max_iterations: int = 5,
        improvement_threshold: float = 0.05,
    ):
        self.skills_dir = skills_dir
        self.tasks_dir = tasks_dir
        self.results_dir = results_dir
        self.model = model
        self.max_iterations = max_iterations
        self.improvement_threshold = improvement_threshold
        self.client = anthropic.Anthropic()
        self._backup_path: Path | None = None
        self._backup_content: str | None = None

    def run(self) -> HillClimbResult:
        tasks = load_suite(self.tasks_dir)
        runner = Runner(skills_dir=self.skills_dir, model=self.model)
        scorer = Scorer()

        initial_scores = self._evaluate_suite(tasks, runner, scorer)
        initial_avg = self._avg_score(initial_scores)

        improvements = []
        current_scores = initial_scores

        for iteration in range(self.max_iterations):
            weakest = self._find_weakest_tasks(current_scores)
            if not weakest:
                break

            skill_suggestion = self._suggest_improvement(weakest, tasks)
            if not skill_suggestion:
                break

            self._apply_suggestion(skill_suggestion)

            new_scores = self._evaluate_suite(tasks, runner, scorer)
            new_avg = self._avg_score(new_scores)

            if new_avg > self._avg_score(current_scores) + self.improvement_threshold:
                improvements.append({
                    "iteration": iteration,
                    "change_summary": skill_suggestion.get("summary", ""),
                    "old_avg": self._avg_score(current_scores),
                    "new_avg": new_avg,
                })
                current_scores = new_scores
            else:
                self._revert_suggestion(skill_suggestion)

            self._save_iteration(iteration, current_scores)

        return HillClimbResult(
            iterations=len(improvements),
            initial_avg_score=initial_avg,
            final_avg_score=self._avg_score(current_scores),
            improvements=improvements,
        )

    def _evaluate_suite(
        self, tasks: list[BenchmarkTask], runner: Runner, scorer: Scorer
    ) -> dict[str, TaskScore]:
        scores = {}
        for task in tasks:
            run_result = runner.run_task(task)
            try:
                if run_result.recording.error:
                    score = TaskScore(task_id=task.id, run_id=run_result.recording.run_id)
                    score.overall_score = 0.0
                else:
                    score = scorer.score(task, run_result.recording, run_result.workspace)
                scores[task.id] = score
            finally:
                run_result.cleanup()
        return scores

    def _avg_score(self, scores: dict[str, TaskScore]) -> float:
        if not scores:
            return 0.0
        return sum(s.overall_score for s in scores.values()) / len(scores)

    def _find_weakest_tasks(self, scores: dict[str, TaskScore]) -> list[tuple[str, float]]:
        sorted_scores = sorted(scores.items(), key=lambda x: x[1].overall_score)
        return [(tid, s.overall_score) for tid, s in sorted_scores if s.overall_score < 0.8][:3]

    def _suggest_improvement(self, weak_tasks: list[tuple[str, float]], tasks: list[BenchmarkTask]) -> dict | None:
        task_descriptions = []
        for tid, score in weak_tasks:
            task = next((t for t in tasks if t.id == tid), None)
            if task:
                task_descriptions.append(f"- {task.name} (score: {score:.2f}): {task.description}")

        skill_files = {}
        for path in self.skills_dir.rglob("*.md"):
            skill_files[str(path.relative_to(self.skills_dir))] = path.read_text()[:2000]

        prompt = f"""You are improving Claude Code skills to perform better on benchmark tasks.

WEAK TASKS (need improvement):
{chr(10).join(task_descriptions)}

CURRENT SKILLS:
{json.dumps(skill_files, indent=2)[:5000]}

Suggest ONE specific edit to an existing skill file (or a new skill) that would help with the weakest tasks.
Respond in JSON only:
{{
  "file": "path/to/skill.md",
  "action": "edit" | "create",
  "new_content": "full file content",
  "summary": "what changed and why"
}}"""

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )

        try:
            text = response.content[0].text
            start = text.find("{")
            end = text.rfind("}") + 1
            return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            return None

    def _apply_suggestion(self, suggestion: dict):
        path = self.skills_dir / suggestion["file"]
        self._backup_path = path
        self._backup_content = path.read_text() if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(suggestion["new_content"])

    def _revert_suggestion(self, suggestion: dict):
        path = self.skills_dir / suggestion["file"]
        if self._backup_content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(self._backup_content)

    def _save_iteration(self, iteration: int, scores: dict[str, TaskScore]):
        iter_dir = self.results_dir / f"iteration_{iteration:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        summary = {tid: s.overall_score for tid, s in scores.items()}
        (iter_dir / "scores.json").write_text(json.dumps(summary, indent=2))
