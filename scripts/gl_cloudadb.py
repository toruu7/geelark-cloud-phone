"""Bring GeeLark *cloud* phones up and down for bulk runs, through the separate `geelark-cloud-adb` skill.

That skill owns the Cloud OpenAPI + ADB login dance (start the phone, enable ADB, connect, `glogin` with a
password that changes every start). We call its CLI as a subprocess, so no code or secret is duplicated here:
the ADB password never passes through this program, and the API token stays in the environment.

Cloud phones bill per minute. Every phone we start is recorded in a registry file and is stopped when its worker
ends, when the run ends, or on the next `bulk-cloud-stop` if the process was killed before it could.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

import gl_base

CLOUD_PREFIX = "cloud:"
CLOUD_DEVICE_RE = re.compile(r"^cloud:[A-Za-z0-9_\-]+$")
SERIAL_RE = re.compile(r"^[A-Za-z0-9_.\-]+:\d{2,5}$")
REGISTRY_NAME = ".cloud_active.json"
_registry_lock = threading.Lock()


class CloudError(RuntimeError):
    pass


def is_cloud_device(device):
    return str(device or "").startswith(CLOUD_PREFIX)


def phone_id(device):
    return str(device)[len(CLOUD_PREFIX):]


def find_script():
    """Locate the geelark-cloud-adb skill's CLI."""
    here = os.path.abspath(gl_base.SCRIPT_DIR)
    skill_dir = os.path.dirname(here)
    home = os.path.expanduser("~")
    candidates = [
        os.environ.get("GEELARK_CLOUD_ADB", "").strip(),
        os.path.join(os.path.dirname(skill_dir), "geelark-cloud-adb", "scripts", "geelark_adb.py"),
        os.path.join(home, ".claude", "skills", "geelark-cloud-adb", "scripts", "geelark_adb.py"),
        os.path.join(home, ".gemini", "config", "skills", "geelark-cloud-adb", "scripts", "geelark_adb.py"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise CloudError(
        "geelark-cloud-adb skill not found. Install it or set GEELARK_CLOUD_ADB to its scripts/geelark_adb.py."
    )


def _run(args, timeout):
    script = find_script()
    try:
        proc = subprocess.run([sys.executable, script] + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise CloudError(f"geelark-cloud-adb {args[0]} timed out after {timeout}s")
    try:
        data = json.loads(proc.stdout.strip() or "{}")
    except ValueError:
        data = {"status": "error", "message": (proc.stdout or proc.stderr).strip()[:300]}
    if not isinstance(data, dict):
        data = {"status": "error", "message": "unexpected output"}
    return data


def _registry_path(log_dir):
    return os.path.join(os.path.abspath(log_dir), REGISTRY_NAME)


def _registry_update(log_dir, fn):
    path = _registry_path(log_dir)
    with _registry_lock:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        fn(data)
        if data:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        elif os.path.exists(path):
            os.remove(path)


def leftover_phones(log_dir):
    try:
        with open(_registry_path(log_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def cloud_up(pid, log_dir, timeout=180):
    """Start the phone and connect ADB. Returns the ADB serial. Records the phone as billing first."""
    _registry_update(log_dir, lambda d: d.__setitem__(pid, {"since": int(time.time())}))
    res = _run(["up", "--id", pid, "--timeout", str(int(timeout))], timeout=timeout + 60)
    serial = str(res.get("serial", ""))
    if res.get("status") != "success" or not SERIAL_RE.match(serial):
        raise CloudError(f"could not bring up cloud phone {pid}: {res.get('message') or res.get('last') or 'no serial returned'}")
    return serial


def cloud_down(pid, log_dir, attempts=3):
    """Stop the phone (stops billing). Retries; returns True once the stop was accepted."""
    last = ""
    for i in range(attempts):
        try:
            res = _run(["down", "--id", pid], timeout=90)
            if res.get("status") == "success":
                _registry_update(log_dir, lambda d: d.pop(pid, None))
                return True
            last = res.get("message", "")
        except CloudError as e:
            last = str(e)
        time.sleep(2 * (i + 1))
    raise CloudError(f"FAILED to stop cloud phone {pid} (it may still be billing): {last}")


def stop_leftovers(log_dir):
    """Stop every phone a previous, interrupted run left registered. Returns {stopped: [...], failed: [...]}."""
    stopped, failed = [], []
    for pid in list(leftover_phones(log_dir)):
        try:
            cloud_down(pid, log_dir)
            stopped.append(pid)
        except CloudError as e:
            failed.append({"id": pid, "error": str(e)})
    return {"stopped": stopped, "failed": failed}
