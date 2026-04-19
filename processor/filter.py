"""
Topic filter: decides whether a paper matches the user-defined topics.

A paper is accepted if its title OR abstract contains at least one keyword
from ANY topic group.
"""
from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fetcher.journal_fetcher import Paper

logger = logging.getLogger(__name__)


def _normalise(text: str) -> str:
    """Lowercase and collapse whitespace for robust matching."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _build_patterns(topics: dict[str, list[str]]) -> list[re.Pattern]:
    """Compile one regex per keyword (word-boundary aware, case-insensitive)."""
    patterns = []
    for group_keywords in topics.values():
        for kw in group_keywords:
            # For short abbreviations (TEM, STEM) use word boundary.
            # For phrases, allow partial matches.
            escaped = re.escape(kw)
            if len(kw) <= 6 and kw.isupper():
                pat = re.compile(r"\b" + escaped + r"\b")
            else:
                pat = re.compile(escaped, re.IGNORECASE)
            patterns.append(pat)
    return patterns


def matches_topics(paper: "Paper", patterns: list[re.Pattern]) -> bool:
    """Return True if the paper title or abstract matches any keyword."""
    haystack = paper.title + " " + paper.abstract
    for pat in patterns:
        if pat.search(haystack):
            return True
    return False


def filter_papers(
    papers: list["Paper"],
    topics: dict[str, list[str]],
) -> list["Paper"]:
    """Filter a list of papers to those matching the topic keywords."""
    patterns = _build_patterns(topics)
    matched = [p for p in papers if matches_topics(p, patterns)]
    logger.info("Filter: %d / %d papers matched topics", len(matched), len(papers))
    return matched


def select_best_fallback(
    papers: list["Paper"],
    topics: dict[str, list[str]],
    n: int = 1,
) -> list["Paper"]:
    """
    From a list of topic-matched papers (possibly spanning many dates),
    pick the n most recent ones as the fallback.
    """
    matched = filter_papers(papers, topics)
    # Sort newest first (None dates go last)
    matched.sort(
        key=lambda p: p.pub_date.toordinal() if p.pub_date else 0,
        reverse=True,
    )
    return matched[:n]
