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
import gl_cloudadb
import gl_sheets
import gl_transport

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
    if gl_cloudadb.is_cloud_device(task["device"]):
        if not gl_cloudadb.CLOUD_DEVICE_RE.match(task["device"]):
            raise TaskError(f"invalid cloud device '{task['device']}' (expected cloud:<phone_id>)")
    elif task["device"] and not gl_adb._SERIAL_RE.match(task["device"]):
        raise TaskError(f"invalid device serial '{task['device']}'")
    validate_action(action, task["params"])
    return task


def validate_action(action, params, depth=0):
    ACTIONS[action]["validate"](params)


# ---------------------------------------------------------------------------
# Execution context
# ---------------------------------------------------------------------------
class Ctx:
    """Per-task context. `device` is an ADB serial (str) or a transport object (ApiTransport / AdbTransport)."""

    def __init__(self, device, task_id, run_id, deadline, shots_dir):
        self.transport = device if hasattr(device, "run") else gl_transport.AdbTransport(device)
        self.device = self.transport.label
        self.task_id = task_id
        self.run_id = run_id
        self.deadline = deadline
        self.shots_dir = shots_dir
        self._screen = None
        self._shots = 0

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
        return self.transport.run(args, **kw)

    def state(self):
        return self.transport.state()

    def screen_size(self):
        if self._screen is None:
            res = self.adb(["shell", "wm", "size"], timeout=10)
            sizes = re.findall(r"(\d+)x(\d+)", res["stdout"]) if res["returncode"] == 0 else []
            if sizes:
                self._screen = (int(sizes[-1][0]), int(sizes[-1][1]))   # an "Override size" line, when present, is last
        return self._screen

    def tap_normalized(self, nx, ny):
        size = self.screen_size()
        if not size:
            return None
        x, y = int(float(nx) * size[0]), int(float(ny) * size[1])
        res = self.adb(["shell", "input", "tap", x, y])
        return {"coords": [x, y]} if res["returncode"] == 0 else None

    def swipe_normalized(self, x1, y1, x2, y2, duration_ms=250):
        size = self.screen_size()
        if not size:
            return None
        w, h = size
        pts = [int(float(x1) * w), int(float(y1) * h), int(float(x2) * w), int(float(y2) * h)]
        res = self.adb(["shell", "input", "swipe", *pts, int(duration_ms)])
        return {"from": pts[:2], "to": pts[2:]} if res["returncode"] == 0 else None


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
    res = ctx.adb(["shell", "dumpsys", "window", "|", "grep", "-E", gl_adb.shell_quote("mCurrentFocus|mFocusedApp")], timeout=20)
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


# ---------------------------------------------------------------------------
# description-link: open a YouTube video, open its description, tap one link, screenshot, go back.
# Safe by default: every tap needs positive confirmation first, and when it cannot get it the task fails without tapping.
# A pre-roll ad covers the title area and has its own "More info" / "Learn more" buttons, so "ad is over" is never assumed
# from an unreadable screen (the UI dump fails on a busy watch page).
# ---------------------------------------------------------------------------
YOUTUBE_URL_RE = re.compile(r"^https://(www\.|m\.)?(youtube\.com|youtu\.be)/\S+$")
AD_MARKERS = ("sponsored", "skip ad", "visit advertiser", "visit site", "my ad center", "like ad", "share ad",
              "close ad panel", "more info", "book now", "learn more")
SKIP_LABELS = ("skip ad", "skip ads", "skip")


def _desc_link_args(p):
    url, text = p.get("url"), p.get("link_text")
    if p.get("spec") and not (url and text):
        parts = [x.strip() for x in str(p["spec"]).split("|")]   # "video link | link text [| tap height]" (one sheet cell)
        url, text = parts[0], (parts[1] if len(parts) > 1 else "")
    return url, (str(text).strip() if text else text)


