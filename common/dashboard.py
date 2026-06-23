"""
Mesh Canary — веб-дашборд v3.

Новое в этой версии:
- Увеличенный масштаб UI, вкладки
- Механизм подключения нод через запрос/подтверждение (взаимное)
- Детальный вид по каждой цели с историей и мини-графиком
- Настройки прямо в дашборде (интервал, хранение, список целей)
"""
import json
import os
import threading
import urllib.request
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import storage

_NODE_ID = ""
_NODES_FILE = ""
_JOIN_FILE = ""
_CONFIG_FILE = ""
_TARGETS_FILE = ""
_NODES_LOCK = threading.Lock()
_JOIN_LOCK = threading.Lock()

LIMIT = 25


def _load_json(path, default):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def _read_config() -> dict:
    cfg = {}
    if _CONFIG_FILE and os.path.exists(_CONFIG_FILE):
        with open(_CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return cfg


def _write_config(updates: dict):
    cfg = _read_config()
    cfg.update(updates)
    with open(_CONFIG_FILE, "w") as f:
        for k, v in cfg.items():
            f.write(f"{k}={v}\n")


def _fetch_remote(url: str, path: str = "/api/status", timeout: int = 4):
    try:
        req = urllib.request.urlopen(f"{url.rstrip('/')}{path}", timeout=timeout)
        return json.loads(req.read())
    except Exception:
        return None


def _post_remote(url: str, path: str, body: dict, timeout: int = 4):
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{url.rstrip('/')}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except Exception:
        return None


def _aggregate_local() -> dict:
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


def _build_hub_data() -> list:
    result = [_aggregate_local()]
    for node in _load_json(_NODES_FILE, []):
        data = _fetch_remote(node["url"])
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
                "known_peers": 0,
            }
        result.append(data)
    return result


_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mesh Canary</title>
<style>
:root{--bg:#15130F;--s:#1C1914;--b:#2e2c24;--t:#EDE8DD;--dim:#9a9288;
  --amber:#E8A33D;--ok:#4FA37C;--err:#C1503A;--ff:'IBM Plex Mono',monospace}
*{box-sizing:border-box;margin:0;padding:0}
html{font-size:16px}
body{background:var(--bg);color:var(--t);font-family:system-ui,sans-serif;
  line-height:1.55;padding:28px;max-width:1200px;margin:0 auto}
h1{font-size:24px;font-weight:600;margin-bottom:5px}
h2{font-size:18px;font-weight:500;margin-bottom:14px}
h3{font-size:16px;font-weight:500;margin-bottom:12px}
.meta{color:var(--dim);font-size:14px;margin-bottom:26px}
.tabs{display:flex;gap:4px;margin-bottom:24px;border-bottom:1px solid var(--b)}
.tab{font-size:15px;padding:9px 20px;cursor:pointer;border-radius:8px 8px 0 0;
  color:var(--dim);background:transparent;border:none;border-bottom:2px solid transparent}
.tab.active{color:var(--t);border-bottom:2px solid var(--amber)}
.tab:hover:not(.active){color:var(--t)}
.pane{display:none}.pane.active{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(400px,1fr));gap:18px;margin-bottom:24px}
.card{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:20px}
.card-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.card-title{font-weight:600;font-size:16px}
.badge{font-family:var(--ff);font-size:12px;padding:4px 12px;border-radius:12px}
.badge.ok{background:#1a3d2c;color:var(--ok)}.badge.err{background:#3d1a1a;color:var(--err)}
.card-sub{font-size:13px;color:var(--dim);margin-bottom:12px}
.target-row{display:flex;justify-content:space-between;align-items:center;
  font-size:15px;padding:9px 0;border-top:1px solid var(--b);cursor:pointer}
.target-row:hover .dn{color:var(--amber)}.dn{transition:color .15s}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;flex:none}
.dot.ok{background:var(--ok)}.dot.err{background:var(--err)}
.ratio{font-size:14px;color:var(--dim)}
.panel{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:20px;margin-bottom:18px}
.row{display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap}
input,select{background:#0e0e0c;border:1px solid var(--b);border-radius:8px;
  color:var(--t);font-size:15px;padding:9px 13px;flex:1;outline:none;min-width:120px}
