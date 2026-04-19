"""
LLM processor: uses GLM-4-Flash to translate and summarise each paper.
Adapted from cmwalker2048/arxiv-daily-tracker.
"""
from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from openai import OpenAI

if TYPE_CHECKING:
    from fetcher.journal_fetcher import Paper

logger = logging.getLogger(__name__)


def translate_title_free(title: str) -> str:
    """Translate title to Chinese using MyMemory free API (no key needed)."""
    try:
        import requests
        resp = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": title[:500], "langpair": "en|zh"},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            translated = data.get("responseData", {}).get("translatedText", "")
            if translated and translated != title:
                return translated
    except Exception:
        pass
    return title

# ── Delimiter tags used in LLM output ─────────────────────────────────────────
_TAGS = ["TITLE_ZH", "CORE_VALUE", "KEYWORDS", "ABSTRACT_EN", "ABSTRACT_ZH"]


def _extract_section(text: str, tag: str) -> str:
    pattern = rf"==={tag}===\s*(.*?)\s*(?====[A-Z_]+=|$)"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _parse_keywords(raw: str) -> list[str]:
    # Expect: "term_en / 中文; term2_en / 中文2"
    parts = re.split(r"[;；\n]", raw)
    result = []
    for p in parts:
        p = p.strip().strip("•-").strip()
        if p:
            result.append(p)
    return result[:5]


def _apply_marks(text: str, terms: list[str]) -> str:
    """Bold-mark key terms in text, skipping LaTeX math regions."""
    if not terms:
        return text
    math_spans: list[tuple[int, int]] = []
    for m in re.finditer(r"\$[^$]*\$", text):
        math_spans.append((m.start(), m.end()))

    def _in_math(pos: int) -> bool:
        return any(s <= pos < e for s, e in math_spans)

    for term in terms:
        escaped = re.escape(term)
        def _replacer(m, _term=term):
            if _in_math(m.start()):
                return m.group(0)
            inner = m.group(0)
            if inner.startswith("**"):
                return inner
            return f"**{inner}**"
        text = re.sub(escaped, _replacer, text, flags=re.IGNORECASE)
    return text


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).strip()


# ── Main processor ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert scientific editor specializing in materials science,
battery technology, electron microscopy, and 2D materials.
Your task is to analyse a journal paper and produce structured bilingual output.

Rules:
1. ===CORE_VALUE===: 1-2 sentences in Chinese summarising the key scientific contribution.
2. ===KEYWORDS===: 2-4 bilingual keyword pairs (English / Chinese), semicolon-separated.
3. ===ABSTRACT_EN===: Original abstract with **2-4 key phrases bolded**.
4. ===ABSTRACT_ZH===: Chinese translation with corresponding **bolded phrases**.
5. ===TITLE_ZH===: Chinese translation of the title.
Output ONLY the tagged sections, no extra text."""

USER_TEMPLATE = """Journal: {journal}
Title: {title}
Authors: {authors}
Abstract: {abstract}

Produce the structured output now."""


class PaperProcessor:
    def __init__(self, api_key: str, model: str = "glm-4-flash", max_retries: int = 3):
        self._client = OpenAI(
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
        )
        self._model = model
        self._max_retries = max_retries

    def process(self, paper: "Paper") -> "Paper":
        """Run LLM processing on a paper, returning the enriched Paper."""
        abstract = _strip_html(paper.abstract) or "(Abstract not available)"
        authors_str = ", ".join(paper.authors[:5])
        if len(paper.authors) > 5:
            authors_str += " et al."

        user_msg = USER_TEMPLATE.format(
            journal=paper.journal,
            title=paper.title,
            authors=authors_str,
            abstract=abstract[:2000],  # truncate very long abstracts
        )

        raw = self._call_llm(user_msg)
        if not raw:
            logger.warning("LLM returned empty for: %s", paper.title[:60])
            paper.title_zh = paper.title
            paper.core_value = ""
            paper.abstract_en_highlighted = abstract
            paper.abstract_zh = ""
            return paper

        paper.title_zh = _extract_section(raw, "TITLE_ZH") or paper.title
        paper.core_value = _extract_section(raw, "CORE_VALUE")
        kw_raw = _extract_section(raw, "KEYWORDS")
        paper.keywords = _parse_keywords(kw_raw)
        paper.abstract_en_highlighted = _extract_section(raw, "ABSTRACT_EN") or abstract
        paper.abstract_zh = _extract_section(raw, "ABSTRACT_ZH")

        # Fallback: if LLM forgot to bold, apply Python-side highlighting
        kw_terms = [k.split("/")[0].strip() for k in paper.keywords]
        if "**" not in paper.abstract_en_highlighted and kw_terms:
            paper.abstract_en_highlighted = _apply_marks(abstract, kw_terms)

        return paper

    def _call_llm(self, user_msg: str) -> str:
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.3,
                    max_tokens=1500,
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                logger.warning("LLM attempt %d/%d failed: %s", attempt, self._max_retries, e)
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)
        return ""
