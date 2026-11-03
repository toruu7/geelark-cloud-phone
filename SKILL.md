---
name: geelark-cloud-phone
description: Control and inspect GeeLark cloud phones on a Windows host - capture the screen, tap, swipe, type, press Back/Home, open apps and links, and click UI text via ADB or local OCR. Use when the user wants to operate, test, or automate a GeeLark phone profile.
metadata:
  author: toruu7
  version: "4.7.0"
  license: MIT
  platform: windows
  repository: https://github.com/toruu7/geelark-cloud-phone
---

# GeeLark Cloud Phone

Windows-only. Drives the open GeeLark phone window (and its bundled ADB) through one CLI.
Every command prints JSON; `"status": "error"` means it did not work, so read the message instead of retrying blindly.

```bash
python "${CLAUDE_SKILL_DIR}/scripts/geelark.py" <command> [options]
```
Below, `gl` means that command line. Full reference: [references/cli_reference.md](references/cli_reference.md).

## Safety rules (read first)

These actions change real accounts. **Ask the user before** any step that:
- posts, comments, follows, likes, sends messages, buys, subscribes, or submits a form;
- logs in, enters credentials, or approves a permission dialog;
- runs `tiktok-feed`, `batch-profiles`, or `broadcast` (they act on many phones/accounts at once).

Never type passwords or payment details. Use `capture` to confirm which app/account is on screen before acting.
Respect each platform's terms. Platforms may detect and restrict automated accounts; never promise the user otherwise.

## Standard loop

1. **Pick the phone**: `gl status` (shows open phone windows and ADB devices), then `gl use <profile> [--device <adb-serial>]`.
   If `status` shows no phone window, run `gl ensure-device`.
2. **Look**: `gl capture --annotate --low-token --out state.png`, then view the image. Numbered marks are saved for `tap-mark`.
   Prefer `gl find-text "<text>"` when you only need to know whether something is on screen (no image tokens).
3. **Act** with the most specific command that fits (see below).
4. **Verify**: capture again or `find-text` for the expected result. Do not assume an action worked.
5. **Recover** if the state is unknown: `gl dismiss-popup`, then `gl recover` (Back, Back, Home).

## Choosing a command

| Intent | Command |
| :--- | :--- |
| Click something by its label | `gl smart-click "Skip"` (ADB UI tree, then OCR, then scroll, then anchor) |
| Click a numbered mark | `gl tap-mark 12` |
| Open a URL / video instantly | `gl deep-link "<url>"` |
| Open an app | `gl open-app youtube` (youtube, tiktok, chrome, settings, playstore, files) |
| Type into the focused field | `gl type "text" --enter` |
| Navigate | `gl key back` / `home` / `recent` / `enter` |
| Scroll down until text shows | `gl scroll-find "text" --max-swipes 5` |
| Wait for text, then click it | `gl wait-text "Skip" --timeout 15` |
| Keyboard covers buttons | `gl hide-keyboard` |
| Raw coordinates (last resort) | `gl tap 0.5 0.8 --norm`, `gl swipe 0.5 0.8 0.5 0.2 --norm` |
| Several steps in one go | `gl batch-run steps.json` (see reference for actions) |
| Plain English | `gl prompt "open youtube on profile 4"` |

Use normalized coordinates (`--norm`, 0.0 to 1.0) so results do not depend on window size.

## Behaviour you should know

- **One command at a time.** A cross-process lock serializes commands; a second caller waits, then exits with code 3 / `"code": "busy"`. Retry later; do not run commands in parallel.
- **Mouse takeover.** In the default mode taps and swipes move the real mouse and focus the phone window, so the user cannot use the mouse meanwhile. Set `GEELARK_INPUT_MODE=adb` (with `use --device <serial>`) to inject taps/swipes over ADB in the background instead.
- **Back/Home/Recent** use real Android key events over ADB when exactly one device is known; otherwise they fall back to tapping the window's navigation bar.
- **OCR** is Windows' built-in engine: it only reads languages installed on the host and misses stylized text. If `find-text` fails, try `capture` and read the screenshot yourself.
- **Several phones open**: always `use <profile>` first; commands never fall back to a different phone than the one targeted.

## Bulk runs over ADB (many phones + Google Sheet)

`gl bulk-run` works through a task queue on every connected phone in parallel (ADB only, no mouse takeover) and reports each result (success, failed, timeout, offline, ...) to a Google Sheet and `logs/`. Setup, task format and actions: [references/bulk_automation.md](references/bulk_automation.md).
- **Before any real run**: `gl bulk-check`, then `gl bulk-run --tasks <file> --dry-run`, show the user the task list, and get a yes. Start with `--max-tasks 1` on one phone, check the result, then scale up.
- Bulk tasks change many accounts at once, so the safety rules above apply to every row: do not queue posting, liking, messaging, purchases, or logins without the user's explicit approval.
- **Cloud phones** (`device` = `cloud:<phone_id>` in the sheet, via the `geelark-cloud-adb` skill) only run with `gl bulk-run --cloud`, and they bill per minute. Ask the user before using `--cloud`, state which phones, start with `--max-tasks 1`, and afterwards confirm the report shows each phone stopped (`cloud.stopped`, no `stop_failures`). If a run was killed, run `gl bulk-cloud-stop`.
- **Daily unattended routine**: the sheet's Phones / Library / Routine / Settings tabs (all dropdowns) define a plan that is queued every day at `run_time` and run by `gl bulk-run --only-cloud` on a VPS or GitHub Actions, then reported on the Overview tab and by email. Setup and safety: [references/unattended.md](references/unattended.md). Never edit the Routine to add posting, messaging, purchases or logins without the user's explicit approval, and never turn off `paused`/limits to "make it run". If asked to stop everything, tick `paused` in Settings first.
- Report back from the run summary (`success` / `failed` / `other`) and the `logs/bulk-<run_id>.jsonl` path; do not claim success for tasks the report marks failed.

## Environment variables

`GEELARK_ADB_DEVICE` (ADB serial), `GEELARK_INPUT_MODE` (`gui`|`adb`), `GEELARK_ADB_KEYS=0` (disable ADB key events),
`GEELARK_ADB_TIMEOUT` (seconds, default 15), `GEELARK_LOCK_TIMEOUT` (seconds, default 60),
`GEELARK_SHEETS_URL` and `GEELARK_SHEETS_SECRET` (bulk reporting),
`GEELARK_API_TOKEN` and `GEELARK_CLOUD_PHONE_ID` (Cloud OpenAPI: `cloud-list`, `cloud-start`, `cloud-stop`, `cloud-status`, `cloud-api`).

## HTTP / MCP gateway (optional)

`python scripts/webhook_bridge.py` exposes `/run`, `/prompt`, `/mcp` for n8n and other agents. It binds to `127.0.0.1`, requires a bearer token on every POST, and only permits an allowlist of commands. See [examples/README.md](examples/README.md).

## More

- [references/cli_reference.md](references/cli_reference.md): every command, batch actions, recipes, edge cases.
- [references/features_and_architecture.md](references/features_and_architecture.md): architecture and defensive design.
- [references/window_specs.md](references/window_specs.md): window geometry and coordinate mapping.
- [INSTALL.md](INSTALL.md): installation per agent.
