# Bulk automation (ADB) with Google Sheets

Run the same kind of task on many phones in parallel, with a Google Sheet as the **task queue** and the **report log**.

```
Google Sheet ("Tasks" tab)  <--claim/report-->  Apps Script web app  <--HTTPS-->  bulk-run  --adb-->  phone 1..N
                                                                                     |
                                                                       logs/bulk-<run>.jsonl  (always written)
```

* **ADB only.** No mouse, windows or OCR, so it runs while you use the PC and never takes the desktop lock.
* **One worker per phone.** Tasks for one phone run in order; different phones run at the same time.
* **Every outcome is recorded**: success, failed, error (bad task), timeout, offline, skipped, plus events (retries, warnings, device problems) and a per-run summary.
* **Nothing is lost**: if the sheet is unreachable, reports go to a local log and an offline spool that `bulk-flush` (or the next run) replays.

## 1. One-time setup

1. Create a Google Sheet. **Extensions > Apps Script**, paste [`sheets/apps_script.gs`](../sheets/apps_script.gs).
2. **Project Settings > Script properties**: add `SECRET` = a long random string.
3. Run `setup` once from the editor and authorize it. It creates the `Tasks`, `Reports` and `Runs` tabs.
4. **Deploy > New deployment > Web app**. Execute as *Me*, access *Anyone*. (Anyone can reach the URL; only requests carrying your secret are accepted.) Copy the `/exec` URL.
5. On the machine running the phones:
   ```powershell
   $env:GEELARK_SHEETS_URL    = "https://script.google.com/macros/s/.../exec"
   $env:GEELARK_SHEETS_SECRET = "<the SECRET from step 2>"
   python scripts/geelark.py bulk-check
   ```
   `bulk-check` lists ADB devices and confirms the sheet answers. Redeploy the web app (new version) whenever you edit the script.

The URL must be an `https://script.google.com/...` address; the secret is sent in the request body, never in the URL, and is not written to logs.

## 2. Queue tasks (the `Tasks` tab)

| Column | You fill in | Meaning |
| :--- | :--- | :--- |
| `task_id` | optional | Unique label. Blank gets `row-N`. |
| `device` | optional | ADB serial (see `adb devices`). **Blank = any phone.** |
| `action` | yes | One of the actions below. |
| `params` | per action | JSON object, e.g. `{"name":"youtube"}`. |
| `status` | leave blank | Blank/`pending` = waiting. The runner sets `running`, then `success` or `failed`. |
| `attempts`, `worker`, `claimed_at`, `finished_at`, `result` | runner fills | Outcome of the task. |

To re-run a task, set `status` back to `pending`. A task stuck in `running` for more than 15 minutes (a crashed run) is handed out again automatically.

### Actions
| Action | Params | Notes |
| :--- | :--- | :--- |
| `open-app` | `name` (youtube, tiktok, chrome, settings, playstore, files, or a package name), `verify_s` (default 6, 0 = skip) | Launches and **verifies** the app is in the foreground. |
| `force-stop` | `name` | |
| `deep-link` | `url`, optional `package` | `https://...` or an app scheme. Reports failure if no app can handle it. |
| `key` | `name` (back, home, recent, enter, tab, esc, backspace), `repeat` 1-10 | |
| `tap` | `x`, `y` in 0.0-1.0 | Normalized to the phone's real screen size. |
| `swipe` | `x1 y1 x2 y2` in 0.0-1.0, `duration_ms` | |
| `type` | `text` (printable ASCII, up to 500), `enter` | `adb input text` cannot send other characters. |
| `sleep` | `seconds` (max 300) | |
| `screenshot` | none | Saved under `logs/shots/<run>/`; the path is in the report. |
| `click-text` | `text`, optional `timeout`, `index` | Finds the element in the UI tree (not OCR) and taps it. |
| `wait-text` | `text`, `timeout` (default 15), `click` | Waits until it appears. |
| `assert-text` | `text`, `absent` | Success only if the text is (or with `absent`, is not) on screen. Use it to **verify** a step worked. |
| `check-device` | none | Reports state, model and foreground app. |
| `flow` | `steps`: list of the actions above | Runs steps in order, stops at the first failure (`continue_on_error` to keep going). Up to 50 steps. |

There is deliberately **no raw shell action**: a spreadsheet cell must not be able to run arbitrary commands on your phones. Anything sent to the device shell is quoted.

Example `flow` row:
```json
{"steps":[
  {"action":"open-app","name":"chrome"},
  {"action":"deep-link","url":"https://example.com/offer?id=7&src=bulk"},
  {"action":"wait-text","text":"Add to cart","timeout":20},
  {"action":"screenshot"}
]}
```
See [`examples/bulk_tasks.json`](../examples/bulk_tasks.json) for a local file in the same format.

## 3. Run

```powershell
python scripts/geelark.py bulk-run                      # claim from the sheet until the queue is empty
python scripts/geelark.py bulk-run --tasks examples/bulk_tasks.json --dry-run   # validate only, touches nothing
python scripts/geelark.py bulk-run --tasks tasks.csv --devices 98.98.125.37:21127 --max-tasks 5
```
Useful flags: `--devices a,b` (default: all connected), `--max-workers 8`, `--retries 1`, `--task-timeout 120`, `--task-delay 2` (pause between tasks on one phone), `--no-sheet` (local log only), `--fail-on-error` (exit 4 if anything failed), `--log-dir`.

**Always dry-run a new task file first, and start with `--max-tasks 1`** on a single phone before unleashing a long queue.

## 4. Reports

`Reports` tab (one row per attempt outcome or event):

| Column | Values |
| :--- | :--- |
| `status` | `success`, `failed`, `error` (invalid task), `timeout`, `offline` (phone not reachable), `skipped` (no matching phone), or an event level `info` / `warning` / `error` |
| `attempts`, `duration_s` | Tries used and total time |
| `message`, `output` | What happened; structured detail (screenshot path, foreground app, per-step results of a flow) |

`Runs` tab: one summary row per run (workers, total, success, failed, other). A local copy of everything is in `logs/bulk-<run_id>.jsonl`.

Exit codes: `0` finished, `1` could not start (no devices / no task source), `4` tasks failed (with `--fail-on-error`).

## Troubleshooting
| Symptom | Fix |
| :--- | :--- |
| `No ADB devices found` | Open the phone profiles and confirm `adb devices` lists them. For GeeLark cloud phones, make sure ADB is enabled for the profile. |
| `claim failed: unauthorized` | `GEELARK_SHEETS_SECRET` does not match the `SECRET` script property. |
| `non_json_response` | The web app is not deployed as "Anyone", or you edited the script without redeploying a new version. |
| Reports missing in the sheet | `bulk-flush` replays anything spooled while the sheet was unreachable. |
| Tasks stay `running` | A previous run was killed. They are re-issued after 15 minutes, or set them to `pending`. |
| `open-app` says focus is another app | A permission or login dialog is on top. Add a `wait-text`/`click-text` step, or set `verify_s: 0`. |

## Safety
* Bulk runs change many accounts at once. Confirm the task list with a person before a real run, and never queue tasks you would not do by hand (posting, buying, messaging).
* Platforms may restrict accounts that behave like bots. Use `--task-delay` and sensible volumes; this tool does not hide automation.
* Treat the Apps Script URL + secret like a password: whoever has both can queue work onto your phones.
