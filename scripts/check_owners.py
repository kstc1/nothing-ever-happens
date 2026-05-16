"""Inspect `FUNDER_ADDRESS` on Polygon.

For Gnosis Safe / proxy setups (`signature_type` 2), probes `getOwners()` when the contract behaves like Safe.

For new API deposit wallets (`signature_type` 3 / POLY_1271), there is **no** `getOwners()` view —
the wallet is an ERC-1967 proxy deployed via relayer `WALLET-CREATE`. Confirm the deterministic
deposit address via explorer or `py-builder-relayer-client` (`get_expected_deposit_wallet()`).

Polygon mainnet factory (Polymarket docs): 0x00000000000Fb5C9ADea0298D729A0CB3823Cc07

Docs: https://docs.polymarket.com/trading/deposit-wallets"""

import argparse
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3

from bot.config import _load_config_file, _load_nothing_happens_config

logger = logging.getLogger(__name__)

DEPOSIT_WALLET_FACTORY_137 = "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to config.json (default: CONFIG_PATH env or ./config.json).",
    )
    args = parser.parse_args()

    load_dotenv()

    cfg_raw = (
        json.loads(Path(args.config).read_text(encoding="utf-8"))
        if args.config
        else _load_config_file()
    )
    try:
        ex, _ = _load_nothing_happens_config(cfg_raw)
    except Exception as exc:
        logger.error(
            "check_owners_load_config_failed: could not derive exchange cfg err=%s",
            exc,
            exc_info=True,
        )
        raise SystemExit(f"Could not load config: {exc}") from exc

    rpc = (os.getenv("POLYGON_RPC_URL", "").strip() or ex.polygon_rpc_url or "").strip()
    if not rpc:
        logger.error("check_owners_missing_rpc: POLYGON_RPC_URL unset and not in config")
        raise SystemExit("POLYGON_RPC_URL required")

    funder_raw = (os.getenv("FUNDER_ADDRESS", "").strip() or ex.funder_address or "").strip()
    if not funder_raw:
        logger.error("check_owners_missing_funder")
        raise SystemExit("Set FUNDER_ADDRESS env or funder_address in secrets/config backing")

    w3 = Web3(Web3.HTTPProvider(rpc))
    proxy = Web3.to_checksum_address(funder_raw)
    print(f"FUNDER_ADDRESS: {proxy}")

    bytecode = (w3.eth.get_code(proxy) or b"").hex()
    print(f"On-chain bytecode len: {len(bytecode) // 2 if bytecode else 0}")
    print(f"signature_type (exchange config): {ex.signature_type}  chain_id: {ex.chain_id}")

    if ex.signature_type == 3:
        print(
            "POLY_1271 deposit wallet path — skipping `Safe.getOwners()`.\n"
            "- Documented factory (Polygon mainnet 137):\n"
            f"    {DEPOSIT_WALLET_FACTORY_137}\n"
            "- Relayer `WALLET-CREATE` / `WALLET` batches handle ops; CLOB uses maker/signer = deposit wallet.\n",
        )
        return

    safe = w3.eth.contract(
        address=proxy,
        abi=[
            {
                "constant": True,
                "inputs": [],
                "name": "getOwners",
                "outputs": [{"name": "", "type": "address[]"}],
                "type": "function",
            }
        ],
    )

    try:
        owners = safe.functions.getOwners().call()
        print(f"Owners (Gnosis Safe getOwners): {owners}")
    except Exception as exc:
        print(f"Not a standard Gnosis Safe or getOwners unavailable: {exc}")


if __name__ == "__main__":
    main()
