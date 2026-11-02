"""Bulk automation: run queued tasks on many phones in parallel over ADB and report every outcome.

* ADB only. Nothing here moves the mouse, focuses windows or uses OCR, so it never needs the desktop lock
  and can run while you use the PC.
* One worker thread per ADB device. A worker takes tasks one at a time, so tasks for one phone run in order,
  while different phones run in parallel.
* Tasks come from a Google Sheet queue (see gl_sheets / sheets/apps_script.gs) or a local JSON file.
* Task rows are untrusted input: only the actions below exist (no raw shell), every parameter is validated,
  and anything passed to the device shell is quoted.
"""
import json
import os
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime

import gl_adb
import gl_base
import gl_sheets

MAX_SLEEP_S = 300
MAX_TEXT = 500
MAX_STEPS = 50
MAX_PARAMS_BYTES = 8000
PKG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://\S+$")
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.\-]")
ERROR_OUTPUT_RE = re.compile(r"\b(Error|Exception)\b")


class TaskError(Exception):
    """The task itself is invalid (bad action/params). Never retried."""


class TaskTimeout(Exception):
    """The task exceeded its deadline."""


# ---------------------------------------------------------------------------
# Task parsing and validation
# ---------------------------------------------------------------------------
def parse_params(raw):
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        params = raw
    else:
        text = str(raw)
        if len(text.encode("utf-8")) > MAX_PARAMS_BYTES:
            raise TaskError(f"params larger than {MAX_PARAMS_BYTES} bytes")
        try:
            params = json.loads(text)
        except ValueError as e:
            raise TaskError(f"params is not valid JSON: {e}")
    if not isinstance(params, dict):
        raise TaskError("params must be a JSON object")
    return params


def _num(params, key, lo, hi, default=None, required=False):
    if key not in params:
        if required:
            raise TaskError(f"missing '{key}'")
        return default
    try:
        v = float(params[key])
    except (TypeError, ValueError):
        raise TaskError(f"'{key}' must be a number")
    if not (lo <= v <= hi):
        raise TaskError(f"'{key}' must be between {lo} and {hi}")
    return v


def _str(params, key, max_len=MAX_TEXT, required=True):
    v = params.get(key)
    if v is None or v == "":
        if required:
            raise TaskError(f"missing '{key}'")
        return None
    if not isinstance(v, str):
        raise TaskError(f"'{key}' must be text")
    if len(v) > max_len:
        raise TaskError(f"'{key}' longer than {max_len} characters")
    return v


def _package(name):
    pkg = gl_base.COMMON_APPS.get(name.lower().strip(), name.strip())
    if not PKG_RE.match(pkg):
        raise TaskError(f"'{name}' is not a known app or a valid Android package name")
    return pkg


def normalize_task(raw):
    """Turn a sheet row / JSON object into {task_id, device, action, params}. Raises TaskError."""
    if not isinstance(raw, dict):
        raise TaskError("task must be an object")
    action = str(raw.get("action") or "").strip().lower()
    if action not in ACTIONS:
        raise TaskError(f"unknown action '{action}'. Allowed: {', '.join(sorted(ACTIONS))}")
    task = {
        "task_id": str(raw.get("task_id") or uuid.uuid4().hex[:8]),
        "device": str(raw.get("device") or "").strip(),
        "action": action,
        "params": parse_params(raw.get("params")),
    }
    if task["device"] and not gl_adb._SERIAL_RE.match(task["device"]):
        raise TaskError(f"invalid device serial '{task['device']}'")
    validate_action(action, task["params"])
    return task


def validate_action(action, params, depth=0):
    ACTIONS[action]["validate"](params)


# ---------------------------------------------------------------------------
# Execution context
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, device, task_id, run_id, deadline, shots_dir):
        self.device = device
        self.task_id = task_id
        self.run_id = run_id
        self.deadline = deadline
        self.shots_dir = shots_dir

    def check(self):
        if time.monotonic() > self.deadline:
            raise TaskTimeout("task exceeded its time limit")

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while True:
            self.check()
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(0.25, left))

    def adb(self, args, **kw):
        self.check()
        return gl_adb.run_adb(args, device=self.device, **kw)


def ok(message="ok", output=None):
    return {"status": "success", "message": message, "output": output}


def fail(message, output=None):
    return {"status": "failed", "message": message, "output": output}


def _adb_error(res):
    return res["returncode"] != 0 or bool(ERROR_OUTPUT_RE.search(res.get("stdout", "") + " " + res.get("stderr", "")))


