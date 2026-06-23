"""
Mesh Canary node.

Each running instance is one volunteer node:
  1. Periodically probes a list of targets (DNS -> TCP -> TLS) and signs
     the results.
  2. Stores everything in a local SQLite database, so history survives
     restarts.
  3. Runs a gossip server + client that exchange signed reports *and*
     known peer addresses with other nodes — a node only needs to know
     ONE bootstrap peer to eventually learn about the rest of the
     network (peer exchange, the same idea BitTorrent's PEX uses).
  4. Serves a small built-in web dashboard so you can watch it live in a
     browser instead of reading log lines.

There is no central server anywhere in this picture.
"""
import argparse
import json
import os
import random
import socket
import ssl
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import crypto, models, protocol, storage, dashboard

ADVERTISE = None  # (host, port) this node tells peers to reach it on, or None
GOSSIP_WINDOW_SECONDS = 30 * 60  # how far back to re-send reports each gossip round


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

def check_target(host: str, port: int = 443, timeout: float = 5.0):
    """Returns (status, latency_ms_or_None)."""
    start = time.time()
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return "DNS_FAIL", None

    family, socktype, proto, _, sockaddr = infos[0]
    raw_sock = socket.socket(family, socktype, proto)
    raw_sock.settimeout(timeout)
    try:
        raw_sock.connect(sockaddr)
    except (socket.timeout, TimeoutError):
        raw_sock.close()
        return "TCP_TIMEOUT", None
    except ConnectionRefusedError:
        raw_sock.close()
        return "TCP_REFUSED", None
    except OSError:
        raw_sock.close()
        return "TCP_FAIL", None

    try:
        ctx = ssl.create_default_context()
        tls_sock = ctx.wrap_socket(raw_sock, server_hostname=host)
        tls_sock.close()
    except ssl.SSLError:
        return "TLS_FAIL", None
    except OSError:
        return "TCP_FAIL", None

    latency_ms = int((time.time() - start) * 1000)
    return "OK", latency_ms


def make_report(node_id: str, priv, target: str) -> dict:
    status, latency = check_target(target)
    report = {
        "node_id": node_id,
        "target": target,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "latency_ms": latency if latency is not None else -1,
    }
    report["sig"] = crypto.sign(priv, models.canonical_bytes(report))
    return report


def probe_loop(node_id, priv, targets, interval):
    while True:
        for target in targets:
            report = make_report(node_id, priv, target)
            storage.insert_report(report)
            log(f"probe {target:<30} -> {report['status']}")
        time.sleep(interval)


# ---------------------------------------------------------------------------
# Gossip: reports + peer exchange
# ---------------------------------------------------------------------------

def merge_reports(incoming: list) -> int:
    new_count = 0
    for r in incoming:
        if not models.is_well_formed(r):
            continue
        if not crypto.verify(r["node_id"], models.canonical_bytes(r), r["sig"]):
            continue
        if storage.insert_report(r):
            new_count += 1
    return new_count


def merge_peers(incoming_peers: list) -> None:
    for p in incoming_peers:
        host, port = p.get("host"), p.get("port")
        if not host or not isinstance(port, int):
            continue
        if ADVERTISE and (host, port) == ADVERTISE:
            continue  # don't add ourselves
        storage.remember_peer(host, port)


def build_peer_sample(sample_size: int = 20) -> list:
    known = storage.known_peers()
    sample = random.sample(known, min(sample_size, len(known))) if known else []
    if ADVERTISE:
        sample.append({"host": ADVERTISE[0], "port": ADVERTISE[1]})
    return sample


def handle_peer_connection(conn):
    try:
        msg = protocol.recv_json(conn)
        if msg.get("type") != "reports":
            return
        new_reports = merge_reports(msg.get("reports", []))
        merge_peers(msg.get("peers", []))
        if new_reports:
            log(f"gossip: получено {new_reports} новых отчётов")
        protocol.send_json(
            conn,
            {
                "type": "reports",
                "reports": storage.recent_reports(max_age_seconds=GOSSIP_WINDOW_SECONDS),
                "peers": build_peer_sample(),
            },
        )
    except Exception as e:
        log(f"gossip: ошибка соединения: {e}")
    finally:
        conn.close()


def gossip_server(listen_port: int):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", listen_port))
    server.listen(20)
    log(f"gossip-сервер слушает порт {listen_port}")
    while True:
        conn, _ = server.accept()
        threading.Thread(target=handle_peer_connection, args=(conn,), daemon=True).start()


def gossip_with_peer(host: str, port: int):
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            protocol.send_json(
                sock,
                {
                    "type": "reports",
                    "reports": storage.recent_reports(max_age_seconds=GOSSIP_WINDOW_SECONDS),
                    "peers": build_peer_sample(),
                },
            )
            reply = protocol.recv_json(sock)
            new_reports = merge_reports(reply.get("reports", []))
            merge_peers(reply.get("peers", []))
            storage.remember_peer(host, port)  # confirmed alive
            if new_reports:
                log(f"gossip: получено {new_reports} новых отчётов от {host}:{port}")
    except Exception as e:
        log(f"gossip: не удалось связаться с {host}:{port} ({e})")


