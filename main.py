"""
main.py — CLI entry point for the journal daily tracker.

Usage:
  python main.py                      # yesterday's papers, auto-detect
  python main.py --date 2026-04-18    # specific date
  python main.py --no-llm             # skip LLM processing (raw markdown only)
  python main.py --verbose            # debug logging
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

# ── Logging setup ──────────────────────────────────────────────────────────────
def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

# ── Config loader ──────────────────────────────────────────────────────────────
def _load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# ── Date helper ────────────────────────────────────────────────────────────────
def _resolve_date(date_str: str | None) -> date:
    if date_str:
        return date.fromisoformat(date_str)
    return date.today() - timedelta(days=1)  # yesterday

# ── Main pipeline ──────────────────────────────────────────────────────────────
def run(target_date: date, config: dict, use_llm: bool = True) -> Path:
    from fetcher.journal_fetcher import fetch_papers_for_journal
    from processor.filter import filter_papers, select_best_fallback
    from renderer.markdown_writer import render_daily

    topics = config.get("topics", {})
    journals = config.get("journals", [])
    output_dir = config.get("output", {}).get("dir", "./output")
    fallback_days = 30

    # Optional LLM processor
    processor = None
    if use_llm:
        api_key = os.environ.get("ZHIPUAI_API_KEY", "")
        if api_key:
            from processor.translator import PaperProcessor
            llm_cfg = config.get("llm", {})
            processor = PaperProcessor(
                api_key=api_key,
                model=llm_cfg.get("model", "glm-4-flash"),
                max_retries=llm_cfg.get("max_retries", 3),
            )
        else:
            logging.warning("ZHIPUAI_API_KEY not set — skipping LLM processing.")

    results: dict[str, list] = {}
    fallback_journals: set[str] = set()

    for jcfg in journals:
        jname = jcfg["name"]
        logging.info("── Fetching: %s", jname)

        all_papers = fetch_papers_for_journal(jcfg, target_date, fallback_days=fallback_days)

        # Try papers from target_date first
        # Allow ±1 day tolerance for timezone differences across journals
        today_papers = [p for p in all_papers
                        if p.pub_date and abs((p.pub_date - target_date).days) <= 1]

        if today_papers:
            # RSS found papers for this date → show all (journal itself is the filter)
            selected = today_papers[:3]
        else:
            # No papers found for this date → keyword-filter the 30-day fallback
            selected = select_best_fallback(all_papers, topics, n=1)
            if selected:
                fallback_journals.add(jname)
                logging.info("  → fallback paper: %s", selected[0].pub_date)
            else:
                # Last resort: just take the most recent paper regardless of topic
                recent = sorted([p for p in all_papers if p.pub_date],
                                key=lambda p: p.pub_date, reverse=True)
                if recent:
                    selected = [recent[0]]
                    fallback_journals.add(jname)
                    logging.info("  → last-resort fallback: %s", selected[0].pub_date)

        # LLM processing (full summary) or free title translation fallback
        if processor and selected:
            processed = []
            for paper in selected:
                try:
                    processed.append(processor.process(paper))
                except Exception as e:
                    logging.warning("  LLM failed for '%s': %s", paper.title[:50], e)
                    processed.append(paper)
            selected = processed
        else:
            # No LLM: at least translate the title for free
            from processor.translator import translate_title_free
            for paper in selected:
                if not paper.title_zh:
                    paper.title_zh = translate_title_free(paper.title)
                    logging.info("  Translated: %s", paper.title_zh[:60])

        results[jname] = selected
        logging.info("  → %d paper(s) selected", len(selected))

    out_path = render_daily(results, target_date, fallback_journals, output_dir)
    logging.info("Done → %s", out_path)
    return out_path


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Journal Daily Tracker")
    parser.add_argument("--date", type=str, default=None,
                        help="Target date YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM translation/summarisation")
    parser.add_argument("--config", type=str, default="config.yaml",
                        help="Config file path")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    cfg = _load_config(args.config)
    target = _resolve_date(args.date)
    logging.info("Target date: %s", target)

    out_path = run(target, cfg, use_llm=not args.no_llm)
    print(f"\n✅ Report generated: {out_path}")


if __name__ == "__main__":
    main()
