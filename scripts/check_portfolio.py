import json
import os
from dotenv import load_dotenv
import requests

from bot.config import _load_nothing_happens_config
from bot.exchange.polymarket_clob import PolymarketClobExchangeClient

def main():
    load_dotenv()
    with open("config.json") as f:
        cfg_raw = json.load(f)
    e, s = _load_nothing_happens_config(cfg_raw)
    
    clob = PolymarketClobExchangeClient(e, allow_trading=True, clob_rate_limit_rps=5.0, clob_rate_limit_burst=10.0)
    
    wallet = e.funder_address if e.signature_type in (1,2) and e.funder_address else "unknown"
    print(f"Wallet: {wallet}")
    
    # Fetch positions from Gamma API
    res = requests.get(f"https://data-api.polymarket.com/positions?user={wallet}&redeemable=false")
    positions = res.json()
    
    total_val = 0.0
    for p in positions:
        val = float(p.get("currentValue", 0))
        total_val += val
        
    print(f"Open Positions Value: {total_val}")
    
    # Check open orders
    orders = clob.client.get_orders(clob._open_order_params())
    locked_usd = 0.0
    for o in orders:
        if o.get("side") == "BUY":
            price = float(o.get("price", 0))
            size = float(o.get("original_size", o.get("size", 0)))
            matched = float(o.get("size_matched", 0))
            locked_usd += price * (size - matched)
            
    print(f"Locked in Buy Orders: {locked_usd}")
    
    # Check balance
    bal = clob.client.get_balance_allowance(
        params=clob._balance_allowance_params(asset_type=clob._asset_type.COLLATERAL, signature_type=e.signature_type)
    )
    cash = float(bal.get("balance", 0)) / 1e6
    print(f"Cash (Available): {cash}")
    
    print(f"Total Portfolio Value Estimate: {total_val + locked_usd + cash}")

if __name__ == "__main__":
    main()
