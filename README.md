# GeeLark Cloud Phone Automation Skill 📱⚡

A universal **Agent Skill** for controlling and automating **GeeLark cloud phones** visually or via ADB with maximum speed, anti-bot safety, and token efficiency.

Designed according to the open **Agent Skill Standard**, allowing instant installation across:
- **Claude Code** (Anthropic)
- **Hermes Agent**
- **OpenClaw**
- **OpenAI Codex / Custom Agents**
- **Google Antigravity**

---

## 🌟 Key Capabilities

- **1-Click High-Level Recipes (`youtube-flow`, `tiktok-feed`)**: Run complex multi-step mobile journeys in a single command (auto-skips ads, expands descriptions, clicks links, or warms up social feeds).
- **Target Persistence (`use <profile>`)**: Lock onto Profile 4 or any cloud phone once—never repeat `-w` or `--window` again.
- **Human-like Bézier Gesture Engine (`swipe`)**: Simulates natural human thumb arcs with non-linear velocity easing, making touch interactions undetectable by TikTok/Instagram anti-bot algorithms.
- **0.1s Instant Deep-Linking (`deep-link`)**: Dispatches Android Intent VIEW to open any video, webpage, or app scheme without tedious manual typing.
- **Autonomous Scroll & Find (`scroll-find`)**: Finds and clicks text down scrollable views in a single local OCR command, cutting token costs by 80%.
- **Set-of-Mark (SoM) Visual Badges (`capture --annotate` & `tap-mark`)**: Overlays numbered badges on interactive elements so LLMs can simply call `tap-mark <id>` without coordinate hallucinations.
- **Token-Optimized Multimodal Vision (`--low-token`)**: Downsamples high-res screens to save up to 70% in multimodal vision token costs.
- **Local Windows Native OCR (`ocr_helper.ps1`)**: Zero-dependency OCR powered by Windows 10/11 `Windows.Media.Ocr.OcrEngine` (runs locally in 80ms, $0 token cost).
- **Anti-Lag & Self-Healing (`wait-stable`, `dismiss-popup`, `recover`)**: Automatically detects render completion, dismisses promotional or obstacle popups (YouTube Premium, cookie modals, permissions), and recovers to home screen on failures.
- **n8n & Docker Ready**: Includes a pre-built n8n workflow (`examples/n8n_trigger.json`) and a lightweight HTTP bridge (`scripts/webhook_bridge.py`) for triggering from local Docker containers.

---

## 🚀 Quick Usage

```bash
# 1. Lock onto Profile 4 (persists across all subsequent commands)
python scripts/geelark.py use 4

# 2. Check connected phones, window geometry, and ADB state
python scripts/geelark.py status

# 3. Complete YouTube video journey in 1 command (plays video, skips ads, clicks link)
python scripts/geelark.py youtube-flow "https://www.youtube.com/watch?v=Bm84BAtOfQw" --click-link "http"

# 4. Human-like TikTok warmup (5 videos, realistic timing, Bézier swipes)
python scripts/geelark.py tiktok-feed --videos 5 --like-ratio 0.3

# 5. Capture screen with numbered Set-of-Mark badges
python scripts/geelark.py capture --annotate --out state.png

# 6. Tap an element by mark number
python scripts/geelark.py tap-mark 12

# 7. Collapse virtual keyboard if obscuring buttons
python scripts/geelark.py hide-keyboard

# 8. Dismiss any obstacle popups or system modals
python scripts/geelark.py dismiss-popup
```

---

## 📦 Installation & Setup

See [INSTALL.md](INSTALL.md) for 1-minute installation guides for:
- Claude Code
- Hermes
- OpenClaw
- OpenAI Codex
- Google Antigravity
- n8n Local Docker

See [SKILL.md](SKILL.md) for the complete CLI reference, parameter options, and edge case recovery guide.
