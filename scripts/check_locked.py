"""Rough estimate of BUY-side notional shown by the public Gamma `orders` API for `user`.

Prefer `scripts/check_open_orders.py` with L2-authenticated responses for authoritative CLOB v2 fills.

Deposit wallet POLY flows use `FUNDER_ADDRESS` as maker on posted orders — set env or derive from config.

Docs: https://docs.polymarket.com/trading/deposit-wallets"""

import logging
import os
import sys

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DATA_API_BASE = "https://data-api.polymarket.com"


def _resolve_user_address() -> str:
    explicit = (os.getenv("FUNDER_ADDRESS") or "").strip()
    if explicit:
        return explicit
    try:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        sys.path.insert(0, repo_root)
        from bot.config import _load_config_file, _load_nothing_happens_config

        ex, _ = _load_nothing_happens_config(_load_config_file())
        if ex.funder_address:
            print(f"(Using FUNDER_ADDRESS from config-derived exchange cfg: {ex.funder_address})")
            return ex.funder_address.strip()
    except Exception as exc:
        logger.warning(
            "check_locked_resolve_from_config_failed: %s — set FUNDER_ADDRESS env",
            exc,
            exc_info=True,
        )
    raise SystemExit("Set FUNDER_ADDRESS or ensure config resolves a funder (signature types 1–3)")


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=os.getenv("SCRIPT_LOG_LEVEL", "WARNING"))

    funder = _resolve_user_address()
    res = requests.get(f"{DATA_API_BASE}/orders?user={funder}&limit=100", timeout=30)
    if res.status_code == 200:
        data = res.json()
        print(f"Total open orders found in Data API snapshot: {len(data)}")
        locked = 0.0
        for o in data:
            if o.get("side") == "BUY":
                size = float(o.get("size", 0))
                matched = float(o.get("sizeMatched", 0))
                price = float(o.get("price", 0))
                locked += (size - matched) * price
        print(f"Estimated locked USDC in open buy orders: {locked}")
    else:
        logger.error(
            "check_locked_gamma_orders_failed status=%s body_preview=%s",
            res.status_code,
            (res.text or "")[:200],
        )
        print("Failed to fetch Data API orders")

    print(
        "For authenticated CLOB v2 opens use: python scripts/check_open_orders.py "
        "(host https://clob.polymarket.com + sdk `get_orders`).",
    )


if __name__ == "__main__":
    main()
