"""ADB helpers: timeout-guarded runner, device resolution, and input injection.

Input injected through ADB does not move the physical mouse or need the phone window in front.
"""

import os
import re
import subprocess
import time

BUNDLED_ADB_PATH = os.path.expandvars(r"%APPDATA%\GeeLark\scrcpy\adb.exe")
DEFAULT_TIMEOUT = 15.0
RC_TIMEOUT = 124
RC_NOT_FOUND = 127

KEYCODES = {
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "recent": "KEYCODE_APP_SWITCH",
    "appswitch": "KEYCODE_APP_SWITCH",
    "enter": "KEYCODE_ENTER",
    "tab": "KEYCODE_TAB",
    "esc": "KEYCODE_ESCAPE",
    "backspace": "KEYCODE_DEL",
}

# Commands that must not be sent with -s <serial>
_SERVERLESS = {"devices", "connect", "disconnect", "start-server", "kill-server", "version"}
_SERIAL_RE = re.compile(r"^[A-Za-z0-9_.:\-]+$")

_device_cache = {"at": 0.0, "devices": []}
_DEVICE_CACHE_TTL = 5.0


def adb_executable():
    override = os.environ.get("GEELARK_ADB_PATH", "").strip()
    if override:
        return override
    return BUNDLED_ADB_PATH if os.path.exists(BUNDLED_ADB_PATH) else "adb"


def _timeout():
    try:
        return float(os.environ.get("GEELARK_ADB_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


def run_adb(args, device=None, timeout=None):
    """Run adb with a hard timeout. Never raises for adb being absent or hanging."""
    args = [str(a) for a in args]
    if device is None and args and args[0] not in _SERVERLESS:
        device = os.environ.get("GEELARK_ADB_DEVICE", "").strip() or None
    cmd = [adb_executable()]
    if device and args and args[0] not in _SERVERLESS:
        if not _SERIAL_RE.match(str(device)):
            return {"returncode": 2, "stdout": "", "stderr": f"Invalid adb device serial: {device!r}"}
        cmd.extend(["-s", str(device)])
    cmd.extend(args)
    limit = _timeout() if timeout is None else timeout
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired:
        return {"returncode": RC_TIMEOUT, "stdout": "", "stderr": f"adb timed out after {limit}s", "timed_out": True}
    except (FileNotFoundError, OSError) as e:
        return {"returncode": RC_NOT_FOUND, "stdout": "", "stderr": f"adb unavailable: {e}"}
    return {"returncode": res.returncode, "stdout": res.stdout.strip(), "stderr": res.stderr.strip()}


def parse_devices(stdout):
    return [
        line.split("\t")[0].strip()
        for line in (stdout or "").splitlines()
        if "\tdevice" in line
    ]


def list_devices(use_cache=True):
    now = time.monotonic()
    if use_cache and now - _device_cache["at"] < _DEVICE_CACHE_TTL:
        return list(_device_cache["devices"])
    res = run_adb(["devices"])
    devices = parse_devices(res.get("stdout", "")) if res.get("returncode") == 0 else []
    _device_cache.update(at=now, devices=devices)
    return list(devices)


def resolve_device(preferred=None):
    """Pick an adb serial: explicit > GEELARK_ADB_DEVICE > the only connected device. None if ambiguous."""
    if preferred:
        return str(preferred)
    env = os.environ.get("GEELARK_ADB_DEVICE", "").strip()
    if env:
        return env
    devices = list_devices()
    return devices[0] if len(devices) == 1 else None


def keyevent(device, key_name):
    """Send a key via `input keyevent`. Returns result dict on success, None if unsupported/failed."""
    code = KEYCODES.get(key_name.lower().strip())
    if not code or not device:
        return None
    res = run_adb(["shell", "input", "keyevent", code], device=device)
    return res if res["returncode"] == 0 else None


def screen_size(device):
    res = run_adb(["shell", "wm", "size"], device=device)
    if res["returncode"] != 0:
        return None
    m = re.findall(r"(\d+)x(\d+)", res["stdout"])
    if not m:
        return None
    w, h = m[-1]  # an "Override size" line, when present, comes last and is the effective one
    return int(w), int(h)


def tap_normalized(device, nx, ny):
    size = screen_size(device) if device else None
    if not size:
        return None
    x, y = int(float(nx) * size[0]), int(float(ny) * size[1])
    res = run_adb(["shell", "input", "tap", x, y], device=device)
    return {"coords": [x, y]} if res["returncode"] == 0 else None


def swipe_normalized(device, x1, y1, x2, y2, duration_ms=250):
    size = screen_size(device) if device else None
    if not size:
        return None
    w, h = size
    pts = [int(float(x1) * w), int(float(y1) * h), int(float(x2) * w), int(float(y2) * h)]
    res = run_adb(["shell", "input", "swipe", *pts, int(duration_ms)], device=device)
    return {"from": pts[:2], "to": pts[2:]} if res["returncode"] == 0 else None
