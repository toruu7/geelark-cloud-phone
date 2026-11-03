# GeeLark Cloud Phone Automation Skill 📱⚡

[![Agent Skill](https://img.shields.io/badge/Agent_Skill-Standard_v1.0-blue?style=flat-square&logo=robot)](SKILL.md)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=flat-square&logo=python)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Android-brightgreen?style=flat-square&logo=windows)](SKILL.md)
[![Compatibility](https://img.shields.io/badge/Compatible-Claude_%7C_Antigravity_%7C_Grok_Bot_%7C_Cursor_%7C_OpenClaw_%7C_Codex-orange?style=flat-square)](INSTALL.md)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-243%20Passing-success?style=flat-square)](tests/)

> **`geelark`** · **`cloud-phone`** · **`android-automation`** · **`mobile-agent`** · **`claude-code`** · **`antigravity`** · **`grok-bot`** · **`cursor`** · **`openclaw`** · **`adb`** · **`ocr`** · **`n8n`** · **`set-of-mark`**

A universal, production-grade **Agent Skill & Multi-Protocol Gateway** for controlling and automating **GeeLark cloud phones** visually, via ADB, or via Cloud OpenAPI with automatic **Multi-Path Fallback Routing**, natural-feeling gestures, and zero-token local OCR.

### 🌐 Universal Agent Compatibility (Works with ANY AI Agent)
- **Skill-Native Agents (`SKILL.md`)**: Claude Code, Google Antigravity, Cursor, Windsurf, OpenClaw, Hermes Agent, OpenAI Codex CLI
- **Local Stdio MCP Agents (`scripts/mcp_stdio.py`)**: Claude Desktop, Cursor MCP, Cline, Roo Code, Zed, OpenCode
- **Remote Cloud MCP Agents (`/mcp` & `/sse`)**: xAI Grok Bot (`https://x.ai/bot` / `grok.com/connectors`), Devin, Goose
- **Function-Calling & OpenAPI Agents (`/openapi.json`)**: OpenAI Custom GPTs, LangChain, CrewAI, AutoGen, Dify, Coze
- **Plain-Text & No-Code Orchestrators (`/prompt` & `/run`)**: n8n, Make, Zapier, Telegram/Discord Bots, Local Ollama LLMs

---

## 🌟 Key Capabilities

- **Multi-Path Element Grounding (`smart-click`)**: Automatically cascades through **Path 1: ADB UIAutomator XML Tree** $\rightarrow$ **Path 2: Local Windows Native OCR** $\rightarrow$ **Path 3: Scroll-Find OCR Loop** $\rightarrow$ **Path 4: Normalized Coordinate Anchor**.
- **Multi-Path Device Lifecycle (`ensure-device`)**: Cascades from **Cached Profile** $\rightarrow$ **Restore Minimized Window** $\rightarrow$ **Auto-Scan Open Phones** $\rightarrow$ **Cloud OpenAPI Remote Boot (`openapi.geelark.com`)** $\rightarrow$ **Desktop App Launch**.
- **Built-in Plain-Text Semantic Transpiler (`prompt`)**: Translates casual English instructions (e.g. `"watch 5 tiktoks on profile 4"`) directly into compound recipes without needing an LLM schema.
- **Universal Schema Exporter (`export-schema`)**: Generates ready-to-import tool schemas for `x.ai/bot`, OpenAI Function Calling, MCP, and OpenAPI 3.1.
- **Feature Introspection (`features`)**: Instantly inspect all capabilities, supported batch actions, common apps, and environment status in human-readable or JSON format.
- **Batch Actions (`batch-run`)**: Run entire multi-action mobile sequences from a JSON file or inline string in a single execution—eliminating LLM round-trip delays.
- **Simultaneous Broadcasting (`broadcast`)**: Multicast an action (home key, back key, deep-link, popup dismissal) across **all open cloud phone windows** simultaneously.
- **Multi-Profile Automation (`batch-profiles`)**: Sequentially process multiple accounts or profiles (`--profiles 1,2,4` or `all`) with a single command.
- **1-Click High-Level Recipes (`youtube-flow`, `tiktok-feed`)**: Run complex multi-step mobile journeys in a single command (auto-skips ads, expands descriptions, clicks links, or warms up social feeds).
- **Target Persistence (`use <profile>`)**: Lock onto Profile 4 or any cloud phone once—never repeat `-w` or `--window` again.
- **Human-like Bézier Gesture Engine (`swipe`)**: Curved, eased swipe paths with small jitter so gestures look like a thumb rather than a straight line. A usability nicety, not a guarantee against platform detection; follow each platform's terms.
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

## 📊 Bulk Automation + Google Sheets

`python scripts/geelark.py bulk-run` runs a task queue on all connected phones **in parallel over ADB** (one worker per phone, no mouse takeover). The queue and the reports live in a Google Sheet through a small Apps Script web app (`sheets/apps_script.gs`): each task ends as `success`, `failed`, `error`, `timeout`, `offline` or `skipped`, with retries, durations, screenshots and a per-run summary, plus a local JSONL log and an offline spool so nothing is lost. There is no raw-shell action, params are validated, and everything sent to the device shell is quoted. Put `cloud:<phone_id>` in the device column and run with `--cloud` to drive GeeLark cloud phones from the same sheet (started via the `geelark-cloud-adb` skill, always stopped afterwards). Start with `--dry-run` and `--max-tasks 1`. See [references/bulk_automation.md](references/bulk_automation.md).

---

## 🗓️ Daily Unattended Routine (PC off)

Build a plan once in the sheet with dropdowns only (**Phones**, **Library** of named tasks, **Routine**, **Settings**): pick a phone, pick a task, optionally a link and a duration. Every day at your chosen time the plan is queued and a runner on a small VPS or GitHub Actions (`deploy/`) works through it phone by phone, each phone taking its next task when the previous one finishes. Results land in Reports, a live Overview and an email. Cloud phones are stopped after use (billing safety on every exit path), a `paused` tick stops everything instantly, and an idle check makes frequent polling free. See [references/unattended.md](references/unattended.md).

---

### ☁️ Run it from a Claude cloud routine

`.claude/skills/` holds the skills an unattended cloud agent loads from a single clone: `geelark-daily-operator` (the run-once, stop-everything, report playbook) and a vendored copy of [geelark-cloud-adb](https://github.com/toruu7/geelark-cloud-adb) (`python scripts/sync_cloud_adb.py` refreshes it). The routine prompt is in `deploy/claude-routine/prompt.txt`; setup is in [references/unattended.md](references/unattended.md).

---

## 🔒 Security & Robustness

- **HTTP bridge is locked down**: binds to `127.0.0.1`, requires `Authorization: Bearer <token>` on every POST (auto-generated at startup, or set `GEELARK_BRIDGE_TOKEN`), allowlists commands (no raw `adb`), and sends no CORS headers unless you pass `--cors-origin`. Use `--host 0.0.0.0` only for Docker n8n on a trusted network.
- **One command at a time**: a cross-process file lock serializes CLI, bridge and MCP calls (exit code 3 / `busy` if it times out).
- **ADB-first input**: Back/Home/Recent use real Android key events; `GEELARK_INPUT_MODE=adb` injects taps/swipes in the background without taking over your mouse. Every ADB call has a timeout.
- **Cloud OpenAPI client** retries transient errors, validates endpoints, and never echoes your token.
- Run the live smoke test against a real phone: `python scripts/smoke_test.py`.

---

## 📦 Installation & Setup

See [INSTALL.md](INSTALL.md) for 1-minute installation guides for:
- Claude Code
- Hermes
- OpenClaw
- OpenAI Codex
- Google Antigravity
- n8n Local Docker

See [SKILL.md](SKILL.md) for the agent workflow and safety rules, and [references/cli_reference.md](references/cli_reference.md) for the complete CLI reference.
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
geelark, cloud-phone, cloudphone, android-automation, mobile-automation, mobile-agent, agent-skill, claude-code, antigravity, hermes-agent, openclaw, codex, adb, windows-ocr, n8n, set-of-mark, tiktok-automation, youtube-automation
```

### 🔍 Categorized Search Index:
- **Core Automation**: `geelark`, `geelark-cloud-phone`, `cloud-phone-automation`, `android-automation`, `mobile-automation`, `adb-automation`, `scrcpy-control`
- **Agent Ecosystems**: `agent-skill`, `claude-code-skill`, `antigravity-skill`, `hermes-agent-skill`, `openclaw-skill`, `codex-agent`, `ai-agent-tools`, `llm-mobile-control`
- **Vision & OCR**: `set-of-mark`, `som-prompting`, `windows-media-ocr`, `ocr-automation`, `low-token-vision`, `multimodal-ai`, `screen-analysis`
- **Multi-Device & Workflows**: `batch-actions`, `multi-phone-broadcast`, `multi-profile-automation`, `n8n-trigger`, `webhook-bridge`, `social-media-automation`
- **Gestures & Recipes**: `bezier-curves`, `natural-gestures`, `tiktok-warmup`, `youtube-automation`
