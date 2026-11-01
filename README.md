# GeeLark Cloud Phone Automation Skill 📱⚡

[![Agent Skill](https://img.shields.io/badge/Agent_Skill-Standard_v1.0-blue?style=flat-square&logo=robot)](SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=flat-square&logo=python)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Android-brightgreen?style=flat-square&logo=windows)](SKILL.md)
[![Compatibility](https://img.shields.io/badge/Compatible-Claude_Code_%7C_Antigravity_%7C_Hermes_%7C_OpenClaw_%7C_Codex-orange?style=flat-square)](INSTALL.md)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-54%20Passed-success?style=flat-square)](tests/)

> **`geelark`** · **`cloud-phone`** · **`android-automation`** · **`mobile-agent`** · **`claude-code`** · **`antigravity`** · **`hermes`** · **`openclaw`** · **`adb`** · **`ocr`** · **`n8n`** · **`set-of-mark`** · **`antidetect`**

A universal, production-grade **Agent Skill** for controlling and automating **GeeLark cloud phones** visually or via ADB with maximum speed, anti-bot safety, and token efficiency.

Designed according to the open **Agent Skill Standard**, allowing instant installation across:
- **Claude Code** (Anthropic)
- **Hermes Agent**
- **OpenClaw**
- **OpenAI Codex / Custom Agents**
- **Google Antigravity**

---

## 🌟 Key Capabilities

- **Feature Introspection (`features`)**: Instantly inspect all capabilities, supported batch actions, common apps, and environment status in human-readable or JSON format.
- **Batch Actions (`batch-run`)**: Run entire multi-action mobile sequences from a JSON file or inline string in a single execution—eliminating LLM round-trip delays.
- **Simultaneous Broadcasting (`broadcast`)**: Multicast an action (home key, back key, deep-link, popup dismissal) across **all open cloud phone windows** simultaneously.
- **Multi-Profile Automation (`batch-profiles`)**: Sequentially process multiple accounts or profiles (`--profiles 1,2,4` or `all`) with a single command.
- **1-Click High-Level Recipes (`youtube-flow`, `tiktok-feed`)**: Run complex multi-step mobile journeys in a single command (auto-skips ads, expands descriptions, clicks links, or warms up social feeds).
- **Target Persistence (`use <profile>`)**: Lock onto Profile 4 or any cloud phone once—never repeat `-w` or `--window` again.
- **Human-like Bézier Gesture Engine (`swipe`)**: Simulates natural human thumb arcs with non-linear velocity easing, making touch interactions undetectable by TikTok/Instagram anti-bot algorithms.
- **0.1s Instant Deep-Linking (`deep-link`)**: Dispatches Android Intent VIEW to open any video, webpage, or app scheme without tedious manual typing.
- **Autonomous Scroll & Find (`scroll-find`)**: Finds and clicks text down scrollable views in a single local OCR command, cutting token costs by 80%.
- **Set-of-Mark (SoM) Visual Badges (`capture --annotate` & `tap-mark`)**: Overlays numbered badges on interactive elements so LLMs can simply call `tap-mark <id>` without coordinate hallucinations.
- **Token-Optimized Multimodal Vision (`--low-token`)**: Downsamples high-res screens to save up to 70% in multimodal vision token costs.
- **Local Windows Native OCR (`ocr_helper.ps1`)**: Zero-dependency OCR powered by Windows 10/11 `Windows.Media.Ocr.OcrEngine` (runs locally in 80ms, $0 token cost).
- **Fast Obstacle Clearance & Self-Healing (`wait-stable`, `dismiss-popup`, `recover`)**: Single-pass OCR dismissal (15x faster), automatic render stabilization, and emergency recovery to home screen on failures.
- **n8n & Docker Ready**: Includes a pre-built n8n workflow (`examples/n8n_trigger.json`) and a lightweight HTTP bridge (`scripts/webhook_bridge.py`) for triggering from local Docker containers.

---

## 🚀 Quick Usage

```bash
# 0. Inspect all capabilities and supported batch actions
python scripts/geelark.py features

# 1. Lock onto Profile 4 (persists across all subsequent commands)
python scripts/geelark.py use 4

# 2. Check connected phones, window geometry, and ADB state
python scripts/geelark.py status

# 3. Execute a complete multi-step batch sequence from a JSON file
python scripts/geelark.py batch-run examples/sample_batch.json

# 4. Broadcast an action across ALL open phone windows at once
python scripts/geelark.py broadcast dismiss-popup
python scripts/geelark.py broadcast key home

# 5. Run a warmup recipe across multiple profiles sequentially
python scripts/geelark.py batch-profiles --profiles 1,2,4 tiktok-feed 5

# 6. Complete YouTube video journey in 1 command (plays video, skips ads, clicks link)
python scripts/geelark.py youtube-flow "https://www.youtube.com/watch?v=Bm84BAtOfQw" --click-link "http"

# 7. Human-like TikTok warmup (5 videos, realistic timing, Bézier swipes)
python scripts/geelark.py tiktok-feed --videos 5 --like-ratio 0.3

# 8. Capture screen with numbered Set-of-Mark badges
python scripts/geelark.py capture --annotate --out state.png

# 9. Tap an element by mark number
python scripts/geelark.py tap-mark 12

# 10. Collapse virtual keyboard if obscuring buttons
python scripts/geelark.py hide-keyboard

# 11. Dismiss any obstacle popups or system modals in 1 fast pass
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
See [references/features_and_architecture.md](references/features_and_architecture.md) for deep-dive architecture diagrams, capability specifications, and defensive engineering details.
See [references/window_specs.md](references/window_specs.md) for window geometry and normalized coordinate maps.

---

## 🧪 Automated Tests

Run the full unit test suite covering Bézier gestures, batch execution, window matching, and webhook handlers:
```bash
python -m unittest discover tests
```

---

## 🏷️ Tags, Topics & Search Keywords

For repository indexing, agent marketplaces, and search engines:

### 📌 GitHub Topics (Copy-Paste into GitHub Repo "About" Settings):
```text
geelark, cloud-phone, cloudphone, android-automation, mobile-automation, mobile-agent, agent-skill, claude-code, antigravity, hermes-agent, openclaw, codex, adb, windows-ocr, n8n, set-of-mark, antidetect, tiktok-automation, youtube-automation, anti-bot
```

### 🔍 Categorized Search Index:
- **Core Automation**: `geelark`, `geelark-cloud-phone`, `cloud-phone-automation`, `android-automation`, `mobile-automation`, `adb-automation`, `scrcpy-control`, `antidetect-phone`
- **Agent Ecosystems**: `agent-skill`, `claude-code-skill`, `antigravity-skill`, `hermes-agent-skill`, `openclaw-skill`, `codex-agent`, `ai-agent-tools`, `llm-mobile-control`
- **Vision & OCR**: `set-of-mark`, `som-prompting`, `windows-media-ocr`, `ocr-automation`, `low-token-vision`, `multimodal-ai`, `screen-analysis`
- **Multi-Device & Workflows**: `batch-actions`, `multi-phone-broadcast`, `multi-profile-automation`, `n8n-trigger`, `webhook-bridge`, `social-media-automation`
- **Anti-Bot & Human Simulation**: `bezier-curves`, `natural-gestures`, `anti-bot-bypass`, `tiktok-warmup`, `youtube-automation`
