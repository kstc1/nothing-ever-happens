"""Gasless CTF redeem for Polymarket deposit wallets (signature_type 3).

Submits an EIP-712 WALLET batch to the v2 relayer. The batch calls
redeemPositions on the pUSD collateral adapter, not ConditionalTokens
directly, and not a Gnosis Safe execTransaction.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

logger = logging.getLogger(__name__)

RELAYER_BASE = "https://relayer-v2.polymarket.com"
DEPOSIT_WALLET_FACTORY = "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07"
CTF_COLLATERAL_ADAPTER = "0xAdA100Db00Ca00073811820692005400218FcE1f"
NEG_RISK_CTF_COLLATERAL_ADAPTER = "0xadA2005600Dec949baf300f4C6120000bDB6eAab"
PUSD_ADDRESS = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
PARENT_COLLECTION_ID = b"\x00" * 32
BINARY_INDEX_SETS = [1, 2]
CONFIRM_POLL_SEC = 2.0
CONFIRM_TIMEOUT_SEC = 120.0

_REDEEM_ABI = [
    {
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "name": "redeemPositions",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


def adapter_address_for_position(position: dict) -> str:
    neg = position.get("negRisk")
    if neg is None:
        neg = position.get("negativeRisk")
    if neg is None:
        neg = position.get("negative_risk")
    if bool(neg):
        return NEG_RISK_CTF_COLLATERAL_ADAPTER
    return CTF_COLLATERAL_ADAPTER


def encode_redeem_positions_calldata(condition_id: str) -> str:
    cid_hex = condition_id[2:] if condition_id.startswith("0x") else condition_id
    condition_bytes = bytes.fromhex(cid_hex)
    w3 = Web3()
    ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF_COLLATERAL_ADAPTER), abi=_REDEEM_ABI)
    return ctf.encode_abi(
        "redeemPositions",
        [
            Web3.to_checksum_address(PUSD_ADDRESS),
            PARENT_COLLECTION_ID,
            condition_bytes,
            BINARY_INDEX_SETS,
        ],
    )


def _relayer_headers(api_key: str, api_key_address: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "RELAYER_API_KEY": api_key,
        "RELAYER_API_KEY_ADDRESS": api_key_address,
    }


def _http_json(method: str, url: str, headers: dict[str, str], body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        logger.error("deposit_wallet_relayer_http_error status=%s url=%s detail=%s", exc.code, url, detail)
        raise RuntimeError(f"Relayer HTTP {exc.code} for {url}: {detail}") from exc
    except Exception as exc:
        logger.error("deposit_wallet_relayer_request_failed url=%s err=%s", url, exc)
        raise
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"Relayer response was not an object: {type(parsed).__name__}")
    return parsed


def fetch_wallet_nonce(api_key: str, api_key_address: str, signer_address: str) -> int:
    query = urllib.parse.urlencode({"address": signer_address, "type": "WALLET"})
    url = f"{RELAYER_BASE}/v1/account/transactions/params?{query}"
    payload = _http_json("GET", url, _relayer_headers(api_key, api_key_address))
    nonce = payload.get("nonce")
    if nonce is None:
        logger.error("deposit_wallet_relayer_nonce_missing payload=%s", payload)
        raise RuntimeError("Relayer nonce response missing nonce")
    return int(nonce)


def sign_wallet_batch(
    private_key: str,
    deposit_wallet: str,
    nonce: int,
    deadline: int,
    calls: list[dict],
    chain_id: int,
) -> str:
    typed = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Call": [
                {"name": "target", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "data", "type": "bytes"},
            ],
            "Batch": [
                {"name": "wallet", "type": "address"},
                {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
                {"name": "calls", "type": "Call[]"},
            ],
        },
        "primaryType": "Batch",
        "domain": {
            "name": "DepositWallet",
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": Web3.to_checksum_address(deposit_wallet),
        },
        "message": {
            "wallet": Web3.to_checksum_address(deposit_wallet),
            "nonce": nonce,
            "deadline": deadline,
            "calls": [
                {
                    "target": Web3.to_checksum_address(str(call["target"])),
                    "value": int(call["value"]),
                    "data": bytes.fromhex(str(call["data"]).removeprefix("0x")),
                }
                for call in calls
            ],
        },
    }
    signed = Account.sign_message(encode_typed_data(full_message=typed), private_key=private_key)
    return signed.signature.to_0x_hex()


def wait_for_relayer_tx(api_key: str, api_key_address: str, transaction_id: str) -> dict:
    url = f"{RELAYER_BASE}/v1/account/transactions/{transaction_id}"
    headers = _relayer_headers(api_key, api_key_address)
    deadline = time.time() + CONFIRM_TIMEOUT_SEC
    last: dict = {}
    while time.time() < deadline:
        last = _http_json("GET", url, headers)
        state = str(last.get("state") or "")
        if state == "STATE_CONFIRMED":
            return last
        if state in {"STATE_FAILED", "STATE_INVALID"}:
            logger.error("deposit_wallet_relayer_terminal_failure tx=%s payload=%s", transaction_id, last)
            raise RuntimeError(f"Relayer tx {transaction_id} ended in {state}: {last.get('error_msg')}")
        time.sleep(CONFIRM_POLL_SEC)
    logger.error("deposit_wallet_relayer_confirm_timeout tx=%s last=%s", transaction_id, last)
    raise RuntimeError(f"Relayer tx {transaction_id} did not confirm in {CONFIRM_TIMEOUT_SEC}s")


def redeem_via_relayer(
    *,
    private_key: str,
    deposit_wallet: str,
    chain_id: int,
    relayer_api_key: str,
    relayer_api_key_address: str,
    position: dict,
    condition_id: str,
) -> dict:
    signer = Account.from_key(private_key)
    adapter = adapter_address_for_position(position)
    calldata = encode_redeem_positions_calldata(condition_id)
    nonce = fetch_wallet_nonce(relayer_api_key, relayer_api_key_address, signer.address)
    deadline = int(time.time()) + 240
    calls = [{"target": adapter, "value": "0", "data": calldata}]
    signature = sign_wallet_batch(private_key, deposit_wallet, nonce, deadline, calls, chain_id)
    body = {
        "type": "WALLET",
        "from": signer.address,
        "to": DEPOSIT_WALLET_FACTORY,
        "nonce": str(nonce),
        "signature": signature,
        "metadata": "Redeem positions",
        "depositWalletParams": {
            "depositWallet": Web3.to_checksum_address(deposit_wallet),
            "deadline": str(deadline),
            "calls": calls,
        },
    }
    submitted = _http_json(
        "POST",
        f"{RELAYER_BASE}/submit",
        _relayer_headers(relayer_api_key, relayer_api_key_address),
        body,
    )
    tx_id = submitted.get("transactionID") or submitted.get("transaction_id")
    if not tx_id:
        logger.error("deposit_wallet_relayer_submit_missing_id payload=%s", submitted)
        raise RuntimeError(f"Relayer submit missing transaction id: {submitted}")
    return wait_for_relayer_tx(relayer_api_key, relayer_api_key_address, str(tx_id))
