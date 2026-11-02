---
name: geelark-cloud-phone
description: Control, automate, and inspect GeeLark cloud phones visually or via ADB. Use to launch profiles, capture phone screens, tap, swipe, type, press navigation buttons, open apps (YouTube, TikTok, Chrome), search videos, skip ads, and click links. Compatible with Claude Code, Hermes, OpenClaw, Codex, and Antigravity.
tags:
  - geelark
  - cloud-phone
  - android-automation
  - mobile-automation
  - mobile-agent
  - agent-skill
  - claude-code
  - antigravity
  - hermes-agent
  - openclaw
  - codex
  - adb
  - ocr
  - n8n
  - set-of-mark
  - antidetect
  - tiktok-automation
  - youtube-automation
  - social-media-automation
  - bot-detection-bypass
metadata:
  icon: smartphone
  author: toruu7
  version: "4.2.0"
  category: mobile-automation
  license: MIT
  repository: https://github.com/toruu7/geelark-cloud-phone
---

# GeeLark Cloud Phone Automation Skill (v4.2 Universal Agent & Multi-Path Edition)

This skill enables **ANY AI agent** (**Claude Code, Claude Desktop, Antigravity, Cursor, Windsurf, x.ai/bot Grok Bot, OpenClaw, Hermes, OpenAI Codex/Custom GPTs, Cline, Roo Code, LangChain, CrewAI, Dify, n8n**) to control and automate **GeeLark cloud phones** with automatic multi-path fallback routing, zero-token local OCR, and anti-bot Bézier physics.

---

## ⚡ Cost & Time Optimization Guide for Agents

To minimize LLM token usage and execution time, use these high-efficiency shortcuts:

| Goal | Low-Cost / Fast-Path Command | Why It's Faster & Cheaper |
| :--- | :--- | :--- |
| **Plain-Text Natural Instruction** | `python scripts/geelark.py prompt "watch 5 tiktoks on profile 4"` | **Zero schema overhead**: Deterministic local transpiler maps English directly to recipes. |
| **Multi-Path Smart Click** | `python scripts/geelark.py smart-click "Skip"` | **4-Layer Fallback**: Tries ADB XML UI Tree $\rightarrow$ Local OCR $\rightarrow$ Scroll-Find $\rightarrow$ Anchor. |
| **Ensure Device Ready** | `python scripts/geelark.py ensure-device -w 4` | **5-Layer Lifecycle**: Cached Window $\rightarrow$ Restore Minimized $\rightarrow$ Scan $\rightarrow$ Cloud API Boot $\rightarrow$ Desktop Launch. |
| **Export Agent Tool Schemas** | `python scripts/geelark.py export-schema -f xai` | Exports ready-to-import tool schemas for `x.ai/bot`, OpenAI, MCP, and OpenAPI 3.1. |
| **Inspect All Skill Capabilities** | `python scripts/geelark.py features` | **Zero guesswork**: Full manifest of commands, recipes, batch actions, and configuration. |
| **Set Active Profile Once** | `python scripts/geelark.py use 4` | **Zero repetitive flags**: Automatically targets Profile 4 across all commands without `--window`. |
| **Run Multi-Step Action Lists** | `python scripts/geelark.py batch-run workflow.json` | **Zero LLM round-trip latency**: Executes sequences (taps, swipes, deep links, OCR checks) locally in 1 turn. |
| **Broadcast Across All Phones** | `python scripts/geelark.py broadcast dismiss-popup` | Multicasts an action (or key/deep-link) to all open phone windows simultaneously. |
| **Multi-Profile Automation** | `python scripts/geelark.py batch-profiles -p 1,2,4 tiktok-feed 5` | Runs commands or recipes sequentially across multiple profiles in one execution. |
| **1-Click Full YouTube Automation** | `python scripts/geelark.py youtube-flow "<url>" --click-link "http"` | **1 turn execution**: Deep links, auto-skips ads, expands description, and clicks the link! |
| **1-Click TikTok Account Warmup** | `python scripts/geelark.py tiktok-feed --videos 5` | **Anti-ban**: Watches 5 videos with realistic pauses and human Bézier gesture curves. |
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

### 1. Profile Target Management & Status
```bash
# Inspect all skill capabilities, supported batch actions, and configuration:
python scripts/geelark.py features
python scripts/geelark.py features --json

# Set active profile (persists across commands so you never need -w again):
python scripts/geelark.py use 4

# View connected phones, active profile, and ADB status:
python scripts/geelark.py status

# List all open windows:
python scripts/geelark.py list-windows
```

### 2. Batch Actions & Multi-Phone Automation
```bash
# Execute a sequence of actions from a JSON file:
python scripts/geelark.py batch-run examples/sample_batch.json

# Execute an inline JSON batch sequence:
python scripts/geelark.py batch-run '[{"action":"dismiss-popup"},{"action":"deep-link","url":"https://youtube.com/watch?v=Bm84BAtOfQw"},{"action":"wait-text","query":"Skip"}]'

# Broadcast an action across ALL open phone windows at once:
python scripts/geelark.py broadcast dismiss-popup
python scripts/geelark.py broadcast key home
python scripts/geelark.py broadcast deep-link "https://youtube.com/watch?v=Bm84BAtOfQw"

# Run a command or recipe sequentially across specific profiles or all profiles:
python scripts/geelark.py batch-profiles --profiles 1,2,4 tiktok-feed 5
python scripts/geelark.py batch-profiles --profiles all dismiss-popup
```

