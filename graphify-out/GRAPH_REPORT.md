# Graph Report - ./bot  (2026-04-26)

## Corpus Check
- Corpus is ~25,344 words - fits in a single context window. You may not need a graph.

## Summary
- 465 nodes · 1172 edges · 15 communities detected
- Extraction: 67% EXTRACTED · 33% INFERRED · 0% AMBIGUOUS · INFERRED: 391 edges (avg confidence: 0.62)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Module 0 Enum|Module 0: Enum]]
- [[_COMMUNITY_Module 1 run()|Module 1: run()]]
- [[_COMMUNITY_Configuration & Setup|Configuration & Setup]]
- [[_COMMUNITY_Module 3 str|Module 3: str]]
- [[_COMMUNITY_Market & Trading|Market & Trading]]
- [[_COMMUNITY_Market & Trading|Market & Trading]]
- [[_COMMUNITY_Logging & Monitoring|Logging & Monitoring]]
- [[_COMMUNITY_Module 7 _parse_iso_ts()|Module 7: _parse_iso_ts()]]
- [[_COMMUNITY_Module 8 DashboardServer|Module 8: DashboardServer]]
- [[_COMMUNITY_Module 9 _env_int()|Module 9: _env_int()]]
- [[_COMMUNITY_Data & Storage|Data & Storage]]
- [[_COMMUNITY_Market & Trading|Market & Trading]]
- [[_COMMUNITY_Market & Trading|Market & Trading]]
- [[_COMMUNITY_Utilities & Helpers|Utilities & Helpers]]
- [[_COMMUNITY_Module 14 __init__.py|Module 14: __init__.py]]

## God Nodes (most connected - your core abstractions)
1. `NothingHappensRuntime` - 60 edges
2. `PolymarketClobExchangeClient` - 40 edges
3. `PaperExchangeClient` - 32 edges
4. `OrderStore` - 30 edges
5. `LiveRecoveryCoordinator` - 26 edges
6. `NothingHappensControlState` - 26 edges
7. `Side` - 25 edges
8. `LimitOrderIntent` - 24 edges
9. `OrderBookSnapshot` - 24 edges
10. `run()` - 22 edges

## Surprising Connections (you probably didn't know these)
- `Dashboard web server via aiohttp + WebSocket.` --uses--> `NothingHappensControlState`  [INFERRED]
  /home/stefansy/nothing-ever-happens/bot/dashboard.py → /home/stefansy/nothing-ever-happens/bot/nothing_happens_control.py
- `NothingHappensRuntime` --uses--> `PositionSnapshot`  [INFERRED]
  /home/stefansy/nothing-ever-happens/bot/strategy/nothing_happens.py → /home/stefansy/nothing-ever-happens/bot/portfolio_state.py
- `_position_snapshot_from_local()` --calls--> `PositionSnapshot`  [INFERRED]
  /home/stefansy/nothing-ever-happens/bot/strategy/nothing_happens.py → /home/stefansy/nothing-ever-happens/bot/portfolio_state.py
- `_position_snapshot_from_api()` --calls--> `PositionSnapshot`  [INFERRED]
  /home/stefansy/nothing-ever-happens/bot/strategy/nothing_happens.py → /home/stefansy/nothing-ever-happens/bot/portfolio_state.py
- `Async supervisor for the public nothing-happens runtime.` --uses--> `PortfolioState`  [INFERRED]
  /home/stefansy/nothing-ever-happens/bot/main.py → /home/stefansy/nothing-ever-happens/bot/portfolio_state.py

## Communities

### Community 0 - "Module 0: Enum"
Cohesion: 0.08
Nodes (45): ExchangeConfig, NothingHappensConfig, Enum, CancelOrder, LimitOrderIntent, MarketOrderIntent, MarketRules, OpenOrder (+37 more)

### Community 1 - "Module 1: run()"
Cohesion: 0.07
Nodes (19): _best_bid(), _bid_depth_notional(), _eta_seconds(), _extract_positions_payload(), _fetch_open_positions(), _is_clean_no_fill_order_status(), _is_definitive_no_fill_error(), _is_success_order_status() (+11 more)

### Community 2 - "Configuration & Setup"
Cohesion: 0.07
Nodes (25): configure_logging(), SensitiveFieldFilter, _build_exchange(), main(), _patch_clob_http_timeout(), Async supervisor for the public nothing-happens runtime., Increase py-clob-client's httpx read timeout from 5s to 12s., _record_supervisor_event() (+17 more)

### Community 3 - "Module 3: str"
Cohesion: 0.12
Nodes (15): _clamp_probability(), _coerce_float(), _collect_float_values(), _extract_allowance_value(), _extract_float_field(), _extract_trade_fee(), _normalize_side(), PolymarketClobExchangeClient (+7 more)

### Community 4 - "Market & Trading"
Cohesion: 0.11
Nodes (17): _bot_variant(), _bot_variant_clause(), _check_gamma_resolution(), _expected_trade_side(), LiveRecoveryCoordinator, _order_snapshot_status(), _parse_trade_timestamp_us(), Durable live recovery helpers for ambiguous orders and settlement. (+9 more)

### Community 5 - "Market & Trading"
Cohesion: 0.11
Nodes (6): _daily_realized_pnl_key(), _normalize_db_timestamp(), OrderStore, _risk_orders_sent_key(), _risk_session_notional_key(), _submission_lock_key()