def _desc_tap(p):
    """Where to tap the title row, as fractions (x, y) of the screen. YouTube versions differ: on most phones the row sits at
    about (0.636, 0.371); on a newer layout "more" is further right and lower (about 0.76, 0.39). An optional third field of
    `spec` sets it for one run: a height (`... | 0.39`) or `x,y` (`... | 0.76,0.39`); otherwise the `more_x` / `more_y` params."""
    parts = [x.strip() for x in str(p.get("spec") or "").split("|")]
    x, y = _num(p, "more_x", 0, 1, 0.636), _num(p, "more_y", 0, 1, 0.371)
    if len(parts) > 2 and parts[2]:
        nums = [v.strip() for v in parts[2].split(",")]
        try:
            vals = [float(v) for v in nums]
        except ValueError:
            vals = []
        if len(vals) not in (1, 2):
            raise TaskError("the third field of the value (tap position) must be a height such as 0.39, or x,y such as 0.76,0.39")
        if len(vals) == 2:
            x = vals[0]
        y = vals[-1]
        if not (0.2 <= y <= 0.6):
            raise TaskError("the tap height must be between 0.2 and 0.6 of the screen height")
        if not (0.1 <= x <= 0.95):
            raise TaskError("the tap x must be between 0.1 and 0.95 of the screen width")
    return x, y


def _desc_row_y(p):
    return _desc_tap(p)[1]


def _v_description_link(p):
    url, text = _desc_link_args(p)
    if not url or not YOUTUBE_URL_RE.match(str(url)):
        raise TaskError("needs a YouTube video link (https://youtube.com/... or https://youtu.be/...)")
    if not text or not (3 <= len(text) <= 200):
        raise TaskError("needs the link text to look for in the description (3-200 characters): 'link_text', or 'spec' as 'video link | link text'")
    _num(p, "ad_wait_s", 20, 180, 90)
    _num(p, "ad_blind_wait_s", 15, 120, 50)
    _num(p, "settle_s", 3, 30, 12)
    _desc_tap(p)


def _label(node):
    return (node["text"] or node["desc"]).strip()


AD_ZONE_BOTTOM = 530      # px on a 720x1440 screen: a pre-roll ad's controls sit in the player and the panel under it


def _ad_on_screen(nodes):
    """A pre-roll ad (or an ad panel) is on screen. Only the top of the screen counts: an in-feed ad further down the page
    (below the comments) has its own "Sponsored" / "Learn more" but does not cover the title row."""
    return any(m in (n["text"] + " " + n["desc"]).lower()
               for n in nodes if n["bounds"][1] < AD_ZONE_BOTTOM for m in AD_MARKERS)


