"""Standalone yes/no market discovery shared by scripts and live runtime."""

from __future__ import annotations

import asyncio
import ctypes
import gc
import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp

logger = logging.getLogger(__name__)
try:
    _LIBC = ctypes.CDLL("libc.so.6")
except OSError:
    _LIBC = None

GAMMA_API = "https://gamma-api.polymarket.com"
PAGE_LIMIT = 1000
DEFAULT_MAX_END_DATE_MONTHS = 3
PAGE_DELAY_SEC = 0.2
PAGE_BURST_SIZE = 10
PAGE_BURST_PAUSE_SEC = 2.0
PAGE_MAX_RETRIES = 8
PAGE_RETRY_BASE_DELAY_SEC = 1.0
PAGE_RETRY_MAX_DELAY_SEC = 30.0
GC_COLLECT_INTERVAL_PAGES = 20

class GammaMarketFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class StandaloneMarket:
    question: str
    slug: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    volume: float
    liquidity: float
    min_order_size: float
    end_date: str
    end_ts: float
    category: str
    event_slug: str
    keyword_exclusion_blob: str
    created_at_ts: float = 0.0
    end_date_ts: float = 0.0


@dataclass(frozen=True)
class MarketsByTokensResult:
    """Markets resolved from Gamma by CLOB token id, plus NO tokens skipped as config-excluded."""

    markets: tuple[StandaloneMarket, ...]
    excluded_no_token_ids: frozenset[str]


def _get_event_slug(market: dict) -> str:
    events = market.get("events") or []
    if events and isinstance(events, list):
        return events[0].get("slug", "") if isinstance(events[0], dict) else ""
    return ""


def _load_json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _parse_iso_ts(value: str) -> float:
    if not value:
        return 0.0
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return 0.0
    return dt.timestamp()


def _market_keyword_exclusion_blob(market: dict) -> str:
    """Lowercased text from the same fields as keyword checks in Gamma payloads.

    Used for `StandaloneMarket` so runtime exclusion matches discovery (`is_market_text_excluded`).
    """
    parts: list[str] = []
    tags = market.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = [tags]
    for tag in tags:
        label = (
            (tag.get("label") or tag.get("name") or "").lower()
            if isinstance(tag, dict)
            else str(tag).lower()
        )
        if label:
            parts.append(label)

    for field in (
        "slug",
        "groupItemTitle",
        "category",
        "question",
        "description",
        "title",
    ):
        value = str(market.get(field) or "").lower()
        if value:
            parts.append(value)

    events = market.get("events") or []
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            for fld in ("title", "slug", "subtitle", "description", "name"):
                value = str(event.get(fld) or "").lower()
                if value:
                    parts.append(value)
    return "\n".join(parts)


def _is_excluded_category(market: dict, excluded_keywords: frozenset[str]) -> bool:
    if not excluded_keywords:
        return False
    blob = _market_keyword_exclusion_blob(market)
    for keyword in excluded_keywords:
        if keyword in blob:
            return True
    return False


def _is_binary_yes_no(market: dict) -> bool:
    outcomes = _load_json_list(market.get("outcomes"))
    if len(outcomes) != 2:
        return False
    labels = {str(outcome).strip().lower() for outcome in outcomes}
    return labels == {"yes", "no"}


def _has_excluded_title_phrase(market: dict, excluded_title_phrases: frozenset[str]) -> bool:
    if not excluded_title_phrases:
        return False
    for field in ("question", "groupItemTitle", "title"):
        value = str(market.get(field) or "").lower()
        if any(phrase in value for phrase in excluded_title_phrases):
            return True
    return False


def is_market_text_excluded(
    market: dict,
    *,
    excluded_keywords: frozenset[str],
    excluded_title_phrases: frozenset[str],
) -> bool:
    """True when market text matches excluded_keywords or excluded_title_phrases."""
    if _has_excluded_title_phrase(market, excluded_title_phrases):
        return True
    if _is_excluded_category(market, excluded_keywords):
        return True
    return False


def standalone_market_matches_text_exclusions(
    market: StandaloneMarket,
    *,
    excluded_keywords: frozenset[str],
    excluded_title_phrases: frozenset[str],
) -> bool:
    """Same exclusion rules as `is_market_text_excluded`, using fields on ``StandaloneMarket``."""
    if not excluded_keywords and not excluded_title_phrases:
        return False
    title_phrase_blob = "\n".join(
        part.lower() for part in (market.question, market.category) if part
    )
    for phrase in excluded_title_phrases:
        if phrase in title_phrase_blob:
            return True
    for kw in excluded_keywords:
        if kw in market.keyword_exclusion_blob:
            return True
    return False


