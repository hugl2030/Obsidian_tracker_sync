"""
Markdown renderer: generates a daily digest file.

Output path: output/{year}/{YYYY-MM-DD}.md
Also writes output/latest.md (symlink target for Obsidian convenience).
"""
from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fetcher.journal_fetcher import Paper

logger = logging.getLogger(__name__)

HEADER_TEMPLATE = """---
date: {date}
type: journal-digest
topics: [battery, microscopy, 2D-materials, materials]
---

# 📰 期刊每日速递 · {date}

> 涵盖期刊：Nature 系列 · Science 系列 · ACS · Wiley
> 话题：电池 · 电子显微镜 · 二维材料 · 材料科学

"""

JOURNAL_HEADER = "## {journal}\n\n"

PAPER_TEMPLATE = """### {idx}. {title}

> **{title_zh}**

| | |
|---|---|
| **期刊** | {journal} |
| **作者** | {authors} |
| **日期** | {pub_date} |
| **DOI** | [{doi}](https://doi.org/{doi}) |

**🔑 核心价值**：{core_value}

**关键词**：{keywords}

<details>
<summary>📄 英文摘要</summary>

{abstract_en}

</details>

<details>
<summary>📝 中文摘要</summary>

{abstract_zh}

</details>

---
"""

FALLBACK_NOTE = "*（当日无相关文章，以下为近期精选）*\n\n"
NO_PAPER_NOTE = "*（未找到相关文章）*\n\n"


def _fmt_authors(authors: list[str], max_n: int = 4) -> str:
    if not authors:
        return "N/A"
    if len(authors) <= max_n:
        return ", ".join(authors)
    return ", ".join(authors[:max_n]) + " et al."


def _fmt_doi(doi: str) -> str:
    return doi if doi else "N/A"


def render_daily(
    results: dict[str, list["Paper"]],  # journal_name → papers (already processed)
    target_date: date,
    fallback_journals: set[str],        # journals where fallback was used
    output_dir: str = "./output",
) -> Path:
    """
    Render the daily digest markdown file.

    Args:
        results: dict mapping journal name to list of processed Paper objects.
        target_date: the date being reported.
        fallback_journals: set of journal names that used fallback papers.
        output_dir: base output directory.

    Returns:
        Path to the generated markdown file.
    """
    year_str = str(target_date.year)
    date_str = target_date.isoformat()

    out_dir = Path(output_dir) / year_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}.md"

    lines: list[str] = [HEADER_TEMPLATE.format(date=date_str)]

    total_papers = sum(len(v) for v in results.values())
    lines.append(f"> 本期共收录 **{total_papers}** 篇，覆盖 **{len(results)}** 个期刊。\n\n")
    lines.append("---\n\n")

    for journal_name, papers in sorted(results.items()):
        lines.append(JOURNAL_HEADER.format(journal=journal_name))

        if not papers:
            lines.append(NO_PAPER_NOTE)
            continue

        if journal_name in fallback_journals:
            lines.append(FALLBACK_NOTE)

        for idx, paper in enumerate(papers, start=1):
            authors_str = _fmt_authors(paper.authors)
            pub_date_str = paper.pub_date.isoformat() if paper.pub_date else "Unknown"
            doi_str = _fmt_doi(paper.doi)

            # Graceful fallbacks for unprocessed papers
            title_zh = paper.title_zh or paper.title
            core_value = paper.core_value or "（暂无）"
            keywords = " · ".join(paper.keywords) if paper.keywords else "—"
            abstract_en = paper.abstract_en_highlighted or paper.abstract or "（暂无）"
            abstract_zh = paper.abstract_zh or "（暂无）"

            lines.append(PAPER_TEMPLATE.format(
                idx=idx,
                title=paper.title,
                title_zh=title_zh,
                journal=journal_name,
                authors=authors_str,
                pub_date=pub_date_str,
                doi=doi_str,
                core_value=core_value,
                keywords=keywords,
                abstract_en=abstract_en,
                abstract_zh=abstract_zh,
            ))

    content = "".join(lines)
    out_path.write_text(content, encoding="utf-8")
    logger.info("Written: %s (%d chars)", out_path, len(content))

    # Also write a latest.md for quick Obsidian access
    latest_path = Path(output_dir) / "latest.md"
    latest_path.write_text(content, encoding="utf-8")

    return out_path
