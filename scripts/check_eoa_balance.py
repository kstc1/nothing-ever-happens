"""Show on-chain ERC-20 USDC balances for the signing EOA and (if set) `FUNDER_ADDRESS`.

For POLY_1271 / deposit wallets (`signature_type` 3), trading collateral must sit on the
deposit wallet (`FUNDER_ADDRESS`). USDC left only on the EOA does **not** count as CLOB
buying power until moved to that wallet.

Docs: https://docs.polymarket.com/trading/deposit-wallets"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

from bot.config import _load_config_file, _load_nothing_happens_config


def _usdc_balances(*, w3: Web3, owner: str) -> tuple[float, float]:
    usdc_e = w3.eth.contract(
        address=Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"),
        abi=[
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            }
        ],
    )
    usdc_native = w3.eth.contract(
        address=Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"),
        abi=[
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            }
        ],
    )
    cs = Web3.to_checksum_address(owner)
    return usdc_e.functions.balanceOf(cs).call() / 1e6, usdc_native.functions.balanceOf(cs).call() / 1e6


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to config.json (default: CONFIG_PATH env or ./config.json).",
    )
    args = parser.parse_args()

    load_dotenv()
    cfg_raw = (
        json.loads(Path(args.config).read_text(encoding="utf-8"))
        if args.config
        else _load_config_file()
    )
    e, _ = _load_nothing_happens_config(cfg_raw)

    rpc = e.polygon_rpc_url
    if not rpc:
        raise SystemExit("POLYGON_RPC_URL is required for on-chain balance checks.")

    w3 = Web3(Web3.HTTPProvider(rpc))
    pk = e.private_key.get_secret_value() if e.private_key else None
    if not pk:
        raise SystemExit("PRIVATE_KEY required to derive signer address.")

    eoa = Account.from_key(pk).address
    print(f"Signer EOA:          {eoa}")
    ue, un = _usdc_balances(w3=w3, owner=eoa)
    print(f"  EOA USDC.e:         {ue}")
    print(f"  EOA native USDC:    {un}")
    print(f"  EOA MATIC (gas):    {w3.eth.get_balance(eoa) / 1e18}")

    fa = e.funder_address
    print()
    print(f"FUNDER_ADDRESS:       {fa or '(not set)'}")

    if e.signature_type == 3:
        print(
            "Mode: POLY_1271 deposit wallet — set `connection.signature_type` 3 and `FUNDER_ADDRESS` "
            "to the deterministic deposit wallet. Fund that address; then run "
            "`python scripts/check_balance.py --sync-update`."
        )

    if fa and Web3.to_checksum_address(fa) != Web3.to_checksum_address(eoa):
        fe, fn = _usdc_balances(w3=w3, owner=fa)
        print(f"  Funder USDC.e:       {fe}")
        print(f"  Funder native USDC:  {fn}")
        print(f"  Funder MATIC (gas):  {w3.eth.get_balance(Web3.to_checksum_address(fa)) / 1e18}")


if __name__ == "__main__":
    main()
