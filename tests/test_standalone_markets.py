from types import SimpleNamespace
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import aiohttp
import pytest

import bot.standalone_markets as standalone_markets

from bot.standalone_markets import (
    StandaloneMarket,
    build_standalone_market,
    fetch_candidate_markets,
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


def test_parse_retry_after_seconds_honors_positive_header():
    headers = {"Retry-After": "3.5"}
    assert standalone_markets._parse_retry_after_seconds(headers) == 3.5


def test_parse_retry_after_seconds_zero_or_negative_treated_as_missing():
    assert standalone_markets._parse_retry_after_seconds({"Retry-After": "0"}) is None
    assert standalone_markets._parse_retry_after_seconds({"Retry-After": "-1"}) is None


def test_raw_market_contains_clob_token_handles_string_json_list():
    raw = {
        "clobTokenIds": '["111", "222"]',
    }
    assert _raw_market_contains_clob_token(raw, "222")
    assert not _raw_market_contains_clob_token(raw, "333")


def test_is_market_text_excluded_matches_embedded_tag_label(base_binary_market):
    raw = dict(base_binary_market)
    raw["title"] = "Untitled"
    raw["tags"] = [{"label": "Russia", "slug": "russia"}]
    assert is_market_text_excluded(
        raw,
        excluded_keywords=frozenset({"russia"}),
        excluded_title_phrases=frozenset(),
    )


def test_is_market_text_excluded_ignores_title_for_keywords(base_binary_market):
    raw = dict(base_binary_market)
    raw["title"] = "Will Russia capture Sampleville by Friday?"
    raw["tags"] = []
    assert not is_market_text_excluded(
        raw,
        excluded_keywords=frozenset({"russia"}),
        excluded_title_phrases=frozenset(),
    )


def test_is_market_text_excluded_ignores_event_slug_for_keywords(base_binary_market):
    raw = dict(base_binary_market)
    raw["slug"] = "foo-bar"
    raw["events"] = [{"title": "Russia troop movements", "slug": "russia-evt"}]
    raw["tags"] = []
    assert not is_market_text_excluded(
        raw,
        excluded_keywords=frozenset({"russia"}),
        excluded_title_phrases=frozenset(),
    )


def test_standalone_market_matches_text_exclusions_uses_tag_blob_only():
    raw = {
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["111", "222"]',
        "outcomePrices": "[0.5, 0.5]",
        "question": "Peace in Sampleville?",
        "slug": "peace-sampleville",
        "endDate": "2099-01-01T00:00:00Z",
        "tags": [{"label": "russia-politics", "slug": "russia"}],
    }
    built = build_standalone_market(raw)
    assert built is not None
    assert standalone_market_matches_text_exclusions(
        built,
        excluded_keywords=frozenset({"russia"}),
        excluded_title_phrases=frozenset(),
    )


def test_standalone_market_matches_text_exclusions_slug_not_in_blob_without_tags():
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
        keyword_exclusion_blob="",
    )
    assert not standalone_market_matches_text_exclusions(
        m,
        excluded_keywords=frozenset({"russia"}),
        excluded_title_phrases=frozenset(),
    )


def test_standalone_market_matches_text_exclusions_on_manual_tag_blob():
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
        keyword_exclusion_blob="politics\nrussia",
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


def test_is_market_text_excluded_override_blob(base_binary_market):
    raw = dict(base_binary_market)
    raw["tags"] = []
    assert is_market_text_excluded(
        raw,
        excluded_keywords=frozenset({"sports"}),
        excluded_title_phrases=frozenset(),
        tag_keyword_blob_override="basketball sports",
    )


@pytest.mark.asyncio
async def test_fetch_candidate_markets_calls_tags_endpoint_when_keywords_configured():
    future_end = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    batch = [
        {
            "id": 424242,
            "question": "Will it rain?",
            "slug": "will-it-rain-tags",
            "conditionId": "cond-rain",
            "events": [{"slug": "single-event"}],
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["yes-rain", "no-rain"]',
            "outcomePrices": "[0.31, 0.69]",
            "volume": "1234",
            "liquidity": "4321",
            "orderMinSize": "5",
            "endDate": future_end,
        }
    ]

    urls: list[str] = []

    class RecordingSession:
        def get(self, url, **kwargs):
            urls.append(str(url))

            class Resp:
                def __init__(self, payload, status=200):
                    self._payload = payload
                    self.status = status

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

                def raise_for_status(self):
                    if self.status >= 400:
                        raise aiohttp.ClientResponseError(
                            request_info=SimpleNamespace(real_url="http://test"),
                            history=(),
                            status=self.status,
                            message="err",
                            headers={},
                        )

                async def json(self):
                    return self._payload

            class CM:
                async def __aenter__(self):
                    if "/tags" in url:
                        return Resp([{"label": "Politics", "slug": "politics"}])
                    return Resp(batch)

                async def __aexit__(self, *a):
                    return False

            return CM()

    async def mock_iter(session, *, max_pages=None):
        yield batch

    with patch("bot.standalone_markets._iter_open_market_batches", new=mock_iter):
        markets = await fetch_candidate_markets(
            RecordingSession(),  # type: ignore[arg-type]
            max_end_date_months=6,
            excluded_keywords=frozenset({"politics"}),
            excluded_title_phrases=frozenset(),
        )

    assert markets == []
    assert any("/markets/424242/tags" in u for u in urls)


@pytest.mark.asyncio
async def test_resolve_tag_blob_merges_embedded_with_api():
    """Gamma list payload may omit tags that appear only on /markets/{id}/tags."""

    async def fake_fetch(*_a, **_k):
        return [{"label": "Ukraine", "slug": "ukraine", "id": "1"}]

    market = {
        "id": 99,
        "tags": [{"label": "Politics", "slug": "politics", "id": "2"}],
    }
    sem = asyncio.Semaphore(1)
    with patch.object(standalone_markets, "fetch_market_tags_by_id", side_effect=fake_fetch):
        blob = await standalone_markets._resolve_market_tag_keyword_blob(
            object(), market, tag_fetch_semaphore=sem
        )

    assert "ukraine" in blob
    assert "politics" in blob
