import json
import os
from dotenv import load_dotenv

from bot.config import _load_nothing_happens_config
from bot.exchange.polymarket_clob import PolymarketClobExchangeClient
from eth_account import Account
from web3 import Web3

def main():
    load_dotenv()
    with open("config.json") as f:
        cfg_raw = json.load(f)
    e, s = _load_nothing_happens_config(cfg_raw)
    
    eoa = Account.from_key(e.private_key.get_secret_value()).address
    print(f"EOA Address: {eoa}")
    
    w3 = Web3(Web3.HTTPProvider(e.polygon_rpc_url))
    
    usdc_e = w3.eth.contract(address=Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"), abi=[{
        "constant": True, "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"
    }])
    
    e_bal = usdc_e.functions.balanceOf(eoa).call() / 1e6
    print(f"EOA USDC.e Balance: {e_bal}")

if __name__ == "__main__":
    main()
