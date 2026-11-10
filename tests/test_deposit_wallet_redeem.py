from unittest.mock import MagicMock, patch

import pytest

from bot.deposit_wallet_redeem import (
    CTF_COLLATERAL_ADAPTER,
    NEG_RISK_CTF_COLLATERAL_ADAPTER,
    RELAYER_USER_AGENT,
    _relayer_headers,
    adapter_address_for_position,
    encode_redeem_positions_calldata,
)
from bot.redeemer import Redeemer


def test_adapter_address_uses_standard_adapter_when_not_neg_risk():
    assert adapter_address_for_position({"negRisk": False}) == CTF_COLLATERAL_ADAPTER


def test_adapter_address_uses_neg_risk_adapter():
    assert adapter_address_for_position({"negativeRisk": True}) == NEG_RISK_CTF_COLLATERAL_ADAPTER


def test_relayer_headers_include_user_agent_for_cloudflare():
    headers = _relayer_headers("rk-test", "0xsigner")
    assert headers["User-Agent"] == RELAYER_USER_AGENT
    assert headers["RELAYER_API_KEY"] == "rk-test"


def test_encode_redeem_positions_calldata_is_nonempty():
    data = encode_redeem_positions_calldata("0x" + "aa" * 32)
    assert data.startswith("0x")
    assert len(data) > 10


def test_execute_redeem_type3_does_not_call_safe_exec():
    redeemer = Redeemer(
        private_key="0x" + "ab" * 32,
        proxy_address="0x" + "cd" * 20,
        chain_id=137,
        rpc_url="https://polygon-rpc.com",
        signature_type=3,
        relayer_api_key="rk",
        relayer_api_key_address="0xsigner",
    )
    mock_w3 = MagicMock()
    mock_ctf = MagicMock()
    with patch.object(redeemer, "_execute_deposit_wallet_redeem") as mock_v3:
        redeemer._execute_redeem(mock_w3, mock_ctf, "0xct", b"\xaa" * 32, {"negRisk": False})
    mock_v3.assert_called_once()
    mock_w3.eth.send_raw_transaction.assert_not_called()
