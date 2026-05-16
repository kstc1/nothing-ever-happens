"""Dashboard web server via aiohttp + WebSocket."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import time
from collections import deque
from pathlib import Path

from aiohttp import web

from bot.nothing_happens_control import NothingHappensControlState
from bot.performance_metrics import (
    compute_performance,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
BACKGROUND_IMAGE = STATIC_DIR / "nothingeverhappens.svg"
BALANCE_POLL_INTERVAL_SEC = 30.0
BALANCE_TIMEOUT_SEC = 10.0
RESOLUTION_POLL_INTERVAL_SEC = 15.0
TRADE_HISTORY_LIMIT = 1000
BALANCE_HISTORY_LIMIT = 2880
EQUITY_SNAPSHOT_INTERVAL_SEC = 3600.0  # hourly
EQUITY_HISTORY_LIMIT = 2880

# Re-push portfolio to browsers on this wall-clock interval even when strategy versions
# are unchanged (strategy often publishes at price_poll_interval, e.g. 30–60s).
_DEFAULT_PORTFOLIO_FORCE_INTERVAL_SEC = 3.0


def _env_flag_truthy(name: str) -> bool:
    v = os.getenv(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


class DashboardServer:
    def __init__(
        self,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
        exchange=None,
        portfolio_state=None,
        nothing_happens_control: NothingHappensControlState | None = None,
    ):
        self.host = host
        self.port = port
        self._exchange = exchange
        self._portfolio_state = portfolio_state
        self._nothing_happens_control = nothing_happens_control
        self._clients: set[web.WebSocketResponse] = set()
        self._last_portfolio_version = -1
        self._last_nothing_happens_control_version = -1
        self._ledger_path = os.getenv("TRADE_LEDGER_PATH", "trades.jsonl")
        self._ledger_pos = 0
        self._trade_history: deque[dict] = deque(maxlen=TRADE_HISTORY_LIMIT)
        self._starting_balance: float | None = None
        self._current_balance: float | None = None
        self._last_balance_poll = 0.0
        self._balance_history: deque[tuple[float, float]] = deque(maxlen=BALANCE_HISTORY_LIMIT)
        self._equity_history: deque[tuple[float, float]] = deque(maxlen=EQUITY_HISTORY_LIMIT)
        self._starting_equity: float | None = None
        self._equity_metric_start_ts: float | None = None
        self._last_equity_snapshot_ts = 0.0
        self._equity_csv_path = os.getenv("PERFORMANCE_EQUITY_CSV", "performance_equity.csv")
        self._resolutions: dict[str, str] = {}
        self._pending_resolution_slugs: list[str] = []
        self._last_resolution_poll = 0.0
        try:
            self._portfolio_force_interval_sec = max(
                0.0,
                float(os.getenv("DASHBOARD_PORTFOLIO_FORCE_INTERVAL_SEC", "3") or 0),
            )
        except ValueError:
            self._portfolio_force_interval_sec = _DEFAULT_PORTFOLIO_FORCE_INTERVAL_SEC
        self._last_portfolio_broadcast_wall: float = 0.0
        self._last_performance_broadcast_wall: float = 0.0
        self._initialize_performance_series()

    def _resolve_reset_marker_path(self) -> Path | None:
        raw = os.getenv("PERFORMANCE_BASELINE_RESET_MARKER", "reset_performance_baseline").strip()
        if not raw:
            return None
        p = Path(raw)
        if not p.is_absolute():
            p = Path.cwd() / p
        return p if p.is_file() else None

    def _initialize_performance_series(self) -> None:
        env_reset = _env_flag_truthy("PERFORMANCE_BASELINE_RESET")
        marker_path = self._resolve_reset_marker_path()
        if env_reset or marker_path is not None:
            reason = (
                "PERFORMANCE_BASELINE_RESET"
                if env_reset
                else f"marker:{marker_path}"
            )
            self._reset_performance_baseline(
                reason=reason,
                marker_to_remove=marker_path if marker_path is not None else None,
            )
            return
        self._load_equity_series_from_disk()

    def _reset_performance_baseline(
        self,
        *,
        reason: str,
        marker_to_remove: Path | None,
    ) -> None:
        """Clear equity history and CSV so the next snapshot defines a new return baseline."""
        self._equity_history.clear()
        self._starting_equity = None
        self._equity_metric_start_ts = None
        self._last_equity_snapshot_ts = 0.0
        path = self._equity_csv_path
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                f.write("timestamp_iso,unix_ts,equity_usd\n")
        except OSError as exc:
            logger.error("performance_baseline_reset_csv_truncate_failed: %s", exc, exc_info=True)
        if marker_to_remove is not None:
            try:
                marker_to_remove.unlink()
            except OSError as exc:
                logger.error("performance_baseline_reset_marker_remove_failed: %s", exc, exc_info=True)
        logger.info("performance_baseline_reset reason=%s csv=%s", reason, path)

    def _load_equity_series_from_disk(self) -> None:
        """Restore hourly equity series and baseline so metrics survive process restarts."""
        path = self._equity_csv_path
        parsed: list[tuple[float, float]] = []
        try:
            if not os.path.isfile(path):
                return
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row or len(row) < 3:
                        continue
                    if str(row[1]).strip().lower() == "unix_ts":
                        continue
                    try:
                        ts = float(row[1].strip())
                        equity = float(row[2].strip())
                    except ValueError:
                        logger.warning(
                            "performance_equity_csv_skip_row_invalid: %s",
                            row,
                        )
                        continue
                    if ts <= 0 or equity < 0:
                        continue
                    parsed.append((ts, equity))
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.warning(
                "performance_equity_csv_load_failed path=%s err=%s",
                path,
                exc,
                exc_info=True,
            )
            return

        if not parsed:
            return

        by_ts: dict[float, float] = {}
        for ts, eq in parsed:
            by_ts[ts] = eq
        merged = sorted(by_ts.items(), key=lambda x: x[0])
        baseline = merged[0][1]
        tail = merged[-EQUITY_HISTORY_LIMIT:]
        for item in tail:
            self._equity_history.append(item)
        self._starting_equity = float(baseline)
        self._equity_metric_start_ts = float(merged[0][0])
        self._last_equity_snapshot_ts = merged[-1][0]
        logger.info(
            "performance_equity_restored path=%s samples=%d baseline=%.2f "
            "deque=%d last_ts=%.3f",
            path,
            len(merged),
            baseline,
            len(self._equity_history),
            self._last_equity_snapshot_ts,
        )

    async def _index(self, request):
        return web.FileResponse(STATIC_DIR / "dashboard.html")

    async def _background_image(self, request):
        if not BACKGROUND_IMAGE.exists():
            raise web.HTTPNotFound(text="background image not found")
        return web.FileResponse(BACKGROUND_IMAGE)

    async def _ws_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        logger.info("Dashboard client connected (%d total)", len(self._clients))
        await self._send_initial(ws)
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    await self._handle_ws_message(ws, msg.data)
        finally:
            self._clients.discard(ws)
            logger.info("Dashboard client disconnected (%d remaining)", len(self._clients))
        return ws

    async def _handle_ws_message(self, ws: web.WebSocketResponse, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            await self._send_to(ws, {"type": "control_ack", "ok": False, "error": "invalid_json"})
            return
        if not isinstance(payload, dict):
            await self._send_to(ws, {"type": "control_ack", "ok": False, "error": "invalid_payload"})
            return
        if payload.get("type") == "reset_performance_baseline":
            self._reset_performance_baseline(reason="websocket", marker_to_remove=None)
            await self._broadcast({"type": "equity_history", "points": []})
            perf_msg = self._make_performance_message()
            if perf_msg is not None:
                await self._broadcast(perf_msg)
            await self._send_to(
                ws,
                {"type": "control_ack", "ok": True, "action": "reset_performance_baseline"},
            )
            logger.info("performance_baseline_reset_via_websocket")
            return
        if payload.get("type") == "set_position_target":
            await self._send_to(ws, {"type": "control_ack", "ok": False, "error": "controls_disabled"})

    async def _send_to(self, ws: web.WebSocketResponse, data: dict) -> None:
        try:
            await ws.send_str(json.dumps(data, allow_nan=False))
        except Exception:
            self._clients.discard(ws)

    async def _broadcast(self, data: dict) -> None:
        if not self._clients:
            return
        try:
            message = json.dumps(data, allow_nan=False)
        except (TypeError, ValueError) as exc:
            logger.error(
                "dashboard_broadcast_serialize_failed: %s",
                exc,
                exc_info=True,
            )
            return
        dead: set[web.WebSocketResponse] = set()
        for ws in self._clients:
            try:
                await ws.send_str(message)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def _send_initial(self, ws: web.WebSocketResponse) -> None:
        portfolio_message = self._make_portfolio_message(force=True)
        if portfolio_message is not None:
            await self._send_to(ws, portfolio_message)
        if self._starting_balance is not None and self._current_balance is not None:
            await self._send_to(ws, self._make_pnl_message())
        if self._balance_history:
            await self._send_to(
                ws,
                {
                    "type": "balance_history",
                    "points": [
                        {"ts": ts * 1000, "balance": round(balance, 2)}
                        for ts, balance in self._balance_history
                    ],
                },
            )
        await self._send_equity_initial(ws)
        for trade in list(self._trade_history)[-500:]:
            await self._send_to(ws, trade)
        for slug, winner in self._resolutions.items():
            await self._send_to(
                ws,
                {"type": "resolution", "market_slug": slug, "winner": winner},
            )

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Dashboard poll error: %s", exc, exc_info=True)
            await asyncio.sleep(0.25)

    async def _poll_once(self) -> None:
        await self._poll_trades()
        await self._poll_balance()

        now = time.time()
        interval = self._portfolio_force_interval_sec
        force_portfolio = False
        if (
            interval > 0
            and self._last_portfolio_broadcast_wall > 0
            and (now - self._last_portfolio_broadcast_wall) >= interval
        ):
            force_portfolio = True

        portfolio_message = self._make_portfolio_message(force=force_portfolio)
        if portfolio_message is not None:
            await self._broadcast(portfolio_message)
            self._last_portfolio_broadcast_wall = now

        interval_pf = self._portfolio_force_interval_sec
        should_perf = self._equity_usd_for_snapshot() is not None and interval_pf > 0 and (
            self._last_performance_broadcast_wall == 0.0
            or (now - self._last_performance_broadcast_wall) >= interval_pf
        )
        if should_perf:
            perf_msg = self._make_performance_message()
            if perf_msg is not None:
                await self._broadcast(perf_msg)
                self._last_performance_broadcast_wall = now

        await self._maybe_snapshot_equity()
        await self._poll_resolutions()

    def _make_portfolio_message(self, *, force: bool = False) -> dict | None:
        if self._portfolio_state is None:
            return None
        version = self._portfolio_state.version()
        control_version = (
            self._nothing_happens_control.version()
            if self._nothing_happens_control is not None
            else -1
        )
        if (
            not force
            and version == self._last_portfolio_version
            and control_version == self._last_nothing_happens_control_version
        ):
            return None
        self._last_portfolio_version = version
        self._last_nothing_happens_control_version = control_version
        snapshot = self._portfolio_state.snapshot()
        control_snapshot = (
            self._nothing_happens_control.snapshot()
            if self._nothing_happens_control is not None
            else None
        )
        display_cash = snapshot.cash_balance
        if self._current_balance is not None:
            display_cash = float(self._current_balance)
        return {
            "type": "portfolio",
            "updated_at_us": snapshot.updated_at_us,
            "monitored_markets": snapshot.monitored_markets,
            "eligible_markets": snapshot.eligible_markets,
            "in_range_markets": snapshot.in_range_markets,
            "cash_balance": display_cash,
            "last_market_refresh_ts": snapshot.last_market_refresh_ts,
            "last_position_sync_ts": snapshot.last_position_sync_ts,
            "last_price_cycle_ts": snapshot.last_price_cycle_ts,
            "last_error": snapshot.last_error,
            "target_open_positions": (
                control_snapshot.target_open_positions if control_snapshot is not None else None
            ),
            "pending_entry_count": (
                control_snapshot.pending_entry_count if control_snapshot is not None else 0
            ),
            "remaining_position_capacity": (
                control_snapshot.remaining_capacity if control_snapshot is not None else None
            ),
            "opened_this_run": (
                control_snapshot.opened_this_run if control_snapshot is not None else 0
            ),
            "controls_enabled": control_snapshot is not None,
            "positions": [
                {
                    "slug": position.slug,
                    "title": position.title,
                    "outcome": position.outcome,
                    "asset": position.asset,
                    "condition_id": position.condition_id,
                    "size": round(position.size, 6),
                    "avg_price": round(position.avg_price, 6),
                    "initial_value": round(position.initial_value, 6),
                    "current_price": round(position.current_price, 6),
                    "current_value": round(position.current_value, 6),
                    "pnl_usd": round(position.pnl_usd, 6),
                    "pnl_pct": round(position.pnl_pct, 6),
                    "end_date": position.end_date,
                    "eta_seconds": round(position.eta_seconds, 3),
                    "source": position.source,
                }
                for position in snapshot.positions
            ],
        }

    async def _poll_trades(self) -> None:
        try:
            if not os.path.exists(self._ledger_path):
                return
            with open(self._ledger_path, "r") as f:
                f.seek(self._ledger_pos)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    trade_msg = {"type": "bot_trade", **record}
                    self._trade_history.append(trade_msg)
                    await self._broadcast(trade_msg)
                self._ledger_pos = f.tell()
        except Exception as exc:
            logger.warning("Trade ledger poll error: %s", exc, exc_info=True)

    def _make_pnl_message(self) -> dict:
        pnl_usd = (self._current_balance or 0.0) - (self._starting_balance or 0.0)
        pnl_pct = (
            (pnl_usd / self._starting_balance * 100.0)
            if self._starting_balance and self._starting_balance > 0
            else 0.0
        )
        return {
            "type": "session_pnl",
            "starting_balance": round(self._starting_balance or 0.0, 2),
            "current_balance": round(self._current_balance or 0.0, 2),
            "pnl_usd": round(pnl_usd, 2),
            "pnl_pct": round(pnl_pct, 2),
        }

    async def _send_equity_initial(self, ws: web.WebSocketResponse) -> None:
        perf = self._make_performance_message()
        if perf is not None:
            await self._send_to(ws, perf)
        if self._equity_history:
            await self._send_to(
                ws,
                {
                    "type": "equity_history",
                    "points": [
                        {"ts": ts * 1000, "equity": round(eq, 2)}
                        for ts, eq in self._equity_history
                    ],
                },
            )

    def _strategy_elapsed_for_metrics(self) -> float | None:
        if self._equity_metric_start_ts is None or not self._equity_history:
            return None
        last_ts = max(t for t, _ in self._equity_history)
        return max(0.0, last_ts - self._equity_metric_start_ts)

    def _make_performance_message(self) -> dict | None:
        live_eq = self._equity_usd_for_snapshot()

        if not self._equity_history:
            if live_eq is None:
                return None
            start = self._starting_equity
            if start is None or start <= 0:
                start_display = round(live_eq, 2)
                tr_pct = 0.0
            else:
                start_display = round(float(start), 2)
                tr_pct = ((live_eq / float(start)) - 1.0) * 100.0
            return {
                "type": "performance",
                "equity_usd": round(live_eq, 2),
                "starting_equity_usd": start_display,
                "total_return_pct": round(tr_pct, 4),
                "apy_pct": None,
                "sharpe_ratio": None,
                "sortino_ratio": None,
                "elapsed_seconds": 0.0,
                "sample_count": 0,
            }

        try:
            perf = compute_performance(
                list(self._equity_history),
                starting_equity_fallback=self._starting_equity,
                strategy_elapsed_seconds=self._strategy_elapsed_for_metrics(),
            )
        except Exception as exc:
            logger.error("performance_message_compute_failed: %s", exc, exc_info=True)
            return None
        if perf is None:
            return None

        equity_out = round(perf.equity_usd, 2)
        tr_pct = round(perf.total_return_pct, 4)
        if live_eq is not None:
            equity_out = round(live_eq, 2)
            if perf.starting_equity_usd > 0:
                tr_pct = round(((live_eq / perf.starting_equity_usd) - 1.0) * 100.0, 4)

        return {
            "type": "performance",
            "equity_usd": equity_out,
            "starting_equity_usd": round(perf.starting_equity_usd, 2),
            "total_return_pct": tr_pct,
            "apy_pct": None if perf.apy_pct is None else round(perf.apy_pct, 4),
            "sharpe_ratio": None if perf.sharpe_ratio is None else round(perf.sharpe_ratio, 4),
            "sortino_ratio": None if perf.sortino_ratio is None else round(perf.sortino_ratio, 4),
            "elapsed_seconds": round(perf.elapsed_seconds, 3),
            "sample_count": perf.sample_count,
        }

    def _append_equity_csv(self, ts: float, equity: float) -> None:
        try:
            from datetime import datetime, timezone

            path = self._equity_csv_path
            row = (
                datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                round(ts, 3),
                round(equity, 6),
            )
            exists = os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8") as f:
                if not exists:
                    f.write("timestamp_iso,unix_ts,equity_usd\n")
                f.write(f"{row[0]},{row[1]},{row[2]}\n")
        except Exception as exc:
            logger.error("performance_equity_csv_write_failed: %s", exc, exc_info=True)

    def _equity_usd_for_snapshot(self) -> float | None:
        """Total equity for performance: exchange collateral (when polled) + marked positions.

        The balance poll runs on the first dashboard tick so `_current_balance` usually aligns
        with on-chain collateral before equity snapshots anchor the baseline (fixes stale portfolio
        cash during the boot window).
        """
        if self._portfolio_state is None:
            return None
        snap = self._portfolio_state.snapshot()
        cash = snap.cash_balance
        if self._current_balance is not None:
            cash = float(self._current_balance)
        if cash is None:
            return None
        pos_val = sum(float(p.current_value) for p in snap.positions)
        return float(cash) + pos_val

    async def _maybe_snapshot_equity(self) -> None:
        if self._portfolio_state is None:
            return
        equity = self._equity_usd_for_snapshot()
        if equity is None:
            return
        if self._starting_equity is None:
            self._starting_equity = equity
        now = time.time()
        if self._last_equity_snapshot_ts > 0 and now - self._last_equity_snapshot_ts < EQUITY_SNAPSHOT_INTERVAL_SEC:
            return
        self._last_equity_snapshot_ts = now
        if self._equity_metric_start_ts is None:
            self._equity_metric_start_ts = float(now)
        self._equity_history.append((now, equity))
        perf_msg = self._make_performance_message()
        if perf_msg is not None:
            await self._broadcast(perf_msg)
        await self._broadcast(
            {
                "type": "equity_point",
                "ts": now * 1000,
                "equity": round(equity, 2),
            }
        )
        self._append_equity_csv(now, equity)

    async def _poll_balance(self) -> None:
        if self._exchange is None:
            return
        loop_now = asyncio.get_running_loop().time()
        # Allow first poll immediately (_last_balance_poll starts at 0; loop_now - 0 < interval would stall ~30s).
        if (
            self._last_balance_poll > 0.0
            and loop_now - self._last_balance_poll < BALANCE_POLL_INTERVAL_SEC
        ):
            return
        self._last_balance_poll = loop_now
        try:
            balance = await asyncio.wait_for(
                asyncio.to_thread(self._exchange.get_collateral_balance),
                timeout=BALANCE_TIMEOUT_SEC,
            )
            if self._starting_balance is None:
                self._starting_balance = balance
                logger.info(
                    "dashboard_starting_balance",
                    extra={"balance": round(balance, 2)},
                )
            self._current_balance = balance
            ts_sec = time.time()
            self._balance_history.append((ts_sec, balance))
            await self._broadcast(self._make_pnl_message())
            await self._broadcast(
                {
                    "type": "balance_point",
                    "ts": ts_sec * 1000,
                    "balance": round(balance, 2),
                }
            )
        except Exception as exc:
            logger.warning("Dashboard balance poll failed: %s", exc, exc_info=True)

    async def _poll_resolutions(self) -> None:
        loop_now = asyncio.get_running_loop().time()
        if (
            self._last_resolution_poll > 0.0
            and loop_now - self._last_resolution_poll < RESOLUTION_POLL_INTERVAL_SEC
        ):
            return
        self._last_resolution_poll = loop_now

        for trade in self._trade_history:
            slug = trade.get("market_slug", "")
            if slug and slug not in self._resolutions and slug not in self._pending_resolution_slugs:
                self._pending_resolution_slugs.append(slug)

        if not self._pending_resolution_slugs:
            return

        from bot.live_recovery import _check_gamma_resolution

        for slug in self._pending_resolution_slugs[:5]:
            try:
                winner = await _check_gamma_resolution(slug)
                if winner is None:
                    continue
                display_winner = winner.capitalize()
                self._resolutions[slug] = display_winner
                self._pending_resolution_slugs.remove(slug)
                await self._broadcast(
                    {
                        "type": "resolution",
                        "market_slug": slug,
                        "winner": display_winner,
                    }
                )
                logger.info("Resolution: %s -> %s", slug, display_winner)
            except Exception as exc:
                logger.debug("Resolution fetch failed for %s: %s", slug, exc)

    async def run(self) -> None:
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/nothingeverhappens.svg", self._background_image)
        app.router.add_get("/ws", self._ws_handler)

        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info("Dashboard at http://%s:%d", self.host, self.port)

        try:
            await self._poll_loop()
        finally:
            await runner.cleanup()
