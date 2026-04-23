import json
import os
from dotenv import load_dotenv

from bot.config import _load_nothing_happens_config
from bot.exchange.polymarket_clob import PolymarketClobExchangeClient
from web3 import Web3

def main():
    load_dotenv()
    with open("config.json") as f:
        cfg_raw = json.load(f)
    e, s = _load_nothing_happens_config(cfg_raw)
    
    clob = PolymarketClobExchangeClient(e, allow_trading=True, clob_rate_limit_rps=5.0, clob_rate_limit_burst=10.0)
    proxy = clob.funder_address
    
    w3 = Web3(Web3.HTTPProvider(e.polygon_rpc_url))
    print(f"Proxy Address: {proxy}")
    
    # USDC.e
    usdc_e = w3.eth.contract(address=Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"), abi=[{
        "constant": True, "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"
    }])
    # Native USDC
    usdc = w3.eth.contract(address=Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"), abi=[{
        "constant": True, "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"
    }])
    
    e_bal = usdc_e.functions.balanceOf(proxy).call() / 1e6
    n_bal = usdc.functions.balanceOf(proxy).call() / 1e6
    
    print(f"USDC.e Balance: {e_bal}")
    print(f"Native USDC Balance: {n_bal}")
    print(f"MATIC Balance: {w3.eth.get_balance(proxy) / 1e18}")
    
    # Let's also check if there are open orders locking the USDC.e
    orders = clob.client.get_orders(clob._open_order_params())
    locked = 0.0
    for o in orders:
        if o.get("side") == "BUY":
            locked += float(o.get("price", 0)) * float(o.get("original_size", 0)) - float(o.get("size_matched", 0)) * float(o.get("price", 0))
    print(f"Approx USDC.e locked in open buy orders: {locked}")

if __name__ == "__main__":
    main()
