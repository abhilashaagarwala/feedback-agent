"""The three Claude steps: plan the search, label each item, write the report."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from .config import Settings
from .models import FeedbackItem, Label, Plan, Theme
from .text import truncate

PLAN_TOOL = {
    "name": "record_plan",
    "description": "Record the search plan for this feedback research run.",
    "input_schema": {
        "type": "object",
        "properties": {
            "themes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "queries": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "description", "queries"],
                },
            },
            "subreddits": {"type": "array", "items": {"type": "string"}},
            "github_orgs": {"type": "array", "items": {"type": "string"}},
            "github_repos": {"type": "array", "items": {"type": "string"}},
            "audience": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["themes", "subreddits", "github_orgs", "github_repos", "audience", "notes"],
    },
}

LABEL_TOOL = {
    "name": "record_labels",
    "description": "Record one label per feedback item.",
    "input_schema": {
        "type": "object",
        "properties": {
            "labels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "relevant": {"type": "boolean"},
                        "theme": {"type": "string"},
                        "about_company": {"type": "string", "enum": ["yes", "no", "unclear"]},
                        "pain": {"type": "string"},
                        "severity": {"type": "integer", "minimum": 0, "maximum": 3},
                        "sentiment": {"type": "string", "enum": ["negative", "mixed", "neutral", "positive"]},
                    },
                    "required": ["id", "relevant", "theme", "about_company", "pain", "severity", "sentiment"],
                },
            }
        },
        "required": ["labels"],
    },
}

PLAN_SYSTEM = """You plan customer-feedback research. Turn the user's scope into
themes and short search queries written the way customers talk, not the way
marketing does ("snowflake bill too high", not "cost optimization solution").

Rules:
- If the user listed options or themes, use exactly those as the themes, in order.
  Otherwise derive 3-6 themes from the scope.
- 4-6 queries per theme, 2-6 words each. Most should include the company or
  product name so general sources (Hacker News, Reddit, Stack Overflow) find it.
- Suggest subreddits where this company's customers talk (without "r/"), the
  company's GitHub org(s) and the most relevant public repos ("owner/repo").
  Leave a list empty rather than guess wildly.
- audience: who the feedback should come from. notes: anything the analyst
  should keep in mind (e.g. constraints in the attached context)."""

LABEL_SYSTEM = """You label public feedback items for a customer research report.
For every item return one label:
- relevant: does it say something about the experience of using {company}
  (or a direct alternative) that bears on one of the themes? Job posts, ads,
  spam and off-topic mentions are not relevant.
- theme: the best matching theme name from the list, exactly as written, or "other".
- about_company: "yes" if the person is talking about {company} itself,
  "no" if about the category or a competitor, "unclear" otherwise.
- pain: one sentence paraphrasing the specific problem, wish or praise. Do not
  quote more than a few words. Empty if not relevant.
- severity: 0 none or praise, 1 annoyance, 2 costs real time or money,
  3 blocker, data/trust problem, or a reason to leave.
- sentiment: negative | mixed | neutral | positive.
Label every id you are given, and only those ids."""

REPORT_SYSTEM = """You write evidence reports from public customer feedback.
You are given labelled items, each with a number like [12]. Rules:
- Every claim about what customers say must cite item numbers, e.g. [3][17].
  Never cite a number you weren't given. Never invent feedback.
- Paraphrase. Quote at most a few words from any one item.
- Say when evidence is thin, old, from one source, or about the category
  rather than {company} itself. Volume of posts is not prevalence; don't
  turn counts into market percentages.
