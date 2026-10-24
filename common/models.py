"""
Report format and canonical serialization.

A report is a small signed statement: "node X tried to reach target Y at
time T and got result Z". Canonical serialization (sorted keys, no
whitespace) ensures the same logical report always produces the same bytes,
so a signature stays valid no matter who re-serializes it.
"""
import json
from datetime import datetime, timedelta, timezone

REPORT_FIELDS = ["node_id", "target", "timestamp", "status", "latency_ms"]

VALID_STATUSES = {
    "OK",
    "DNS_FAIL",
    "TCP_TIMEOUT",
    "TCP_REFUSED",
    "TCP_FAIL",
    "TLS_FAIL",
}


def canonical_bytes(report: dict) -> bytes:
    payload = {k: report[k] for k in REPORT_FIELDS}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def is_well_formed(report: dict) -> bool:
    if not isinstance(report, dict):
        return False

    if not all(k in report for k in REPORT_FIELDS + ["sig"]):
        return False

    status = report.get("status")
    if not isinstance(status, str) or status not in VALID_STATUSES:
        return False

    node_id = report["node_id"]
    sig = report["sig"]
    target = report["target"]
    timestamp = report["timestamp"]
    latency = report["latency_ms"]

    if not isinstance(node_id, str) or len(node_id) != 64:
        return False

    if not isinstance(sig, str) or len(sig) != 128:
        return False

    try:
        bytes.fromhex(node_id)
        bytes.fromhex(sig)
    except ValueError:
        return False

    if not isinstance(target, str) or not 1 <= len(target) <= 253:
        return False

    if not isinstance(timestamp, str):
        return False

    try:
        reported_at = datetime.fromisoformat(timestamp)
    except ValueError:
        return False

    if reported_at.tzinfo is None:
        return False

    if reported_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return False

    if type(latency) is not int:
        return False

    if report["status"] == "OK":
        return latency >= 0

    return latency == -1
