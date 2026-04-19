"""
Journal fetcher: RSS-first, CrossRef fallback.

Flow for each journal:
  1. Parse RSS feed → papers published on target_date
  2. If count == 0, query CrossRef API for papers within fallback_days
  3. Return list of Paper objects
"""
from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Optional

import feedparser
import requests

logger = logging.getLogger(__name__)

CROSSREF_API = "https://api.crossref.org/works"
CROSSREF_HEADERS = {"User-Agent": "JournalDailyTracker/1.0 (mailto:your@email.com)"}
RSS_TIMEOUT = 30
CROSSREF_TIMEOUT = 20


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Paper:
    title: str
    abstract: str
    authors: list[str]
    url: str
    doi: str
    journal: str
    pub_date: Optional[date]
    # Filled by processor
    title_zh: str = ""
    core_value: str = ""
    keywords: list[str] = field(default_factory=list)
    abstract_en_highlighted: str = ""
    abstract_zh: str = ""


# ── HTML stripper ─────────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str):
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _strip_html(text: str) -> str:
    if not text:
        return ""
    p = _TextExtractor()
    try:
        p.feed(text)
        return p.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", text).strip()


# ── Date helpers ──────────────────────────────────────────────────────────────

def _parse_rss_date(entry) -> Optional[date]:
    """Extract publication date from an RSS entry."""
    # feedparser normalises to published_parsed (time.struct_time, UTC)
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return date(t.tm_year, t.tm_mon, t.tm_mday)
            except (ValueError, AttributeError):
                pass
    # Try raw string fallback
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, "")
        if raw:
            for fmt in ("%Y-%m-%d", "%d %b %Y", "%B %d, %Y"):
                try:
                    return datetime.strptime(raw[:len(fmt)+4].strip(), fmt).date()
                except ValueError:
                    pass
    return None


def _crossref_date(item: dict) -> Optional[date]:
    """Extract date from a CrossRef work item."""
    for key in ("published", "published-print", "published-online", "created"):
        dp = item.get(key, {}).get("date-parts", [[]])
        if dp and dp[0]:
            parts = dp[0]
            try:
                y = parts[0]
                m = parts[1] if len(parts) > 1 else 1
                d_ = parts[2] if len(parts) > 2 else 1
                return date(y, m, d_)
            except (ValueError, IndexError):
                pass
    return None


# ── RSS fetcher ───────────────────────────────────────────────────────────────

def _fetch_rss(journal_cfg: dict, target_date: date) -> list[Paper]:
    """Fetch papers from RSS feed published on target_date."""
    rss_url = journal_cfg.get("rss", "")
    if not rss_url:
        return []

    try:
        feed = feedparser.parse(rss_url, request_headers={"User-Agent": CROSSREF_HEADERS["User-Agent"]})
    except Exception as e:
        logger.warning("[RSS] %s failed: %s", journal_cfg["name"], e)
        return []

    papers = []
    for entry in feed.entries:
        pub_date = _parse_rss_date(entry)
        # Allow ±1 day tolerance for timezone issues
        if pub_date is None or abs((pub_date - target_date).days) > 1:
            continue

        title = _strip_html(getattr(entry, "title", "") or "")
        abstract = _strip_html(
            getattr(entry, "summary", "")
            or getattr(entry, "description", "")
            or ""
        )
        url = getattr(entry, "link", "") or ""
        doi = ""
        # Some feeds embed DOI
        for link in getattr(entry, "links", []):
            href = link.get("href", "")
            if "doi.org" in href:
                doi = href.split("doi.org/")[-1]
                break
        if not doi:
            doi_tag = getattr(entry, "prism_doi", "") or getattr(entry, "dc_identifier", "")
            doi = doi_tag.replace("doi:", "").strip()

        authors = _parse_rss_authors(entry)

        if title:
            papers.append(Paper(
                title=title,
                abstract=abstract,
                authors=authors,
                url=url,
                doi=doi,
                journal=journal_cfg["name"],
                pub_date=pub_date,
            ))

    return papers


