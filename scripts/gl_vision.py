"""Phone screenshot capture, OCR invocation, Set-of-Mark annotation and screen-stability checks."""
import os
import time
import json
import subprocess
import gl_base
import gl_input
import gl_win32

def capture_phone(target=None, out_path=None, crop_phone_screen=True, low_token=False):
    """
    Capture phone window.
    If low_token is True, downsamples the image to ~720p height, saving up to 70% in multimodal token costs.
    """
    if not gl_base.IS_WINDOWS or not gl_base.user32:
        raise RuntimeError("Screen capture is only supported on Windows host.")
    if gl_base.Image is None:
        raise RuntimeError("Pillow is required for image operations. Install with 'pip install pillow'")
    win = gl_win32.find_target_window(target, prefer_phone=True)
    if not win:
        raise RuntimeError("No GeeLark or Phone window found. Make sure GeeLark is open.")
    hwnd = win["hwnd"]
    gl_win32.focus_window(hwnd)
    time.sleep(0.05)
    r = win["rect"]
    img = gl_win32.capture_rect(r["left"], r["top"], r["width"], r["height"])
    try:
        if crop_phone_screen and win["is_phone"]:
            top_offset = 30
            right_toolbar_width = 44
            phone_w = r["width"] - right_toolbar_width
            phone_h = r["height"] - top_offset
            if phone_w > 50 and phone_h > 50:
                cropped = img.crop((0, top_offset, phone_w, top_offset + phone_h))
                img.close()
                img = cropped

        if low_token and img.height > 800:
            ratio = 800 / img.height
            new_w = int(img.width * ratio)
            resized = img.resize((new_w, 800), gl_base.Image.Resampling.LANCZOS)
            img.close()
            img = resized

        if not out_path:
            out_path = os.path.join(os.getcwd(), "phone_screen.png")
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        img.save(out_path, optimize=True)
        size = [img.width, img.height]
    finally:
        img.close()
    return {
        "status": "success",
        "file": os.path.abspath(out_path),
        "window": win["title"],
        "size": size
    }

def run_ocr(image_path):
    if not os.path.exists(gl_base.OCR_HELPER_PATH):
        return []
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", gl_base.OCR_HELPER_PATH,
        "-ImagePath", os.path.abspath(image_path)
    ]
    res = subprocess.run(cmd, capture_output=True)
    try:
        stdout_text = res.stdout.decode('utf-8', errors='replace').strip()
        return json.loads(stdout_text, strict=False)
    except Exception:
        return []

def capture_and_annotate(target=None, out_path=None, low_token=False):
    """
    Set-of-Mark (SoM): Captures phone, overlays numbered badges,
    and returns a compact text summary of all marks so the agent
    can act immediately without analyzing pixels!
    """
    clean_cap = capture_phone(target=target, out_path=out_path, low_token=low_token)
    img_path = clean_cap["file"]
    words = run_ocr(img_path)

    with gl_base.Image.open(img_path) as src_img:
        img = src_img.convert("RGB")
    try:
        draw = gl_base.ImageDraw.Draw(img)

        filtered = [w for w in words if len(w.get("text", "").strip()) > 1]
        marks = {}
        summary_list = []

        for idx, w in enumerate(filtered, 1):
            x, y, bw, bh = w["x"], w["y"], w["w"], w["h"]
            center_x = x + (bw / 2)
            center_y = y + (bh / 2)
            norm_x = round(center_x / img.width, 3)
            norm_y = round(center_y / img.height, 3)

            mark_data = {
                "text": w["text"],
                "box": [x, y, bw, bh],
                "norm": [norm_x, norm_y]
            }
            marks[str(idx)] = mark_data
            summary_list.append(f"[{idx}] \"{w['text']}\" ({norm_x}, {norm_y})")

            draw.rectangle([x, y, x + bw, y + bh], outline="#00E5FF", width=2)
            draw.rectangle([x, max(0, y - 14), x + 20, y], fill="#00E5FF")
            draw.text((x + 2, max(0, y - 14)), str(idx), fill="black")

        annotated_path = img_path.replace(".png", "_annotated.png") if ".png" in img_path else img_path + "_annotated.png"
        img.save(annotated_path, optimize=True)
    finally:
        img.close()

    gl_base._write_json_atomic(gl_base.MARKS_CACHE_PATH, {"window": clean_cap["window"], "marks": marks})

    return {
        "status": "success",
        "clean_image": clean_cap["file"],
        "annotated_image": os.path.abspath(annotated_path),
        "total_marks": len(marks),
        "quick_summary": summary_list[:25],
        "marks": marks
    }

def tap_mark(mark_id, target=None):
    """Tap a numbered mark from previous 'capture --annotate'."""
    if not os.path.exists(gl_base.MARKS_CACHE_PATH):
        return {"status": "error", "message": "No marks cache found. Run 'capture --annotate' first."}
    try:
        with open(gl_base.MARKS_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"status": "error", "message": f"Failed to read marks cache: {str(e)}"}
    marks = data.get("marks", {})
    mark = marks.get(str(mark_id))
    if not mark:
        return {"status": "error", "message": f"Mark '{mark_id}' not found in active marks."}
    norm_x, norm_y = mark["norm"]
    return gl_input.tap(norm_x, norm_y, target=target, normalized=True)

# Dynamic Stability & Verification
def wait_screen_stable(target=None, timeout=6.0, poll_interval=0.35, threshold=0.015):
    if not gl_base.IS_WINDOWS or not gl_base.user32:
        raise RuntimeError("Screen stability check is only supported on Windows host.")
    if gl_base.Image is None:
        raise RuntimeError("Pillow is required for image operations. Install with 'pip install pillow'")
    start_time = time.time()
    last_img = None
    temp_path = os.path.join(gl_base.SCRIPT_DIR, ".temp_stable.png")
    try:
        while (time.time() - start_time) < timeout:
            res = capture_phone(target=target, out_path=temp_path)
            img = gl_base.Image.open(res["file"])
            if last_img is not None:
                diff = gl_base.ImageChops.difference(img, last_img)
                try:
                    diff_pixels = sum(1 for p in diff.getdata() if any(c > 20 for c in p))
                    ratio = diff_pixels / (img.width * img.height)
                finally:
                    diff.close()
                last_img.close()
                last_img = None
                if ratio < threshold:
                    img.close()
                    return {"status": "success", "stable": True, "elapsed": round(time.time() - start_time, 2)}
            last_img = img
            time.sleep(poll_interval)
        return {"status": "success", "stable": False, "timeout": timeout}
    finally:
        if last_img is not None:
            try:
                last_img.close()
            except Exception:
                pass
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