def _ends_within_window(market: dict, *, max_end_date_months: int) -> bool:
    end_dt = _parse_iso_ts(market.get("endDate") or market.get("endDateIso") or "")
    if end_dt <= 0:
        return False
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=max_end_date_months * 30)
    end = datetime.fromtimestamp(end_dt, tz=timezone.utc)
    return now <= end <= cutoff


def _is_standalone(market: dict, event_counts: Counter) -> bool:
    if market.get("negRisk"):
        return False
    event_slug = _get_event_slug(market)
    if event_slug and event_counts.get(event_slug, 0) > 1:
        return False
    return True


def _is_sports_market(market: dict) -> bool:
    if market.get("sportsMarketType"):
        return True
    if market.get("gameStartTime"):
        return True
    if str(market.get("feeType") or "").startswith("sports"):
        return True
    events = market.get("events") or []
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and event.get("seriesSlug"):
                return True
    return False


def _passes_candidate_filters(
    market: dict,
    *,
    max_end_date_months: int,
    excluded_keywords: frozenset[str],
    excluded_title_phrases: frozenset[str],
) -> bool:
    if not _is_binary_yes_no(market):
        return False
    if _is_sports_market(market):
        return False
    if is_market_text_excluded(
        market,
        excluded_keywords=excluded_keywords,
        excluded_title_phrases=excluded_title_phrases,
    ):
        return False
    if not _ends_within_window(market, max_end_date_months=max_end_date_months):
        return False
    return True


def _parse_probability_pair(value) -> tuple[float, float]:
    prices = _load_json_list(value)
    if len(prices) < 2:
        return 0.0, 0.0
    try:
        return float(prices[0]), float(prices[1])
    except (TypeError, ValueError):
        return 0.0, 0.0


def _parse_token_pair(market: dict) -> tuple[str, str]:
    token_ids = _load_json_list(market.get("clobTokenIds"))
    outcomes = _load_json_list(market.get("outcomes"))
    if len(token_ids) < 2 or len(outcomes) < 2:
        return "", ""
    yes_token = ""
    no_token = ""
    for index, outcome in enumerate(outcomes):
        label = str(outcome).strip().lower()
        if label == "yes":
            yes_token = str(token_ids[index])
        elif label == "no":
            no_token = str(token_ids[index])
    return yes_token, no_token


def build_standalone_market(market: dict) -> StandaloneMarket | None:
    yes_token_id, no_token_id = _parse_token_pair(market)
    if not yes_token_id or not no_token_id:
        return None
    yes_price, no_price = _parse_probability_pair(market.get("outcomePrices"))
    end_date = str(market.get("endDate") or market.get("endDateIso") or "")
    created_raw = str(
        market.get("createdAt")
        or market.get("created_at")
        or market.get("createdTime")
        or market.get("created")
        or ""
    )
    return StandaloneMarket(
        question=str(market.get("question") or market.get("title") or ""),
        slug=str(market.get("slug") or ""),
        condition_id=str(market.get("conditionId") or ""),
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        yes_price=yes_price,
        no_price=no_price,
        volume=float(market.get("volume") or 0.0),
        liquidity=float(market.get("liquidity") or 0.0),
        min_order_size=float(market.get("orderMinSize") or 0.0),
        end_date=end_date,
        end_ts=_parse_iso_ts(end_date),
        category=str(market.get("groupItemTitle") or market.get("category") or ""),
        event_slug=_get_event_slug(market),
        keyword_exclusion_blob=_market_keyword_exclusion_blob(market),
        created_at_ts=_parse_iso_ts(created_raw),
        end_date_ts=_parse_iso_ts(end_date),
    )


async def fetch_all_open_markets(session: aiohttp.ClientSession) -> list[dict]:
    all_markets: list[dict] = []
    pages_processed = 0
    async for batch in _iter_open_market_batches(session):
        all_markets.extend(batch)
        pages_processed += 1
        _maybe_collect_gc(pages_processed)
    return all_markets


def _parse_retry_after_seconds(headers) -> float | None:
    if not headers:
        return None
    try:
        raw = headers.get("Retry-After")
    except AttributeError:
        raw = None
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