def _parse_rss_authors(entry) -> list[str]:
    # Atom-style author list
    if hasattr(entry, "authors") and entry.authors:
        names = []
        for a in entry.authors:
            name = getattr(a, "name", "") or a.get("name", "")
            if name:
                names.append(name)
        if names:
            return names
    # dc:creator or author tag
    for attr in ("author", "dc_creator"):
        raw = getattr(entry, attr, "") or ""
        if raw:
            # comma or semicolon separated
            parts = re.split(r"[;,]", raw)
            return [p.strip() for p in parts if p.strip()]
    return []


# ── CrossRef fetcher ──────────────────────────────────────────────────────────

def _fetch_crossref(journal_cfg: dict, from_date: date, until_date: date,
                    max_rows: int = 50) -> list[Paper]:
    """Query CrossRef for papers in a date range."""
    issn = journal_cfg.get("issn", "")
    if not issn:
        return []

    params = {
        "filter": f"issn:{issn},from-pub-date:{from_date},until-pub-date:{until_date}",
        "rows": max_rows,
        "sort": "published",
        "order": "desc",
        "select": "DOI,title,abstract,author,URL,published,published-print,published-online,container-title",
    }

    try:
        resp = requests.get(CROSSREF_API, params=params,
                            headers=CROSSREF_HEADERS, timeout=CROSSREF_TIMEOUT)
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])
    except Exception as e:
        logger.warning("[CrossRef] %s failed: %s", journal_cfg["name"], e)
        return []

    papers = []
    for item in items:
        title_list = item.get("title", [])
        title = _strip_html(title_list[0] if title_list else "")
        if not title:
            continue

        abstract = _strip_html(item.get("abstract", "") or "")
        doi = item.get("DOI", "")
        url = item.get("URL", "") or (f"https://doi.org/{doi}" if doi else "")
        pub_date = _crossref_date(item)

        authors = []
        for a in item.get("author", []):
            given = a.get("given", "")
            family = a.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)

        papers.append(Paper(
            title=title,
            abstract=abstract,
            authors=authors,
            url=url,
            doi=doi,
            journal=journal_cfg["name"],
            pub_date=pub_date,
        ))

    return papers


# ── Abstract enrichment ───────────────────────────────────────────────────────

def _enrich_abstract(paper: Paper) -> Paper:
    """Fetch full abstract via CrossRef DOI lookup if abstract is empty."""
    if paper.abstract or not paper.doi:
        return paper
    try:
        resp = requests.get(
            f"https://api.crossref.org/works/{paper.doi}",
            headers=CROSSREF_HEADERS,
            timeout=CROSSREF_TIMEOUT,
        )
        if resp.ok:
            data = resp.json().get("message", {})
            abstract = _strip_html(data.get("abstract", "") or "")
            if abstract:
                paper.abstract = abstract
    except Exception:
        pass
    return paper


# ── Public interface ──────────────────────────────────────────────────────────

def fetch_papers_for_journal(
    journal_cfg: dict,
    target_date: date,
    fallback_days: int = 30,
) -> list[Paper]:
    """
    Fetch relevant papers for one journal.

    Steps:
      1. Try RSS for target_date (±1 day)
      2. If empty, try CrossRef for target_date
      3. If still empty, widen to fallback_days via CrossRef
    Returns at most max(all found) papers; caller filters by topic.
    """
    name = journal_cfg["name"]

    # Step 1: RSS
    papers = _fetch_rss(journal_cfg, target_date)
    logger.info("[%s] RSS → %d papers on %s", name, len(papers), target_date)

    # Step 2: CrossRef for exact date
    if not papers:
        time.sleep(1.0)
        papers = _fetch_crossref(journal_cfg, target_date, target_date, max_rows=50)
        logger.info("[%s] CrossRef exact → %d papers", name, len(papers))

    # Step 3: Widen window
    if not papers:
        time.sleep(2.0)
        fallback_from = target_date - timedelta(days=fallback_days)
        papers = _fetch_crossref(journal_cfg, fallback_from, target_date, max_rows=100)
        logger.info("[%s] CrossRef fallback (%dd) → %d papers", name, fallback_days, len(papers))

    # Enrich abstracts (best-effort, only for short abstracts)
    enriched = []
    for idx, p in enumerate(papers[:40]):  # Cap to avoid too many API calls
        if len(p.abstract) < 50:
            if idx > 0:
                time.sleep(1.0)  # Respect CrossRef rate limit (1 req/sec)
            p = _enrich_abstract(p)
        enriched.append(p)

    return enriched
