"""Google Sheets task queue + report log (via the Apps Script web app in sheets/apps_script.gs).

Three layers, so reports are never lost:
  * a local JSONL run log, always written;
  * the sheet, written with retries;
  * an on-disk spool for sheet writes that still failed, replayed by `bulk-flush` / the next run.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import gl_base

ALLOWED_HOSTS = {"script.google.com", "script.googleusercontent.com"}
DEFAULT_LOG_DIR = os.path.join(gl_base.SCRIPT_DIR, "..", "logs")
SPOOL_NAME = ".report_spool.jsonl"
# 401 is retried because Apps Script returns it transiently (e.g. right after a redeploy); a wrong secret
# is answered with a normal JSON {ok:false,error:'unauthorized'}, never a 401, so retrying cannot hide misconfiguration.
RETRY_STATUSES = {401, 429, 500, 502, 503, 504}
READ_VERBS = {"ping", "devices", "settings"}     # safe to repeat after an HTML reply


class SheetsError(RuntimeError):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def truthy(value):
    return str(value).strip().lower() in ("true", "yes", "y", "1", "on", "checked")


def validate_url(url):
    u = urllib.parse.urlparse(str(url or ""))
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise SheetsError("GEELARK_SHEETS_URL must be an https://script.google.com/... Apps Script web app URL.")
    return url


class SheetsClient:
    def __init__(self, url, secret, timeout=30, retries=3):
        self.url = validate_url(url)
        if not secret:
            raise SheetsError("GEELARK_SHEETS_SECRET is not set.")
        self._secret = secret
        self.timeout = timeout
        self.retries = retries

    def __repr__(self):
        return f"SheetsClient(url={self.url!r}, secret=<hidden>)"

    @classmethod
    def from_env(cls):
        url = os.environ.get("GEELARK_SHEETS_URL", "").strip()
        secret = os.environ.get("GEELARK_SHEETS_SECRET", "").strip()
        if not url and not secret:
            return None
        return cls(url, secret)

    def call(self, verb, **payload):
        """POST one action. Apps Script answers POSTs with a redirect that urllib follows as GET,
        after the action has already run. Never raises on API errors; returns {"ok": False, ...}."""
        body = json.dumps(dict(payload, action=verb, secret=self._secret)).encode("utf-8")
        last = "unknown error"
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                try:
                    data = json.loads(raw)
                except ValueError:
                    # Under load Apps Script sometimes answers a call with an HTML page. Re-asking is safe for pure reads.
                    # Writes are not retried here (a repeat could duplicate a row); they go to the spool instead, and a
                    # claim that hits this is retried by the worker's own loop.
                    if verb in READ_VERBS and attempt < self.retries:
                        last = "non_json_response"
                        time.sleep(min(8.0, 0.8 * (2 ** attempt)))
                        continue
                    return {"ok": False, "error": "non_json_response", "detail": raw[:200]}
                return data if isinstance(data, dict) else {"ok": False, "error": "bad_response"}
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                e.close()
                if e.code not in RETRY_STATUSES:
                    break
            except Exception as e:  # network, DNS, timeout
                last = str(e)
            if attempt < self.retries:
                time.sleep(min(8.0, 0.8 * (2 ** attempt)))
        return {"ok": False, "error": "request_failed", "detail": last}

    def ping(self):
        return self.call("ping")

    def pending_devices(self):
        res = self.call("devices")
        if not res.get("ok"):
            raise SheetsError(f"devices failed: {res.get('error')} {res.get('detail', '')}".strip())
        return [str(d) for d in res.get("devices", [])]

    def pending_summary(self):
        """{"devices": [named devices with waiting tasks], "blank": number of waiting tasks with no device}."""
        res = self.call("devices")
        if not res.get("ok"):
            raise SheetsError(f"devices failed: {res.get('error')} {res.get('detail', '')}".strip())
        return {"devices": [str(d) for d in res.get("devices", [])], "blank": int(res.get("blank") or 0)}

    def settings(self):
        """Run settings the owner edits in the sheet's Settings tab ({} if the tab/endpoint is unavailable)."""
        res = self.call("settings")
        return res.get("settings", {}) if res.get("ok") and isinstance(res.get("settings"), dict) else {}

    def claim(self, worker, limit=1, exact=False):
        res = self.call("claim", worker=worker, limit=limit, exact=bool(exact))
        if not res.get("ok"):
            raise SheetsError(f"claim failed: {res.get('error')} {res.get('detail', '')}".strip())
        return res.get("tasks", [])