def _tap_center(ctx, node):
    x1, y1, x2, y2 = node["bounds"]
    return ctx.adb(["shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2)])["returncode"] == 0


def _r_description_link(ctx, p):
    url, text = _desc_link_args(p)
    ad_wait = _num(p, "ad_wait_s", 20, 180, 90)
    blind_wait = _num(p, "ad_blind_wait_s", 15, 120, 50)
    settle = _num(p, "settle_s", 3, 30, 12)
    shots = []

    def shot():
        res = _r_screenshot(ctx, {"blockers": False})
        if res["status"] == "success":
            shots.append(res["output"]["path"])

    res = ctx.adb(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", gl_adb.shell_quote(url),
                   "-p", "com.google.android.youtube"])
    if _adb_error(res):
        return fail("could not open the video", {"detail": (res["stdout"] + " " + res["stderr"])[:300]})

    # 1) wait for any ad to finish. An ad counts as over only after 3 reads in a row without ad controls, and only once an
    #    ad was seen, or `blind_wait` seconds passed without seeing one. That second rule matters: an ad screen is not always
    #    readable (seen on a newer YouTube layout), so "no ad seen" is not proof of "no ad"; the fallback must outlast a
    #    typical pre-roll (up to ~30 s unskippable). Skip is tapped only on an exact "Skip" label.
    started = time.monotonic()
    end = started + ad_wait
    seen_ad, clear, ad_last = False, 0, False
    tries = getattr(ctx.transport, "ui_tries", None)
    if tries is not None:
        ctx.transport.ui_tries = 1       # polling: one attempt per read (a failed read on a busy page is slow)
    try:
        while True:
            nodes = ui_nodes(ctx)
            ad_last = _ad_on_screen(nodes)
            if ad_last:
                seen_ad, clear = True, 0
                skip = next((n for n in nodes if _label(n).lower() in SKIP_LABELS), None)
                if skip:
                    _tap_center(ctx, skip)
            else:
                clear += 1
            if clear >= 3 and (seen_ad or time.monotonic() - started >= blind_wait):
                break
            if time.monotonic() >= end:
                shot()
                why = "an ad was still on screen" if ad_last else "could not confirm the ad had ended (the screen was not readable)"
                return fail(f"{why} after {int(ad_wait)}s; nothing was tapped", {"screenshots": shots, "ad_seen": seen_ad})
            ctx.wait(2)
    finally:
        if tries is not None:
            ctx.transport.ui_tries = tries

    # 2) never tap outside the YouTube app
    fg = foreground_package(ctx) or ""
    if not fg.startswith("com.google.android.youtube"):
        shot()
        return fail(f"YouTube is not in the foreground ({fg or 'unknown'}); nothing was tapped", {"screenshots": shots})

    # 3) one tap on the title row opens the description
    if not ctx.tap_normalized(*_desc_tap(p)):
        return fail("could not tap the description row")
    ctx.wait(3)

    # 4) confirm the description really opened (and an ad panel did not) before touching anything else
    confirmed, ad_opened, wrong_sheet, nodes = False, False, False, []
    for _ in range(3):
        nodes = ui_nodes(ctx)
        if _ad_on_screen(nodes):
            ad_opened = True
            break
        if any(_label(n).lower() in ("copy link", "share") for n in nodes) and                 not any(_label(n).lower().startswith("description") for n in nodes):
            wrong_sheet = True       # the tap landed on Share (or similar); close it, never touch anything in it
            break
        if any(_label(n).lower().startswith("description") for n in nodes) or \
                any(text.lower() in (n["text"] + " " + n["desc"]).lower() for n in nodes):
            confirmed = True
            break
        ctx.wait(2)
    shot()
    if wrong_sheet:
        ctx.adb(["shell", "input", "keyevent", gl_adb.KEYCODES["back"]])
        return fail("the tap opened the Share sheet, not the description (closed it); set the tap position in the third field, e.g. 0.76,0.39",
                    {"screenshots": shots})
    if ad_opened:
        return fail("an ad panel opened instead of the description; nothing else was tapped", {"screenshots": shots})
    if not confirmed:
        return fail("could not confirm the description opened; the link was not tapped", {"screenshots": shots})

    # 5) tap the link by its text
    link = next((n for n in sorted(nodes, key=lambda n: not n["clickable"])
                 if text.lower() in (n["text"] + " " + n["desc"]).lower()), None)
    if link is None:
        return fail(f"link text '{text[:60]}' was not found in the description", {"screenshots": shots})
    if not _tap_center(ctx, link):
        return fail("could not tap the link", {"screenshots": shots})
    ctx.wait(settle)
    shot()
    for _ in range(2):                    # leave the link page, then the description
        ctx.adb(["shell", "input", "keyevent", gl_adb.KEYCODES["back"]])
        ctx.wait(1)
    return ok("opened the description link", {"link_text": text[:80], "ad_seen": seen_ad, "screenshots": shots})


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
    hit = ctx.tap_normalized(p["x"], p["y"])
    return ok("tapped", hit) if hit else fail("tap failed (could not read screen size or send input)")


def _v_swipe(p):
    for k in ("x1", "y1", "x2", "y2"):
        _num(p, k, 0, 1, required=True)
    _num(p, "duration_ms", 50, 3000, 300)


def _r_swipe(ctx, p):
    hit = ctx.swipe_normalized(p["x1"], p["y1"], p["x2"], p["y2"], duration_ms=int(_num(p, "duration_ms", 50, 3000, 300)))
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


# ---------------------------------------------------------------------------
# Blocker detection. A task can "succeed" while the phone shows a wall: a bot check, "Video unavailable", Chrome's first-run
# page. Those screens are static, so the UI dump can usually read them; a healthy playing video cannot be read at all.
# So the rule is: a blocker is reported only on positive evidence (a known phrase on a readable screen). An unreadable
# screen is never treated as a blocker, and never as proof that all is well either.
# ---------------------------------------------------------------------------
BLOCKERS = (
    ("bot check", ("not a bot", "unusual traffic", "i'm not a robot", "captcha", "verify you are human", "verify you're human")),
    ("video unavailable", ("video unavailable", "this content isn't available", "this video isn't available",
                           "video isn't available", "this video is unavailable", "content unavailable")),
    ("Chrome first-run screen", ("welcome to chrome", "accept & continue")),
    ("Google verification prompt", ("verify it's you", "verify your identity", "verify your phone number",
                                    "get a verification code", "couldn't sign you in")),
    ("account problem", ("account has been disabled", "account has been suspended", "account has been terminated",
                         "account is disabled")),
    ("age check", ("confirm your age", "age-restricted")),
    ("app error", ("something went wrong", "an error occurred", "playback error", "can't play this video")),
    ("no connection", ("no internet connection", "you're offline", "check your connection")),
)


def find_blocker(nodes):
    """(kind, text on screen) for the first blocker phrase found among UI nodes, else None."""
    for node in nodes:
        label = (node["text"] + " " + node["desc"]).lower().replace("\u2019", "'").replace("\u2018", "'")
        if not label.strip():
            continue
        for kind, phrases in BLOCKERS:
            if any(ph in label for ph in phrases):
                return kind, (node["text"] or node["desc"]).strip()[:80]
    return None


def _read_screen_once(ctx):
    """One quick read of the screen (a failed read on a busy page is slow, so no retries). [] when it cannot be read."""
    tries = getattr(ctx.transport, "ui_tries", None)
    if tries is not None:
        ctx.transport.ui_tries = 1
    try:
        return ui_nodes(ctx)
    finally:
        if tries is not None:
            ctx.transport.ui_tries = tries


def _v_screenshot(p):
    if "blockers" in p and not isinstance(p["blockers"], bool):
        raise TaskError("'blockers' must be true or false")


def _r_screenshot(ctx, p):
    res = ctx.transport.screenshot()
    data = res["stdout"] or b""
    ext = "png" if data.startswith(b"\x89PNG") else ("jpg" if data.startswith(b"\xff\xd8\xff") else None)
    if res["returncode"] != 0 or not ext:
        return fail("screenshot failed", {"stderr": str(res["stderr"])[:200]})
    os.makedirs(ctx.shots_dir, exist_ok=True)
    ctx._shots += 1
    suffix = "" if ctx._shots == 1 else f"-{ctx._shots}"   # a flow can take several; do not overwrite the first
    name = SAFE_NAME_RE.sub("_", f"{ctx.task_id}-{ctx.device}") + suffix + "." + ext
    path = os.path.join(ctx.shots_dir, name)
    with open(path, "wb") as f:
        f.write(data)
    host = getattr(ctx.transport, "last_download_host", None)
    out = {"path": path, "bytes": len(data), **({"download_host": host} if host else {})}
    if p.get("blockers", True):                      # a screenshot that shows a wall is a failed task, not a success
        hit = find_blocker(_read_screen_once(ctx))
        if hit:
            out["blocker"] = hit[0]
            return fail(f"screenshot saved, but the screen shows a blocker: {hit[0]} ({hit[1]!r})", out)
    return ok("screenshot saved", out)


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
            if p.get("optional") and not absent:
                return ok(f"'{p['text']}' not shown (optional, skipped)")
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
    state = ctx.state()
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
    "description-link": {"validate": _v_description_link, "run": _r_description_link},
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
# Run settings: explicit CLI flag > sheet Settings tab > built-in default
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS = {"retries": 1, "max_workers": 8, "max_cloud_phones": 2, "task_timeout": 120.0,
                    "task_delay": 0.0, "max_runtime": None, "on_failure": "continue",
                    "max_phone_minutes": 8.0, "daily_phone_minutes": 120.0}


def _as_int(v):
    return int(float(v))


def _minutes_to_s(v):
    return float(v) * 60


# run-setting -> (sheet key, parser, min, max)
_SHEET_SETTINGS = {
    "retries": ("retries", _as_int, 0, 5),
    "max_cloud_phones": ("max_cloud_phones", _as_int, 1, 10),
    "task_timeout": ("task_timeout_s", float, 10, 1800),
    "task_delay": ("task_delay_s", float, 0, 600),
    "max_runtime": ("max_runtime_min", _minutes_to_s, 60, 24 * 3600),
    "max_phone_minutes": ("max_phone_minutes", float, 1, 240),
    "daily_phone_minutes": ("daily_phone_minutes", float, 1, 10000),
}


def resolve_settings(cli, sheet):
    """Merge settings. Returns (settings, ignored) where `ignored` lists sheet values that were invalid or out of range."""
    out, ignored = dict(DEFAULT_SETTINGS), []
    for key, default in DEFAULT_SETTINGS.items():
        if cli.get(key) is not None:
            out[key] = cli[key]
            continue
        if key == "on_failure":
            raw = str(sheet.get("on_failure", "")).strip().lower()
            if raw in ("continue", "stop"):
                out[key] = raw
            elif raw:
                ignored.append(f"on_failure={raw!r}")
            continue
        spec = _SHEET_SETTINGS.get(key)
        raw = sheet.get(spec[0]) if spec else None
        if raw in (None, ""):
            continue
        try:
            value = spec[1](raw)
        except (TypeError, ValueError):
            ignored.append(f"{spec[0]}={raw!r}")
            continue
        if not (spec[2] <= value <= spec[3]):
            ignored.append(f"{spec[0]}={raw!r} (allowed {spec[2]}-{spec[3]})")
            continue
        out[key] = value
    return out, ignored


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def _day_file(log_dir):
    return os.path.join(log_dir, ".phone_minutes.json")


def daily_used_s(log_dir, today=None):
    """Cloud phone seconds already used today (by earlier runs and waves in this log directory)."""
    today = today or datetime.now().date().isoformat()
    try:
        with open(_day_file(log_dir), encoding="utf-8") as f:
            data = json.load(f)
        return float(data["seconds"]) if data.get("date") == today else 0.0
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


def add_daily_used_s(log_dir, seconds, today=None):
    today = today or datetime.now().date().isoformat()
    total = daily_used_s(log_dir, today) + max(0.0, seconds)
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(_day_file(log_dir), "w", encoding="utf-8") as f:
            json.dump({"date": today, "seconds": round(total, 1)}, f)
    except OSError:
        pass
    return total


def execute_task(device, task, run_id, retries, task_timeout, shots_dir, reporter):
    """Run one task with retries and report the final outcome. Never raises."""
    started = time.monotonic()
    attempts, result, status = 0, None, "failed"
    for attempt in range(1, retries + 2):
        attempts = attempt
        deadline = time.monotonic() + task_timeout
        ctx = Ctx(device, task["task_id"], run_id, deadline, shots_dir)
        try:
            state = ctx.state()
            if state != "device":
                time.sleep(2)
                state = ctx.state()
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
            reporter.event("warning", f"attempt {attempt} {status}: {result['message']}; retrying", getattr(device, "label", device), task["task_id"])
            time.sleep(min(2 ** attempt, 10))
    reporter.report(task, status, attempts, time.monotonic() - started, result["message"], result.get("output"))
    return status


def run_bulk(tasks=None, client=None, devices=None, retries=1, max_workers=8, max_tasks=None,
             task_timeout=120, task_delay=0.0, dry_run=False, log_dir=None, run_id=None,
             cloud=False, max_cloud_phones=2, cloud_up_timeout=180,
             only_cloud=False, max_runtime=None, on_failure="continue", probe=False, transport="adb",
             max_phone_minutes=None, daily_phone_minutes=None):
    """Run tasks in parallel, one worker per phone. `tasks` = local list; otherwise tasks are claimed from `client`'s sheet.

    Local ADB phones are addressed by serial. GeeLark cloud phones are addressed as `cloud:<phone_id>`; they are only
    started when `cloud=True` (they bill per minute), only take tasks addressed to them, and are always stopped.

    Unattended use: `only_cloud=True` ignores local ADB phones and tasks without a `cloud:` device. A sheet run with
    nothing to do returns {"status": "idle"} without writing anything, so polling it every few minutes is free.
    `max_runtime` (seconds) stops *new* tasks from starting; `on_failure="stop"` skips a phone's remaining tasks after one fails.
    Spend caps (minutes, None = off): `max_phone_minutes` stops one cloud phone taking new tasks once it has been up that long;
    `daily_phone_minutes` stops every phone from taking new work, and new phones from starting, once the day's total
    (this run plus earlier runs today) reaches it. Tasks left over stay pending."""
    if transport not in ("adb", "api"):
        return {"status": "error", "message": "transport must be 'adb' or 'api'"}
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
        cloud_targets = sorted({t["device"] for t in queue if gl_cloudadb.is_cloud_device(t["device"])})
        return {"status": "success", "dry_run": True, "run_id": run_id,
                "valid": [{"task_id": t["task_id"], "device": t["device"] or "any", "action": t["action"]} for t in queue],
                "invalid": [{"task_id": str((r or {}).get("task_id", "")) if isinstance(r, dict) else "", "error": e} for r, e in invalid],
                "cloud_phones_needed": cloud_targets}

    if client and not local_mode:
        flushed = gl_sheets.flush_spool(client, log_dir)
        if flushed["sent"]:
            reporter.event("info", f"replayed {flushed['sent']} spooled report(s) from an earlier run")
    if only_cloud:
        cloud = True
    pending = {"devices": [], "blank": 0}
    if not local_mode:
        try:
            pending = client.pending_summary()
        except gl_sheets.SheetsError as e:
            return {"status": "error", "message": f"could not read the task queue: {e}", "run_id": run_id}
        cloud_pending = [d for d in pending["devices"] if gl_cloudadb.CLOUD_DEVICE_RE.match(d)]
        relevant = cloud_pending if only_cloud else pending["devices"] + (["*"] if pending["blank"] else [])
        if not relevant:
            return {"status": "idle", "run_id": run_id, "message": "no waiting tasks for this runner",
                    "waiting_without_cloud_device": pending["blank"] if only_cloud else 0}
        if probe:  # cheap "is there anything to do?" check for schedulers: needs only the sheet, starts nothing
            return {"status": "work", "run_id": run_id, "waiting_devices": relevant}
    leftovers = gl_cloudadb.leftover_phones(reporter.log_dir)
    if leftovers:
        reporter.event("warning", f"cloud phone(s) from an interrupted run may still be billing: {', '.join(leftovers)}. "
                                  "Run `bulk-cloud-stop` to stop them.")

    # Workers: (claim name, adb serial). Cloud phones get their serial only after they have been started.
    online = [] if only_cloud else (devices or gl_adb.list_devices(use_cache=False))
    local_workers = [(d, d) for d in online if gl_adb._SERIAL_RE.match(d) and not gl_cloudadb.is_cloud_device(d)][:max(1, max_workers)]

    wanted_cloud = set()
    try:
        if local_mode:
            wanted_cloud = {t["device"] for t in queue}
        else:
            wanted_cloud = set(pending["devices"])
    except gl_sheets.SheetsError as e:
        reporter.event("error", f"could not read pending devices: {e}")
    wanted_cloud = sorted(d for d in wanted_cloud if gl_cloudadb.CLOUD_DEVICE_RE.match(d))
    cloud_workers = []
    if wanted_cloud and not cloud:
        reporter.event("info", f"{len(wanted_cloud)} cloud phone(s) have waiting tasks ({', '.join(wanted_cloud)}); "
                               "not started. Re-run with --cloud to start them (cloud phones bill per minute).")
    elif wanted_cloud:
        cloud_workers = [(d, None) for d in wanted_cloud[:max(0, max_cloud_phones)]]
        if len(wanted_cloud) > len(cloud_workers):
            reporter.event("warning", f"cloud phone limit {max_cloud_phones} reached; left pending: {', '.join(wanted_cloud[len(cloud_workers):])}")

    workers = local_workers + cloud_workers
    if not workers:
        reporter.event("error", "no ADB devices available")
        reporter.summary(started, [], 0, notes="no devices")
        return {"status": "error", "message": "No ADB devices found (run `adb devices`).", "run_id": run_id, "log": reporter.log_path}
    reporter.event("info", f"run started on {len(workers)} phone(s): {', '.join(n for n, _ in workers)}")

    for raw, err in invalid:
        reporter.report({"task_id": str((raw or {}).get("task_id", "")) if isinstance(raw, dict) else "",
                         "device": "", "action": str((raw or {}).get("action", "")) if isinstance(raw, dict) else ""},
                        "error", 0, 0, f"invalid task: {err}")

    # cloud phones are started/stopped over ADB (via the cloud-adb skill) or purely over GeeLark's HTTPS API
    up_fn = gl_transport.cloud_up if transport == "api" else gl_cloudadb.cloud_up
    down_fn = gl_transport.cloud_down if transport == "api" else gl_cloudadb.cloud_down

    lock = threading.Lock()
    deadline = (time.monotonic() + max_runtime) if max_runtime else None
    limit_logged = {"done": False}
    budget = {"left": max_tasks if max_tasks else float("inf"), "total": len(invalid)}
    stop = threading.Event()
    cloud_state = {"started": set(), "stopped": set(), "billed_s": 0.0, "stop_failures": [], "active": {}}
    phone_cap_s = max_phone_minutes * 60 if max_phone_minutes else None
    daily_cap_s = daily_phone_minutes * 60 if daily_phone_minutes else None
    daily_prior_s = daily_used_s(reporter.log_dir) if daily_cap_s else 0.0
    cap_hit = {"phone": set(), "daily": False}

    def daily_spent_s():
        with lock:
            now = time.monotonic()
            return daily_prior_s + cloud_state["billed_s"] + sum(now - t0 for t0 in cloud_state["active"].values())

    def cap_reached(name, started_at):
        """Why this cloud phone should stop taking work, or None. Logged once per phone / once per run."""
        if started_at is None:
            return None
        if phone_cap_s and time.monotonic() - started_at > phone_cap_s:
            with lock:
                first = name not in cap_hit["phone"]
                cap_hit["phone"].add(name)
            if first:
                reporter.event("warning", f"per-phone cap ({max_phone_minutes:g} min) reached; no new tasks on this phone, "
                                          "remaining tasks stay pending", name)
            return "phone"
        if daily_cap_s and daily_spent_s() >= daily_cap_s:
            with lock:
                first = not cap_hit["daily"]
                cap_hit["daily"] = True
            if first:
                reporter.event("warning", f"daily cap ({daily_phone_minutes:g} phone-minutes) reached; no new work or phones "
                                          "will start, remaining tasks stay pending")
            return "daily"
        return None

    def reserve():
        with lock:
            if budget["left"] <= 0:
                return False
            budget["left"] -= 1
            return True

    def give_back():
        with lock:
            budget["left"] += 1

    def next_local(name, exact):
        with lock:
            for i, t in enumerate(queue):
                if t["device"] == name or (t["device"] == "" and not exact):
                    return queue.pop(i)
        return None

    def next_sheet(name, exact):
        try:
            got = client.claim(name, limit=1, exact=exact)
        except gl_sheets.SheetsError as e:
            raise RuntimeError(str(e))
        if not got:
            return None
        try:
            return normalize_task(dict(got[0], device=got[0].get("device") or ""))
        except TaskError as e:
            raw = got[0]
            reporter.report({"task_id": raw.get("task_id", ""), "device": name, "action": raw.get("action", "")},
                            "error", 0, 0, f"invalid task: {e}")
            with lock:
                budget["total"] += 1
            return "invalid"

    def work(name, serial, exact, started_at=None):
        """Take tasks for phone `name` one at a time and run them over `serial` until none are left."""
        failures = 0
        phone_failed = False
        while not stop.is_set():
            if cap_reached(name, started_at):
                return
            if deadline and time.monotonic() > deadline:
                with lock:
                    first = not limit_logged["done"]
                    limit_logged["done"] = True
                if first:
                    reporter.event("warning", f"max runtime ({max_runtime / 60:.0f} min) reached; no new tasks will start, "
                                              "remaining tasks stay pending")
                return
            if not reserve():
                return
            try:
                task = next_local(name, exact) if local_mode else next_sheet(name, exact)
            except Exception as e:
                give_back()
                failures += 1
                reporter.event("error", f"could not fetch tasks: {e}", name)
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
            if phone_failed and on_failure == "stop":
                reporter.report(dict(task, device=name), "skipped", 0, 0,
                                "skipped: an earlier task on this phone failed (on_failure = stop)")
                continue
            status = execute_task(serial, dict(task, device=name), run_id, retries, task_timeout, shots_dir, reporter)
            if status in ("failed", "timeout", "offline"):
                phone_failed = True
            if task_delay:
                time.sleep(task_delay)

    def stop_cloud(name, final=False):
        """Stop a cloud phone. The worker's attempt may fail; the final sweep gets a second chance and only then
        is a failure recorded as an error (the phone may still be billing)."""
        pid = gl_cloudadb.phone_id(name)
        with lock:
            if name in cloud_state["stopped"] or name not in cloud_state["started"]:
                return
        try:
            down_fn(pid, reporter.log_dir)
            with lock:
                cloud_state["stopped"].add(name)
            reporter.event("info", f"cloud phone {pid} stopped", name)
        except gl_cloudadb.CloudError as e:
            if not final:
                reporter.event("warning", f"stopping {pid} failed, will retry before the run ends: {e}", name)
                return
            with lock:
                cloud_state["stop_failures"].append(pid)
            reporter.event("error", f"STOP FAILED, {pid} may still be billing: {e}", name)

    def cloud_worker(name):
        pid = gl_cloudadb.phone_id(name)
        if daily_cap_s and daily_spent_s() >= daily_cap_s:      # never start a phone once the day's cap is used up
            cap_reached(name, time.monotonic())
            return
        t0 = time.monotonic()
        with lock:
            cloud_state["started"].add(name)  # recorded before `up` so a half-started phone is still stopped
            cloud_state["active"][name] = t0
        try:
            reporter.event("info", f"starting cloud phone {pid} (billing starts)", name)
            serial = up_fn(pid, reporter.log_dir, cloud_up_timeout)
            reporter.event("info", f"cloud phone {pid} ready as {getattr(serial, 'label', serial)} after {time.monotonic() - t0:.0f}s", name)
            work(name, serial, True, started_at=t0)
        except gl_cloudadb.CloudError as e:
            reporter.event("error", str(e), name)
        except Exception as e:
            reporter.event("error", f"cloud worker crashed: {type(e).__name__}: {e}", name)
        finally:
            stop_cloud(name)
            with lock:
                cloud_state["active"].pop(name, None)
                cloud_state["billed_s"] += time.monotonic() - t0

    threads = [threading.Thread(target=work, args=(n, s, False), name=f"bulk-{n}", daemon=True) for n, s in local_workers]
    threads += [threading.Thread(target=cloud_worker, args=(n,), name=f"bulk-{n}", daemon=True) for n, _ in cloud_workers]
    interrupted = False
    try:
        for t in threads:
            t.start()
        for t in threads:
            while t.is_alive():
                t.join(0.5)
    except KeyboardInterrupt:
        interrupted = True
        stop.set()
        reporter.event("warning", "interrupted; finishing in-flight tasks and stopping cloud phones")
        for t in threads:
            t.join(60)
    finally:
        # Billing safety net: whatever happened above, stop every cloud phone this run started.
        for name in sorted(cloud_state["started"]):
            stop_cloud(name, final=True)

    # Local tasks nobody could run are reported, not dropped.
    for t in queue:
        why = ("cloud phone not started (use --cloud)" if gl_cloudadb.is_cloud_device(t["device"])
               else f"device '{t['device']}' not connected or run ended before it was reached")
        reporter.report(t, "skipped", 0, 0, why)
        budget["total"] += 1

    day_total_s = add_daily_used_s(reporter.log_dir, cloud_state["billed_s"]) if (daily_cap_s and cloud_state["billed_s"]) else daily_prior_s
    notes = []
    if interrupted:
        notes.append("interrupted")
    if cap_hit["daily"]:
        notes.append("daily phone-minute cap reached")
    if cap_hit["phone"]:
        notes.append(f"per-phone cap reached on {len(cap_hit['phone'])} phone(s)")
    if cloud_state["started"]:
        notes.append(f"cloud phones: {len(cloud_state['started'])}, ~{cloud_state['billed_s'] / 60:.1f} phone-minutes")
    if cloud_state["stop_failures"]:
        notes.append("STOP FAILED: " + ",".join(cloud_state["stop_failures"]))
    summary = reporter.summary(started, [n for n, _ in workers], budget["total"], "; ".join(notes))
    return {"status": "success", "run_id": run_id, "workers": [n for n, _ in workers], "total": summary["total"],
            "success": summary["success"], "failed": summary["failed"], "other": summary["other"],
            "log": reporter.log_path, "sheet_write_failures": reporter.sheet_failures, "interrupted": interrupted,
            "transport": transport,
            "cloud": {"started": sorted(cloud_state["started"]), "stopped": sorted(cloud_state["stopped"]),
                      "stop_failures": cloud_state["stop_failures"],
                      "phone_minutes": round(cloud_state["billed_s"] / 60, 1)},
            "caps": {"daily_phone_minutes": daily_phone_minutes, "daily_used_minutes": round(day_total_s / 60, 1),
                     "max_phone_minutes": max_phone_minutes, "daily_cap_reached": cap_hit["daily"],
                     "phones_capped": sorted(cap_hit["phone"])}}
