import ccxt
import time
import logging
import os
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

from strategy import analyze, Signal, get_swing_points

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Trade:
    id: str
    symbol: str
    side: str
    setup_type: str
    entry_price: float
    quantity: float           # totale originele positie
    stop_loss: float          # dynamisch, verschuift mee
    tp1: float
    tp2: float
    tp3: float
    timestamp: str
    reason: str
    status: str = "open"      # open | partial_1 | partial_2 | partial_3 | closed
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    exit_price: Optional[float] = None
    realized_pnl: float = 0.0  # opgebouwde PnL van partiële exits

@dataclass
class BotState:
    running: bool = False
    symbol: str = "BTC/USDC"
    risk_per_trade: float = 0.01
    trades: list = field(default_factory=list)
    last_signal: str = "none"
    last_setup: str = "none"
    last_candle_time: str = ""
    balance: float = 0.0
    equity: float = 0.0
    total_pnl: float = 0.0

state = BotState()

def get_exchange() -> ccxt.okx:
    api_key    = os.environ.get('OKX_API_KEY', '')
    secret     = os.environ.get('OKX_SECRET', '')
    passphrase = os.environ.get('OKX_PASSPHRASE', '')
    sandbox    = os.environ.get('OKX_SANDBOX', 'true').lower() == 'true'

    params = {
        'apiKey':   api_key,
        'secret':   secret,
        'password': passphrase,
        'options':  {'defaultType': 'spot'},
    }

    # OKX demo trading: gebruik x-simulated-trading header
    if sandbox:
        params['headers'] = {'x-simulated-trading': '1'}

    return ccxt.okx(params)

def get_candles(exchange, symbol: str, timeframe: str, limit: int = 100):
    return exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

def calculate_position_size(balance: float, entry: float, stop: float, risk_pct: float) -> float:
    risk_amount = balance * risk_pct
    risk_per_unit = abs(entry - stop)
    if risk_per_unit == 0:
        return 0
    return round(risk_amount / risk_per_unit, 6)

def place_order(exchange, symbol: str, signal: Signal, qty: float) -> Optional[Trade]:
    try:
        order = exchange.create_market_order(symbol, signal.side, qty)
        trade = Trade(
            id=order['id'],
            symbol=symbol,
            side=signal.side,
            setup_type=signal.setup_type,
            entry_price=signal.entry,
            quantity=qty,
            stop_loss=signal.stop_loss,
            tp1=signal.tp1,
            tp2=signal.tp2,
            tp3=signal.tp3,
            reason=signal.reason,
            timestamp=datetime.utcnow().isoformat(),
        )
        logger.info(
            f"[{signal.setup_type.upper()}] {signal.side.upper()} {qty} {symbol} @ {signal.entry:.0f} | "
            f"SL={signal.stop_loss:.0f} | TP1={signal.tp1:.0f} | TP2={signal.tp2:.0f} | TP3={signal.tp3:.0f} | Runner open"
        )
        return trade
    except Exception as e:
        logger.error(f"Order mislukt: {e}")
        return None

def partial_close(exchange, trade: Trade, fraction: float, curr_price: float, label: str):
    """Sluit een deel van de positie en registreer de PnL."""
    qty = round(trade.quantity * fraction, 6)
    try:
        close_side = "sell" if trade.side == "buy" else "buy"
        exchange.create_market_order(trade.symbol, close_side, qty)
    except Exception as e:
        logger.error(f"{label} order fout: {e}")
        return 0.0

    if trade.side == "buy":
        pnl = (curr_price - trade.entry_price) * qty
    else:
        pnl = (trade.entry_price - curr_price) * qty

    trade.realized_pnl += pnl
    state.total_pnl += pnl
    logger.info(f"{label} ({fraction*100:.0f}% uit @ {curr_price:.0f}) | PnL = {pnl:.2f} USDT")
    return pnl

def trail_sl_to_structure(trade: Trade, candles: list, phase: int):
    """
    Verschuif SL naar relevante prijsactie na TP2 en TP3.
    phase 2 → laatste swing low/high
    phase 3 → nieuwste swing punt nog dichter bij prijs
    """
    swing_highs, swing_lows = get_swing_points(candles[:-1], lookback=3)

    if trade.side == "buy" and swing_lows:
        # Meest recente swing low onder huidige prijs als nieuwe SL
        candidates = sorted(
            [p for _, p in swing_lows if p < candles[-1][4]],
            reverse=True
        )
        if candidates:
            new_sl = candidates[0] * 0.999  # net eronder
            if new_sl > trade.stop_loss:    # alleen omhoog verschuiven
                logger.info(f"SL verschoven naar swing low: {trade.stop_loss:.0f} → {new_sl:.0f} (fase {phase})")
                trade.stop_loss = new_sl

    elif trade.side == "sell" and swing_highs:
        candidates = sorted(
            [p for _, p in swing_highs if p > candles[-1][4]]
        )
        if candidates:
            new_sl = candidates[0] * 1.001  # net erboven
            if new_sl < trade.stop_loss:    # alleen omlaag verschuiven
                logger.info(f"SL verschoven naar swing high: {trade.stop_loss:.0f} → {new_sl:.0f} (fase {phase})")
                trade.stop_loss = new_sl