# ---------------------------------------------------------------------------
# UI tree helpers (uiautomator dump)
# ---------------------------------------------------------------------------
def foreground_package(ctx):
    res = ctx.adb(["shell", "dumpsys", "window"], timeout=20)
    if res["returncode"] != 0:
        return None
    m = re.search(r"mCurrentFocus=Window\{[^}]*?\s(\S+?)/", res["stdout"]) or \
        re.search(r"mFocusedApp=.*?\s([A-Za-z0-9_.]+)/", res["stdout"])
    return m.group(1) if m else None


def parse_ui_nodes(xml_text):
    """Parse a uiautomator dump into [{text, desc, bounds, clickable}]. Empty list if unparseable."""
    start, end = xml_text.find("<?xml"), xml_text.rfind("</hierarchy>")
    if start < 0 or end < 0 or "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        return []
    try:
        root = ET.fromstring(xml_text[start:end + len("</hierarchy>")])
    except ET.ParseError:
        return []
    nodes = []
    for el in root.iter("node"):
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", el.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        nodes.append({
            "text": el.get("text", ""), "desc": el.get("content-desc", ""),
            "bounds": (x1, y1, x2, y2), "clickable": el.get("clickable") == "true",
        })
    return nodes


def find_ui_node(nodes, query, index=0):
    q = query.lower().strip()
    exact = [n for n in nodes if q in (n["text"].lower().strip(), n["desc"].lower().strip())]
    loose = [n for n in nodes if q in (n["text"] + " " + n["desc"]).lower()]
    pool = exact or loose
    pool = sorted(pool, key=lambda n: not n["clickable"])  # prefer clickable; stable otherwise
    return pool[index] if 0 <= index < len(pool) else None


def ui_nodes(ctx):
    res = ctx.adb(["exec-out", "uiautomator", "dump", "/dev/tty"], timeout=25)
    return parse_ui_nodes(res["stdout"]) if res["returncode"] == 0 else []


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def _v_open_app(p):
    _package(_str(p, "name"))
    _num(p, "verify_s", 0, 30, 6)


def _r_open_app(ctx, p):
    pkg = _package(p["name"])
    res = ctx.adb(["shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"])
    if res["returncode"] != 0 or "Events injected: 1" not in res["stdout"]:
        return fail(f"could not launch {pkg}", {"stderr": res["stderr"][:200]})
    verify = _num(p, "verify_s", 0, 30, 6)
    if not verify:
        return ok(f"launched {pkg}")
    end = time.monotonic() + verify
    seen = None
    while time.monotonic() < end:
        seen = foreground_package(ctx)
        if seen is None:
            return ok(f"launched {pkg} (foreground app not verifiable)")
        if seen == pkg:
            return ok(f"{pkg} in foreground")
        ctx.wait(1.0)
    return fail(f"{pkg} launched but focus is {seen}", {"foreground": seen})


def _v_force_stop(p):
    _package(_str(p, "name"))


def _r_force_stop(ctx, p):
    pkg = _package(p["name"])
    res = ctx.adb(["shell", "am", "force-stop", pkg])
    return fail(f"force-stop failed: {res['stderr'][:200]}") if res["returncode"] != 0 else ok(f"stopped {pkg}")


def _v_deep_link(p):
    url = _str(p, "url", 2000)
    if not URL_RE.match(url):
        raise TaskError("'url' must look like scheme://...")
    if p.get("package"):
        _package(_str(p, "package"))


def _r_deep_link(ctx, p):
    args = ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", gl_adb.shell_quote(p["url"])]
    if p.get("package"):
        args += ["-p", _package(p["package"])]
    res = ctx.adb(args)
    if _adb_error(res):
        return fail("intent was not delivered", {"detail": (res["stdout"] + " " + res["stderr"])[:300]})
    return ok("link opened", {"url": p["url"][:200]})


def _v_key(p):
    name = _str(p, "name").lower()
    if name not in gl_adb.KEYCODES:
        raise TaskError(f"unknown key '{name}'. Allowed: {', '.join(sorted(gl_adb.KEYCODES))}")
    _num(p, "repeat", 1, 10, 1)


def _r_key(ctx, p):
    code = gl_adb.KEYCODES[p["name"].lower()]
    for _ in range(int(_num(p, "repeat", 1, 10, 1))):
        res = ctx.adb(["shell", "input", "keyevent", code])
        if res["returncode"] != 0:
            return fail(f"keyevent failed: {res['stderr'][:200]}")
        ctx.wait(0.15)
    return ok(f"pressed {p['name']}")


def _v_tap(p):
    _num(p, "x", 0, 1, required=True)
    _num(p, "y", 0, 1, required=True)


