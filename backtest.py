"""
Walk-forward backtester voor de DoopieCash strategie.

Aanpak:
  - Haalt historische 15m candles op (configurable aantal dagen)
  - Resamplet intern naar 1h en 4h (geen extra API calls)
  - Test window = laatste test_pct van alle candles
  - Train window = de rest (geeft context aan analyze())
  - Voor elke candle in de test window: analyze() aanroepen, trade simuleren
  - Geen look-ahead bias: analyze() ziet alleen candles t/m huidige candle

Vereenvoudiging t.o.v. live bot:
  - Trailing SL na TP2/TP3 is gebaseerd op recente swing lows/highs uit de candles
  - Position sizing gebruikt ATR maar geen vol_scale (te weinig effect op stats)
"""

import math
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime, timezone

from strategy import analyze, calc_atr, get_swing_points

logger = logging.getLogger(__name__)


# ─── Config & Dataclasses ──────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    symbol: str          = "BTC/USDT"
    days: int            = 90      # totale periode
    test_pct: float      = 0.30    # laatste 30% = test window
    risk_per_trade: float = 0.01
    starting_balance: float = 10000.0
    session_filter: bool = True    # London/NY filter aan/uit

@dataclass
class BtTrade:
    id: int
    setup_type: str
    side: str
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    entry_idx: int
    quantity: float
    exit_idx: int    = -1
    exit_price: float = 0.0
    realized_pnl: float = 0.0
    status: str      = "open"   # open | closed
    tp1_hit: bool    = False
    tp2_hit: bool    = False
    tp3_hit: bool    = False

@dataclass
class BacktestResult:
    config: dict             = field(default_factory=dict)
    total_trades: int        = 0
    wins: int                = 0
    losses: int              = 0
    win_rate: float          = 0.0
    profit_factor: float     = 0.0
    sharpe: Optional[float]  = None
    max_drawdown_pct: float  = 0.0
    total_pnl: float         = 0.0
    expectancy: float        = 0.0
    equity_curve: list       = field(default_factory=list)
    trades: list             = field(default_factory=list)
    setup_stats: dict        = field(default_factory=dict)
    train_period: str        = ""
    test_period: str         = ""
    duration_s: float        = 0.0

@dataclass
class BacktestState:
    running: bool            = False
    progress: float          = 0.0   # 0.0–1.0
    result: Optional[dict]   = None
    error: str               = ""

backtest_state = BacktestState()


# ─── Helpers ───────────────────────────────────────────────────────────────────

def resample_candles(candles_15m: list, factor: int) -> list:
    """Resample 15m → hogere timeframe. factor=4 → 1h, factor=16 → 4h."""
    result = []
    for i in range(0, len(candles_15m) - factor + 1, factor):
        grp   = candles_15m[i:i + factor]
        ts    = grp[0][0]
        open_ = grp[0][1]
        high  = max(c[2] for c in grp)
        low   = min(c[3] for c in grp)
        close = grp[-1][4]
        vol   = sum(c[5] for c in grp)
        result.append([ts, open_, high, low, close, vol])
    return result


def _position_size(balance: float, entry: float, stop: float,
                   risk_pct: float, candles: list) -> float:
    risk_amount   = balance * risk_pct
    risk_per_unit = abs(entry - stop)
    if risk_per_unit == 0:
        return 0.0
    return round(risk_amount / risk_per_unit, 6)


def _trail_sl(trade: BtTrade, candles: list) -> None:
    """Schuif SL naar recente swing punt (alleen in gunstige richting)."""
    swing_highs, swing_lows = get_swing_points(candles[:-1], lookback=3)

    if trade.side == "buy" and swing_lows:
        candidates = sorted(
            [p for _, p in swing_lows if p < candles[-1][4]],
            reverse=True,
        )
        if candidates:
            new_sl = candidates[0] * 0.999
            if new_sl > trade.stop_loss:
                trade.stop_loss = new_sl

    elif trade.side == "sell" and swing_highs:
        candidates = sorted(
            [p for _, p in swing_highs if p > candles[-1][4]]
        )
        if candidates:
            new_sl = candidates[0] * 1.001
            if new_sl < trade.stop_loss:
                trade.stop_loss = new_sl


