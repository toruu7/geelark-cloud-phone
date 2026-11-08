#!/bin/bash
# Paste this into the cloud environment's "Setup script". It runs before the agent starts and installs the runner
# at a pinned commit, so the agent only RUNS code that was already in place; it never downloads and executes code
# itself (which the cloud permission classifier blocks). To update the runner: change REF, save the environment.
# setup-version: 5 (pins the runner to REF; bump this number to force the cloud to re-run the script)
set -euo pipefail
REPO=https://github.com/toruu7/geelark-cloud-phone
REF=f93b13e66aef2439695bc22c42cbf8234da44d49
DEST=/opt/geelark
rm -rf "$DEST"
git clone --quiet "$REPO" "$DEST"
git -C "$DEST" checkout --quiet "$REF"
python3 --version
echo "geelark runner installed at $DEST ($(git -C "$DEST" rev-parse --short HEAD))"