async def _iter_open_market_batches(session: aiohttp.ClientSession):
    offset = 0
    pages_in_burst = 0
    retries = 0
    while True:
        params = {
            "active": "true",
            "closed": "false",
            "limit": str(PAGE_LIMIT),
            "offset": str(offset),
        }
        try:
            async with session.get(
                f"{GAMMA_API}/markets",
                params=params,
                headers={"User-Agent": "polymarket-scanner/1.0"},
                timeout=15.0,
            ) as resp:
                resp.raise_for_status()
                batch = await resp.json()
        except aiohttp.ClientResponseError as exc:
            if exc.status in (429, 500, 502, 503, 504) and retries < PAGE_MAX_RETRIES:
                retry_after = _parse_retry_after_seconds(exc.headers)
                delay = retry_after if retry_after is not None else min(
                    PAGE_RETRY_BASE_DELAY_SEC * (2 ** retries),
                    PAGE_RETRY_MAX_DELAY_SEC,
                )
                retries += 1
                logger.warning(
                    "gamma_markets_rate_limited_or_error offset=%d status=%s retry=%d delay=%.2f",
                    offset,
                    exc.status,
                    retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            logger.warning(
                "gamma_markets_fetch_aborted offset=%d status=%s err=%s",
                offset,
                exc.status,
                exc,
            )
            raise GammaMarketFetchError(f"gamma_markets_fetch_aborted offset={offset} status={exc.status}") from exc
        except aiohttp.ClientError as exc:
            logger.warning("gamma_markets_fetch_failed offset=%d err=%s", offset, exc)
            raise GammaMarketFetchError("gamma_markets_fetch_failed") from exc
        except asyncio.TimeoutError as exc:
            logger.warning("gamma_markets_fetch_timeout offset=%d", offset)
            if retries < PAGE_MAX_RETRIES:
                delay = min(
                    PAGE_RETRY_BASE_DELAY_SEC * (2 ** retries),
                    PAGE_RETRY_MAX_DELAY_SEC,
                )
                retries += 1
                await asyncio.sleep(delay)
                continue
            raise GammaMarketFetchError("gamma_markets_fetch_timeout") from exc

        retries = 0
        if not isinstance(batch, list) or not batch:
            return

        yield batch

        offset += len(batch)
        pages_in_burst += 1
        if len(batch) < PAGE_LIMIT:
            return
        await asyncio.sleep(PAGE_DELAY_SEC)
        if pages_in_burst >= PAGE_BURST_SIZE:
            await asyncio.sleep(PAGE_BURST_PAUSE_SEC)
            pages_in_burst = 0


def _maybe_collect_gc(pages_processed: int) -> None:
    if pages_processed > 0 and pages_processed % GC_COLLECT_INTERVAL_PAGES == 0:
        gc.collect()
        _trim_process_memory()


def _trim_process_memory() -> None:
    if _LIBC is None:
        return
    try:
        _LIBC.malloc_trim(0)
    except AttributeError:
        return


def filter_standalone_markets(
    raw_markets: list[dict],
    *,
    max_end_date_months: int = DEFAULT_MAX_END_DATE_MONTHS,
    excluded_keywords: frozenset[str] = frozenset(),
    excluded_title_phrases: frozenset[str] = frozenset(),
) -> list[dict]:
    event_counts: Counter = Counter()
    for market in raw_markets:
        slug = _get_event_slug(market)
        if slug:
            event_counts[slug] += 1
    return filter_standalone_markets_with_event_counts(
        raw_markets,
        event_counts=event_counts,
        max_end_date_months=max_end_date_months,
        excluded_keywords=excluded_keywords,
        excluded_title_phrases=excluded_title_phrases,
    )


def filter_standalone_markets_with_event_counts(
    raw_markets: list[dict],
    *,
    event_counts: Counter,
    max_end_date_months: int = DEFAULT_MAX_END_DATE_MONTHS,
    excluded_keywords: frozenset[str] = frozenset(),
    excluded_title_phrases: frozenset[str] = frozenset(),
) -> list[dict]:
    kept: list[dict] = []
    for market in raw_markets:
        if not _passes_candidate_filters(
            market,
            max_end_date_months=max_end_date_months,
            excluded_keywords=excluded_keywords,
            excluded_title_phrases=excluded_title_phrases,
        ):
            continue
        if not _is_standalone(market, event_counts):
            continue
        kept.append(market)
    return kept


async def fetch_candidate_markets(
    session: aiohttp.ClientSession,
    *,
    max_end_date_months: int = DEFAULT_MAX_END_DATE_MONTHS,
    excluded_keywords: frozenset[str] = frozenset(),
    excluded_title_phrases: frozenset[str] = frozenset(),
) -> list[StandaloneMarket]:
    markets: list[StandaloneMarket] = []
    standalone_candidates: dict[str, StandaloneMarket] = {}
    standalone_no_event: list[StandaloneMarket] = []
    event_counts: Counter = Counter()
    pages_processed = 0
    async for batch in _iter_open_market_batches(session):
        for raw_market in batch:
            event_slug = _get_event_slug(raw_market)
            if event_slug:
                event_counts[event_slug] += 1

            if not _passes_candidate_filters(
                raw_market,
                max_end_date_months=max_end_date_months,
                excluded_keywords=excluded_keywords,
                excluded_title_phrases=excluded_title_phrases,
            ):
                continue
            if raw_market.get("negRisk"):
                continue

            market = build_standalone_market(raw_market)
            if market is None:
                continue

            if not event_slug:
                standalone_no_event.append(market)
                continue

            if event_counts[event_slug] == 1:
                standalone_candidates[event_slug] = market
                continue

            standalone_candidates.pop(event_slug, None)
        pages_processed += 1
        _maybe_collect_gc(pages_processed)
        del batch
    markets.extend(standalone_no_event)
    markets.extend(standalone_candidates.values())
    markets.sort(key=lambda market: market.volume, reverse=True)
    gc.collect()
    _trim_process_memory()
    return markets


def _raw_market_contains_clob_token(raw_market: dict, token_id: str) -> bool:
    tid = str(token_id).strip()
    if not tid:
        return False
    for entry in _load_json_list(raw_market.get("clobTokenIds")):
        if str(entry).strip() == tid:
            return True
    return False


async def fetch_markets_by_token_ids(
    session: aiohttp.ClientSession,
    token_ids: list[str],
    *,
    excluded_keywords: frozenset[str] = frozenset(),
    excluded_title_phrases: frozenset[str] = frozenset(),
) -> MarketsByTokensResult:
    if not token_ids:
        return MarketsByTokensResult(markets=tuple(), excluded_no_token_ids=frozenset())

    markets: list[StandaloneMarket] = []
    excluded_no: set[str] = set()
    seen_no_tokens: set[str] = set()

    # Gamma expects ``clob_token_ids`` (snake_case). The camelCase param is ignored and
    # returns an arbitrary market, which breaks open-order recovery and exclusions.
    for token_id in token_ids:
        retries = 0
        raw_match: dict | None = None
        while retries < PAGE_MAX_RETRIES:
            try:
                async with session.get(
                    f"{GAMMA_API}/markets",
                    params={"clob_token_ids": str(token_id).strip()},
                    headers={"User-Agent": "polymarket-scanner/1.0"},
                    timeout=15.0,
                ) as resp:
                    resp.raise_for_status()
                    batch = await resp.json()

                if isinstance(batch, list):
                    for raw_market in batch:
                        if isinstance(raw_market, dict) and _raw_market_contains_clob_token(
                            raw_market, token_id
                        ):
                            raw_match = raw_market
                            break
                if raw_match is None:
                    logger.warning(
                        "gamma_markets_by_token_unresolved token_prefix=%s batch_len=%s",
                        str(token_id)[:16],
                        len(batch) if isinstance(batch, list) else type(batch).__name__,
                    )
                break

            except aiohttp.ClientResponseError as exc:
                if exc.status == 429:
                    retry_after = _parse_retry_after_seconds(exc.headers)
                    delay = retry_after if retry_after is not None else min(
                        PAGE_RETRY_BASE_DELAY_SEC * (2**retries),
                        PAGE_RETRY_MAX_DELAY_SEC,
                    )
                    retries += 1
                    logger.warning(
                        "gamma_markets_by_token_rate_limited retry=%d delay=%.2f", retries, delay
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.warning("gamma_markets_by_token_aborted status=%s err=%s", exc.status, exc)
                break
            except asyncio.TimeoutError:
                logger.warning("gamma_markets_by_token_timeout token_prefix=%s", str(token_id)[:16])
                retries += 1
                await asyncio.sleep(1.0)
                continue
            except Exception as exc:
                logger.warning(
                    "gamma_markets_by_token_failed token_prefix=%s err=%s",
                    str(token_id)[:16],
                    exc,
                )
                break

        if raw_match is None:
            continue

        _, no_tid = _parse_token_pair(raw_match)
        if (
            excluded_keywords or excluded_title_phrases
        ) and is_market_text_excluded(
            raw_match,
            excluded_keywords=excluded_keywords,
            excluded_title_phrases=excluded_title_phrases,
        ):
            # Use the requested token so callers can cancel via ``missing_tokens[token_id]``.
            excluded_no.add(str(token_id).strip())
            if no_tid and no_tid != str(token_id).strip():
                excluded_no.add(no_tid)
            logger.info(
                "gamma_markets_by_token_skip_excluded slug=%s",
                raw_match.get("slug") or "",
            )
            continue

        market = build_standalone_market(raw_match)
        if market is None or not market.no_token_id:
            logger.warning(
                "gamma_markets_by_token_build_failed slug=%s",
                raw_match.get("slug") or "",
            )
            continue
        if market.no_token_id in seen_no_tokens:
            continue
        seen_no_tokens.add(market.no_token_id)
        markets.append(market)

    return MarketsByTokensResult(
        markets=tuple(markets),
        excluded_no_token_ids=frozenset(excluded_no),
    )
