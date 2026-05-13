import ccxt
import time
import logging
import os
import requests
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

from strategy import analyze, Signal, get_swing_points, calc_atr

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
    realized_pnl: float = 0.0

@dataclass
class BotState:
    running: bool = False
    symbol: str = "BTC/USDT"
    risk_per_trade: float = 0.01
    sim_mode: bool = True
    sim_balance: float = 10000.0
    trades: list = field(default_factory=list)
    last_signal: str = "none"
    last_setup: str = "none"
    last_candle_time: str = ""
    balance: float = 0.0
    equity: float = 0.0
    total_pnl: float = 0.0
    # Circuit breaker
    consecutive_stops: int = 0
    circuit_breaker_until: float = 0.0   # Unix timestamp; 0.0 = inactief
    # Daily loss limit
    day_date: str = ""
    day_start_equity: float = 0.0
    # Equity history voor grafiek (max 500 punten)
    equity_history: list = field(default_factory=list)

state = BotState()


def _record_equity():
    snap = (state.sim_balance + state.total_pnl) if state.sim_mode else state.equity
    state.equity_history.append({
        "ts": datetime.utcnow().strftime("%d/%m %H:%M"),
        "equity": round(snap, 2),
    })
    if len(state.equity_history) > 500:
        state.equity_history.pop(0)


def send_telegram(message: str):
    token   = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        logger.warning(f"Telegram melding mislukt: {e}")


def get_public_exchange():
    """OKX publieke API voor marktdata — geen auth nodig."""
    return ccxt.okx({'options': {'defaultType': 'spot'}})

def get_exchange():
    """OKX met auth — alleen nodig in LIVE mode voor orderplaatsing."""
    api_key    = os.environ.get('OKX_API_KEY', '')
    secret     = os.environ.get('OKX_SECRET', '')
    passphrase = os.environ.get('OKX_PASSPHRASE', '')
    sandbox    = os.environ.get('OKX_SANDBOX', 'false').lower() == 'true'

    params = {
        'apiKey':   api_key,
        'secret':   secret,
        'password': passphrase,
        'options':  {'defaultType': 'spot'},
    }
    if sandbox:
        params['headers'] = {'x-simulated-trading': '1'}

    # EEA gebruikers (Nederland etc.) moeten myokx gebruiken ipv okx
    try:
        exchange = ccxt.myokx(params)
    except AttributeError:
        exchange = ccxt.okx(params)

    return exchange

def get_candles(exchange, symbol: str, timeframe: str, limit: int = 100):
    return exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

def calculate_position_size(balance: float, entry: float, stop: float,
                             risk_pct: float, vol_scale: float = 1.0) -> float:
    """
    Positiegrootte op basis van risicobedrag.
    vol_scale < 1 bij hoge volatiliteit (ATR14 > ATR50), > 1 bij lage volatiliteit.
    Geclampt op [0.5, 2.0] zodat positie nooit meer dan verdubbelt of halveert.
    """
    risk_amount = balance * risk_pct * vol_scale
    risk_per_unit = abs(entry - stop)
    if risk_per_unit == 0:
        return 0
    return round(risk_amount / risk_per_unit, 6)

