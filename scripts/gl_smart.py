"""Multi-path element grounding (smart-click)."""
import re
import gl_adb
import gl_apps
import gl_base
import gl_input
import gl_ocr

# Pre-compiled Regular Expressions for Zero-Overhead Parsing
RE_XML_NODE = re.compile(r'<node[^>]+>', re.IGNORECASE)

RE_XML_TEXT = re.compile(r'text="([^"]*)"')

RE_XML_DESC = re.compile(r'content-desc="([^"]*)"')

RE_XML_BOUNDS = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')

# Multi-Path Fallback Routing, Cloud API & Natural Language Engine
KNOWN_UI_ANCHORS = {
    "home": (0.50, 0.97),
    "back": (0.18, 0.97),
    "recent": (0.82, 0.97),
    "appswitch": (0.82, 0.97),
    "omnibox": (0.50, 0.09),
    "address bar": (0.50, 0.09),
    "url bar": (0.50, 0.09),
    "search bar": (0.50, 0.09),
    "like": (0.92, 0.52),
    "heart": (0.92, 0.52),
    "center": (0.50, 0.50),
    "play": (0.50, 0.50),
    "pause": (0.50, 0.50),
}

def smart_click(query, target=None, scroll_fallback=True):
    """Multi-Path Fallback Element Grounding & Clicking (inspired by MobileRun & AppAgent v2):
    Path 1: Structural UI Accessibility Tree (ADB UIAutomator XML bounds)
    Path 2: Local Windows Native OCR (click_text_on_screen)
    Path 3: Autonomous Scroll-Find OCR Loop (scroll_find with skip_initial_check=True)
    Path 4: Pre-Calibrated Normalized Coordinate Anchor Fallback
    """
    paths_tried = []
    q_clean = str(query).strip()
    q_lower = q_clean.lower()

    # Path 1: ADB UI Automator Accessibility Tree
    paths_tried.append("adb_ui_tree")
    try:
        ui_res = gl_apps.dump_ui_tree()
        if ui_res.get("status") == "success" and ui_res.get("xml"):
            xml_str = ui_res["xml"]
            for node_match in RE_XML_NODE.finditer(xml_str):
                node_tag = node_match.group(0)
                text_m = RE_XML_TEXT.search(node_tag)
                desc_m = RE_XML_DESC.search(node_tag)
                bounds_m = RE_XML_BOUNDS.search(node_tag)
                node_text = (text_m.group(1) if text_m else "") + " " + (desc_m.group(1) if desc_m else "")
                if q_lower in node_text.lower() and bounds_m:
                    x1, y1, x2, y2 = map(int, bounds_m.groups())
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    tap_args = ["shell", "input", "tap", str(cx), str(cy)]
                    adb_dev = gl_base.get_active_adb_device()
                    adb_tap = gl_adb.run_adb(tap_args, device=adb_dev) if adb_dev else gl_adb.run_adb(tap_args)
                    if adb_tap.get("returncode") == 0:
                        return {
                            "status": "success",
                            "action": "smart-click",
                            "path": "adb_ui_tree",
                            "matched": node_text.strip(),
                            "coords": [cx, cy],
                            "paths_tried": paths_tried
                        }
    except Exception:
        pass

    # Path 2: Local Windows Native OCR
    paths_tried.append("local_ocr")
    try:
        ocr_res = gl_ocr.click_text_on_screen(q_clean, target=target)
        if ocr_res.get("status") == "success":
            return {
                "status": "success",
                "action": "smart-click",
                "path": "local_ocr",
                "matched": ocr_res.get("matched", q_clean),
                "coords": ocr_res.get("coords"),
                "paths_tried": paths_tried
            }
    except Exception:
        pass

    # Path 3: Autonomous Scroll-Find Loop (skip_initial_check=True avoids re-OCR-ing the current screen)
    if scroll_fallback:
        paths_tried.append("scroll_find_ocr")
        try:
            sf_res = gl_ocr.scroll_find(q_clean, max_swipes=3, click=True, target=target, skip_initial_check=True)
            if sf_res.get("status") == "success":
                return {
                    "status": "success",
                    "action": "smart-click",
                    "path": "scroll_find_ocr",
                    "matched": sf_res.get("matched", q_clean),
                    "coords": sf_res.get("coords"),
                    "swipes_performed": sf_res.get("swipes_performed", 0),
                    "paths_tried": paths_tried
                }
        except Exception:
            pass

    # Path 4: Pre-Calibrated Normalized Coordinate Anchor
    paths_tried.append("normalized_anchor")
    if q_lower in KNOWN_UI_ANCHORS:
        nx, ny = KNOWN_UI_ANCHORS[q_lower]
        try:
            gl_input.tap(nx, ny, target=target, normalized=True)
            return {
                "status": "success",
                "action": "smart-click",
                "path": "normalized_anchor",
                "matched": q_lower,
                "coords": [nx, ny],
                "paths_tried": paths_tried
            }
        except Exception as e:
            return {"status": "error", "message": f"Anchor tap failed: {str(e)}", "paths_tried": paths_tried}

    return {
        "status": "error",
        "action": "smart-click",
        "message": f"All fallback paths failed to locate element '{q_clean}'",
        "paths_tried": paths_tried
    }
