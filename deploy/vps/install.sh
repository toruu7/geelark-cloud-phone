#!/usr/bin/env bash
# Installs the GeeLark unattended runner on a Debian/Ubuntu server: code, a locked-down service user,
# and a systemd timer that checks the sheet every 5 minutes.
#
#   sudo bash install.sh
#
# Override the repos if yours differ:
#   PHONE_REPO=https://github.com/you/geelark-cloud-phone ADB_REPO=https://github.com/you/geelark-cloud-adb sudo -E bash install.sh
set -euo pipefail

PHONE_REPO="${PHONE_REPO:-https://github.com/toruu7/geelark-cloud-phone}"
ADB_REPO="${ADB_REPO:-https://github.com/toruu7/geelark-cloud-adb}"
BASE=/opt/geelark
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash install.sh" >&2
  exit 1
fi

echo "==> Installing packages (python3, adb, git)"
apt-get update -qq
apt-get install -y -qq python3 adb git

echo "==> Creating service user and directories"
id geelark >/dev/null 2>&1 || useradd --system --home-dir /var/lib/geelark --create-home --shell /usr/sbin/nologin geelark
mkdir -p "$BASE" /var/lib/geelark/logs
chown -R geelark:geelark /var/lib/geelark

clone_or_update() {
  local repo="$1" dir="$2"
  if [ -d "$dir/.git" ]; then
    git -C "$dir" pull --ff-only
  else
    git clone --depth 1 "$repo" "$dir"
  fi
}
echo "==> Fetching the runner and the cloud-adb skill"
clone_or_update "$PHONE_REPO" "$BASE/geelark-cloud-phone"
clone_or_update "$ADB_REPO" "$BASE/geelark-cloud-adb"

echo "==> Installing config and systemd units"
if [ ! -f /etc/geelark.env ]; then
  install -m 600 -o root -g root "$HERE/geelark.env.example" /etc/geelark.env
  echo "    created /etc/geelark.env  <-- EDIT IT: add your token, sheet URL and secret"
else
  echo "    /etc/geelark.env already exists; left unchanged"
fi
install -m 644 "$HERE/geelark-bulk.service" /etc/systemd/system/geelark-bulk.service
install -m 644 "$HERE/geelark-bulk.timer" /etc/systemd/system/geelark-bulk.timer
systemctl daemon-reload

echo
echo "Next steps:"
echo "  1. sudo nano /etc/geelark.env            (fill in the three values)"
echo "  2. sudo systemctl start geelark-bulk.service    # one manual pass; read the result with:"
echo "     journalctl -u geelark-bulk.service -n 50 --no-pager"
echo "  3. sudo systemctl enable --now geelark-bulk.timer   # only after step 2 looks right"
echo
echo "Pause everything instantly: tick 'paused' in the sheet's Settings tab (or: sudo systemctl stop geelark-bulk.timer)."
