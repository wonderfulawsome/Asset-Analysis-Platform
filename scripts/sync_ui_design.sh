#!/usr/bin/env bash
# 본폴더(Passive-Financial-Data-Analysis) → "/root/UI 디자인" 단방향 프론트 미러링.
# Stop hook(.claude/settings.json) 또는 수동 실행으로 호출됨.
set -euo pipefail

SRC="/root/Passive-Financial-Data-Analysis"
DST="/root/UI 디자인"

if [ ! -d "$DST" ]; then
  mkdir -p "$DST"
fi

rsync -a --delete \
  --exclude='node_modules' \
  --exclude='dist' \
  --exclude='.next' \
  --exclude='.vite' \
  "$SRC/static" \
  "$SRC/templates" \
  "$SRC/frontend-realestate" \
  "$DST/" >/dev/null 2>&1 || true

exit 0
