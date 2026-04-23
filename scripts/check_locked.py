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
        
    res2 = requests.get(f"https://clob.polymarket.com/orders?maker={funder}&status=OPEN")
    print("CLOB Open Orders HTTP response:")
    print(res2.json())

if __name__ == "__main__":
    main()
