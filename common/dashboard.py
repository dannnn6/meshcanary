"""
Mesh Canary — веб-дашборд с поддержкой нескольких нод.

Локальный узел всегда отображается. Дополнительные ноды добавляются
через UI по адресу IP:PORT — данные агрегируются на стороне сервера
(Python urllib), чтобы не было проблем с CORS.
Список нод хранится в data/dashboard_nodes.json.
"""
import json
import os
import threading
import urllib.request
import urllib.error
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import storage

_NODE_ID = ""
_NODES_FILE = ""
_NODES_LOCK = threading.Lock()


def _load_nodes():
    if not _NODES_FILE or not os.path.exists(_NODES_FILE):
        return []
    try:
        with open(_NODES_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_nodes(nodes):
    with open(_NODES_FILE, "w") as f:
        json.dump(nodes, f, indent=2)


def _fetch_node(url: str) -> dict | None:
    try:
        req = urllib.request.urlopen(
            f"{url.rstrip('/')}/api/status", timeout=4
        )
        return json.loads(req.read())
    except Exception:
        return None


def _aggregate_local():
    rows = storage.latest_per_node(max_age_seconds=24 * 3600)
    by_target = defaultdict(dict)
    for r in rows:
        by_target[r["target"]][r["node_id"]] = r
    return {
        "node_id": _NODE_ID,
        "label": "этот узел",
        "url": "local",
        "report_count": storage.report_count(),
        "known_peers": len(storage.known_peers()),
        "targets": {t: list(v.values()) for t, v in by_target.items()},
        "reachable": True,
    }


def _build_hub_data():
    """Собирает данные со всех нод: локальной + внешних."""
    result = [_aggregate_local()]
    for node in _load_nodes():
        data = _fetch_node(node["url"])
        if data:
            data["label"] = node.get("label", node["url"])
            data["url"] = node["url"]
            data["reachable"] = True
        else:
            data = {
                "label": node.get("label", node["url"]),
                "url": node["url"],
                "reachable": False,
                "targets": {},
                "report_count": 0,
            }
        result.append(data)
    return result


# ─── HTML ─────────────────────────────────────────────────────────────────
_HTML = """\
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>Mesh Canary</title>
<style>
:root{--bg:#15130F;--s:#1C1914;--b:#2a2c24;--t:#EDE8DD;--dim:#9a9288;
  --amber:#E8A33D;--ok:#4FA37C;--err:#C1503A;--warn:#d4962a;
  --ff:'IBM Plex Mono',monospace}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--t);font-family:system-ui,sans-serif;
  font-size:14px;line-height:1.5;padding:20px}
h1{font-size:18px;font-weight:500;margin-bottom:4px}
.meta{color:var(--dim);font-size:12px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px;margin-bottom:20px}
.card{background:var(--s);border:1px solid var(--b);border-radius:10px;padding:14px}
.card-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.card-title{font-weight:500;font-size:13px}
.badge{font-family:var(--ff);font-size:11px;padding:2px 8px;border-radius:12px}
.badge.ok{background:#1a3d2c;color:var(--ok)}
.badge.err{background:#3d1a1a;color:var(--err)}
.badge.warn{background:#3d2e10;color:var(--warn)}
.target-row{display:flex;justify-content:space-between;font-size:12px;
  padding:4px 0;border-top:1px solid var(--b);color:var(--dim)}
.target-row .dn{color:var(--t)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px}
.dot.ok{background:var(--ok)}
.dot.err{background:var(--err)}
.add-panel{background:var(--s);border:1px solid var(--b);border-radius:10px;
  padding:14px;max-width:500px}
.add-panel h2{font-size:14px;font-weight:500;margin-bottom:10px}
.row{display:flex;gap:8px;margin-bottom:8px}
input{background:#0e0e0c;border:1px solid var(--b);border-radius:6px;
  color:var(--t);font-size:13px;padding:6px 10px;flex:1;outline:none}
input:focus{border-color:var(--amber)}
button{background:var(--amber);border:none;border-radius:6px;color:#1a1407;
  cursor:pointer;font-size:12px;font-weight:600;padding:6px 14px;white-space:nowrap}
button.del{background:#3d1a1a;color:var(--err)}
.node-list{margin-top:10px}
.node-item{display:flex;justify-content:space-between;align-items:center;
  padding:5px 0;border-top:1px solid var(--b);font-size:12px;color:var(--dim)}
code{font-family:var(--ff);font-size:11px;color:var(--dim)}
</style>
</head>
<body>
<h1>Mesh Canary</h1>
<div class="meta" id="meta">загрузка...</div>
<div class="grid" id="grid"></div>

<div class="add-panel">
  <h2>Добавить ноду в хаб</h2>
  <div class="row">
    <input id="nurl" placeholder="http://1.2.3.4:8080" />
    <input id="nlabel" placeholder="Название (необязательно)" style="max-width:180px"/>
    <button onclick="addNode()">Добавить</button>
  </div>
  <div class="node-list" id="node-list"></div>
</div>

<script>
async function load(){
  try{
    const r=await fetch('/api/hub');
    const nodes=await r.json();
    const grid=document.getElementById('grid');
    grid.innerHTML='';
    let total=0,totalPeers=0;
    nodes.forEach(n=>{
      total+=n.report_count||0;
      totalPeers+=n.known_peers||0;
      const ok=n.reachable;
      const targets=n.targets||{};
      const rows=Object.entries(targets).map(([t,rs])=>{
        const nOk=rs.filter(r=>r.status==='OK').length;
        const all=rs.length;
        const cls=nOk===all?'ok':'err';
        return `<div class="target-row">
          <span><span class="dot ${cls}"></span><span class="dn">${t}</span></span>
          <span>${nOk}/${all}</span></div>`;
      }).join('');
      const badge=ok?'<span class="badge ok">online</span>':'<span class="badge err">недоступна</span>';
      grid.innerHTML+=`<div class="card">
        <div class="card-head"><span class="card-title">${n.label}</span>${badge}</div>
        <div style="margin-bottom:8px"><code>${(n.node_id||'').slice(0,16)}…</code>
          <span style="color:var(--dim);font-size:11px;margin-left:8px">${n.report_count||0} отчётов · ${n.known_peers||0} пиров</span></div>
        ${rows||'<div style="color:var(--dim);font-size:12px">нет данных</div>'}
      </div>`;
    });
    document.getElementById('meta').textContent=
      `узлов в хабе: ${nodes.length} · отчётов всего: ${total} · пиров: ${totalPeers} · обновление каждые 10с`;
  }catch(e){console.error(e)}
  loadNodes();
}

async function loadNodes(){
  const r=await fetch('/api/nodes');
  const nodes=await r.json();
  const el=document.getElementById('node-list');
  if(!nodes.length){el.innerHTML='<div style="color:var(--dim);font-size:12px;margin-top:4px">Нет добавленных нод</div>';return;}
  el.innerHTML=nodes.map((n,i)=>`
    <div class="node-item">
      <span><b>${n.label||n.url}</b> <code>${n.url}</code></span>
      <button class="del" onclick="removeNode(${i})">✕</button>
    </div>`).join('');
}

async function addNode(){
  const url=document.getElementById('nurl').value.trim();
  const label=document.getElementById('nlabel').value.trim()||url;
  if(!url)return;
  await fetch('/api/nodes',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({url,label})});
  document.getElementById('nurl').value='';
  document.getElementById('nlabel').value='';
  load();
}

async function removeNode(i){
  await fetch('/api/nodes',{method:'DELETE',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({index:i})});
  load();
}

load();
</script>
</body>
</html>
"""


def _make_handler(node_id: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_GET(self):
            if self.path == "/api/status":
                self._json(_aggregate_local())
            elif self.path == "/api/hub":
                self._json(_build_hub_data())
            elif self.path == "/api/nodes":
                self._json(_load_nodes())
            else:
                self._send(_HTML.encode(), "text/html; charset=utf-8")

        def do_POST(self):
            if self.path == "/api/nodes":
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with _NODES_LOCK:
                    nodes = _load_nodes()
                    if not any(n["url"] == body["url"] for n in nodes):
                        nodes.append({"url": body["url"], "label": body.get("label", body["url"])})
                        _save_nodes(nodes)
                self._json({"ok": True})

        def do_DELETE(self):
            if self.path == "/api/nodes":
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with _NODES_LOCK:
                    nodes = _load_nodes()
                    idx = body.get("index", -1)
                    if 0 <= idx < len(nodes):
                        nodes.pop(idx)
                        _save_nodes(nodes)
                self._json({"ok": True})

        def _json(self, obj):
            self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json")

        def _send(self, body: bytes, ct: str):
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return H


def start(port: int, host: str, node_id: str, nodes_file: str):
    global _NODE_ID, _NODES_FILE
    _NODE_ID = node_id
    _NODES_FILE = nodes_file
    server = ThreadingHTTPServer((host, port), _make_handler(node_id))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
