"""Base class every feedback source implements."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone

import httpx

from ..config import Settings
from ..models import FeedbackItem, Plan, SourceReport, parse_date


class Source(ABC):
    """A place feedback comes from.

    Subclasses implement ``search`` (one query) or override ``collect`` when
    the source isn't query-driven (e.g. local imports).
    """

    name: str = "source"
    label: str = "Source"
    default_enabled: bool = True
    # Seconds to wait between requests, to stay well inside rate limits.
    request_delay: float = 0.5

    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        self.http = http or httpx.Client(
            timeout=30.0,
            headers={"User-Agent": settings.http_user_agent},
            follow_redirects=True,
        )

    def status(self, plan: Plan | None = None) -> tuple[bool, str]:
        """(ready, explanation). Override when credentials or config are needed."""
        return True, "ready"

    @abstractmethod
    def search(
        self, query: str, since: date | None, limit: int, plan: Plan
    ) -> list[FeedbackItem]:
        ...

    def collect(self, plan: Plan, since: date | None, limit: int) -> tuple[list[FeedbackItem], SourceReport]:
        report = SourceReport(name=self.name)
        ready, why = self.status(plan)
        if not ready:
            report.status = "skipped"
            report.note = why
            return [], report

        items: list[FeedbackItem] = []
        for theme_name, query in plan.all_queries():
            try:
                found = self.search(query, since, limit, plan)
            except Exception as exc:  # keep going; one bad query shouldn't sink the run
                report.errors.append(f"{query!r}: {exc}")
                continue
            finally:
                report.queries_run += 1
                if self.request_delay:
                    time.sleep(self.request_delay)
            for item in found:
                item.query = item.query or query
                item.theme_hint = item.theme_hint or theme_name
            items.extend(found)

        items = [i for i in items if within(i, since)]
        report.collected = len(items)
        if report.errors and not items:
            report.status = "error"
            report.note = report.errors[0]
        else:
            report.status = "ok"
            report.note = why if why != "ready" else ""
        return items, report


def within(item: FeedbackItem, since: date | None) -> bool:
    if since is None:
        return True
    d = parse_date(item.created_at)
    return d is None or d >= since


def to_unix(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def from_unix(ts: int | float | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
