#!/usr/bin/env bash
# Mesh Canary — установщик. Запускай: sudo bash install.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"
CONFIG="$DIR/data/config.env"
SERVICE="meshcanary"
SERVICE_FILE="/etc/systemd/system/${SERVICE}.service"

chmod +x "$DIR/install.sh" "$DIR/update.sh" "$DIR/config.sh" 2>/dev/null || true

IS_ROOT=$([ "${EUID:-$(id -u)}" -eq 0 ] && echo true || echo false)
RUN_USER=$( $IS_ROOT && echo "${SUDO_USER:-root}" || whoami )

# ─── Python ───────────────────────────────────────────────────────────────
echo "==> Mesh Canary installer"
command -v python3 &>/dev/null || { echo "Ошибка: python3 не найден."; exit 1; }
PYVER=$(python3 -c 'import sys; print(".".join(map(str,sys.version_info[:2])))')
echo "==> Python $PYVER"

if ! python3 -m venv --help &>/dev/null 2>&1; then
  echo "==> Устанавливаю python3-venv..."
  $IS_ROOT || { echo "Нужен sudo: sudo bash install.sh"; exit 1; }
  VENV_PKG="python${PYVER}-venv"
  apt-get install -y "$VENV_PKG" 2>/dev/null || apt-get install -y python3-venv
fi

echo "==> Создаю .venv"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install cryptography --quiet

# ─── данные ───────────────────────────────────────────────────────────────
mkdir -p "$DIR/data"
$IS_ROOT && chown -R "$RUN_USER" "$DIR/data" 2>/dev/null || true

[ -f "$DIR/peers.json" ]   || cp "$DIR/peers.json.example"   "$DIR/peers.json"
[ -f "$DIR/targets.json" ] || cp "$DIR/targets.json.example" "$DIR/targets.json"
# Все пользовательские файлы должны принадлежать RUN_USER, а не root
$IS_ROOT && chown "$RUN_USER" "$DIR/peers.json" "$DIR/targets.json" 2>/dev/null || true

# ─── конфиг ───────────────────────────────────────────────────────────────
# Значения по умолчанию
MC_PORT=9001
MC_WEB_PORT=8080
MC_WEB_HOST=127.0.0.1
MC_ADVERTISE=""
MC_MODE=full
MC_PROBE=30
MC_GOSSIP=15
MC_RETAIN=45

# Подгружаем существующий конфиг (переустановка не сбросит настройки)
if [ -f "$CONFIG" ]; then
  source "$CONFIG"
  MC_PORT="${MESHCANARY_PORT:-$MC_PORT}"
  MC_WEB_PORT="${MESHCANARY_WEB_PORT:-$MC_WEB_PORT}"
  MC_WEB_HOST="${MESHCANARY_WEB_HOST:-$MC_WEB_HOST}"
  MC_ADVERTISE="${MESHCANARY_ADVERTISE_HOST:-}"
  MC_MODE="${MESHCANARY_MODE:-$MC_MODE}"
  MC_PROBE="${MESHCANARY_PROBE_INTERVAL:-$MC_PROBE}"
  MC_GOSSIP="${MESHCANARY_GOSSIP_INTERVAL:-$MC_GOSSIP}"
  MC_RETAIN="${MESHCANARY_RETENTION_DAYS:-$MC_RETAIN}"
  echo "==> Существующий конфиг найден, настройки сохранены"
