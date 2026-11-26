"""Core data types shared by sources, the LLM steps and the report."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class FeedbackItem:
    """One piece of public feedback: a review, post, comment or issue."""

    source: str
    url: str
    text: str
    title: str = ""
    author: str = ""
    created_at: str = ""  # ISO 8601 date or datetime, "" if unknown
    score: int | None = None
    query: str = ""
    theme_hint: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        key = f"{self.source}|{self.url}|{self.text[:200]}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["id"] = self.id
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "FeedbackItem":
        data = {k: v for k, v in data.items() if k != "id"}
        return cls(**data)


@dataclass
class Theme:
    name: str
    description: str = ""
    queries: list[str] = field(default_factory=list)


@dataclass
class Plan:
    """What to look for, produced from the user's prompt."""

    company: str
    scope: str
    themes: list[Theme]
    subreddits: list[str] = field(default_factory=list)
    github_repos: list[str] = field(default_factory=list)
    github_orgs: list[str] = field(default_factory=list)
    discourse_forums: list[str] = field(default_factory=list)
    audience: str = ""
    notes: str = ""

    def all_queries(self) -> list[tuple[str, str]]:
        """(theme name, query) pairs, de-duplicated, in order."""
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for theme in self.themes:
            for q in theme.queries:
                key = q.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    out.append((theme.name, q.strip()))
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        themes = [Theme(**t) for t in data.get("themes", [])]
        rest = {k: v for k, v in data.items() if k != "themes"}
        return cls(themes=themes, **rest)


@dataclass
class Label:
    """The classifier's verdict on one item."""

    id: str
    relevant: bool
    theme: str = "other"
    about_company: str = "unclear"  # yes | no | unclear
    pain: str = ""
    severity: int = 0  # 0 none, 1 annoyance, 2 real cost, 3 blocker / trust / money
    sentiment: str = "neutral"


@dataclass
class SourceReport:
    """Coverage bookkeeping for one source in one run."""

    name: str
    status: str = "not run"  # ok | skipped | error | not run
    note: str = ""
    collected: int = 0
    queries_run: int = 0
    errors: list[str] = field(default_factory=list)


def parse_date(value: str) -> date | None:
    """Best-effort ISO date parse; returns None if unknown."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
