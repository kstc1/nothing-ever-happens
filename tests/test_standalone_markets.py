import pytest

from bot.standalone_markets import (
    StandaloneMarket,
    build_standalone_market,
    is_market_text_excluded,
    standalone_market_matches_text_exclusions,
)
from bot.standalone_markets import _raw_market_contains_clob_token


@pytest.fixture
def base_binary_market() -> dict:
    return {
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["111", "222"]',
        "outcomePrices": "[0.5, 0.5]",
        "question": "",
        "slug": "test-market-slug-only",
        "endDate": "2099-01-01T00:00:00Z",
    }


def test_raw_market_contains_clob_token_handles_string_json_list():
    raw = {
        "clobTokenIds": '["111", "222"]',
    }
    assert _raw_market_contains_clob_token(raw, "222")
    assert not _raw_market_contains_clob_token(raw, "333")


def test_is_market_text_excluded_matches_gamma_title_when_question_empty(base_binary_market):
    raw = dict(base_binary_market)
    raw["title"] = "Will Russia capture Sampleville by Friday?"
    assert is_market_text_excluded(
        raw,
        excluded_keywords=frozenset({"russia"}),
        excluded_title_phrases=frozenset(),
    )


def test_is_market_text_excluded_matches_nested_event_title(base_binary_market):
    raw = dict(base_binary_market)
    raw["slug"] = "foo-bar"
    raw["events"] = [{"title": "Russia troop movements", "slug": "russia-evt"}]
    assert is_market_text_excluded(
        raw,
        excluded_keywords=frozenset({"russia"}),
        excluded_title_phrases=frozenset(),
    )


def test_standalone_market_matches_text_exclusions_after_build_includes_event_text(base_binary_market):
    raw = dict(base_binary_market)
    raw["slug"] = "foo-bar"
    raw["events"] = [{"title": "Russia troop movements", "slug": "russia-evt"}]
    built = build_standalone_market(raw)
    assert built is not None
    assert standalone_market_matches_text_exclusions(
        built,
        excluded_keywords=frozenset({"russia"}),
        excluded_title_phrases=frozenset(),
    )


def test_standalone_market_matches_text_exclusions_on_slug():
    m = StandaloneMarket(
        question="",
        slug="will-russia-enter-x-by-may-31",
        condition_id="c",
        yes_token_id="y",
        no_token_id="n",
        yes_price=0.5,
        no_price=0.5,
        volume=0.0,
        liquidity=0.0,
        min_order_size=0.0,
        end_date="",
        end_ts=0.0,
        category="",
        event_slug="",
        keyword_exclusion_blob="will-russia-enter-x-by-may-31",
    )
    assert standalone_market_matches_text_exclusions(
        m,
        excluded_keywords=frozenset({"russia"}),
        excluded_title_phrases=frozenset(),
    )


def test_is_market_text_excluded_respects_title_phrases_on_title_field(base_binary_market):
    raw = dict(base_binary_market)
    raw["title"] = "Nothing ever happens in this market"
    assert is_market_text_excluded(
        raw,
        excluded_keywords=frozenset(),
        excluded_title_phrases=frozenset({"nothing ever happens"}),
    )
