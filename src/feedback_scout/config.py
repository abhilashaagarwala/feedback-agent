"""Settings loaded from environment variables (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-5-5"


@dataclass
class Settings:
    anthropic_api_key: str | None = None
    model: str = DEFAULT_MODEL
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "feedback-scout/0.1 (personal research)"
    github_token: str | None = None
    stackexchange_key: str | None = None
    http_user_agent: str = "feedback-scout/0.1 (+https://github.com/)"

    @classmethod
    def from_env(cls, env_file: str | None = None) -> "Settings":
        load_dotenv(env_file or ".env", override=False)
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            model=os.getenv("FEEDBACK_SCOUT_MODEL", DEFAULT_MODEL),
            reddit_client_id=os.getenv("REDDIT_CLIENT_ID"),
            reddit_client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            reddit_user_agent=os.getenv("REDDIT_USER_AGENT", cls.reddit_user_agent),
            github_token=os.getenv("GITHUB_TOKEN"),
            stackexchange_key=os.getenv("STACKEXCHANGE_KEY"),
            http_user_agent=os.getenv("HTTP_USER_AGENT", cls.http_user_agent),
        )
