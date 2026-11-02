"""OCR-driven find / click / wait / scroll-find actions."""
import os
import time
import gl_base
import gl_input
import gl_vision

# OCR Search, Click, & Autonomous Scroll-Find
def find_text_on_screen(query, target=None):
    cap = gl_vision.capture_phone(target=target, out_path=os.path.join(gl_base.SCRIPT_DIR, ".ocr_cap.png"))
    words = gl_vision.run_ocr(cap["file"])
    query_lower = query.lower().strip()
    matches = []
    for w in words:
        if query_lower in w.get("text", "").lower():
            center_x = w["x"] + (w["w"] / 2)
            center_y = w["y"] + (w["h"] / 2)
            norm_x = center_x / cap["size"][0]
            norm_y = center_y / cap["size"][1]
            matches.append({
                "text": w["text"],
                "box": [w["x"], w["y"], w["w"], w["h"]],
                "center": [center_x, center_y],
                "norm_center": [round(norm_x, 3), round(norm_y, 3)]
            })
    return {"status": "success", "query": query, "matches": matches, "count": len(matches)}

def click_text_on_screen(query, target=None):
    res = find_text_on_screen(query, target=target)
    if not res["matches"]:
        return {"status": "error", "message": f"Text '{query}' not found on phone screen"}
    match = res["matches"][0]
    norm_x, norm_y = match["norm_center"]
    tap_res = gl_input.tap(norm_x, norm_y, target=target, normalized=True)
    return {"status": "success", "action": "click-text", "matched": match["text"], "coords": [norm_x, norm_y], "tap_result": tap_res}

def wait_and_click_text(query, target=None, timeout=30.0, poll_interval=1.2):
    start_time = time.time()
    while (time.time() - start_time) < timeout:
        res = find_text_on_screen(query, target=target)
        if res["matches"]:
            match = res["matches"][0]
            norm_x, norm_y = match["norm_center"]
            gl_input.tap(norm_x, norm_y, target=target, normalized=True)
            return {"status": "success", "clicked": match["text"], "coords": [norm_x, norm_y], "elapsed": round(time.time() - start_time, 2)}
        time.sleep(poll_interval)
    return {"status": "error", "message": f"Timeout waiting for text '{query}'"}

def scroll_find(query, max_swipes=5, click=True, target=None, skip_initial_check=False):
    """
    Autonomous Cost/Time Saver:
    Repeatedly scans for query. If found, clicks it immediately.
    If not, smoothly swipes down and repeats. Accomplishes what used to take 5 agent turns in 1 call!
    When skip_initial_check is True, skips OCR on the initial un-scrolled screen (saving 1 redundant capture+OCR pass).
    """
    for swipe_idx in range(max_swipes + 1):
        if not (swipe_idx == 0 and skip_initial_check):
            res = find_text_on_screen(query, target=target)
            if res["matches"]:
                match = res["matches"][0]
                norm_x, norm_y = match["norm_center"]
                if click:
                    gl_input.tap(norm_x, norm_y, target=target, normalized=True)
                return {
                    "status": "success",
                    "found": True,
                    "clicked": click,
                    "matched": match["text"],
                    "coords": [norm_x, norm_y],
                    "swipes_performed": swipe_idx
                }
        if swipe_idx < max_swipes:
            # Swipe up to scroll down
            gl_input.swipe(0.5, 0.72, 0.5, 0.35, target=target, normalized=True)
            time.sleep(0.8)

    return {"status": "error", "found": False, "swipes_performed": max_swipes, "message": f"Could not find '{query}' after {max_swipes} scrolls"}
