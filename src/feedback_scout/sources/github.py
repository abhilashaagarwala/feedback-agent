"""GitHub issues on the company's public repos, via the official REST API.

Works without a token (low rate limit); set GITHUB_TOKEN for more headroom.
Docs: https://docs.github.com/en/rest/search/search#search-issues-and-pull-requests
"""

from __future__ import annotations

from datetime import date

from ..models import FeedbackItem, Plan
from ..text import truncate
from .base import Source

API = "https://api.github.com/search/issues"


class GitHubIssues(Source):
    name = "github"
    label = "GitHub issues"
    request_delay = 2.0  # unauthenticated search allows ~10 requests/minute

    def status(self, plan: Plan | None = None) -> tuple[bool, str]:
        if plan is not None and not (plan.github_repos or plan.github_orgs):
            return False, "no GitHub repos or orgs in the plan (use --github-org / --github-repo)"
        if self.settings.github_token:
            self.request_delay = 0.3
            return True, "ready"
        return True, "no GITHUB_TOKEN, so searches are slow (10/minute)"

    def _scope(self, plan: Plan) -> str:
        parts = [f"repo:{r}" for r in plan.github_repos] + [f"org:{o}" for o in plan.github_orgs]
        return " ".join(parts)

    def search(self, query: str, since: date | None, limit: int, plan: Plan) -> list[FeedbackItem]:
        # Drop the company name from the query: the repo/org scope already implies it.
        terms = " ".join(w for w in query.split() if w.lower() != plan.company.lower()) or query
        q = f"{terms} is:issue {self._scope(plan)}"
        if since:
            q += f" created:>={since.isoformat()}"
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        resp = self.http.get(API, params={"q": q, "per_page": min(max(limit, 1), 100)}, headers=headers)
        resp.raise_for_status()
        items = []
        for issue in resp.json().get("items", []):
            title = issue.get("title", "")
            items.append(
                FeedbackItem(
                    source=self.name,
                    url=issue.get("html_url", ""),
                    title=title,
                    text=f"{title}\n\n{truncate(issue.get('body') or '', 4000)}".strip(),
                    author=(issue.get("user") or {}).get("login", ""),
                    created_at=(issue.get("created_at") or "")[:10],
                    score=(issue.get("reactions") or {}).get("total_count"),
                    extra={"comments": issue.get("comments", 0), "state": issue.get("state", "")},
                )
            )
        return items
