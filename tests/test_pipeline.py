from __future__ import annotations

from datetime import date

from conftest import fake_client, text_response, tool_response
from feedback_scout.cli import build_parser
from feedback_scout.llm import LLM
from feedback_scout.models import FeedbackItem, Label
from feedback_scout.pipeline import RunOptions, dedupe, load_run, round_robin, run
from feedback_scout.report import number_relevant


def _item(source, url, text="t", created="2025-01-01"):
    return FeedbackItem(source=source, url=url, text=text, created_at=created)


def test_dedupe_keeps_longest_text():
    a = _item("hn", "https://x/1", "short")
    b = _item("hn", "https://x/1/", "much longer text")
    assert [i.text for i in dedupe([a, b])] == ["much longer text"]


def test_round_robin_keeps_every_source():
    items = [_item("hn", f"h{i}") for i in range(10)] + [_item("reddit", "r1")]
    capped = round_robin(items, 3)
    assert {i.source for i in capped} == {"hn", "reddit"}


def test_number_relevant_orders_by_theme_then_severity(plan):
    i1, i2, i3 = _item("hn", "u1"), _item("hn", "u2"), _item("hn", "u3")
    labels = [
        Label(id=i1.id, relevant=True, theme="Data quality", severity=1),
        Label(id=i2.id, relevant=True, theme="Query cost", severity=3),
        Label(id=i3.id, relevant=False),
    ]
    numbered = number_relevant([i1, i2, i3], labels, plan)
    assert [(n, it.url) for n, it, _ in numbered] == [(1, "u2"), (2, "u1")]


def test_plan_keeps_user_options(settings):
    client = fake_client(tool_response("record_plan", {
        "themes": [{"name": "Something else", "description": "", "queries": ["q"]}],
        "subreddits": ["r/snowflake"], "github_orgs": ["snowflakedb"], "github_repos": [], "audience": "", "notes": "",
    }))
    plan = LLM(settings, client=client).plan("Snowflake", "scope", ["Query cost", "Data quality"])
    assert [t.name for t in plan.themes] == ["Query cost", "Data quality"]
    assert plan.subreddits == ["snowflake"]


def test_full_run_offline(tmp_path, settings, plan):
    imports = tmp_path / "imports"
    imports.mkdir()
    (imports / "g2_snowflake.md").write_text("url: https://g2.example/1\ndate: 2025-02-01\nThe bill is unpredictable and we can't see per-query cost.\n", encoding="utf-8")

    client = fake_client(
        # labels for the one item (id computed below), then the report
        tool_response("record_labels", {"labels": []}),
        text_response("## Summary\n\n- Cost visibility is the main complaint [1]."),
    )
    llm = LLM(settings, client=client)
    item_id = FeedbackItem(source="g2", url="https://g2.example/1", text="The bill is unpredictable and we can't see per-query cost.", created_at="2025-02-01").id
    client.messages.responses[0].content[0].input["labels"] = [
        {"id": item_id, "relevant": True, "theme": "Query cost", "about_company": "yes", "pain": "No per-query cost visibility", "severity": 2, "sentiment": "negative"}
    ]

    opts = RunOptions(sources=["imports"], since=date(2024, 1, 1), imports_dir=str(imports), out_dir=str(tmp_path / "runs"))
    report_path = run(settings, opts, "Snowflake", "cost", plan=plan, llm=llm, log=lambda m: None)

    text = report_path.read_text(encoding="utf-8")
    assert "# Customer feedback: Snowflake" in text
    assert "| Your imports (review sites) | ok | 1 | 1 |" in text
    assert "1. [The bill is unpredictable" in text and "https://g2.example/1" in text
    assert (report_path.parent / "evidence.csv").exists()

    plan2, items, labels, reports = load_run(report_path.parent)
    assert plan2.company == "Snowflake" and len(items) == 1 and labels[0].relevant


def test_cli_parses_run_args():
    args = build_parser().parse_args([
        "run", "--company", "Snowflake", "--scope", "x", "--option", "A", "--option", "B",
        "--sources", "hackernews,reddit", "--subreddit", "snowflake", "--rank",
    ])
    assert args.option == ["A", "B"] and args.rank and args.sources == "hackernews,reddit"
