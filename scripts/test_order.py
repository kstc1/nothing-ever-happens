import json
import os
from dotenv import load_dotenv

from bot.config import _load_nothing_happens_config
from bot.exchange.polymarket_clob import PolymarketClobExchangeClient
from py_clob_client.clob_types import OrderArgs, OrderType

def main():
    load_dotenv()
    with open("config.json") as f:
        cfg_raw = json.load(f)
    e, s = _load_nothing_happens_config(cfg_raw)
    
    clob = PolymarketClobExchangeClient(e, allow_trading=True, clob_rate_limit_rps=5.0, clob_rate_limit_burst=10.0)
    
    order_args = clob._order_args(
        price=0.5,
        size=10,
        side=clob._buy,
        token_id="61020455292630745581535812453282662780976642538387697712385466477732102349880",
    )
    
    signed_order = clob.client.create_order(order_args)
    print("Signed order:")
    print(vars(signed_order))

    # Try posting to test API or just inspect it
    try:
        res = clob.client.post_order(signed_order, OrderType.GTC)
        print("Post order success:")
        print(res)
        if isinstance(res, dict) and "orderID" in res:
            clob.client.cancel_order(res["orderID"])
    except Exception as exc:
        print("Post order failed:", exc)

if __name__ == "__main__":
    main()
