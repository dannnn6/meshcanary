#!/usr/bin/env bash
# Mesh Canary — обновление. Запускай: bash update.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
chmod +x "$DIR/update.sh" "$DIR/install.sh" "$DIR/config.sh" 2>/dev/null || true

if [ ! -d .git ]; then
  echo "Ошибка: проект не установлен через git clone." >&2; exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
CURRENT_VERSION="$(cat VERSION 2>/dev/null || echo "unknown")"

echo "==> Текущая версия: $CURRENT_VERSION (ветка $BRANCH)"
echo "==> Проверяю обновления..."
git fetch origin "$BRANCH" --quiet

LOCAL_REV="$(git rev-parse HEAD)"
REMOTE_REV="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL_REV" = "$REMOTE_REV" ]; then
  echo "==> Уже последняя версия."; exit 0
fi

NEW_VERSION="$(git show "origin/$BRANCH:VERSION" 2>/dev/null || echo "unknown")"
COMMITS="$(git rev-list --count "HEAD..origin/$BRANCH")"

echo
echo "==> Доступно: $CURRENT_VERSION → $NEW_VERSION  ($COMMITS новых коммитов)"
echo
echo "--- коммиты ---"
git log --oneline --no-decorate "HEAD..origin/$BRANCH"
echo
echo "--- изменённые файлы ---"
git --no-pager diff --stat HEAD "origin/$BRANCH"
echo

read -r -p "Применить обновление? [y/N] " ANS
case "$ANS" in [yY]*)
  # Сбрасываем изменения в tracked-файлах — пользовательские данные
  # хранятся в data/ и *.json (они в .gitignore), поэтому ничего важного не теряется
  git checkout -- . 2>/dev/null || true
  git merge --ff-only "origin/$BRANCH"
  chmod +x "$DIR/install.sh" "$DIR/update.sh" "$DIR/config.sh" 2>/dev/null || true

  echo "==> Обновлено: $CURRENT_VERSION → $NEW_VERSION"
  if [ -d /run/systemd/system ] && systemctl is-active --quiet meshcanary 2>/dev/null; then
    sudo systemctl restart meshcanary && echo "==> Нода перезапущена."
  else
    echo "==> Перезапусти ноду: sudo systemctl restart meshcanary"
  fi ;;
*) echo "==> Отменено." ;;
esac
