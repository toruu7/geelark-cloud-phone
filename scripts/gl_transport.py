"""How bulk tasks talk to a phone: ADB over TCP, or GeeLark's own HTTPS API.

`AdbTransport` is the original behaviour (adb to an `ip:port` serial).

`ApiTransport` needs no ADB at all: shell commands go through `POST /open/v1/shell/execute` (the command's output is
returned in the response) and screenshots through `/open/v1/phone/screenShot`. Everything is HTTPS to
openapi.geelark.com, so it works from places that only allow web traffic, such as a Claude cloud environment behind an
HTTP proxy where raw TCP (ADB) is blocked. The cloud phone must be running and run Android 10 or newer.

Both transports expose the same small surface: run(args), screenshot(), state(), label.
`cloud_up` / `cloud_down` start and stop a cloud phone through the API (billing starts and stops with them).
"""
import time
import urllib.error
import urllib.parse
import urllib.request

import gl_adb
import gl_cloud
import gl_cloudadb

RATE_LIMIT_CODE = 40007            # GeeLark: 200 requests/minute per API
UI_DUMP_PATH = "/sdcard/.gl_ui.xml"
STATUS_NAMES = {0: "device", 1: "starting", 2: "shut down", 3: "expired"}


class AdbTransport:
    kind = "adb"

    def __init__(self, serial):
        self.serial = str(serial)
        self.label = self.serial

    def run(self, args, timeout=None):
        kw = {} if timeout is None else {"timeout": timeout}
        return gl_adb.run_adb(args, device=self.serial, **kw)

    def screenshot(self, timeout=25):
        return gl_adb.run_adb_bytes(["exec-out", "screencap", "-p"], device=self.serial, timeout=timeout)

    def state(self):
        return gl_adb.get_state(self.serial)


class ApiTransport:
    kind = "api"

    def __init__(self, phone_id):
        self.phone_id = str(phone_id)
        self.label = f"api-{self.phone_id}"

    # -- low level -----------------------------------------------------------------------------------------
    def _call(self, endpoint, payload, timeout=30):
        res = {}
        for _ in range(4):
            res = gl_cloud.cloud_api_request(endpoint, payload, timeout=timeout)
            if res.get("api_code") == RATE_LIMIT_CODE:      # back off and retry instead of failing the task
                time.sleep(5)
                continue
            break
        return res

    @staticmethod
    def _to_command(args):
        args = [str(a) for a in args]
        if args and args[0] == "shell":
            return " ".join(args[1:])
        if args[:2] == ["exec-out", "uiautomator"]:
            # `uiautomator dump /dev/tty` needs a terminal, and a busy page's full dump can exceed the API's output limit.
            # Dump to a file and send back only the nodes that have text or a label, trimmed to what the parser reads.
            keep = r"""sed -E 's|.* text="([^"]*)".* content-desc="([^"]*)".* clickable="([^"]*)".* bounds="([^"]*)".*|<node text="\1" content-desc="\2" clickable="\3" bounds="\4"/>|'"""
            # the dump fails with "could not get idle state" while a video animates, so retry a few times
            dump = f"for i in 1 2 3; do uiautomator dump {UI_DUMP_PATH} >/dev/null 2>&1 && [ -s {UI_DUMP_PATH} ] && break; sleep 1; done"
            return (f"{dump}; echo '<?xml version=\"1.0\"?><hierarchy>'; "
                    f"grep -o '<node [^>]*>' {UI_DUMP_PATH} | grep -E ' (text|content-desc)=\"[^\"]' | {keep}; "
                    f"echo '</hierarchy>'; rm -f {UI_DUMP_PATH}")
        return None

    # -- transport surface ---------------------------------------------------------------------------------
    def run(self, args, timeout=None):
        cmd = self._to_command(args)
        if cmd is None:
            return {"returncode": 2, "stdout": "", "stderr": f"not supported over the GeeLark API: {list(args)[:2]}"}
        res = self._call("/open/v1/shell/execute", {"id": self.phone_id, "cmd": cmd}, timeout=max(30, int(timeout or 0)))
        if res.get("status") != "success":
            return {"returncode": 1, "stdout": "", "stderr": str(res.get("message") or res.get("code") or "api error")[:300]}
        data = (res.get("response") or {}).get("data") or {}
        out = str(data.get("output") or "").strip()
        if data.get("status") is False:
            return {"returncode": 1, "stdout": out, "stderr": out or "command failed"}
        return {"returncode": 0, "stdout": out, "stderr": ""}

    def screenshot(self, timeout=90):
        res = self._call("/open/v1/phone/screenShot", {"id": self.phone_id})
        if res.get("status") != "success":
            return {"returncode": 1, "stdout": b"", "stderr": str(res.get("message") or "screenshot request failed")}
        task_id = str(((res.get("response") or {}).get("data") or {}).get("taskId") or "")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(2)
            r = self._call("/open/v1/phone/screenShot/result", {"taskId": task_id})
            data = ((r.get("response") or {}).get("data") or {}) if r.get("status") == "success" else {}
            status = data.get("status")
            if status == 2 and data.get("downloadLink"):
                try:
                    self.last_download_host = urllib.parse.urlparse(data["downloadLink"]).hostname
                    with urllib.request.urlopen(data["downloadLink"], timeout=30) as resp:
                        return {"returncode": 0, "stdout": resp.read(), "stderr": ""}
                except Exception as e:
                    host = urllib.parse.urlparse(data["downloadLink"]).hostname
                    return {"returncode": 1, "stdout": b"", "stderr": f"could not download the screenshot from {host}: {e}"}
            if status in (0, 3):
                return {"returncode": 1, "stdout": b"", "stderr": "GeeLark could not take the screenshot"}
        return {"returncode": 124, "stdout": b"", "stderr": "screenshot timed out"}

    def state(self):
        res = self._call("/open/v1/phone/status", {"ids": [self.phone_id]}, timeout=20)
        if res.get("status") != "success":
            return str(res.get("message") or "unknown")[:80]
        data = (res.get("response") or {}).get("data") or {}
        for item in data.get("successDetails") or []:
            if str(item.get("id")) == self.phone_id:
                return STATUS_NAMES.get(item.get("status"), f"status {item.get('status')}")
        for item in data.get("failDetails") or []:
            if str(item.get("id")) == self.phone_id:
                return str(item.get("msg") or "not found")
        return "unknown"


