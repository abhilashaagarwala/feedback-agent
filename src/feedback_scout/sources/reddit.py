"""Reddit via the official Data API (OAuth, application-only).

You need your own Reddit app (https://www.reddit.com/prefs/apps) and must
follow Reddit's Developer Terms and Data API Terms. The free tier is for
personal, non-commercial use; Reddit's terms forbid using the data to train
AI models. This source only reads posts and comments to summarise them for you.
Docs: https://www.reddit.com/dev/api
"""

from __future__ import annotations

import time
from datetime import date

from ..models import FeedbackItem, Plan
from .base import Source, from_unix, to_unix

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"


class Reddit(Source):
    name = "reddit"
    label = "Reddit"
    request_delay = 0.7  # free tier allows ~100 queries/minute
    comment_posts = 3  # fetch top comments for this many top posts per query

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._token: str | None = None
        self._token_expires = 0.0

    def status(self, plan: Plan | None = None) -> tuple[bool, str]:
        if not (self.settings.reddit_client_id and self.settings.reddit_client_secret):
            return False, "set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET (see README)"
        subs = ", ".join(f"r/{s}" for s in (plan.subreddits if plan else [])) or "all of Reddit"
        return True, f"searching {subs}"

    def _auth_headers(self) -> dict:
        if not self._token or time.time() > self._token_expires - 60:
            resp = self.http.post(
                TOKEN_URL,
                auth=(self.settings.reddit_client_id or "", self.settings.reddit_client_secret or ""),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.settings.reddit_user_agent},
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            self._token_expires = time.time() + float(data.get("expires_in", 3600))
        return {"Authorization": f"Bearer {self._token}", "User-Agent": self.settings.reddit_user_agent}

    def _get(self, path: str, params: dict) -> dict | list:
        resp = self.http.get(f"{API}{path}", params=params, headers=self._auth_headers())
        resp.raise_for_status()
        return resp.json()

    def search(self, query: str, since: date | None, limit: int, plan: Plan) -> list[FeedbackItem]:
        targets = plan.subreddits or [None]
        per_target = max(1, limit // len(targets))
        items: list[FeedbackItem] = []
        for sub in targets:
            path = f"/r/{sub}/search" if sub else "/search"
            params = {"q": query, "sort": "relevance", "t": "all", "limit": min(per_target, 100), "type": "link"}
            if sub:
                params["restrict_sr"] = 1
            listing = self._get(path, params)
            posts = [c["data"] for c in listing.get("data", {}).get("children", [])]
            if since:
                posts = [p for p in posts if p.get("created_utc", 0) >= to_unix(since)]
            for post in posts:
                items.append(self._post_item(post))
            for post in sorted(posts, key=lambda p: p.get("num_comments", 0), reverse=True)[: self.comment_posts]:
                items.extend(self._top_comments(post, since))
                time.sleep(self.request_delay)
        return items

    def _post_item(self, post: dict) -> FeedbackItem:
        title = post.get("title", "")
        body = post.get("selftext", "")
        return FeedbackItem(
            source=self.name,
            url=f"https://www.reddit.com{post.get('permalink', '')}",
            title=title,
            text=f"{title}\n\n{body}".strip(),
            author=post.get("author", ""),
            created_at=from_unix(post.get("created_utc")),
            score=post.get("score"),
            extra={"subreddit": post.get("subreddit", "")},
        )

    def _top_comments(self, post: dict, since: date | None, n: int = 15) -> list[FeedbackItem]:
        data = self._get(f"/comments/{post['id']}", {"limit": n, "depth": 1, "sort": "top"})
        if not isinstance(data, list) or len(data) < 2:
            return []
        out = []
        for child in data[1].get("data", {}).get("children", []):
            if child.get("kind") != "t1":
                continue
            c = child["data"]
            if since and c.get("created_utc", 0) < to_unix(since):
                continue
            body = c.get("body", "")
            if not body or body in ("[deleted]", "[removed]"):
                continue
            out.append(
                FeedbackItem(
                    source=self.name,
                    url=f"https://www.reddit.com{c.get('permalink', '')}",
                    title=f"Comment on: {post.get('title', '')}",
                    text=body,
                    author=c.get("author", ""),
                    created_at=from_unix(c.get("created_utc")),
                    score=c.get("score"),
                    extra={"subreddit": post.get("subreddit", "")},
                )
            )
        return out
