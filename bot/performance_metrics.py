"""Portfolio equity performance metrics (return, APY, Sharpe, Sortino) from time series."""

from __future__ import annotations

import math
from dataclasses import dataclass

from bot.portfolio_state import PortfolioSnapshot

# Minimum history span to show annualized figures (avoid absurd APY when t→0)
_MIN_APY_ELAPSED_SEC = 3600.0  # 1 hour
# Minimum simple returns for Sharpe/Sortino denominators to be finite
_MIN_RISK_METRIC_RETURNS = 2


@dataclass(frozen=True)
class PerformanceSnapshot:
    equity_usd: float
    starting_equity_usd: float
    total_return_pct: float
    apy_pct: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    elapsed_seconds: float
    sample_count: int


def equity_from_portfolio(snapshot: PortfolioSnapshot) -> float | None:
    """Total equity = cash + sum of position mark values. None if cash is unknown."""
    if snapshot.cash_balance is None:
        return None
    cash = float(snapshot.cash_balance)
    positions_value = sum(float(p.current_value) for p in snapshot.positions)
    return cash + positions_value


# Cap exp() input so APY cannot overflow float (exp(709) ~ 8e307)
_MAX_APY_LOG_SCALE = 700.0


def _compound_apy_pct(
    start_equity: float,
    end_equity: float,
    elapsed_sec: float,
) -> float | None:
    if elapsed_sec < _MIN_APY_ELAPSED_SEC or start_equity <= 0:
        return None
    if end_equity <= 0:
        return None
    years = elapsed_sec / (365.25 * 24 * 3600)
    if years <= 0:
        return None
    growth = end_equity / start_equity
    if growth <= 0:
        return None
    # growth ** (1/years) == exp(log(growth) / years); direct pow overflows when exponent is huge.
    try:
        log_g = math.log(growth)
    except ValueError:
        return None
    log_scale = log_g / years
    if log_scale > _MAX_APY_LOG_SCALE or log_scale < -745.0:
        return None
    try:
        compounded = math.exp(log_scale)
    except OverflowError:
        return None
    if not math.isfinite(compounded):
        return None
    return (compounded - 1.0) * 100.0


def _period_returns(equity_points: list[tuple[float, float]]) -> tuple[list[float], float | None]:
    """Simple returns between consecutive equity samples; mean dt in seconds."""
    if len(equity_points) < 2:
        return [], None
    ordered = sorted(equity_points, key=lambda x: x[0])
    returns: list[float] = []
    dts: list[float] = []
    for i in range(1, len(ordered)):
        _, prev_e = ordered[i - 1]
        t_i, e_i = ordered[i]
        t_prev, _ = ordered[i - 1]
        dt = t_i - t_prev
        if dt <= 0 or prev_e <= 0:
            continue
        dts.append(dt)
        returns.append((e_i - prev_e) / prev_e)
    if not returns:
        return [], None
    mean_dt = sum(dts) / len(dts)
    return returns, mean_dt


def annualized_sharpe_ratio(returns: list[float], mean_period_seconds: float) -> float | None:
    """
    Sharpe of simple per-period returns, annualized via sqrt(periods per year).
    Risk-free rate assumed 0 (appropriate for short crypto-style holding).
    """
    if len(returns) < _MIN_RISK_METRIC_RETURNS or mean_period_seconds <= 0:
        return None
    mean_r = sum(returns) / len(returns)
    if len(returns) >= 2:
        var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(var)
    else:
        std = 0.0
    if std <= 1e-12:
        return None
    periods_per_year = (365.25 * 24 * 3600) / mean_period_seconds
    if periods_per_year <= 0:
        return None
    return (mean_r / std) * math.sqrt(periods_per_year)


def annualized_sortino_ratio(
    returns: list[float],
    mean_period_seconds: float,
    *,
    mar: float = 0.0,
) -> float | None:
    """
    Sortino using simple period returns vs MAR (default 0), annualized like Sharpe.
    Downside deviation: sqrt(mean(min(0, r - MAR)^2)) over all periods.
    """
    if len(returns) < _MIN_RISK_METRIC_RETURNS or mean_period_seconds <= 0:
        return None
    n = len(returns)
    mean_excess = sum(returns) / n - mar
    downside_sq = sum(min(0.0, r - mar) ** 2 for r in returns) / n
    dd = math.sqrt(downside_sq)
    if dd <= 1e-12:
        return None
    periods_per_year = (365.25 * 24 * 3600) / mean_period_seconds
    if periods_per_year <= 0:
        return None
    return (mean_excess / dd) * math.sqrt(periods_per_year)


def compute_performance(
    history: list[tuple[float, float]],
    *,
    starting_equity_fallback: float | None,
    strategy_elapsed_seconds: float | None = None,
) -> PerformanceSnapshot | None:
    """
    history: (unix_ts, equity_usd) samples, oldest→newest not required (sorted inside).
    strategy_elapsed_seconds: if set (e.g. persisted first-sample time), used for APY and
        elapsed_seconds UI; otherwise inferred from the first/last points in history.
    """
    if not history:
        return None
    ordered = sorted(history, key=lambda x: x[0])
    first_ts = ordered[0][0]
    last_ts, end_e = ordered[-1]
    start_effective = float(ordered[0][1])
    if starting_equity_fallback is not None and starting_equity_fallback > 0:
        start_effective = float(starting_equity_fallback)

    deque_elapsed = max(0.0, last_ts - first_ts)
    if start_effective <= 0:
        return None

    elapsed_metrics = (
        float(strategy_elapsed_seconds)
        if strategy_elapsed_seconds is not None and strategy_elapsed_seconds >= 0
        else deque_elapsed
    )

    total_return_pct = ((end_e / start_effective) - 1.0) * 100.0
    apy = _compound_apy_pct(start_effective, end_e, elapsed_metrics)

    returns, mean_dt = _period_returns(ordered)
    sharpe = None
    sortino = None
    if returns and mean_dt is not None:
        sharpe = annualized_sharpe_ratio(returns, mean_dt)
        sortino = annualized_sortino_ratio(returns, mean_dt)

    return PerformanceSnapshot(
        equity_usd=float(end_e),
        starting_equity_usd=float(start_effective),
        total_return_pct=float(total_return_pct),
        apy_pct=apy,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        elapsed_seconds=float(elapsed_metrics),
        sample_count=len(ordered),
    )
