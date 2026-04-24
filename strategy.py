"""
DoopieCash Strategy Engine
==========================
4 trade setups op 15m/1h timeframe:

1. BREAKOUT    — candle sluit boven/onder key level + retest van dat level (liquiditeitszone)
2. RANGE       — long aan onderkant, short aan bovenkant van een geïdentificeerde range
3. CONTINUATION— pullback naar vorige constructie (oud resistance = nieuwe support) of prijsactie
4. ROTATION    — structuurbreuk (LL/HH) + bevestiging via afwijzing (lange wick of engulfing)

Risk management:
- Stop loss: net buiten het af te dekken prijsgebied (wick/level)
- Take profits op significante levels in de grafiek:
    TP1 (25%) → SL naar breakeven
    TP2 (25%) → SL naar laatste swing low/high (prijsactie)
    TP3 (25%) → SL naar nieuw swing punt dichter bij prijs
    25% blijft open als "runner" → SL blijft meeschuiven met marktstructuur
- Trend filter: higher highs & higher lows op 1h
"""

from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# ─── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class Level:
    price: float
    strength: int  # hoe vaak getest
    type: str      # 'support' | 'resistance' | 'range_low' | 'range_high'

@dataclass
class Signal:
    setup_type: str          # 'breakout' | 'range' | 'continuation' | 'rotation'
    side: str                # 'buy' | 'sell'
    entry: float
    stop_loss: float
    tp1: float               # 25% uitstap → SL naar breakeven
    tp2: float               # 25% uitstap → SL naar swing prijsactie
    tp3: float               # 25% uitstap → SL naar nieuw swing punt
    # 25% blijft open als runner, SL trailend op marktstructuur
    reason: str
    confidence: float        # 0.0 - 1.0

# ─── Market Structure ──────────────────────────────────────────────────────────

def get_swing_points(candles, lookback: int = 5):
    """Detecteer swing highs en lows voor marktstructuur analyse."""
    highs = [c[2] for c in candles]
    lows  = [c[3] for c in candles]
    swing_highs, swing_lows = [], []

    for i in range(lookback, len(candles) - lookback):
        if highs[i] == max(highs[i-lookback:i+lookback+1]):
            swing_highs.append((i, highs[i]))
        if lows[i] == min(lows[i-lookback:i+lookback+1]):
            swing_lows.append((i, lows[i]))

    return swing_highs, swing_lows

def get_market_structure(candles) -> str:
    """
    Bepaal trend op basis van HH/HL (uptrend) of LL/LH (downtrend).
    Returnt: 'uptrend' | 'downtrend' | 'ranging'
    """
    swing_highs, swing_lows = get_swing_points(candles, lookback=5)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return 'ranging'

    last_highs = [p for _, p in swing_highs[-3:]]
    last_lows  = [p for _, p in swing_lows[-3:]]

    hh = all(last_highs[i] > last_highs[i-1] for i in range(1, len(last_highs)))
    hl = all(last_lows[i]  > last_lows[i-1]  for i in range(1, len(last_lows)))
    ll = all(last_lows[i]  < last_lows[i-1]  for i in range(1, len(last_lows)))
    lh = all(last_highs[i] < last_highs[i-1] for i in range(1, len(last_highs)))

    if hh and hl:
        return 'uptrend'
    if ll and lh:
        return 'downtrend'
    return 'ranging'

def find_key_levels(candles, tolerance: float = 0.002) -> list[Level]:
    """
    Identificeer sterke support/resistance levels op basis van
    hoe vaak de prijs een zone heeft getest of gerespecteerd.
    """
    swing_highs, swing_lows = get_swing_points(candles, lookback=4)
    levels = {}

    def add_level(price, level_type):
        # Cluster levels die dicht bij elkaar liggen
        for existing in list(levels.keys()):
            if abs(existing - price) / price < tolerance:
                levels[existing]['strength'] += 1
                return
        levels[price] = {'strength': 1, 'type': level_type}

    for _, p in swing_highs:
        add_level(p, 'resistance')
    for _, p in swing_lows:
        add_level(p, 'support')

    return [
        Level(price=p, strength=v['strength'], type=v['type'])
        for p, v in levels.items()
        if v['strength'] >= 1  # alle swing levels meenemen; sterkere krijgen hogere confidence
    ]