def place_order(exchange, symbol: str, signal: Signal, qty: float) -> Optional[Trade]:
    mode = "SIM" if state.sim_mode else "LIVE"
    if state.sim_mode:
        trade = Trade(
            id=f"SIM-{len(state.trades)+1:04d}",
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
            f"[SIM] [{signal.setup_type.upper()}] {signal.side.upper()} {qty:.4f} {symbol} @ {signal.entry:.0f} | "
            f"SL={signal.stop_loss:.0f} | TP1={signal.tp1:.0f} | TP2={signal.tp2:.0f} | TP3={signal.tp3:.0f}"
        )
        send_telegram(
            f"📈 <b>TRADE OPEN [{mode}]</b>\n"
            f"{signal.setup_type.upper()} {signal.side.upper()} {qty:.4f} {symbol}\n"
            f"Entry: {signal.entry:.0f} | SL: {signal.stop_loss:.0f}\n"
            f"TP1: {signal.tp1:.0f} | TP2: {signal.tp2:.0f} | TP3: {signal.tp3:.0f}\n"
            f"<i>{signal.reason}</i>"
        )
        return trade
    else:
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
                f"[LIVE] [{signal.setup_type.upper()}] {signal.side.upper()} {qty} {symbol} @ {signal.entry:.0f} | "
                f"SL={signal.stop_loss:.0f} | TP1={signal.tp1:.0f} | TP2={signal.tp2:.0f} | TP3={signal.tp3:.0f}"
            )
            send_telegram(
                f"📈 <b>TRADE OPEN [{mode}]</b>\n"
                f"{signal.setup_type.upper()} {signal.side.upper()} {qty} {symbol}\n"
                f"Entry: {signal.entry:.0f} | SL: {signal.stop_loss:.0f}\n"
                f"TP1: {signal.tp1:.0f} | TP2: {signal.tp2:.0f} | TP3: {signal.tp3:.0f}\n"
                f"<i>{signal.reason}</i>"
            )
            return trade
        except Exception as e:
            logger.error(f"Order mislukt: {e}")
            return None

def partial_close(exchange, trade: Trade, fraction: float, curr_price: float, label: str):
    """Sluit een deel van de positie — echt of gesimuleerd."""
    qty = round(trade.quantity * fraction, 6)

    if not state.sim_mode:
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

    mode = "SIM" if state.sim_mode else "LIVE"
    logger.info(f"[{mode}] {label} ({fraction*100:.0f}% @ {curr_price:.0f}) | PnL = {pnl:.2f} USDT")
    return pnl

def trail_sl_to_structure(trade: Trade, candles: list, phase: int):
    """
    Verschuif SL naar relevante prijsactie na TP2 en TP3.
    phase 2 → laatste swing low/high
    phase 3 → nieuwste swing punt nog dichter bij prijs
    """
    swing_highs, swing_lows = get_swing_points(candles[:-1], lookback=3)

    if trade.side == "buy" and swing_lows:
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
            remaining = 1.0
            if trade.tp1_hit: remaining -= 0.25
            if trade.tp2_hit: remaining -= 0.25
            if trade.tp3_hit: remaining -= 0.25
            partial_close(exchange, trade, remaining, curr_price, "❌ SL")
            trade.status = "closed"
            trade.exit_price = curr_price

            _record_equity()
            state.consecutive_stops += 1
            send_telegram(
                f"❌ <b>SL HIT</b>\n"
                f"{trade.setup_type.upper()} {trade.side.upper()} {trade.symbol}\n"
                f"Entry: {trade.entry_price:.0f} → Exit: {curr_price:.0f}\n"
                f"PnL: {trade.realized_pnl:+.2f} USDT | Stops op rij: {state.consecutive_stops}"
            )

            # Circuit breaker na 5 stops op rij
            if state.consecutive_stops >= 5:
                state.circuit_breaker_until = time.time() + 86400  # 24 uur
                resume = datetime.utcfromtimestamp(state.circuit_breaker_until).strftime('%Y-%m-%d %H:%M UTC')
                logger.warning(f"Circuit breaker actief tot {resume}")
                send_telegram(
                    f"🚨 <b>CIRCUIT BREAKER</b>\n"
                    f"5 stops op rij — bot gepauzeerd.\n"
                    f"Hervat om: {resume}"
                )

        elif hit_tp1:
            partial_close(exchange, trade, 0.25, curr_price, "✅ TP1")
            trade.tp1_hit = True
            trade.status = "partial_1"
            trade.stop_loss = trade.entry_price  # → breakeven
            _record_equity()
            state.consecutive_stops = 0
            logger.info(f"SL verschoven naar breakeven: {trade.entry_price:.0f}")
            send_telegram(
                f"✅ <b>TP1 GERAAKT</b>\n"
                f"{trade.setup_type.upper()} {trade.side.upper()} @ {curr_price:.0f}\n"
                f"PnL tot nu: {trade.realized_pnl:+.2f} USDT | SL → breakeven"
            )

        elif hit_tp2:
            partial_close(exchange, trade, 0.25, curr_price, "✅ TP2")
            trade.tp2_hit = True
            trade.status = "partial_2"
            trail_sl_to_structure(trade, candles_15m, phase=2)
            _record_equity()
            state.consecutive_stops = 0
            send_telegram(
                f"✅ <b>TP2 GERAAKT</b>\n"
                f"{trade.setup_type.upper()} {trade.side.upper()} @ {curr_price:.0f}\n"
                f"PnL tot nu: {trade.realized_pnl:+.2f} USDT | SL → swing PA"
            )

        elif hit_tp3:
            partial_close(exchange, trade, 0.25, curr_price, "✅ TP3")
            trade.tp3_hit = True
            trade.status = "partial_3"
            trail_sl_to_structure(trade, candles_15m, phase=3)
            _record_equity()
            state.consecutive_stops = 0
            send_telegram(
                f"✅ <b>TP3 GERAAKT</b>\n"
                f"{trade.setup_type.upper()} {trade.side.upper()} @ {curr_price:.0f}\n"
                f"PnL tot nu: {trade.realized_pnl:+.2f} USDT | Runner actief, SL trailend"
            )

        elif trade.tp3_hit:
            # Runner fase: SL continu trailen op elke nieuwe candle
            trail_sl_to_structure(trade, candles_15m, phase=4)