- Write in plain, specific language. No filler, no marketing tone.
- Output GitHub-flavoured Markdown only. Do not add a Sources list; it is
  appended automatically."""


class LLM:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self.model = settings.model
        if client is None:
            import anthropic

            if not settings.anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set (see .env.example)")
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.client = client

    # --- helpers --------------------------------------------------------------

    def _forced_tool(self, system: str, content, tool: dict, max_tokens: int = 8000) -> dict:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
        )
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use":
                return dict(block.input)
        raise RuntimeError(f"model did not call {tool['name']}")

    @staticmethod
    def context_blocks(path: str | Path | None) -> list[dict]:
        """Attach a PDF or text file the user gave as extra context."""
        if not path:
            return []
        p = Path(path)
        if p.suffix.lower() == ".pdf":
            data = base64.standard_b64encode(p.read_bytes()).decode()
            return [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}]
        return [{"type": "text", "text": f"Attached context ({p.name}):\n\n{p.read_text(encoding='utf-8')}"}]

    # --- step 1: plan ---------------------------------------------------------

    def plan(
        self,
        company: str,
        scope: str,
        options: list[str] | None = None,
        audience: str = "",
        context_file: str | None = None,
    ) -> Plan:
        ask = [f"Company / product: {company}", f"Scope: {scope}"]
        if options:
            ask.append("Options to research (use these as the themes):\n" + "\n".join(f"- {o}" for o in options))
        if audience:
            ask.append(f"Audience: {audience}")
        content = self.context_blocks(context_file) + [{"type": "text", "text": "\n\n".join(ask)}]
        data = self._forced_tool(PLAN_SYSTEM, content, PLAN_TOOL)
        themes = [Theme(name=t["name"], description=t.get("description", ""), queries=t.get("queries", [])) for t in data.get("themes", [])]
        if options:
            # The user's option list is authoritative: keep their names and order,
            # reusing the model's queries by name match, then by position.
            by_name = {t.name.lower(): t for t in themes}
            fixed = []
            for idx, opt in enumerate(options):
                match = by_name.get(opt.lower()) or (themes[idx] if idx < len(themes) and len(themes) == len(options) else None)
                if match:
                    fixed.append(Theme(name=opt, description=match.description, queries=match.queries))
                else:
                    fixed.append(Theme(name=opt, description=opt, queries=[f"{company} {opt}"]))
            themes = fixed
        return Plan(
            company=company,
            scope=scope,
            themes=themes,
            subreddits=[s.removeprefix("r/") for s in data.get("subreddits", [])],
            github_orgs=data.get("github_orgs", []),
            github_repos=data.get("github_repos", []),
            audience=audience or data.get("audience", ""),
            notes=data.get("notes", ""),
        )

    # --- step 2: label --------------------------------------------------------

    def label(self, plan: Plan, items: list[FeedbackItem], batch_size: int = 20, progress=None) -> list[Label]:
        theme_list = "\n".join(f"- {t.name}: {t.description}" for t in plan.themes)
        system = LABEL_SYSTEM.format(company=plan.company)
        labels: list[Label] = []
        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            payload = [
                {
                    "id": it.id,
                    "source": it.source,
                    "date": it.created_at,
                    "title": truncate(it.title, 200),
                    "text": truncate(it.text, 1500),
                }
                for it in batch
            ]
            content = (
                f"Company: {plan.company}\nScope: {plan.scope}\nThemes:\n{theme_list}\n\n"
                f"Items:\n{json.dumps(payload, ensure_ascii=False)}"
            )
            data = self._forced_tool(system, content, LABEL_TOOL)
            wanted = {it.id for it in batch}
            got = {}
            for raw in data.get("labels", []):
                if raw.get("id") in wanted:
                    got[raw["id"]] = Label(**{k: raw[k] for k in Label.__dataclass_fields__ if k in raw})
            for it in batch:  # anything the model skipped counts as not relevant
                labels.append(got.get(it.id, Label(id=it.id, relevant=False)))
            if progress:
                progress(min(start + batch_size, len(items)), len(items))
        return labels

    # --- step 3: report -------------------------------------------------------

    def write_report(self, plan: Plan, numbered: list[tuple[int, FeedbackItem, Label]], coverage_md: str, rank: bool) -> str:
        lines = []
        for n, it, lab in numbered:
            lines.append(
                f"[{n}] theme={lab.theme} | source={it.source} | date={it.created_at or 'unknown'} | "
                f"about_company={lab.about_company} | severity={lab.severity} | sentiment={lab.sentiment}\n"
                f"    pain: {lab.pain}\n    text: {truncate(it.text, 700)}"
            )
        themes = "\n".join(f"- {t.name}: {t.description}" for t in plan.themes)
        structure = (
            "Structure:\n"
            "1. Summary: 3-5 bullets on what customers say across all themes.\n"
            "2. One section per theme (in the order given), each with: the main pain points "
            "grouped and ordered by how often and how severely they come up, with citations; "
            "what customers wish existed; positive feedback if any; the job-to-be-done in one "
            "sentence ('When..., I want to..., so I can...'); and evidence gaps.\n"
            "3. Patterns across themes and notable disagreements between sources.\n"
        )
        if rank:
            structure += (
                "4. Comparison: a table with one row per theme: strength of evidence, severity, "
                "share about the company itself vs the category, and a one-line takeaway. "
                "Then rank the themes by customer pain, with reasoning.\n"
            )
        content = (
            f"Company: {plan.company}\nScope: {plan.scope}\nAudience: {plan.audience}\n"
            f"Analyst notes: {plan.notes}\nThemes:\n{themes}\n\n"
            f"Source coverage for this run:\n{coverage_md}\n\n{structure}\n"
            f"Items:\n" + "\n".join(lines)
        )
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=REPORT_SYSTEM.format(company=plan.company),
            messages=[{"role": "user", "content": content}],
        )
        return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()