def _r_tap(ctx, p):
    hit = gl_adb.tap_normalized(ctx.device, p["x"], p["y"])
    return ok("tapped", hit) if hit else fail("tap failed (could not read screen size or send input)")


def _v_swipe(p):
    for k in ("x1", "y1", "x2", "y2"):
        _num(p, k, 0, 1, required=True)
    _num(p, "duration_ms", 50, 3000, 300)


def _r_swipe(ctx, p):
    hit = gl_adb.swipe_normalized(ctx.device, p["x1"], p["y1"], p["x2"], p["y2"], duration_ms=int(_num(p, "duration_ms", 50, 3000, 300)))
    return ok("swiped", hit) if hit else fail("swipe failed (could not read screen size or send input)")


def _v_type(p):
    text = _str(p, "text")
    if not all(32 <= ord(c) < 127 for c in text):
        raise TaskError("'text' must be printable ASCII (adb 'input text' cannot send other characters)")


def _r_type(ctx, p):
    # `input text` treats %s as a space; quote the whole argument for the device shell.
    res = ctx.adb(["shell", "input", "text", gl_adb.shell_quote(p["text"].replace(" ", "%s"))])
    if res["returncode"] != 0:
        return fail(f"typing failed: {res['stderr'][:200]}")
    if p.get("enter"):
        ctx.adb(["shell", "input", "keyevent", gl_adb.KEYCODES["enter"]])
    return ok(f"typed {len(p['text'])} characters")


def _v_sleep(p):
    _num(p, "seconds", 0, MAX_SLEEP_S, required=True)


def _r_sleep(ctx, p):
    ctx.wait(float(p["seconds"]))
    return ok(f"slept {p['seconds']}s")


def _v_screenshot(p):
    pass


def _r_screenshot(ctx, p):
    res = gl_adb.run_adb_bytes(["exec-out", "screencap", "-p"], device=ctx.device, timeout=25)
    data = res["stdout"]
    if res["returncode"] != 0 or not data.startswith(b"\x89PNG"):
        return fail("screencap failed", {"stderr": res["stderr"][:200]})
    os.makedirs(ctx.shots_dir, exist_ok=True)
    name = SAFE_NAME_RE.sub("_", f"{ctx.task_id}-{ctx.device}") + ".png"
    path = os.path.join(ctx.shots_dir, name)
    with open(path, "wb") as f:
        f.write(data)
    return ok("screenshot saved", {"path": path, "bytes": len(data)})


def _v_ui_text(p):
    _str(p, "text", 200)
    _num(p, "timeout", 0, 120, None)
    _num(p, "index", 0, 50, 0)


def _ui_text_action(ctx, p, click, default_timeout):
    timeout = _num(p, "timeout", 0, 120, default_timeout)
    index = int(_num(p, "index", 0, 50, 0))
    absent = bool(p.get("absent"))
    end = time.monotonic() + timeout
    while True:
        nodes = ui_nodes(ctx)
        node = find_ui_node(nodes, p["text"], index)
        if absent:
            if node is None and nodes:
                return ok(f"'{p['text']}' is not on screen")
        elif node:
            if not click:
                return ok(f"'{p['text']}' is on screen")
            x1, y1, x2, y2 = node["bounds"]
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            res = ctx.adb(["shell", "input", "tap", str(cx), str(cy)])
            if res["returncode"] != 0:
                return fail(f"tap failed: {res['stderr'][:200]}")
            return ok(f"clicked '{p['text']}'", {"coords": [cx, cy]})
        if time.monotonic() >= end:
            what = "still on screen" if absent else "not found on screen"
            return fail(f"'{p['text']}' {what}", {"nodes_seen": len(nodes)})
        ctx.wait(1.5)


def _r_click_text(ctx, p):
    return _ui_text_action(ctx, p, click=True, default_timeout=0)


def _r_wait_text(ctx, p):
    return _ui_text_action(ctx, p, click=bool(p.get("click")), default_timeout=15)


def _r_assert_text(ctx, p):
    return _ui_text_action(ctx, p, click=False, default_timeout=0)


def _v_check(p):
    pass


def _r_check(ctx, p):
    state = gl_adb.get_state(ctx.device)
    if state != "device":
        return fail(f"device state: {state}")
    model = ctx.adb(["shell", "getprop", "ro.product.model"], timeout=8)["stdout"]
    return ok("device online", {"model": model[:60], "foreground": foreground_package(ctx)})


