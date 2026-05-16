"""Smoke tests for dashboard server."""

import asyncio
import json

import aiohttp
import pytest

import bot.dashboard as dashboard_mod

from bot.dashboard import DashboardServer
from bot.nothing_happens_control import NothingHappensControlState
from bot.portfolio_state import PortfolioState


@pytest.fixture(autouse=True)
def _isolate_performance_equity_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("PERFORMANCE_EQUITY_CSV", str(tmp_path / "_test_perf_equity.csv"))


def _make_portfolio_state() -> PortfolioState:
    portfolio_state = PortfolioState()
    portfolio_state.update(
        updated_at_us=1,
        monitored_markets=12,
        eligible_markets=10,
        in_range_markets=3,
        positions=[],
        cash_balance=42.0,
        last_market_refresh_ts=1.0,
        last_position_sync_ts=1.0,
        last_price_cycle_ts=1.0,
        last_error="",
    )
    return portfolio_state


def test_dashboard_performance_message():
    portfolio_state = _make_portfolio_state()
    portfolio_state.update(
        updated_at_us=1,
        monitored_markets=12,
        eligible_markets=10,
        in_range_markets=3,
        positions=[],
        cash_balance=102.0,
        last_market_refresh_ts=1.0,
        last_position_sync_ts=1.0,
        last_price_cycle_ts=1.0,
        last_error="",
    )
    server = DashboardServer(port=0, portfolio_state=portfolio_state)
    server._starting_equity = 100.0
    server._equity_metric_start_ts = 500.0
    server._equity_history.append((1000.0, 100.0))
    server._equity_history.append((2000.0, 102.0))
    msg = server._make_performance_message()
    assert msg is not None
    assert msg["type"] == "performance"
    assert msg["total_return_pct"] == 2.0
    assert msg["equity_usd"] == 102.0


def test_dashboard_loads_equity_csv_for_persistence(tmp_path, monkeypatch):
    path = tmp_path / "eq.csv"
    path.write_text(
        "timestamp_iso,unix_ts,equity_usd\n"
        "2026-01-01T00:00:00Z,100000,100\n"
        "2026-01-01T01:00:00Z,103600,103\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PERFORMANCE_EQUITY_CSV", str(path.resolve()))
    server = DashboardServer(port=0)
    assert server._starting_equity == 100.0
    assert server._equity_metric_start_ts == 100000.0
    assert server._last_equity_snapshot_ts == 103600.0
    assert list(server._equity_history) == [(100000.0, 100.0), (103600.0, 103.0)]
    msg = server._make_performance_message()
    assert msg is not None
    assert msg["equity_usd"] == 103.0
    assert msg["starting_equity_usd"] == 100.0
    assert msg["total_return_pct"] == pytest.approx(3.0)


def test_dashboard_equity_csv_truncates_tail_to_maxlen(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_mod, "EQUITY_HISTORY_LIMIT", 4)
    path = tmp_path / "wide.csv"
    lines = ["timestamp_iso,unix_ts,equity_usd\n"]
    for i in range(6):
        ts = float(1000 + i * 100)
        eq = float(100 + i)
        lines.append(f"x,{ts},{eq}\n")
    path.write_text("".join(lines), encoding="utf-8")
    monkeypatch.setenv("PERFORMANCE_EQUITY_CSV", str(path.resolve()))
    server = DashboardServer(port=0)
    assert server._starting_equity == 100.0
    assert len(server._equity_history) == 4
    assert list(server._equity_history)[0] == (1200.0, 102.0)
    msg = server._make_performance_message()
    assert msg is not None
    assert msg["total_return_pct"] == pytest.approx(5.0)


def test_performance_baseline_reset_env_truncates_csv(tmp_path, monkeypatch):
    path = tmp_path / "ledger.csv"
    path.write_text(
        "timestamp_iso,unix_ts,equity_usd\nx,100,100\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PERFORMANCE_EQUITY_CSV", str(path))
    monkeypatch.setenv("PERFORMANCE_BASELINE_RESET", "1")
    server = DashboardServer(port=0)
    assert server._starting_equity is None
    assert len(server._equity_history) == 0
    assert path.read_text(encoding="utf-8").strip() == "timestamp_iso,unix_ts,equity_usd"


def test_performance_baseline_reset_marker_file_removed(tmp_path, monkeypatch):
    csv_path = tmp_path / "ledger.csv"
    csv_path.write_text("timestamp_iso,unix_ts,equity_usd\n", encoding="utf-8")
    marker = tmp_path / "touch"
    marker.write_bytes(b"")
    monkeypatch.setenv("PERFORMANCE_EQUITY_CSV", str(csv_path))
    monkeypatch.setenv("PERFORMANCE_BASELINE_RESET_MARKER", str(marker))
    monkeypatch.delenv("PERFORMANCE_BASELINE_RESET", raising=False)
    server = DashboardServer(port=0)
    assert not marker.is_file()
    assert server._starting_equity is None


