import json

import pytest

from bot.config import load_nothing_happens_config


def _write_config(tmp_path, payload) -> str:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload))
    return str(path)


def _base_config(*, connection=None, strategy_cfg=None):
    payload = {
        "connection": {
            "host": "https://clob.polymarket.com",
            "chain_id": 137,
            "signature_type": 2,
        },
        "strategies": {
            "nothing_happens": strategy_cfg or {},
        },
    }
    if connection:
        payload["connection"].update(connection)
    return payload


def test_load_nothing_happens_config_fails_without_config_file(monkeypatch) -> None:
    monkeypatch.setenv("CONFIG_PATH", "/nonexistent/config.json")
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_nothing_happens_config()


def test_load_nothing_happens_config_requires_strategy_section(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, {"connection": {}}))
    with pytest.raises(ValueError, match="Missing strategies.nothing_happens"):
        load_nothing_happens_config()


def test_load_nothing_happens_config_rejects_unsupported_strategy_selector(
    tmp_path,
    monkeypatch,
) -> None:
    payload = _base_config()
    payload["strategy"] = "instant_gap"
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))
    with pytest.raises(ValueError, match="Unsupported runtime strategy"):
        load_nothing_happens_config()


def test_load_nothing_happens_config_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("BOT_MODE", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("DASHBOARD_PORT", raising=False)
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    monkeypatch.delenv("FUNDER_ADDRESS", raising=False)
    monkeypatch.delenv("POLYGON_RPC_URL", raising=False)

    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, _base_config()))
    exchange, strategy, deploy = load_nothing_happens_config()

    assert exchange.host == "https://clob.polymarket.com"
    assert exchange.chain_id == 137
    assert strategy.market_refresh_interval_sec == 600
    assert strategy.portfolio_pct_per_trade == 0.02
    assert strategy.fixed_trade_amount == 0.0
    assert strategy.min_entry_price == 0.0
    assert strategy.max_entry_price == 0.65
    assert strategy.max_total_positions == -1
    assert strategy.shutdown_on_max_positions is False
    assert strategy.max_new_positions == -1
    assert strategy.risk_config.max_total_open_exposure_usd == 1_500.0
    assert strategy.risk_config.max_market_open_exposure_usd == 1_000.0


def test_load_nothing_happens_config_parses_risk_section(tmp_path, monkeypatch) -> None:
    payload = _base_config(
        strategy_cfg={
            "risk_config": {
                "max_total_open_exposure_usd": 250.0,
                "max_market_open_exposure_usd": 125.0,
                "max_daily_drawdown_usd": 10.0,
                "kill_switch_cooldown_sec": 30.0,
                "drawdown_arm_after_sec": 15.0,
                "drawdown_min_fresh_observations": 4,
            }
        }
    )
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))

    _, strategy, _ = load_nothing_happens_config()

    assert strategy.risk_config.max_total_open_exposure_usd == 250.0
    assert strategy.risk_config.max_market_open_exposure_usd == 125.0
    assert strategy.risk_config.max_daily_drawdown_usd == 10.0
    assert strategy.risk_config.kill_switch_cooldown_sec == 30.0
    assert strategy.risk_config.drawdown_arm_after_sec == 15.0
    assert strategy.risk_config.drawdown_min_fresh_observations == 4


def test_load_nothing_happens_config_applies_risk_env_overrides(tmp_path, monkeypatch) -> None:
    payload = _base_config(
        strategy_cfg={
            "risk_config": {
                "max_total_open_exposure_usd": 250.0,
                "max_market_open_exposure_usd": 125.0,
            }
        }
    )
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))
    monkeypatch.setenv("PM_RISK_MAX_TOTAL_OPEN_EXPOSURE_USD", "300")
    monkeypatch.setenv("PM_RISK_MAX_MARKET_OPEN_EXPOSURE_USD", "150")

    _, strategy, _ = load_nothing_happens_config()

    assert strategy.risk_config.max_total_open_exposure_usd == 300.0
    assert strategy.risk_config.max_market_open_exposure_usd == 150.0


def test_load_nothing_happens_config_applies_env_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, _base_config()))
    monkeypatch.setenv("PM_NH_FIXED_TRADE_AMOUNT_USD", "5")
    monkeypatch.setenv("PM_NH_MIN_ENTRY_PRICE", "0.11")
    monkeypatch.setenv("PM_NH_ORDER_DISPATCH_INTERVAL_SEC", "75")
    monkeypatch.setenv("PM_NH_MAX_TOTAL_POSITIONS", "2")
    monkeypatch.setenv("PM_NH_SHUTDOWN_ON_MAX_POSITIONS", "true")

    exchange, strategy, deploy = load_nothing_happens_config()

    assert exchange.host == "https://clob.polymarket.com"
    assert strategy.fixed_trade_amount == 5.0
    assert strategy.min_entry_price == 0.11
    assert strategy.order_dispatch_interval_sec == 75
    assert strategy.max_total_positions == 2
    assert strategy.shutdown_on_max_positions is True


def test_load_nothing_happens_config_validates_bounds(tmp_path, monkeypatch) -> None:
    payload = _base_config(
        strategy_cfg={
            "portfolio_pct_per_trade": 0,
            "min_entry_price": 0.8,
            "max_entry_price": 0.6,
        }
    )
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))
    with pytest.raises(ValueError, match="portfolio_pct_per_trade"):
        load_nothing_happens_config()


