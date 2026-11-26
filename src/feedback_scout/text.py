"""Small text helpers."""

from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|br|div|li|pre|blockquote)[^>]*>", re.IGNORECASE)
_WS = re.compile(r"[ \t]+")
_NL = re.compile(r"\n{3,}")


def html_to_text(value: str | None) -> str:
    """Strip HTML to readable plain text."""
    if not value:
        return ""
    text = _BLOCK.sub("\n", value)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = _NL.sub("\n\n", text)
    return text.strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
