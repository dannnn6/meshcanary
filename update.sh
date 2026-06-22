#!/usr/bin/env bash
# Mesh Canary self-updater.
#
# Fetches the latest commits from the git remote, shows exactly what would
# change (version, commit log, full diff), and applies the update only
# after you confirm. Never overwrites uncommitted local changes — it will
# refuse and tell you to stash them first.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d .git ]; then
  echo "Ошибка: это не git-копия Mesh Canary." >&2
  echo "Обновлятор работает только если проект склонирован через 'git clone'." >&2
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
git --no-pager diff HEAD "origin/$BRANCH" -- node.py common/ install.sh VERSION
echo

if [ -n "$(git status --porcelain)" ]; then
  echo "Внимание: у тебя есть несохранённые локальные изменения в репозитории." >&2
  echo "Обновление через fast-forward может с ними конфликтовать." >&2
  echo "Сохрани их (git stash) и запусти update.sh снова." >&2
  exit 1
fi

read -r -p "Применить обновление? [y/N] " ANSWER
case "$ANSWER" in
  [yY]|[yY][eE][sS])
    git merge --ff-only "origin/$BRANCH"
    echo "==> Обновлено: $CURRENT_VERSION -> $NEW_VERSION"
    echo "==> Если менялись node.py / common/ — на всякий случай пересоздай venv: ./install.sh"
    ;;
  *)
    echo "==> Отменено, ничего не изменилось."
    ;;
esac