def test_load_nothing_happens_config_validates_min_entry_price_bounds(
    tmp_path,
    monkeypatch,
) -> None:
    payload = _base_config(strategy_cfg={"min_entry_price": -0.01})
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))
    with pytest.raises(ValueError, match="min_entry_price"):
        load_nothing_happens_config()


def test_load_nothing_happens_config_validates_min_not_greater_than_max_entry_price(
    tmp_path,
    monkeypatch,
) -> None:
    payload = _base_config(
        strategy_cfg={
            "min_entry_price": 0.8,
            "max_entry_price": 0.6,
        }
    )
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))
    with pytest.raises(ValueError, match="min_entry_price cannot be greater"):
        load_nothing_happens_config()


def test_load_nothing_happens_config_validates_risk_bounds(tmp_path, monkeypatch) -> None:
    payload = _base_config(
        strategy_cfg={
            "risk_config": {
                "max_total_open_exposure_usd": -1,
            }
        }
    )
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))
    with pytest.raises(ValueError, match="max_total_open_exposure_usd"):
        load_nothing_happens_config()


def test_load_nothing_happens_config_accepts_negative_one_for_unbounded_positions(
    tmp_path,
    monkeypatch,
) -> None:
    payload = _base_config(strategy_cfg={"max_total_positions": -1})
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))

    _, strategy, _ = load_nothing_happens_config()

    assert strategy.max_total_positions == -1


def test_load_nothing_happens_config_rejects_less_than_negative_one(
    tmp_path,
    monkeypatch,
) -> None:
    payload = _base_config(strategy_cfg={"max_total_positions": -2})
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))
    with pytest.raises(ValueError, match="max_total_positions must be >= -1"):
        load_nothing_happens_config()


def test_load_nothing_happens_config_uses_legacy_max_new_positions_as_fallback(
    tmp_path,
    monkeypatch,
) -> None:
    payload = _base_config(
        strategy_cfg={
            "max_new_positions": 7,
            "shutdown_on_max_new_positions": True,
        }
    )
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))

    _, strategy, _ = load_nothing_happens_config()

    assert strategy.max_total_positions == 7
    assert strategy.shutdown_on_max_positions is True


def test_load_nothing_happens_config_requires_private_key_when_live_send_enabled(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    monkeypatch.delenv("FUNDER_ADDRESS", raising=False)
    monkeypatch.delenv("POLYGON_RPC_URL", raising=False)
    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, _base_config()))
    monkeypatch.setenv("BOT_MODE", "live")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("DRY_RUN", "false")
    with pytest.raises(ValueError, match="PRIVATE_KEY"):
        load_nothing_happens_config()


def test_load_nothing_happens_config_requires_funder_for_proxy_wallets(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "CONFIG_PATH",
        _write_config(tmp_path, _base_config(connection={"signature_type": 2})),
    )
    monkeypatch.delenv("FUNDER_ADDRESS", raising=False)
    monkeypatch.delenv("POLYGON_RPC_URL", raising=False)
    monkeypatch.setenv("BOT_MODE", "live")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("PRIVATE_KEY", "0xabc")
    with pytest.raises(ValueError, match="FUNDER_ADDRESS"):
        load_nothing_happens_config()


def test_load_nothing_happens_config_requires_polygon_rpc_for_proxy_live(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "CONFIG_PATH",
        _write_config(tmp_path, _base_config(connection={"signature_type": 2})),
    )
    monkeypatch.setenv("BOT_MODE", "live")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("PRIVATE_KEY", "0xabc")
    monkeypatch.setenv("FUNDER_ADDRESS", "0x0000000000000000000000000000000000000001")
    monkeypatch.delenv("POLYGON_RPC_URL", raising=False)
    with pytest.raises(ValueError, match="POLYGON_RPC_URL"):
        load_nothing_happens_config()


def test_load_nothing_happens_config_deployment_section(tmp_path, monkeypatch) -> None:
    payload = _base_config()
    payload["deployment"] = {
        "bot_mode": "live",
        "dry_run": False,
        "live_trading_enabled": True,
        "database_url": "postgresql://user:pass@localhost/db",
        "dashboard_port": 9090,
    }
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("BOT_MODE", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("DASHBOARD_PORT", raising=False)

    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))
    monkeypatch.setenv("PRIVATE_KEY", "0xabc")
    monkeypatch.setenv("FUNDER_ADDRESS", "0x0000000000000000000000000000000000000001")
    monkeypatch.setenv("POLYGON_RPC_URL", "http://localhost:8545")

    _, _, deploy = load_nothing_happens_config()

    assert deploy.bot_mode == "live"
    assert deploy.dry_run is False
    assert deploy.live_trading_enabled is True
    assert deploy.database_url == "postgresql://user:pass@localhost/db"
    assert deploy.dashboard_port == 9090


def test_load_nothing_happens_config_env_overrides_deployment(tmp_path, monkeypatch) -> None:
    payload = _base_config()
    payload["deployment"] = {
        "bot_mode": "paper",
        "dashboard_port": 8080,
    }
    # We set these, but clear others to be safe
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    monkeypatch.setenv("CONFIG_PATH", _write_config(tmp_path, payload))
    monkeypatch.setenv("BOT_MODE", "live")
    monkeypatch.setenv("DASHBOARD_PORT", "9999")

    _, _, deploy = load_nothing_happens_config()

    assert deploy.bot_mode == "live"
    assert deploy.dashboard_port == 9999
