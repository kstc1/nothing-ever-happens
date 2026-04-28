# Agent Instructions
- Global rules: ~/.claude/CLAUDE.md → ~/AGENTS.md (role, session protocol, wiki structure, git, coding principles). Load only if not yet in context.
- Same for global rules for GEMINI : ~/.gemini/antigravity/GEMINI.md
- For other agents, refer to ~/AGENTS.md for global rules.

## Canonical Wiki Path (this project):
`/mnt/c/vault/projects/nothing-ever-happens/wiki/`

---

## Project Overview

**Nothing Ever Happens** is an async Python trading bot for Polymarket that focuses on buying NO shares on standalone yes/no markets below a configured price cap. It emphasizes GTC limit orders (not market orders), market lifecycle gating, strict rate limiting, and secure secret handling.

**Safety first:** Real order transmission requires `BOT_MODE=live`, `LIVE_TRADING_ENABLED=true`, AND `DRY_RUN=false`. Otherwise defaults to `PaperExchangeClient`.

## Core Architecture

### System Backbone: `NothingHappensRuntime` (Orchestrator)
The main entry point (`bot/main.py:run()`) spawns `NothingHappensRuntime` which orchestrates:
- **Market scanning**: Standalone market discovery + lifecycle gating (age %, absolute seconds)
- **Order dispatch**: GTC limit order submission with configurable price caps and sizing (% or fixed USD)
- **Position tracking**: `PortfolioState` syncs cash, open orders, and positions from exchange
- **Recovery**: `LiveRecoveryCoordinator` handles ambiguous order states (PENDING_SIGNATURE, etc.)
- **Dashboard**: Real-time web UI (`dashboard.py`) via aiohttp WebSocket
- **Redeemer**: Background task (`redeemer.py`) cashes out winning positions

### Component Interaction Layers

**Exchange Clients** (abstraction via `ExchangeClient` protocol):
- `PolymarketClobExchangeClient`: Real live trading on Polymarket CLOB
- `PaperExchangeClient`: Paper trading simulation (default fallback)
- Both implement same interface: order placement, position sync, market data

**State Management**:
- `PortfolioState`: Current cash, open positions, pending orders (synced from exchange)
- `VenueState`: Cached market data, order books, snapshots
- `NothingHappensControlState`: Bot's high-level state machine (running, paused, error)

**Risk & Recovery**:
- `RiskControls`: Enforces max positions, per-category concentration, notional limits
- `LiveRecoveryCoordinator`: Disambiguates failed orders, resubmits on network/API errors
- `OrderStore`: Persists trades to PostgreSQL for audit/reconstruction

**Market Filtering**:
- `standalone_markets.py`: Fetches standalone markets by token, filters by age/category
- Lifecycle gates: Markets must be between `min_market_age_pct` and `max_market_age_pct` of lifespan

### Design Patterns

**Orchestrator-Worker Pattern:**
- **Orchestrator**: Public methods (e.g., `execute_entry()`, `sync_positions()`) define process flow.
- **Workers**: Private methods (`_calculate_size()`, `_fetch_fees()`) are atomic and reusable.
- **Max nesting**: 2 levels (`if/else`, `for`). Spin out a 3rd level into a worker.

**State & Validation (Tri-State API Responses):**
1. **Success with data**: Proceed.
2. **Success but empty**: Log WARNING, return `None` (unless explicitly approved).
3. **Exception/Error**: Log ERROR and raise immediately (never silent fallback to defaults).
- **Zero-Value Guards**: Immediate check for `zero` or `null` before calculations or trades.
- **Lean Pydantic Models**: No redundant state; use `@property` for derived values.

**Secret Handling:**
- Custom `SecretStr` class: Redacts sensitive strings (PRIVATE_KEY, etc.) from logs and exception traces.
- JSON encoders: Specialized handling to prevent leaking secrets in serialization.

## Development Workflow

### Setup
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp config.example.json config.json
cp .env.example .env
```

### Running
```bash
# Local: defaults to paper trading (DRY_RUN=true, no real orders)
python -m bot.main

# With custom config
CONFIG_PATH=/path/to/config.json python -m bot.main

# Dashboard: binds to $PORT (default 8080) or $DASHBOARD_PORT
# Open browser to http://localhost:8080
```

### Testing
```bash
python -m pytest -v                    # all tests
python -m pytest tests/test_models.py  # single file
python -m pytest -k "test_sizing"      # by name pattern
python -m pytest --tb=short            # less verbose traceback
```

### Key Config Paths
- `config.json`: Non-secret settings (polling intervals, sizing, market gates)
- `.env`: Secrets and runtime flags (PRIVATE_KEY, DATABASE_URL, BOT_MODE, etc.)
- `strategies.nothing_happens` section in config controls bot behavior
- See `config.example.json` and `.env.example` for all parameters

### Karpathy Pattern (Wiki-First)
- **Canonical Wiki Path**: `/mnt/c/vault/projects/nothing-ever-happens/wiki/`
- All architectural decisions, task tracking, and issue logging MUST go in the Wiki
- No `PLAN.md` or `issues.md` in the repo root
- Wiki is source of truth for ongoing work and design rationale

## Code Navigation

**Entry points:**
- `bot/main.py:run()` — Main async supervisor, spawns runtime
- `bot/nothing_happens.py` (strategy submodule) — `NothingHappensRuntime` orchestrator

**Core state:**
- `portfolio_state.py` — Current cash, positions, orders
- `venue_state.py` — Market snapshots, order books, rate limiter state
- `nothing_happens_control.py` — Bot control state, logging hooks

**Exchange & Markets:**
- `market.py` — Market model, lifecycle gates, filtering
- `proxy_wallet.py` — Web3 interactions (approvals, signatures)
- `redeemer.py` — Background task for cashing out winning positions

**Resilience:**
- `live_recovery.py` — Handle ambiguous order states (PENDING_SIGNATURE, FAILED, etc.)
- `order_status.py` — Order status enumeration and meaning
- `db.py` / `store.py` — PostgreSQL order ledger and query helpers

**Utilities:**
- `config.py` — Configuration loading and env var parsing
- `models.py` — Pydantic models (trade orders, market snapshots, position structs)
- `rate_limiter.py` — Token-bucket rate limiter (5 RPS default, 10 burst)
- `latency.py` — Structured latency logging for perf debugging
- `secret_str.py` — Sensitive string handling
- `logging_config.py` — JSON logger setup with SensitiveFieldFilter

**UI:**
- `dashboard.py` — aiohttp WebSocket server, real-time portfolio view

## Key Principles

1. **No silent fallbacks**: If an API call returns empty data (not an error), log WARNING and return None. Never substitute a default price or synthetic data.
2. **Defensive against ambiguity**: When order transmission succeeds (200 OK) but the bot has no confirmation (e.g., PENDING_SIGNATURE), `LiveRecoveryCoordinator` retries or reconciles.
3. **Rate limiting is mandatory**: All exchange requests go through `rate_limiter.py` (default 5 RPS, 10 burst). Respect Polymarket's limits.
4. **GTC limit orders, not market orders**: Entry strategy uses limit orders + configurable max age to fill. Falls back to market only if `allowed_slippage` permits.
5. **Market lifecycle gating**: Only trade markets within `min_market_age_pct` to `max_market_age_pct` of lifespan. Avoids volatile new markets and near-expiry churn.
6. **Strict order validation**: Check exchange minimums, calculate sizes atomically, validate zero amounts before submission.
7. **Dual-client abstraction**: Code against `ExchangeClient` protocol, swap `PolymarketClobExchangeClient` ↔ `PaperExchangeClient` via config.
