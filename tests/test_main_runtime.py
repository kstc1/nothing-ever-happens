from unittest.mock import patch

import pytest

from bot.config import ExchangeConfig, NothingHappensConfig
from bot.exchange.paper import PaperExchangeClient
from bot.main import (
    _build_exchange,
    _build_live_redeemer,
    _resolve_live_wallet_address,
    _validate_live_runtime,
)
from bot.secret_str import SecretStr


def test_validate_live_runtime_requires_database_url():
    exchange = ExchangeConfig(
        host="https://clob.polymarket.com",
        chain_id=137,
        signature_type=2,
        private_key=SecretStr("0xabc"),
        funder_address="0xfunder",
        live_send_enabled=True,
    )
    with pytest.raises(ValueError, match="DATABASE_URL"):
        _validate_live_runtime(exchange, None)


def test_build_exchange_uses_paper_client_when_live_send_disabled():
    exchange = ExchangeConfig(
        host="https://clob.polymarket.com",
        chain_id=137,
        signature_type=2,
        private_key=None,
        funder_address=None,
        live_send_enabled=False,
    )
    strategy = NothingHappensConfig()
    built = _build_exchange(exchange, strategy)
    assert isinstance(built, PaperExchangeClient)


def test_build_exchange_uses_live_client_when_enabled():
    exchange = ExchangeConfig(
        host="https://clob.polymarket.com",
        chain_id=137,
        signature_type=0,
        private_key=SecretStr("0xabc"),
        funder_address=None,
        live_send_enabled=True,
    )
    strategy = NothingHappensConfig()
    sentinel = object()
    with patch("bot.exchange.polymarket_clob.PolymarketClobExchangeClient", return_value=sentinel) as factory:
        built = _build_exchange(exchange, strategy)
    assert built is sentinel
    factory.assert_called_once_with(
        exchange,
        allow_trading=True,
        clob_rate_limit_rps=strategy.clob_rate_limit_rps,
        clob_rate_limit_burst=strategy.clob_rate_limit_burst,
    )


def test_resolve_live_wallet_address_uses_signer_for_direct_eoa():
    exchange = ExchangeConfig(
        host="https://clob.polymarket.com",
        chain_id=137,
        signature_type=0,
        private_key=SecretStr("0xabc"),
        funder_address=None,
        live_send_enabled=True,
    )
    signer = type("Signer", (), {"address": "0xsigner"})()
    with patch("eth_account.Account.from_key", return_value=signer) as from_key:
        wallet_address = _resolve_live_wallet_address(exchange)
    assert wallet_address == "0xsigner"
    from_key.assert_called_once_with("0xabc")


def _live_exchange(**overrides) -> ExchangeConfig:
    values = dict(
        host="https://clob.polymarket.com",
        chain_id=137,
        signature_type=2,
        private_key=SecretStr("0xabc"),
        funder_address="0xfunder",
        polygon_rpc_url="https://polygon-rpc.com",
        live_send_enabled=True,
    )
    values.update(overrides)
    return ExchangeConfig(**values)


def test_build_live_redeemer_starts_for_safe_v2():
    redeemer = _build_live_redeemer(_live_exchange(), NothingHappensConfig(auto_redeem_enabled=True))
    assert redeemer is not None
    assert redeemer._signature_type == 2


def test_build_live_redeemer_starts_for_deposit_wallet_v3(monkeypatch):
    monkeypatch.setenv("RELAYER_API_KEY", "rk")
    monkeypatch.setenv("RELAYER_API_KEY_ADDRESS", "0xsigner")
    exchange = _live_exchange(signature_type=3, polygon_rpc_url=None)
    redeemer = _build_live_redeemer(exchange, NothingHappensConfig(auto_redeem_enabled=True))
    assert redeemer is not None
    assert redeemer._signature_type == 3


def test_build_live_redeemer_type3_raises_without_relayer_keys(monkeypatch):
    monkeypatch.delenv("RELAYER_API_KEY", raising=False)
    monkeypatch.delenv("RELAYER_API_KEY_ADDRESS", raising=False)
    monkeypatch.delenv("POLYMARKET_RELAYER_API_KEY", raising=False)
    monkeypatch.delenv("POLYMARKET_RELAYER_API_KEY_ADDRESS", raising=False)
    exchange = _live_exchange(signature_type=3, polygon_rpc_url=None)
    with pytest.raises(ValueError, match="RELAYER_API_KEY"):
        _build_live_redeemer(exchange, NothingHappensConfig(auto_redeem_enabled=True))