def _v_flow(p):
    steps = p.get("steps")
    if not isinstance(steps, list) or not steps:
        raise TaskError("'steps' must be a non-empty list")
    if len(steps) > MAX_STEPS:
        raise TaskError(f"at most {MAX_STEPS} steps")
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise TaskError(f"step {i} must be an object")
        act = str(step.get("action") or "").lower()
        if act not in ACTIONS or act == "flow":
            raise TaskError(f"step {i}: action '{act}' not allowed in a flow")
        try:
            ACTIONS[act]["validate"](step)
        except TaskError as e:
            raise TaskError(f"step {i} ({act}): {e}")


def _r_flow(ctx, p):
    results = []
    for i, step in enumerate(p["steps"], 1):
        act = step["action"].lower()
        res = ACTIONS[act]["run"](ctx, step)
        results.append({"step": i, "action": act, "status": res["status"], "message": res["message"]})
        if res["status"] != "success" and not p.get("continue_on_error"):
            return fail(f"step {i} ({act}) failed: {res['message']}", results)
    failed = [r for r in results if r["status"] != "success"]
    return fail(f"{len(failed)} step(s) failed", results) if failed else ok(f"{len(results)} steps completed", results)


ACTIONS = {
    "open-app": {"validate": _v_open_app, "run": _r_open_app},
    "force-stop": {"validate": _v_force_stop, "run": _r_force_stop},
    "deep-link": {"validate": _v_deep_link, "run": _r_deep_link},
    "key": {"validate": _v_key, "run": _r_key},
    "tap": {"validate": _v_tap, "run": _r_tap},
    "swipe": {"validate": _v_swipe, "run": _r_swipe},
    "type": {"validate": _v_type, "run": _r_type},
    "sleep": {"validate": _v_sleep, "run": _r_sleep},
    "screenshot": {"validate": _v_screenshot, "run": _r_screenshot},
    "click-text": {"validate": _v_ui_text, "run": _r_click_text},
    "wait-text": {"validate": _v_ui_text, "run": _r_wait_text},
    "assert-text": {"validate": _v_ui_text, "run": _r_assert_text},
    "check-device": {"validate": _v_check, "run": _r_check},
    "flow": {"validate": _v_flow, "run": _r_flow},
}


def load_tasks_file(path):
    """Read tasks from .json (a list, or {"tasks": [...]}) or .csv (columns: task_id,device,action,params)."""
    if os.path.getsize(path) > 5 * 1024 * 1024:
        raise TaskError("task file larger than 5 MB")
    if path.lower().endswith(".csv"):
        import csv
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [dict(row) for row in csv.DictReader(f)]
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("tasks")
    if not isinstance(data, list):
        raise TaskError("task file must be a JSON list or an object with a 'tasks' list")
    return data


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def execute_task(device, task, run_id, retries, task_timeout, shots_dir, reporter):
    """Run one task with retries and report the final outcome. Never raises."""
    started = time.monotonic()
    attempts, result, status = 0, None, "failed"
    for attempt in range(1, retries + 2):
        attempts = attempt
        deadline = time.monotonic() + task_timeout
        ctx = Ctx(device, task["task_id"], run_id, deadline, shots_dir)
        try:
            state = gl_adb.get_state(device)
            if state != "device":
                time.sleep(2)
                state = gl_adb.get_state(device)
            if state != "device":
                result, status = fail(f"device offline ({state})"), "offline"
            else:
                result = ACTIONS[task["action"]]["run"](ctx, task["params"])
                status = result["status"]
        except TaskError as e:
            result, status = fail(str(e)), "error"
            break  # invalid task: retrying cannot help
        except TaskTimeout as e:
            result, status = fail(str(e)), "timeout"
            break
        except Exception as e:  # never let one task kill the worker
            result, status = fail(f"{type(e).__name__}: {e}"), "error"
        if status == "success":
            break
        if attempt <= retries:
            reporter.event("warning", f"attempt {attempt} {status}: {result['message']}; retrying", device, task["task_id"])
            time.sleep(min(2 ** attempt, 10))
    reporter.report(task, status, attempts, time.monotonic() - started, result["message"], result.get("output"))
    return status