else
  echo
  echo "==> Первичная настройка (Enter = оставить значение по умолчанию)"
  echo

  # Порт gossip
  read -r -p "   Порт gossip-сервера [$MC_PORT]: " V; MC_PORT="${V:-$MC_PORT}"

  # Режим ноды
  echo "   Режим ноды:"
  echo "     [1] full     — есть публичный IP (полноценная нода)"
  echo "     [2] outbound — серый IP / за NAT (только исходящие соединения)"
  read -r -p "   → [1]: " V
  [ "${V:-1}" = "2" ] && MC_MODE="outbound" || MC_MODE="full"

  if [ "$MC_MODE" = "full" ]; then
    read -r -p "   Публичный адрес для peer exchange (IP или домен, Enter = пропустить): " MC_ADVERTISE
  fi

  # Хост дашборда
  echo "   Дашборд доступен:"
  echo "     [1] Только локально — 127.0.0.1 (рекомендуется)"
  echo "     [2] В локальной сети (определить автоматически)"
  echo "     [3] Везде — 0.0.0.0"
  read -r -p "   → [1]: " WH_CHOICE
  case "${WH_CHOICE:-1}" in
    2)
      DETECTED=$(python3 -c "
import socket
ips=set()
try:
  for i in socket.getaddrinfo(socket.gethostname(),None):
    ip=i[4][0]
    if ':' not in ip and not ip.startswith('127.'): ips.add(ip)
except: pass
try:
  s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
  s.connect(('8.8.8.8',80)); ips.add(s.getsockname()[0]); s.close()
except: pass
print('\n'.join(sorted(ips)))" 2>/dev/null)
      if [ -z "$DETECTED" ]; then
        read -r -p "   Не удалось определить. Введи IP вручную: " MC_WEB_HOST
      else
        echo "   Обнаруженные локальные IP:"
        mapfile -t IPS <<< "$DETECTED"
        for i in "${!IPS[@]}"; do echo "     [$((i+1))] ${IPS[$i]}"; done
        read -r -p "   Выбери номер [1]: " N
        MC_WEB_HOST="${IPS[$(( ${N:-1} - 1 ))]:-127.0.0.1}"
      fi ;;
    3) MC_WEB_HOST="0.0.0.0" ;;
    *) MC_WEB_HOST="127.0.0.1" ;;
  esac

  read -r -p "   Порт дашборда [$MC_WEB_PORT]: " V; MC_WEB_PORT="${V:-$MC_WEB_PORT}"
fi

# Пишем config.env
cat > "$CONFIG" << ENV
MESHCANARY_PORT=$MC_PORT
MESHCANARY_WEB_PORT=$MC_WEB_PORT
MESHCANARY_WEB_HOST=$MC_WEB_HOST
MESHCANARY_ADVERTISE_HOST=$MC_ADVERTISE
MESHCANARY_MODE=$MC_MODE
MESHCANARY_PROBE_INTERVAL=$MC_PROBE
MESHCANARY_GOSSIP_INTERVAL=$MC_GOSSIP
MESHCANARY_RETENTION_DAYS=$MC_RETAIN
ENV
$IS_ROOT && chown "$RUN_USER" "$CONFIG" 2>/dev/null || true
echo "==> Конфиг записан: $CONFIG"

# ─── run-node.sh ──────────────────────────────────────────────────────────
cat > "$DIR/run-node.sh" << 'RUNNER'
#!/usr/bin/env bash
set -euo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$D/data/config.env" ] && source "$D/data/config.env"

ARGS=(
  --port    "${MESHCANARY_PORT:-9001}"
  --id-file "$D/data/node.key"
  --db      "$D/data/node.db"
  --targets "$D/targets.json"
  --peers   "$D/peers.json"
  --web-host  "${MESHCANARY_WEB_HOST:-127.0.0.1}"
  --web-port  "${MESHCANARY_WEB_PORT:-8080}"
  --probe-interval  "${MESHCANARY_PROBE_INTERVAL:-30}"
  --gossip-interval "${MESHCANARY_GOSSIP_INTERVAL:-15}"
  --retention-days  "${MESHCANARY_RETENTION_DAYS:-45}"
)
[ "${MESHCANARY_MODE:-full}" = "outbound" ] && ARGS+=(--grey-ip)
[ -n "${MESHCANARY_ADVERTISE_HOST:-}" ]     && ARGS+=(--advertise-host "$MESHCANARY_ADVERTISE_HOST")

exec "$D/.venv/bin/python3" "$D/node.py" "${ARGS[@]}" "$@"
RUNNER
chmod +x "$DIR/run-node.sh"

# ─── systemd ──────────────────────────────────────────────────────────────
if [ -d /run/systemd/system ]; then
  if ! $IS_ROOT; then
    echo; echo "==> Для systemd-сервиса нужен sudo: sudo bash install.sh"
  else
    echo "==> Регистрирую systemd-сервис (пользователь: $RUN_USER)"
    cat > "$SERVICE_FILE" << UNIT
[Unit]
Description=Mesh Canary Node
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${DIR}
ExecStart=${DIR}/run-node.sh
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable "$SERVICE" --quiet
    systemctl restart "$SERVICE"
    sleep 2
    systemctl status "$SERVICE" --no-pager -l
    echo
    echo "==> Нода запущена в фоне."
    echo "    Логи:        journalctl -u $SERVICE -f"
    echo "    Настройки:   bash config.sh"
    echo "    Обновление:  bash update.sh"
  fi
else
  echo "==> systemd не найден. Запускай: ./run-node.sh"
fi

echo
echo "==> Дашборд: http://${MC_WEB_HOST}:${MC_WEB_PORT}"
echo "==> Готово."
