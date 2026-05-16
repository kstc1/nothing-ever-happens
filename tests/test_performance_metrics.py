"""Tests for portfolio performance metrics."""

import math

from bot.performance_metrics import (
    annualized_sharpe_ratio,
    annualized_sortino_ratio,
    compute_performance,
    equity_from_portfolio,
    _compound_apy_pct,
)
from bot.portfolio_state import PortfolioSnapshot, PositionSnapshot


def test_equity_from_portfolio_none_without_cash():
    snap = PortfolioSnapshot(positions=(), cash_balance=None)
    assert equity_from_portfolio(snap) is None


def test_equity_from_portfolio_cash_and_positions():
    pos = PositionSnapshot(
        slug="s",
        title="t",
        outcome="Yes",
        asset="x",
        condition_id="c",
        size=10.0,
        avg_price=0.4,
        initial_value=4.0,
        current_price=0.5,
        current_value=5.0,
        pnl_usd=1.0,
        pnl_pct=25.0,
        end_date="",
        eta_seconds=0.0,
    )
    snap = PortfolioSnapshot(positions=(pos,), cash_balance=100.0)
    assert equity_from_portfolio(snap) == 105.0


def test_compute_performance_return_and_apy():
    # 2 calendar days, +10% gain -> compound APY should be positive and large
    t0 = 1000.0
    t1 = t0 + 2 * 86400.0
    hist = [(t0, 100.0), (t1, 110.0)]
    p = compute_performance(hist, starting_equity_fallback=100.0)
    assert p is not None
    assert abs(p.total_return_pct - 10.0) < 1e-9
    assert p.apy_pct is not None and p.apy_pct > 100.0


def test_annualized_sharpe_positive_carry():
    # Steady tiny positive returns, stable vol -> positive Sharpe
    mean_dt = 86400.0  # daily
    returns = [0.001, 0.002, 0.001, 0.0015, 0.001]
    sh = annualized_sharpe_ratio(returns, mean_dt)
    assert sh is not None and sh > 1.0


def test_annualized_sortino_exceeds_sharpe_with_mild_drawdowns():
    mean_dt = 86400.0
    returns = [0.012, -0.004, 0.018, -0.002, 0.006]
    sh = annualized_sharpe_ratio(returns, mean_dt)
    so = annualized_sortino_ratio(returns, mean_dt)
    assert sh is not None and so is not None
    assert so > sh


def test_compute_performance_sortino_with_downside_moves():
    t0 = 0.0
    hist = [
        (t0, 100.0),
        (t0 + 86400.0, 102.0),
        (t0 + 172800.0, 101.0),
        (t0 + 259200.0, 104.0),
    ]
    p = compute_performance(hist, starting_equity_fallback=100.0)
    assert p is not None
    assert p.sharpe_ratio is not None
    assert p.sortino_ratio is not None


def test_compute_performance_strategy_elapsed_overrides_deque_span():
    t0 = 1_700_000_000
    hist = [(t0, 100.0), (t0 + 3600.0, 101.0)]
    p_deque = compute_performance(hist, starting_equity_fallback=100.0)
    assert p_deque is not None
    assert abs(p_deque.elapsed_seconds - 3600.0) < 1e-6
    p_override = compute_performance(
        hist,
        starting_equity_fallback=100.0,
        strategy_elapsed_seconds=86400.0 * 30,
    )
    assert p_override is not None
    assert abs(p_override.elapsed_seconds - 86400.0 * 30) < 1e-6
    assert p_override.apy_pct is not None


def test_compound_apy_extreme_growth_no_overflow():
    # Previously: growth ** (1/years) overflowed for large return / short window.
    r = _compound_apy_pct(100.0, 100_000.0, 7200.0)
    assert r is None or (math.isfinite(r) and abs(r) < 1e200)

