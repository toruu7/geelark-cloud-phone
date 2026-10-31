# GeeLark Cloud Phone Automation Skill 📱⚡

A universal **Agent Skill** for controlling and automating **GeeLark cloud phones** visually or via ADB with maximum speed, reliability, and token efficiency.

Designed according to the open **Agent Skill Standard**, allowing instant installation across:
- **Claude Code** (Anthropic)
- **Hermes Agent**
- **OpenClaw**
- **OpenAI Codex / Custom Agents**
- **Google Antigravity**

---

## 🌟 Key Capabilities

- **0.1s Instant Deep-Linking (`deep-link`)**: Dispatches Android Intent VIEW to open any video, webpage, or app scheme without tedious manual typing.
- **Autonomous Scroll & Find (`scroll-find`)**: Finds and clicks text down scrollable views in a single local OCR command, cutting token costs by 80%.
- **Set-of-Mark (SoM) Visual Badges (`capture --annotate` & `tap-mark`)**: Overlays numbered badges on interactive elements so LLMs can simply call `tap-mark <id>` without coordinate hallucinations.
- **Token-Optimized Multimodal Vision (`--low-token`)**: Downsamples high-res screens to save up to 70% in multimodal vision token costs.
- **Local Windows Native OCR (`ocr_helper.ps1`)**: Zero-dependency OCR powered by Windows 10/11 `Windows.Media.Ocr.OcrEngine` (runs locally in 80ms, $0 token cost).
- **Anti-Lag & Self-Healing (`wait-stable`, `dismiss-popup`, `recover`)**: Automatically detects render completion, dismisses promotional or obstacle popups (YouTube Premium, cookie modals, permissions), and recovers to home screen on failures.
- **Multi-Monitor Visual Engine**: Seamlessly captures phone displays and sends clicks across secondary and tertiary monitors.
- **Normalized Coordinate System (`--norm`)**: Tap and swipe using normalized coordinates (`0.0` to `1.0`), eliminating screen resolution and DPI mismatches for AI agents.
- **n8n & Docker Ready**: Includes a pre-built n8n workflow (`examples/n8n_trigger.json`) and a lightweight HTTP bridge (`scripts/webhook_bridge.py`) for triggering from local Docker containers.

---

## 🚀 Quick Usage

```bash
# 1. Open video or webpage instantly in 0.1s
python scripts/geelark.py deep-link "https://www.youtube.com/watch?v=Bm84BAtOfQw"

# 2. Wait for playback & auto-skip any pre-roll ads
python scripts/geelark.py wait-text "Skip" --timeout 15.0

# 3. Capture screen with numbered Set-of-Mark badges
python scripts/geelark.py capture --annotate --out state.png

# 4. Tap an element by mark number
python scripts/geelark.py tap-mark 12

# 5. Scroll down to find and click a link in the description
python scripts/geelark.py scroll-find "http" --max-swipes 3

# 6. Collapse virtual keyboard if obscuring buttons
python scripts/geelark.py hide-keyboard

# 7. Dismiss any obstacle popups or system modals
python scripts/geelark.py dismiss-popup
```

---

## 📦 Installation & Setup

See [INSTALL.md](file:///C:/Users/Backspace/.gemini/config/skills/geelark-cloud-phone/INSTALL.md) for 1-minute installation guides for:
- Claude Code
- Hermes
- OpenClaw
- OpenAI Codex
- Google Antigravity
- n8n Local Docker

See [SKILL.md](file:///C:/Users/Backspace/.gemini/config/skills/geelark-cloud-phone/SKILL.md) for the complete CLI reference, parameter options, and edge case recovery guide.
