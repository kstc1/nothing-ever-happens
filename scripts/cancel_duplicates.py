import os
import sys
import logging
from dotenv import load_dotenv
from bot.exchange.polymarket_clob import PolymarketClobExchangeClient
from bot.config import load_nothing_happens_config

load_dotenv()

logging.basicConfig(level=logging.INFO)

cfg = load_nothing_happens_config()

exchange_cfg = cfg[0]

exchange = PolymarketClobExchangeClient(exchange_cfg, allow_trading=True)

print("Fetching all open orders...")
open_orders = exchange.get_all_open_orders()
print(f"Found {len(open_orders)} open orders.")

active_orders_by_token = {}
duplicates = []

for order in open_orders:
    status = (order.status or "").lower()
    if status not in {"open", "matched", "live", "active", "resting"}:
        continue
    
    token = order.token_id
    if token in active_orders_by_token:
        print(f"Duplicate found for token {token}!")
        print(f"  Keeping: {active_orders_by_token[token].order_id} (created: {getattr(active_orders_by_token[token], 'created_at', 'unknown')})")
        print(f"  Cancelling duplicate: {order.order_id} (created: {getattr(order, 'created_at', 'unknown')})")
        duplicates.append(order)
    else:
        active_orders_by_token[token] = order

print(f"\nFound {len(duplicates)} duplicates out of {len(open_orders)} total orders.")

for dup in duplicates:
    print(f"Cancelling duplicate order: {dup.order_id} (Token: {dup.token_id})")
    success = exchange.cancel_order(dup.order_id)
    if success:
        print(" -> Success")
    else:
        print(" -> Failed to cancel")

print("Done.")
