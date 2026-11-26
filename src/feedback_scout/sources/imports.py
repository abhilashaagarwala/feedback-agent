"""Reviews you export or copy by hand (G2, Gartner Peer Insights, TrustRadius,
PeerSpot, Capterra, a vendor forum, interview notes...).

Those sites don't offer a public API for readers, and their terms restrict
automated collection, so feedback-scout never scrapes them. Instead, save what
you read into the imports folder and it is analysed with everything else.

File naming: the part before the first "_" or "-" becomes the source label,
e.g. ``g2_snowflake.csv`` -> ``g2``, ``gartner-notes.md`` -> ``gartner``.

Supported formats
- .csv   columns: text (or review/body/content/comment), optional likes,
         dislikes, pros, cons, title, url, date, author, rating
- .json / .jsonl  objects with the same keys
- .md / .txt      one review per block, blocks separated by a line "---".
                  Optional first lines "url: ...", "date: ...", "title: ...".
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

from ..models import FeedbackItem, Plan, SourceReport
from .base import Source, within

TEXT_KEYS = ("text", "review", "body", "content", "comment", "feedback")
EXTRA_TEXT_KEYS = ("likes", "dislikes", "pros", "cons", "what do you like best", "what do you dislike")
DATE_KEYS = ("date", "created_at", "published", "review_date")
META = re.compile(r"^(url|date|title|author|source)\s*:\s*(.+)$", re.IGNORECASE)


class Imports(Source):
    name = "imports"
    label = "Your imports (review sites)"
    request_delay = 0

    def __init__(self, *args, folder: str | Path = "imports", **kwargs):
        super().__init__(*args, **kwargs)
        self.folder = Path(folder)

    def _files(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        return sorted(
            p for p in self.folder.rglob("*")
            if p.is_file() and p.suffix.lower() in {".csv", ".json", ".jsonl", ".md", ".txt"}
        )

    def status(self, plan: Plan | None = None) -> tuple[bool, str]:
        files = self._files()
        if not files:
            return False, f"no files in {self.folder}/ (add exported or copied reviews there)"
        return True, f"{len(files)} file(s) in {self.folder}/"

    def search(self, query: str, since: date | None, limit: int, plan: Plan) -> list[FeedbackItem]:
        return []  # not query-driven; see collect()

    def collect(self, plan: Plan, since: date | None, limit: int) -> tuple[list[FeedbackItem], SourceReport]:
        report = SourceReport(name=self.name)
        ready, why = self.status(plan)
        if not ready:
            report.status, report.note = "skipped", why
            return [], report
        items: list[FeedbackItem] = []
        for path in self._files():
            try:
                items.extend(self.read_file(path))
            except Exception as exc:
                report.errors.append(f"{path.name}: {exc}")
        items = [i for i in items if within(i, since)]
        report.collected = len(items)
        report.status = "ok" if items or not report.errors else "error"
        report.note = why if not report.errors else f"{why}; {len(report.errors)} file(s) failed"
        return items, report

    # --- parsing -------------------------------------------------------------

    @staticmethod
    def label_for(path: Path) -> str:
        return re.split(r"[_\-\s.]", path.stem, maxsplit=1)[0].lower() or "import"

    def read_file(self, path: Path) -> list[FeedbackItem]:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
        elif suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            rows = data if isinstance(data, list) else data.get("items", [])
        elif suffix == ".jsonl":
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        else:
            rows = self._text_blocks(path.read_text(encoding="utf-8"))
        label = self.label_for(path)
        out = []
        for n, row in enumerate(rows, start=1):
            item = self._row_to_item(row, label, path, n)
            if item:
                out.append(item)
        return out

    @staticmethod
    def _text_blocks(raw: str) -> list[dict]:
        rows = []
        for block in re.split(r"^\s*---\s*$", raw, flags=re.MULTILINE):
            lines = block.strip().splitlines()
            meta: dict = {}
            while lines and META.match(lines[0].strip()):
                k, v = META.match(lines[0].strip()).groups()
                meta[k.lower()] = v.strip()
                lines.pop(0)
            text = "\n".join(lines).strip()
            if text:
                rows.append({**meta, "text": text})
        return rows

    @staticmethod
    def _row_to_item(row: dict, label: str, path: Path, n: int) -> FeedbackItem | None:
        lower = {str(k).strip().lower(): ("" if v is None else str(v).strip()) for k, v in row.items()}
        parts = [lower[k] for k in TEXT_KEYS if lower.get(k)]
        parts += [f"{k.title()}: {lower[k]}" for k in EXTRA_TEXT_KEYS if lower.get(k)]
        text = "\n\n".join(parts)
        if not text:
            return None
        created = next((lower[k] for k in DATE_KEYS if lower.get(k)), "")
        rating = lower.get("rating", "")
        return FeedbackItem(
            source=lower.get("source") or label,
            url=lower.get("url") or f"{path.as_posix()}#{n}",
            title=lower.get("title", ""),
            text=text,
            author=lower.get("author", "") or lower.get("role", ""),
            created_at=created[:10],
            extra={"rating": rating, "file": path.name} if rating else {"file": path.name},
        )
