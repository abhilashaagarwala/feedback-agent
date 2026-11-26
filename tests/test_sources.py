from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import httpx

from conftest import fake_client, mock_http, text_response
from feedback_scout.sources.discourse import Discourse
from feedback_scout.sources.github import GitHubIssues
from feedback_scout.sources.hackernews import HackerNews
from feedback_scout.sources.imports import Imports
from feedback_scout.sources.reddit import Reddit
from feedback_scout.sources.stackexchange import StackExchange
from feedback_scout.sources.web import WebSearch, parse_web_items


def test_hackernews_parses_hits_and_filters_by_date(settings, plan):
    def handler(request: httpx.Request):
        assert request.url.host == "hn.algolia.com"
        assert "created_at_i>" in request.url.params["numericFilters"]
        return httpx.Response(200, json={"hits": [
            {"objectID": "1", "comment_text": "<p>Snowflake bill <i>doubled</i></p>", "author": "a", "created_at": "2025-01-02T00:00:00Z"},
            {"objectID": "2", "title": "Ask HN: Snowflake costs?", "story_text": None, "created_at": "2024-06-01T00:00:00Z", "points": 10},
        ]})

    src = HackerNews(settings, http=mock_http(handler))
    src.request_delay = 0
    items, rep = src.collect(plan, date(2024, 1, 1), 10)
    assert rep.status == "ok"
    urls = {i.url for i in items}
    assert "https://news.ycombinator.com/item?id=1" in urls
    first = next(i for i in items if i.url.endswith("=1"))
    assert first.text == "Snowflake bill doubled"
    assert first.theme_hint in {"Query cost", "Data quality"}


def test_reddit_skips_without_credentials(plan):
    from feedback_scout.config import Settings

    src = Reddit(Settings())
    items, rep = src.collect(plan, None, 10)
    assert items == [] and rep.status == "skipped"
    assert "REDDIT_CLIENT_ID" in rep.note


def test_reddit_posts_and_comments(settings, plan):
    def handler(request: httpx.Request):
        if request.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer tok"
        if request.url.path.endswith("/search"):
            assert request.url.path == "/r/snowflake/search"
            return httpx.Response(200, json={"data": {"children": [{"kind": "t3", "data": {
                "id": "abc", "title": "Warehouse costs", "selftext": "Our credits exploded",
                "permalink": "/r/snowflake/comments/abc/x/", "created_utc": 1735689600, "score": 5,
                "num_comments": 2, "subreddit": "snowflake", "author": "u1"}}]}})
        if request.url.path == "/comments/abc":
            return httpx.Response(200, json=[{}, {"data": {"children": [
                {"kind": "t1", "data": {"body": "Same here, no query-level attribution", "permalink": "/r/snowflake/comments/abc/x/c1/", "created_utc": 1735689700, "score": 3, "author": "u2"}},
                {"kind": "t1", "data": {"body": "[deleted]", "permalink": "/c2", "created_utc": 1735689700}},
            ]}}])
        raise AssertionError(request.url)

    src = Reddit(settings, http=mock_http(handler))
    src.request_delay = 0
    items = src.search("snowflake cost", None, 10, plan)
    assert [i.text for i in items] == ["Warehouse costs\n\nOur credits exploded", "Same here, no query-level attribution"]
    assert items[1].url == "https://www.reddit.com/r/snowflake/comments/abc/x/c1/"
    assert items[0].created_at == "2025-01-01"


def test_stackexchange_is_opt_in(settings, plan):
    assert StackExchange.default_enabled is False

    def handler(request):
        assert request.url.params["site"] == "stackoverflow"
        return httpx.Response(200, json={"items": [{"link": "https://stackoverflow.com/q/1", "title": "Slow &amp; costly", "body": "<p>Why?</p>", "creation_date": 1735689600, "score": 2, "owner": {"display_name": "x"}}]})

    items = StackExchange(settings, http=mock_http(handler)).search("q", None, 5, plan)
    assert items[0].title == "Slow & costly" and items[0].text.endswith("Why?")


