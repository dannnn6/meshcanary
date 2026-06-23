#!/usr/bin/env bash
# Mesh Canary — утилита настройки.
# Запускай: bash config.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$DIR/data/config.env"
TARGETS="$DIR/targets.json"

# ── загрузка текущего конфига ──────────────────────────────────────────────
load_config() {
  MESHCANARY_PORT="${MESHCANARY_PORT:-9001}"
  MESHCANARY_WEB_PORT="${MESHCANARY_WEB_PORT:-8080}"
  MESHCANARY_WEB_HOST="${MESHCANARY_WEB_HOST:-127.0.0.1}"
  MESHCANARY_ADVERTISE_HOST="${MESHCANARY_ADVERTISE_HOST:-}"
  MESHCANARY_MODE="${MESHCANARY_MODE:-full}"
  MESHCANARY_PROBE_INTERVAL="${MESHCANARY_PROBE_INTERVAL:-30}"
  MESHCANARY_GOSSIP_INTERVAL="${MESHCANARY_GOSSIP_INTERVAL:-15}"
  MESHCANARY_RETENTION_DAYS="${MESHCANARY_RETENTION_DAYS:-45}"
  [ -f "$CONFIG" ] && source "$CONFIG"
}

save_config() {
  mkdir -p "$DIR/data"
  cat > "$CONFIG" << ENV
MESHCANARY_PORT=$MESHCANARY_PORT
MESHCANARY_WEB_PORT=$MESHCANARY_WEB_PORT
MESHCANARY_WEB_HOST=$MESHCANARY_WEB_HOST
MESHCANARY_ADVERTISE_HOST=$MESHCANARY_ADVERTISE_HOST
MESHCANARY_MODE=$MESHCANARY_MODE
MESHCANARY_PROBE_INTERVAL=$MESHCANARY_PROBE_INTERVAL
MESHCANARY_GOSSIP_INTERVAL=$MESHCANARY_GOSSIP_INTERVAL
MESHCANARY_RETENTION_DAYS=$MESHCANARY_RETENTION_DAYS
ENV
  echo "  ✓ Сохранено в $CONFIG"
}

# ── определение локальных IP ───────────────────────────────────────────────
detect_local_ips() {
  python3 -c "
import socket
ips = set()
try:
    for iface_info in socket.getaddrinfo(socket.gethostname(), None):
        ip = iface_info[4][0]
        if ':' not in ip and not ip.startswith('127.'):
            ips.add(ip)
except: pass
# fallback via UDP trick
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80)); ips.add(s.getsockname()[0]); s.close()
except: pass
print('\n'.join(sorted(ips)))
" 2>/dev/null
}

# ── редактирование targets.json ────────────────────────────────────────────
edit_targets() {
  echo
  echo "=== Список проверяемых сайтов ==="
  if [ ! -f "$TARGETS" ]; then echo "  (файл не найден)"; return; fi

  mapfile -t CURRENT < <(python3 -c "
import json
with open('$TARGETS') as f:
    for t in json.load(f)['targets']: print(t)
")

  echo "  Текущие цели:"
  for i in "${!CURRENT[@]}"; do
    echo "    [$((i+1))] ${CURRENT[$i]}"
  done
  echo
  echo "  [a] Добавить сайт"
  echo "    [d] Удалить сайт по номеру"
  echo "    [q] Назад"
  read -r -p "  → " ACT
  case "$ACT" in
    a)
      read -r -p "  Домен (например: wikipedia.org): " NEW_TARGET
      if [ -n "$NEW_TARGET" ]; then
        python3 -c "
import json
with open('$TARGETS') as f: data = json.load(f)
if '$NEW_TARGET' not in data['targets']:
    data['targets'].append('$NEW_TARGET')
with open('$TARGETS','w') as f: json.dump(data, f, indent=2)
print('  ✓ Добавлен: $NEW_TARGET')
"
      fi ;;
    d)
      read -r -p "  Номер для удаления: " NUM
      python3 -c "
import json
with open('$TARGETS') as f: data = json.load(f)
idx = int('$NUM') - 1
if 0 <= idx < len(data['targets']):
    removed = data['targets'].pop(idx)
    with open('$TARGETS','w') as f: json.dump(data, f, indent=2)
    print(f'  ✓ Удалён: {removed}')
else:
    print('  Номер вне диапазона')
" ;;
    *) return ;;
  esac
}