def run_bot():
    state.sim_mode = os.environ.get('SIM_MODE', 'true').lower() == 'true'
    mode_label = "PAPER TRADING" if state.sim_mode else "LIVE TRADING"

    # SIM: Binance publieke API voor candles (geen auth). LIVE: OKX met auth.
    exchange = get_public_exchange() if state.sim_mode else get_exchange()
    logger.info(f"DoopieCash Bot gestart | {state.symbol} | {mode_label}")

    if state.sim_mode:
        state.sim_balance = float(os.environ.get('SIM_BALANCE', '10000'))
        state.balance = state.sim_balance
        state.equity  = state.sim_balance
        logger.info(f"[SIM] Startkapitaal: ${state.balance:,.0f}")

    while state.running:
        try:
            # ── Circuit breaker ────────────────────────────────────────────────
            if state.circuit_breaker_until and time.time() < state.circuit_breaker_until:
                resume = datetime.utcfromtimestamp(state.circuit_breaker_until).strftime('%H:%M UTC')
                logger.info(f"Circuit breaker actief — hervat om {resume}")
                time.sleep(60)
                continue

            # ── Balance ophalen ────────────────────────────────────────────────
            if state.sim_mode:
                state.balance = state.sim_balance + state.total_pnl
                state.equity  = state.balance
            else:
                balance_info = exchange.fetch_balance()
                for currency in ['USDT', 'USDC', 'USD']:
                    if currency in balance_info and balance_info[currency]['total'] > 0:
                        state.balance = float(balance_info[currency]['free'])
                        state.equity  = float(balance_info[currency]['total'])
                        break

            # ── Daily loss limit ───────────────────────────────────────────────
            today = datetime.utcnow().strftime('%Y-%m-%d')
            if state.day_date != today:
                state.day_date = today
                state.day_start_equity = state.equity

            if state.day_start_equity > 0 and state.equity < state.day_start_equity * 0.97:
                daily_pct = (state.equity - state.day_start_equity) / state.day_start_equity * 100
                logger.warning(f"Daily loss limit bereikt ({daily_pct:.1f}%). Geen nieuwe trades vandaag.")
                time.sleep(60)
                continue

            # ── Marktdata ─────────────────────────────────────────────────────
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

                        # ATR-gebaseerde positiegrootte: kleinere positie bij hoge volatiliteit
                        atr14 = calc_atr(candles_15m, 14)
                        atr50 = calc_atr(candles_15m, min(50, len(candles_15m)))
                        # vol_scale = atr50/atr14: bij hoge vol (atr14>atr50) → schaal <1, geclampt [0.5, 2.0]
                        vol_scale = max(0.5, min(2.0, atr50 / atr14)) if atr14 > 0 else 1.0

                        qty = calculate_position_size(
                            state.balance, signal.entry,
                            signal.stop_loss, state.risk_per_trade, vol_scale
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
