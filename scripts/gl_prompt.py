"""Deterministic plain-text instruction transpiler."""
import re
import gl_apps
import gl_base
import gl_input
import gl_orch
import gl_recipes
import gl_smart

RE_PROFILE_NUM = re.compile(r'(?:profile|phone|window|#)\s*(\d+)')

RE_URL = re.compile(r"(https?://[^\s\"'<>]+)")

RE_VIDEO_COUNT = re.compile(r'(\d+)\s*(?:tiktok|video|vid|clip)')

RE_OPEN_APP = re.compile(r'\b(?:open|launch|start)\s+(youtube|tiktok|chrome|settings|playstore|files)\b')

RE_TYPE_TEXT = re.compile(r"(?:type|write|input|search\s+for)\s+[\"']?([^\"']+)[\"']?", re.IGNORECASE)

RE_CLICK_TEXT = re.compile(r"(?:click|tap|press|select)\s+(?:on\s+)?[\"']?([^\"']+)[\"']?", re.IGNORECASE)

def execute_natural_prompt(prompt_text, target=None):
    """Built-in Plain-Text Semantic Intent Transpiler:
    Translates casual natural language prompts (from x.ai/bot, Telegram, small LLMs, or humans)
    into deterministic GeeLark recipes, batch steps, or multi-path actions.
    """
    if not prompt_text or not str(prompt_text).strip():
        return {"status": "error", "message": "Empty prompt provided"}

    raw = str(prompt_text).strip()
    low = raw.lower()

    # 1. Extract profile / phone number if mentioned (e.g., "on profile 4", "phone #2")
    prof_match = RE_PROFILE_NUM.search(low)
    eff_target = target
    profile_locked = None
    if prof_match:
        profile_locked = prof_match.group(1)
        eff_target = profile_locked
        gl_base.set_active_target(profile_locked)

    # 2. Extract URL if present
    url_match = RE_URL.search(raw)
    extracted_url = url_match.group(1) if url_match else None

    # 3. Route by semantic intent
    # Case A: TikTok Warmup / Feed
    if "tiktok" in low and any(w in low for w in ["watch", "feed", "warm", "video", "scroll", "swipe", "like"]):
        vid_match = RE_VIDEO_COUNT.search(low)
        videos = int(vid_match.group(1)) if vid_match else 5
        like_ratio = 0.5 if "like" in low else 0.25
        res = gl_recipes.recipe_tiktok_feed(videos=videos, like_ratio=like_ratio, target=eff_target)
        return {"status": "success", "transpiled_intent": "tiktok-feed", "profile": eff_target, "result": res}

    # Case B: YouTube Flow
    if ("youtube" in low or (extracted_url and ("youtube.com" in extracted_url or "youtu.be" in extracted_url))):
        url = extracted_url or "https://www.youtube.com"
        click_link = "http" if any(w in low for w in ["link", "description", "desc"]) else None
        res = gl_recipes.recipe_youtube_flow(url, click_link=click_link, skip_ads=True, target=eff_target)
        return {"status": "success", "transpiled_intent": "youtube-flow", "profile": eff_target, "result": res}

    # Case C: Direct URL Deep-Link
    if extracted_url:
        res = gl_apps.deep_link(extracted_url, target=eff_target)
        return {"status": "success", "transpiled_intent": "deep-link", "profile": eff_target, "result": res}

    # Case D: Dismiss Popups / Skip Ads
    if any(w in low for w in ["dismiss", "popup", "pop-up", "skip ad", "close ad", "modal"]):
        if "all" in low or "every" in low or "broadcast" in low:
            res = gl_orch.broadcast_action("dismiss-popup", [])
            return {"status": "success", "transpiled_intent": "broadcast:dismiss-popup", "result": res}
        res = gl_apps.dismiss_popups(target=eff_target)
        return {"status": "success", "transpiled_intent": "dismiss-popup", "profile": eff_target, "result": res}

    # Case E: Status Check
    if any(w in low for w in ["status", "what is open", "connected", "list window", "check phone"]):
        res = gl_orch.get_system_status()
        return {"status": "success", "transpiled_intent": "status", "result": res}

    # Case F: Emergency Recover
    if any(w in low for w in ["recover", "emergency", "reset phone", "clean home"]):
        res = gl_apps.emergency_recover(target=eff_target)
        return {"status": "success", "transpiled_intent": "recover", "profile": eff_target, "result": res}

    # Case G: Navigation Keys (Home, Back, Keyboard)
    if "hide keyboard" in low or "close keyboard" in low:
        res = gl_input.hide_keyboard(target=eff_target)
        return {"status": "success", "transpiled_intent": "hide-keyboard", "profile": eff_target, "result": res}
    if any(w in low for w in ["go home", "home screen", "press home"]):
        res = gl_input.send_key("home", target=eff_target)
        return {"status": "success", "transpiled_intent": "key:home", "profile": eff_target, "result": res}
    if any(w in low for w in ["go back", "press back"]):
        res = gl_input.send_key("back", target=eff_target)
        return {"status": "success", "transpiled_intent": "key:back", "profile": eff_target, "result": res}

    # Case H: Open App
    app_match = RE_OPEN_APP.search(low)
    if app_match:
        app_name = app_match.group(1)
        res = gl_apps.open_app(app_name, target=eff_target)
        return {"status": "success", "transpiled_intent": f"open-app:{app_name}", "profile": eff_target, "result": res}

    # Case I: Type Text
    type_match = RE_TYPE_TEXT.search(raw)
    if type_match:
        txt = type_match.group(1).strip()
        res = gl_input.type_text(txt, target=eff_target)
        if "enter" in low or "search" in low or "submit" in low:
            gl_input.send_key("enter", target=eff_target)
        return {"status": "success", "transpiled_intent": "type", "text": txt, "profile": eff_target, "result": res}

    # Case J: Click / Tap Element by Name (Smart Multi-Path Click)
    click_match = RE_CLICK_TEXT.search(raw)
    if click_match:
        query = click_match.group(1).strip()
        res = gl_smart.smart_click(query, target=eff_target)
        return {"status": "success" if res.get("status") == "success" else "error", "transpiled_intent": "smart-click", "query": query, "profile": eff_target, "result": res}

    # Case K: Only profile switch requested ("use profile 4", "switch to phone 4")
    if profile_locked:
        return {"status": "success", "transpiled_intent": "use", "active_profile": profile_locked}

    # Default Fallback: Try smart_click with the raw query
    res = gl_smart.smart_click(raw, target=eff_target, scroll_fallback=False)
    return {
        "status": res.get("status", "error"),
        "transpiled_intent": "fallback_smart_click",
        "query": raw,
        "profile": eff_target,
        "result": res
    }