def detect_range(candles, lookback: int = 40, tolerance: float = 0.010):
    """
    Detecteer een echte consolidatierange.
    Vereisten:
    - Range breedte 2%–4% (strak gedefinieerd)
    - Minimaal 4 touches van zowel high als low zone
    - Prijs wisselt minstens 8x van kant (boven/onder midden)
    - Laatste candle mag range NIET al hebben verlaten
    """
    if len(candles) < lookback:
        return None

    recent = candles[-lookback:]
    n = len(recent)

    highs = [c[2] for c in recent]
    lows  = [c[3] for c in recent]

    # Gebruik 88e en 12e percentiel om extreme wicks te filteren
    range_high = sorted(highs)[int(n * 0.88)]
    range_low  = sorted(lows)[int(n * 0.12)]
    range_size = (range_high - range_low) / range_low

    # Strakke grootte: 2%–4%
    if range_size < 0.02 or range_size > 0.04:
        return None

    mid = (range_high + range_low) / 2

    # Prijs moet echt heen en weer bewegen: minimaal 8 candles elke kant
    above_mid = sum(1 for c in recent if c[4] > mid)
    below_mid = sum(1 for c in recent if c[4] < mid)
    if above_mid < 8 or below_mid < 8:
        return None

    # Minimaal 4 touches per zone
    touches_high = sum(1 for c in recent if c[2] >= range_high * (1 - tolerance))
    touches_low  = sum(1 for c in recent if c[3] <= range_low  * (1 + tolerance))
    if touches_high < 4 or touches_low < 4:
        return None

    # Laatste candle moet nog binnen de range zitten
    last_close = candles[-1][4]
    if last_close > range_high * 1.005 or last_close < range_low * 0.995:
        return None

    return (range_low, range_high)

# ─── Candlestick Helpers ───────────────────────────────────────────────────────

def is_rejection_candle(candle, direction='bullish') -> bool:
    """Lange wick = afwijzing van een level (pin bar stijl)."""
    o, h, l, c = candle[1], candle[2], candle[3], candle[4]
    body  = abs(c - o)
    total = h - l
    if total == 0:
        return False
    if direction == 'bullish':
        lower_wick = min(o, c) - l
        return lower_wick >= body * 2 and lower_wick / total >= 0.5
    else:
        upper_wick = h - max(o, c)
        return upper_wick >= body * 2 and upper_wick / total >= 0.5

def is_engulfing(candles, direction='bullish') -> bool:
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    if direction == 'bullish':
        return (prev[4] < prev[1] and curr[4] > curr[1] and
                curr[1] <= prev[4] and curr[4] >= prev[1])
    else:
        return (prev[4] > prev[1] and curr[4] < curr[1] and
                curr[1] >= prev[4] and curr[4] <= prev[1])

def confirmation_candle(candles, direction='bullish') -> bool:
    """Bevestiging = rejection candle OF engulfing."""
    return (is_rejection_candle(candles[-1], direction) or
            is_engulfing(candles, direction))

def near_level(price, level, tolerance=0.003) -> bool:
    return abs(price - level) / level < tolerance

def find_tp_levels(entry: float, side: str, key_levels: list[Level], candles) -> tuple[float, float, float]:
    """
    Zoek de 3 eerstvolgende significante levels voorbij de entry als TP-levels.
    Gebruikt key levels uit de grafiek — geen vaste R:R.
    Valt terug op ATR-gebaseerde afstanden als er onvoldoende levels zijn.
    """
    atr = sum(abs(c[2] - c[3]) for c in candles[-14:]) / 14

    if side == 'buy':
        # Levels boven entry, gesorteerd van dichtbij naar ver
        candidates = sorted(
            [l.price for l in key_levels if l.price > entry * 1.002],
        )
        # Fallback levels op ATR-basis
        fallbacks = [entry + atr * 2, entry + atr * 3.5, entry + atr * 5.5]
    else:
        # Levels onder entry, gesorteerd van dichtbij naar ver
        candidates = sorted(
            [l.price for l in key_levels if l.price < entry * 0.998],
            reverse=True
        )
        fallbacks = [entry - atr * 2, entry - atr * 3.5, entry - atr * 5.5]

    # Vul aan met fallbacks als er te weinig levels zijn
    while len(candidates) < 3:
        candidates.append(fallbacks[len(candidates)])

    return candidates[0], candidates[1], candidates[2]

