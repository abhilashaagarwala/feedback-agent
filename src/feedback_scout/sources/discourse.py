"""Community forums that run on Discourse, via their public JSON search.

Many vendor communities run Discourse (e.g. https://community.openai.com).
Pass forum base URLs with --discourse. Only public posts are read.
Docs: https://docs.discourse.org/
"""

from __future__ import annotations

from datetime import date

from ..models import FeedbackItem, Plan
from ..text import html_to_text
from .base import Source


class Discourse(Source):
    name = "discourse"
    label = "Discourse forums"
    request_delay = 1.0

    def status(self, plan: Plan | None = None) -> tuple[bool, str]:
        if plan is not None and not plan.discourse_forums:
            return False, "no Discourse forum URLs given (use --discourse https://forum.example.com)"
        return True, "ready"

    def search(self, query: str, since: date | None, limit: int, plan: Plan) -> list[FeedbackItem]:
        items: list[FeedbackItem] = []
        for base in plan.discourse_forums:
            base = base.rstrip("/")
            q = query + (f" after:{since.isoformat()}" if since else "")
            resp = self.http.get(f"{base}/search.json", params={"q": q})
            resp.raise_for_status()
            data = resp.json()
            topics = {t["id"]: t for t in data.get("topics", [])}
            for post in data.get("posts", [])[:limit]:
                topic = topics.get(post.get("topic_id"), {})
                slug = topic.get("slug", "topic")
                items.append(
                    FeedbackItem(
                        source=self.name,
                        url=f"{base}/t/{slug}/{post.get('topic_id')}/{post.get('post_number', 1)}",
                        title=topic.get("title", ""),
                        text=html_to_text(post.get("blurb", "")),
                        author=post.get("username", ""),
                        created_at=(post.get("created_at") or "")[:10],
                        score=post.get("like_count"),
                        extra={"forum": base},
                    )
                )
        return items
