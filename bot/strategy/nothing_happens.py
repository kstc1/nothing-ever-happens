"""Multi-market 'nothing ever happens' strategy."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from concurrent.futures import Executor
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from types import SimpleNamespace

import aiohttp

from bot.config import NothingHappensConfig
from bot.models import LimitOrderIntent, OrderBookSnapshot, Side
from bot.nothing_happens_control import NothingHappensControlState
from bot.order_status import normalize_order_status
from bot.portfolio_state import PortfolioState, PositionSnapshot
from bot.standalone_markets import StandaloneMarket, fetch_candidate_markets, fetch_markets_by_token_ids
from bot.trade_ledger import record_order

logger = logging.getLogger(__name__)

LIMIT_ORDER_POLL_INTERVAL_SEC = 30

DATA_API_BASE = "https://data-api.polymarket.com"
POSITIONS_ENDPOINT = f"{DATA_API_BASE}/positions"
BALANCE_DUST_THRESHOLD = 0.01
POSITION_GRACE_SEC = 300.0
POSITIONS_FETCH_TIMEOUT_SEC = 30.0
POSITIONS_PAGE_LIMIT = 100
SUCCESS_ORDER_STATUSES = {"matched", "filled", "simulated"}
CLEAN_NO_FILL_ORDER_STATUSES = {"unmatched", "rejected", "cancelled", "failed"}
DEFINITIVE_NO_FILL_FRAGMENTS = {
    "no orders found to match",
    "fak orders are partially filled or killed",
    "couldn't be fully filled",
    "fok orders are fully filled or killed",
    "not enough balance",
    "not enough allowance",
    "market is not yet ready",
    "minimum tick size",
    "lower than the minimum",
    "invalid post-only order",
    "order crosses the book",
    "duplicated",
    "invalid nonce",
    "invalid expiration",
    "canceled in the ctf exchange",
    "trading is currently disabled",
    "cancel-only",
    "address banned",
    "closed only mode",
}


@dataclass
class LocalPosition:
    slug: str
    title: str
    outcome: str
    asset: str
    condition_id: str
    size: float
    avg_price: float
    initial_value: float
    current_price: float
    current_value: float
    end_date: str
    end_ts: float
    source: str
    created_at_ts: float


@dataclass
class PriceBackoff:
    failures: int = 0
    next_check_monotonic: float = 0.0


@dataclass
class PendingEntry:
    market: StandaloneMarket
    enqueued_at_ts: float
    next_attempt_monotonic: float
    dispatch_failures: int = 0
    last_error: str = ""
    order_id: str = ""
    order_placed_at_ts: float = 0.0
    last_partial_fill_reported: float = 0.0


@dataclass(frozen=True)
class EntryPlan:
    entry_price: float
    target_notional: float


@dataclass(frozen=True)
class EntryAttemptResult:
    success: bool
    error: str = ""
    min_retry_delay_sec: float | None = None
    open_limit_pending: bool = False


async def _run_blocking(executor: Executor | None, fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, partial(fn, *args, **kwargs))


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_success_order_status(status: str | None) -> bool:
    return normalize_order_status(status or "") in SUCCESS_ORDER_STATUSES


def _is_clean_no_fill_order_status(status: str | None) -> bool:
    return normalize_order_status(status or "") in CLEAN_NO_FILL_ORDER_STATUSES


def _is_definitive_no_fill_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(fragment in msg for fragment in DEFINITIVE_NO_FILL_FRAGMENTS)


def _best_ask(book: OrderBookSnapshot) -> float:
    return min((level.price for level in book.asks), default=0.0)


def _best_bid(book: OrderBookSnapshot) -> float:
    return max((level.price for level in book.bids), default=0.0)


def _bid_depth_notional(book: OrderBookSnapshot) -> float:
    """Total USD notional resting on the bid side (price * size per level)."""
    return sum(level.size * level.price for level in book.bids)


def _clamp_probability(price: float) -> float:
    return max(0.01, min(0.99, float(price)))


def _eta_seconds(end_ts: float) -> float:
    if end_ts <= 0:
        return 0.0
    return max(0.0, end_ts - time.time())


def _position_snapshot_from_local(position: LocalPosition) -> PositionSnapshot:
    pnl_usd = position.current_value - position.initial_value
    pnl_pct = (pnl_usd / position.initial_value * 100.0) if position.initial_value > 0 else 0.0
    return PositionSnapshot(
        slug=position.slug,
        title=position.title,
        outcome=position.outcome,
        asset=position.asset,
        condition_id=position.condition_id,
        size=position.size,
        avg_price=position.avg_price,
        initial_value=position.initial_value,
        current_price=position.current_price,
        current_value=position.current_value,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        end_date=position.end_date,
        eta_seconds=_eta_seconds(position.end_ts),
        source=position.source,
    )


def _position_snapshot_from_api(position: dict, market: StandaloneMarket | None) -> PositionSnapshot:
    title = str(position.get("title") or (market.question if market is not None else ""))
    end_date = str(position.get("endDate") or (market.end_date if market is not None else ""))
    if market is not None:
        end_ts = market.end_ts
    elif end_date:
        try:
            end_ts = datetime.fromisoformat(end_date.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            end_ts = 0.0
    else:
        end_ts = 0.0
    return PositionSnapshot(
        slug=str(position.get("slug") or ""),
        title=title,
        outcome=str(position.get("outcome") or ""),
        asset=str(position.get("asset") or ""),
        condition_id=str(position.get("conditionId") or (market.condition_id if market is not None else "")),
        size=_safe_float(position.get("size")),
        avg_price=_safe_float(position.get("avgPrice")),
        initial_value=_safe_float(position.get("initialValue")),
        current_price=_safe_float(position.get("curPrice")),
        current_value=_safe_float(position.get("currentValue")),
        pnl_usd=_safe_float(position.get("cashPnl")),
        pnl_pct=_safe_float(position.get("percentPnl")),
        end_date=end_date,
        eta_seconds=_eta_seconds(end_ts),
        source="data_api",
    )


def _extract_positions_payload(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if "data" in payload and isinstance(payload.get("data"), list):
            return [item for item in payload["data"] if isinstance(item, dict)]
        if "positions" in payload and isinstance(payload.get("positions"), list):
            return [item for item in payload["positions"] if isinstance(item, dict)]
        raise ValueError("positions response missing data/positions list")
    raise ValueError("unexpected positions response payload")


async def _fetch_open_positions(
    session: aiohttp.ClientSession,
    wallet_address: str,
) -> list[dict]:
    all_positions: list[dict] = []
    offset = 0
    timeout = aiohttp.ClientTimeout(total=POSITIONS_FETCH_TIMEOUT_SEC)
    while True:
        async with session.get(
            POSITIONS_ENDPOINT,
            params={
                "user": wallet_address,
                "redeemable": "false",
                "sizeThreshold": "0",
                "limit": str(POSITIONS_PAGE_LIMIT),
                "offset": str(offset),
            },
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            payload = await resp.json()
        page = _extract_positions_payload(payload)
        all_positions.extend(page)
        if len(page) < POSITIONS_PAGE_LIMIT:
            return all_positions
        offset += len(page)


class NothingHappensRuntime:
    def __init__(
        self,
        *,
        exchange,
        session: aiohttp.ClientSession,
        cfg: NothingHappensConfig,
        risk,
        background_executor: Executor | None,
        shutdown_event: asyncio.Event,
        portfolio_state: PortfolioState | None,
        control_state: NothingHappensControlState | None,
        recovery_coordinator=None,
        wallet_address: str | None,
    ) -> None:
        self.exchange = exchange
        self.session = session
        self.cfg = cfg
        self.risk = risk
        self.background_executor = background_executor
        self.shutdown_event = shutdown_event
        self.portfolio_state = portfolio_state
        self.control_state = control_state
        self.recovery_coordinator = recovery_coordinator
        self.wallet_address = wallet_address

        self._markets_by_slug: dict[str, StandaloneMarket] = {}
        self._positions_by_slug: dict[str, PositionSnapshot] = {}
        self._local_positions: dict[str, LocalPosition] = {}
        self._price_backoff: dict[str, PriceBackoff] = {}
        self._pending_entries_by_slug: dict[str, PendingEntry] = {}
        self._recovery_blocked_slugs: set[str] = set()
        self._ambiguous_reserved_notional_by_slug: dict[str, float] = {}
        self._market_in_range_by_slug: dict[str, bool] = {}
        self._cash_balance: float | None = None
        self._last_market_refresh_ts: float = 0.0
        self._last_position_sync_ts: float = 0.0
        self._last_price_cycle_ts: float = 0.0
        self._last_error: str = ""
        self._remote_positions_ready: bool = wallet_address is None
        self._opened_position_count: int = 0
        self._target_open_positions: int | None = None
        self._auto_target_baseline_open_positions: int = 0
        self._book_semaphore = asyncio.Semaphore(max(1, int(cfg.request_concurrency)))
        self._entry_lock = asyncio.Lock()

    async def run(self) -> None:
        await self._refresh_markets()
        await self._sync_positions()
        await self._sync_open_orders()
        self._initialize_target_open_positions()
        self._publish_portfolio()

        tasks = [
            asyncio.create_task(self._market_refresh_loop(), name="nh_market_refresh"),
            asyncio.create_task(self._position_sync_loop(), name="nh_position_sync"),
            asyncio.create_task(self._price_loop(), name="nh_price_loop"),
            asyncio.create_task(self._order_dispatch_loop(), name="nh_order_dispatch"),
            asyncio.create_task(self._open_order_poll_loop(), name="nh_order_poll"),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _default_target_open_positions(self) -> int | None:
        if self.cfg.max_new_positions < 0:
            return None
        baseline_open_positions = max(0, len(self._positions_by_slug) - self._opened_position_count)
        self._auto_target_baseline_open_positions = max(
            self._auto_target_baseline_open_positions,
            baseline_open_positions,
        )
        return self._auto_target_baseline_open_positions + self.cfg.max_new_positions

    def _initialize_target_open_positions(self) -> int | None:
        default_target = self._default_target_open_positions()
        if self.control_state is not None:
            return self.control_state.ensure_target_open_positions(default_target).target_open_positions
        if self._target_open_positions != default_target:
            self._target_open_positions = default_target
        return self._target_open_positions

    def _current_target_open_positions(self) -> int | None:
        if self.control_state is not None:
            snapshot = self.control_state.snapshot()
            if snapshot.target_open_positions is not None:
                return snapshot.target_open_positions
        return self._initialize_target_open_positions()

    def _uses_manual_target_override(self) -> bool:
        return self.control_state is not None and self.control_state.is_target_user_override()

    def _remaining_new_entry_capacity(self) -> int | None:
        if self._uses_manual_target_override() or self.cfg.max_new_positions < 0:
            return None
        return max(
            0,
            self.cfg.max_new_positions
            - self._opened_position_count
            - len(self._pending_entries_by_slug)
            - len(self._recovery_blocked_slugs),
        )

    def _remaining_queue_capacity(self) -> int | None:
        capacities: list[int] = []
        target = self._current_target_open_positions()
        if target is not None:
            capacities.append(
                max(
                    0,
                    target
                    - len(self._positions_by_slug)
                    - len(self._pending_entries_by_slug)
                    - len(self._recovery_blocked_slugs),
                )
            )
        new_entry_capacity = self._remaining_new_entry_capacity()
        if new_entry_capacity is not None:
            capacities.append(new_entry_capacity)
        if not capacities:
            return None
        return min(capacities)

    def _eligible_markets(self) -> list[StandaloneMarket]:
        position_slugs = set(self._positions_by_slug)
        pending_slugs = set(self._pending_entries_by_slug)
        blocked_slugs = set(self._recovery_blocked_slugs)
        now_ts = time.time()
        return [
            market
            for market in self._markets_by_slug.values()
            if market.slug not in position_slugs
            and market.slug not in pending_slugs
            and market.slug not in blocked_slugs
            and market.end_ts > now_ts
        ]

    def _in_range_market_count(self, eligible_markets: list[StandaloneMarket]) -> int:
        return sum(1 for market in eligible_markets if self._market_in_range_by_slug.get(market.slug, False))

    def _position_target_reached(self) -> bool:
        new_entry_capacity = self._remaining_new_entry_capacity()
        if new_entry_capacity is not None and new_entry_capacity <= 0:
            return True
        target = self._current_target_open_positions()
        return target is not None and (len(self._positions_by_slug) + len(self._recovery_blocked_slugs)) >= target

    async def _sleep_or_shutdown(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self.shutdown_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return

    def _market_in_entry_window(self, market: StandaloneMarket) -> bool:
        """Return True if market age and time-to-resolution satisfy lifecycle config."""
        now = time.time()

        if market.created_at_ts > 0.0:
            age_sec = now - market.created_at_ts
            if age_sec < self.cfg.min_market_age_sec:
                logger.debug(
                    "lifecycle_gate_skip_too_new slug=%s age_sec=%.0f min=%.0f",
                    market.slug,
                    age_sec,
                    self.cfg.min_market_age_sec,
                )
                return False
            if not math.isinf(self.cfg.max_market_age_sec) and age_sec > self.cfg.max_market_age_sec:
                logger.debug(
                    "lifecycle_gate_skip_too_old slug=%s age_sec=%.0f max=%.0f",
                    market.slug,
                    age_sec,
                    self.cfg.max_market_age_sec,
                )
                return False

        if market.end_date_ts > 0.0:
            remaining_sec = market.end_date_ts - now
            if remaining_sec < self.cfg.min_time_remaining_sec:
                logger.debug(
                    "lifecycle_gate_skip_expiring slug=%s remaining_sec=%.0f min=%.0f",
                    market.slug,
                    remaining_sec,
                    self.cfg.min_time_remaining_sec,
                )
                return False

        if market.created_at_ts > 0.0 and market.end_date_ts > 0.0:
            lifespan_sec = market.end_date_ts - market.created_at_ts
            if lifespan_sec > 0:
                age_sec = now - market.created_at_ts
                age_pct = age_sec / lifespan_sec
                if age_pct < self.cfg.min_market_age_pct:
                    logger.debug(
                        "lifecycle_gate_skip_too_new_pct slug=%s age_pct=%.3f min_pct=%.3f",
                        market.slug,
                        age_pct,
                        self.cfg.min_market_age_pct,
                    )
                    return False
                if age_pct > self.cfg.max_market_age_pct:
                    logger.debug(
                        "lifecycle_gate_skip_too_old_pct slug=%s age_pct=%.3f max_pct=%.3f",
                        market.slug,
                        age_pct,
                        self.cfg.max_market_age_pct,
                    )
                    return False

        if market.created_at_ts == 0.0:
            logger.debug("lifecycle_gate_no_created_at slug=%s — age check skipped", market.slug)
        if market.end_date_ts == 0.0:
            logger.debug("lifecycle_gate_no_end_date slug=%s — remaining-time check skipped", market.slug)

        return True

    async def _market_refresh_loop(self) -> None:
        while not self.shutdown_event.is_set():
            await self._refresh_markets()
            await self._sleep_or_shutdown(self.cfg.market_refresh_interval_sec)

    async def _position_sync_loop(self) -> None:
        while not self.shutdown_event.is_set():
            await self._sync_positions()
            await self._sleep_or_shutdown(self.cfg.position_sync_interval_sec)

    async def _price_loop(self) -> None:
        while not self.shutdown_event.is_set():
            cycle_started = time.time()
            try:
                await self._run_price_cycle()
                self._last_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("nothing_happens_price_cycle_failed")
            self._last_price_cycle_ts = cycle_started
            self._publish_portfolio()
            elapsed = time.time() - cycle_started
            await self._sleep_or_shutdown(max(0.0, self.cfg.price_poll_interval_sec - elapsed))

    async def _order_dispatch_loop(self) -> None:
        # idle_poll_sec: sleep between scans when there is nothing to dispatch
        idle_poll_sec = min(5.0, max(1.0, self.cfg.order_dispatch_interval_sec / 6.0))
        # fast_dispatch_sec: sleep between successive dispatches when a queue
        # of unsubmitted pending entries is building up, so new markets are
        # entered quickly rather than at most once per order_dispatch_interval_sec.
        fast_dispatch_sec = min(2.0, self.cfg.order_dispatch_interval_sec)
        while not self.shutdown_event.is_set():
            cycle_started = time.time()
            attempted_order = False
            try:
                attempted_order = await self._dispatch_next_pending_entry()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("nothing_happens_order_dispatch_failed")
            self._publish_portfolio()
            elapsed = time.time() - cycle_started

            # Count entries that are queued but have not yet been submitted to
            # the exchange (no order_id). When the queue is non-empty we use
            # the fast interval so the backlog clears in seconds, not minutes.
            unsubmitted = sum(
                1 for p in self._pending_entries_by_slug.values() if not p.order_id
            )
            if attempted_order and unsubmitted > 0:
                sleep_for = max(0.0, fast_dispatch_sec - elapsed)
            elif attempted_order:
                sleep_for = max(0.0, self.cfg.order_dispatch_interval_sec - elapsed)
            else:
                sleep_for = idle_poll_sec
            await self._sleep_or_shutdown(sleep_for)

    async def _open_order_poll_loop(self) -> None:
        """Poll pending GTC limit orders; confirm fills or cancel stale orders."""
        loops = 0
        while not self.shutdown_event.is_set():
            try:
                if loops % 4 == 0:
                    await self._sync_open_orders()
                loops += 1
                await self._poll_open_limit_orders()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("nothing_happens_poll_loop_failed err=%s", exc)
            await self._sleep_or_shutdown(LIMIT_ORDER_POLL_INTERVAL_SEC)

    async def _poll_open_limit_orders(self) -> None:
        """Poll all tracked GTC limit orders using a single bulk API call.

        One call to get_all_open_orders() replaces N individual get_order()
        calls, staying well within the rate limit budget. Orders that have
        disappeared from the open-orders list (filled or cancelled) receive a
        single targeted get_order() call to confirm their final status.
        """
        now_ts = time.time()

        # Build lookup of order_id -> (slug, pending) for every tracked order.
        tracked: dict[str, tuple[str, PendingEntry]] = {
            pending.order_id: (slug, pending)
            for slug, pending in list(self._pending_entries_by_slug.items())
            if pending.order_id
        }
        if not tracked:
            return

        # Single bulk fetch: 1 API call regardless of how many orders we track.
        try:
            all_open = await asyncio.wait_for(
                _run_blocking(self.background_executor, self.exchange.get_all_open_orders),
                timeout=20.0,
            )
        except Exception as exc:
            logger.warning("limit_order_bulk_poll_failed err=%s", exc)
            return

        open_by_id = {o.order_id: o for o in all_open}
        logger.debug(
            "limit_order_bulk_poll tracked=%d exchange_open=%d",
            len(tracked),
            len(all_open),
        )

        for order_id, (slug, pending) in tracked.items():
            order = open_by_id.get(order_id)

            if order is None:
                # Not in open orders — likely filled or cancelled.
                # Do one targeted lookup to get the final status.
                try:
                    order = await asyncio.wait_for(
                        _run_blocking(self.background_executor, self.exchange.get_order, order_id),
                        timeout=10.0,
                    )
                except Exception as exc:
                    logger.warning(
                        "limit_order_poll_failed slug=%s order_id=%s err=%s",
                        slug,
                        order_id,
                        exc,
                    )
                    continue

            if order is None:
                continue

            status = normalize_order_status(order.status or "")

            if status in {"cancelled", "canceled", "rejected", "failed"}:
                self._pending_entries_by_slug.pop(slug, None)
                logger.info("limit_order_closed slug=%s status=%s order_id=%s", slug, status, order_id)
                continue

            if status in {"matched", "filled"}:
                market = self._markets_by_slug.get(slug, pending.market)
                fill_price = order.price
                size = (
                    order.size_matched
                    if order.size_matched is not None
                    else (order.original_size or 0.0)
                )
                spent = fill_price * size if fill_price and size else 0.0
                async with self._entry_lock:
                    self._record_local_fill(
                        market=market,
                        size=size,
                        avg_price=fill_price,
                        initial_value=spent,
                        current_price=fill_price,
                        source="limit_fill",
                    )
                    record_order(
                        action="buy",
                        market_slug=slug,
                        side="NO",
                        token_id=market.no_token_id,
                        amount=spent,
                        reference_price=fill_price,
                        order_id=order_id,
                        order_status=status,
                        question=market.question,
                        shares=size,
                    )
                    self._pending_entries_by_slug.pop(slug, None)
                logger.info(
                    "limit_order_filled slug=%s price=%.4f size=%.4f",
                    slug,
                    fill_price,
                    size,
                )
                continue

            if order.size_matched is not None and order.size_matched > BALANCE_DUST_THRESHOLD:
                market = self._markets_by_slug.get(slug, pending.market)
                fill_price = order.price
                total_matched = order.size_matched
                delta = total_matched - pending.last_partial_fill_reported
                if delta > BALANCE_DUST_THRESHOLD:
                    size = delta
                    spent = fill_price * size if fill_price and size else 0.0
                    async with self._entry_lock:
                        self._record_local_fill(
                            market=market,
                            size=size,
                            avg_price=fill_price,
                            initial_value=spent,
                            current_price=fill_price,
                            source="limit_partial_fill",
                        )
                        record_order(
                            action="buy",
                            market_slug=slug,
                            side="NO",
                            token_id=market.no_token_id,
                            amount=spent,
                            reference_price=fill_price,
                            order_id=order_id,
                            order_status="partial",
                            question=market.question,
                            shares=size,
                        )
                        pending.last_partial_fill_reported = total_matched
                    logger.info(
                        "limit_order_partial_fill slug=%s price=%.4f size=%.4f",
                        slug,
                        fill_price,
                        size,
                    )
                continue

            if pending.order_placed_at_ts and (now_ts - pending.order_placed_at_ts) > self.cfg.limit_order_max_age_sec:
                cancel_success = False
                try:
                    cancel_success = await asyncio.wait_for(
                        _run_blocking(
                            self.background_executor,
                            self.exchange.cancel_order,
                            order_id,
                        ),
                        timeout=10.0,
                    )
                except Exception as exc:
                    logger.warning("limit_order_cancel_failed slug=%s err=%s", slug, exc)

                if cancel_success:
                    self._pending_entries_by_slug.pop(slug, None)
                    logger.info(
                        "limit_order_cancelled_stale slug=%s order_id=%s",
                        slug,
                        order_id,
                    )
                else:
                    logger.warning(
                        "limit_order_cancel_api_failed slug=%s order_id=%s - keeping in pending to avoid duplicates",
                        slug,
                        order_id,
                    )

    async def _refresh_markets(self) -> None:
        try:
            markets = await fetch_candidate_markets(
                self.session,
                excluded_keywords=self.cfg.excluded_keywords,
                excluded_title_phrases=self.cfg.excluded_title_phrases,
            )
        except Exception as exc:
            self._last_error = f"markets_refresh_failed: {exc}"
            logger.warning("nothing_happens_markets_refresh_failed: %s", exc)
            self._publish_portfolio()
            return
        previous = set(self._markets_by_slug)
        self._markets_by_slug = {market.slug: market for market in markets}
        self._market_in_range_by_slug = {
            slug: value
            for slug, value in self._market_in_range_by_slug.items()
            if slug in self._markets_by_slug
        }
        for slug, pending in list(self._pending_entries_by_slug.items()):
            if slug not in self._markets_by_slug:
                # Only drop pending entries if an order hasn't been placed yet.
                # If an order is already live, we must not forget it even if the Gamma API drops the market.
                if not pending.order_id:
                    self._pending_entries_by_slug.pop(slug, None)
        self._last_market_refresh_ts = time.time()
        new_slugs = sorted(set(self._markets_by_slug) - previous)
        if new_slugs:
            logger.info(
                "nothing_happens_markets_added",
                extra={"count": len(new_slugs), "sample": new_slugs[:10]},
            )
        logger.info(
            "nothing_happens_markets_refreshed",
            extra={"count": len(markets), "timestamp": self._last_market_refresh_ts},
        )
        self._publish_portfolio()

    async def _sync_open_orders(self) -> None:
        """Fetch all existing open orders on startup to avoid duplicating them."""
        try:
            if not hasattr(self.exchange, "get_all_open_orders"):
                return
            open_orders = await asyncio.wait_for(
                _run_blocking(self.background_executor, self.exchange.get_all_open_orders),
                timeout=20.0,
            )
            recovered_count = 0
            missing_tokens = {}
            for order in open_orders:
                status = normalize_order_status(order.status or "")
                if status not in {"open", "matched", "live", "active", "resting"}:
                    continue
                # Find matching market
                found = False
                for slug, market in self._markets_by_slug.items():
                    if market.no_token_id == order.token_id:
                        found = True
                        if slug not in self._pending_entries_by_slug:
                            self._pending_entries_by_slug[slug] = PendingEntry(
                                market=market,
                                enqueued_at_ts=time.time(),
                                next_attempt_monotonic=asyncio.get_running_loop().time(),
                                order_id=order.order_id,
                                order_placed_at_ts=time.time(),
                                last_partial_fill_reported=order.size_matched or 0.0,
                            )
                            recovered_count += 1
                        else:
                            pending = self._pending_entries_by_slug[slug]
                            if not pending.order_id:
                                pending.order_id = order.order_id
                                pending.order_placed_at_ts = time.time()
                                recovered_count += 1
                            elif pending.order_id != order.order_id:
                                logger.warning("duplicate_order_found slug=%s tracked=%s extra=%s - cancelling extra", slug, pending.order_id, order.order_id)
                                self.background_executor.submit(self.exchange.cancel_order, order.order_id)
                        break
                
                if not found:
                    missing_tokens[order.token_id] = order

            if missing_tokens:
                logger.info("fetching_missing_markets_for_open_orders", extra={"missing_count": len(missing_tokens)})
                try:
                    missing_markets = await fetch_markets_by_token_ids(
                        self.session,
                        list(missing_tokens.keys()),
                    )
                    for market in missing_markets:
                        order = missing_tokens.get(market.no_token_id)
                        if not order:
                            continue
                        
                        slug = market.slug
                        self._markets_by_slug[slug] = market
                        if slug not in self._pending_entries_by_slug:
                            self._pending_entries_by_slug[slug] = PendingEntry(
                                market=market,
                                enqueued_at_ts=time.time(),
                                next_attempt_monotonic=asyncio.get_running_loop().time(),
                                order_id=order.order_id,
                                order_placed_at_ts=time.time(),
                                last_partial_fill_reported=order.size_matched or 0.0,
                            )
                            recovered_count += 1
                        else:
                            pending = self._pending_entries_by_slug[slug]
                            if not pending.order_id:
                                pending.order_id = order.order_id
                                pending.order_placed_at_ts = time.time()
                                recovered_count += 1
                            elif pending.order_id != order.order_id:
                                logger.warning("duplicate_order_found slug=%s tracked=%s extra=%s - cancelling extra", slug, pending.order_id, order.order_id)
                                self.background_executor.submit(self.exchange.cancel_order, order.order_id)
                except Exception as exc:
                    logger.warning("failed_to_fetch_missing_markets: %s", exc)

            if recovered_count > 0:
                logger.info(
                    "nothing_happens_recovered_open_orders",
                    extra={"recovered_count": recovered_count},
                )
        except Exception as exc:
            logger.warning("nothing_happens_sync_open_orders_failed: %s", exc)

    async def _sync_positions(self) -> None:
        now_ts = time.time()
        fetched_positions: list[dict] | None = []
        if self.wallet_address:
            try:
                fetched_positions = await _fetch_open_positions(self.session, self.wallet_address)
                self._remote_positions_ready = True
            except Exception as exc:
                fetched_positions = None
                self._last_error = f"positions_fetch_failed: {exc}"
                logger.warning("nothing_happens_positions_fetch_failed: %s", exc)

        if fetched_positions is None:
            positions_by_slug = dict(self._positions_by_slug)
            for slug, overlay in self._local_positions.items():
                positions_by_slug[slug] = _position_snapshot_from_local(overlay)
        else:
            positions_by_slug = {}
            for position in fetched_positions:
                slug = str(position.get("slug") or "")
                if not slug:
                    continue
                positions_by_slug[slug] = _position_snapshot_from_api(
                    position,
                    self._markets_by_slug.get(slug),
                )

            for slug, overlay in list(self._local_positions.items()):
                if slug in positions_by_slug:
                    self._local_positions.pop(slug, None)
                    continue
                if self.wallet_address and (now_ts - overlay.created_at_ts) > POSITION_GRACE_SEC:
                    self._local_positions.pop(slug, None)
                    continue
                positions_by_slug[slug] = _position_snapshot_from_local(overlay)

        self._positions_by_slug = positions_by_slug
        await self._refresh_recovery_state()
        self._initialize_target_open_positions()
        for slug, pending in list(self._pending_entries_by_slug.items()):
            if slug in self._positions_by_slug and not pending.order_id:
                self._pending_entries_by_slug.pop(slug, None)
        self._last_position_sync_ts = now_ts

        try:
            self._cash_balance = await asyncio.wait_for(
                _run_blocking(self.background_executor, self.exchange.get_collateral_balance),
                timeout=20.0,
            )
        except Exception as exc:
            logger.warning("nothing_happens_cash_balance_failed: %s", exc)

        if self._cash_balance is not None:
            self.risk.check_balance_drawdown(
                int(now_ts * 1_000_000),
                self._cash_balance,
            )

        self.risk.open_exposure_by_market = {
            slug: snapshot.initial_value
            for slug, snapshot in self._positions_by_slug.items()
        }
        self.risk.open_exposure_total_usd = sum(self.risk.open_exposure_by_market.values())

        logger.info(
            "nothing_happens_positions_synced",
            extra={
                "open_positions": len(self._positions_by_slug),
                "cash_balance": self._cash_balance,
            },
        )
        self._publish_portfolio()

    async def _run_price_cycle(self) -> None:
        if not self._markets_by_slug:
            return
        if self.wallet_address and not self._remote_positions_ready:
            logger.info("nothing_happens_waiting_for_initial_position_sync")
            return
        if self._remaining_queue_capacity() == 0:
            return

        eligible_markets = self._eligible_markets()
        in_range_markets = self._in_range_market_count(eligible_markets)

        await self._ensure_cash_balance(log_context="cycle")

        due_markets = []
        loop_now = asyncio.get_running_loop().time()
        for market in eligible_markets:
            state = self._price_backoff.get(market.slug)
            if state is None or loop_now >= state.next_check_monotonic:
                due_markets.append(market)

        logger.info(
            "nothing_happens_price_cycle",
            extra={
                "tracked_markets": len(self._markets_by_slug),
                "eligible_markets": len(eligible_markets),
                "in_range_markets": in_range_markets,
                "pending_markets": len(self._pending_entries_by_slug),
                "target_open_positions": self._current_target_open_positions(),
                "remaining_capacity": self._remaining_queue_capacity(),
                "due_markets": len(due_markets),
                "cash_balance": self._cash_balance,
            },
        )

        async def _check_market(market: StandaloneMarket) -> None:
            await self._evaluate_market(market)

        await asyncio.gather(*(_check_market(market) for market in due_markets))
        in_range_markets = self._in_range_market_count(eligible_markets)

        if self.portfolio_state is not None:
            self.portfolio_state.update(
                updated_at_us=int(time.time() * 1_000_000),
                monitored_markets=len(self._markets_by_slug),
                eligible_markets=len(eligible_markets),
                in_range_markets=in_range_markets,
                positions=list(self._positions_by_slug.values()),
                cash_balance=self._cash_balance,
                last_market_refresh_ts=self._last_market_refresh_ts,
                last_position_sync_ts=self._last_position_sync_ts,
                last_price_cycle_ts=self._last_price_cycle_ts,
                last_error=self._last_error,
            )

    async def _evaluate_market(self, market: StandaloneMarket) -> None:
        if not self._market_in_entry_window(market):
            return

        async with self._book_semaphore:
            try:
                book = await asyncio.wait_for(
                    _run_blocking(self.background_executor, self.exchange.get_order_book, market.no_token_id),
                    timeout=20.0,
                )
            except Exception as exc:
                self._schedule_backoff(market.slug, failed=True)
                logger.warning("nothing_happens_book_fetch_failed slug=%s err=%s", market.slug, exc)
                return

        no_bid = _best_bid(book)
        if no_bid <= 0 or no_bid > self.cfg.max_entry_price:
            self._market_in_range_by_slug[market.slug] = False
            self._schedule_backoff(market.slug, failed=False)
            return
        self._market_in_range_by_slug[market.slug] = True

        async with self._entry_lock:
            if self._remaining_queue_capacity() == 0:
                logger.info(
                    "nothing_happens_entry_cap_skip slug=%s open=%d pending=%d target=%s",
                    market.slug,
                    len(self._positions_by_slug),
                    len(self._pending_entries_by_slug),
                    self._current_target_open_positions(),
                )
                self._schedule_backoff(market.slug, failed=False)
                return
            if (
                market.slug in self._positions_by_slug
                or market.slug in self._local_positions
                or market.slug in self._pending_entries_by_slug
            ):
                self._schedule_backoff(market.slug, failed=False)
                return

            if not self._category_has_capacity(market.category):
                logger.debug(
                    "nothing_happens_category_cap_skip slug=%s category=%s limit=%d",
                    market.slug,
                    market.category,
                    self.cfg.max_positions_per_category,
                )
                self._schedule_backoff(market.slug, failed=False)
                return

            entry_plan = await self._build_entry_plan(market, book, enforce_risk=False)
            if entry_plan is None:
                self._schedule_backoff(market.slug, failed=False)
                return

            self._enqueue_pending_entry(market)
            logger.info(
                "nothing_happens_entry_queued slug=%s bid=%.4f target=%.4f pending=%d",
                market.slug,
                entry_plan.entry_price,
                entry_plan.target_notional,
                len(self._pending_entries_by_slug),
            )
            self._schedule_backoff(market.slug, failed=False)
            self._publish_portfolio()

    async def _dispatch_next_pending_entry(self) -> bool:
        await self._refresh_recovery_state()
        if not self._pending_entries_by_slug:
            return False

        while not self.shutdown_event.is_set():
            pending = self._next_due_pending_entry()
            if pending is None:
                return False
            if await self._dispatch_pending_entry(pending):
                return True

        return False

    async def _dispatch_pending_entry(self, pending: PendingEntry) -> bool:
        slug = pending.market.slug
        market = self._markets_by_slug.get(slug, pending.market)
        pending.market = market

        if not self._market_in_entry_window(market):
            logger.info(
                "lifecycle_gate_drop_pending slug=%s reason=outside_window",
                pending.market.slug,
            )
            self._pending_entries_by_slug.pop(pending.market.slug, None)
            return False

        if market.end_ts <= time.time():
            self._pending_entries_by_slug.pop(slug, None)
            self._schedule_backoff(slug, failed=False)
            return False

        if pending.order_id:
            return False

        async with self._entry_lock:
            if slug in self._positions_by_slug or slug in self._local_positions:
                self._pending_entries_by_slug.pop(slug, None)
                self._schedule_backoff(slug, failed=False)
                return False

        async with self._book_semaphore:
            try:
                book = await asyncio.wait_for(
                    _run_blocking(self.background_executor, self.exchange.get_order_book, market.no_token_id),
                    timeout=20.0,
                )
            except Exception as exc:
                logger.warning("nothing_happens_dispatch_book_fetch_failed slug=%s err=%s", slug, exc)
                self._reschedule_pending_entry(slug, error=f"book_fetch_failed: {exc}")
                self._schedule_backoff(slug, failed=True)
                return False

        no_bid = _best_bid(book)
        if no_bid <= 0 or no_bid > self.cfg.max_entry_price:
            self._pending_entries_by_slug.pop(slug, None)
            self._schedule_backoff(slug, failed=False)
            return False

        async with self._entry_lock:
            if self._position_target_reached():
                self._pending_entries_by_slug.pop(slug, None)
                self._schedule_backoff(slug, failed=False)
                return False
            if slug in self._positions_by_slug or slug in self._local_positions:
                self._pending_entries_by_slug.pop(slug, None)
                self._schedule_backoff(slug, failed=False)
                return False

            entry_plan = await self._build_entry_plan(market, book, enforce_risk=True)
            if entry_plan is None:
                self._pending_entries_by_slug.pop(slug, None)
                self._schedule_backoff(slug, failed=False)
                return False

            result = await self._attempt_entry(
                market, book, entry_plan.entry_price, entry_plan.target_notional
            )
            if result.open_limit_pending:
                pass
            elif result.success:
                self._pending_entries_by_slug.pop(slug, None)
            else:
                self._reschedule_pending_entry(
                    slug,
                    error=result.error or "order_attempt_failed",
                    min_delay_sec=result.min_retry_delay_sec,
                )
            self._publish_portfolio()
            return True

    async def _ensure_cash_balance(self, *, log_context: str) -> float | None:
        if self._cash_balance is not None:
            return self._cash_balance
        try:
            self._cash_balance = await asyncio.wait_for(
                _run_blocking(self.background_executor, self.exchange.get_collateral_balance),
                timeout=20.0,
            )
        except Exception as exc:
            logger.warning("nothing_happens_cash_balance_%s_failed: %s", log_context, exc)
        return self._cash_balance

    def _reserved_cash_notional_total(self) -> float:
        total = 0.0
        for slug, notional in self._ambiguous_reserved_notional_by_slug.items():
            snapshot = self._positions_by_slug.get(slug)
            if snapshot is not None and snapshot.source == "data_api":
                continue
            total += max(0.0, float(notional))
        return total

    def _reserved_open_exposure_total(self) -> float:
        total = 0.0
        for slug, notional in self._ambiguous_reserved_notional_by_slug.items():
            if slug in self._positions_by_slug:
                continue
            total += max(0.0, float(notional))
        return total

    def _reserved_open_exposure_for_market(self, slug: str) -> float:
        if slug in self._positions_by_slug:
            return 0.0
        return max(0.0, float(self._ambiguous_reserved_notional_by_slug.get(slug, 0.0)))

    def _available_cash_balance(self) -> float | None:
        if self._cash_balance is None:
            return None
        return max(0.0, float(self._cash_balance) - self._reserved_cash_notional_total())

    def _can_open_trade_with_reservations(self, now_us: int, market_slug: str, notional_usd: float) -> tuple[bool, str]:
        self.risk._roll_day_if_needed(now_us)
        if self.risk.kill_switch_active(now_us):
            return False, f"kill_switch_active:{self.risk.kill_switch_reason()}"
        notional = max(0.0, float(notional_usd))
        total_open = self.risk.open_exposure_total_usd + self._reserved_open_exposure_total()
        market_open = self.risk.open_exposure_by_market.get(market_slug, 0.0) + self._reserved_open_exposure_for_market(
            market_slug
        )
        if total_open + notional > self.risk.cfg.max_total_open_exposure_usd:
            return False, "max_total_open_exposure"
        if market_open + notional > self.risk.cfg.max_market_open_exposure_usd:
            return False, "max_market_open_exposure"
        return True, ""

    def _reserve_ambiguous_notional(self, slug: str, notional_usd: float) -> None:
        notional = max(0.0, float(notional_usd))
        if notional <= 0.0:
            self._ambiguous_reserved_notional_by_slug.pop(slug, None)
            return
        current = max(0.0, float(self._ambiguous_reserved_notional_by_slug.get(slug, 0.0)))
        if notional > current:
            self._ambiguous_reserved_notional_by_slug[slug] = notional

    async def _build_entry_plan(
        self,
        market: StandaloneMarket,
        book: OrderBookSnapshot,
        *,
        enforce_risk: bool,
    ) -> EntryPlan | None:
        no_bid = _best_bid(book)
        if no_bid <= 0 or no_bid > self.cfg.max_entry_price:
            return None

        entry_price = no_bid
        submitted_buy_price = entry_price
        bid_depth = _bid_depth_notional(book)
        if bid_depth < self.cfg.min_trade_amount:
            return None

        cash_balance = max(0.0, float(self._available_cash_balance() or 0.0))
        if cash_balance <= 0.0:
            cached_balance = await self._ensure_cash_balance(log_context="entry")
            cash_balance = max(0.0, float(self._available_cash_balance() if cached_balance is not None else 0.0))
            
        open_positions_value = sum(pos.current_value for pos in self._positions_by_slug.values())
        portfolio_value = cash_balance + open_positions_value
        
        target_notional = self._target_notional(
            portfolio_value=portfolio_value,
            submitted_price=submitted_buy_price,
            market_min_order_size=market.min_order_size,
            book_min_order_size=book.min_order_size,
        )
        if target_notional > cash_balance + 1e-9:
            logger.info(
                "nothing_happens_insufficient_cash slug=%s cash=%.4f target=%.4f",
                market.slug,
                cash_balance,
                target_notional,
            )
            return None

        if bid_depth + 1e-9 < target_notional:
            logger.info(
                "nothing_happens_depth_skip slug=%s bid=%.4f bid_depth=%.4f target=%.4f",
                market.slug,
                no_bid,
                bid_depth,
                target_notional,
            )
            return None

        if enforce_risk:
            now_us = int(time.time() * 1_000_000)
            allowed, reason = self._can_open_trade_with_reservations(now_us, market.slug, target_notional)
            if not allowed:
                logger.info(
                    "nothing_happens_risk_block slug=%s reason=%s target=%.4f",
                    market.slug,
                    reason,
                    target_notional,
                )
                return None

        return EntryPlan(entry_price=entry_price, target_notional=target_notional)

    def _enqueue_pending_entry(self, market: StandaloneMarket) -> None:
        if market.slug in self._pending_entries_by_slug:
            return
        self._pending_entries_by_slug[market.slug] = PendingEntry(
            market=market,
            enqueued_at_ts=time.time(),
            next_attempt_monotonic=asyncio.get_running_loop().time(),
        )

    def _category_has_capacity(self, category: str) -> bool:
        """Return True if we can open another position in this market's category.

        When max_positions_per_category <= 0 the limit is disabled.  An empty
        category string is always allowed so uncategorised markets are never
        incorrectly blocked.
        """
        limit = self.cfg.max_positions_per_category
        if limit <= 0 or not category:
            return True
        cat = category.strip().lower()
        count = 0
        for slug in self._positions_by_slug:
            market = self._markets_by_slug.get(slug)
            if market and market.category.strip().lower() == cat:
                count += 1
        for slug, pending in self._pending_entries_by_slug.items():
            market = self._markets_by_slug.get(slug, pending.market)
            if market and market.category.strip().lower() == cat:
                count += 1
        return count < limit

    def _next_due_pending_entry(self) -> PendingEntry | None:
        loop_now = asyncio.get_running_loop().time()
        for pending in self._pending_entries_by_slug.values():
            if pending.order_id:
                continue
            if loop_now >= pending.next_attempt_monotonic:
                return pending
        return None

    def _reschedule_pending_entry(
        self,
        slug: str,
        *,
        error: str,
        min_delay_sec: float | None = None,
    ) -> None:
        pending = self._pending_entries_by_slug.pop(slug, None)
        if pending is None:
            return
        pending.dispatch_failures += 1
        pending.last_error = error
        base_delay = min(
            self.cfg.order_dispatch_interval_sec * (2 ** max(0, pending.dispatch_failures - 1)),
            self.cfg.max_backoff_sec,
        )
        delay = max(base_delay, float(min_delay_sec or 0.0))
        pending.next_attempt_monotonic = asyncio.get_running_loop().time() + delay
        self._pending_entries_by_slug[slug] = pending
        logger.info(
            "nothing_happens_entry_requeued slug=%s failures=%d retry_in=%.1f err=%s",
            slug,
            pending.dispatch_failures,
            delay,
            error,
        )

    async def _attempt_entry(
        self,
        market: StandaloneMarket,
        book: OrderBookSnapshot,
        entry_price: float,
        target_notional: float,
    ) -> EntryAttemptResult:
        try:
            await asyncio.wait_for(
                _run_blocking(self.background_executor, self.exchange.warm_token_cache, market.no_token_id),
                timeout=10.0,
            )
        except Exception:
            pass

        record_order(
            action="attempt",
            market_slug=market.slug,
            side="NO",
            token_id=market.no_token_id,
            amount=target_notional,
            reference_price=entry_price,
            question=market.question,
            attempt=1,
        )
        shares = target_notional / entry_price if entry_price > 0 else 0.0
        if shares <= 0:
            return EntryAttemptResult(success=False, error="invalid_entry_price")

        try:
            result = await asyncio.wait_for(
                _run_blocking(
                    self.background_executor,
                    self.exchange.place_limit_order,
                    LimitOrderIntent(
                        token_id=market.no_token_id,
                        side=Side.BUY,
                        price=entry_price,
                        size=round(shares, 6),
                    ),
                ),
                timeout=25.0,
            )
        except Exception as exc:
            record_order(
                action="error",
                market_slug=market.slug,
                side="NO",
                token_id=market.no_token_id,
                amount=target_notional,
                reference_price=entry_price,
                error=str(exc),
                question=market.question,
                attempt=1,
            )
            logger.warning(
                "nothing_happens_limit_order_failed slug=%s err=%s",
                market.slug,
                exc,
                exc_info=True,
            )
            return EntryAttemptResult(success=False, error=str(exc))

        if result and result.order_id:
            if pending := self._pending_entries_by_slug.get(market.slug):
                pending.order_id = str(result.order_id)
                pending.order_placed_at_ts = time.time()
            return EntryAttemptResult(success=False, open_limit_pending=True)

        return EntryAttemptResult(success=False, error="limit_order_no_id")

    def _ambiguous_retry_delay_sec(self) -> float:
        return max(
            float(self.cfg.order_dispatch_interval_sec),
            float(self.cfg.position_sync_interval_sec) + 5.0,
        )

    def _recovery_market_view(self, market: StandaloneMarket):
        return SimpleNamespace(
            slug=market.slug,
            interval_start=0,
            up_token_id=market.yes_token_id,
            down_token_id=market.no_token_id,
        )

    async def _record_ambiguous_buy(
        self,
        *,
        market: StandaloneMarket,
        target_notional: float,
        reference_price: float,
        error: str,
        order_id: str = "",
    ) -> None:
        self._reserve_ambiguous_notional(market.slug, target_notional)
        if self.recovery_coordinator is None:
            return
        row_id = await _run_blocking(
            self.background_executor,
            lambda: self.recovery_coordinator.create_ambiguous_order(
                market=self._recovery_market_view(market),
                phase="buy",
                side="DOWN",
                token_id=market.no_token_id,
                requested_amount=target_notional,
                reference_price=reference_price,
                order_id=order_id,
                initial_error=error,
            ),
        )
        await self.recovery_coordinator.schedule_fast_ambiguity_resolution(
            row_id,
            exchange=self.exchange,
            venue_state=None,
            background_executor=self.background_executor,
        )

    def _restore_durable_recovery_fill(
        self,
        *,
        market: StandaloneMarket,
        size: float,
        avg_price: float,
        initial_value: float,
    ) -> None:
        if market.slug in self._positions_by_slug or market.slug in self._local_positions:
            return
        self._register_local_position(
            market=market,
            size=size,
            avg_price=avg_price,
            initial_value=initial_value,
            current_price=avg_price,
            source="ambiguous_recovery",
        )
        self.risk.on_open_trade(market.slug, initial_value, int(time.time() * 1_000_000))

    async def _refresh_recovery_state(self) -> None:
        if self.recovery_coordinator is None:
            return
        try:
            rows = await asyncio.wait_for(
                _run_blocking(
                    self.background_executor,
                    self.recovery_coordinator.fetch_latest_ambiguous_buy_rows,
                    interval_start=0,
                ),
                timeout=20.0,
            )
        except Exception as exc:
            logger.warning("nothing_happens_recovery_refresh_failed: %s", exc)
            return

        blocked_slugs: set[str] = set()
        reserved_notional_by_slug: dict[str, float] = {}
        for row in rows:
            slug = str(row.get("market_slug") or "")
            if not slug:
                continue
            state = str(row.get("state") or "").strip().lower()
            requested_amount = max(
                0.0,
                _safe_float(row.get("requested_amount") or row.get("resolved_spent_usd")),
            )
            snapshot = self._positions_by_slug.get(slug)
            has_remote_position = snapshot is not None and snapshot.source == "data_api"
            if requested_amount > 0.0 and not has_remote_position:
                reserved_notional_by_slug[slug] = max(
                    reserved_notional_by_slug.get(slug, 0.0),
                    requested_amount,
                )
            if state == "not_filled":
                reserved_notional_by_slug.pop(slug, None)
                continue
            if state == "filled":
                if slug in self._positions_by_slug or slug in self._local_positions:
                    self._pending_entries_by_slug.pop(slug, None)
                    if has_remote_position:
                        reserved_notional_by_slug.pop(slug, None)
                    continue
                market = self._markets_by_slug.get(slug)
                pending = self._pending_entries_by_slug.get(slug)
                if market is None and pending is not None:
                    market = pending.market
                if market is None:
                    blocked_slugs.add(slug)
                    continue
                filled_shares = _safe_float(row.get("resolved_filled_shares"))
                fill_price = _safe_float(
                    row.get("resolved_fill_price") or row.get("reference_price"),
                    self.cfg.max_entry_price,
                )
                spent_usd = _safe_float(row.get("resolved_spent_usd"))
                if spent_usd <= 0.0 and fill_price > 0.0 and filled_shares > 0.0:
                    spent_usd = fill_price * filled_shares
                if filled_shares <= BALANCE_DUST_THRESHOLD or spent_usd <= 0.0:
                    blocked_slugs.add(slug)
                    continue
                self._restore_durable_recovery_fill(
                    market=market,
                    size=max(filled_shares, BALANCE_DUST_THRESHOLD),
                    avg_price=fill_price,
                    initial_value=spent_usd,
                )
                self._pending_entries_by_slug.pop(slug, None)
                self._schedule_backoff(slug, failed=False)
                continue
            blocked_slugs.add(slug)
            self._pending_entries_by_slug.pop(slug, None)

        blocked_slugs -= set(self._positions_by_slug)
        blocked_slugs -= set(self._local_positions)
        self._recovery_blocked_slugs = blocked_slugs
        self._ambiguous_reserved_notional_by_slug = reserved_notional_by_slug

    async def _recover_balance_fill(self, market: StandaloneMarket, target_notional: float) -> bool:
        try:
            balance = await asyncio.wait_for(
                _run_blocking(self.background_executor, self.exchange.get_conditional_balance, market.no_token_id),
                timeout=20.0,
            )
        except Exception:
            return False
        if balance <= BALANCE_DUST_THRESHOLD:
            return False
        avg_price = target_notional / balance if balance > 0 else self.cfg.max_entry_price
        self._record_local_fill(
            market=market,
            size=balance,
            avg_price=avg_price,
            initial_value=target_notional,
            current_price=avg_price,
            source="balance_recovery",
        )
        self._pending_entries_by_slug.pop(market.slug, None)
        record_order(
            action="buy",
            market_slug=market.slug,
            side="NO",
            token_id=market.no_token_id,
            amount=target_notional,
            reference_price=avg_price,
            question=market.question,
            shares=balance,
            recovery_source="conditional_balance",
        )
        logger.info(
            "nothing_happens_recovered_fill slug=%s balance=%.4f target=%.4f",
            market.slug,
            balance,
            target_notional,
        )
        return True

    def _register_local_position(
        self,
        *,
        market: StandaloneMarket,
        size: float,
        avg_price: float,
        initial_value: float,
        current_price: float,
        source: str,
    ) -> None:
        local_position = LocalPosition(
            slug=market.slug,
            title=market.question,
            outcome="No",
            asset=market.no_token_id,
            condition_id=market.condition_id,
            size=float(size),
            avg_price=float(avg_price),
            initial_value=float(initial_value),
            current_price=float(current_price),
            current_value=float(size) * float(current_price),
            end_date=market.end_date,
            end_ts=market.end_ts,
            source=source,
            created_at_ts=time.time(),
        )
        self._local_positions[market.slug] = local_position
        self._positions_by_slug[market.slug] = _position_snapshot_from_local(local_position)

    def _record_local_fill(
        self,
        *,
        market: StandaloneMarket,
        size: float,
        avg_price: float,
        initial_value: float,
        current_price: float,
        source: str,
    ) -> None:
        self._initialize_target_open_positions()
        notional = max(0.0, float(initial_value))
        
        is_new_position = market.slug not in self._positions_by_slug and market.slug not in self._local_positions
        self._register_local_position(
            market=market,
            size=size,
            avg_price=avg_price,
            initial_value=notional,
            current_price=current_price,
            source=source,
        )
        self.risk.on_open_trade(market.slug, notional, int(time.time() * 1_000_000))
        if self._cash_balance is not None:
            self._cash_balance = max(0.0, float(self._cash_balance) - notional)
        if is_new_position:
            self._opened_position_count += 1
            if self._position_target_reached():
                logger.info(
                    "nothing_happens_entry_cap_reached open=%d target=%s shutdown=%s",
                    len(self._positions_by_slug),
                    self._current_target_open_positions(),
                    self.cfg.shutdown_on_max_new_positions,
                )
                if self.cfg.shutdown_on_max_new_positions:
                    self.shutdown_event.set()

    def _target_notional(
        self,
        *,
        portfolio_value: float,
        submitted_price: float,
        market_min_order_size: float,
        book_min_order_size: float,
    ) -> float:
        base_notional = (
            self.cfg.fixed_trade_amount
            if self.cfg.fixed_trade_amount > 0
            else max(portfolio_value * self.cfg.portfolio_pct_per_trade, self.cfg.min_trade_amount)
        )
        minimum_shares = max(0.0, market_min_order_size, book_min_order_size)
        if minimum_shares <= 0 or submitted_price <= 0:
            return base_notional
        return max(base_notional, minimum_shares * submitted_price)

    def _schedule_backoff(self, slug: str, *, failed: bool) -> None:
        state = self._price_backoff.get(slug)
        if state is None:
            state = PriceBackoff()
            self._price_backoff[slug] = state
        if failed:
            state.failures += 1
            delay = min(
                self.cfg.price_poll_interval_sec * (2 ** max(0, state.failures - 1)),
                self.cfg.max_backoff_sec,
            )
        else:
            state.failures = 0
            delay = self.cfg.price_poll_interval_sec
        state.next_check_monotonic = asyncio.get_running_loop().time() + delay

    def _publish_portfolio(self) -> None:
        remaining_capacity = self._remaining_queue_capacity()
        if self.control_state is not None:
            self.control_state.update_status(
                current_open_positions=len(self._positions_by_slug),
                pending_entry_count=len(self._pending_entries_by_slug),
                remaining_capacity=remaining_capacity,
                opened_this_run=self._opened_position_count,
            )
        if self.portfolio_state is None:
            return
        eligible_markets = self._eligible_markets()
        self.portfolio_state.update(
            updated_at_us=int(time.time() * 1_000_000),
            monitored_markets=len(self._markets_by_slug),
            eligible_markets=len(eligible_markets),
            in_range_markets=self._in_range_market_count(eligible_markets),
            positions=list(self._positions_by_slug.values()),
            cash_balance=self._cash_balance,
            last_market_refresh_ts=self._last_market_refresh_ts,
            last_position_sync_ts=self._last_position_sync_ts,
            last_price_cycle_ts=self._last_price_cycle_ts,
            last_error=self._last_error,
        )


async def run(
    *,
    exchange,
    session: aiohttp.ClientSession,
    cfg: NothingHappensConfig,
    risk,
    background_executor: Executor | None,
    shutdown_event: asyncio.Event,
    portfolio_state: PortfolioState | None,
    control_state: NothingHappensControlState | None,
    recovery_coordinator=None,
    wallet_address: str | None,
) -> None:
    runtime = NothingHappensRuntime(
        exchange=exchange,
        session=session,
        cfg=cfg,
        risk=risk,
        background_executor=background_executor,
        shutdown_event=shutdown_event,
        portfolio_state=portfolio_state,
        control_state=control_state,
        recovery_coordinator=recovery_coordinator,
        wallet_address=wallet_address,
    )
    await runtime.run()