# ─── 4 Setup Detectors ────────────────────────────────────────────────────────

def check_breakout(candles, key_levels: list[Level], structure: str) -> Optional[Signal]:
    """
    Breakout setup:
    - Candle sluit boven resistance (of onder support)
    - Wacht op retest van dat level (liquiditeitszone)
    - Bevestiging via rejection of engulfing op retest
    """
    if len(candles) < 10:
        return None

    curr  = candles[-1]
    prev  = candles[-2]
    close = curr[4]
    low   = curr[3]
    high  = curr[2]

    for level in key_levels:
        lp = level.price

        # Bullish breakout
        if (structure in ('uptrend', 'ranging') and
                prev[4] < lp and close > lp * 1.002):
            if near_level(low, lp, 0.008) and confirmation_candle(candles, 'bullish'):
                sl = low - (close - low) * 0.3
                tp1, tp2, tp3 = find_tp_levels(close, 'buy', key_levels, candles)
                return Signal(
                    setup_type='breakout', side='buy',
                    entry=close, stop_loss=sl, tp1=tp1, tp2=tp2, tp3=tp3,
                    reason=f"Bullish breakout + retest van {lp:.0f}",
                    confidence=0.75 + min(level.strength * 0.05, 0.2)
                )

        # Bearish breakout
        if (structure in ('downtrend', 'ranging') and
                prev[4] > lp and close < lp * 0.998):
            if near_level(high, lp, 0.008) and confirmation_candle(candles, 'bearish'):
                sl = high + (high - close) * 0.3
                tp1, tp2, tp3 = find_tp_levels(close, 'sell', key_levels, candles)
                return Signal(
                    setup_type='breakout', side='sell',
                    entry=close, stop_loss=sl, tp1=tp1, tp2=tp2, tp3=tp3,
                    reason=f"Bearish breakout + retest van {lp:.0f}",
                    confidence=0.75 + min(level.strength * 0.05, 0.2)
                )
    return None


def check_range(candles, structure: str = 'ranging') -> Optional[Signal]:
    """
    Range trade:
    - Long aan onderkant — alleen in uptrend of ranging (niet tegen downtrend in)
    - Short aan bovenkant — alleen in downtrend of ranging (niet tegen uptrend in)
    - Vereist minimaal 2 bewezen bounces van het level (niet eerste aanraking)
    """
    result = detect_range(candles)
    if not result:
        return None

    range_low, range_high = result
    close = candles[-1][4]
    low   = candles[-1][3]
    high  = candles[-1][2]
    tolerance = (range_high - range_low) * 0.06

    # Tel bounces: hoeveel keer is prijs al van dit level afgestuiterd?
    recent_closes = [c[4] for c in candles[-30:]]
    bounces_low  = sum(1 for p in recent_closes if abs(p - range_low)  / range_low  < 0.008)
    bounces_high = sum(1 for p in recent_closes if abs(p - range_high) / range_high < 0.008)

    range_levels = [
        Level(price=range_high, strength=3, type='resistance'),
        Level(price=range_low,  strength=3, type='support'),
    ]

    # Minimaal 3 bewezen bounces + trendfilter
    near_low  = abs(close - range_low)  < tolerance
    near_high = abs(close - range_high) < tolerance

    if (near_low and bounces_low >= 3 and
            structure in ('uptrend', 'ranging') and
            confirmation_candle(candles, 'bullish')):
        sl = low - (range_high - range_low) * 0.08   # ruimere SL buffer
        tp1, tp2, tp3 = find_tp_levels(close, 'buy', range_levels, candles)
        tp3 = min(tp3, range_high * 0.995)
        return Signal(
            setup_type='range', side='buy',
            entry=close, stop_loss=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            reason=f"Range long onderkant ({range_low:.0f}–{range_high:.0f}, {bounces_low} bounces)",
            confidence=0.70
        )

    if (near_high and bounces_high >= 3 and
            structure in ('downtrend', 'ranging') and
            confirmation_candle(candles, 'bearish')):
        sl = high + (range_high - range_low) * 0.08  # ruimere SL buffer
        tp1, tp2, tp3 = find_tp_levels(close, 'sell', range_levels, candles)
        tp3 = max(tp3, range_low * 1.005)
        return Signal(
            setup_type='range', side='sell',
            entry=close, stop_loss=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            reason=f"Range short bovenkant ({range_low:.0f}–{range_high:.0f}, {bounces_high} bounces)",
            confidence=0.70
        )
    return None


