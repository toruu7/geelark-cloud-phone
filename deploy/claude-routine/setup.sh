#!/bin/bash
# Paste this into the cloud environment's "Setup script". It runs before the agent starts and installs the runner
# at a pinned commit, so the agent only RUNS code that was already in place; it never downloads and executes code
# itself (which the cloud permission classifier blocks). To update the runner: change REF, save the environment.
set -euo pipefail
REPO=https://github.com/toruu7/geelark-cloud-phone
REF=ee19f75235fcb51fbe4e8f2b0bc6b3a14b3e0cab
DEST=/opt/geelark
rm -rf "$DEST"
git clone --quiet "$REPO" "$DEST"
git -C "$DEST" checkout --quiet "$REF"
python3 --version
echo "geelark runner installed at $DEST ($(git -C "$DEST" rev-parse --short HEAD))"