# ---------------------------------------------------------------------------------------------------------------
# Phone lifecycle over the API (billing starts at `start` and ends at `stop`)
# ---------------------------------------------------------------------------------------------------------------
def _check_batch(res, pid, what):
    if res.get("status") != "success":
        raise gl_cloudadb.CloudError(f"{what} failed: {res.get('message') or res.get('code')}")
    for item in ((res.get("response") or {}).get("data") or {}).get("failDetails") or []:
        if str(item.get("id")) == str(pid):
            raise gl_cloudadb.CloudError(f"{what} failed: {item.get('msg')} (code {item.get('code')})")


def cloud_up(pid, log_dir, timeout=180):
    """Start the phone and wait until it answers shell commands. Returns an ApiTransport. Recorded as billing first."""
    gl_cloudadb._registry_update(log_dir, lambda d: d.__setitem__(pid, {"since": int(time.time()), "via": "api"}))
    _check_batch(gl_cloud.cloud_api_request("/open/v1/phone/start", {"ids": [pid]}, timeout=30), pid, "start")
    t = ApiTransport(pid)
    deadline = time.monotonic() + timeout
    last = "not started"
    while time.monotonic() < deadline:
        state = t.state()
        if state == "device":
            boot = t.run(["shell", "getprop", "sys.boot_completed"], timeout=15)
            if boot["returncode"] == 0 and boot["stdout"].strip() == "1":
                return t
            last = f"booting ({boot['stderr'] or boot['stdout'] or 'no answer yet'})"
        else:
            last = state
        time.sleep(4)
    raise gl_cloudadb.CloudError(f"cloud phone {pid} was not ready after {timeout}s: {last}")


def cloud_down(pid, log_dir, attempts=3):
    """Stop the phone (stops billing). A phone that is already off counts as stopped."""
    last = ""
    for i in range(attempts):
        try:
            _check_batch(gl_cloud.cloud_api_request("/open/v1/phone/stop", {"ids": [pid]}, timeout=30), pid, "stop")
            gl_cloudadb._registry_update(log_dir, lambda d: d.pop(pid, None))
            return True
        except gl_cloudadb.CloudError as e:
            last = str(e)
            if ApiTransport(pid).state() in ("shut down", "expired"):
                gl_cloudadb._registry_update(log_dir, lambda d: d.pop(pid, None))
                return True
        time.sleep(2 * (i + 1))
    raise gl_cloudadb.CloudError(f"FAILED to stop cloud phone {pid} (it may still be billing): {last}")


def stop_leftovers(log_dir):
    return gl_cloudadb.stop_leftovers(log_dir, down_fn=cloud_down)
