# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the bot

```bash
# Install Python dependencies
pip install -r requirements.txt

# Copy and fill in API keys
cp .env.example .env

# Start the FastAPI backend (bot API on http://localhost:8000)
uvicorn api:app --reload

# Start the React dashboard (separate terminal)
cd dashboard
npm install
VITE_API_URL=http://localhost:8000 npm run dev
```

**Environment variables** (`.env` or Railway config):
| Variable | Description |
|---|---|
| `OKX_API_KEY` | OKX API key |
| `OKX_SECRET` | OKX secret |
| `OKX_PASSPHRASE` | OKX passphrase |
| `OKX_SANDBOX` | `true` for paper mode via OKX sandbox header |
| `SIM_MODE` | `true` (default) = internal paper trading, no OKX orders placed |
| `SIM_BALANCE` | Starting capital for sim mode (default `10000`) |
| `TELEGRAM_BOT_TOKEN` | Optional — Telegram bot token for trade alerts |
| `TELEGRAM_CHAT_ID` | Optional — Telegram chat ID for trade alerts |

**Deployment:** `Procfile` runs `uvicorn api:app --host 0.0.0.0 --port $PORT` on Railway.

## Architecture

The system is three layers communicating at runtime:

```
strategy.py  ←  pure analysis, no side effects
    ↓
bot.py       ←  exchange connection, trade state, order execution
    ↓
api.py       ←  FastAPI HTTP layer, starts/stops bot in a daemon thread
    ↓
dashboard/   ←  React SPA, polls /status every 5s
```

### strategy.py — signal generation
The `analyze()` function is the single entry point. It takes `candles_15m` and `candles_1h` (OHLCV lists from ccxt), determines market structure on 1h, then checks four setups in priority order:

1. **Rotation** — structural break (uptrend makes LL / downtrend makes HH) + rejection candle or engulfing
2. **Breakout** — candle closes beyond a key level, retest of that level with confirmation
3. **Continuation** — pullback to a flipped level (old resistance → new support) in a clear trend
4. **Range** — price at the extremes of a detected consolidation range (2–4% wide, ≥4 touches per side)

Each checker returns a `Signal` dataclass or `None`. The first non-`None` result wins. After detection, `analyze()` validates minimum R:R of 2.5 (on TP3) before returning.

TP levels are picked from real key levels in the chart, not fixed R:R multiples. ATR-based fallbacks fill in if fewer than 3 chart levels exist ahead.

### bot.py — execution and state
`BotState` is a module-level singleton (`state`). The main loop (`run_bot`) polls on a 10-second interval and only processes a new candle when `last_candle_time` changes.

Per new candle:
1. `manage_open_trades()` checks every open trade for SL/TP hits at the current close price
2. If no open trades, `analyze()` is called; if a signal is returned, a position is sized and `place_order()` is called

**Trade lifecycle — 4-tranche exit:**
- TP1 hit → close 25%, SL moves to breakeven
- TP2 hit → close 25%, SL trails to last swing low/high (`trail_sl_to_structure`)
- TP3 hit → close 25%, SL trails to newer swing point
- Remaining 25% ("runner") → SL keeps trailing on every candle until hit

`sim_mode=True` (default) creates `SIM-XXXX` trades and tracks PnL without placing real orders. Live mode calls `ccxt.myokx` (with EEA fallback to `ccxt.okx`).

### api.py — HTTP interface
Thin FastAPI wrapper around `state` and `run_bot`. The bot runs in a `daemon=True` thread. Key endpoints:
- `GET /status` — full state snapshot (serializes `Trade` dataclasses via `asdict`)
- `POST /start` — accepts `BotConfig` (symbol, timeframe, risk_per_trade), starts thread
- `POST /stop` — sets `state.running = False`
- `GET /trades` / `DELETE /trades` — trade history
- `GET /stats` — per-setup win rate / profit factor, daily PnL list, equity history for charts

