#!/usr/bin/env python3
"""Refresh the vendored copy of the geelark-cloud-adb skill in .claude/skills/geelark-cloud-adb.

A cloud agent only sees the repository it clones, so the phone-control skill is copied in here.
Upstream: https://github.com/toruu7/geelark-cloud-adb (MIT).

  python scripts/sync_cloud_adb.py                      # download the latest main from GitHub
  python scripts/sync_cloud_adb.py --ref <tag|sha>      # a specific ref
  python scripts/sync_cloud_adb.py --from ../geelark-cloud-adb   # copy from a local checkout

Prints which files changed. Review and commit the result.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request

UPSTREAM = "toruu7/geelark-cloud-adb"
FILES = ["SKILL.md", "README.md", "LICENSE", "scripts/geelark_adb.py"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, ".claude", "skills", "geelark-cloud-adb")


def _http(url):
    req = urllib.request.Request(url, headers={"User-Agent": "geelark-sync"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def write_if_changed(path, data):
    """Write bytes (normalized to LF). Returns True when the file content changed."""
    data = data.replace(b"\r\n", b"\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, "rb") as f:
            if f.read() == data:
                return False
    with open(path, "wb") as f:
        f.write(data)
    return True


def write_upstream_note(dest, commit):
    note = (f"Vendored from https://github.com/{UPSTREAM}\ncommit: {commit}\n"
            "Refresh with: python scripts/sync_cloud_adb.py\n").encode()
    return write_if_changed(os.path.join(dest, "UPSTREAM.txt"), note)


def sync_from_local(src, dest=DEST):
    changed = []
    for rel in FILES:
        with open(os.path.join(src, rel), "rb") as f:
            if write_if_changed(os.path.join(dest, rel), f.read()):
                changed.append(rel)
    try:
        commit = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20).stdout.strip() or "local"
    except (OSError, subprocess.SubprocessError):
        commit = "local"
    if write_upstream_note(dest, commit):
        changed.append("UPSTREAM.txt")
    return changed, commit


def sync_from_github(ref="main", dest=DEST, fetch=_http):
    commit = json.loads(fetch(f"https://api.github.com/repos/{UPSTREAM}/commits/{ref}"))["sha"]
    changed = []
    for rel in FILES:
        data = fetch(f"https://raw.githubusercontent.com/{UPSTREAM}/{commit}/{rel}")
        if write_if_changed(os.path.join(dest, rel), data):
            changed.append(rel)
    if write_upstream_note(dest, commit):
        changed.append("UPSTREAM.txt")
    return changed, commit


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="src", help="copy from a local checkout instead of GitHub")
    p.add_argument("--ref", default="main", help="GitHub branch, tag or commit (default: main)")
    args = p.parse_args(argv)
    changed, commit = sync_from_local(args.src) if args.src else sync_from_github(args.ref)
    print(f"upstream commit: {commit}")
    print("changed: " + (", ".join(changed) if changed else "nothing (already up to date)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
