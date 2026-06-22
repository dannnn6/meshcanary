#!/usr/bin/env bash
# Mesh Canary — обновление.
# Запускай как: bash update.sh  (chmod не нужен)
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Выставляем права исполнения на себя и install.sh
chmod +x "$DIR/update.sh" "$DIR/install.sh" 2>/dev/null || true

if [ ! -d .git ]; then
  echo "Ошибка: это не git-копия Mesh Canary." >&2
  echo "Обновление работает только если проект установлен через git clone." >&2
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
CURRENT_VERSION="$(cat VERSION 2>/dev/null || echo "unknown")"

echo "==> Текущая версия: $CURRENT_VERSION (ветка $BRANCH)"
echo "==> Проверяю обновления..."
git fetch origin "$BRANCH" --quiet

LOCAL_REV="$(git rev-parse HEAD)"
REMOTE_REV="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL_REV" = "$REMOTE_REV" ]; then
  echo "==> У вас уже последняя версия. Обновлений нет."
  exit 0
fi

NEW_VERSION="$(git show "origin/$BRANCH:VERSION" 2>/dev/null || echo "unknown")"
COMMITS_BEHIND="$(git rev-list --count "HEAD..origin/$BRANCH")"

echo
echo "==> Доступно обновление: $CURRENT_VERSION -> $NEW_VERSION  ($COMMITS_BEHIND новых коммитов)"
echo
echo "----- что изменится (коммиты) -----"
git log --oneline --no-decorate "HEAD..origin/$BRANCH"
echo
echo "----- что изменится (diff) -----"
git --no-pager diff --stat HEAD "origin/$BRANCH"
echo
git --no-pager diff HEAD "origin/$BRANCH" -- node.py common/ install.sh update.sh VERSION
echo

if [ -n "$(git status --porcelain)" ]; then
  echo "Внимание: есть несохранённые локальные изменения." >&2
  echo "Сохрани их (git stash) и запусти update.sh снова." >&2
  exit 1
fi

read -r -p "Применить обновление? [y/N] " ANSWER
case "$ANSWER" in
  [yY]|[yY][eE][sS])
    git merge --ff-only "origin/$BRANCH"
    # Восстанавливаем права после merge
    chmod +x "$DIR/install.sh" "$DIR/update.sh" 2>/dev/null || true
    echo "==> Обновлено: $CURRENT_VERSION -> $NEW_VERSION"
    echo
    echo "==> Применяю обновление (перезапуск ноды)..."
    if [ -d /run/systemd/system ] && systemctl is-active --quiet meshcanary 2>/dev/null; then
      sudo systemctl restart meshcanary
      echo "==> Нода перезапущена через systemd."
    else
      echo "==> Перезапусти ноду вручную: sudo bash install.sh"
    fi
    ;;
  *)
    echo "==> Отменено, ничего не изменилось."
    ;;
esac
