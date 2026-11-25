#!/bin/bash
# Pushes the ctrl code and its env file to the airlock-ctrl Sprite (~/airlock).
set -euo pipefail
cd "$(dirname "$0")/.."
SPRITE="${SPRITE_BIN:-sprite}"
command -v "$SPRITE" >/dev/null 2>&1 || SPRITE="$LOCALAPPDATA/Programs/Sprite/sprite.exe"
CTRL="${CTRL:-airlock-ctrl}"
[ -f .env.chamber ] || { echo "run scripts/build-chamber-baseline.sh first"; exit 1; }
if [ ! -f .env.ctrl ]; then
  echo "AIRLOCK_PASSWORD=$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')" > .env.ctrl
fi

tmp=$(mktemp -d)
mkdir -p "$tmp/airlock"
cp -r ctrl samples "$tmp/airlock/"
cat .env.chamber .env.ctrl > "$tmp/airlock/airlock.env"
find "$tmp" -name __pycache__ -prune -exec rm -rf {} +
tar -C "$tmp" -cf - airlock | "$SPRITE" exec -s "$CTRL" --stdin -- bash -c \
  'mkdir -p ~/airlock && rm -rf ~/airlock/ctrl && tar -xf - -C ~ && chmod 600 ~/airlock/airlock.env && echo deployed
   sprite-env services restart airlock >/dev/null 2>&1 && echo "service restarted" || echo "service not created yet"'
rm -rf "$tmp"
