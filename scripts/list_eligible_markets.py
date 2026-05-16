"""Fetch candidate Gamma markets using config exclusions, then apply lifecycle gates (same as nothing_happens).

Live strategy also gates on NO best bid vs ``max_entry_price`` (order book); this script adds a heuristic
column using Gamma ``no_price`` (outcome probability) vs ``max_entry_price`` — indicative only."""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
import time
from pathlib import Path

import aiohttp

from bot.config import load_nothing_happens_config
from bot.standalone_markets import (
    StandaloneMarket,
    fetch_candidate_markets,
    standalone_market_matches_text_exclusions,
)
from bot.strategy.nothing_happens import market_passes_strategy_lifecycle


def _gamma_price_hint_in_range(market: StandaloneMarket, max_entry: float) -> bool:
    """Loose heuristic: Gamma NO outcome vs configured max bid (strategy uses actual book best bid)."""
    return bool(0 < market.no_price <= max_entry)


async def main_async(*, csv_path: Path, max_end_date_months: int, max_gamma_pages: int | None) -> int:
    try:
        _, cfg = load_nothing_happens_config()
    except Exception as exc:
        logging.error("list_eligible_markets_config_failed: %s", exc, exc_info=True)
        return 1

    try:
        async with aiohttp.ClientSession() as session:
            markets = await fetch_candidate_markets(
                session,
                excluded_keywords=cfg.excluded_keywords,
                excluded_title_phrases=cfg.excluded_title_phrases,
                max_end_date_months=max_end_date_months,
                max_gamma_pages=max_gamma_pages,
            )
    except Exception as exc:
        logging.error("list_eligible_markets_fetch_failed: %s", exc, exc_info=True)
        return 1

    now = time.time()
    rows: list[dict] = []
    for m in markets:
        if standalone_market_matches_text_exclusions(
            m,
            excluded_keywords=cfg.excluded_keywords,
            excluded_title_phrases=cfg.excluded_title_phrases,
        ):
            continue
        open_ok = m.end_ts > now
        lifecycle_ok = open_ok and market_passes_strategy_lifecycle(m, cfg)
        gamma_hint_ok = lifecycle_ok and _gamma_price_hint_in_range(m, cfg.max_entry_price)
        lifespan = (
            (m.end_date_ts - m.created_at_ts)
            if m.created_at_ts and m.end_date_ts and m.end_date_ts > m.created_at_ts
            else 0.0
        )
        age_pct = ((now - m.created_at_ts) / lifespan) if lifespan > 0 else ""
        rows.append(
            {
                "slug": m.slug,
                "question": m.question,
                "category": m.category,
                "event_slug": m.event_slug,
                "gamma_still_before_end_iso": open_ok,
                "passes_strategy_lifecycle": lifecycle_ok,
                "gamma_no_price_hint_ok_vs_max_entry": gamma_hint_ok,
                "gamma_no_price": round(m.no_price, 6),
                "cfg_max_entry_price": cfg.max_entry_price,
                "cfg_min_market_age_sec": cfg.min_market_age_sec,
                "cfg_min_time_remaining_sec": cfg.min_time_remaining_sec,
                "cfg_min_market_age_pct": cfg.min_market_age_pct,
                "cfg_max_market_age_pct": cfg.max_market_age_pct,
                "created_at_unix": m.created_at_ts,
                "end_date_unix": m.end_date_ts,
                "age_sec": round(now - m.created_at_ts, 1) if m.created_at_ts else "",
                "remaining_sec": round(m.end_date_ts - now, 1) if m.end_date_ts else "",
                "age_pct_of_lifespan": round(age_pct, 6) if isinstance(age_pct, float) else "",
                "volume": round(m.volume, 2),
            }
        )

    n_cand = len(rows)
    n_life = sum(1 for r in rows if r["passes_strategy_lifecycle"])
    n_hint = sum(1 for r in rows if r["gamma_no_price_hint_ok_vs_max_entry"])

    if not rows:
        print("No candidates returned from Gamma.")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                f.write("")
        except OSError as exc:
            logging.error("list_eligible_markets_csv_write_failed path=%s err=%s", csv_path, exc, exc_info=True)
            return 1
        return 0

    fieldnames = list(rows[0].keys())

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except OSError as exc:
        logging.error("list_eligible_markets_csv_write_failed path=%s err=%s", csv_path, exc, exc_info=True)
        return 1

    print(
        "Gamma candidates (after discovery filters): %d\n"
        "Passes strategy lifecycle gates (excluding open-book check): %d\n"
        "Also heuristic Gamma NO px <= max_entry_price: %d\n"
        "Wrote CSV: %s"
        % (n_cand, n_life, n_hint, csv_path.resolve()),
    )
    if max_gamma_pages is not None:
        print("(Truncated: --max-gamma-pages=%d; omit for full Gamma scan.)" % max_gamma_pages)

    lifecycle_slugs = [r["slug"] for r in rows if r["passes_strategy_lifecycle"]]
    for slug in lifecycle_slugs[:80]:
        print(slug)
    if len(lifecycle_slugs) > 80:
        print("… %d more (see CSV)" % (len(lifecycle_slugs) - 80))

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        default="eligible_markets_report.csv",
        help="Secondary CSV export path (default: eligible_markets_report.csv in cwd)",
    )
    parser.add_argument(
        "--max-end-date-months",
        type=int,
        default=3,
        help="Same horizon as standalone_markets.fetch_candidate_markets default.",
    )
    parser.add_argument(
        "--max-gamma-pages",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N Gamma pages (for testing); default scans until exhausted.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    code = asyncio.run(
        main_async(
            csv_path=Path(args.csv),
            max_end_date_months=args.max_end_date_months,
            max_gamma_pages=args.max_gamma_pages,
        )
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
