"""High-level portfolio snapshot: Data API positions, CLOB open orders, collateral balance cache.

Deposit wallet (`signature_type` 3): cash line reflects **CLOB** balance for `POLY_1271` /
`FUNDER_ADDRESS`. After funding deposit wallet collateral, refresh with `--sync-collateral-first`
or run `scripts/check_balance.py --sync-update`.

Docs: https://docs.polymarket.com/trading/deposit-wallets"""

import argparse
import json
from pathlib import Path

import requests
from dotenv import load_dotenv

from bot.config import _load_config_file, _load_nothing_happens_config
from bot.exchange.polymarket_clob import PolymarketClobExchangeClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, metavar="PATH", help="Path to config.json.")
    parser.add_argument(
        "--sync-collateral-first",
        action="store_true",
        help="Call CLOB update_balance_allowance (COLLATERAL) before reading balance.",
    )
    args = parser.parse_args()

    load_dotenv()

    cfg_raw = (
        json.loads(Path(args.config).read_text(encoding="utf-8"))
        if args.config
        else _load_config_file()
    )
    e, _s = _load_nothing_happens_config(cfg_raw)

    clob = PolymarketClobExchangeClient(e, allow_trading=True, clob_rate_limit_rps=5.0, clob_rate_limit_burst=10.0)

    wallet = e.funder_address if e.signature_type in (1, 2, 3) and e.funder_address else "unknown"
    print(f"CLOB-facing wallet (`FUNDER_ADDRESS` when typed): {wallet}")
    print(f"signature_type: {e.signature_type}")

    res = requests.get(
        f"https://data-api.polymarket.com/positions?user={wallet}&redeemable=false",
        timeout=30,
    )
    positions = res.json() if res.status_code == 200 else []
    total_val = 0.0
    for p in positions:
        if isinstance(p, dict):
            total_val += float(p.get("currentValue", 0))

    print(f"Open Positions Value: {total_val}")

    orders = clob.client.get_orders(clob._open_order_params())
    locked_usd = 0.0
    for o in orders:
        if isinstance(o, dict) and o.get("side") == "BUY":
            price = float(o.get("price", 0))
            size = float(o.get("original_size", o.get("size", 0)))
            matched = float(o.get("size_matched", 0))
            locked_usd += price * (size - matched)

    print(f"Locked in Buy Orders: {locked_usd}")

    params = clob._balance_allowance_params(asset_type=clob._asset_type.COLLATERAL, signature_type=e.signature_type)
    if args.sync_collateral_first:
        clob.client.update_balance_allowance(params=params)

    bal = clob.client.get_balance_allowance(params=params)
    cash = float(bal.get("balance", 0)) / 1e6
    print(f"Cash (Available, CLOB): {cash}")

    print(f"Total Portfolio Value Estimate: {total_val + locked_usd + cash}")
    if e.signature_type == 3:
        print("(POLY_1271 deposits: fund `FUNDER_ADDRESS`, then `--sync-collateral-first` once after changes.)")


if __name__ == "__main__":
    main()
