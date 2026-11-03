---
name: geelark-cloud-adb
description: Run a GeeLark cloud phone headlessly over the Cloud OpenAPI and ADB - start/stop it, screenshot, tap by on-screen text, open links in an app, skip ads. No desktop app, window or mouse, so it works with the PC off (e.g. on a VPS). Use for unattended GeeLark phone automation.
---

# GeeLark Cloud ADB

Headless counterpart of `geelark-cloud-phone`. Talks to GeeLark's Cloud OpenAPI to start the phone and enable ADB, then drives it with ADB. Standard library only.

```bash
python "<skill dir>/scripts/geelark_adb.py" <command>
```
Below, `ga` means that command line. Every command prints JSON; `"status": "error"` means it failed.

## Setup (once)
- `GEELARK_API_TOKEN`: Bearer token from GeeLark settings. Set it as an environment variable; never paste it into files, memory or chat.
- `GEELARK_CLOUD_PHONE_ID`: the profile id (or pass `--id`).
- `adb` on PATH, or `GEELARK_ADB`. Falls back to GeeLark's bundled `%APPDATA%\GeeLark\scrcpy\adb.exe`.
- In Git Bash set `MSYS_NO_PATHCONV=1`, or `/sdcard/...` style args get rewritten.

## Safety rules
Ask the user before any step that posts, comments, follows, likes, sends, buys, subscribes, submits a form, logs in or approves a permission. Never type passwords or payment details. The phone has no Google account signed in, so likes and comments are not possible. Phones bill per minute: ALWAYS run `down` when finished, every time, without asking (standing user instruction), and say so in the final message.

## Standard loop
1. `ga up` - starts the phone, enables ADB, connects, runs `glogin`. ADB ip/port/password change every start, so always re-run `up` after a stop. Takes 30-90 s.
2. Look: `ga shot --out s.png` then view the image (720x1440 px), or `ga ui --find "Skip"` for text only.
3. Act: `ga tap-text "more"`, `ga tap X Y`, `ga swipe`, `ga type "..." --enter`, `ga key back|home|recent`.
4. Verify with `ga shot` / `ga ui` / `ga focus`. Do not assume an action worked.
5. `ga down` to stop billing.

## Common recipes
| Task | Commands |
| :--- | :--- |
| Open a video in the YouTube app | `ga open-url "<url>" --package com.google.android.youtube` |
| Handle a pre-roll ad | `ga skip-ad` (taps Skip when it appears; reports `skipped:false` if no ad or unskippable - then wait and retry) |
| Expand description, click a link | `ga shot`, then `ga tap X Y` on "more" (~458,534 under the title) and again on the link (the "more" link and the links in the sheet are not in the UI tree, and links are cut off with "...", so use coordinates from the screenshot) |
| Who is in the foreground | `ga focus` (links open in `com.android.chrome` CustomTabActivity; `ga key back` returns) |
| Launch an app | `ga app com.zhiliaoapp.musically` |

## Gotchas
- Description links go through a youtube.com redirect and can take 15 s+ or time out.
- Positions shift between videos; screenshot before tapping by coordinates.
- `ui` reads Android's UI tree; video players and some overlays expose no text, so fall back to a screenshot.
- The API only checks the token; keep it out of logs.