def run_bulk(tasks=None, client=None, devices=None, retries=1, max_workers=8, max_tasks=None,
             task_timeout=120, task_delay=0.0, dry_run=False, log_dir=None, run_id=None):
    """Run tasks on `devices` in parallel. `tasks` = local list; otherwise tasks are claimed from `client`'s sheet."""
    run_id = run_id or f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    started = gl_sheets.now_iso()
    local_mode = tasks is not None
    if not local_mode and not client:
        return {"status": "error", "message": "No task source: pass --tasks FILE or set GEELARK_SHEETS_URL / GEELARK_SHEETS_SECRET."}
    if dry_run and not local_mode:
        return {"status": "error", "message": "--dry-run needs --tasks FILE (claiming from the sheet would modify it)."}

    reporter = gl_sheets.Reporter(run_id, None if dry_run else client, log_dir)
    shots_dir = os.path.join(reporter.log_dir, "shots", run_id)

    # Validate local tasks up front; invalid ones are reported, not silently dropped.
    queue, invalid = [], []
    if local_mode:
        for raw in tasks:
            try:
                queue.append(normalize_task(raw))
            except TaskError as e:
                invalid.append((raw, str(e)))
    if dry_run:
        return {"status": "success", "dry_run": True, "run_id": run_id,
                "valid": [{"task_id": t["task_id"], "device": t["device"] or "any", "action": t["action"]} for t in queue],
                "invalid": [{"task_id": str((r or {}).get("task_id", "")) if isinstance(r, dict) else "", "error": e} for r, e in invalid]}

    if client and not local_mode:
        flushed = gl_sheets.flush_spool(client, log_dir)
        if flushed["sent"]:
            reporter.event("info", f"replayed {flushed['sent']} spooled report(s) from an earlier run")

    online = devices or gl_adb.list_devices(use_cache=False)
    workers = [d for d in online if gl_adb._SERIAL_RE.match(d)][:max(1, max_workers)]
    if not workers:
        reporter.event("error", "no ADB devices available")
        reporter.summary(started, [], 0, notes="no devices")
        return {"status": "error", "message": "No ADB devices found (run `adb devices`).", "run_id": run_id, "log": reporter.log_path}
    reporter.event("info", f"run started on {len(workers)} device(s): {', '.join(workers)}")

    for raw, err in invalid:
        reporter.report({"task_id": str((raw or {}).get("task_id", "")) if isinstance(raw, dict) else "",
                         "device": "", "action": str((raw or {}).get("action", "")) if isinstance(raw, dict) else ""},
                        "error", 0, 0, f"invalid task: {err}")

    lock = threading.Lock()
    budget = {"left": max_tasks if max_tasks else float("inf"), "total": len(invalid)}
    stop = threading.Event()

    def reserve():
        with lock:
            if budget["left"] <= 0:
                return False
            budget["left"] -= 1
            return True

    def give_back():
        with lock:
            budget["left"] += 1

    def next_local(device):
        with lock:
            for i, t in enumerate(queue):
                if t["device"] in ("", device):
                    return queue.pop(i)
        return None

    def next_sheet(device):
        try:
            got = client.claim(device, limit=1)
        except gl_sheets.SheetsError as e:
            raise RuntimeError(str(e))
        if not got:
            return None
        try:
            return normalize_task(dict(got[0], device=got[0].get("device") or ""))
        except TaskError as e:
            raw = got[0]
            reporter.report({"task_id": raw.get("task_id", ""), "device": device, "action": raw.get("action", "")},
                            "error", 0, 0, f"invalid task: {e}")
            with lock:
                budget["total"] += 1
            return "invalid"

    def worker(device):
        failures = 0
        while not stop.is_set():
            if not reserve():
                return
            try:
                task = next_local(device) if local_mode else next_sheet(device)
            except Exception as e:
                give_back()
                failures += 1
                reporter.event("error", f"could not fetch tasks: {e}", device)
                if failures >= 3:
                    return
                time.sleep(2 * failures)
                continue
            failures = 0
            if task is None:
                give_back()
                return
            if task == "invalid":
                continue
            with lock:
                budget["total"] += 1
            execute_task(device, task, run_id, retries, task_timeout, shots_dir, reporter)
            if task_delay:
                time.sleep(task_delay)

    threads = [threading.Thread(target=worker, args=(d,), name=f"bulk-{d}", daemon=True) for d in workers]
    interrupted = False
    for t in threads:
        t.start()
    try:
        for t in threads:
            while t.is_alive():
                t.join(0.5)
    except KeyboardInterrupt:
        interrupted = True
        stop.set()
        reporter.event("warning", "interrupted; finishing in-flight tasks")
        for t in threads:
            t.join(30)

    # Local tasks nobody could run (their device is not connected) are reported, not dropped.
    for t in queue:
        reporter.report(t, "skipped", 0, 0, f"device '{t['device']}' not connected or run ended before it was reached")
        budget["total"] += 1

    notes = "interrupted" if interrupted else ""
    summary = reporter.summary(started, workers, budget["total"], notes)
    return {"status": "success", "run_id": run_id, "workers": workers, "total": summary["total"],
            "success": summary["success"], "failed": summary["failed"], "other": summary["other"],
            "log": reporter.log_path, "sheet_write_failures": reporter.sheet_failures,
            "interrupted": interrupted}
