"""
Settlement Detective — Grounded Context Builder
Retrieves deterministic variance records, settlements, and linked transactions
from the database to create grounded LLM prompts.
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "settlement_detective.db"


class ContextBuilder:
    """
    Builds minimal, grounded financial context snapshots for the AI service.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def build_investigation_context(self, variance_id: str) -> Dict[str, Any]:
        """Loads the exact variance record and its linked settlement/orders."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM variances WHERE id = ?", (variance_id,))
        var_row = cursor.fetchone()
        if not var_row:
            conn.close()
            raise ValueError(f"Variance '{variance_id}' not found in database.")

        var_dict = dict(var_row)
        evidence_json = var_dict.get("evidence")
        if isinstance(evidence_json, str):
            try:
                var_dict["evidence"] = json.loads(evidence_json)
            except Exception:
                var_dict["evidence"] = {}

        # Fetch settlement metadata if linked
        settlement_id = var_dict.get("settlement_id")
        if settlement_id:
            cursor.execute("SELECT * FROM settlements WHERE id = ?", (settlement_id,))
            s_row = cursor.fetchone()
            if s_row:
                s_dict = dict(s_row)
                var_dict["razorpay_settlement_id"] = s_dict.get("razorpay_settlement_id")
                var_dict["settlement_amount_paise"] = s_dict.get("amount_paise")
                var_dict["settlement_utr"] = s_dict.get("utr")
                var_dict["period_start"] = s_dict.get("period_start")
                var_dict["period_end"] = s_dict.get("period_end")

        conn.close()
        return var_dict

    def build_chat_context(self, query: str) -> Dict[str, Any]:
        """Retrieves relevant settlements, variances, and summary statistics for answering chat questions."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Fetch all detected variances
        cursor.execute("SELECT * FROM variances ORDER BY ABS(variance_paise) DESC LIMIT 20")
        var_rows = cursor.fetchall()
        variances = []
        for r in var_rows:
            d = dict(r)
            if isinstance(d.get("evidence"), str):
                try:
                    d["evidence"] = json.loads(d["evidence"])
                except Exception:
                    d["evidence"] = {}
            variances.append(d)

        # Fetch settlement summary
        cursor.execute("SELECT count(*) as total, sum(amount_paise) as total_payout FROM settlements")
        stats = dict(cursor.fetchone())

        # Fetch recent settlements
        cursor.execute("SELECT id, razorpay_settlement_id, amount_paise, utr, status, settled_at FROM settlements ORDER BY settled_at DESC LIMIT 10")
        recent_settlements = [dict(r) for r in cursor.fetchall()]

        conn.close()
        return {
            "statistics": stats,
            "variances": variances,
            "settlements": recent_settlements
        }
