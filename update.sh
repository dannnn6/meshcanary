
#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Проверка репозитория
if [ ! -d .git ]; then
    echo "Ошибка: отсутствует Git-репозиторий" >&2
    exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "Ошибка: есть незакоммиченные изменения" >&2
    git status --short
    exit 1
fi

BRANCH="$(git symbolic-ref --quiet --short HEAD)" || {
    echo "Ошибка: HEAD не привязан к ветке" >&2
    exit 1
}

git remote get-url origin >/dev/null

OLD_REV="$(git rev-parse HEAD)"
echo "Ветка: $BRANCH"
echo "Получаю обновления..."
git fetch origin "$BRANCH"
NEW_REV="$(git rev-parse FETCH_HEAD)"

if [ "$OLD_REV" = "$NEW_REV" ]; then
    echo "Уже установлена последняя версия"
    exit 0
fi

if ! git merge-base --is-ancestor "$OLD_REV" "$NEW_REV"; then
    echo "Ошибка: обновление не является fast-forward" >&2
    exit 1
fi

if [ ! -x "$DIR/.venv/bin/python3" ]; then
    echo "Ошибка: .venv отсутствует. Сначала выполните install.sh" >&2
    exit 1
fi

if ! git cat-file -e "$NEW_REV:requirements.txt" 2>/dev/null; then
    echo "Ошибка: в новой версии отсутствует requirements.txt" >&2
    exit 1
fi

SERVICE_ACTIVE=false
if command -v systemctl >/dev/null 2>&1 &&
   systemctl is-active --quiet meshcanary; then
    SERVICE_ACTIVE=true
    sudo -v
fi

echo "Обновление: ${OLD_REV:0:8} -> ${NEW_REV:0:8}"
git --no-pager diff --stat "$OLD_REV" "$NEW_REV"

read -r -p "Установить? [y/N] " ANSWER
case "$ANSWER" in
    y|Y|yes|YES) ;;
    *) echo "Отменено"; exit 0 ;;
esac

git merge --ff-only "$NEW_REV"

# Python-зависимости
if ! "$DIR/.venv/bin/python3" -m pip install \
    -r "$DIR/requirements.txt"; then
    echo "Ошибка обновления зависимостей" >&2
    exit 1
fi

# Перезапуск работающей ноды
if [ "$SERVICE_ACTIVE" = true ]; then
    sudo systemctl restart meshcanary
    sleep 2

    if ! systemctl is-active --quiet meshcanary; then
        echo "Ошибка запуска сервиса" >&2
        sudo systemctl status meshcanary --no-pager -l || true
        exit 1
    fi

    echo "Сервис перезапущен"
else
    echo "Сервис не был запущен, перезапуск пропущен"
fi

echo "Обновлено до $(git rev-parse --short HEAD)"
