"""Keep the Costs tab complete even when a run dies.

A cloud phone's cost row is opened when it starts billing and closed when it stops (see Reporter.cost). If the run is killed,
crashes, loses its sandbox or the PC sleeps, the row stays "open". `reconcile_costs` closes such rows:

  * a phone that the stop sweep just stopped (the local registry knows when it started) is booked as "recovered" with its real
    start time, and a row is created when the sheet never got the open record;
  * an open row older than `stale_after_min` whose phone is not in the registry is booked as "estimated": the end was never
    recorded, so it is the shorter of its age and the per-phone cap plus boot time, and the note says so.

Rows younger than that are left alone: another runner may still own them.
"""

import time
from datetime import datetime, timezone

STALE_AFTER_MIN = 30
BOOT_ALLOWANCE_MIN = 2.0


def _parse(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def reconcile_costs(client, since_by_pid=None, cost_per_minute=None, currency="USD", max_phone_minutes=8.0,
                    now=None, stale_after_min=STALE_AFTER_MIN):
    """Close open cost rows. Returns {"closed": [...], "created": [...], "skipped": reason or None}. Never raises."""
    out = {"closed": [], "created": [], "skipped": None}
    if client is None:
        out["skipped"] = "no sheet"
        return out
    now = time.time() if now is None else now
    since_by_pid = {str(k): v for k, v in (since_by_pid or {}).items() if v}
    cap = (max_phone_minutes or 8.0) + BOOT_ALLOWANCE_MIN
    try:
        res = client.call("costs_open")
    except Exception as e:                                    # a bookkeeping call must never break a run
        out["skipped"] = f"costs_open failed: {e}"
        return out
    if not res.get("ok"):
        out["skipped"] = f"costs_open not available ({res.get('error', 'unknown')}); redeploy the sheet script"
        rows = []
    else:
        rows = list(res.get("rows") or [])
    handled = set()

    def book(row, minutes, status, note, started_epoch, ended_epoch):
        payload = {"run_id": row["run_id"], "device": row.get("device", ""), "phone_id": str(row["phone_id"]),
                   "minutes": round(minutes, 2),
                   "cost": round(minutes * cost_per_minute, 4) if cost_per_minute else "", "currency": currency or "",
                   "status": status, "started": _iso(started_epoch), "ended": _iso(ended_epoch), "note": note}
        return bool(client.call("cost", **payload).get("ok"))

    for pid, since in since_by_pid.items():
        mine = sorted((r for r in rows if str(r.get("phone_id")) == pid), key=lambda r: _parse(r.get("started")) or 0)
        minutes = max(0.0, (now - float(since)) / 60)
        if mine:
            for r in mine[:-1]:                                # an older open row for the same phone: its end is unknown
                s = _parse(r.get("started")) or now
                est = min(max(0.0, (now - s) / 60), cap)
                if book(r, est, "estimated", "end was not recorded; estimated", s, s + est * 60):
                    out["closed"].append({"phone_id": pid, "run_id": r["run_id"], "status": "estimated", "minutes": round(est, 2)})
                handled.add(id(r))
            last = mine[-1]
            handled.add(id(last))
            if book(last, minutes, "recovered", "run ended abnormally; phone stopped by the stop sweep", float(since), now):
                out["closed"].append({"phone_id": pid, "run_id": last["run_id"], "status": "recovered", "minutes": round(minutes, 2)})
        else:
            stamp = datetime.fromtimestamp(float(since), timezone.utc).strftime("%Y%m%d-%H%M%S")
            row = {"run_id": "recovered-" + stamp, "device": "cloud:" + pid, "phone_id": pid}
            if book(row, minutes, "recovered", "no open record in the sheet; booked from the local registry", float(since), now):
                out["created"].append({"phone_id": pid, "run_id": row["run_id"], "minutes": round(minutes, 2)})
    for r in rows:
        if id(r) in handled:
            continue
        s = _parse(r.get("started"))
        if s is None or (now - s) / 60 < stale_after_min:
            continue
        est = min((now - s) / 60, cap)
        if book(r, est, "estimated", "end was not recorded; estimated from the per-phone cap", s, s + est * 60):
            out["closed"].append({"phone_id": str(r.get("phone_id")), "run_id": r["run_id"], "status": "estimated", "minutes": round(est, 2)})
    return out
