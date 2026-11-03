"""Polymarket Data API v2 helpers for wallet positions."""

from __future__ import annotations

from typing import Any

import aiohttp
import requests

DATA_API_BASE = "https://data-api.polymarket.com"
POSITIONS_V2_URL = f"{DATA_API_BASE}/v2/positions"
POSITIONS_PAGE_LIMIT = 100
POSITIONS_FETCH_TIMEOUT_SEC = 30.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def extract_positions_page(payload: Any) -> tuple[list[dict], str | None]:
    """Parse a v2 `{ data, pagination }` positions response."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], None
    if not isinstance(payload, dict):
        raise ValueError("unexpected positions response payload")
    data = payload.get("data")
    if data is None:
        legacy = payload.get("positions")
        if isinstance(legacy, list):
            data = legacy
        else:
            raise ValueError("positions response missing data/positions list")
    if not isinstance(data, list):
        raise ValueError("positions response missing data/positions list")
    rows = [item for item in data if isinstance(item, dict)]
    pagination = payload.get("pagination")
    next_cursor: str | None = None
    if isinstance(pagination, dict):
        raw = pagination.get("next_cursor")
        if raw:
            next_cursor = str(raw)
    return rows, next_cursor


def position_condition_id(position: dict) -> str:
    raw = position.get("condition_id") or position.get("conditionId") or ""
    return str(raw)


def position_token_id(position: dict) -> str:
    raw = position.get("token_id") or position.get("asset") or ""
    return str(raw)


def position_current_size(position: dict) -> float:
    if "current_size" in position:
        return _safe_float(position.get("current_size"))
    return _safe_float(position.get("size"))


def position_current_value(position: dict) -> float:
    if "current_value" in position:
        return _safe_float(position.get("current_value"))
    return _safe_float(position.get("currentValue"))


def _positions_query_params(
    wallet_address: str,
    *,
    status: str,
    filter_amount: str = "0",
) -> dict[str, str]:
    return {
        "user": wallet_address,
        "status": status,
        "filter_type": "TOKENS",
        "filter_amount": filter_amount,
        "limit": str(POSITIONS_PAGE_LIMIT),
    }


async def fetch_wallet_positions_async(
    session: aiohttp.ClientSession,
    wallet_address: str,
    *,
    status: str = "OPEN",
    exclude_redeemable: bool = False,
    timeout_sec: float = POSITIONS_FETCH_TIMEOUT_SEC,
) -> list[dict]:
    """Page through `/v2/positions` for one wallet and lifecycle status."""
    all_positions: list[dict] = []
    params = _positions_query_params(wallet_address, status=status)
    cursor: str | None = None
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    while True:
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        async with session.get(POSITIONS_V2_URL, params=page_params, timeout=timeout) as resp:
            resp.raise_for_status()
            payload = await resp.json()
        page, next_cursor = extract_positions_page(payload)
        if exclude_redeemable:
            page = [row for row in page if not row.get("redeemable")]
        all_positions.extend(page)
        if not next_cursor:
            return all_positions
        cursor = next_cursor


def fetch_wallet_positions_sync(
    wallet_address: str,
    *,
    status: str = "OPEN",
    timeout_sec: float = POSITIONS_FETCH_TIMEOUT_SEC,
    http: requests.Session | None = None,
) -> list[dict]:
    """Sync variant of `fetch_wallet_positions_async` for scripts."""
    client = http or requests
    all_positions: list[dict] = []
    params = _positions_query_params(wallet_address, status=status)
    cursor: str | None = None
    while True:
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        resp = client.get(POSITIONS_V2_URL, params=page_params, timeout=timeout_sec)
        resp.raise_for_status()
        page, next_cursor = extract_positions_page(resp.json())
        all_positions.extend(page)
        if not next_cursor:
            return all_positions
        cursor = next_cursor
