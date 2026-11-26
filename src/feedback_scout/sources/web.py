"""General web (blogs, write-ups, public review pages) via the Claude API's
built-in web search tool.

Billed by Anthropic per search (see https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool).
Only URLs that actually came back from a search are kept, so the model can't
invent sources.
"""

from __future__ import annotations

import json
import re
from datetime import date

from ..models import FeedbackItem, Plan, SourceReport
from .base import Source, within

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}

PROMPT = """Find first-hand customer or user feedback about {company} on this topic:

Topic: {theme}
What it covers: {description}
Example search phrasings: {queries}
{since_line}
Look for practitioners describing their own experience: complaints, workarounds,
wishes, praise. Prefer forums, review pages, engineering blogs and conference
talks over vendor marketing. Skip pages that are only {company}'s own marketing.

Run several searches. Then reply with ONLY a JSON array (no prose), at most
{limit} entries, each:
{{"url": "...", "title": "...", "date": "YYYY-MM-DD or empty",
  "who": "role / company size if stated, else empty",
  "feedback": "a faithful paraphrase of what the person said, 1-3 sentences, no long quotes"}}
Use only URLs that appeared in your search results."""


class WebSearch(Source):
    name = "web"
    label = "Web (Claude web search)"
    request_delay = 0

    def __init__(self, *args, llm_client=None, model: str | None = None, max_searches: int = 5, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = llm_client
        self.model = model or self.settings.model
        self.max_searches = max_searches

    def status(self, plan: Plan | None = None) -> tuple[bool, str]:
        if self.client is None and not self.settings.anthropic_api_key:
            return False, "needs ANTHROPIC_API_KEY"
        return True, f"up to {self.max_searches} searches per theme (billed by Anthropic)"

    def _client(self):
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self.client

    def search(self, query: str, since: date | None, limit: int, plan: Plan) -> list[FeedbackItem]:
        return []  # searches per theme, not per query; see collect()

    def collect(self, plan: Plan, since: date | None, limit: int) -> tuple[list[FeedbackItem], SourceReport]:
        report = SourceReport(name=self.name)
        ready, why = self.status(plan)
        if not ready:
            report.status, report.note = "skipped", why
            return [], report
        items: list[FeedbackItem] = []
        for theme in plan.themes:
            try:
                found = self.search_theme(plan, theme, since, limit)
                for item in found:
                    item.theme_hint = theme.name
                items.extend(found)
            except Exception as exc:
                report.errors.append(f"{theme.name}: {exc}")
            report.queries_run += 1
        items = [i for i in items if within(i, since)]
        report.collected = len(items)
        report.status = "error" if report.errors and not items else "ok"
        report.note = report.errors[0] if report.status == "error" else why
        return items, report

    def search_theme(self, plan: Plan, theme, since: date | None, limit: int) -> list[FeedbackItem]:
        prompt = PROMPT.format(
            company=plan.company,
            theme=theme.name,
            description=theme.description or theme.name,
            queries="; ".join(theme.queries[:6]),
            since_line=f"Only feedback from {since.isoformat()} or later.\n" if since else "",
            limit=min(limit, 25),
        )
        messages = [{"role": "user", "content": prompt}]
        tool = {**WEB_SEARCH_TOOL, "max_uses": self.max_searches}
        seen_urls: set[str] = set()
        final_text = ""
        for _ in range(4):  # server tools can pause long turns; continue them
            resp = self._client().messages.create(
                model=self.model, max_tokens=8000, messages=messages, tools=[tool]
            )
            for block in resp.content:
                btype = getattr(block, "type", "")
                if btype == "web_search_tool_result":
                    content = getattr(block, "content", None)
                    if isinstance(content, list):
                        for r in content:
                            url = getattr(r, "url", None)
                            if url:
                                seen_urls.add(url)
                elif btype == "text":
                    final_text += getattr(block, "text", "")
            if getattr(resp, "stop_reason", "") == "pause_turn":
                messages = messages + [{"role": "assistant", "content": resp.content}]
                final_text = ""
                continue
            break
        return parse_web_items(final_text, seen_urls, self.name)


def parse_web_items(text: str, allowed_urls: set[str], source: str) -> list[FeedbackItem]:
    match = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if not match:
        return []
    try:
        rows = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    allowed = {u.rstrip("/") for u in allowed_urls}
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url", "")).strip()
        if not url or url.rstrip("/") not in allowed:
            continue  # never keep a URL the search didn't return
        feedback = str(row.get("feedback", "")).strip()
        if not feedback:
            continue
        items.append(
            FeedbackItem(
                source=source,
                url=url,
                title=str(row.get("title", "")),
                text=feedback,
                author=str(row.get("who", "")),
                created_at=str(row.get("date", ""))[:10],
                extra={"paraphrased_by": "claude-web-search"},
            )
        )
    return items
