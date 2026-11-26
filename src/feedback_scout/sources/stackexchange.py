"""Stack Overflow (and other Stack Exchange sites) via the official API.

OFF BY DEFAULT. Stack Exchange's terms require express prior written consent
for automated collection used in generative-AI work. Read the current API
Terms of Use and enable this source only if your use is permitted.
Docs: https://api.stackexchange.com/docs
"""

from __future__ import annotations

from datetime import date

from ..models import FeedbackItem, Plan
from ..text import html_to_text
from .base import Source, from_unix, to_unix

API = "https://api.stackexchange.com/2.3/search/advanced"


class StackExchange(Source):
    name = "stackoverflow"
    label = "Stack Overflow"
    default_enabled = False
    request_delay = 0.5
    site = "stackoverflow"

    def status(self, plan: Plan | None = None) -> tuple[bool, str]:
        note = "opt-in: check Stack Exchange API terms for AI use before enabling"
        if not self.settings.stackexchange_key:
            note += "; no STACKEXCHANGE_KEY, so a low daily quota applies"
        return True, note

    def search(self, query: str, since: date | None, limit: int, plan: Plan) -> list[FeedbackItem]:
        params = {
            "q": query,
            "site": self.site,
            "order": "desc",
            "sort": "relevance",
            "pagesize": min(max(limit, 1), 100),
            "filter": "withbody",
        }
        if since:
            params["fromdate"] = to_unix(since)
        if self.settings.stackexchange_key:
            params["key"] = self.settings.stackexchange_key
        resp = self.http.get(API, params=params)
        resp.raise_for_status()
        items = []
        for q in resp.json().get("items", []):
            title = html_to_text(q.get("title", ""))
            items.append(
                FeedbackItem(
                    source=self.name,
                    url=q.get("link", ""),
                    title=title,
                    text=f"{title}\n\n{html_to_text(q.get('body', ''))}".strip(),
                    author=(q.get("owner") or {}).get("display_name", ""),
                    created_at=from_unix(q.get("creation_date")),
                    score=q.get("score"),
                    extra={"tags": q.get("tags", [])},
                )
            )
        return items
