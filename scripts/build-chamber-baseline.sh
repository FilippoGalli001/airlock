#!/bin/bash
# Builds (or rebuilds) the chamber-1 baseline from this laptop, then checkpoints it.
# Writes the key, canary, URL and baseline checkpoint id to .env.chamber (gitignored).
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
SPRITE="${SPRITE_BIN:-sprite}"
command -v "$SPRITE" >/dev/null 2>&1 || SPRITE="$LOCALAPPDATA/Programs/Sprite/sprite.exe"
CH="${CHAMBER:-chamber-1}"
ENVF=.env.chamber

if [ ! -f "$ENVF" ]; then
  {
    echo "AIRLOCK_KEY=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    echo "AIRLOCK_CANARY=AIRLOCK-CANARY-$(head -c 8 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  } > "$ENVF"
fi
# shellcheck disable=SC1090
. "./$ENVF"

policy() { "$SPRITE" api -s "$CH" /policy/network -- -s -X POST -H "Content-Type: application/json" -d "$1" >/dev/null; }

echo "1/6 open egress for apt"
policy '{"rules":[]}'
sleep 3

echo "2/6 push files"
tmp=$(mktemp -d)
cp chamber/worker.py chamber/extract.py chamber/setup.sh "$tmp/"
printf 'AIRLOCK_KEY=%s\nAIRLOCK_CANARY=%s\n' "$AIRLOCK_KEY" "$AIRLOCK_CANARY" > "$tmp/secrets.env"
tar -C "$tmp" -cf - . | "$SPRITE" exec -s "$CH" --stdin -- bash -c 'rm -rf /tmp/airlock-src && mkdir -p /tmp/airlock-src && tar -xf - -C /tmp/airlock-src'
rm -rf "$tmp"

echo "3/6 run setup"
"$SPRITE" exec -s "$CH" --no-stdin -- bash -c 'set -a; . /tmp/airlock-src/secrets.env; set +a; bash /tmp/airlock-src/setup.sh /tmp/airlock-src; rm -rf /tmp/airlock-src'

echo "4/6 deny all egress"
policy '{"rules":[{"domain":"*","action":"deny"}]}'
"$SPRITE" config update -s "$CH" --url-auth public >/dev/null
URL=$("$SPRITE" info -s "$CH" | awk '/^URL/{print $2}')
sleep 3

echo "5/6 health"
for i in $(seq 1 20); do
  if curl -fs -H "X-Airlock-Key: $AIRLOCK_KEY" "$URL/health" 2>/dev/null; then echo; break; fi
  sleep 1
done

echo "6/6 checkpoint"
out=$("$SPRITE" exec -s "$CH" --no-stdin -- sprite-env checkpoints create --comment "airlock baseline")
CP=$(echo "$out" | grep -o 'Checkpoint v[0-9]* created' | grep -o 'v[0-9]*' | head -1)
echo "baseline checkpoint: $CP"
grep -v '^AIRLOCK_URL=\|^AIRLOCK_BASELINE=' "$ENVF" > "$ENVF.tmp" || true
{ cat "$ENVF.tmp"; echo "AIRLOCK_URL=$URL"; echo "AIRLOCK_BASELINE=$CP"; } > "$ENVF"
rm -f "$ENVF.tmp"
echo "done: $ENVF updated"
