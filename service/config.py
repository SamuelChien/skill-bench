from __future__ import annotations

import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    claude_oauth_token: str = ""
    database_path: str = "skill_bench.db"
    num_workers: int = 2
    default_model: str = "claude-sonnet-4-6"
    default_judge_model: str = "claude-sonnet-4-6"
    default_thinking_budget: int = 10000

    model_config = {"env_prefix": "SKILL_BENCH_", "env_file": ".env"}

    def get_api_key(self) -> str:
        return (
            self.anthropic_api_key
            or os.environ.get("ANTHROPIC_API_KEY", "")
            or self.claude_oauth_token
            or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        )


settings = Settings()
