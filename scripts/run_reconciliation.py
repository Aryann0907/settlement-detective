#!/usr/bin/env python3
"""
Settlement Detective — Run Reconciliation CLI
Task: Agent B (Reconciliation Pipeline Runner)

Executes the deterministic reconciliation pipeline across all settlements in the database.
Outputs detailed statistics and financial variance breakdowns.
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.reconciliation import DeterministicReconciliationEngine

DB_PATH = PROJECT_ROOT / "data" / "settlement_detective.db"


def run():
    print("=" * 75)
    print("SETTLEMENT DETECTIVE — DETERMINISTIC RECONCILIATION ENGINE")
    print("=" * 75)

    if not DB_PATH.exists():
        print(f"[FAIL] Database file not found at {DB_PATH}. Run generator first!")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    engine = DeterministicReconciliationEngine(conn)

    start_time = datetime.now()
    summaries = engine.reconcile_all_settlements()
    duration_ms = (datetime.now() - start_time).total_seconds() * 1000

    total_settlements = len(summaries)
    clean_settlements = sum(1 for s in summaries if s.is_clean)
    anomalous_settlements = total_settlements - clean_settlements
    total_variances = sum(len(s.variances) for s in summaries)

    # Log to audit_log
    cursor = conn.cursor()
    audit_id = f"aud_recon_{int(datetime.now(timezone.utc).timestamp())}"
    cursor.execute("""
        INSERT INTO audit_log (id, event_type, entity_type, entity_id, description, actor, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        audit_id,
        "FULL_RECONCILIATION_COMPLETED",
        "system",
        "recon_pipeline_v1",
        f"Reconciled {total_settlements} settlements ({clean_settlements} clean, {anomalous_settlements} with variances) in {duration_ms:.1f}ms.",
        "agent_b_reconciler",
        json.dumps({
            "total_settlements": total_settlements,
            "clean_settlements": clean_settlements,
            "anomalous_settlements": anomalous_settlements,
            "total_variances": total_variances,
            "duration_ms": duration_ms
        }),
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()
    conn.close()

    print(f"\n[✓] Processed {total_settlements} settlements in {duration_ms:.1f}ms.")
    print(f"[✓] Clean settlements (100% Reconciled): {clean_settlements} / {total_settlements} ({clean_settlements/total_settlements*100:.1f}%)")
    print(f"[!] Anomalous settlements detected: {anomalous_settlements}")
    print(f"[!] Total distinct variances identified: {total_variances}")

    print("\n" + "-" * 75)
    print("DETAILED ANOMALY & VARIANCE BREAKDOWN:")
    print("-" * 75)

    category_counts = {}
    for s in summaries:
        if not s.is_clean:
            for v in s.variances:
                cat = v["anomaly_type"]
                category_counts[cat] = category_counts.get(cat, 0) + 1
                var_inr = v["variance_paise"] / 100
                print(f"  [{v['severity']}] {v['anomaly_type']:<24} | Settl: {s.settlement_id} ({s.razorpay_settlement_id}) | Var: INR {var_inr:>+9.2f} | {v['title']}")

    print("-" * 75)
    print("SUMMARY BY ANOMALY CATEGORY:")
    for cat, count in sorted(category_counts.items()):
        print(f"  - {cat:<26}: {count} occurrences")
    print("=" * 75)


if __name__ == "__main__":
    run()
