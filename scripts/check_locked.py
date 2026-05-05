import requests
import os
from dotenv import load_dotenv

def main():
    load_dotenv()
    funder = os.getenv("FUNDER_ADDRESS")
    res = requests.get(f"https://data-api.polymarket.com/orders?user={funder}&limit=100")
    if res.status_code == 200:
        data = res.json()
        print(f"Total open orders found in Gamma API: {len(data)}")
        locked = 0.0
        for o in data:
            if o.get("side") == "BUY":
                size = float(o.get("size", 0))
                matched = float(o.get("sizeMatched", 0))
                price = float(o.get("price", 0))
                locked += (size - matched) * price
        print(f"Estimated locked USDC in open buy orders: {locked}")
    else:
        print("Failed to fetch Gamma API orders")
        
    # CLOB v2 lists orders at /data/orders with L2 (API key) auth — not public GET /orders.
    print(
        "For authenticated CLOB v2 open orders use: python scripts/check_open_orders.py "
        "(host https://clob.polymarket.com + paths like /data/orders from py_clob_client_v2)."
    )

if __name__ == "__main__":
    main()
