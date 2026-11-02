"""System status and multi-step / multi-phone orchestration (batch-run, broadcast, batch-profiles)."""
import os
import time
import json
import gl_adb
import gl_apps
import gl_base
import gl_input
import gl_ocr
import gl_prompt
import gl_recipes
import gl_smart
import gl_vision
import gl_win32

def get_system_status():
    wins = gl_win32.list_windows()
    active = gl_base.get_active_target()
    adb_status = gl_adb.run_adb(["devices"])
    adb_devices = [line.strip().split("\t")[0].strip() for line in adb_status.get("stdout", "").splitlines() if "\tdevice" in line]
    
    phone_wins = [w for w in wins if w["is_phone"]]
    app_wins = [w for w in wins if not w["is_phone"]]
    
    return {
        "status": "success",
        "active_profile": active,
        "total_windows": len(wins),
        "phone_windows": [{"hwnd": w["hwnd"], "title": w["title"], "rect": w["rect"]} for w in phone_wins],
        "app_windows": [{"hwnd": w["hwnd"], "title": w["title"], "rect": w["rect"]} for w in app_wins],
        "adb_connected_devices": adb_devices,
        "adb_ready": len(adb_devices) > 0
    }

def execute_batch_steps(steps_data, target=None):
    """Executes a list of action dicts sequentially on target device.
    Accepts JSON file path, raw JSON string, list of dicts, or single dict.
    """
    if isinstance(steps_data, str):
        if os.path.exists(steps_data):
            try:
                with open(steps_data, "r", encoding="utf-8") as f:
                    steps = json.load(f)
            except Exception as e:
                return {"status": "error", "message": f"Failed to parse batch JSON file: {str(e)}"}
        else:
            try:
                steps = json.loads(steps_data)
            except Exception as e:
                return {"status": "error", "message": f"Failed to parse batch JSON string: {str(e)}"}
    elif isinstance(steps_data, dict):
        steps = [steps_data]
    elif isinstance(steps_data, list):
        steps = steps_data
    else:
        return {"status": "error", "message": f"Invalid steps data type: {type(steps_data).__name__}"}

    results = []
    start_time = time.time()

    for idx, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            results.append({"step_index": idx, "status": "error", "message": f"Step {idx} is not an action object"})
            continue

        action = step.get("action", "").lower().strip()
        step_target = step.get("window", step.get("target", target))
        res = {"step_index": idx, "action": action}

        try:
            if action == "sleep":
                dur = float(step.get("duration", step.get("seconds", 1.0)))
                time.sleep(dur)
                res["status"] = "success"
                res["slept"] = dur

            elif action == "tap":
                res["result"] = gl_input.tap(step["x"], step["y"], target=step_target, normalized=step.get("norm", False))

            elif action == "swipe":
                res["result"] = gl_input.swipe(
                    step["x1"], step["y1"], step["x2"], step["y2"],
                    target=step_target,
                    normalized=step.get("norm", False),
                    steps=step.get("steps", 22),
                    duration=step.get("duration", 0.25),
                    human=step.get("human", True)
                )

            elif action == "type":
                res["result"] = gl_input.type_text(step["text"], target=step_target)
                if step.get("enter", False):
                    time.sleep(0.1)
                    gl_input.send_key("enter", target=step_target)

            elif action == "key":
                key_name = step.get("name", step.get("key", "home"))
                res["result"] = gl_input.send_key(key_name, target=step_target)

            elif action == "open-app":
                app_name = step.get("name", step.get("app", ""))
                res["result"] = gl_apps.open_app(app_name, target=step_target)

            elif action == "deep-link":
                url = step.get("url", step.get("link", ""))
                res["result"] = gl_apps.deep_link(url, target=step_target)

            elif action == "click-text":
                query = step.get("query", step.get("text", ""))
                res["result"] = gl_ocr.click_text_on_screen(query, target=step_target)

            elif action == "wait-text":
                query = step.get("query", step.get("text", ""))
                res["result"] = gl_ocr.wait_and_click_text(query, target=step_target, timeout=step.get("timeout", 30.0))

            elif action == "scroll-find":
                query = step.get("query", step.get("text", ""))
                res["result"] = gl_ocr.scroll_find(
                    query,
                    max_swipes=step.get("max_swipes", 5),
                    click=step.get("click", True),
                    target=step_target
                )

            elif action == "dismiss-popup":
                res["result"] = gl_apps.dismiss_popups(target=step_target)

            elif action == "hide-keyboard":
                res["result"] = gl_input.hide_keyboard(target=step_target)

            elif action == "wait-stable":
                res["result"] = gl_vision.wait_screen_stable(target=step_target, timeout=step.get("timeout", 6.0))

            elif action == "capture":
                out = step.get("out", f"batch_step_{idx}.png")
                if step.get("annotate", False):
                    res["result"] = gl_vision.capture_and_annotate(target=step_target, out_path=out, low_token=step.get("low_token", False))
                else:
                    res["result"] = gl_vision.capture_phone(target=step_target, out_path=out, low_token=step.get("low_token", False))

            elif action == "youtube-flow":
                res["result"] = gl_recipes.recipe_youtube_flow(step["url"], click_link=step.get("click_link"), skip_ads=step.get("skip_ads", True), target=step_target)

            elif action == "tiktok-feed":
                res["result"] = gl_recipes.recipe_tiktok_feed(videos=step.get("videos", 5), min_watch=step.get("min_watch", 4.0), max_watch=step.get("max_watch", 10.0), like_ratio=step.get("like_ratio", 0.25), target=step_target)

            elif action == "smart-click":
                query = step.get("query", step.get("text", ""))
                res["result"] = gl_smart.smart_click(query, target=step_target, scroll_fallback=step.get("scroll", True))

            elif action == "prompt":
                p_text = step.get("prompt", step.get("text", ""))
                res["result"] = gl_prompt.execute_natural_prompt(p_text, target=step_target)

            else:
                res["status"] = "error"
                res["message"] = f"Unknown action '{action}'"

            if "status" not in res:
                if isinstance(res.get("result"), dict) and res["result"].get("status") == "error":
                    res["status"] = "error"
                    res["message"] = res["result"].get("message", "Step failed")
                else:
                    res["status"] = "success"

        except Exception as e:
            res["status"] = "error"
            res["error"] = str(e)

        results.append(res)

    return {
        "status": "success",
        "total_steps": len(steps),
        "elapsed_seconds": round(time.time() - start_time, 2),
        "steps": results
    }

