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
    
    open_orders = clob.client.get_open_orders(clob._open_order_params())
    print("Open Orders:")
    for o in open_orders:
        print(f"ID: {o.get('id')}, Price: {o.get('price')}, Size: {o.get('original_size')}, Token: {o.get('asset_id')}")

if __name__ == "__main__":
    main()
