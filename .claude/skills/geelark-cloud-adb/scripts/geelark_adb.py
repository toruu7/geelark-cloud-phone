#!/usr/bin/env python3
"""geelark_adb: drive a GeeLark cloud phone over the Cloud OpenAPI + ADB.

No desktop app, window or mouse needed, so it also runs on a headless server.
Standard library only. Every command prints one JSON object; "status": "error" means it failed.

Env:
  GEELARK_API_TOKEN       Bearer token from GeeLark settings (required for up/down/status)
  GEELARK_CLOUD_PHONE_ID  default phone id (or pass --id)
  GEELARK_ADB             path to adb (default: adb on PATH, else GeeLark's bundled adb)
  GEELARK_API_BASE        default https://openapi.geelark.com
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET

API_BASE = os.environ.get("GEELARK_API_BASE", "https://openapi.geelark.com")
STATE_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache"), "geelark-cloud-adb")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
RE_ENDPOINT = re.compile(r"^/open/v1/[A-Za-z0-9_]+/[A-Za-z0-9_]+$")
RE_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
ADB_TIMEOUT = int(os.environ.get("GEELARK_ADB_TIMEOUT", "30"))


def out(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    sys.exit(code)


def fail(message, **extra):
    out({"status": "error", "message": message, **extra}, 1)


# ---------- Cloud OpenAPI ----------

def api(endpoint, body):
    token = os.environ.get("GEELARK_API_TOKEN")
    if not token:
        fail("GEELARK_API_TOKEN is not set.")
    if not RE_ENDPOINT.match(endpoint):
        fail("Endpoint must look like /open/v1/<resource>/<action>.", endpoint=endpoint)
    trace = str(uuid.uuid4())
    req = urllib.request.Request(
        API_BASE + endpoint,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "traceId": trace},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        fail(f"HTTP {e.code} from {endpoint}", traceId=trace)
    except Exception as e:  # network, json
        fail(f"API call failed: {type(e).__name__}: {e}", traceId=trace)
    if payload.get("code") != 0:
        fail(f"API error on {endpoint}", api_code=payload.get("code"), api_msg=payload.get("msg"), traceId=trace)
    return payload.get("data") or {}


def phone_id(args):
    pid = getattr(args, "id", None) or os.environ.get("GEELARK_CLOUD_PHONE_ID")
    if not pid:
        fail("No phone id. Pass --id or set GEELARK_CLOUD_PHONE_ID.")
    return pid


# ---------- ADB ----------

def adb_exe():
    for cand in (os.environ.get("GEELARK_ADB"), shutil.which("adb"),
                 os.path.expandvars(r"%APPDATA%\GeeLark\scrcpy\adb.exe")):
        if cand and os.path.exists(cand) or (cand and shutil.which(cand)):
            return cand
    fail("adb not found. Install platform-tools or set GEELARK_ADB.")


def run_adb(*argv, serial=None, binary=False, check=True):
    cmd = [adb_exe()] + (["-s", serial] if serial else []) + list(argv)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=ADB_TIMEOUT)
    except subprocess.TimeoutExpired:
        fail("adb timed out", cmd=argv[0])
    if check and p.returncode != 0:
        fail("adb failed", cmd=list(argv), stderr=p.stderr.decode(errors="replace")[:300])
    return p.stdout if binary else p.stdout.decode(errors="replace")


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)  # never holds the ADB password or API token


def serial(args):
    s = getattr(args, "serial", None) or os.environ.get("GEELARK_ADB_SERIAL") or load_state().get("serial")
    if not s:
        fail("No ADB serial. Run `up` first or pass --serial ip:port.")
    return s


# ---------- UI helpers ----------

def ui_nodes(ser):
    run_adb("shell", "uiautomator", "dump", "/sdcard/gl_ui.xml", serial=ser)
    xml = run_adb("exec-out", "cat", "/sdcard/gl_ui.xml", serial=ser)
    root = ET.fromstring(xml[xml.index("<"):])
    nodes = []
    for n in root.iter("node"):
        m = RE_BOUNDS.search(n.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        nodes.append({
            "text": n.get("text", ""), "desc": n.get("content-desc", ""), "id": n.get("resource-id", ""),
            "clickable": n.get("clickable") == "true", "cx": (x1 + x2) // 2, "cy": (y1 + y2) // 2,
            "bounds": [x1, y1, x2, y2],
        })
    return nodes


def find_nodes(nodes, needle, exact=False):
    needle = needle.lower()
    hits = []
    for n in nodes:
        for label in (n["text"], n["desc"]):
            low = label.lower()
            if low and ((low == needle) if exact else (needle in low)):
                hits.append(n)
                break
    return hits


# ---------- commands ----------

def cmd_up(args):
    pid = phone_id(args)
    api("/open/v1/phone/start", {"ids": [pid]})
    api("/open/v1/adb/setStatus", {"ids": [pid], "open": True})
    deadline = time.time() + args.timeout
    last = ""
    while time.time() < deadline:
        time.sleep(4)
        data = api("/open/v1/adb/getData", {"ids": [pid]})
        items = data.get("items") or []
        item = items[0] if items else {}
        if item.get("code", 1) != 0 or not item.get("ip"):
            last = item.get("msg") or "ADB data not ready"
            continue
        ser = f"{item['ip']}:{item['port']}"
        conn = run_adb("connect", ser, check=False).strip()
        if "connected" not in conn:
            last = conn
            continue
        login = run_adb("shell", "glogin", item["pwd"], serial=ser, check=False).strip()
        if "success" not in login.lower():
            last = f"glogin: {login}"
            continue
        save_state({"serial": ser, "phone_id": pid, "ts": int(time.time())})
        out({"status": "success", "serial": ser, "message": "phone up, ADB connected and logged in"})
    fail("Timed out waiting for the phone/ADB.", last=last)


def cmd_down(args):
    pid = phone_id(args)
    api("/open/v1/phone/stop", {"ids": [pid]})
    save_state({})
    out({"status": "success", "message": "stop requested; billing ends when the phone stops"})


def cmd_status(args):
    pid = phone_id(args)
    data = api("/open/v1/phone/status", {"ids": [pid]})
    st = load_state()
    out({"status": "success", "phone": data, "adb_serial": st.get("serial")})


def cmd_shot(args):
    ser = serial(args)
    png = run_adb("exec-out", "screencap", "-p", serial=ser, binary=True)
    if not png.startswith(b"\x89PNG"):
        fail("screencap did not return a PNG")
    with open(args.out, "wb") as f:
        f.write(png)
    out({"status": "success", "file": os.path.abspath(args.out), "bytes": len(png)})


def cmd_ui(args):
    nodes = ui_nodes(serial(args))
    if args.find:
        nodes = find_nodes(nodes, args.find, args.exact)
    elif not args.all:
        nodes = [n for n in nodes if n["text"] or n["desc"]]
    out({"status": "success", "count": len(nodes), "nodes": nodes[: args.limit]})


def cmd_tap(args):
    run_adb("shell", "input", "tap", str(args.x), str(args.y), serial=serial(args))
    out({"status": "success", "action": "tap", "x": args.x, "y": args.y})


def cmd_swipe(args):
    run_adb("shell", "input", "swipe", *map(str, (args.x1, args.y1, args.x2, args.y2, args.ms)), serial=serial(args))
    out({"status": "success", "action": "swipe"})


def cmd_tap_text(args):
    ser = serial(args)
    hits = find_nodes(ui_nodes(ser), args.text, args.exact)
    if len(hits) <= args.index:
        fail(f"No on-screen match #{args.index} for {args.text!r}", matches=len(hits))
    n = hits[args.index]
    run_adb("shell", "input", "tap", str(n["cx"]), str(n["cy"]), serial=ser)
    out({"status": "success", "action": "tap-text", "text": n["text"] or n["desc"], "x": n["cx"], "y": n["cy"], "matches": len(hits)})


def cmd_type(args):
    text = args.text.replace("%", "%25").replace(" ", "%s")
    run_adb("shell", "input", "text", text, serial=serial(args))
    if args.enter:
        run_adb("shell", "input", "keyevent", "66", serial=serial(args))
    out({"status": "success", "action": "type", "chars": len(args.text)})


KEYS = {"back": 4, "home": 3, "recent": 187, "enter": 66, "power": 26, "volup": 24, "voldown": 25}


def cmd_key(args):
    code = KEYS.get(args.name.lower())
    if code is None:
        fail(f"Unknown key. Use one of {sorted(KEYS)}")
    run_adb("shell", "input", "keyevent", str(code), serial=serial(args))
    out({"status": "success", "action": "key", "key": args.name})


def cmd_open_url(args):
    ser = serial(args)
    argv = ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", args.url]
    if args.package:
        argv += ["-p", args.package]
    res = run_adb(*argv, serial=ser)
    if "Error" in res:
        fail("am start reported an error", output=res.strip()[:300])
    out({"status": "success", "action": "open-url", "url": args.url, "package": args.package})


def cmd_skip_ad(args):
    ser = serial(args)
    deadline = time.time() + args.timeout
    saw_ad = False
    while time.time() < deadline:
        nodes = ui_nodes(ser)
        if find_nodes(nodes, "skip", exact=False):
            hits = [n for n in find_nodes(nodes, "skip") if "skip" in (n["text"] or n["desc"]).lower()
                    and "next" not in (n["text"] or n["desc"]).lower()]
            if hits:
                n = hits[0]
                run_adb("shell", "input", "tap", str(n["cx"]), str(n["cy"]), serial=ser)
                out({"status": "success", "action": "skip-ad", "skipped": True, "x": n["cx"], "y": n["cy"]})
        saw_ad = saw_ad or bool(find_nodes(nodes, "sponsored")) or bool(find_nodes(nodes, "visit advertiser"))
        if not saw_ad and time.time() - (deadline - args.timeout) > args.quick:
            out({"status": "success", "action": "skip-ad", "skipped": False, "message": "no ad detected"})
        time.sleep(2)
    out({"status": "success", "action": "skip-ad", "skipped": False, "ad_seen": saw_ad,
         "message": "timed out; ad may be unskippable, wait and retry"})


def cmd_app(args):
    run_adb("shell", "monkey", "-p", args.package, "-c", "android.intent.category.LAUNCHER", "1", serial=serial(args))
    out({"status": "success", "action": "app", "package": args.package})


def cmd_focus(args):
    res = run_adb("shell", "dumpsys", "window", serial=serial(args))
    m = re.search(r"mCurrentFocus=.*?\s(\S+)/(\S+)\}", res)
    out({"status": "success", "package": m.group(1) if m else None, "activity": m.group(2) if m else None})


def build_parser():
    p = argparse.ArgumentParser(prog="geelark_adb", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--serial", help="ADB serial ip:port (default: from last `up`)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        sp = sub.add_parser(name, **kw)
        sp.set_defaults(fn=fn)
        return sp

    s = add("up", cmd_up, help="start phone, enable ADB, connect and glogin")
    s.add_argument("--id"); s.add_argument("--timeout", type=int, default=120)
    s = add("down", cmd_down, help="stop the phone (stops billing)"); s.add_argument("--id")
    s = add("status", cmd_status, help="phone status from the API"); s.add_argument("--id")
    s = add("shot", cmd_shot, help="PNG screenshot"); s.add_argument("--out", default="shot.png")
    s = add("ui", cmd_ui, help="list on-screen text/buttons with tap centers")
    s.add_argument("--find"); s.add_argument("--exact", action="store_true"); s.add_argument("--all", action="store_true")
    s.add_argument("--limit", type=int, default=80)
    s = add("tap", cmd_tap); s.add_argument("x", type=int); s.add_argument("y", type=int)
    s = add("swipe", cmd_swipe)
    for a in ("x1", "y1", "x2", "y2"):
        s.add_argument(a, type=int)
    s.add_argument("--ms", type=int, default=300)
    s = add("tap-text", cmd_tap_text, help="tap the on-screen element whose text/desc matches")
    s.add_argument("text"); s.add_argument("--exact", action="store_true"); s.add_argument("--index", type=int, default=0)
    s = add("type", cmd_type); s.add_argument("text"); s.add_argument("--enter", action="store_true")
    s = add("key", cmd_key); s.add_argument("name")
    s = add("open-url", cmd_open_url, help="open a URL, optionally forced into an app")
    s.add_argument("url"); s.add_argument("--package", help="e.g. com.google.android.youtube")
    s = add("skip-ad", cmd_skip_ad, help="wait for a Skip button and tap it")
    s.add_argument("--timeout", type=int, default=40); s.add_argument("--quick", type=int, default=6,
                   help="give up after this many seconds if no ad is detected")
    s = add("app", cmd_app, help="launch an app by package"); s.add_argument("package")
    add("focus", cmd_focus, help="which app/activity is in the foreground")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
