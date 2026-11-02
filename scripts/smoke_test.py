#!/usr/bin/env python3
"""Live smoke test against a real GeeLark phone window. Read-only: it never taps, swipes or types.

Usage: python scripts/smoke_test.py [--window 4]
Exit code is the number of failed checks.
"""

import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GEELARK = os.path.join(SCRIPT_DIR, "geelark.py")


def run(*args):
    p = subprocess.run([sys.executable, GEELARK, *args], capture_output=True, text=True, timeout=120)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, {"raw": p.stdout.strip(), "stderr": p.stderr.strip()}


def main():
    window = sys.argv[sys.argv.index("--window") + 1] if "--window" in sys.argv else None
    wargs = ["--window", window] if window else []
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

    if sys.platform != "win32":
        print("SKIP: live smoke test needs a Windows host with GeeLark running.")
        return 0

    code, st = run("status")
    phones = st.get("phone_windows", []) if isinstance(st, dict) else []
    check("status runs", code == 0 and st.get("status") == "success")
    check("a phone window is open", bool(phones), f"{len(phones)} found")
    check("ADB reachable", bool(st.get("adb_ready")), f"devices: {st.get('adb_connected_devices')}")
    if not phones:
        print("Open a GeeLark phone and re-run for the capture/OCR checks.")
        return len(results) - sum(results)

    out = os.path.join(SCRIPT_DIR, ".smoke_capture.png")
    code, cap = run("capture", "--annotate", "--low-token", "-o", out, *wargs)
    check("capture + annotate", code == 0 and cap.get("status") == "success" and os.path.exists(out))
    if os.path.exists(out):
        check("capture is non-trivial", os.path.getsize(out) > 5000, f"{os.path.getsize(out)} bytes")
        os.remove(out)

    code, ft = run("find-text", "a", *wargs)
    check("OCR engine responds", code == 0 and isinstance(ft, dict) and ft.get("status") in ("success", "error"), str(ft.get("status")))

    code, ui = run("dump-ui")
    check("ADB UI tree dump", code == 0 and ui.get("status") == "success", ui.get("message", ""))

    failed = len(results) - sum(results)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return failed


if __name__ == "__main__":
    sys.exit(main())