input:focus,select:focus{border-color:var(--amber)}
button{background:var(--amber);border:none;border-radius:8px;color:#1a1407;
  cursor:pointer;font-size:15px;font-weight:600;padding:9px 18px;white-space:nowrap}
button:hover{opacity:.9}
button.sec{background:var(--s);border:1px solid var(--b);color:var(--t)}
button.sec:hover{border-color:var(--amber)}
button.del{background:#3d1a1a;color:var(--err)}
button.ok-btn{background:#1a3d2c;color:var(--ok)}
button:disabled{opacity:.4;cursor:default}
.req-item,.node-item,.target-item,.settings-row{display:flex;justify-content:space-between;
  align-items:center;padding:11px 0;border-top:1px solid var(--b);font-size:15px;gap:12px}
.req-info,.node-info{flex:1}.req-info b,.node-info b{display:block;margin-bottom:2px}
.req-info span,.node-info span{color:var(--dim);font-size:13px}
.req-btns{display:flex;gap:8px}
.settings-row label{color:var(--dim)}
.settings-row input{max-width:130px;flex:none}
.save-ok{color:var(--ok);font-size:14px;margin-left:10px;opacity:0;transition:opacity .3s}
.save-ok.show{opacity:1}
.notice{padding:12px 16px;border-radius:8px;font-size:14px;margin-bottom:16px;line-height:1.5}
.notice.warn{background:#3d2e10;color:#d4962a}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);
  z-index:100;align-items:flex-start;justify-content:center;padding:48px 16px;overflow-y:auto}
.modal-overlay.open{display:flex}
.modal{background:var(--s);border:1px solid var(--b);border-radius:14px;
  width:100%;max-width:820px;padding:28px}
.modal-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.modal-head h2{margin:0;font-size:20px}
.close-btn{background:none;border:none;color:var(--dim);font-size:24px;cursor:pointer;line-height:1}
.close-btn:hover{color:var(--t)}
.stat-row{display:flex;gap:28px;font-size:15px;color:var(--dim);margin-bottom:16px}
.hist-bar{display:flex;gap:3px;flex-wrap:wrap;margin:10px 0 18px}
.hb{width:18px;height:18px;border-radius:4px;cursor:default;flex:none}
.hb.ok{background:var(--ok)}.hb.err{background:var(--err)}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:12px}
th{text-align:left;padding:7px 10px;color:var(--dim);border-bottom:1px solid var(--b);font-weight:400}
td{padding:7px 10px;border-bottom:1px solid #201e18}
tr:hover td{background:#201e18}
.s-ok{color:var(--ok)}.s-err{color:var(--err)}
code{font-family:var(--ff);font-size:13px;color:var(--dim)}
</style>
</head>
<body>
<h1>🐦 Mesh Canary</h1>
<div class="meta" id="meta">загрузка...</div>
<div class="tabs">
  <button class="tab active" onclick="showTab(this,'hub')">Хаб</button>
  <button class="tab" id="tab-req" onclick="showTab(this,'requests')">Запросы</button>
  <button class="tab" onclick="showTab(this,'settings')">Настройки</button>
</div>

<div class="pane active" id="pane-hub">
  <div class="grid" id="grid"></div>
  <div class="panel">
    <h3>Добавить ноду в хаб</h3>
    <div class="row">
      <input id="nurl" placeholder="http://1.2.3.4:8080" style="min-width:220px"/>
      <input id="nlabel" placeholder="Название (необязательно)" style="max-width:220px"/>
      <button onclick="requestJoin()">Запросить подключение</button>
    </div>
    <div id="join-msg" style="font-size:14px;min-height:20px"></div>
    <div id="hub-nodes" style="margin-top:14px"></div>
  </div>
</div>

<div class="pane" id="pane-requests">
  <div class="panel">
    <h3>Входящие запросы на подключение</h3>
    <p style="color:var(--dim);font-size:14px;margin-bottom:16px">
      При подтверждении эта нода появится в хабе запрашивающей, а она — в вашем хабе.
    </p>
    <div id="req-list"><span style="color:var(--dim)">Нет запросов</span></div>
  </div>
</div>

<div class="pane" id="pane-settings">
  <div class="panel">
    <h3>Параметры проверки</h3>
    <div class="notice warn">⚠ Изменения вступают в силу после перезапуска:<br>
      <code>sudo systemctl restart meshcanary</code></div>
    <div class="settings-row">
      <label>Интервал проверки (сек)</label>
      <div style="display:flex;align-items:center;gap:10px">
        <input type="number" id="s-probe" min="5" max="3600"/>
        <button onclick="saveSettings()">Сохранить</button>
        <span class="save-ok" id="s-ok">✓</span>
      </div>
    </div>
    <div class="settings-row">
      <label>Хранить отчёты (дни)</label>
      <input type="number" id="s-retain" min="1" max="365"/>
    </div>
  </div>
  <div class="panel">
    <h3>Список проверяемых сайтов</h3>
    <div id="target-list"></div>
    <div class="row" style="margin-top:14px">
      <input id="new-target" placeholder="example.com"/>
      <button onclick="addTarget()">Добавить</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="modal" onclick="maybeClose(event)">
  <div class="modal">
    <div class="modal-head">
      <h2 id="modal-title">—</h2>
      <button class="close-btn" onclick="closeModal()">✕</button>
    </div>
    <div class="stat-row" id="modal-stats"></div>
    <div style="font-size:13px;color:var(--dim);margin-bottom:6px">Последние проверки:</div>
    <div class="hist-bar" id="modal-bar"></div>
    <div style="display:flex;gap:10px;margin-bottom:14px;align-items:center">
      <select id="node-filter" onchange="loadDetail(0)" style="max-width:320px"></select>
      <button class="sec" onclick="loadDetail(0)">↻</button>
    </div>
    <table>
      <thead><tr><th>Время</th><th>Узел</th><th>Статус</th><th>Задержка</th></tr></thead>
      <tbody id="modal-rows"></tbody>
    </table>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:16px">
      <span id="modal-count" style="font-size:14px;color:var(--dim)"></span>
      <div style="display:flex;gap:10px">
        <button class="sec" id="btn-prev" onclick="detailPage(-1)">← Назад</button>
        <button class="sec" id="btn-next" onclick="detailPage(1)">Вперёд →</button>
      </div>
    </div>
  </div>
</div>

<script>
const LIMIT=25;
let _dt='',_off=0,_total=0;

function showTab(el,id){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('pane-'+id).classList.add('active');
  if(id==='requests')loadRequests();
  if(id==='settings')loadSettings();
}

async function loadHub(){
  try{
    const nodes=await(await fetch('/api/hub')).json();
    const grid=document.getElementById('grid');
    grid.innerHTML='';
    let tr=0,tp=0;
    nodes.forEach(n=>{
      tr+=n.report_count||0;tp+=n.known_peers||0;
      const tgts=n.targets||{};
      const rows=Object.entries(tgts).map(([t,rs])=>{
        const ok=rs.filter(r=>r.status==='OK').length,all=rs.length;
        const cl=ok===all?'ok':'err';
        return `<div class="target-row" onclick="openDetail('${t}')">
          <span><span class="dot ${cl}"></span><span class="dn">${t}</span></span>
          <span class="ratio">${ok}/${all}</span></div>`;
      }).join('');
      const badge=n.reachable?'<span class="badge ok">online</span>':'<span class="badge err">недоступна</span>';
      grid.innerHTML+=`<div class="card">
        <div class="card-head"><span class="card-title">${n.label}</span>${badge}</div>
        <div class="card-sub"><code>${(n.node_id||'').slice(0,14)}…</code>
          &nbsp;·&nbsp;${n.report_count||0} отчётов&nbsp;·&nbsp;${n.known_peers||0} пиров</div>
        ${rows||'<div style="color:var(--dim);font-size:14px;padding:8px 0">нет данных</div>'}
      </div>`;
    });
    document.getElementById('meta').textContent=`узлов: ${nodes.length} · отчётов: ${tr} · пиров: ${tp}`;
    loadHubNodes();
  }catch(e){console.error(e)}
}

async function loadHubNodes(){
  const nodes=await(await fetch('/api/nodes')).json();
  const el=document.getElementById('hub-nodes');
  if(!nodes.length){el.innerHTML='<span style="color:var(--dim);font-size:14px">Нет добавленных нод</span>';return;}
  el.innerHTML='<div style="font-size:13px;color:var(--dim);margin-bottom:8px">В хабе:</div>'
    +nodes.map((n,i)=>`<div class="node-item">
      <div class="node-info"><b>${n.label||n.url}</b><span>${n.url}</span></div>
      <button class="del" onclick="removeNode(${i})">Удалить</button>
    </div>`).join('');
}

async function requestJoin(){
  const url=document.getElementById('nurl').value.trim();
  const label=document.getElementById('nlabel').value.trim()||url;
  if(!url)return;
  const msg=document.getElementById('join-msg');
  msg.style.color='var(--dim)';msg.textContent='Отправляю...';
  const res=await fetch('/api/request-join',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({target_url:url,my_label:label})});
  const d=await res.json();
  if(d.ok){
    msg.style.color='var(--ok)';
    msg.textContent='✓ Запрос отправлен — зайди на ту ноду и подтверди';
    document.getElementById('nurl').value='';
    document.getElementById('nlabel').value='';
  }else{
    msg.style.color='var(--err)';
    msg.textContent='✗ '+(d.error||'Не удалось отправить');
  }
}

async function removeNode(i){
  await fetch('/api/nodes',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:i})});
  loadHub();
}

