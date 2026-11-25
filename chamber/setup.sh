#!/bin/bash
# Builds the chamber baseline. Runs ON chamber-1 (as the sprite user, with sudo), with egress open.
# Usage: AIRLOCK_KEY=... AIRLOCK_CANARY=... bash setup.sh <dir with worker.py and extract.py>
set -euo pipefail
SRC="${1:?source dir}"
: "${AIRLOCK_KEY:?}" "${AIRLOCK_CANARY:?}"

sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  tesseract-ocr tesseract-ocr-ita poppler-utils bubblewrap >/dev/null

# unprivileged user the jail drops to (no sudo rights, no shell login needed)
id jail >/dev/null 2>&1 || sudo useradd --system --no-create-home --shell /usr/sbin/nologin jail
JAIL_UID=$(id -u jail)

# trusted code and secrets: root only
sudo install -d -m 755 -o root -g root /opt/airlock
sudo install -m 644 -o root -g root "$SRC/worker.py" "$SRC/extract.py" /opt/airlock/
printf '%s' "$AIRLOCK_KEY" | sudo tee /opt/airlock/key >/dev/null
printf '%s' "$AIRLOCK_CANARY" | sudo tee /opt/airlock/canary >/dev/null
echo "$JAIL_UID" | sudo tee /opt/airlock/jail_uid >/dev/null
sudo chmod 600 /opt/airlock/key /opt/airlock/canary

# jail home with root-owned canaries: readable by the jail, but it cannot change their times
sudo rm -rf /srv/airlock
sudo install -d -m 755 -o root -g root /srv/airlock /srv/airlock/home /srv/airlock/home/.config \
  /srv/airlock/home/.config/box /srv/airlock/home/.aws
sudo install -d -m 700 -o root -g root /srv/airlock/state
printf '%s\n' "$AIRLOCK_CANARY" | sudo tee /srv/airlock/home/.config/box/token >/dev/null
printf '[default]\naws_access_key_id = AKIA%s\naws_secret_access_key = %s\n' \
  "$(echo "$AIRLOCK_CANARY" | tail -c 13 | tr a-z A-Z)" "$AIRLOCK_CANARY" \
  | sudo tee /srv/airlock/home/.aws/credentials >/dev/null
sudo chmod 444 /srv/airlock/home/.config/box/token /srv/airlock/home/.aws/credentials
sudo touch -a -d "2020-01-01 00:00:00 UTC" /srv/airlock/home/.config/box/token /srv/airlock/home/.aws/credentials

# leftovers from the spike
rm -rf ~/.config/box ~/spike /tmp/x.sh 2>/dev/null || true

# worker service (root via sudo); the proxy routes the Sprite URL to port 8080
sprite-env services delete worker >/dev/null 2>&1 || true
sprite-env services create worker --cmd /usr/bin/sudo \
  --args /usr/bin/python3,/opt/airlock/worker.py --http-port 8080 --no-stream
echo "setup ok, jail uid $JAIL_UID"
