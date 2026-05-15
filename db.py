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

def _conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    with _conn() as c:
        c.execute(_CREATE_TABLE)
    logger.info(f"Database geïnitialiseerd: {DB_PATH}")

def save_trade(t: dict):
    sql = """
    INSERT OR REPLACE INTO trades
        (id, symbol, side, setup_type, entry_price, quantity, stop_loss,
         tp1, tp2, tp3, timestamp, reason, status,
         tp1_hit, tp2_hit, tp3_hit, exit_price, realized_pnl, session, valid_until)
    VALUES
        (:id, :symbol, :side, :setup_type, :entry_price, :quantity, :stop_loss,
         :tp1, :tp2, :tp3, :timestamp, :reason, :status,
         :tp1_hit, :tp2_hit, :tp3_hit, :exit_price, :realized_pnl, :session, :valid_until)
    """
    with _conn() as c:
        c.execute(sql, {
            **t,
            'tp1_hit': int(t.get('tp1_hit', False)),
            'tp2_hit': int(t.get('tp2_hit', False)),
            'tp3_hit': int(t.get('tp3_hit', False)),
            'session': t.get('session', 'unknown'),
            'valid_until': t.get('valid_until', ''),
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
        rows = c.execute("SELECT * FROM trades ORDER BY timestamp ASC").fetchall()
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