def test_github_scopes_query_and_strips_company(settings, plan):
    seen = {}

    def handler(request):
        seen["q"] = request.url.params["q"]
        return httpx.Response(200, json={"items": [{"html_url": "https://github.com/snowflakedb/x/issues/1", "title": "Bug", "body": "details", "created_at": "2025-03-01T00:00:00Z", "user": {"login": "z"}}]})

    items = GitHubIssues(settings, http=mock_http(handler)).search("snowflake query cost", date(2024, 1, 1), 5, plan)
    assert seen["q"] == "query cost is:issue org:snowflakedb created:>=2024-01-01"
    assert items[0].url.endswith("/issues/1")


def test_github_skips_without_repos(settings, plan):
    plan.github_orgs = []
    ready, why = GitHubIssues(settings).status(plan)
    assert not ready and "--github-org" in why


def test_discourse(settings, plan):
    plan.discourse_forums = ["https://forum.example.com/"]

    def handler(request):
        assert request.url.path == "/search.json"
        return httpx.Response(200, json={"posts": [{"topic_id": 7, "post_number": 3, "blurb": "costs went up", "username": "q", "created_at": "2025-05-05T00:00:00Z"}], "topics": [{"id": 7, "slug": "costs", "title": "Costs"}]})

    items = Discourse(settings, http=mock_http(handler)).search("cost", None, 5, plan)
    assert items[0].url == "https://forum.example.com/t/costs/7/3"


def test_imports_csv_md_json(tmp_path, settings, plan):
    (tmp_path / "g2_snowflake.csv").write_text("title,likes,dislikes,date,url\nGreat,Fast,Expensive,2025-02-01,https://g2.example/r/1\n", encoding="utf-8")
    (tmp_path / "gartner-notes.md").write_text("url: https://gartner.example/r/9\ndate: 2025-06-01\nCost visibility is poor.\n---\nSecond review text\n", encoding="utf-8")
    (tmp_path / "peerspot.jsonl").write_text('{"review": "Docs are hard to follow", "date": "2020-01-01"}\n', encoding="utf-8")

    items, rep = Imports(settings, folder=tmp_path).collect(plan, date(2024, 1, 1), 10)
    assert rep.status == "ok"
    by_source = {}
    for i in items:
        by_source.setdefault(i.source, []).append(i)
    assert set(by_source) == {"g2", "gartner"}  # peerspot row is older than --since
    assert "Dislikes: Expensive" in by_source["g2"][0].text
    assert by_source["gartner"][0].url == "https://gartner.example/r/9"
    assert len(by_source["gartner"]) == 2


def test_imports_skipped_when_empty(tmp_path, settings, plan):
    items, rep = Imports(settings, folder=tmp_path / "missing").collect(plan, None, 10)
    assert rep.status == "skipped" and items == []


def test_web_keeps_only_urls_from_search_results():
    text = '[{"url": "https://a.example/post", "title": "A", "date": "2025-01-01", "who": "DE", "feedback": "bill too high"},' \
           ' {"url": "https://invented.example", "title": "B", "feedback": "made up"}]'
    items = parse_web_items("Here you go:\n" + text, {"https://a.example/post/"}, "web")
    assert [i.url for i in items] == ["https://a.example/post"]


def test_web_collect_uses_search_tool(settings, plan):
    result_block = SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(url="https://blog.example/x")])
    answer = '[{"url": "https://blog.example/x", "title": "X", "date": "2025-04-01", "who": "", "feedback": "Costs are opaque"}]'
    client = fake_client(text_response(answer, [result_block]), text_response("[]"))
    items, rep = WebSearch(settings, llm_client=client, max_searches=2).collect(plan, None, 10)
    assert rep.status == "ok" and len(items) == 1 and items[0].theme_hint == "Query cost"
    tool = client.messages.calls[0]["tools"][0]
    assert tool["type"] == "web_search_20250305" and tool["max_uses"] == 2