def _manage_trade(trade: BtTrade, candle_close: float,
                  candles_window: list, balance: float) -> float:
    """
    Simuleert één candle van trade management. Geeft PnL-delta terug.
    Past trade in-place aan (status, tp*_hit, stop_loss, exit_price, realized_pnl).
    """
    pnl_delta = 0.0

    hit_sl = (
        (trade.side == "buy"  and candle_close <= trade.stop_loss) or
        (trade.side == "sell" and candle_close >= trade.stop_loss)
    )
    hit_tp1 = not trade.tp1_hit and (
        (trade.side == "buy"  and candle_close >= trade.tp1) or
        (trade.side == "sell" and candle_close <= trade.tp1)
    )
    hit_tp2 = trade.tp1_hit and not trade.tp2_hit and (
        (trade.side == "buy"  and candle_close >= trade.tp2) or
        (trade.side == "sell" and candle_close <= trade.tp2)
    )
    hit_tp3 = trade.tp2_hit and not trade.tp3_hit and (
        (trade.side == "buy"  and candle_close >= trade.tp3) or
        (trade.side == "sell" and candle_close <= trade.tp3)
    )

    if hit_sl:
        remaining = 1.0
        if trade.tp1_hit: remaining -= 0.25
        if trade.tp2_hit: remaining -= 0.25
        if trade.tp3_hit: remaining -= 0.25
        qty = trade.quantity * remaining
        pnl = (candle_close - trade.entry_price) * qty if trade.side == "buy" \
              else (trade.entry_price - candle_close) * qty
        trade.realized_pnl += pnl
        pnl_delta = pnl
        trade.exit_price = candle_close
        trade.status = "closed"

    elif hit_tp1:
        qty = trade.quantity * 0.25
        pnl = (candle_close - trade.entry_price) * qty if trade.side == "buy" \
              else (trade.entry_price - candle_close) * qty
        trade.realized_pnl += pnl
        pnl_delta = pnl
        trade.tp1_hit = True
        trade.stop_loss = trade.entry_price  # breakeven

    elif hit_tp2:
        qty = trade.quantity * 0.25
        pnl = (candle_close - trade.entry_price) * qty if trade.side == "buy" \
              else (trade.entry_price - candle_close) * qty
        trade.realized_pnl += pnl
        pnl_delta = pnl
        trade.tp2_hit = True
        _trail_sl(trade, candles_window)

    elif hit_tp3:
        qty = trade.quantity * 0.25
        pnl = (candle_close - trade.entry_price) * qty if trade.side == "buy" \
              else (trade.entry_price - candle_close) * qty
        trade.realized_pnl += pnl
        pnl_delta = pnl
        trade.tp3_hit = True
        _trail_sl(trade, candles_window)

    elif trade.tp3_hit:
        _trail_sl(trade, candles_window)

    return pnl_delta


# ─── Main Backtester ───────────────────────────────────────────────────────────