async function loadRequests(){
  const reqs=await(await fetch('/api/join-requests')).json();
  document.getElementById('tab-req').textContent=reqs.length?`Запросы (${reqs.length})`:'Запросы';
  const el=document.getElementById('req-list');
  if(!reqs.length){el.innerHTML='<span style="color:var(--dim)">Нет запросов</span>';return;}
  el.innerHTML=reqs.map((r,i)=>`<div class="req-item">
    <div class="req-info"><b>${r.label||r.url}</b><span>${r.url}&nbsp;·&nbsp;${r.ts}</span></div>
    <div class="req-btns">
      <button class="ok-btn" onclick="approveJoin(${i})">✓ Подтвердить</button>
      <button class="del" onclick="denyJoin(${i})">✗ Отклонить</button>
    </div>
  </div>`).join('');
}

async function approveJoin(i){
  await fetch('/api/approve-join',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:i})});
  loadRequests();loadHub();
}
async function denyJoin(i){
  await fetch('/api/deny-join',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:i})});
  loadRequests();
}

async function loadSettings(){
  const cfg=await(await fetch('/api/settings')).json();
  document.getElementById('s-probe').value=cfg.probe_interval||30;
  document.getElementById('s-retain').value=cfg.retention_days||45;
  loadTargetList();
}
async function saveSettings(){
  await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      probe_interval:parseInt(document.getElementById('s-probe').value),
      retention_days:parseInt(document.getElementById('s-retain').value)
    })});
  const ok=document.getElementById('s-ok');
  ok.classList.add('show');setTimeout(()=>ok.classList.remove('show'),2000);
}
async function loadTargetList(){
  const d=await(await fetch('/api/targets')).json();
  const el=document.getElementById('target-list');
  el.innerHTML=(d.targets||[]).map((t,i)=>`<div class="target-item">
    <span>${t}</span><button class="del" onclick="removeTarget(${i})">Удалить</button>
  </div>`).join('')||'<span style="color:var(--dim)">Пусто</span>';
}
async function addTarget(){
  const v=document.getElementById('new-target').value.trim();
  if(!v)return;
  await fetch('/api/targets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:v})});
  document.getElementById('new-target').value='';
  loadTargetList();
}
async function removeTarget(i){
  await fetch('/api/targets',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:i})});
  loadTargetList();
}

