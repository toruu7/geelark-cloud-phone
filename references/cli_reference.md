# CLI Reference

```bash
python scripts/geelark.py <command> [options]
```
All commands print JSON. Exit codes: `0` ok, `1` error, `3` another command holds the device lock.
Most commands take `--window/-w <profile number | title | HWND>`; `use` sets a persistent default.

## Targeting and status
| Command | Notes |
| :--- | :--- |
| `use <target> [--device SERIAL]` | Persist the active phone (and optionally its ADB serial). Matching is exact: `4` never matches `#14`. |
| `status` | Phone windows, app windows, ADB devices. |
| `list-windows [--json]`, `focus`, `launch-app` | Window helpers. |
| `ensure-device [--no-boot]` | Active window, restore minimized, scan, cloud boot (needs `GEELARK_API_TOKEN` + `GEELARK_CLOUD_PHONE_ID`), desktop launch. |
| `features [--json]` | Capability manifest. |

## Seeing
| Command | Notes |
| :--- | :--- |
| `capture [--annotate] [--low-token] [--no-crop] [-o file.png]` | `--annotate` draws numbered marks (OCR) and saves them for `tap-mark`. `--low-token` downsamples to ~800px high. |
| `find-text "q"` | OCR search; returns normalized coordinates. No image tokens. |
| `dump-ui` | ADB UIAutomator XML. |
| `wait-stable [--timeout 6]` | Wait until frames stop changing. |

## Acting
| Command | Notes |
| :--- | :--- |
| `tap X Y [--norm]` | Normalized coordinates recommended. |
| `swipe X1 Y1 X2 Y2 [--norm] [--steps N]` | GUI mode: curved, eased path with small jitter. ADB mode: straight `input swipe`. |
| `type "text" [--enter]` | Pastes via clipboard into the focused field. |
| `key back\|home\|recent\|appswitch\|enter\|tab\|esc` | Back/Home/Recent via ADB keyevent when a device is known; else nav-bar tap. |
| `hide-keyboard` | Sends Back. |
| `click-text "q"`, `wait-text "q" [--timeout]`, `scroll-find "q" [--max-swipes] [--no-click]`, `smart-click "q" [--no-scroll]`, `tap-mark N` | Label-based clicking. |
| `open-app <name\|package>`, `deep-link <url>` | Via ADB intent; Chrome omnibox fallback if ADB is unavailable. |
| `dismiss-popup`, `recover` | Obstacle clearing / return to Home. |
| `prompt "plain English"` | Deterministic keyword transpiler (not an LLM). Supports open/launch, URLs, "watch N tiktoks", click/tap "x", type "x", profile N, dismiss popups. |

## Recipes and multi-phone
| Command | Notes |
| :--- | :--- |
| `youtube-flow URL [--click-link TXT] [--no-skip-ads]` | Deep-link, skip ads, expand description, optionally click a link. |
| `tiktok-feed [--videos N --min-watch S --max-watch S --like-ratio P]` | Scrolls a feed with randomized dwell times and optional likes. **Likes change an account: confirm first.** |
| `batch-run <file.json \| '[...]'>` | Runs steps in order; a failing step is reported and the run continues. |
| `broadcast <action> [args]` | Same action on every open phone window. |
| `batch-profiles -p 1,2,4\|all <command> [args]` | Same command on each profile in turn. |

### `batch-run` actions
`tap`, `swipe`, `type`, `key`, `open-app`, `deep-link`, `smart-click`, `click-text`, `wait-text`, `scroll-find`, `dismiss-popup`, `hide-keyboard`, `wait-stable`, `sleep`, `capture`, `youtube-flow`, `tiktok-feed`, `prompt`.
Each step may carry `"window": "<profile>"`.
```json
[{"action":"dismiss-popup"},
 {"action":"deep-link","url":"https://youtube.com/watch?v=Bm84BAtOfQw"},
 {"action":"wait-text","query":"Skip","timeout":15}]
```

## Bulk automation (ADB, parallel)
`bulk-run [--tasks FILE.json|.csv] [--devices a,b] [--retries N] [--max-workers N] [--max-tasks N] [--task-timeout S] [--task-delay S] [--dry-run] [--no-sheet] [--fail-on-error]`, `bulk-check`, `bulk-flush`.
Full guide, actions and sheet format: [bulk_automation.md](bulk_automation.md). These commands never take the desktop lock and are not exposed through the HTTP bridge.

## Cloud OpenAPI (optional)
Needs `GEELARK_API_TOKEN` (or `--token`). Requests are retried on 429/5xx/network errors; non-zero API codes are returned as `status: error`.
`cloud-list`, `cloud-start <id>`, `cloud-stop <id>`, `cloud-status <id>`, and `cloud-api /open/v1/... --data '{...}'` for any other endpoint (path must start with `/open/`).
Check GeeLark's current OpenAPI docs for endpoint names and body shapes before using `cloud-api`.

## Configuration
| Variable | Meaning |
| :--- | :--- |
| `GEELARK_ADB_DEVICE` | ADB serial used for ADB calls (overrides `use --device`). |
| `GEELARK_ADB_PATH` | adb executable (default: GeeLark's bundled adb, else `adb` on PATH). |
| `GEELARK_ADB_TIMEOUT` | Seconds before an adb call is abandoned (default 15). |
| `GEELARK_ADB_KEYS=0` | Never use ADB keyevents; always tap the nav bar. |
| `GEELARK_INPUT_MODE` | `gui` (default, real mouse) or `adb` (background taps/swipes; normalized coords only). |
| `GEELARK_LOCK_TIMEOUT` / `GEELARK_LOCK_PATH` | Cross-process lock wait (default 60 s) and lock file. |
| `GEELARK_API_TOKEN`, `GEELARK_CLOUD_PHONE_ID` | Cloud OpenAPI. |
| `GEELARK_BRIDGE_TOKEN` | Bearer token for the HTTP bridge. |
| `GEELARK_SHEETS_URL`, `GEELARK_SHEETS_SECRET` | Apps Script web app URL and its secret, for `bulk-run` / `bulk-check` / `bulk-flush`. |

## Edge cases
| Scenario | What to do |
| :--- | :--- |
| Multiple phones open | `use <profile>` first. |
| Keyboard hides a button | `hide-keyboard`. |
| Pre-roll ad | `wait-text "Skip" --timeout 15`. |
| Promo / permission modal | `dismiss-popup` (handles "Not now", "No thanks", "Skip trial", ...). It also taps "Allow"/"OK": check the dialog first if it matters. |
| Sponsored search result | Check for an "Ad"/"Sponsored" badge, or use `deep-link`. |
| Collapsed description | Click "...more", then `scroll-find "http"`. |
| UI still loading | `wait-stable` before tapping. |
| Unknown state | `recover`. |
| `busy` / exit 3 | Another command is running; retry. |
| adb hangs | Calls time out after `GEELARK_ADB_TIMEOUT`; check `status`. |
