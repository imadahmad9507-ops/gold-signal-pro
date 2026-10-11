"""
SQLite and CSV Signal Performance Tracker.
Records every issued signal, monitors active signals until outcome (TP1, TP2, TP3, SL, Invalidation, Timeout),
and computes rolling win rate, profit factor, drawdown, and visual AI agreement statistics.
"""
import os
import sqlite3
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "tracking", "signals.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


class SignalTracker:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry REAL NOT NULL,
                stop_loss REAL NOT NULL,
                tp1 REAL NOT NULL,
                tp2 REAL NOT NULL,
                tp3 REAL,
                lot_size REAL NOT NULL,
                confluence_score REAL NOT NULL,
                grade TEXT NOT NULL,
                status TEXT NOT NULL, -- 'OPEN', 'TP1_HIT', 'TP2_HIT', 'TP3_HIT', 'SL_HIT', 'INVALIDATED', 'EXPIRED'
                outcome_r REAL DEFAULT 0.0,
                closed_at TEXT,
                visual_bias TEXT,
                visual_confidence INTEGER
            )
            """)
            conn.commit()

    def log_new_signal(self, signal: Dict[str, Any], visual_data: Optional[Dict[str, Any]] = None) -> int:
        now_str = datetime.now(timezone.utc).isoformat()
        vis_bias = visual_data.get("bias") if visual_data else None
        vis_conf = visual_data.get("confidence") if visual_data else None

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO signals (
                timestamp, symbol, timeframe, direction, entry, stop_loss, tp1, tp2, tp3,
                lot_size, confluence_score, grade, status, outcome_r, visual_bias, visual_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', 0.0, ?, ?)
            """, (
                now_str,
                signal["symbol"],
                signal["timeframe"],
                signal["direction"],
                signal["entry"],
                signal["stop_loss"],
                signal["tp1"],
                signal["tp2"],
                signal.get("tp3"),
                signal["suggested_lot_size"],
                signal["confluence_score"],
                signal["grade"],
                vis_bias,
                vis_conf
            ))
            conn.commit()
            return cur.lastrowid

    def get_open_signals(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM signals WHERE status = 'OPEN'"
        params = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)

        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def update_signal_status(self, signal_id: int, status: str, outcome_r: float = 0.0):
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute("""
            UPDATE signals SET status = ?, outcome_r = ?, closed_at = ? WHERE id = ?
            """, (status, outcome_r, now_str, signal_id))
            conn.commit()

    def get_performance_stats(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            df = pd.read_sql("SELECT * FROM signals WHERE status != 'OPEN'", conn)

        if df.empty:
            return {
                "total_closed_signals": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_r": 0.0,
                "summary": "No completed signals logged yet."
            }

        total = len(df)
        wins = len(df[df['outcome_r'] > 0])
        win_rate = (wins / total) * 100 if total > 0 else 0.0
        tot_win_r = df[df['outcome_r'] > 0]['outcome_r'].sum()
        tot_loss_r = abs(df[df['outcome_r'] < 0]['outcome_r'].sum())
        pf = round(tot_win_r / (tot_loss_r + 1e-9), 2)
        total_r = round(df['outcome_r'].sum(), 2)

        return {
            "total_closed_signals": total,
            "win_rate": round(win_rate, 1),
            "profit_factor": pf,
            "total_r": total_r,
            "summary": f"{total} trades | {win_rate:.1f}% Win Rate | PF: {pf} | Total Gain: {total_r}R"
        }
