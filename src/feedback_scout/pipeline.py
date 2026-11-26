"""End-to-end run: plan -> collect -> label -> report."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from .config import Settings
from .llm import LLM
from .models import FeedbackItem, Label, Plan, SourceReport
from .report import assemble, coverage_markdown, number_relevant, write_evidence_csv
from .sources import REGISTRY
from .sources.imports import Imports
from .sources.web import WebSearch

Log = Callable[[str], None]


@dataclass
class RunOptions:
    sources: list[str]
    since: date | None = None
    per_query: int = 25
    max_items: int = 400
    imports_dir: str = "imports"
    web_searches: int = 5
    rank: bool = False
    out_dir: str = "runs"
    extra: dict = field(default_factory=dict)


def make_source(name: str, settings: Settings, opts: RunOptions, llm: LLM | None):
    cls = REGISTRY[name]
    if cls is Imports:
        return Imports(settings, folder=opts.imports_dir)
    if cls is WebSearch:
        return WebSearch(settings, llm_client=llm.client if llm else None, max_searches=opts.web_searches)
    return cls(settings)


def dedupe(items: list[FeedbackItem]) -> list[FeedbackItem]:
    best: dict[str, FeedbackItem] = {}
    for it in items:
        key = it.url.rstrip("/") or it.id
        if key not in best or len(it.text) > len(best[key].text):
            best[key] = it
    return list(best.values())


def round_robin(items: list[FeedbackItem], cap: int) -> list[FeedbackItem]:
    """Cap the item count while keeping every source represented."""
    if len(items) <= cap:
        return items
    by_source: dict[str, list[FeedbackItem]] = {}
    for it in items:
        by_source.setdefault(it.source, []).append(it)
    out: list[FeedbackItem] = []
    queues = list(by_source.values())
    while len(out) < cap and any(queues):
        for q in queues:
            if q and len(out) < cap:
                out.append(q.pop(0))
    return out


def new_run_dir(base: str, company: str) -> Path:
    slug = "".join(c if c.isalnum() else "-" for c in company.lower()).strip("-") or "run"
    path = Path(base) / f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def collect(plan: Plan, settings: Settings, opts: RunOptions, llm: LLM | None, log: Log) -> tuple[list[FeedbackItem], list[SourceReport]]:
    items: list[FeedbackItem] = []
    reports: list[SourceReport] = []
    for name in opts.sources:
        source = make_source(name, settings, opts, llm)
        log(f"· {source.label}: collecting…")
        found, rep = source.collect(plan, opts.since, opts.per_query)
        log(f"  {rep.status}: {rep.collected} item(s){(' — ' + rep.note) if rep.note else ''}")
        for it in found:
            it.extra.setdefault("collector", source.name)
        items.extend(found)
        reports.append(rep)
    return dedupe(items), reports


def run(
    settings: Settings,
    opts: RunOptions,
    company: str,
    scope: str,
    options: list[str] | None = None,
    audience: str = "",
    context_file: str | None = None,
    plan: Plan | None = None,
    llm: LLM | None = None,
    log: Log = print,
) -> Path:
    llm = llm or LLM(settings)
    run_dir = new_run_dir(opts.out_dir, company)

    if plan is None:
        log("Planning searches…")
        plan = llm.plan(company, scope, options, audience, context_file)
    (run_dir / "plan.json").write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    log(f"  {len(plan.themes)} theme(s), {len(plan.all_queries())} queries")

    log("Collecting feedback…")
    items, reports = collect(plan, settings, opts, llm, log)
    _write_jsonl(run_dir / "items.jsonl", [i.to_dict() for i in items])
    (run_dir / "coverage.json").write_text(json.dumps([asdict(r) for r in reports], indent=2), encoding="utf-8")

    selected = round_robin(items, opts.max_items)
    log(f"Labelling {len(selected)} of {len(items)} item(s)…")
    labels = llm.label(plan, selected, progress=lambda d, t: log(f"  {d}/{t}"))
    _write_jsonl(run_dir / "labels.jsonl", [asdict(l) for l in labels])

    return write_report(run_dir, plan, selected, labels, reports, opts, llm, log)


def write_report(run_dir: Path, plan: Plan, items, labels, reports, opts: RunOptions, llm: LLM, log: Log = print) -> Path:
    numbered = number_relevant(items, labels, plan)
    relevant_by_source: dict[str, int] = {}
    for _, it, _ in numbered:
        key = it.extra.get("collector", it.source)
        relevant_by_source[key] = relevant_by_source.get(key, 0) + 1
    cov = coverage_markdown(reports, relevant_by_source)
    if not numbered:
        body = "_No relevant feedback was found. Check the coverage table: sources may be skipped or the queries too narrow._"
    else:
        log(f"Writing report from {len(numbered)} relevant item(s)…")
        body = llm.write_report(plan, numbered, cov, opts.rank)
    report_path = run_dir / "report.md"
    report_path.write_text(assemble(plan, body, cov, numbered, opts.since), encoding="utf-8")
    write_evidence_csv(run_dir / "evidence.csv", numbered)
    log(f"Done: {report_path}")
    return report_path


def load_run(run_dir: Path) -> tuple[Plan, list[FeedbackItem], list[Label], list[SourceReport]]:
    plan = Plan.from_dict(json.loads((run_dir / "plan.json").read_text(encoding="utf-8")))
    items = [FeedbackItem.from_dict(d) for d in _read_jsonl(run_dir / "items.jsonl")]
    labels = [Label(**d) for d in _read_jsonl(run_dir / "labels.jsonl")]
    reports = [SourceReport(**d) for d in json.loads((run_dir / "coverage.json").read_text(encoding="utf-8"))]
    return plan, items, labels, reports


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
