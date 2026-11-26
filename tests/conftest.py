from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from feedback_scout.config import Settings
from feedback_scout.models import Plan, Theme


@pytest.fixture
def settings() -> Settings:
    return Settings(anthropic_api_key="test-key", reddit_client_id="id", reddit_client_secret="secret")


@pytest.fixture
def plan() -> Plan:
    return Plan(
        company="Snowflake",
        scope="query cost and data quality",
        themes=[
            Theme(name="Query cost", description="cost of queries", queries=["snowflake query cost"]),
            Theme(name="Data quality", description="data quality checks", queries=["snowflake data quality"]),
        ],
        subreddits=["snowflake"],
        github_orgs=["snowflakedb"],
    )


def mock_http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class FakeMessages:
    """Stands in for anthropic.Anthropic().messages; returns queued responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def fake_client(*responses):
    return SimpleNamespace(messages=FakeMessages(responses))


def tool_response(name: str, payload: dict):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input=payload)], stop_reason="tool_use")


def text_response(text: str, extra_blocks=()):
    return SimpleNamespace(content=[*extra_blocks, SimpleNamespace(type="text", text=text)], stop_reason="end_turn")
