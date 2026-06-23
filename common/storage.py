"""
SQLite-backed persistent storage for reports and discovered peers.

A single process-wide connection guarded by a lock keeps this simple and
thread-safe across the probe / gossip-server / gossip-client / dashboard
threads, without pulling in any external dependency.
"""
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta

_LOCK = threading.Lock()
_CONN = None


def init(db_path: str):
    global _CONN
    _CONN = sqlite3.connect(db_path, check_same_thread=False)
    _CONN.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            sig TEXT PRIMARY KEY,
            node_id TEXT NOT NULL,
            target TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            status TEXT NOT NULL,
            latency_ms INTEGER NOT NULL
        )
        """
    )
    _CONN.execute(
        "CREATE INDEX IF NOT EXISTS idx_reports_target ON reports(target)"
    )
    _CONN.execute(
        """
        CREATE TABLE IF NOT EXISTS peers (
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            last_seen REAL NOT NULL,
            PRIMARY KEY (host, port)
        )
        """
    )
    _CONN.commit()


def insert_report(report: dict) -> bool:
    """Insert a report. Returns True if it was new, False if already stored
    (the sig is a primary key, so duplicates are naturally rejected)."""
    with _LOCK:
        try:
            _CONN.execute(
                "INSERT INTO reports (sig, node_id, target, timestamp, status, latency_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    report["sig"],
                    report["node_id"],
                    report["target"],
                    report["timestamp"],
                    report["status"],
                    report["latency_ms"],
                ),
            )
            _CONN.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def recent_reports(max_age_seconds: int = 6 * 3600) -> list:
    cutoff = _iso_cutoff(max_age_seconds)
    with _LOCK:
        cur = _CONN.execute(
            "SELECT sig, node_id, target, timestamp, status, latency_ms "
            "FROM reports WHERE timestamp >= ? ORDER BY timestamp DESC",
            (cutoff,),
        )
        rows = cur.fetchall()
    return [_row_to_report(r) for r in rows]


def latest_per_node(max_age_seconds: int = 24 * 3600) -> list:
    """One row per (target, node_id): each node's most recent report."""
    cutoff = _iso_cutoff(max_age_seconds)
    with _LOCK:
        cur = _CONN.execute(
            """
            SELECT r.sig, r.node_id, r.target, r.timestamp, r.status, r.latency_ms
            FROM reports r
            INNER JOIN (
                SELECT target, node_id, MAX(timestamp) AS max_ts
                FROM reports WHERE timestamp >= ?
                GROUP BY target, node_id
            ) latest
            ON r.target = latest.target
               AND r.node_id = latest.node_id
               AND r.timestamp = latest.max_ts
            ORDER BY r.target, r.node_id
            """,
            (cutoff,),
        )
        rows = cur.fetchall()
    return [_row_to_report(r) for r in rows]


def report_count() -> int:
    with _LOCK:
        return _CONN.execute("SELECT COUNT(*) FROM reports").fetchone()[0]


def prune_old_reports(max_age_days: int = 30) -> int:
    """Delete reports older than max_age_days. Returns rows removed.
    Keeps the database bounded — without this it would grow forever."""
    cutoff = _iso_cutoff(max_age_days * 86400)
    with _LOCK:
        cur = _CONN.execute("DELETE FROM reports WHERE timestamp < ?", (cutoff,))
        _CONN.commit()
        return cur.rowcount


def _row_to_report(row) -> dict:
    sig, node_id, target, timestamp, status, latency_ms = row
    return {
        "sig": sig,
        "node_id": node_id,
        "target": target,
        "timestamp": timestamp,
        "status": status,
        "latency_ms": latency_ms,
    }


def _iso_cutoff(max_age_seconds: int) -> str:
    cutoff_dt = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    return cutoff_dt.isoformat(timespec="seconds")


# --- peer discovery (gossip-based peer exchange) ---

def remember_peer(host: str, port: int) -> None:
    with _LOCK:
        _CONN.execute(
            "INSERT INTO peers (host, port, last_seen) VALUES (?, ?, ?) "
            "ON CONFLICT(host, port) DO UPDATE SET last_seen = excluded.last_seen",
            (host, port, time.time()),
        )
        _CONN.commit()


def known_peers() -> list:
    with _LOCK:
        cur = _CONN.execute("SELECT host, port FROM peers ORDER BY last_seen DESC")
        rows = cur.fetchall()
    return [{"host": h, "port": p} for h, p in rows]


def get_target_reports(target: str, limit: int = 50, offset: int = 0) -> list:
    """Recent reports for a specific target, newest first."""
    with _LOCK:
        cur = _CONN.execute(
            "SELECT sig, node_id, target, timestamp, status, latency_ms "
            "FROM reports WHERE target = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (target, limit, offset),
        )
        return [_row_to_report(r) for r in cur.fetchall()]


def get_target_stats(target: str, hours: int = 24) -> dict:
    """Uptime summary for a target over the last N hours."""
    cutoff = _iso_cutoff(hours * 3600)
    with _LOCK:
        cur = _CONN.execute(
            "SELECT status, COUNT(*) FROM reports "
            "WHERE target = ? AND timestamp >= ? GROUP BY status",
            (target, cutoff),
        )
        counts = {row[0]: row[1] for row in cur.fetchall()}
    total = sum(counts.values())
    ok = counts.get("OK", 0)
    return {
        "total": total,
        "ok": ok,
        "by_status": counts,
        "uptime_pct": round(ok / total * 100, 1) if total else 0,
    }


def prune_removed_targets(active_targets: list) -> int:
    """Удаляет отчёты целей, которых больше нет в targets.json."""
    if not active_targets:
        return 0
    placeholders = ",".join("?" * len(active_targets))
    with _LOCK:
        cur = _CONN.execute(
            f"DELETE FROM reports WHERE target NOT IN ({placeholders})",
            active_targets,
        )
        _CONN.commit()
        return cur.rowcount


def get_target_history(target: str, limit: int = 20, offset: int = 0,
                       node_id: str = None) -> dict:
    """Постраничная история проверок конкретной цели."""
    with _LOCK:
        if node_id:
            rows = _CONN.execute(
                "SELECT sig,node_id,target,timestamp,status,latency_ms "
                "FROM reports WHERE target=? AND node_id=? "
                "ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (target, node_id, limit, offset),
            ).fetchall()
            total = _CONN.execute(
                "SELECT COUNT(*) FROM reports WHERE target=? AND node_id=?",
                (target, node_id),
            ).fetchone()[0]
        else:
            rows = _CONN.execute(
                "SELECT sig,node_id,target,timestamp,status,latency_ms "
                "FROM reports WHERE target=? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (target, limit, offset),
            ).fetchall()
            total = _CONN.execute(
                "SELECT COUNT(*) FROM reports WHERE target=?", (target,)
            ).fetchone()[0]

    reports = [_row_to_report(r) for r in rows]
    ok_n = sum(1 for r in reports if r["status"] == "OK")
    lats = [r["latency_ms"] for r in reports if r["latency_ms"] > 0]
    return {
        "target": target,
        "reports": reports,
        "total": total,
        "has_more": offset + limit < total,
        "ok_pct": round(ok_n / len(reports) * 100, 1) if reports else 0,
        "avg_latency_ms": round(sum(lats) / len(lats)) if lats else None,
    }


def known_node_ids_for_target(target: str) -> list:
    with _LOCK:
        rows = _CONN.execute(
            "SELECT DISTINCT node_id FROM reports WHERE target=?", (target,)
        ).fetchall()
    return [r[0] for r in rows]
