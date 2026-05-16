"""Print CLOB balance/allowance for the configured signer + funder (signature types 0–3).

Deposit wallet API users (`connection.signature_type` 3): after funding `FUNDER_ADDRESS`
with collateral, refresh the cache with `--sync-update` — same behavior as SDK
`signature_type = POLY_1271`.

See https://docs.polymarket.com/trading/deposit-wallets"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from bot.config import _load_config_file, _load_nothing_happens_config
from bot.exchange.polymarket_clob import PolymarketClobExchangeClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sync-update",
        action="store_true",
        help="Call CLOB update_balance_allowance for COLLATERAL first (recommended after deposits or allowances).",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to config.json (default: CONFIG_PATH env or ./config.json).",
    )
    args = parser.parse_args()

    load_dotenv()

    if args.config:
        cfg_raw = json.loads(Path(args.config).read_text(encoding="utf-8"))
    else:
        cfg_raw = _load_config_file()

    e, _s = _load_nothing_happens_config(cfg_raw)

    clob = PolymarketClobExchangeClient(
        e,
        allow_trading=True,
        clob_rate_limit_rps=5.0,
        clob_rate_limit_burst=10.0,
    )

    params = clob._balance_allowance_params(
        asset_type=clob._asset_type.COLLATERAL,
        signature_type=e.signature_type,
    )
    if args.sync_update:
        clob.client.update_balance_allowance(params=params)

    res = clob.client.get_balance_allowance(params=params)

    hint = ""
    if e.signature_type == 3:
        hint = (
            "\n(signature_type 3 POLY_1271: CLOB buys use collateral on "
            "`FUNDER_ADDRESS` / deposit wallet, not necessarily EOA on-chain USDC.)"
        )
    print(json.dumps(res, indent=2))
    if hint:
        print(hint)


if __name__ == "__main__":
    main()
