"""Assemble the Markdown report and the evidence CSV."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .models import FeedbackItem, Label, Plan, SourceReport
from .sources import REGISTRY


def coverage_markdown(reports: list[SourceReport], relevant_by_source: dict[str, int] | None = None) -> str:
    relevant_by_source = relevant_by_source or {}
    rows = ["| Source | Status | Collected | Relevant | Note |", "| --- | --- | --- | --- | --- |"]
    for r in reports:
        label = REGISTRY[r.name].label if r.name in REGISTRY else r.name
        note = (r.note or "").replace("|", "/")
        if r.errors and r.status == "ok":
            note = (note + f"; {len(r.errors)} query error(s)").strip("; ")
        rows.append(f"| {label} | {r.status} | {r.collected} | {relevant_by_source.get(r.name, 0)} | {note} |")
    return "\n".join(rows)


def number_relevant(
    items: list[FeedbackItem], labels: list[Label], plan: Plan, per_theme: int = 60
) -> list[tuple[int, FeedbackItem, Label]]:
    """Pick the relevant items, strongest first within each theme, and number them."""
    by_id = {l.id: l for l in labels}
    order = [t.name for t in plan.themes] + ["other"]
    buckets: dict[str, list[tuple[FeedbackItem, Label]]] = {name: [] for name in order}
    for it in items:
        lab = by_id.get(it.id)
        if not lab or not lab.relevant:
            continue
        theme = lab.theme if lab.theme in buckets else "other"
        buckets[theme].append((it, lab))
    out: list[tuple[int, FeedbackItem, Label]] = []
    n = 1
    for theme in order:
        ranked = sorted(
            buckets[theme],
            key=lambda pair: (pair[1].severity, pair[1].about_company == "yes", pair[0].created_at),
            reverse=True,
        )
        for it, lab in ranked[:per_theme]:
            out.append((n, it, lab))
            n += 1
    return out


def sources_markdown(numbered: list[tuple[int, FeedbackItem, Label]]) -> str:
    lines = ["## Sources", ""]
    for n, it, _ in numbered:
        title = (it.title or it.text[:80]).replace("\n", " ").replace("[", "(").replace("]", ")")
        when = f", {it.created_at}" if it.created_at else ""
        link = f"[{title}]({it.url})" if it.url.startswith("http") else f"{title} ({it.url})"
        lines.append(f"{n}. {link} ({it.source}{when})")
    return "\n".join(lines)


def assemble(plan: Plan, body: str, coverage_md: str, numbered, since: date | None) -> str:
    header = [
        f"# Customer feedback: {plan.company}",
        "",
        f"**Scope:** {plan.scope}  ",
        f"**Themes:** {', '.join(t.name for t in plan.themes)}  ",
        f"**Run date:** {date.today().isoformat()}"
        + (f" · feedback since {since.isoformat()}" if since else ""),
        "",
        "## Coverage",
        "",
        coverage_md,
        "",
    ]
    return "\n".join(header) + "\n" + body.strip() + "\n\n" + sources_markdown(numbered) + "\n"


def write_evidence_csv(path: Path, numbered) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["n", "theme", "source", "date", "about_company", "severity", "sentiment", "pain", "url", "title"])
        for n, it, lab in numbered:
            w.writerow([n, lab.theme, it.source, it.created_at, lab.about_company, lab.severity, lab.sentiment, lab.pain, it.url, it.title])