### Community 6 - "Logging & Monitoring"
Cohesion: 0.12
Nodes (13): log_latency_event(), log_latency_span(), monotonic_us(), Structured latency logging helpers for the live bot., Monotonic clock for duration measurement., Emit a structured latency marker., Emit a duration-bearing latency marker and return the elapsed time., Background venue-state reconciliation cache for live market positions. (+5 more)

### Community 7 - "Module 7: _parse_iso_ts()"
Cohesion: 0.18
Nodes (24): build_standalone_market(), _ends_within_window(), fetch_all_open_markets(), fetch_candidate_markets(), fetch_markets_by_token_ids(), filter_standalone_markets(), filter_standalone_markets_with_event_counts(), GammaMarketFetchError (+16 more)

### Community 8 - "Module 8: DashboardServer"
Cohesion: 0.18
Nodes (2): DashboardServer, Dashboard web server via aiohttp + WebSocket.

### Community 9 - "Module 9: _env_int()"
Cohesion: 0.26
Nodes (13): _build_exchange_config(), _compute_live_send_enabled(), _env_bool(), _env_float(), _env_int(), _env_optional(), _env_positive_float_or_inf(), _env_secret() (+5 more)

### Community 10 - "Data & Storage"
Cohesion: 0.18
Nodes (12): create_engine(), create_tables(), _normalize_db_url(), flush_trade_ledger(), init_db(), _open_ledger(), Append-only trade ledger for incident reconstruction.  Every order attempt (BUY/, Best-effort wait for queued records to be persisted. (+4 more)

### Community 11 - "Market & Trading"
Cohesion: 0.13
Nodes (2): ExchangeClient, Protocol

### Community 12 - "Market & Trading"
Cohesion: 0.15
Nodes (13): backoff_sleep(), current_interval_start(), next_interval_start(), now_ms(), polymarket_taker_fee(), Shared helpers: timestamps, interval math, fast JSON., Current time as Unix milliseconds., Return the Unix timestamp (seconds) of the current interval start. (+5 more)

### Community 13 - "Utilities & Helpers"
Cohesion: 0.6
Nodes (3): _epoch_to_datetime(), parse_venue_timestamp(), to_epoch_seconds()

### Community 14 - "Module 14: __init__.py"
Cohesion: 0.67
Nodes (1): Strategy package for the public nothing-happens runtime.

## Knowledge Gaps
- **34 isolated node(s):** `Thread-safe portfolio snapshot for the dashboard.`, `Background venue-state reconciliation cache for live market positions.`, `Standalone yes/no market discovery shared by scripts and live runtime.`, `Runtime risk controls for live strategy loops.  Implements:   - Max total and pe`, `Set the daily high-water mark directly, bypassing the arm period.          Calle` (+29 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Module 8: DashboardServer`** (21 nodes): `DashboardServer`, `._background_image()`, `._broadcast()`, `._handle_ws_message()`, `._index()`, `.__init__()`, `._make_pnl_message()`, `._make_portfolio_message()`, `._poll_balance()`, `._poll_loop()`, `._poll_once()`, `._poll_resolutions()`, `._poll_trades()`, `.run()`, `._send_initial()`, `._send_to()`, `._ws_handler()`, `dashboard.py`, `Dashboard web server via aiohttp + WebSocket.`, `.snapshot()`, `.version()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Market & Trading`** (15 nodes): `ExchangeClient`, `.bootstrap_live_trading()`, `.cancel_all()`, `.cancel_order()`, `.check_order_readiness()`, `.get_all_open_orders()`, `.get_market_rules()`, `.get_mid_price()`, `.get_open_orders()`, `.get_order()`, `.get_trades()`, `.place_limit_order()`, `.place_market_order()`, `base.py`, `Protocol`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module 14: __init__.py`** (3 nodes): `__init__.py`, `Strategy package for the public nothing-happens runtime.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `NothingHappensRuntime` connect `Module 1: run()` to `Module 0: Enum`?**
  _High betweenness centrality (0.154) - this node is a cross-community bridge._
- **Why does `run()` connect `Configuration & Setup` to `Module 0: Enum`, `Module 3: str`, `Market & Trading`, `Module 8: DashboardServer`, `Module 9: _env_int()`, `Data & Storage`?**
  _High betweenness centrality (0.142) - this node is a cross-community bridge._
- **Why does `Side` connect `Module 0: Enum` to `Module 1: run()`, `Module 3: str`, `Market & Trading`?**
  _High betweenness centrality (0.103) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `NothingHappensRuntime` (e.g. with `NothingHappensConfig` and `LimitOrderIntent`) actually correct?**
  _`NothingHappensRuntime` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 52 inferred relationships involving `str` (e.g. with `.update()` and `_get_nothing_happens_section()`) actually correct?**
  _`str` has 52 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `PolymarketClobExchangeClient` (e.g. with `Async supervisor for the public nothing-happens runtime.` and `Increase py-clob-client's httpx read timeout from 5s to 12s.`) actually correct?**
  _`PolymarketClobExchangeClient` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `PaperExchangeClient` (e.g. with `Async supervisor for the public nothing-happens runtime.` and `Increase py-clob-client's httpx read timeout from 5s to 12s.`) actually correct?**
  _`PaperExchangeClient` has 12 INFERRED edges - model-reasoned connections that need verification._