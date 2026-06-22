"""
Minimal built-in web dashboard for a Mesh Canary node.

Pure standard library (http.server) — no extra dependencies, no separate
process. Serves a human-readable page at "/" and a JSON view at
"/api/status" for anyone who wants to build their own UI on top.
"""
import json
import threading
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import storage

STATUS_COLOR = {"OK": "#1d9e75"}
DEFAULT_COLOR = "#d85a30"


def _aggregate():
    rows = storage.latest_per_node(max_age_seconds=24 * 3600)
    by_target = defaultdict(dict)
    for r in rows:
        by_target[r["target"]][r["node_id"]] = r
    return by_target


def _render_html(node_id: str) -> str:
    by_target = _aggregate()
    total_reports = storage.report_count()
    known_peer_count = len(storage.known_peers())

    cards = []
    for target, by_node in sorted(by_target.items()):
        ok = sum(1 for r in by_node.values() if r["status"] == "OK")
        total = len(by_node)
        node_rows = "".join(
            f'<div class="node-row"><span class="dot" style="background:'
            f'{STATUS_COLOR.get(r["status"], DEFAULT_COLOR)}"></span>'
            f'<code>{nid[:10]}…</code> '
            f'<span class="status">{r["status"]}</span> '
            f'<span class="ts">{r["timestamp"]}</span></div>'
            for nid, r in sorted(by_node.items())
        )
        cards.append(
            f'<div class="target-card">'
            f'<div class="target-head"><span class="target-name">{target}</span>'
            f'<span class="ratio">{ok}/{total} доступно</span></div>'
            f'{node_rows}</div>'
        )

    body = "".join(cards) if cards else "<p>Пока нет данных — подожди первый цикл проверки.</p>"

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>Mesh Canary</title>
<style>
  body {{ font-family: system-ui, sans-serif; background:#0d0f10; color:#e8e6df; margin:0; padding:24px; }}
  h1 {{ font-size:20px; font-weight:500; margin:0 0 4px; }}
  .meta {{ color:#8a8a82; font-size:13px; margin-bottom:20px; }}
  .target-card {{ background:#17191a; border:1px solid #2a2c2c; border-radius:10px;
                   padding:14px 16px; margin-bottom:12px; max-width:560px; }}
  .target-head {{ display:flex; justify-content:space-between; font-size:15px; margin-bottom:8px; }}
  .target-name {{ font-weight:500; }}
  .ratio {{ color:#9fa39a; }}
  .node-row {{ font-size:13px; color:#b8b6ac; padding:2px 0; }}
  .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }}
  code {{ color:#d8d6cc; }}
  .status {{ display:inline-block; min-width:90px; }}
  .ts {{ color:#74746c; }}
</style>
</head>
<body>
  <h1>Mesh Canary</h1>
  <div class="meta">этот узел: <code>{node_id[:16]}…</code> ·
    известно пиров: {known_peer_count} ·
    подписанных отчётов: {total_reports} ·
    обновление каждые 5с</div>
  {body}
</body>
</html>"""


def _make_handler(node_id: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # node.py already logs what matters; keep stdout clean

        def do_GET(self):
            if self.path == "/api/status":
                by_target = _aggregate()
                payload = {
                    "node_id": node_id,
                    "report_count": storage.report_count(),
                    "known_peers": len(storage.known_peers()),
                    "targets": {t: list(by_node.values()) for t, by_node in by_target.items()},
                }
                self._send(json.dumps(payload, indent=2).encode(), "application/json")
                return
            self._send(_render_html(node_id).encode(), "text/html; charset=utf-8")

        def _send(self, body: bytes, content_type: str):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def start(port: int, node_id: str) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(node_id))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
