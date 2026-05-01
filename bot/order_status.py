_ORDER_STATUS_ALIASES = {
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "delayed": "delayed",
    "filled": "filled",
    "live": "live",
    "matched": "matched",
    "open": "open",
    "partial": "partially_filled",
    "partial_fill": "partially_filled",
    "partial_filled": "partially_filled",
    "partially_filled": "partially_filled",
    "rejected": "rejected",
    "simulated": "simulated",
    "submitted": "submitted",
    "unmatched": "unmatched",
}


def normalize_order_status(status: str) -> str:
    normalized = str(status).strip().lower()
    return _ORDER_STATUS_ALIASES.get(normalized, normalized)


def normalize_optional_order_status(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = normalize_order_status(status)
    return normalized or None


# Normalized statuses: order may still be live on the CLOB book. Omitting these
# (e.g. ``submitted`` or ``partially_filled``) lets pre-check miss real opens.
RESTING_POLYMARKET_ORDER_STATUSES: frozenset[str] = frozenset(
    {
        "open",
        "live",
        "active",
        "resting",
        "matched",
        "submitted",
        "delayed",
        "unmatched",
        "partially_filled",
        "simulated",
    }
)


def is_resting_polymarket_order_status(status: str | None) -> bool:
    # Open-order payloads sometimes omit ``status``; listings from the open-orders
    # API are still non-terminal resting orders.
    if status is None or not str(status).strip():
        return True
    return normalize_order_status(status) in RESTING_POLYMARKET_ORDER_STATUSES