def manage_open_trades(exchange, candles_15m):
    """
    4-tranche uitstap strategie:
    - TP1 (25%) → SL naar breakeven
    - TP2 (25%) → SL naar laatste swing low/high
    - TP3 (25%) → SL naar nieuwer swing punt
    - Runner (25%) → SL blijft trailen totdat SL geraakt wordt
    """
    curr_price = candles_15m[-1][4]

    for trade in state.trades:
        if trade.status == "closed":
            continue

        hit_sl = (
            (trade.side == "buy"  and curr_price <= trade.stop_loss) or
            (trade.side == "sell" and curr_price >= trade.stop_loss)
        )
        hit_tp1 = not trade.tp1_hit and (
            (trade.side == "buy"  and curr_price >= trade.tp1) or
            (trade.side == "sell" and curr_price <= trade.tp1)
        )
        hit_tp2 = trade.tp1_hit and not trade.tp2_hit and (
            (trade.side == "buy"  and curr_price >= trade.tp2) or
            (trade.side == "sell" and curr_price <= trade.tp2)
        )
        hit_tp3 = trade.tp2_hit and not trade.tp3_hit and (
            (trade.side == "buy"  and curr_price >= trade.tp3) or
            (trade.side == "sell" and curr_price <= trade.tp3)
        )

        if hit_sl:
            # Bepaal hoeveel er nog open staat
            remaining = 1.0
            if trade.tp1_hit: remaining -= 0.25
            if trade.tp2_hit: remaining -= 0.25
            if trade.tp3_hit: remaining -= 0.25
            partial_close(exchange, trade, remaining, curr_price, "❌ SL")
            trade.status = "closed"
            trade.exit_price = curr_price

        elif hit_tp1:
            partial_close(exchange, trade, 0.25, curr_price, "✅ TP1")
            trade.tp1_hit = True
            trade.status = "partial_1"
            trade.stop_loss = trade.entry_price  # → breakeven
            logger.info(f"SL verschoven naar breakeven: {trade.entry_price:.0f}")

        elif hit_tp2:
            partial_close(exchange, trade, 0.25, curr_price, "✅ TP2")
            trade.tp2_hit = True
            trade.status = "partial_2"
            trail_sl_to_structure(trade, candles_15m, phase=2)

        elif hit_tp3:
            partial_close(exchange, trade, 0.25, curr_price, "✅ TP3")
            trade.tp3_hit = True
            trade.status = "partial_3"
            trail_sl_to_structure(trade, candles_15m, phase=3)

        elif trade.tp3_hit:
            # Runner fase: SL continu trailen op elke nieuwe candle
            trail_sl_to_structure(trade, candles_15m, phase=4)

def run_bot():
    exchange = get_exchange()
    logger.info(f"DoopieCash Bot gestart | {state.symbol}")

    while state.running:
        try:
            balance_info  = exchange.fetch_balance()
            # Probeer USDC, val terug op USDT of USD
            for currency in ['USDC', 'USDT', 'USD']:
                if currency in balance_info and balance_info[currency]['total'] > 0:
                    state.balance = float(balance_info[currency]['free'])
                    state.equity  = float(balance_info[currency]['total'])
                    break

            candles_15m = get_candles(exchange, state.symbol, '15m', limit=100)
            candles_1h  = get_candles(exchange, state.symbol, '1h',  limit=50)
            last_ts = str(candles_15m[-1][0])

            if last_ts != state.last_candle_time:
                state.last_candle_time = last_ts
                manage_open_trades(exchange, candles_15m)

                open_count = sum(1 for t in state.trades if t.status != "closed")
                if open_count == 0:
                    signal = analyze(candles_15m, candles_1h)
                    if signal:
                        state.last_signal = signal.side
                        state.last_setup  = signal.setup_type
                        qty = calculate_position_size(
                            state.balance, signal.entry,
                            signal.stop_loss, state.risk_per_trade
                        )
                        if qty > 0:
                            trade = place_order(exchange, state.symbol, signal, qty)
                            if trade:
                                state.trades.append(trade)
                    else:
                        state.last_signal = "none"
                        state.last_setup  = "none"

            time.sleep(10)

        except Exception as e:
            logger.error(f"Bot loop fout: {e}")
            time.sleep(30)

    logger.info("Bot gestopt.")
