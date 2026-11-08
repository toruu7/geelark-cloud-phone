"""GeeLark Cloud OpenAPI client and device-readiness resolver."""
import collections
import os
import threading
import time
import json
import subprocess
import re
import uuid
import urllib.request
import urllib.error
import gl_base
import gl_win32

RE_CLOUD_ENDPOINT = re.compile(r"^/open/[A-Za-z0-9_\-/]+$")

CLOUD_RETRY_STATUSES = {429, 500, 502, 503, 504}

# GeeLark allows 200 requests a minute per API. Every thread of a bulk run shares one sliding window, so 10 phones
# working at once are spread out instead of being refused. GEELARK_API_RATE_PER_MIN overrides the default.
DEFAULT_RATE_PER_MIN = 150
_rate_lock = threading.Lock()
_call_times = collections.deque()


def _throttle(now=time.monotonic, sleep=time.sleep):
    try:
        limit = int(os.environ.get("GEELARK_API_RATE_PER_MIN", DEFAULT_RATE_PER_MIN))
    except ValueError:
        limit = DEFAULT_RATE_PER_MIN
    if limit <= 0:
        return
    while True:
        with _rate_lock:
            t = now()
            while _call_times and t - _call_times[0] >= 60:
                _call_times.popleft()
            if len(_call_times) < limit:
                _call_times.append(t)
                return
            wait = 60 - (t - _call_times[0])
        sleep(max(0.05, wait))


def cloud_api_request(endpoint, payload=None, api_token=None, retries=2, timeout=15):
    """Hybrid Cloud OpenAPI client for https://openapi.geelark.com.
    Attaches a UUID v4 traceId and Bearer token, retries transient failures (network, 429, 5xx),
    and reports API-level failures (non-zero `code`) as errors. The token is never echoed back.
    """
    trace_id = str(uuid.uuid4())
    token = (api_token or os.environ.get("GEELARK_API_TOKEN", "")).strip()
    if not token:
        return {
            "status": "error",
            "code": "missing_api_token",
            "traceId": trace_id,
            "message": "GEELARK_API_TOKEN is not set. Set GEELARK_API_TOKEN environment variable or pass --token to use Cloud OpenAPI."
        }

    endpoint = endpoint if str(endpoint).startswith("/") else "/" + str(endpoint)
    if not RE_CLOUD_ENDPOINT.match(endpoint):
        return {"status": "error", "code": "invalid_endpoint", "traceId": trace_id,
                "message": "Endpoint must look like /open/v1/<resource>/<action>."}

    url = f"https://openapi.geelark.com{endpoint}"
    body_bytes = json.dumps(payload or {}).encode("utf-8")
    last_error = None
    for attempt in range(retries + 1):
        _throttle()
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "traceId": trace_id},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except ValueError:
                return {"status": "error", "code": "invalid_json", "traceId": trace_id, "endpoint": endpoint, "message": raw[:300]}
            api_code = data.get("code") if isinstance(data, dict) else None
            if api_code not in (None, 0, "0"):
                return {"status": "error", "code": "api_error", "api_code": api_code, "traceId": trace_id,
                        "endpoint": endpoint, "message": str(data.get("msg") or data.get("message") or "API error"), "response": data}
            return {"status": "success", "traceId": trace_id, "endpoint": endpoint, "response": data}
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.reason}"
            if e.code not in CLOUD_RETRY_STATUSES:
                break
        except Exception as e:  # URLError, timeouts, connection resets
            last_error = str(e)
        if attempt < retries:
            time.sleep(0.5 * (2 ** attempt))
    return {"status": "error", "code": "request_failed", "traceId": trace_id, "endpoint": endpoint, "message": last_error}

def ensure_device_ready(target=None, auto_boot=True):
    """Multi-Path Device Lifecycle Resolver:
    Path 1: Active / Cached Phone Window
    Path 2: Restore Minimized Phone Window
    Path 3: Auto-Scan Any Open Phone Window
    Path 4: Cloud OpenAPI Remote Boot (needs GEELARK_API_TOKEN + GEELARK_CLOUD_PHONE_ID)
    Path 5: Local GeeLark Desktop App Launch
    """
    paths_tried = []
    eff_target = target or gl_base.get_active_target()

    # Path 1 & 2: Check target window
    paths_tried.append("cached_or_target_window")
    win = gl_win32.find_target_window(eff_target, prefer_phone=True)
    if win:
        if win.get("minimized"):
            paths_tried.append("restore_minimized_window")
            try:
                gl_win32.focus_window(win["hwnd"])
            except Exception:
                pass
            return {"status": "ready", "path": "restore_minimized_window", "window": win, "paths_tried": paths_tried}
        return {"status": "ready", "path": "cached_or_target_window", "window": win, "paths_tried": paths_tried}

    # Path 3: Auto-scan any open phone window
    paths_tried.append("auto_discover_open_phone")
    wins = gl_win32.list_windows()
    phones = [w for w in wins if w.get("is_phone")]
    if phones:
        return {"status": "ready", "path": "auto_discover_open_phone", "window": phones[0], "paths_tried": paths_tried}

    if not auto_boot:
        return {"status": "error", "message": "No open phone window found and auto_boot is disabled", "paths_tried": paths_tried}

    # Path 4: Cloud OpenAPI Remote Boot
    cloud_id = os.environ.get("GEELARK_CLOUD_PHONE_ID", "").strip()
    if os.environ.get("GEELARK_API_TOKEN") and cloud_id:
        # Needs the real cloud phone ID; a window/profile number is not a valid ID.
        paths_tried.append("cloud_openapi_boot")
        c_res = cloud_api_request("/open/v1/phone/start", {"ids": [cloud_id]})
        if c_res.get("status") == "success":
            return {"status": "booting", "path": "cloud_openapi_boot", "cloud_result": c_res, "paths_tried": paths_tried}

    # Path 5: Local Desktop App Launch
    paths_tried.append("local_desktop_launch")
    if os.path.exists(gl_base.GEELARK_PATH):
        try:
            subprocess.Popen([gl_base.GEELARK_PATH])
            return {"status": "launching_desktop", "path": "local_desktop_launch", "executable": gl_base.GEELARK_PATH, "paths_tried": paths_tried}
        except Exception as e:
            return {"status": "error", "message": f"Failed to launch GeeLark desktop: {str(e)}", "paths_tried": paths_tried}

    return {"status": "error", "message": "Device unavailable across all lifecycle paths", "paths_tried": paths_tried}
