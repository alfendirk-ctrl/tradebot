from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import threading
import time
from bot import state, run_bot, get_setup_health, SETUP_TYPES
from dataclasses import asdict
from db import clear_trades as db_clear_trades
import math

app = FastAPI(title="BTC Trading Bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

bot_thread: threading.Thread = None

class BotConfig(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "15m"
    risk_per_trade: float = 0.01

@app.get("/status")
def get_status():
    trades_serialized = [asdict(t) for t in state.trades]
    return {
        "running": state.running,
        "sim_mode": state.sim_mode,
        "symbol": state.symbol,
        "timeframe": "15m",
        "risk_per_trade": state.risk_per_trade,
        "last_signal": state.last_signal,
        "last_setup": state.last_setup,
        "last_candle_time": state.last_candle_time,
        "balance": state.balance,
        "equity": state.equity,
        "total_pnl": state.total_pnl,
        "trades": trades_serialized,
        "open_trades": sum(1 for t in state.trades if t.status != "closed"),
        "closed_trades": sum(1 for t in state.trades if t.status == "closed"),
        "winning_trades": sum(1 for t in state.trades if t.status == "closed" and t.realized_pnl and t.realized_pnl > 0),
        "consecutive_stops": state.consecutive_stops,
        "circuit_breaker_active": bool(state.circuit_breaker_until and time.time() < state.circuit_breaker_until),
        "circuit_breaker_until": state.circuit_breaker_until if state.circuit_breaker_until and time.time() < state.circuit_breaker_until else None,
        "daily_loss_pct": round((state.equity - state.day_start_equity) / state.day_start_equity * 100, 2) if state.day_start_equity > 0 else 0.0,
        "disabled_setups": state.disabled_setups,
        "setup_health": {s: get_setup_health(s) for s in SETUP_TYPES},
    }

@app.post("/start")
def start_bot(config: BotConfig):
    global bot_thread
    if state.running:
        raise HTTPException(status_code=400, detail="Bot is already running")
    state.symbol = config.symbol
    state.risk_per_trade = config.risk_per_trade
    state.running = True
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    return {"message": "Bot started", "config": config}

@app.post("/stop")
def stop_bot():
    if not state.running:
        raise HTTPException(status_code=400, detail="Bot is not running")
    state.running = False
    return {"message": "Bot stopping..."}

@app.get("/stats")
def get_stats():
    closed = [t for t in state.trades if t.status == "closed"]

    # Per-setup statistieken + gezondheid
    setup_stats = {}
    for setup in SETUP_TYPES:
        ts = [t for t in closed if t.setup_type == setup]
        wins   = [t for t in ts if t.realized_pnl > 0]
        losses = [t for t in ts if t.realized_pnl <= 0]
        gross_profit = sum(t.realized_pnl for t in wins)
        gross_loss   = abs(sum(t.realized_pnl for t in losses))
        health = get_setup_health(setup)
        setup_stats[setup] = {
            "count": len(ts),
            "wins": len(wins),
            "win_rate": round(len(wins) / len(ts) * 100) if ts else 0,
            "avg_pnl": round(sum(t.realized_pnl for t in ts) / len(ts), 2) if ts else 0,
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
            "health": health['status'],
            "recent_win_rate": round(health['win_rate'] * 100) if health['win_rate'] is not None else None,
            "recent_trades": health['trades'],
        }

    # Dagelijkse PnL gegroepeerd op datum (YYYY-MM-DD)
    daily: dict = {}
    for t in closed:
        day = t.timestamp[:10]
        daily[day] = round(daily.get(day, 0.0) + t.realized_pnl, 2)
    daily_pnl = [{"date": k, "pnl": v} for k, v in sorted(daily.items())]

    # Sharpe ratio op basis van dagelijkse PnL (annualized, ≥2 dagen nodig)
    sharpe = None
    if len(daily_pnl) >= 2:
        returns = [d['pnl'] for d in daily_pnl]
        n = len(returns)
        mean_r = sum(returns) / n
        variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0
        if std_r > 0:
            sharpe = round(mean_r / std_r * math.sqrt(252), 2)

    # Max drawdown vanuit equity history
    max_drawdown = None
    if len(state.equity_history) >= 2:
        equities = [e['equity'] for e in state.equity_history]
        peak = equities[0]
        max_dd = 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        max_drawdown = round(max_dd * 100, 2)  # als percentage

    return {
        "equity_history": state.equity_history,
        "setup_stats": setup_stats,
        "daily_pnl": daily_pnl,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_drawdown,
    }


@app.get("/trades")
def get_trades():
    return [asdict(t) for t in state.trades]

@app.delete("/trades")
def clear_trades():
    if state.running:
        raise HTTPException(status_code=400, detail="Stop the bot before clearing trades")
    state.trades.clear()
    state.total_pnl = 0.0
    db_clear_trades()
    return {"message": "Trade history cleared"}
