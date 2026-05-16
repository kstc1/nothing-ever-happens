"""Probe USDC balances on Polygon for `FUNDER_ADDRESS` (deposit wallet / Safe / proxy).

POLY_1271 deposit wallets (`signature_type` 3): CLOB buys draw from collateral on `FUNDER_ADDRESS`.
On-chain allowances for trading must come from deposit-wallet relayer WALLET batches, not EOA EOA txs.

Docs: https://docs.polymarket.com/trading/deposit-wallets"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3

from bot.config import _load_config_file, _load_nothing_happens_config
from bot.exchange.polymarket_clob import PolymarketClobExchangeClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to config.json.",
    )
    args = parser.parse_args()

    load_dotenv()

    cfg_raw = (
        json.loads(Path(args.config).read_text(encoding="utf-8"))
        if args.config
        else _load_config_file()
    )
    e, _s = _load_nothing_happens_config(cfg_raw)

    if not e.polygon_rpc_url:
        raise SystemExit("POLYGON_RPC_URL required in env or reachable from exchange config.")

    clob = PolymarketClobExchangeClient(
        e,
        allow_trading=True,
        clob_rate_limit_rps=5.0,
        clob_rate_limit_burst=10.0,
    )
    proxy_raw = clob.funder_address
    if not proxy_raw:
        raise SystemExit("Configure FUNDER_ADDRESS for signature types 1–3.")

    w3 = Web3(Web3.HTTPProvider(e.polygon_rpc_url))
    proxy = Web3.to_checksum_address(proxy_raw)

    label = (
        "Funder (deposit wallet / proxy / Safe)"
        if e.signature_type in {1, 2, 3}
        else "Funder / trading address"
    )
    print(f"{label}: {proxy}")
    print(f"(signature_type={e.signature_type})")

    usdc_e = w3.eth.contract(
        address=Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"),
        abi=[
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            }
        ],
    )
    usdc_native = w3.eth.contract(
        address=Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"),
        abi=[
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            }
        ],
    )

    print(f"USDC.e Balance: {usdc_e.functions.balanceOf(proxy).call() / 1e6}")
    print(f"Native USDC Balance: {usdc_native.functions.balanceOf(proxy).call() / 1e6}")
    print(f"POL Balance: {w3.eth.get_balance(proxy) / 1e18}")

    orders = clob.client.get_orders(clob._open_order_params())
    locked = 0.0
    for o in orders:
        if o.get("side") == "BUY":
            price = float(o.get("price", 0))
            size = float(o.get("original_size", 0))
            matched = float(o.get("size_matched", 0))
            locked += price * (size - matched)
    print(f"Approx USDC notionally locked in open buy orders (CLOB): {locked}")


if __name__ == "__main__":
    main()
