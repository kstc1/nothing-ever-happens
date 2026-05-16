"""Exercise CLOB signing + POST with the exact `signature_type`/funder from config.json.

For deposit wallets configure `signature_type` 3 and `POLY_1271` CLOB semantics (maker/signer
= `FUNDER_ADDRESS`, wrapped signatures). Requires valid API creds and token id env if you customize.

Deposit wallet onboarding (relayer `WALLET-CREATE`): use Polymarket builder relayer client / docs.

Docs: https://docs.polymarket.com/trading/deposit-wallets
"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from py_clob_client_v2.clob_types import OrderType

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
    parser.add_argument(
        "--cancel",
        action="store_true",
        help="Attempt to cancel the posted order immediately after placement.",
    )
    args = parser.parse_args()

    load_dotenv()

    cfg_raw = (
        json.loads(Path(args.config).read_text(encoding="utf-8"))
        if args.config
        else _load_config_file()
    )
    exchange_cfg, _s = _load_nothing_happens_config(cfg_raw)

    clob = PolymarketClobExchangeClient(
        exchange_cfg,
        allow_trading=True,
        clob_rate_limit_rps=5.0,
        clob_rate_limit_burst=10.0,
    )

    order_args = clob._order_args(
        price=0.5,
        size=10,
        side=clob._buy,
        token_id="61020455292630745581535812453282662780976642538387697712385466477732102349880",
    )

    signed_order = clob.client.create_order(order_args)
    print("Signed order:")
    print(vars(signed_order))

    try:
        res = clob.client.post_order(signed_order, OrderType.GTC)
        print("Post order success:")
        print(res)
        if args.cancel and isinstance(res, dict) and "orderID" in res:
            clob.client.cancel_order(res["orderID"])
    except Exception as exc:
        print("Post order failed:", exc)


if __name__ == "__main__":
    main()
