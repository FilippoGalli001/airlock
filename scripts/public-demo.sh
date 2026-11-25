#!/bin/bash
# Public read-only demo on/off for airlock-ctrl.
#   on : anyone with the URL can look at the queue and timelines; every action still needs the password
#   off: back to Fly login + password
# Usage: bash scripts/public-demo.sh on|off
set -euo pipefail
cd "$(dirname "$0")/.."
SPRITE="${SPRITE_BIN:-sprite}"
command -v "$SPRITE" >/dev/null 2>&1 || SPRITE="$LOCALAPPDATA/Programs/Sprite/sprite.exe"
CTRL="${CTRL:-airlock-ctrl}"
mode="${1:?on|off}"
[ -f .env.ctrl ] || { echo "no .env.ctrl: deploy first"; exit 1; }
grep -v '^AIRLOCK_PUBLIC_READONLY=' .env.ctrl > .env.ctrl.tmp || true
case "$mode" in
  on)  echo "AIRLOCK_PUBLIC_READONLY=1" >> .env.ctrl.tmp; auth=public ;;
  off) auth=sprite ;;
  *)   echo "usage: $0 on|off"; rm -f .env.ctrl.tmp; exit 1 ;;
esac
mv .env.ctrl.tmp .env.ctrl
bash scripts/deploy-ctrl.sh
"$SPRITE" config update -s "$CTRL" --url-auth "$auth" >/dev/null
"$SPRITE" info -s "$CTRL" | grep -E '^(URL|Auth)'