### dashboard/src/App.jsx — React monitoring UI
Single-file React SPA. Reads `VITE_API_URL` at build time (defaults to `http://localhost:8000`). Polls `/status` every 5 seconds. No build config files are in the repo — a `package.json` with Vite is expected but not committed.

## Key design constraints

- **One trade at a time.** `run_bot` only calls `analyze()` when `open_count == 0`.
- **Candle-level resolution.** All SL/TP checks use the candle close price, not tick-level prices. A trade can skip a TP level if price jumps.
- **SL only moves in the favorable direction.** `trail_sl_to_structure` guards against moving SL against the trade.
- **EEA / Netherlands users** must use `ccxt.myokx` (OKX's European entity). The code tries `myokx` first and falls back to `okx`.
- **Volatility-scaled position sizing.** `calculate_position_size` accepts a `vol_scale` factor derived from ATR14/ATR50. When recent volatility (ATR14) is high relative to baseline (ATR50), position size shrinks; clamped to [0.5, 2.0].
- **SL cooldown.** `analyze()` skips signal detection for 5 candles (75 min on 15m) after a stop loss hit, via the `cooldown_candles` parameter.
- **Circuit breaker.** After 5 consecutive stop losses, `state.circuit_breaker_until` is set to `now + 86400s` and the bot loop sleeps until that timestamp.
- **Daily loss limit.** If equity drops more than 3% from the day's starting equity, no new trades are taken for the rest of that UTC day.
- **Sim mode uses OKX public API.** `get_public_exchange()` calls `ccxt.okx` without auth (market data only). `get_exchange()` requires credentials and is only called in live mode.
- **No test suite.** There are no automated tests in this repo.

## Roadmap

Verbeteringen in volgorde van prioriteit, gebaseerd op analyse van het huidige systeem vs. referentiesystemen.

### Fase 1 — Signaalkwaliteit (kleine wijzigingen, grote impact)
- **Session filter** in `analyze()`: alleen trades tijdens London (08:00–12:00 UTC) en NY (13:00–17:00 UTC). Buiten die tijden meer fake-outs.
- **Signal expiry**: als de entry >0.5% van de huidige prijs afwijkt op het moment van uitvoering, signaal verwerpen.
- **H4 als macro-bias**: H4 candles ophalen naast 1H. Trades alleen in de richting van de H4 trend.

### Fase 2 — Betrouwbaarheid
- **SQLite persistence**: trades opslaan in `trades.db` zodat data niet verloren gaat bij een restart op Railway.
- **Outcome polling elke 60s**: TP/SL checken op live prijs elke minuut, niet alleen op candle-close (elke 15 min is te traag).
- **Per-setup win rate bijhouden** in `BotState`: rolling window over laatste N trades per setup type.

### Fase 3 — Strategie gezondheid
- **Auto-disable per setup**: als een setup de afgelopen 20 trades onder 40% win rate zakt, tijdelijk uitschakelen. Automatisch herstellen als historische performance terugkomt.
- **Sharpe ratio + max drawdown** toevoegen aan `/stats` endpoint.

### Fase 4 — Backtester
- `backtest.py`: walk-forward backtest op historische OKX candles. Train op periode A, test op periode B. Geeft per setup: win rate, profit factor, Sharpe, max drawdown.
- Nodig als basis voor alle verdere optimalisatie — zonder dit weet je niet of aanpassingen helpen of schaden.

### Fase 5 — Liquidity Sweep setup
- Nieuw setup type naast de bestaande vier. Een sweep gaat naar een key level, jaagt stops aan, en keert dan direct om (fake breakout). Anders dan onze `check_breakout()` die verwacht dat prijs door het level heen blijft.

### Fase 6 — Monte Carlo validatie (later)
- Pas zinvol als Fase 4 (backtester) draait en er voldoende historische trades zijn.
- Shuffle trades 1000×, vergelijk met random strategie — als random wint, parameters weggooien.
