---
name: geelark-daily-operator
description: Operate the daily GeeLark cloud-phone routine unattended (a scheduled cloud agent with no human present). Runs the sheet-driven runner once, makes sure every cloud phone is stopped, uses the geelark-cloud-adb skill only for stopping phones or one bounded diagnosis, and reports the result. Use only for the scheduled daily run.
---

# GeeLark daily operator

You are running **unattended**: nobody can answer questions, so never ask for confirmation. Phones bill per minute while running. Your job is to run the plan the sheet already defines, make sure nothing is left running, and report honestly.

The plan (which phones, which tasks, in what order, limits, pause switch) lives in the Google Sheet. The runner reads it. You do not decide what the phones do.

## Hard rules
- Never like, follow, subscribe, comment, post, message, buy, log in, approve permissions or enter any credentials. If a screen asks for any of these, leave it and report it.
- Never print, log, or paste the value of `GEELARK_API_TOKEN`, `GEELARK_SHEETS_URL` or `GEELARK_SHEETS_SECRET`. Check only whether they are set.
- Run the runner **once**. Never loop or re-run it; the sheet owns retries.
- Use only the commands below. Do not edit files, open pull requests, or touch anything outside this task.
- Whatever happens, finish with every phone stopped (step 5).

## Steps (from the repository root)

1. **Preconditions.** Check `python3 --version` and that the three variables above are SET. If `GEELARK_TRANSPORT` is `api`, no adb is needed (everything goes over HTTPS). Otherwise check `adb version` (if missing run `apt-get update && apt-get install -y adb`; the update matters, because a fresh sandbox has empty package lists). If something is missing, stop and report exactly what (nothing has started yet).

2. **Is there work?**
   `python3 scripts/geelark.py bulk-run --only-cloud --probe`
   Read the `status` field: `idle` or `paused` or `busy` means report that and finish (do not start anything). `work` means continue. `error` means report the `message` and finish.

3. **Run the plan once.**
   `python3 scripts/geelark.py bulk-run --only-cloud`
   It prints JSON. Note `total`, `success`, `failed`, `other`, `cloud.started`, `cloud.stopped`, `cloud.stop_failures`, `cloud.phone_minutes` and `log`. Per-task detail is already in the sheet (Reports tab); do not try to re-create it.

4. **If tasks failed** (`failed` or `other` above zero): you may investigate **once per affected phone, for at most 5 minutes**, using the `geelark-cloud-adb` skill (`.claude/skills/geelark-cloud-adb`):
   `python3 .claude/skills/geelark-cloud-adb/scripts/geelark_adb.py up --id <phone id>`, then `shot`, `ui`, `focus` to see what blocked the task, then `down`.
   You may dismiss a harmless obstacle (a "Not now", "Skip", "Close" or "Got it" dialog) but do nothing else on the phone, and do not retry the failed task. Describe what you saw in the report. The phone id is the part after `cloud:` in `cloud.started`.

5. **Always make sure everything is stopped.**
   `python3 scripts/geelark.py bulk-cloud-stop`
   Then for every phone in `cloud.started` that is not in `cloud.stopped`, or whenever `cloud.stop_failures` is not empty, or the runner crashed without output, stop each phone by id:
   `python3 .claude/skills/geelark-cloud-adb/scripts/geelark_adb.py down --id <phone id>`
   (If adb is unavailable and `GEELARK_TRANSPORT=api`, `python3 scripts/geelark.py bulk-cloud-stop` already stops by API; if a phone still fails, report it.)
   Retry a failed stop up to 3 times. If a phone still cannot be stopped, say so prominently in the report: it may still be billing.

6. **Report** in a few lines: what ran (or why nothing ran), counts of OK / failed / other, phone-minutes, whether every phone was confirmed stopped, and anything that needs a human (failed tasks and why, stop failures, missing setup). Do not include secrets. Point to the sheet's Overview and Reports tabs for detail.

## Reference
- The runner: `scripts/geelark.py bulk-run` (see `references/unattended.md`). Exit codes: 0 finished/idle/paused/busy, 1 could not run, 4 failures.
- The phone skill: `.claude/skills/geelark-cloud-adb/SKILL.md` (commands: up, down, status, shot, ui, tap-text, key, focus).
- Needed environment variables: `GEELARK_API_TOKEN`, `GEELARK_SHEETS_URL`, `GEELARK_SHEETS_SECRET`; optional `GEELARK_TRANSPORT=api` (HTTPS-only, no adb; required in a Claude cloud environment, which blocks raw TCP).