def broadcast_action(command_name, command_args=None):
    """Executes an action across ALL open cloud phone windows."""
    if command_args is None:
        command_args = []
    wins = gl_win32.list_windows()
    phones = [w for w in wins if w["is_phone"]]
    if not phones:
        return {"status": "error", "message": "No active phone windows found to broadcast to."}

    results = []
    for p in phones:
        hwnd = p["hwnd"]
        gl_win32.focus_window(hwnd)
        time.sleep(0.1)

        try:
            if command_name == "tap":
                norm = "--norm" in command_args
                coords = [a for a in command_args if a != "--norm"]
                if len(coords) < 2:
                    raise ValueError("Tap broadcast requires x and y coordinates")
                r = gl_input.tap(float(coords[0]), float(coords[1]), target=hwnd, normalized=norm)
            elif command_name == "swipe":
                norm = "--norm" in command_args
                coords = [a for a in command_args if a != "--norm"]
                if len(coords) < 4:
                    raise ValueError("Swipe broadcast requires x1, y1, x2, and y2 coordinates")
                r = gl_input.swipe(float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]), target=hwnd, normalized=norm)
            elif command_name == "key":
                if not command_args:
                    raise ValueError("Key broadcast requires a key name")
                r = gl_input.send_key(command_args[0], target=hwnd)
            elif command_name == "type":
                clean_args = [a for a in command_args if a != "--norm"]
                r = gl_input.type_text(" ".join(clean_args), target=hwnd)
            elif command_name == "open-app":
                if not command_args:
                    raise ValueError("open-app broadcast requires an app name")
                r = gl_apps.open_app(command_args[0], target=hwnd)
            elif command_name == "deep-link":
                if not command_args:
                    raise ValueError("deep-link broadcast requires a URL")
                r = gl_apps.deep_link(command_args[0], target=hwnd)
            elif command_name == "dismiss-popup":
                r = gl_apps.dismiss_popups(target=hwnd)
            elif command_name == "hide-keyboard":
                r = gl_input.hide_keyboard(target=hwnd)
            elif command_name == "recover":
                r = gl_apps.emergency_recover(target=hwnd)
            else:
                r = {"status": "error", "message": f"Command '{command_name}' not supported in broadcast mode"}
            results.append({"phone": p["title"], "hwnd": hwnd, "result": r})
        except Exception as e:
            results.append({"phone": p["title"], "hwnd": hwnd, "error": str(e)})

    return {"status": "success", "broadcast_count": len(phones), "results": results}

