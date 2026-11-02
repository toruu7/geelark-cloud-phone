"""App launching, deep links, popup dismissal, recovery and UI-tree dump."""
import os
import time
import gl_adb
import gl_base
import gl_input
import gl_ocr
import gl_vision

# App Launching & Deep-Linking (0.1s Fast-Path)
def deep_link(url_or_uri, target=None):
    """
    Instant 0.1s Deep Linker via Android Intent VIEW:
    Directly opens YouTube videos, web links, or app schemes without UI typing!
    """
    # 1. Try fast ADB intent dispatch
    # Quote: adb joins args and the device shell re-parses them, so a `&` in the URL would truncate it.
    adb_res = gl_adb.run_adb(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", gl_adb.shell_quote(url_or_uri)])
    if adb_res["returncode"] == 0 and "Error" not in adb_res["stderr"]:
        return {"status": "success", "method": "adb_intent", "url": url_or_uri}

    # 2. Visual fallback: Open Chrome -> paste URL -> enter
    open_app("chrome", target=target)
    time.sleep(1.2)
    # Tap omnibox near top (x: 0.5, y: 0.09)
    gl_input.tap(0.5, 0.09, target=target, normalized=True)
    time.sleep(0.4)
    gl_input.type_text(url_or_uri, target=target)
    time.sleep(0.4)
    gl_input.send_key("enter", target=target)
    return {"status": "success", "method": "chrome_visual", "url": url_or_uri}

def open_app(app_name, target=None):
    package = gl_base.COMMON_APPS.get(app_name.lower().strip(), app_name.strip())
    adb_res = gl_adb.run_adb(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])
    if adb_res["returncode"] == 0 and "Events injected: 1" in adb_res["stdout"]:
        return {"status": "success", "method": "adb", "package": package}

    gl_input.send_key("home", target=target)
    time.sleep(0.6)
    gl_input.swipe(0.5, 0.8, 0.5, 0.2, target=target, normalized=True)
    time.sleep(0.8)
    click_res = gl_ocr.click_text_on_screen(app_name, target=target)
    if click_res["status"] == "success":
        return {"status": "success", "method": "visual_ocr", "app": app_name}

    return {"status": "error", "message": f"Could not launch app '{app_name}'"}

def dismiss_popups(target=None):
    common_dismissals = [
        "Skip Ads", "Skip Ad", "Skip in 5s", "Skip trial", "Skip",
        "Not now", "No thanks", "Later", "Cancel", "Close", "Dismiss",
        "Don't allow", "While using the app", "Allow", "OK"
    ]
    cap = gl_vision.capture_phone(target=target, out_path=os.path.join(gl_base.SCRIPT_DIR, ".ocr_cap.png"))
    words = gl_vision.run_ocr(cap["file"])
    for word in common_dismissals:
        word_lower = word.lower()
        for w in words:
            if word_lower in w.get("text", "").lower():
                center_x = w["x"] + (w["w"] / 2)
                center_y = w["y"] + (w["h"] / 2)
                norm_x = center_x / cap["size"][0]
                norm_y = center_y / cap["size"][1]
                gl_input.tap(norm_x, norm_y, target=target, normalized=True)
                return {"status": "success", "dismissed_via": word, "matched_text": w["text"]}
    gl_input.send_key("back", target=target)
    return {"status": "success", "dismissed_via": "back_key"}

def emergency_recover(target=None):
    gl_input.send_key("back", target=target)
    time.sleep(0.4)
    gl_input.send_key("back", target=target)
    time.sleep(0.4)
    gl_input.send_key("home", target=target)
    time.sleep(0.8)
    cap = gl_vision.capture_phone(target=target, out_path=os.path.join(os.getcwd(), "recovered_home.png"))
    return {"status": "recovered", "current_state": cap}

# ADB Integration & UI Tree
# run_adb (timeout-guarded) lives in gl_adb.py and is imported above.
def dump_ui_tree(device=None):
    res = gl_adb.run_adb(["exec-out", "uiautomator", "dump", "/dev/tty"], device=device or gl_base.get_active_adb_device())
    if res["returncode"] != 0 or not res["stdout"]:
        return {"status": "error", "message": "ADB UIAutomator not available."}
    return {"status": "success", "xml": res["stdout"]}
