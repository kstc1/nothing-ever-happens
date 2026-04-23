import json
import os
from dotenv import load_dotenv

from bot.config import _load_nothing_happens_config
from bot.exchange.polymarket_clob import PolymarketClobExchangeClient

def main():
    load_dotenv()
    with open("config.json") as f:
        cfg_raw = json.load(f)
    e, s = _load_nothing_happens_config(cfg_raw)
    
    clob = PolymarketClobExchangeClient(e, allow_trading=True, clob_rate_limit_rps=5.0, clob_rate_limit_burst=10.0)
    
    # Raw call
    res = clob.client.get_balance_allowance(
        params=clob._balance_allowance_params(
            asset_type=clob._asset_type.COLLATERAL,
            signature_type=2
        )
    )
    print("Raw balance_allowance response:", json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
