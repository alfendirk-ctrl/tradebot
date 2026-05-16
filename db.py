"""
Lichtgewicht SQLite persistence voor trades.
Werkt met plain dicts (via dataclasses.asdict) zodat er geen circulaire imports zijn.

Op Railway: zet DB_PATH=/data/trades.db en mount een volume op /data voor echte
persistentie tussen deploys. Standaard schrijft het naar trades.db in de werkmap.
"""

import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get('DB_PATH', 'trades.db')

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS trades (
    id            TEXT PRIMARY KEY,
    symbol        TEXT,
    side          TEXT,
    setup_type    TEXT,
    entry_price   REAL,
    quantity      REAL,
    stop_loss     REAL,
    tp1           REAL,
    tp2           REAL,
    tp3           REAL,
    timestamp     TEXT,
    reason        TEXT,
    status        TEXT DEFAULT 'open',
    tp1_hit       INTEGER DEFAULT 0,
    tp2_hit       INTEGER DEFAULT 0,
    tp3_hit       INTEGER DEFAULT 0,
    exit_price    REAL,
    realized_pnl  REAL DEFAULT 0.0,
    session       TEXT DEFAULT 'unknown',
    valid_until   TEXT DEFAULT ''
);
"""

_MIGRATIONS = [
    "ALTER TABLE trades ADD COLUMN candle_snapshot TEXT",
    "ALTER TABLE trades ADD COLUMN review_label    TEXT DEFAULT NULL",
    "ALTER TABLE trades ADD COLUMN review_note     TEXT DEFAULT NULL",
]

def _conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    with _conn() as c:
        c.execute(_CREATE_TABLE)
        for sql in _MIGRATIONS:
            try:
                c.execute(sql)
            except Exception:
                pass  # column already exists
    logger.info(f"Database geïnitialiseerd: {DB_PATH}")

def save_trade(t: dict):
    sql = """
    INSERT OR REPLACE INTO trades
        (id, symbol, side, setup_type, entry_price, quantity, stop_loss,
         tp1, tp2, tp3, timestamp, reason, status,
         tp1_hit, tp2_hit, tp3_hit, exit_price, realized_pnl, session, valid_until,
         review_label, review_note)
    VALUES
        (:id, :symbol, :side, :setup_type, :entry_price, :quantity, :stop_loss,
         :tp1, :tp2, :tp3, :timestamp, :reason, :status,
         :tp1_hit, :tp2_hit, :tp3_hit, :exit_price, :realized_pnl, :session, :valid_until,
         :review_label, :review_note)
    """
    with _conn() as c:
        c.execute(sql, {
            **t,
            'tp1_hit': int(t.get('tp1_hit', False)),
            'tp2_hit': int(t.get('tp2_hit', False)),
            'tp3_hit': int(t.get('tp3_hit', False)),
            'session': t.get('session', 'unknown'),
            'valid_until': t.get('valid_until', ''),
            'review_label': t.get('review_label', None),
            'review_note': t.get('review_note', None),
        })

def update_trade(t: dict):
    sql = """
    UPDATE trades SET
        stop_loss    = :stop_loss,
        status       = :status,
        tp1_hit      = :tp1_hit,
        tp2_hit      = :tp2_hit,
        tp3_hit      = :tp3_hit,
        exit_price   = :exit_price,
        realized_pnl = :realized_pnl
    WHERE id = :id
    """
    with _conn() as c:
        c.execute(sql, {
            **t,
            'tp1_hit': int(t.get('tp1_hit', False)),
            'tp2_hit': int(t.get('tp2_hit', False)),
            'tp3_hit': int(t.get('tp3_hit', False)),
        })

def load_trades() -> list[dict]:
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT id, symbol, side, setup_type, entry_price, quantity, stop_loss, "
            "tp1, tp2, tp3, timestamp, reason, status, tp1_hit, tp2_hit, tp3_hit, "
            "exit_price, realized_pnl, session, valid_until, review_label, review_note "
            "FROM trades ORDER BY timestamp ASC"
        ).fetchall()
    trades = []
    for row in rows:
        d = dict(row)
        d['tp1_hit'] = bool(d['tp1_hit'])
        d['tp2_hit'] = bool(d['tp2_hit'])
        d['tp3_hit'] = bool(d['tp3_hit'])
        trades.append(d)
    logger.info(f"{len(trades)} trades geladen uit database")
    return trades

def clear_trades():
    with _conn() as c:
        c.execute("DELETE FROM trades")

def save_candle_snapshot(trade_id: str, candles: list):
    import json
    with _conn() as c:
        c.execute("UPDATE trades SET candle_snapshot = ? WHERE id = ?",
                  (json.dumps(candles), trade_id))

def get_trade_candles(trade_id: str):
    import json
    with _conn() as c:
        row = c.execute("SELECT candle_snapshot FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not row or not row[0]:
        return None
    return json.loads(row[0])

def save_review(trade_id: str, label: str, note: str = ""):
    with _conn() as c:
        c.execute("UPDATE trades SET review_label = ?, review_note = ? WHERE id = ?",
                  (label, note, trade_id))

def load_reviews_summary() -> list[dict]:
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT setup_type, side, realized_pnl, review_label, review_note "
            "FROM trades WHERE status = 'closed' AND review_label IS NOT NULL"
        ).fetchall()
    return [dict(r) for r in rows]