def check_continuation(candles, key_levels: list[Level], structure: str) -> Optional[Signal]:
    """
    Continuation setup:
    - Trend is duidelijk (uptrend of downtrend)
    - Pullback naar vorige constructie (oud resistance = nieuwe support)
    - Vereist sterkere bevestiging: rejection candle EN close in trendrichting
    """
    if structure not in ('uptrend', 'downtrend'):
        return None

    close = candles[-1][4]
    open_ = candles[-1][1]
    low   = candles[-1][3]
    high  = candles[-1][2]

    for level in key_levels:
        lp = level.price

        # In uptrend: pullback naar vorige resistance (nu support)
        # Extra filter: candle moet bullish sluiten (close > open)
        if (structure == 'uptrend' and level.type == 'resistance' and
                near_level(close, lp, 0.006) and
                close > open_ and                          # bullish candle
                confirmation_candle(candles, 'bullish') and
                level.strength >= 1):
            sl = low - abs(close - lp) * 0.6
            if close - sl <= 0 or close - sl < (close * 0.003):  # min SL afstand 0.3%
                continue
            tp1, tp2, tp3 = find_tp_levels(close, 'buy', key_levels, candles)
            # Valideer R:R intern
            if tp2 - close < (close - sl) * 2:
                continue
            return Signal(
                setup_type='continuation', side='buy',
                entry=close, stop_loss=sl, tp1=tp1, tp2=tp2, tp3=tp3,
                reason=f"Continuation long: pullback naar {lp:.0f} (oud resistance)",
                confidence=0.74
            )

        # In downtrend: pullback naar vorige support (nu resistance)
        # Extra filter: candle moet bearish sluiten (close < open)
        if (structure == 'downtrend' and level.type == 'support' and
                near_level(close, lp, 0.006) and
                close < open_ and                          # bearish candle
                confirmation_candle(candles, 'bearish') and
                level.strength >= 1):
            sl = high + abs(lp - close) * 0.6
            if sl - close <= 0 or sl - close < (close * 0.003):
                continue
            tp1, tp2, tp3 = find_tp_levels(close, 'sell', key_levels, candles)
            if close - tp2 < (sl - close) * 2:
                continue
            return Signal(
                setup_type='continuation', side='sell',
                entry=close, stop_loss=sl, tp1=tp1, tp2=tp2, tp3=tp3,
                reason=f"Continuation short: pullback naar {lp:.0f} (oud support)",
                confidence=0.74
            )
    return None


