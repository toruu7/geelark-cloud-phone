"""One-command compound recipes (YouTube flow, TikTok feed)."""
import time
import random
import gl_apps
import gl_input
import gl_ocr

# Automated Compound Recipes (One-Click Flows)
def recipe_youtube_flow(url, click_link=None, skip_ads=True, target=None):
    """Complete 1-click autonomous YouTube recipe:
    1. Instant deep link (0.1s)
    2. Waits for playback & auto-skips any pre-roll ads
    3. Expands description if click_link requested
    4. Scrolls and clicks the link via local OCR
    """
    start_time = time.time()
    steps = []
    
    # 1. Deep link
    dl = gl_apps.deep_link(url, target=target)
    steps.append({"step": "deep-link", "result": dl})
    time.sleep(1.8)
    
    # 2. Skip ads
    if skip_ads:
        ad_res = gl_ocr.wait_and_click_text("Skip", target=target, timeout=12.0, poll_interval=1.0)
        if ad_res.get("status") == "success":
            steps.append({"step": "skip-ad", "result": ad_res})
    
    # 3. Dismiss any premium promos
    gl_apps.dismiss_popups(target=target)
    
    # 4. If click_link, expand description and find link
    if click_link:
        time.sleep(0.6)
        more_res = gl_ocr.click_text_on_screen("more", target=target)
        steps.append({"step": "expand-description", "result": more_res})
        time.sleep(0.8)
        
        query = click_link if click_link != "true" else "http"
        find_res = gl_ocr.scroll_find(query, max_swipes=4, click=True, target=target)
        steps.append({"step": "click-link", "result": find_res})
        
    return {
        "status": "success",
        "recipe": "youtube-flow",
        "url": url,
        "elapsed_seconds": round(time.time() - start_time, 2),
        "steps": steps
    }

def recipe_tiktok_feed(videos=5, min_watch=4.0, max_watch=10.0, like_ratio=0.25, target=None):
    """Autonomous TikTok human-warmup recipe:
    - Opens TikTok
    - Watches N videos for realistic random durations
    - Performs natural Bézier vertical swipes
    - Randomly double-taps to like based on like_ratio
    """
    import random
    start_time = time.time()
    gl_apps.open_app("tiktok", target=target)
    time.sleep(3.0)
    gl_apps.dismiss_popups(target=target)
    
    actions = []
    for i in range(1, videos + 1):
        watch_time = round(random.uniform(min_watch, max_watch), 1)
        time.sleep(watch_time)
        
        liked = False
        if random.random() < like_ratio:
            gl_input.tap(0.5, 0.5, target=target, normalized=True)
            time.sleep(0.08)
            gl_input.tap(0.5, 0.5, target=target, normalized=True)
            liked = True
            
        gl_input.swipe(0.5, 0.78, 0.5, 0.22, target=target, normalized=True, human=True)
        actions.append({"video_index": i, "watch_seconds": watch_time, "liked": liked})
        
    return {
        "status": "success",
        "recipe": "tiktok-feed",
        "videos_watched": videos,
        "actions": actions,
        "elapsed_seconds": round(time.time() - start_time, 2)
    }