def run_backtest(config: BacktestConfig, exchange) -> BacktestResult:
    t_start = time.time()
    result  = BacktestResult(config=asdict(config))

    # ── Data ophalen ──────────────────────────────────────────────────────────
    limit_15m = config.days * 96  # 96 × 15m candles per dag
    logger.info(f"Backtest: {config.symbol} | {config.days}d | {limit_15m} candles ophalen...")
    backtest_state.progress = 0.05

    candles_15m = exchange.fetch_ohlcv(config.symbol, '15m', limit=limit_15m)
    if len(candles_15m) < 200:
        raise ValueError(f"Te weinig candles ontvangen: {len(candles_15m)}")

    candles_1h = resample_candles(candles_15m, 4)
    candles_4h = resample_candles(candles_15m, 16)

    # ── Train / test split ────────────────────────────────────────────────────
    n_total    = len(candles_15m)
    n_test     = max(100, int(n_total * config.test_pct))
    n_train    = n_total - n_test
    test_candles = candles_15m[n_train:]

    def ts_to_str(ts_ms):
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d')

    result.train_period = f"{ts_to_str(candles_15m[0][0])} → {ts_to_str(candles_15m[n_train-1][0])}"
    result.test_period  = f"{ts_to_str(test_candles[0][0])} → {ts_to_str(test_candles[-1][0])}"
    logger.info(f"Train: {result.train_period} | Test: {result.test_period} ({n_test} candles)")

    # ── Simulatie ─────────────────────────────────────────────────────────────
    balance     = config.starting_balance
    equity_curve = [{'idx': 0, 'equity': balance, 'ts': ts_to_str(test_candles[0][0])}]
    trades: list[BtTrade] = []
    open_trade: Optional[BtTrade] = None
    trade_counter = 0
    cooldown = 0

    CTX_15M = 100
    CTX_1H  = 50
    CTX_4H  = 30

    for i, candle in enumerate(test_candles):
        backtest_state.progress = 0.1 + 0.85 * (i / n_test)
        global_i = n_train + i
        close    = candle[4]

        # Context vensters (alleen verleden zichtbaar)
        ctx_15m = candles_15m[max(0, global_i - CTX_15M): global_i]
        ctx_1h  = candles_1h[max(0, (global_i // 4) - CTX_1H): global_i // 4]
        ctx_4h  = candles_4h[max(0, (global_i // 16) - CTX_4H): global_i // 16]

        # Trade management
        if open_trade and open_trade.status == "open":
            pnl_delta = _manage_trade(open_trade, close, ctx_15m, balance)
            balance  += pnl_delta

            if open_trade.status == "closed":
                open_trade.exit_idx = i
                trades.append(open_trade)
                equity_curve.append({
                    'idx': i,
                    'equity': round(balance, 2),
                    'ts': ts_to_str(candle[0]),
                })
                if open_trade.realized_pnl < 0:
                    cooldown = 1
                open_trade = None
            continue  # één trade tegelijk

        # Cooldown tellen
        if cooldown > 0:
            cooldown += 1
            if cooldown >= 5:
                cooldown = 0

        # Geen open trade: zoek signaal
        if len(ctx_15m) < 30 or len(ctx_1h) < 20:
            continue

        signal = analyze(
            ctx_15m, ctx_1h,
            cooldown_candles=cooldown,
            candles_4h=ctx_4h if len(ctx_4h) >= 10 else None,
            session_filter=config.session_filter,
        )

        if signal:
            # Entry drift check (>0.5% stale)
            drift = abs(signal.entry - close) / close
            if drift > 0.005:
                continue

            qty = _position_size(balance, signal.entry, signal.stop_loss,
                                 config.risk_per_trade, ctx_15m)
            if qty <= 0:
                continue

            trade_counter += 1
            open_trade = BtTrade(
                id=trade_counter,
                setup_type=signal.setup_type,
                side=signal.side,
                entry_price=signal.entry,
                stop_loss=signal.stop_loss,
                tp1=signal.tp1,
                tp2=signal.tp2,
                tp3=signal.tp3,
                entry_idx=i,
                quantity=qty,
            )

    # Openstaande trade bij einde forceren sluiten op laatste close
    if open_trade and open_trade.status == "open":
        last_close = test_candles[-1][4]
        qty = open_trade.quantity * (
            1.0
            - (0.25 if open_trade.tp1_hit else 0)
            - (0.25 if open_trade.tp2_hit else 0)
            - (0.25 if open_trade.tp3_hit else 0)
        )
        pnl = (last_close - open_trade.entry_price) * qty if open_trade.side == "buy" \
              else (open_trade.entry_price - last_close) * qty
        open_trade.realized_pnl += pnl
        open_trade.exit_price = last_close
        open_trade.status = "closed"
        open_trade.exit_idx = len(test_candles) - 1
        balance += pnl
        trades.append(open_trade)

    # ── Statistieken berekenen ────────────────────────────────────────────────
    closed = [t for t in trades if t.status == "closed"]
    wins   = [t for t in closed if t.realized_pnl > 0]
    losses = [t for t in closed if t.realized_pnl <= 0]

    gross_profit = sum(t.realized_pnl for t in wins)
    gross_loss   = abs(sum(t.realized_pnl for t in losses))

    result.total_trades    = len(closed)
    result.wins            = len(wins)
    result.losses          = len(losses)
    result.win_rate        = round(len(wins) / len(closed) * 100, 1) if closed else 0.0
    result.profit_factor   = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
    result.total_pnl       = round(balance - config.starting_balance, 2)
    result.expectancy      = round(sum(t.realized_pnl for t in closed) / len(closed), 2) if closed else 0.0
    result.equity_curve    = equity_curve

    # Max drawdown
    if equity_curve:
        equities = [e['equity'] for e in equity_curve]
        peak, max_dd = equities[0], 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        result.max_drawdown_pct = round(max_dd * 100, 2)

    # Sharpe op dagelijkse PnL
    daily: dict = {}
    for t in closed:
        day = ts_to_str(test_candles[t.exit_idx][0])
        daily[day] = daily.get(day, 0.0) + t.realized_pnl
    if len(daily) >= 2:
        returns = list(daily.values())
        n = len(returns)
        mean_r = sum(returns) / n
        var = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        std_r = math.sqrt(var) if var > 0 else 0
        if std_r > 0:
            result.sharpe = round(mean_r / std_r * math.sqrt(252), 2)

    # Per-setup breakdown
    for setup in ['rotation', 'breakout', 'continuation', 'range']:
        ts = [t for t in closed if t.setup_type == setup]
        if not ts:
            result.setup_stats[setup] = {'trades': 0}
            continue
        sw = [t for t in ts if t.realized_pnl > 0]
        sl = [t for t in ts if t.realized_pnl <= 0]
        gp = sum(t.realized_pnl for t in sw)
        gl = abs(sum(t.realized_pnl for t in sl))
        result.setup_stats[setup] = {
            'trades':        len(ts),
            'wins':          len(sw),
            'win_rate':      round(len(sw) / len(ts) * 100, 1),
            'profit_factor': round(gp / gl, 2) if gl > 0 else None,
            'avg_pnl':       round(sum(t.realized_pnl for t in ts) / len(ts), 2),
        }

    result.trades    = [asdict(t) for t in closed[-200:]]  # max 200 trades teruggeven
    result.duration_s = round(time.time() - t_start, 1)

    logger.info(
        f"Backtest klaar in {result.duration_s}s | "
        f"{result.total_trades} trades | WR={result.win_rate}% | "
        f"PF={result.profit_factor} | PnL={result.total_pnl:+.0f}"
    )
    backtest_state.progress = 1.0
    return result
