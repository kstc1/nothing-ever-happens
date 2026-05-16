"""List open CLOB orders for the authenticated signer (L2 creds from py-clob-client-v2).

Deposit wallet (`signature_type` 3) orders use POLY_1271 and still appear via this client when configured.

Docs: https://docs.polymarket.com/trading/deposit-wallets"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from bot.config import _load_config_file, _load_nothing_happens_config
from bot.exchange.polymarket_clob import PolymarketClobExchangeClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, metavar="PATH", help="Path to config.json.")
    args = parser.parse_args()

    load_dotenv()

    cfg_raw = (
        json.loads(Path(args.config).read_text(encoding="utf-8"))
        if args.config
        else _load_config_file()
    )
    e, _s = _load_nothing_happens_config(cfg_raw)

    clob = PolymarketClobExchangeClient(e, allow_trading=True, clob_rate_limit_rps=5.0, clob_rate_limit_burst=10.0)

    open_orders = clob.client.get_open_orders(clob._open_order_params())
    print("Open Orders:")
    for o in open_orders:
        print(
            f"ID: {o.get('id')}, Price: {o.get('price')}, Size: {o.get('original_size')}, Token: {o.get('asset_id')}"
        )


if __name__ == "__main__":
    main()