def batch_profiles(profiles_input, command_name, command_args=None):
    """Runs a command sequentially across specific profile numbers/names."""
    if command_args is None:
        command_args = []
    wins = gl_win32.list_windows()
    phones = [w for w in wins if w["is_phone"]]
    if not phones:
        return {"status": "error", "message": "No open phone windows found."}

    if profiles_input == "all":
        selected = phones
    else:
        profile_keys = [k.strip().lower() for k in profiles_input.split(",")]
        selected = []
        for pk in profile_keys:
            for p in phones:
                title = p["title"].lower()
                if pk in title or f"#{pk}" in title:
                    if p not in selected:
                        selected.append(p)

    if not selected:
        return {"status": "error", "message": f"No open phone windows matched profiles: {profiles_input}"}

    results = []
    for p in selected:
        hwnd = p["hwnd"]
        gl_win32.focus_window(hwnd)
        time.sleep(0.2)
        try:
            if command_name == "youtube-flow":
                if not command_args:
                    raise ValueError("youtube-flow requires a video URL")
                r = gl_recipes.recipe_youtube_flow(command_args[0], click_link=command_args[1] if len(command_args) > 1 else None, target=hwnd)
            elif command_name == "tiktok-feed":
                v_count = int(command_args[0]) if len(command_args) > 0 else 5
                r = gl_recipes.recipe_tiktok_feed(videos=v_count, target=hwnd)
            elif command_name == "open-app":
                if not command_args:
                    raise ValueError("open-app requires an app name")
                r = gl_apps.open_app(command_args[0], target=hwnd)
            elif command_name == "deep-link":
                if not command_args:
                    raise ValueError("deep-link requires a URL")
                r = gl_apps.deep_link(command_args[0], target=hwnd)
            elif command_name == "dismiss-popup":
                r = gl_apps.dismiss_popups(target=hwnd)
            elif command_name == "recover":
                r = gl_apps.emergency_recover(target=hwnd)
            elif command_name == "key":
                if not command_args:
                    raise ValueError("key requires a key name")
                r = gl_input.send_key(command_args[0], target=hwnd)
            elif command_name == "hide-keyboard":
                r = gl_input.hide_keyboard(target=hwnd)
            elif command_name == "tap":
                norm = "--norm" in command_args
                coords = [a for a in command_args if a != "--norm"]
                if len(coords) < 2:
                    raise ValueError("tap requires x and y coordinates")
                r = gl_input.tap(float(coords[0]), float(coords[1]), target=hwnd, normalized=norm)
            elif command_name == "swipe":
                norm = "--norm" in command_args
                coords = [a for a in command_args if a != "--norm"]
                if len(coords) < 4:
                    raise ValueError("swipe requires x1, y1, x2, and y2 coordinates")
                r = gl_input.swipe(float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]), target=hwnd, normalized=norm)
            elif command_name == "type":
                clean_args = [a for a in command_args if a != "--norm"]
                r = gl_input.type_text(" ".join(clean_args), target=hwnd)
            elif command_name == "batch-run":
                if not command_args:
                    raise ValueError("batch-run requires a JSON file path or steps string")
                r = execute_batch_steps(command_args[0], target=hwnd)
            elif command_name == "click-text":
                if not command_args:
                    raise ValueError("click-text requires a search query")
                r = gl_ocr.click_text_on_screen(command_args[0], target=hwnd)
            elif command_name == "scroll-find":
                if not command_args:
                    raise ValueError("scroll-find requires a search query")
                r = gl_ocr.scroll_find(command_args[0], target=hwnd)
            else:
                r = {"status": "error", "message": f"Command '{command_name}' not supported in batch-profiles mode"}
            results.append({"profile": p["title"], "hwnd": hwnd, "result": r})
        except Exception as e:
            results.append({"profile": p["title"], "hwnd": hwnd, "error": str(e)})

    return {"status": "success", "profiles_processed": len(selected), "results": results}
