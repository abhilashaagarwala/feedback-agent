"""Hacker News via the official Algolia search API (no key needed).

Docs: https://hn.algolia.com/api
"""

from __future__ import annotations

from datetime import date

from ..models import FeedbackItem, Plan
from ..text import html_to_text
from .base import Source, to_unix

API = "https://hn.algolia.com/api/v1/search"


class HackerNews(Source):
    name = "hackernews"
    label = "Hacker News"
    request_delay = 0.3

    def search(self, query: str, since: date | None, limit: int, plan: Plan) -> list[FeedbackItem]:
        params = {
            "query": query,
            "tags": "(story,comment)",
            "hitsPerPage": min(max(limit, 1), 100),
        }
        if since:
            params["numericFilters"] = f"created_at_i>{to_unix(since)}"
        resp = self.http.get(API, params=params)
        resp.raise_for_status()
        items = []
        for hit in resp.json().get("hits", []):
            body = hit.get("comment_text") or hit.get("story_text") or ""
            title = hit.get("title") or hit.get("story_title") or ""
            text = html_to_text(body) or title
            if not text:
                continue
            items.append(
                FeedbackItem(
                    source=self.name,
                    url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
                    title=title,
                    text=text,
                    author=hit.get("author") or "",
                    created_at=(hit.get("created_at") or "")[:10],
                    score=hit.get("points"),
                )
            )
        return items
