"""Tests for shared nothing_happens lifecycle gate."""

import time

from bot.config import NothingHappensConfig
from bot.standalone_markets import StandaloneMarket
from bot.strategy.nothing_happens import market_passes_strategy_lifecycle


def _minimal_market(**kwargs) -> StandaloneMarket:
    base: dict = {
        "question": "",
        "slug": "s",
        "condition_id": "c",
        "yes_token_id": "y",
        "no_token_id": "n",
        "yes_price": 0.9,
        "no_price": 0.1,
        "volume": 1.0,
        "liquidity": 1.0,
        "min_order_size": 0.0,
        "end_date": "",
        "end_ts": 0.0,
        "category": "",
        "event_slug": "",
        "keyword_exclusion_blob": "",
        "created_at_ts": 0.0,
        "end_date_ts": 0.0,
    }
    base.update(kwargs)
    return StandaloneMarket(**base)


def test_lifecycle_false_when_below_min_absolute_age():
    now = time.time()
    cfg = NothingHappensConfig(min_market_age_sec=86400.0)
    market = _minimal_market(
        created_at_ts=now - 3600.0,
        end_date_ts=now + 86400 * 90,
        end_ts=now + 86400 * 90,
    )
    assert market_passes_strategy_lifecycle(market, cfg) is False


def test_lifecycle_true_for_mature_market():
    now = time.time()
    cfg = NothingHappensConfig(
        min_market_age_sec=86400.0,
        min_time_remaining_sec=100.0,
        min_market_age_pct=0.0,
        max_market_age_pct=1.0,
    )
    market = _minimal_market(
        slug="mature",
        created_at_ts=now - 86400 * 5,
        end_date_ts=now + 86400 * 90,
        end_ts=now + 86400 * 90,
    )
    assert market_passes_strategy_lifecycle(market, cfg) is True
