"""Registry of available feedback sources."""

from __future__ import annotations

from .base import Source
from .discourse import Discourse
from .github import GitHubIssues
from .hackernews import HackerNews
from .imports import Imports
from .reddit import Reddit
from .stackexchange import StackExchange
from .web import WebSearch

REGISTRY: dict[str, type[Source]] = {
    cls.name: cls
    for cls in (HackerNews, Reddit, StackExchange, GitHubIssues, Discourse, WebSearch, Imports)
}

DEFAULT_SOURCES = [name for name, cls in REGISTRY.items() if cls.default_enabled]

__all__ = ["REGISTRY", "DEFAULT_SOURCES", "Source"]
