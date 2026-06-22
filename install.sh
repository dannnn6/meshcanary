#!/usr/bin/env bash
# Mesh Canary installer.
# Ставит зависимости, создаёт конфиги и регистрирует systemd-сервис
# (если systemd доступен и запущен с sudo).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
SERVICE_NAME="meshcanary"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# Определяем, от чьего имени запущено (sudo сохраняет SUDO_USER)
if [ "${EUID:-$(id -u)}" -eq 0 ]; then
  RUN_USER="${SUDO_USER:-root}"
else
  RUN_USER="$(whoami)"
fi

echo "==> Mesh Canary installer"

# ---------- Python ----------
if ! command -v python3 &>/dev/null; then
  echo "Ошибка: python3 не найден. Установи Python 3.9+ и повтори." >&2
  exit 1
fi
PYVER="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
echo "==> Python $PYVER найден"

echo "==> Создаю виртуальное окружение (.venv)"
python3 -m venv "$VENV_DIR"

echo "==> Устанавливаю зависимости"
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install cryptography --quiet

# ---------- конфиги ----------
mkdir -p "$PROJECT_DIR/data"

if [ ! -f "$PROJECT_DIR/peers.json" ]; then
  cp "$PROJECT_DIR/peers.json.example" "$PROJECT_DIR/peers.json"
  echo "==> Создан peers.json из шаблона"
fi

if [ ! -f "$PROJECT_DIR/targets.json" ]; then
  cp "$PROJECT_DIR/targets.json.example" "$PROJECT_DIR/targets.json"
  echo "==> Создан targets.json из шаблона"
fi

# ---------- run-node.sh ----------
cat > "$PROJECT_DIR/run-node.sh" << 'RUNNER'
#!/usr/bin/env bash
# Сгенерирован install.sh. Переменные окружения для настройки:
#   MESHCANARY_PORT           порт gossip-сервера   (по умолчанию 9001)
#   MESHCANARY_WEB_PORT       порт веб-дашборда     (по умолчанию 8080)
#   MESHCANARY_ADVERTISE_HOST публичный IP/домен    (необязательно)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ARGS=(
  --port   "${MESHCANARY_PORT:-9001}"
  --id-file "$DIR/data/node.key"
  --db      "$DIR/data/node.db"
  --targets "$DIR/targets.json"
  --peers   "$DIR/peers.json"
  --web-port "${MESHCANARY_WEB_PORT:-8080}"
)

[ -n "${MESHCANARY_ADVERTISE_HOST:-}" ] && ARGS+=(--advertise-host "$MESHCANARY_ADVERTISE_HOST")

exec "$DIR/.venv/bin/python3" "$DIR/node.py" "${ARGS[@]}" "$@"
RUNNER
chmod +x "$PROJECT_DIR/run-node.sh"

# ---------- systemd ----------
if command -v systemctl &>/dev/null && systemctl is-system-running --quiet 2>/dev/null || \
   [ -d /run/systemd/system ]; then

  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo
    echo "==> Для регистрации systemd-сервиса нужны права sudo."
    echo "    Перезапусти установщик: sudo ./install.sh"
    echo "    Или запусти вручную: ./run-node.sh"
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
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PROJECT_DIR}/run-node.sh
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME" --quiet
    systemctl restart "$SERVICE_NAME"

    sleep 2
    echo "==> Статус:"
    systemctl status "$SERVICE_NAME" --no-pager -l

    echo
    echo "==> Нода запущена в фоне и будет стартовать при перезагрузке."
    echo "    Логи:              journalctl -u $SERVICE_NAME -f"
    echo "    Перезапуск:        sudo systemctl restart $SERVICE_NAME"
    echo "    Остановить:        sudo systemctl stop $SERVICE_NAME"
  fi
else
  echo "==> systemd не обнаружен — запускай вручную: ./run-node.sh"
fi

echo
echo "==> Готово."
echo "    Впиши bootstrap-пиров в peers.json, если ещё не сделал."
echo "    Дашборд: http://localhost:8080"