async function openDetail(target){
  _dt=target;_off=0;
  document.getElementById('modal-title').textContent=target;
  document.getElementById('modal').classList.add('open');
  const nids=await(await fetch(`/api/target-nodes?target=${encodeURIComponent(target)}`)).json();
  const sel=document.getElementById('node-filter');
  sel.innerHTML='<option value="">Все узлы</option>'
    +nids.map(n=>`<option value="${n}">${n.slice(0,16)}…</option>`).join('');
  loadDetail(0);
}
async function loadDetail(dir){
  _off=Math.max(0,_off+dir*LIMIT);
  const node=document.getElementById('node-filter').value;
  const url=`/api/target-detail?target=${encodeURIComponent(_dt)}&limit=${LIMIT}&offset=${_off}`+(node?'&node_id='+node:'');
  const d=await(await fetch(url)).json();
  _total=d.total;
  document.getElementById('modal-stats').innerHTML=
    `<span>Доступность: <b style="color:var(--ok)">${d.ok_pct}%</b></span>
     <span>Средняя задержка: <b>${d.avg_latency_ms!=null?d.avg_latency_ms+'мс':'—'}</b></span>
     <span>Всего записей: <b>${d.total}</b></span>`;
  document.getElementById('modal-bar').innerHTML=d.reports.slice(0,60).map(r=>
    `<div class="hb ${r.status==='OK'?'ok':'err'}" title="${r.timestamp.replace('T',' ')} | ${r.status} | ${r.node_id.slice(0,8)}…"></div>`
  ).join('');
  document.getElementById('modal-rows').innerHTML=d.reports.map(r=>
    `<tr><td>${r.timestamp.replace('T',' ').slice(0,16)}</td>
    <td><code>${r.node_id.slice(0,12)}…</code></td>
    <td class="s-${r.status==='OK'?'ok':'err'}">${r.status}</td>
    <td>${r.latency_ms>0?r.latency_ms+'мс':'—'}</td></tr>`
  ).join('');
  const showing=Math.min(_off+LIMIT,d.total);
  document.getElementById('modal-count').textContent=`${_off+1}–${showing} из ${d.total}`;
  document.getElementById('btn-prev').disabled=_off===0;
  document.getElementById('btn-next').disabled=!d.has_more;
}
function detailPage(dir){loadDetail(dir)}
function closeModal(){document.getElementById('modal').classList.remove('open')}
function maybeClose(e){if(e.target===document.getElementById('modal'))closeModal()}

