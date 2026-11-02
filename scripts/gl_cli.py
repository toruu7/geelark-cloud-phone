"""Argument parsing and command dispatch."""
import sys
import os
import time
import json
import argparse
import subprocess
from _version import __version__ as VERSION
from gl_lock import DeviceLock, LockTimeout
import gl_adb
import gl_apps
import gl_base
import gl_bulk
import gl_cloud
import gl_input
import gl_manifest
import gl_ocr
import gl_orch
import gl_prompt
import gl_recipes
import gl_sheets
import gl_smart
import gl_vision
import gl_win32

# CLI Router
# Commands that touch neither the phone windows nor shared cache files; everything else is serialized
# across processes (CLI, webhook bridge, MCP) by DeviceLock.
LOCK_FREE_COMMANDS = {
    "features", "export-schema", "use", "status", "list-windows",
    "cloud-list", "cloud-start", "cloud-stop", "cloud-status", "cloud-api",
    # ADB-only: never touches the mouse, windows or shared desktop cache files
    "bulk-run", "bulk-check", "bulk-flush",
}

def main():
    parser = argparse.ArgumentParser(description=f"GeeLark Cloud Phone Controller v{VERSION}")
    subparsers = parser.add_subparsers(dest="command")

    # list-windows
    p_list = subparsers.add_parser("list-windows", help="List all GeeLark and phone windows")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")

    # launch-app
    subparsers.add_parser("launch-app", help="Launch GeeLark desktop app")

    # focus
    p_focus = subparsers.add_parser("focus", help="Focus a GeeLark or Phone window")
    p_focus.add_argument("--window", "-w", help="Window title substring or HWND")

    # capture
    p_cap = subparsers.add_parser("capture", help="Capture phone screen")
    p_cap.add_argument("--window", "-w", help="Window title substring or HWND")
    p_cap.add_argument("--out", "-o", default="phone_screen.png", help="Output path for PNG")
    p_cap.add_argument("--no-crop", action="store_true", help="Capture full window instead of cropped phone display")
    p_cap.add_argument("--annotate", action="store_true", help="Overlay Set-of-Mark (SoM) numbered badges")
    p_cap.add_argument("--low-token", action="store_true", help="Downsample image to save up to 70 percent LLM vision tokens")

    # tap-mark (SoM)
    p_tm = subparsers.add_parser("tap-mark", help="Tap a numbered mark from previous 'capture --annotate'")
    p_tm.add_argument("mark_id", type=int, help="Mark number (e.g. 1, 2, 3)")
    p_tm.add_argument("--window", "-w", help="Window title substring or HWND")

    # open-app
    p_oa = subparsers.add_parser("open-app", help="Fast App Launcher (youtube, tiktok, chrome, settings)")
    p_oa.add_argument("name", help="App name or Android package")
    p_oa.add_argument("--window", "-w", help="Window title substring or HWND")

    # deep-link
    p_dl = subparsers.add_parser("deep-link", help="0.1s Instant URL/Video loader via Android Intent")
    p_dl.add_argument("url", help="URL or intent URI to open directly")
    p_dl.add_argument("--window", "-w", help="Window title substring or HWND")

    # scroll-find
    p_sf = subparsers.add_parser("scroll-find", help="Scrolls and finds text automatically in 1 command")
    p_sf.add_argument("query", help="Text to search for")
    p_sf.add_argument("--max-swipes", type=int, default=5, help="Max scrolls")
    p_sf.add_argument("--no-click", action="store_true", help="Find coordinates only without clicking")
    p_sf.add_argument("--window", "-w", help="Window title substring or HWND")

    # hide-keyboard
    p_hk = subparsers.add_parser("hide-keyboard", help="Collapse virtual keyboard to reveal hidden buttons")
    p_hk.add_argument("--window", "-w", help="Window title substring or HWND")

    # dump-ui
    subparsers.add_parser("dump-ui", help="Dump UI accessibility tree via ADB")

    # wait-stable
    p_stable = subparsers.add_parser("wait-stable", help="Wait until screen rendering finishes")
    p_stable.add_argument("--window", "-w", help="Window title substring or HWND")
    p_stable.add_argument("--timeout", type=float, default=6.0, help="Max wait seconds")

    # tap
    p_tap = subparsers.add_parser("tap", help="Tap on phone screen")
    p_tap.add_argument("x", type=float, help="X coordinate (pixels or 0.0-1.0 if --norm)")
    p_tap.add_argument("y", type=float, help="Y coordinate (pixels or 0.0-1.0 if --norm)")
    p_tap.add_argument("--window", "-w", help="Window title substring or HWND")
    p_tap.add_argument("--norm", action="store_true", help="Treat coordinates as normalized floats (0.0 to 1.0)")

    # swipe
    p_sw = subparsers.add_parser("swipe", help="Swipe/drag on phone screen")
    p_sw.add_argument("x1", type=float, help="Start X")
    p_sw.add_argument("y1", type=float, help="Start Y")
    p_sw.add_argument("x2", type=float, help="End X")
    p_sw.add_argument("y2", type=float, help="End Y")
    p_sw.add_argument("--window", "-w", help="Window title substring or HWND")
    p_sw.add_argument("--norm", action="store_true", help="Treat coordinates as normalized floats (0.0 to 1.0)")
    p_sw.add_argument("--steps", type=int, default=20, help="Interpolation steps")

    # type
    p_type = subparsers.add_parser("type", help="Type/paste text into focused element")
    p_type.add_argument("text", help="Text string to type")
    p_type.add_argument("--enter", action="store_true", help="Immediately press Enter after typing")
    p_type.add_argument("--window", "-w", help="Window title substring or HWND")

    # key
    p_key = subparsers.add_parser("key", help="Press Android navigation key (home, back, recent, enter)")
    p_key.add_argument("name", choices=["home", "back", "recent", "appswitch", "enter", "tab", "esc"], help="Key name")
    p_key.add_argument("--window", "-w", help="Window title substring or HWND")

    # find-text
    p_find = subparsers.add_parser("find-text", help="Search for text labels using Windows Native OCR")
    p_find.add_argument("query", help="Text to search for")
    p_find.add_argument("--window", "-w", help="Window title substring or HWND")

    # click-text
    p_click_text = subparsers.add_parser("click-text", help="Click on a text label directly via OCR")
    p_click_text.add_argument("query", help="Text to search and click")
    p_click_text.add_argument("--window", "-w", help="Window title substring or HWND")

    # wait-text
    p_wait_text = subparsers.add_parser("wait-text", help="Wait for text label to appear and click it")
    p_wait_text.add_argument("query", help="Text to wait for (e.g. 'Skip', 'Install')")
    p_wait_text.add_argument("--timeout", type=float, default=30.0, help="Timeout in seconds")
    p_wait_text.add_argument("--window", "-w", help="Window title substring or HWND")

    # dismiss-popup
    p_dismiss = subparsers.add_parser("dismiss-popup", help="Dismiss obstacle popups or modals")
    p_dismiss.add_argument("--window", "-w", help="Window title substring or HWND")

    # recover
    p_rec = subparsers.add_parser("recover", help="Emergency recovery: back, back, home, verify")
    p_rec.add_argument("--window", "-w", help="Window title substring or HWND")

    # adb
    p_adb = subparsers.add_parser("adb", help="Run ADB command via GeeLark's bundled ADB")
    p_adb.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to adb")

    # use (set active profile)
    p_use = subparsers.add_parser("use", help="Set active phone window or profile number")
    p_use.add_argument("target", help="Profile number, HWND, or window title substring")
    p_use.add_argument("--device", help="ADB serial for this phone (enables ADB key/tap injection for it)")

    # features
    p_feat = subparsers.add_parser("features", help="Display full catalog of skill features, capabilities, and batch actions")
    p_feat.add_argument("--json", action="store_true", help="Output feature catalog in JSON format")

    # status
    subparsers.add_parser("status", help="Get overview of connected phones, active profile, and ADB status")

    # youtube-flow
    p_yt = subparsers.add_parser("youtube-flow", help="1-Click YouTube recipe: Deep-link, auto-skip ads, click link")
    p_yt.add_argument("url", help="YouTube video URL")
    p_yt.add_argument("--click-link", help="Text/domain of link in description to click (e.g. 'http')")
    p_yt.add_argument("--no-skip-ads", action="store_true", help="Do not wait for or skip pre-roll ads")
    p_yt.add_argument("--window", "-w", help="Window title substring or HWND")

    # tiktok-feed
    p_tt = subparsers.add_parser("tiktok-feed", help="1-Click TikTok warmup: Natural Bézier swipes and realistic watch time")
    p_tt.add_argument("--videos", type=int, default=5, help="Number of videos to watch")
    p_tt.add_argument("--min-watch", type=float, default=4.0, help="Min seconds per video")
    p_tt.add_argument("--max-watch", type=float, default=10.0, help="Max seconds per video")
    p_tt.add_argument("--like-ratio", type=float, default=0.25, help="Probability (0.0 - 1.0) of liking a video")
    p_tt.add_argument("--window", "-w", help="Window title substring or HWND")

    # batch-run
    p_br = subparsers.add_parser("batch-run", help="Run a sequence of actions from a JSON file or JSON string")
    p_br.add_argument("steps", help="Path to JSON file or raw JSON array of action objects")
    p_br.add_argument("--window", "-w", help="Window title substring or HWND")

    # broadcast
    p_bc = subparsers.add_parser("broadcast", help="Broadcast an action across ALL open cloud phones simultaneously")
    p_bc.add_argument("action", help="Action name (tap, swipe, key, type, open-app, deep-link, dismiss-popup)")
    p_bc.add_argument("action_args", nargs=argparse.REMAINDER, help="Arguments passed to the action")

    # batch-profiles
    p_bp = subparsers.add_parser("batch-profiles", help="Run a command sequentially across multiple profiles")
    p_bp.add_argument("--profiles", "-p", default="all", help="Comma-separated profile numbers/names (e.g. '1,2,4' or 'all')")
    p_bp.add_argument("command_name", help="Command to run (youtube-flow, tiktok-feed, open-app, deep-link, dismiss-popup, recover)")
    p_bp.add_argument("command_args", nargs=argparse.REMAINDER, help="Arguments for the command")

    # smart-click (Multi-path element grounding)
    p_sc = subparsers.add_parser("smart-click", help="Multi-path element clicker (ADB XML Tree -> Local OCR -> Scroll-Find -> Anchor)")
    p_sc.add_argument("query", help="Element text, content-desc, or anchor name")
    p_sc.add_argument("--no-scroll", action="store_true", help="Disable scroll-find fallback")
    p_sc.add_argument("--window", "-w", help="Window title substring or HWND")

    # ensure-device (Multi-path lifecycle resolver)
    p_ed = subparsers.add_parser("ensure-device", help="Multi-path device readiness resolver (Active -> Restore -> Scan -> Cloud Boot -> Desktop Launch)")
    p_ed.add_argument("--window", "-w", help="Target profile number or window title")
    p_ed.add_argument("--no-boot", action="store_true", help="Do not attempt auto-boot/launch if window is closed")

    # prompt (Built-in plain-text semantic intent transpiler)
    p_pr = subparsers.add_parser("prompt", help="Execute a plain-text natural language instruction deterministically")
    p_pr.add_argument("text", help="Plain text instruction (e.g. 'watch 5 tiktoks on profile 4')")
    p_pr.add_argument("--window", "-w", help="Optional target profile override")

    # export-schema (Universal agent schema exporter)
    p_es = subparsers.add_parser("export-schema", help="Export tool schemas for OpenAI, xAI Grok Bot, MCP, or OpenAPI 3.1")
    p_es.add_argument("--format", "-f", choices=["all", "openai", "xai", "mcp", "openapi"], default="all", help="Schema format")
    p_es.add_argument("--server-url", default="http://localhost:5055", help="Base URL for OpenAPI spec")

    # cloud-list / cloud-start / cloud-stop (Hybrid Cloud OpenAPI)
    p_cl = subparsers.add_parser("cloud-list", help="List cloud phones via GeeLark Cloud OpenAPI")
    p_cl.add_argument("--token", help="GeeLark API Bearer token (or set GEELARK_API_TOKEN)")

    p_cstart = subparsers.add_parser("cloud-start", help="Remotely start a cloud phone profile via GeeLark OpenAPI")
    p_cstart.add_argument("profile_id", help="Cloud phone profile ID")
    p_cstart.add_argument("--token", help="GeeLark API Bearer token")

    p_cstop = subparsers.add_parser("cloud-stop", help="Remotely stop a cloud phone profile via GeeLark OpenAPI")
    p_cstop.add_argument("profile_id", help="Cloud phone profile ID")
    p_cstop.add_argument("--token", help="GeeLark API Bearer token")

    p_cstat = subparsers.add_parser("cloud-status", help="Query cloud phone status via GeeLark OpenAPI")
    p_cstat.add_argument("profile_id", help="Cloud phone profile ID")
    p_cstat.add_argument("--token", help="GeeLark API Bearer token")

    p_capi = subparsers.add_parser("cloud-api", help="Call any GeeLark OpenAPI endpoint (/open/v1/...) with a JSON body")
    p_capi.add_argument("endpoint", help="Endpoint path, e.g. /open/v1/phone/list")
    p_capi.add_argument("--data", default="{}", help="JSON request body")
    p_capi.add_argument("--token", help="GeeLark API Bearer token")

    p_bulk = subparsers.add_parser("bulk-run", help="Run queued tasks on many phones in parallel over ADB and report to a Google Sheet")
    p_bulk.add_argument("--tasks", help="JSON/CSV task file. Omit to claim tasks from the Google Sheet queue")
    p_bulk.add_argument("--devices", help="Comma-separated ADB serials (default: all connected)")
    p_bulk.add_argument("--retries", type=int, default=1, help="Retries per failed task (default 1)")
    p_bulk.add_argument("--max-workers", type=int, default=8, help="Max phones worked in parallel")
    p_bulk.add_argument("--max-tasks", type=int, help="Stop after this many tasks")
    p_bulk.add_argument("--task-timeout", type=float, default=120.0, help="Seconds allowed per task attempt")
    p_bulk.add_argument("--task-delay", type=float, default=0.0, help="Pause between tasks on the same phone")
    p_bulk.add_argument("--dry-run", action="store_true", help="Validate a --tasks file and show the plan; touch nothing")
    p_bulk.add_argument("--no-sheet", action="store_true", help="Log locally only, even if sheet env vars are set")
    p_bulk.add_argument("--log-dir", help="Directory for run logs, screenshots and the report spool (default: ./logs)")
    p_bulk.add_argument("--fail-on-error", action="store_true", help="Exit with code 4 if any task failed")

    p_bchk = subparsers.add_parser("bulk-check", help="Check ADB devices and the Google Sheet connection")
    p_bflush = subparsers.add_parser("bulk-flush", help="Re-send reports that could not reach the sheet earlier")
    p_bflush.add_argument("--log-dir", help="Directory holding the report spool")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    lock = DeviceLock() if args.command not in LOCK_FREE_COMMANDS else None
    try:
        if lock:
            lock.acquire()
        if args.command == "list-windows":
            wins = gl_win32.list_windows()
            if getattr(args, "json", False):
                print(json.dumps(wins, indent=2))
            else:
                print(f"Found {len(wins)} GeeLark / Phone window(s):")
                for w in wins:
                    ptype = "[PHONE]" if w["is_phone"] else "[APP]"
                    print(f"  {ptype} HWND: {w['hwnd']} | Rect: ({w['rect']['left']}, {w['rect']['top']}, {w['rect']['width']}x{w['rect']['height']}) | Title: {w['title']}")

        elif args.command == "use":
            res = gl_base.set_active_target(args.target, adb_device=args.device)
            print(json.dumps(res, indent=2))

        elif args.command == "features":
            manifest = gl_manifest.get_feature_manifest()
            if getattr(args, "json", False):
                print(json.dumps(manifest, indent=2))
            else:
                print("=======================================================")
                print(f"  {manifest['name']} ({manifest['version']})")
                print("  " + manifest['description'])
                print("=======================================================")
                agents_str = ", ".join(manifest["supported_agents"])
                print(f"Supported Agents: {agents_str}")
                print()
                print("Feature Capabilities:")
                for cat, info in manifest["capabilities"].items():
                    cat_name = cat.upper().replace("_", " ")
                    cmds = info.get("commands") or info.get("components", [])
                    cmd_list = ", ".join(cmds)
                    print(f"  * {cat_name}:")
                    print(f"    - Description: {info.get('description', '')}")
                    print(f"    - Commands / Components: {cmd_list}")
                batch_str = ", ".join(manifest["supported_batch_actions"])
                print()
                print("Supported Batch Actions ('batch-run'):")
                print(f"  {batch_str}")
                print()
                print("Common Android Apps ('open-app'):")
                for app, pkg in manifest["common_apps"].items():
                    print(f"  - {app:10s} -> {pkg}")
                tgt = manifest["environment"]["active_target"] or "None (auto-select)"
                print()
                print(f"Active Target Profile: {tgt}")
                print(f"Platform: {'Windows Host' if manifest['environment']['is_windows'] else 'Non-Windows (Safe CLI/Metadata mode)'}")
                print("=======================================================")

        elif args.command == "status":
            res = gl_orch.get_system_status()
            print(json.dumps(res, indent=2))

        elif args.command == "youtube-flow":
            res = gl_recipes.recipe_youtube_flow(args.url, click_link=args.click_link, skip_ads=not args.no_skip_ads, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "tiktok-feed":
            res = gl_recipes.recipe_tiktok_feed(videos=args.videos, min_watch=args.min_watch, max_watch=args.max_watch, like_ratio=args.like_ratio, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "batch-run":
            res = gl_orch.execute_batch_steps(args.steps, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "broadcast":
            res = gl_orch.broadcast_action(args.action, args.action_args)
            print(json.dumps(res, indent=2))

        elif args.command == "batch-profiles":
            res = gl_orch.batch_profiles(args.profiles, args.command_name, args.command_args)
            print(json.dumps(res, indent=2))

        elif args.command == "launch-app":
            if os.path.exists(gl_base.GEELARK_PATH):
                try:
                    os.startfile(gl_base.GEELARK_PATH)
                    print(json.dumps({"status": "success", "message": "GeeLark launched via startfile"}))
                except Exception:
                    subprocess.Popen([gl_base.GEELARK_PATH])
                    print(json.dumps({"status": "success", "message": "GeeLark launched via Popen"}))
            else:
                print(json.dumps({"status": "error", "message": f"GeeLark executable not found at {gl_base.GEELARK_PATH}"}))

        elif args.command == "focus":
            win = gl_win32.find_target_window(args.window)
            if win:
                gl_win32.focus_window(win["hwnd"])
                print(json.dumps({"status": "success", "focused": win["title"], "hwnd": win["hwnd"]}))
            else:
                print(json.dumps({"status": "error", "message": "Target window not found"}))

        elif args.command == "capture":
            if args.annotate:
                res = gl_vision.capture_and_annotate(target=args.window, out_path=args.out, low_token=args.low_token)
            else:
                res = gl_vision.capture_phone(target=args.window, out_path=args.out, crop_phone_screen=not args.no_crop, low_token=args.low_token)
            print(json.dumps(res, indent=2))

        elif args.command == "tap-mark":
            res = gl_vision.tap_mark(args.mark_id, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "open-app":
            res = gl_apps.open_app(args.name, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "deep-link":
            res = gl_apps.deep_link(args.url, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "scroll-find":
            res = gl_ocr.scroll_find(args.query, max_swipes=args.max_swipes, click=not args.no_click, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "hide-keyboard":
            res = gl_input.hide_keyboard(target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "dump-ui":
            res = gl_apps.dump_ui_tree()
            print(json.dumps(res, indent=2))

        elif args.command == "wait-stable":
            res = gl_vision.wait_screen_stable(target=args.window, timeout=args.timeout)
            print(json.dumps(res, indent=2))

        elif args.command == "tap":
            res = gl_input.tap(args.x, args.y, target=args.window, normalized=args.norm)
            print(json.dumps(res))

        elif args.command == "swipe":
            res = gl_input.swipe(args.x1, args.y1, args.x2, args.y2, target=args.window, normalized=args.norm, steps=args.steps)
            print(json.dumps(res))

        elif args.command == "type":
            res = gl_input.type_text(args.text, target=args.window)
            if args.enter:
                time.sleep(0.1)
                gl_input.send_key("enter", target=args.window)
            print(json.dumps(res))

        elif args.command == "key":
            res = gl_input.send_key(args.name, target=args.window)
            print(json.dumps(res))

        elif args.command == "find-text":
            res = gl_ocr.find_text_on_screen(args.query, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "click-text":
            res = gl_ocr.click_text_on_screen(args.query, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "wait-text":
            res = gl_ocr.wait_and_click_text(args.query, target=args.window, timeout=args.timeout)
            print(json.dumps(res, indent=2))

        elif args.command == "dismiss-popup":
            res = gl_apps.dismiss_popups(target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "recover":
            res = gl_apps.emergency_recover(target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "smart-click":
            res = gl_smart.smart_click(args.query, target=args.window, scroll_fallback=not args.no_scroll)
            print(json.dumps(res, indent=2))

        elif args.command == "ensure-device":
            res = gl_cloud.ensure_device_ready(target=args.window, auto_boot=not args.no_boot)
            print(json.dumps(res, indent=2))

        elif args.command == "prompt":
            res = gl_prompt.execute_natural_prompt(args.text, target=args.window)
            print(json.dumps(res, indent=2))

        elif args.command == "export-schema":
            res = gl_manifest.export_agent_schemas(fmt=args.format, server_url=args.server_url)
            print(json.dumps(res, indent=2))

        elif args.command == "cloud-list":
            res = gl_cloud.cloud_api_request("/open/v1/phone/list", {"page": 1, "pageSize": 100}, api_token=args.token)
            print(json.dumps(res, indent=2))

        elif args.command == "cloud-start":
            res = gl_cloud.cloud_api_request("/open/v1/phone/start", {"ids": [args.profile_id]}, api_token=args.token)
            print(json.dumps(res, indent=2))

        elif args.command == "cloud-stop":
            res = gl_cloud.cloud_api_request("/open/v1/phone/stop", {"ids": [args.profile_id]}, api_token=args.token)
            print(json.dumps(res, indent=2))

        elif args.command == "cloud-status":
            res = gl_cloud.cloud_api_request("/open/v1/phone/status", {"ids": [args.profile_id]}, api_token=args.token)
            print(json.dumps(res, indent=2))

        elif args.command == "cloud-api":
            try:
                body = json.loads(args.data)
            except ValueError as e:
                body = None
                res = {"status": "error", "code": "invalid_json", "message": f"--data is not valid JSON: {e}"}
            if body is not None:
                res = gl_cloud.cloud_api_request(args.endpoint, body, api_token=args.token)
            print(json.dumps(res, indent=2))

        elif args.command == "bulk-run":
            client = None if args.no_sheet else gl_sheets.SheetsClient.from_env()
            tasks = gl_bulk.load_tasks_file(args.tasks) if args.tasks else None
            res = gl_bulk.run_bulk(
                tasks=tasks, client=client,
                devices=[d.strip() for d in args.devices.split(",") if d.strip()] if args.devices else None,
                retries=max(0, args.retries), max_workers=args.max_workers, max_tasks=args.max_tasks,
                task_timeout=args.task_timeout, task_delay=args.task_delay, dry_run=args.dry_run, log_dir=args.log_dir)
            print(json.dumps(res, indent=2))
            if res.get("status") == "error":
                sys.exit(1)
            if args.fail_on_error and res.get("failed"):
                sys.exit(4)

        elif args.command == "bulk-check":
            client = gl_sheets.SheetsClient.from_env()
            devices = gl_adb.list_devices(use_cache=False)
            sheet = {"configured": False}
            if client:
                ping = client.ping()
                sheet = {"configured": True, "reachable": bool(ping.get("ok")), "error": ping.get("error")}
            print(json.dumps({"status": "success", "adb_devices": devices, "sheet": sheet}, indent=2))

        elif args.command == "bulk-flush":
            client = gl_sheets.SheetsClient.from_env()
            if not client:
                print(json.dumps({"status": "error", "message": "GEELARK_SHEETS_URL / GEELARK_SHEETS_SECRET not set"}))
                sys.exit(1)
            print(json.dumps(dict(gl_sheets.flush_spool(client, args.log_dir), status="success"), indent=2))

        elif args.command == "adb":
            res = gl_adb.run_adb(args.args)
            print(json.dumps(res, indent=2))

    except LockTimeout as e:
        print(json.dumps({"status": "error", "code": "busy", "error": str(e)}), file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        sys.exit(1)
    finally:
        if lock:
            lock.release()