def check_rotation(candles, structure: str) -> Optional[Signal]:
    """
    Rotation setup:
    - Structuurbreuk: uptrend maakt een LL, downtrend maakt een HH
    - Bevestiging: grote afwijzing (lange wick) OF engulfing candle
    - Beide condities moeten aanwezig zijn
    """
    if len(candles) < 20:
        return None

    swing_highs, swing_lows = get_swing_points(candles[:-1], lookback=4)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None

    close = candles[-1][4]
    low   = candles[-1][3]
    high  = candles[-1][2]

    last_low  = swing_lows[-1][1]
    prev_low  = swing_lows[-2][1]
    last_high = swing_highs[-1][1]
    prev_high = swing_highs[-2][1]

    # Tijdelijke levels voor TP berekening
    key_levels_temp = (
        [Level(price=p, strength=2, type='support')  for _, p in swing_lows[-4:]] +
        [Level(price=p, strength=2, type='resistance') for _, p in swing_highs[-4:]]
    )

    # Rotation naar bearish
    structure_break_bear = (structure == 'uptrend' and last_low < prev_low)
    rejection_bear = (is_rejection_candle(candles[-1], 'bearish') or
                      is_engulfing(candles, 'bearish'))

    if structure_break_bear and rejection_bear:
        sl = high + abs(high - close) * 0.3
        if sl - close > 0:
            tp1, tp2, tp3 = find_tp_levels(close, 'sell', key_levels_temp, candles)
            return Signal(
                setup_type='rotation', side='sell',
                entry=close, stop_loss=sl, tp1=tp1, tp2=tp2, tp3=tp3,
                reason="Rotation: structuurbreuk (LL) + bearish bevestiging",
                confidence=0.78
            )

    # Rotation naar bullish
    structure_break_bull = (structure == 'downtrend' and last_high > prev_high)
    rejection_bull = (is_rejection_candle(candles[-1], 'bullish') or
                      is_engulfing(candles, 'bullish'))

    if structure_break_bull and rejection_bull:
        sl = low - abs(close - low) * 0.3
        if close - sl > 0:
            tp1, tp2, tp3 = find_tp_levels(close, 'buy', key_levels_temp, candles)
            return Signal(
                setup_type='rotation', side='buy',
                entry=close, stop_loss=sl, tp1=tp1, tp2=tp2, tp3=tp3,
                reason="Rotation: structuurbreuk (HH) + bullish bevestiging",
                confidence=0.78
            )
    return None

# ─── Main Analyzer ────────────────────────────────────────────────────────────

def analyze(candles_15m: list, candles_1h: list, cooldown_candles: int = 0) -> Optional[Signal]:
    """
    Analyseer de markt op alle 4 DoopieCash setups.
    Gebruikt 1h voor trendrichting, 15m voor instap.
    Prioriteit: Rotation > Breakout > Continuation > Range

    cooldown_candles: aantal candles sinds laatste SL — geen trades tijdens cooldown.
    """
    if len(candles_15m) < 30 or len(candles_1h) < 20:
        logger.warning("Niet genoeg candles voor analyse")
        return None

    # Cooldown na SL: geen nieuwe entry voor 5 candles (75 min op 15m)
    if cooldown_candles > 0 and cooldown_candles < 5:
        return None

    # Trend bepalen op 1h (hogere context)
    structure_1h  = get_market_structure(candles_1h)
    structure_15m = get_market_structure(candles_15m)

    # Key levels op beide timeframes
    levels_1h  = find_key_levels(candles_1h)
    levels_15m = find_key_levels(candles_15m)
    all_levels = levels_1h + levels_15m

    logger.info(f"Structuur 1h: {structure_1h} | 15m: {structure_15m} | Levels: {len(all_levels)}")

    # Check setups in volgorde van prioriteit
    signal = (
        check_rotation(candles_15m, structure_1h) or
        check_breakout(candles_15m, all_levels, structure_1h) or
        check_continuation(candles_15m, all_levels, structure_1h) or
        check_range(candles_15m, structure_1h)
    )

    if signal:
        # Valideer minimum R:R van 3 (op tp3, niet tp2)
        risk   = abs(signal.entry - signal.stop_loss)
        reward = abs(signal.tp3 - signal.entry)
        rr = reward / risk if risk > 0 else 0
        if rr < 2.5:
            logger.info(f"Signal afgewezen: R:R te laag ({rr:.1f})")
            return None
        logger.info(f"Signal: {signal.setup_type.upper()} {signal.side.upper()} | {signal.reason} | R:R={rr:.1f}")

    return signal