#### Supported Batch Actions (`batch-run`):
- `tap`: `{"action": "tap", "x": 0.5, "y": 0.5, "norm": true}`
- `swipe`: `{"action": "swipe", "x1": 0.5, "y1": 0.8, "x2": 0.5, "y2": 0.2, "norm": true, "human": true}`
- `type`: `{"action": "type", "text": "hello", "enter": true}`
- `key`: `{"action": "key", "name": "home"}`
- `open-app`: `{"action": "open-app", "name": "youtube"}`
- `deep-link`: `{"action": "deep-link", "url": "https://..."}`
- `click-text`: `{"action": "click-text", "query": "Sign in"}`
- `wait-text`: `{"action": "wait-text", "query": "Skip", "timeout": 15.0}`
- `scroll-find`: `{"action": "scroll-find", "query": "https://", "max_swipes": 5}`
- `dismiss-popup`: `{"action": "dismiss-popup"}`
- `hide-keyboard`: `{"action": "hide-keyboard"}`
- `wait-stable`: `{"action": "wait-stable", "timeout": 6.0}`
- `sleep`: `{"action": "sleep", "duration": 1.5}`
- `capture`: `{"action": "capture", "out": "state.png"}`

### 3. 1-Click Automated Recipes
```bash
# 1-Click YouTube flow (plays video, skips pre-roll ads, expands description, clicks link):
python scripts/geelark.py youtube-flow "https://www.youtube.com/watch?v=Bm84BAtOfQw" --click-link "http"

# 1-Click TikTok warmup (watches 5 videos, realistic timing, human Bézier curve swipes):
python scripts/geelark.py tiktok-feed --videos 5 --min-watch 4.0 --max-watch 12.0 --like-ratio 0.3
```

### 4. Visual Capture & Set-of-Mark (SoM)
```bash
# Capture with numbered overlay badges:
python scripts/geelark.py capture --annotate --out state.png

# Low-token capture for cheap model verification:
python scripts/geelark.py capture --low-token --out state.png

# Tap by mark number:
python scripts/geelark.py tap-mark 12
```

### 5. Fast Navigation & App Launching
```bash
# Instant App Launch (youtube, tiktok, chrome, settings):
python scripts/geelark.py open-app youtube

# 0.1s Instant Link/Video Opener:
python scripts/geelark.py deep-link "https://www.youtube.com/watch?v=Bm84BAtOfQw"
```

### 6. Native Windows OCR (`Windows.Media.Ocr`)
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

### 7. Input & Natural Human Gestures
```bash
# Tap normalized (0.0 to 1.0):
python scripts/geelark.py tap 0.5 0.5 --norm

# Human Bézier swipe (curved trajectory with velocity easing, undetectable by anti-bot systems):
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

### 8. Self-Healing & Failsafes
```bash
# Wait for screen to stop rendering/buffering:
python scripts/geelark.py wait-stable --timeout 6.0

# Auto-dismiss popups / system modals (Fast single-pass OCR):
python scripts/geelark.py dismiss-popup

# Emergency recovery to clean home screen:
python scripts/geelark.py recover
```

---

## 🛡️ Edge Cases & Handling Guide

| Scenario | Solution / Prevention |
| :--- | :--- |
| **Multiple Cloud Phones Open** | Run `python scripts/geelark.py use <profile_number_or_name>` once. All commands lock onto that device. |
| **Virtual keyboard blocking buttons** | Run `python scripts/geelark.py hide-keyboard` (presses Back without leaving screen). |
| **In-stream pre-roll ads** | Run `python scripts/geelark.py wait-text "Skip" --timeout 15.0`. |
| **YouTube Premium / promo modal** | Run `python scripts/geelark.py dismiss-popup` (handles "Not now", "No thanks", "Skip trial", etc.). |
| **Bot detection on social media** | Swiping uses cubic Bézier curves and velocity easing by default (`--human`), mimicking natural human thumb flicks. |
| **Sponsored search results** | When searching manually, verify the item does NOT contain "Ad" or "Sponsored" badge before clicking. (Or use `deep-link` to bypass search entirely). |
| **Video description collapsed** | Click "...more" or the video title area to expand, then `scroll-find "http"`. |
| **Network latency / UI buffering** | Run `python scripts/geelark.py wait-stable` before tapping dynamic buttons. |
| **Unknown state / freezing** | Run `python scripts/geelark.py recover` to return to home screen cleanly. |

---

## 🔄 n8n & Docker Automation Triggering

This skill is fully triggerable from **n8n** (running locally in Docker or on Windows):
1. For Docker n8n, start the bridge: `python scripts/webhook_bridge.py` (runs on port 5055).
2. Import `examples/n8n_trigger.json` into n8n.
3. Call the webhook via HTTP POST with `{"command": "deep-link", "args": ["<url>"]}` or `{"command": "batch-run", "args": ["examples/sample_batch.json"]}`.
4. See [examples/README.md](examples/README.md) for full setup instructions.

---

## 📚 Technical Documentation & Deep-Dive
- [references/features_and_architecture.md](references/features_and_architecture.md): Complete architecture diagrams, capabilities catalog, edge case matrices, and defensive engineering specs.
- [references/window_specs.md](references/window_specs.md): Window geometry specs and normalized touch coordinate reference.
- [INSTALL.md](INSTALL.md): Installation guide for Claude Code, Hermes, OpenClaw, Codex, Antigravity, and n8n Docker.