loadHub();
setInterval(loadHub,15000);
setInterval(async()=>{
  const r=await(await fetch('/api/join-requests')).json();
  document.getElementById('tab-req').textContent=r.length?`Запросы (${r.length})`:'Запросы';
},10000);
</script>
</body>
</html>
"""


def _make_handler():
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_GET(self):
            p = self.path.split("?")[0]
            qs = self.path[len(p)+1:] if "?" in self.path else ""
            params = dict(x.split("=", 1) for x in qs.split("&") if "=" in x)

            if p == "/api/status":
                return self._json(_aggregate_local())
            if p == "/api/hub":
                return self._json(_build_hub_data())
            if p == "/api/nodes":
                return self._json(_load_json(_NODES_FILE, []))
            if p == "/api/join-requests":
                return self._json(_load_json(_JOIN_FILE, []))
            if p == "/api/settings":
                cfg = _read_config()
                return self._json({
                    "probe_interval": int(cfg.get("MESHCANARY_PROBE_INTERVAL", 30)),
                    "retention_days": int(cfg.get("MESHCANARY_RETENTION_DAYS", 45)),
                })
            if p == "/api/targets":
                try:
                    with open(_TARGETS_FILE) as f:
                        return self._json(json.load(f))
                except Exception:
                    return self._json({"targets": []})
            if p == "/api/target-detail":
                target = params.get("target", "")
                limit = int(params.get("limit", LIMIT))
                offset = int(params.get("offset", 0))
                node_id = params.get("node_id") or None
                return self._json(storage.get_target_history(target, limit, offset, node_id))
            if p == "/api/target-nodes":
                return self._json(storage.known_node_ids_for_target(params.get("target", "")))
            self._send(_HTML.encode(), "text/html; charset=utf-8")

        def do_POST(self):
            body = self._body()
            p = self.path

            if p == "/api/nodes":
                with _NODES_LOCK:
                    nodes = _load_json(_NODES_FILE, [])
                    if not any(n["url"] == body.get("url") for n in nodes):
                        nodes.append({"url": body["url"], "label": body.get("label", body["url"])})
                        _save_json(_NODES_FILE, nodes)
                return self._json({"ok": True})

            if p == "/api/request-join":
                target_url = body.get("target_url", "").rstrip("/")
                my_label = body.get("my_label", _NODE_ID[:12] + "…")
                if not target_url:
                    return self._json({"ok": False, "error": "нет target_url"})
                result = _post_remote(target_url, "/api/receive-join-request", {
                    "url": body.get("my_url", ""),
                    "label": my_label,
                    "node_id": _NODE_ID,
                })
                if result and result.get("ok"):
                    return self._json({"ok": True})
                return self._json({"ok": False, "error": "нода недоступна или отклонила"})

            if p == "/api/receive-join-request":
                with _JOIN_LOCK:
                    reqs = _load_json(_JOIN_FILE, [])
                    url = body.get("url", "")
                    if url and not any(r["url"] == url for r in reqs):
                        from datetime import datetime, timezone
                        reqs.append({
                            "url": url,
                            "label": body.get("label", url),
                            "node_id": body.get("node_id", ""),
                            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                        })
                        _save_json(_JOIN_FILE, reqs)
                return self._json({"ok": True})

            if p == "/api/approve-join":
                idx = body.get("index", -1)
                with _JOIN_LOCK:
                    reqs = _load_json(_JOIN_FILE, [])
                    if 0 <= idx < len(reqs):
                        req = reqs.pop(idx)
                        _save_json(_JOIN_FILE, reqs)
                        with _NODES_LOCK:
                            nodes = _load_json(_NODES_FILE, [])
                            if not any(n["url"] == req["url"] for n in nodes):
                                nodes.append({"url": req["url"], "label": req.get("label", req["url"])})
                                _save_json(_NODES_FILE, nodes)
                        _post_remote(req["url"], "/api/join-confirmed", {
                            "url": body.get("my_url", ""),
                            "label": _NODE_ID[:12] + "…",
                        })
                        return self._json({"ok": True})
                return self._json({"ok": False})

            if p == "/api/deny-join":
                idx = body.get("index", -1)
                with _JOIN_LOCK:
                    reqs = _load_json(_JOIN_FILE, [])
                    if 0 <= idx < len(reqs):
                        reqs.pop(idx)
                        _save_json(_JOIN_FILE, reqs)
                return self._json({"ok": True})

            if p == "/api/join-confirmed":
                url = body.get("url", "")
                if url:
                    with _NODES_LOCK:
                        nodes = _load_json(_NODES_FILE, [])
                        if not any(n["url"] == url for n in nodes):
                            nodes.append({"url": url, "label": body.get("label", url)})
                            _save_json(_NODES_FILE, nodes)
                return self._json({"ok": True})

            if p == "/api/settings":
                updates = {}
                if "probe_interval" in body:
                    updates["MESHCANARY_PROBE_INTERVAL"] = str(int(body["probe_interval"]))
                if "retention_days" in body:
                    updates["MESHCANARY_RETENTION_DAYS"] = str(int(body["retention_days"]))
                if updates and _CONFIG_FILE:
                    _write_config(updates)
                return self._json({"ok": True})

            if p == "/api/targets":
                try:
                    with open(_TARGETS_FILE) as f:
                        data = json.load(f)
                    t = body.get("target", "").strip()
                    if t and t not in data["targets"]:
                        data["targets"].append(t)
                        with open(_TARGETS_FILE, "w") as f:
                            json.dump(data, f, indent=2)
                except Exception:
                    pass
                return self._json({"ok": True})

            self._json({"ok": False})

        def do_DELETE(self):
            body = self._body()
            p = self.path

            if p == "/api/nodes":
                with _NODES_LOCK:
                    nodes = _load_json(_NODES_FILE, [])
                    idx = body.get("index", -1)
                    if 0 <= idx < len(nodes):
                        nodes.pop(idx)
                        _save_json(_NODES_FILE, nodes)
                return self._json({"ok": True})

            if p == "/api/targets":
                try:
                    with open(_TARGETS_FILE) as f:
                        data = json.load(f)
                    idx = body.get("index", -1)
                    if 0 <= idx < len(data["targets"]):
                        removed = data["targets"].pop(idx)
                        with open(_TARGETS_FILE, "w") as f:
                            json.dump(data, f, indent=2)
                        # удаляем из БД отчёты этой цели
                        storage.prune_removed_targets(data["targets"])
                except Exception:
                    pass
                return self._json({"ok": True})

            self._json({"ok": False})

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n)) if n else {}

        def _json(self, obj):
            self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json")

        def _send(self, body: bytes, ct: str):
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return H


def start(port: int, host: str, node_id: str, nodes_file: str,
          join_file: str = "", config_file: str = "", targets_file: str = ""):
    global _NODE_ID, _NODES_FILE, _JOIN_FILE, _CONFIG_FILE, _TARGETS_FILE
    _NODE_ID = node_id
    _NODES_FILE = nodes_file
    _JOIN_FILE = join_file
    _CONFIG_FILE = config_file
    _TARGETS_FILE = targets_file
    server = ThreadingHTTPServer((host, port), _make_handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