def gossip_client_loop(bootstrap_peers: list, interval: int, fanout: int = 5):
    for p in bootstrap_peers:
        storage.remember_peer(p["host"], p["port"])
    while True:
        time.sleep(interval)
        known = storage.known_peers()
        if ADVERTISE:
            known = [p for p in known if (p["host"], p["port"]) != ADVERTISE]
        sample = random.sample(known, min(fanout, len(known))) if known else []
        for peer in sample:
            gossip_with_peer(peer["host"], peer["port"])


# ---------------------------------------------------------------------------
# Status view (console)
# ---------------------------------------------------------------------------

def print_status():
    rows = storage.latest_per_node(max_age_seconds=24 * 3600)
    by_target = {}
    for r in rows:
        by_target.setdefault(r["target"], {})[r["node_id"]] = r

    print("\n=== mesh canary status ===")
    for target, by_node in sorted(by_target.items()):
        ok = sum(1 for r in by_node.values() if r["status"] == "OK")
        total = len(by_node)
        print(f"  {target:<30} {ok}/{total} nodes report reachable")
        for node_id, r in sorted(by_node.items()):
            print(f"      {node_id[:12]}…  {r['status']:<12} {r['timestamp']}")
    print(f"  известных пиров: {len(storage.known_peers())} · "
          f"всего подписанных отчётов: {storage.report_count()}\n")


def status_loop(interval: int):
    while True:
        time.sleep(interval)
        print_status()


def prune_loop(retention_days: int, interval: int = 3600):
    while True:
        time.sleep(interval)
        removed = storage.prune_old_reports(retention_days)
        if removed:
            log(f"очистка: удалено {removed} отчётов старше {retention_days} дн.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global ADVERTISE

    parser = argparse.ArgumentParser(description="Mesh Canary node")
    parser.add_argument("--port", type=int, required=True, help="порт gossip-сервера")
    parser.add_argument("--id-file", default="node.key", help="файл с identity-ключом")
    parser.add_argument("--targets", default="targets.json")
    parser.add_argument("--peers", default="peers.json", help="bootstrap-список пиров")
    parser.add_argument("--db", default=None, help="путь к sqlite-файлу (по умолчанию meshcanary_<port>.db)")
    parser.add_argument("--probe-interval", type=int, default=30)
    parser.add_argument("--gossip-interval", type=int, default=15)
    parser.add_argument("--status-interval", type=int, default=60)
    parser.add_argument("--retention-days", type=int, default=45,
                         help="через сколько дней удалять старые отчёты из базы")
    parser.add_argument("--advertise-host", default=None,
                         help="адрес, по которому другие узлы могут достучаться до этого узла "
                              "(нужен, чтобы тебя нашли через peer exchange; для локального теста — 127.0.0.1)")
    parser.add_argument("--web-port", type=int, default=None, help="порт веб-дашборда (если не указан — дашборд выключен)")
    parser.add_argument("--web-host", default="127.0.0.1", help="хост дашборда (127.0.0.1 / 0.0.0.0 / локальный IP)")
    parser.add_argument("--grey-ip", action="store_true", help="режим серого IP: только исходящие gossip-соединения, входящие не принимаются")
    args = parser.parse_args()

    if args.advertise_host:
        ADVERTISE = (args.advertise_host, args.port)

    db_path = args.db or f"meshcanary_{args.port}.db"
    storage.init(db_path)

    priv, node_id = crypto.load_or_create_identity(args.id_file)
    log(f"node id: {node_id}")
    log(f"база данных: {db_path}")

    with open(args.targets) as f:
        targets = json.load(f)["targets"]
    bootstrap_peers = []
    if os.path.exists(args.peers):
        with open(args.peers) as f:
            bootstrap_peers = json.load(f).get("peers", [])

    if not args.grey_ip:
        threading.Thread(target=gossip_server, args=(args.port,), daemon=True).start()
    else:
        log("режим outbound (серый IP): gossip-сервер не запущен, только исходящие соединения")
    threading.Thread(
        target=gossip_client_loop, args=(bootstrap_peers, args.gossip_interval), daemon=True
    ).start()
    threading.Thread(target=status_loop, args=(args.status_interval,), daemon=True).start()
    threading.Thread(target=prune_loop, args=(args.retention_days,), daemon=True).start()

    if args.web_port:
        nodes_file = os.path.join(os.path.dirname(args.db), "dashboard_nodes.json")
        dashboard.start(args.web_port, args.web_host, node_id, nodes_file)
        log(f"веб-дашборд: http://{args.web_host}:{args.web_port}")

    probe_loop(node_id, priv, targets, args.probe_interval)


if __name__ == "__main__":
    main()