# ── главное меню ───────────────────────────────────────────────────────────
show_menu() {
  echo
  echo "╔══════════════════════════════════════════╗"
  echo "║      Mesh Canary — настройки             ║"
  echo "╠══════════════════════════════════════════╣"
  printf "║  [1] Порт gossip-сервера     %-12s║\n" "$MESHCANARY_PORT"
  printf "║  [2] Порт дашборда           %-12s║\n" "$MESHCANARY_WEB_PORT"
  printf "║  [3] Хост дашборда           %-12s║\n" "$MESHCANARY_WEB_HOST"
  printf "║  [4] Публичный адрес (advertise) %-7s║\n" "${MESHCANARY_ADVERTISE_HOST:-не задан}"
  printf "║  [5] Режим ноды              %-12s║\n" "$MESHCANARY_MODE"
  printf "║  [6] Интервал проверок       %-10s║\n" "${MESHCANARY_PROBE_INTERVAL}с"
  printf "║  [7] Интервал gossip         %-10s║\n" "${MESHCANARY_GOSSIP_INTERVAL}с"
  printf "║  [8] Хранить отчёты (дни)    %-12s║\n" "$MESHCANARY_RETENTION_DAYS"
  echo "║  [9] Редактировать сайты для проверки    ║"
  echo "║  [s] Сохранить и выйти                   ║"
  echo "║  [q] Выйти без сохранения                ║"
  echo "╚══════════════════════════════════════════╝"
  echo -n "  → "
}

prompt_web_host() {
  echo
  echo "  Где должен быть доступен дашборд?"
  echo "  [1] Только локально (127.0.0.1) — рекомендуется"
  echo "  [2] В локальной сети (выбрать IP)"
  echo "  [3] Везде (0.0.0.0) — небезопасно без firewall"
  echo "  [4] Ввести вручную"
  read -r -p "  → " CHOICE
  case "$CHOICE" in
    1) MESHCANARY_WEB_HOST="127.0.0.1" ;;
    2)
      DETECTED="$(detect_local_ips)"
      if [ -z "$DETECTED" ]; then
        echo "  Локальные IP не определены, введи вручную:"
        read -r -p "  IP: " MESHCANARY_WEB_HOST
      else
        echo "  Обнаруженные IP:"
        mapfile -t IPS <<< "$DETECTED"
        for i in "${!IPS[@]}"; do echo "    [$((i+1))] ${IPS[$i]}"; done
        read -r -p "  Выбери номер: " N
        MESHCANARY_WEB_HOST="${IPS[$((N-1))]:-127.0.0.1}"
      fi ;;
    3) MESHCANARY_WEB_HOST="0.0.0.0" ;;
    4) read -r -p "  IP: " MESHCANARY_WEB_HOST ;;
  esac
  echo "  ✓ Хост дашборда: $MESHCANARY_WEB_HOST"
}

prompt_mode() {
  echo
  echo "  Режим работы ноды:"
  echo "  [1] full     — полный (есть публичный IP, принимает входящие gossip)"
  echo "  [2] outbound — серый IP/NAT (только исходящие соединения, не станет bootstrap-пиром)"
  read -r -p "  → " CHOICE
  case "$CHOICE" in
    1) MESHCANARY_MODE="full" ;;
    2) MESHCANARY_MODE="outbound"
       echo "  ℹ️  В режиме outbound нода всё равно отправляет отчёты в сеть через"
       echo "     исходящие подключения. Отчёты распространяются нормально."
       ;;
  esac
}

# ── основной цикл ──────────────────────────────────────────────────────────
load_config
while true; do
  show_menu
  read -r OPT
  case "$OPT" in
    1) read -r -p "  Порт gossip [${MESHCANARY_PORT}]: " V; MESHCANARY_PORT="${V:-$MESHCANARY_PORT}" ;;
    2) read -r -p "  Порт дашборда [${MESHCANARY_WEB_PORT}]: " V; MESHCANARY_WEB_PORT="${V:-$MESHCANARY_WEB_PORT}" ;;
    3) prompt_web_host ;;
    4) read -r -p "  Публичный адрес (IP или домен, пусто = не задан): " V; MESHCANARY_ADVERTISE_HOST="$V" ;;
    5) prompt_mode ;;
    6) read -r -p "  Интервал проверок сек [${MESHCANARY_PROBE_INTERVAL}]: " V; MESHCANARY_PROBE_INTERVAL="${V:-$MESHCANARY_PROBE_INTERVAL}" ;;
    7) read -r -p "  Интервал gossip сек [${MESHCANARY_GOSSIP_INTERVAL}]: " V; MESHCANARY_GOSSIP_INTERVAL="${V:-$MESHCANARY_GOSSIP_INTERVAL}" ;;
    8) read -r -p "  Дней хранения [${MESHCANARY_RETENTION_DAYS}]: " V; MESHCANARY_RETENTION_DAYS="${V:-$MESHCANARY_RETENTION_DAYS}" ;;
    9) edit_targets ;;
    s|S)
      save_config
      if [ -d /run/systemd/system ] && systemctl is-active --quiet meshcanary 2>/dev/null; then
        read -r -p "  Перезапустить ноду для применения? [Y/n] " R
        case "$R" in [nN]*) ;; *) sudo systemctl restart meshcanary && echo "  ✓ Нода перезапущена" ;; esac
      fi
      exit 0 ;;
    q|Q) echo "  Выход без сохранения."; exit 0 ;;
    *) echo "  Неверный выбор." ;;
  esac
done
