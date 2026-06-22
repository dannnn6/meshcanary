"""
Report format and canonical serialization.

A report is a small signed statement: "node X tried to reach target Y at
time T and got result Z". Canonical serialization (sorted keys, no
whitespace) ensures the same logical report always produces the same bytes,
so a signature stays valid no matter who re-serializes it.
"""
import json

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
    if not all(k in report for k in REPORT_FIELDS + ["sig"]):
        return False
    if report["status"] not in VALID_STATUSES:
        return False
    if not isinstance(report["target"], str) or not isinstance(report["node_id"], str):
        return False
    if len(report["node_id"]) != 64:  # 32-byte ed25519 pubkey, hex-encoded
        return False
    return True