class Reporter:
    """Thread-safe fan-out of results to the local log, the sheet and the spool."""

    def __init__(self, run_id, client=None, log_dir=None):
        self.run_id = run_id
        self.client = client
        self.log_dir = os.path.abspath(log_dir or DEFAULT_LOG_DIR)
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, f"bulk-{run_id}.jsonl")
        self.spool_path = os.path.join(self.log_dir, SPOOL_NAME)
        self._lock = threading.Lock()
        self.counts = {"success": 0, "failed": 0, "other": 0}
        self.sheet_failures = 0

    def _append(self, path, record):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _send(self, action, payload):
        """Send to the sheet (outside the lock so one slow write can't stall other workers); spool on failure."""
        if not self.client:
            return False
        res = self.client.call(action, **payload)
        if res.get("ok"):
            return True
        with self._lock:
            self.sheet_failures += 1
            self._append(self.spool_path, {"action": action, "payload": payload, "error": res.get("error")})
        return False

    def report(self, task, status, attempts, duration_s, message="", output=None):
        """status: success | failed | error | timeout | skipped | offline"""
        payload = {
            "run_id": self.run_id, "task_id": task.get("task_id", ""), "device": task.get("device", ""),
            "task_action": task.get("action", ""), "status": status, "attempts": attempts,
            "duration_s": round(float(duration_s), 2), "message": str(message)[:500],
            "output": json.dumps(output, ensure_ascii=False)[:1500] if output is not None else "",
        }
        with self._lock:
            bucket = "success" if status == "success" else ("failed" if status in ("failed", "error", "timeout") else "other")
            self.counts[bucket] += 1
            self._append(self.log_path, dict(payload, ts=now_iso(), kind="task"))
        self._send("report", payload)

    def event(self, level, message, device="", task_id=""):
        """Anything else worth a row: device offline, retry, warning, startup/shutdown notes."""
        payload = {"run_id": self.run_id, "level": level, "message": str(message)[:500], "device": device, "task_id": task_id}
        with self._lock:
            self._append(self.log_path, dict(payload, ts=now_iso(), kind="event"))
        self._send("log", payload)

    def cost(self, device, phone_id, minutes, cost_per_minute=None, currency="USD"):
        """One row per cloud phone per run: how long it was up (billing) and, when a rate is set, the estimated cost."""
        payload = {"run_id": self.run_id, "device": device, "phone_id": str(phone_id), "minutes": round(float(minutes), 2),
                   "cost": round(float(minutes) * cost_per_minute, 4) if cost_per_minute else "", "currency": currency or ""}
        with self._lock:
            self._append(self.log_path, dict(payload, ts=now_iso(), kind="cost"))
        self._send("cost", payload)
        return payload

    def summary(self, started, workers, total, notes=""):
        payload = {
            "run_id": self.run_id, "started": started, "finished": now_iso(), "workers": ",".join(workers),
            "total": total, "success": self.counts["success"], "failed": self.counts["failed"],
            "other": self.counts["other"], "notes": notes,
        }
        with self._lock:
            self._append(self.log_path, dict(payload, ts=now_iso(), kind="summary"))
        self._send("summary", payload)
        return payload


def flush_spool(client, log_dir=None):
    """Replay sheet writes that failed earlier. Returns {"sent": n, "remaining": m}."""
    path = os.path.join(os.path.abspath(log_dir or DEFAULT_LOG_DIR), SPOOL_NAME)
    if not client or not os.path.exists(path):
        return {"sent": 0, "remaining": 0}
    with open(path, encoding="utf-8") as f:
        entries = [json.loads(line) for line in f if line.strip()]
    keep, sent = [], 0
    for e in entries:
        if client.call(e["action"], **e["payload"]).get("ok"):
            sent += 1
        else:
            keep.append(e)
    if keep:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in keep)
    else:
        os.remove(path)
    return {"sent": sent, "remaining": len(keep)}