@pytest.mark.asyncio
async def test_websocket_reset_performance_baseline(tmp_path, monkeypatch):
    perf_csv = tmp_path / "eq.csv"
    perf_csv.write_text(
        "timestamp_iso,unix_ts,equity_usd\n2020-01-01T00:00:00Z,1000,250\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PERFORMANCE_EQUITY_CSV", str(perf_csv))
    server = DashboardServer(port=0)
    assert server._starting_equity == 250.0
    assert len(server._equity_history) == 1

    class _Ws:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_str(self, s: str) -> None:
            self.sent.append(json.loads(s))

    ws = _Ws()
    await server._handle_ws_message(ws, json.dumps({"type": "reset_performance_baseline"}))
    assert server._starting_equity is None
    assert len(server._equity_history) == 0
    assert perf_csv.read_text(encoding="utf-8").strip() == "timestamp_iso,unix_ts,equity_usd"
    assert any(m.get("type") == "control_ack" and m.get("ok") is True for m in ws.sent)


def test_dashboard_creates():
    server = DashboardServer(port=0)
    assert server.port == 0
    assert server._clients == set()


@pytest.mark.asyncio
async def test_dashboard_balance_poll_runs_immediately_on_first_tick():
    calls: list[float] = []

    class Ex:
        def get_collateral_balance(self) -> float:
            calls.append(1.0)
            return 250.0

    server = DashboardServer(port=0, exchange=Ex())
    assert server._last_balance_poll == 0.0
    await server._poll_balance()
    assert calls == [1.0]
    assert server._current_balance == 250.0


def test_dashboard_force_portfolio_snapshot_replays_latest_state():
    portfolio_state = _make_portfolio_state()
    server = DashboardServer(port=0, portfolio_state=portfolio_state)

    first = server._make_portfolio_message(force=True)
    second = server._make_portfolio_message(force=True)

    assert first is not None
    assert second is not None
    assert first["cash_balance"] == 42.0
    assert first["in_range_markets"] == 3
    assert second["cash_balance"] == 42.0
    assert second["in_range_markets"] == 3


@pytest.mark.asyncio
async def test_dashboard_http_serves_html():
    server = DashboardServer(port=0)
    app = aiohttp.web.Application()
    app.router.add_get("/", server._index)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:{port}/") as resp:
            assert resp.status == 200
            text = await resp.text()
            assert "Dashboard" in text
            assert "Performance" in text
            assert "In Range" in text

    await runner.cleanup()


@pytest.mark.asyncio
async def test_dashboard_http_serves_background_image():
    server = DashboardServer(port=0)
    app = aiohttp.web.Application()
    app.router.add_get("/nothingeverhappens.svg", server._background_image)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:{port}/nothingeverhappens.svg") as resp:
            assert resp.status == 200
            assert resp.headers["Content-Type"].startswith("image/svg+xml")
            text = await resp.text()
            assert "<svg" in text

    await runner.cleanup()


@pytest.mark.asyncio
async def test_dashboard_websocket_sends_initial_portfolio():
    server = DashboardServer(port=0, portfolio_state=_make_portfolio_state())
    app = aiohttp.web.Application()
    app.router.add_get("/ws", server._ws_handler)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"http://127.0.0.1:{port}/ws") as ws:
            message = await asyncio.wait_for(ws.receive_json(), timeout=2)
            assert message["type"] == "portfolio"
            assert message["cash_balance"] == 42.0
            assert message["in_range_markets"] == 3
            await ws.close()

    await runner.cleanup()


@pytest.mark.asyncio
async def test_dashboard_websocket_rejects_nothing_happens_target_updates():
    control_state = NothingHappensControlState()
    control_state.update_status(
        current_open_positions=0,
        pending_entry_count=0,
        remaining_capacity=None,
        opened_this_run=0,
    )
    server = DashboardServer(
        port=0,
        portfolio_state=_make_portfolio_state(),
        nothing_happens_control=control_state,
    )
    app = aiohttp.web.Application()
    app.router.add_get("/ws", server._ws_handler)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"http://127.0.0.1:{port}/ws") as ws:
            initial = await asyncio.wait_for(ws.receive_json(), timeout=2)
            assert initial["type"] == "portfolio"
            assert initial["controls_enabled"] is True
            perf = await asyncio.wait_for(ws.receive_json(), timeout=2)
            assert perf["type"] == "performance"
            assert perf["equity_usd"] == 42.0
            await ws.send_json({"type": "set_position_target", "target_open_positions": 17})
            ack = await asyncio.wait_for(ws.receive_json(), timeout=2)
            assert ack == {
                "type": "control_ack",
                "ok": False,
                "error": "controls_disabled",
            }
            await ws.close()

    assert control_state.snapshot().target_open_positions is None
    await runner.cleanup()
