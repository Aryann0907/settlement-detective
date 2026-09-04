"""Focused checks for the read-only reconciliation simulator."""

from pathlib import Path
import sys
from io import BytesIO
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.reconciliation.config import simulate_transaction_reconciliation
from src.ai.server import UnifiedServiceHTTPHandler


def post_simulation(payload):
    """Exercise the API handler without opening a network socket."""
    raw_body = json.dumps(payload).encode("utf-8")
    handler = object.__new__(UnifiedServiceHTTPHandler)
    handler.path = "/api/simulate/reconciliation"
    handler.headers = {"Content-Length": str(len(raw_body))}
    handler.rfile = BytesIO(raw_body)
    handler.wfile = BytesIO()
    statuses = []
    handler._set_headers = lambda status_code=200, content_type="application/json": statuses.append(status_code)
    handler.do_POST()
    return statuses[-1], json.loads(handler.wfile.getvalue())


def main() -> None:
    result = simulate_transaction_reconciliation(10_000, "upi", 0.0204)
    assert result["amount_paise"] == 10_000
    assert result["expected_mdr_rate"] == 0.009
    assert result["actual_mdr_rate"] == 0.0204
    assert result["expected_net_paise"] == 9_894
    assert result["actual_net_paise"] == 9_759
    assert result["variance_paise"] == -135
    assert result["classification"] == "FEE_ANOMALY"
    assert result["data_source"] == "READ_ONLY_SIMULATION"

    matched = simulate_transaction_reconciliation(10_000, "card", 0.0200)
    assert matched["variance_paise"] == 0
    assert matched["classification"] == "MATCHED"

    status, response = post_simulation({
        "amount_inr": "100",
        "payment_method": "upi",
        "actual_mdr_percent": "2.04",
    })
    assert status == 200
    assert response["amount_paise"] == 10_000
    assert response["variance_paise"] == -135

    status, response = post_simulation({
        "amount_inr": "0",
        "payment_method": "upi",
        "actual_mdr_percent": "2.04",
    })
    assert status == 400
    assert "Invalid simulation input" in response["error"]

    try:
        simulate_transaction_reconciliation(0, "upi", 0.02)
    except ValueError:
        pass
    else:
        raise AssertionError("Zero amount must be rejected")

    print("Simulator checks passed: arbitrary amount, fee variance, match, API input validation, and read-only behavior.")


if __name__ == "__main__":
    main()
