"""Command-line interface.

    feedback-scout sources                      # what's configured
    feedback-scout plan  --company ... --scope ...   # preview queries, save plan.json
    feedback-scout run   --company ... --scope ...   # full run -> runs/<id>/report.md
    feedback-scout report runs/<id>             # rewrite the report from a saved run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .config import Settings
from .models import Plan
from .pipeline import RunOptions, load_run, run, write_report
from .sources import DEFAULT_SOURCES, REGISTRY


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--company", required=True, help="Company or product, e.g. 'Snowflake'")
    p.add_argument("--scope", required=True, help="What you want feedback about, in plain words")
    p.add_argument("--option", action="append", default=[], help="An option/theme to research (repeatable)")
    p.add_argument("--options-file", help="Text file with one option per line")
    p.add_argument("--audience", default="", help="Whose feedback matters, e.g. 'data engineers'")
    p.add_argument("--context-file", help="PDF or text file with background (e.g. an assignment brief)")
    p.add_argument("--subreddit", action="append", default=[], help="Limit Reddit to these subreddits (repeatable)")
    p.add_argument("--github-org", action="append", default=[], help="GitHub org to search issues in (repeatable)")
    p.add_argument("--github-repo", action="append", default=[], help="owner/repo to search issues in (repeatable)")
    p.add_argument("--discourse", action="append", default=[], help="Discourse forum base URL (repeatable)")
    p.add_argument("--plan-file", help="Use a saved/edited plan.json instead of planning again")
    p.add_argument("--model", help="Claude model ID (default from FEEDBACK_SCOUT_MODEL or claude-sonnet-5-5)")
    p.add_argument("--env-file", help="Path to a .env file (default ./.env)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feedback-scout", description="Prompt-scoped customer feedback research agent.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("sources", help="Show each source and whether it is configured")
    s.add_argument("--imports-dir", default="imports")
    s.add_argument("--env-file")

    p = sub.add_parser("plan", help="Generate and save the search plan without collecting")
    _common(p)
    p.add_argument("--out", default="plan.json")

    r = sub.add_parser("run", help="Plan, collect, label and write the report")
    _common(r)
    r.add_argument(
        "--sources",
        default=",".join(DEFAULT_SOURCES),
        help=f"Comma-separated, from: {', '.join(REGISTRY)}. Default: {','.join(DEFAULT_SOURCES)}",
    )
    r.add_argument("--since", help="Only feedback on or after this date (YYYY-MM-DD). Default: 3 years ago")
    r.add_argument("--per-query", type=int, default=25, help="Max results per query per source")
    r.add_argument("--max-items", type=int, default=400, help="Max items sent to Claude for labelling (cost cap)")
    r.add_argument("--web-searches", type=int, default=5, help="Max web searches per theme")
    r.add_argument("--imports-dir", default="imports")
    r.add_argument("--rank", action="store_true", help="Add a comparison table and ranking of the themes")
    r.add_argument("--out", default="runs", help="Folder for run outputs")

    rp = sub.add_parser("report", help="Rewrite the report for an existing run folder")
    rp.add_argument("run_dir")
    rp.add_argument("--rank", action="store_true")
    rp.add_argument("--model")
    rp.add_argument("--env-file")
    return parser


def _settings(args) -> Settings:
    settings = Settings.from_env(getattr(args, "env_file", None))
    if getattr(args, "model", None):
        settings.model = args.model
    return settings


def _options(args) -> list[str]:
    opts = list(args.option)
    if args.options_file:
        opts += [l.strip().lstrip("-• ").strip() for l in Path(args.options_file).read_text(encoding="utf-8").splitlines() if l.strip()]
    return opts


def _apply_overrides(plan: Plan, args) -> Plan:
    if args.subreddit:
        plan.subreddits = [s.removeprefix("r/") for s in args.subreddit]
    if args.github_org or args.github_repo:
        plan.github_orgs, plan.github_repos = list(args.github_org), list(args.github_repo)
    if args.discourse:
        plan.discourse_forums = list(args.discourse)
    return plan


def _make_plan(args, settings: Settings) -> Plan:
    if args.plan_file:
        plan = Plan.from_dict(json.loads(Path(args.plan_file).read_text(encoding="utf-8")))
    else:
        from .llm import LLM

        print("Planning searches…", file=sys.stderr)
        plan = LLM(settings).plan(args.company, args.scope, _options(args), args.audience, args.context_file)
    return _apply_overrides(plan, args)


def cmd_sources(args) -> int:
    from .pipeline import make_source

    settings = Settings.from_env(args.env_file)
    opts = RunOptions(sources=list(REGISTRY), imports_dir=args.imports_dir)
    print(f"Anthropic API key: {'set' if settings.anthropic_api_key else 'MISSING (required)'}")
    print(f"Model: {settings.model}\n")
    for name in REGISTRY:
        src = make_source(name, settings, opts, None)
        ready, why = src.status(None)
        default = "default" if REGISTRY[name].default_enabled else "opt-in"
        print(f"{'✓' if ready else '✗'} {name:<14} {default:<8} {why}")
    return 0


def cmd_plan(args) -> int:
    settings = _settings(args)
    plan = _make_plan(args, settings)
    Path(args.out).write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    for t in plan.themes:
        print(f"\n{t.name}\n  " + "\n  ".join(t.queries))
    print(f"\nSubreddits: {', '.join(plan.subreddits) or '-'}")
    print(f"GitHub: {', '.join(plan.github_orgs + plan.github_repos) or '-'}")
    print(f"\nSaved to {args.out}. Edit it, then: feedback-scout run ... --plan-file {args.out}")
    return 0


def cmd_run(args) -> int:
    settings = _settings(args)
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.", file=sys.stderr)
        return 2
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in REGISTRY]
    if unknown:
        print(f"Unknown source(s): {', '.join(unknown)}. Choose from {', '.join(REGISTRY)}", file=sys.stderr)
        return 2
    if "stackoverflow" in sources:
        print("Note: Stack Exchange's terms require consent for automated collection used in generative AI. "
              "Make sure your use is permitted.", file=sys.stderr)
    today = date.today()
    since = date.fromisoformat(args.since) if args.since else today.replace(year=today.year - 3)
    opts = RunOptions(
        sources=sources,
        since=since,
        per_query=args.per_query,
        max_items=args.max_items,
        imports_dir=args.imports_dir,
        web_searches=args.web_searches,
        rank=args.rank,
        out_dir=args.out,
    )
    plan = _make_plan(args, settings)
    report = run(settings, opts, args.company, args.scope, plan=plan, log=lambda m: print(m, file=sys.stderr))
    print(report)
    return 0


def cmd_report(args) -> int:
    from .llm import LLM

    settings = _settings(args)
    run_dir = Path(args.run_dir)
    plan, items, labels, reports = load_run(run_dir)
    opts = RunOptions(sources=[r.name for r in reports], rank=args.rank)
    print(write_report(run_dir, plan, items, labels, reports, opts, LLM(settings), log=lambda m: print(m, file=sys.stderr)))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"sources": cmd_sources, "plan": cmd_plan, "run": cmd_run, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
