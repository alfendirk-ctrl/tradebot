from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import threading
from bot import state, run_bot
from dataclasses import asdict

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

@app.get("/trades")
def get_trades():
    return [asdict(t) for t in state.trades]

@app.delete("/trades")
def clear_trades():
    if state.running:
        raise HTTPException(status_code=400, detail="Stop the bot before clearing trades")
    state.trades.clear()
    state.total_pnl = 0.0
    return {"message": "Trade history cleared"}
