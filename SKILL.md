---
name: geelark-cloud-phone
description: Control, automate, and inspect GeeLark cloud phones visually or via ADB. Use to launch profiles, capture phone screens, tap, swipe, type, press navigation buttons, open apps (YouTube, TikTok, Chrome), search videos, skip ads, and click links. Compatible with Claude Code, Hermes, OpenClaw, Codex, and Antigravity.
metadata:
  icon: smartphone
---

# GeeLark Cloud Phone Automation Skill (v4.0 Production & Cost-Optimized)

This skill enables AI agents (**Claude Code, Hermes, OpenClaw, Codex, Antigravity**) to control and automate **GeeLark cloud phones** with maximum time, cost, and token efficiency.

---

## ⚡ Cost & Time Optimization Guide for Agents

To minimize LLM token usage and execution time, use these high-efficiency shortcuts:

| Goal | Low-Cost / Fast-Path Command | Why It's Faster & Cheaper |
| :--- | :--- | :--- |
| **Open Video or Webpage** | `python scripts/geelark.py deep-link "<url>"` | **0.1s instant dispatch** via Android Intent instead of typing or searching. |
| **Find & Click Link down page** | `python scripts/geelark.py scroll-find "http"` | **Saves 80% tokens**: Automatically scrolls and clicks in 1 command instead of 5 visual loops. |
| **Click Elements Accurately** | `python scripts/geelark.py tap-mark <id>` | Taps marked badges from `capture --annotate` without coordinate hallucination. |
| **Save Multimodal Vision Tokens** | `python scripts/geelark.py capture --low-token` | Downsamples screenshot to save ~70% of vision tokens. |
| **Type & Submit** | `python scripts/geelark.py type "Query" --enter` | Combines typing and enter key into a single round trip. |
| **Dismiss Virtual Keyboard** | `python scripts/geelark.py hide-keyboard` | Collapses keyboard so elements beneath it become visible and clickable. |

---

## 🛠️ CLI Command Reference

All commands run through:
```bash
python scripts/geelark.py <command> [options]
```

### 1. Visual Capture & Set-of-Mark (SoM)
```bash
# Capture with numbered overlay badges:
python scripts/geelark.py capture --annotate --out state.png

# Low-token capture for cheap model verification:
python scripts/geelark.py capture --low-token --out state.png

# Tap by mark number:
python scripts/geelark.py tap-mark 12
```

### 2. Fast Navigation & App Launching
```bash
# Instant App Launch (youtube, tiktok, chrome, settings):
python scripts/geelark.py open-app youtube

# 0.1s Instant Link/Video Opener:
python scripts/geelark.py deep-link "https://www.youtube.com/watch?v=Bm84BAtOfQw"
```

### 3. Native Windows OCR (`Windows.Media.Ocr`)
```bash
# Locate words on screen:
python scripts/geelark.py find-text "Description"

# Click text by label:
python scripts/geelark.py click-text "Skip"

# Wait for text to appear and immediately tap it (Ad-Watcher):
python scripts/geelark.py wait-text "Skip" --timeout 30.0

# Scroll down until text appears and click it:
python scripts/geelark.py scroll-find "ceritypartners.com" --max-swipes 5
```

### 4. Input & Navigation
```bash
# Tap normalized (0.0 to 1.0):
python scripts/geelark.py tap 0.5 0.5 --norm

# Smooth swipe:
python scripts/geelark.py swipe 0.5 0.8 0.5 0.2 --norm

# Type text:
python scripts/geelark.py type "Search query" --enter

# Navigation keys:
python scripts/geelark.py key home
python scripts/geelark.py key back
python scripts/geelark.py key recent

# Hide virtual keyboard:
python scripts/geelark.py hide-keyboard
```

### 5. Self-Healing & Failsafes
```bash
# Wait for screen to stop rendering/buffering:
python scripts/geelark.py wait-stable --timeout 6.0

# Auto-dismiss popups / system modals:
python scripts/geelark.py dismiss-popup

# Emergency recovery to clean home screen:
python scripts/geelark.py recover
```

---

## 🛡️ Edge Cases & Handling Guide

| Scenario | Solution / Prevention |
| :--- | :--- |
| **Virtual keyboard blocking buttons** | Run `python scripts/geelark.py hide-keyboard` (presses Back without leaving screen). |
| **In-stream pre-roll ads** | Run `python scripts/geelark.py wait-text "Skip" --timeout 15.0`. |
| **YouTube Premium / promo modal** | Run `python scripts/geelark.py dismiss-popup` (handles "Not now", "No thanks", "Skip trial", etc.). |
| **Sponsored search results** | When searching manually, verify the item does NOT contain "Ad" or "Sponsored" badge before clicking. (Or use `deep-link` to bypass search entirely). |
| **Video description collapsed** | Click "...more" or the video title area to expand, then `scroll-find "http"`. |
| **Network latency / UI buffering** | Run `python scripts/geelark.py wait-stable` before tapping dynamic buttons. |
| **Unknown state / freezing** | Run `python scripts/geelark.py recover` to return to home screen cleanly. |

---

## 🔄 n8n & Docker Automation Triggering

This skill is fully triggerable from **n8n** (running locally in Docker or on Windows):
1. For Docker n8n, start the bridge: `python scripts/webhook_bridge.py` (runs on port 5055).
2. Import `examples/n8n_trigger.json` into n8n.
3. Call the webhook via HTTP POST with `{"command": "deep-link", "args": ["<url>"]}`.
4. See [examples/README.md](file:///C:/Users/Backspace/.gemini/config/skills/geelark-cloud-phone/examples/README.md) for full setup instructions.

---

## 🎯 Recommended High-Speed Agent Workflow

### Example: Watch Video, Skip Ad, and Click Description Link
```bash
# 1. Instant jump to video (0.1s):
python scripts/geelark.py deep-link "https://www.youtube.com/watch?v=Bm84BAtOfQw"

# 2. Wait for playback & auto-skip any pre-roll ads:
python scripts/geelark.py wait-text "Skip" --timeout 15.0

# 3. Expand description box:
python scripts/geelark.py click-text "more"

# 4. Scroll and click target link in description:
python scripts/geelark.py scroll-find "http" --max-swipes 3

# 5. Verify landing page:
python scripts/geelark.py capture --low-token --out landing.png
```
