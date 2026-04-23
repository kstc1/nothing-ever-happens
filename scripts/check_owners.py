import os
from dotenv import load_dotenv
from web3 import Web3

def main():
    load_dotenv()
    rpc = os.getenv("POLYGON_RPC_URL")
    w3 = Web3(Web3.HTTPProvider(rpc))
    proxy = Web3.to_checksum_address(os.getenv("FUNDER_ADDRESS"))
    print("Proxy:", proxy)
    
    # Gnosis Safe getOwners() abi
    safe = w3.eth.contract(address=proxy, abi=[{
        "constant": True, "inputs": [], "name": "getOwners", "outputs": [{"name": "", "type": "address[]"}], "type": "function"
    }])
    
    try:
        owners = safe.functions.getOwners().call()
        print("Owners:", owners)
    except Exception as e:
        print("Not a standard Gnosis Safe or failed:", e)

if __name__ == "__main__":
    main()
