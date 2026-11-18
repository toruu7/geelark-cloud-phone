#!/usr/bin/env python3
"""Cost rows must stay complete when a run dies: open at start, closed at stop, reconciled afterwards."""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for d in (os.path.join(ROOT, "scripts"), os.path.dirname(os.path.abspath(__file__))):
    if d not in sys.path:
        sys.path.insert(0, d)

import gl_cloudadb
import gl_cli
import gl_costs
from test_bulk import FakeSheet

NOW = 1_800_000_000.0
ISO = gl_costs._iso


def open_row(client, run_id, pid, started):
    client.call("cost", run_id=run_id, device="cloud:" + pid, phone_id=pid, minutes=0, cost="", currency="USD",
                status="open", started=ISO(started), ended="", note="")


class TestReconcile(unittest.TestCase):
    def test_a_killed_run_is_booked_from_the_registry_start_time(self):
        sheet = FakeSheet()
        open_row(sheet, "r1", "p1", NOW - 600)
        out = gl_costs.reconcile_costs(sheet, {"p1": NOW - 600}, 0.007, "USD", 8, now=NOW)
        row = sheet.cost_rows[("r1", "p1")]
        self.assertEqual((row["status"], row["minutes"]), ("recovered", 10.0))
        self.assertAlmostEqual(row["cost"], 0.07, places=4)
        self.assertEqual(out["closed"][0]["status"], "recovered")

    def test_a_stopped_phone_with_no_open_row_still_gets_a_row(self):
        sheet = FakeSheet()
        out = gl_costs.reconcile_costs(sheet, {"p9": NOW - 300}, 0.007, "USD", 8, now=NOW)
        self.assertEqual(len(out["created"]), 1)
        row = list(sheet.cost_rows.values())[0]
        self.assertEqual((row["phone_id"], row["status"], row["minutes"]), ("p9", "recovered", 5.0))

    def test_an_old_open_row_with_no_registry_is_estimated_and_capped(self):
        sheet = FakeSheet()
        open_row(sheet, "r1", "p1", NOW - 3 * 3600)               # three hours ago, end never recorded
        out = gl_costs.reconcile_costs(sheet, None, 0.01, "USD", 8, now=NOW)
        row = sheet.cost_rows[("r1", "p1")]
        self.assertEqual(row["status"], "estimated")
        self.assertEqual(row["minutes"], 10.0)                    # per-phone cap 8 + 2 boot, never the 180 minutes of age
        self.assertIn("estimated", row["note"])

    def test_a_recent_open_row_is_left_alone(self):
        sheet = FakeSheet()
        open_row(sheet, "r1", "p1", NOW - 5 * 60)                 # another runner may still own it
        out = gl_costs.reconcile_costs(sheet, None, 0.01, "USD", 8, now=NOW)
        self.assertEqual(sheet.cost_rows[("r1", "p1")]["status"], "open")
        self.assertEqual(out["closed"], [])

    def test_a_late_open_never_reopens_a_closed_row(self):
        sheet = FakeSheet()
        sheet.call("cost", run_id="r", device="d", phone_id="p", minutes=4, status="closed")
        open_row(sheet, "r", "p", NOW)
        self.assertEqual(sheet.cost_rows[("r", "p")]["status"], "closed")

    def test_an_old_sheet_script_is_reported_not_fatal(self):
        class OldScript:
            def call(self, verb, **kw):
                return {"ok": False, "error": "unknown_action"}
        out = gl_costs.reconcile_costs(OldScript(), None, 0.01, "USD", 8, now=NOW)
        self.assertIn("redeploy", out["skipped"])

    def test_no_sheet_and_errors_never_raise(self):
        self.assertEqual(gl_costs.reconcile_costs(None)["skipped"], "no sheet")

        class Broken:
            def call(self, verb, **kw):
                raise RuntimeError("boom")
        self.assertIn("boom", gl_costs.reconcile_costs(Broken())["skipped"])


class TestStopSweepBooksCost(unittest.TestCase):
    def test_stop_leftovers_reports_when_each_phone_started(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            gl_cloudadb._registry_update(d, lambda reg: reg.__setitem__("p1", {"since": 1234}))
            res = gl_cloudadb.stop_leftovers(d, down_fn=lambda pid, log_dir: gl_cloudadb._registry_update(log_dir, lambda r: r.pop(pid, None)))
            self.assertEqual(res["since"], {"p1": 1234})

    def test_the_cli_helper_books_recovered_phones(self):
        sheet = FakeSheet()
        sheet.settings = lambda: {"cost_per_phone_minute": "0.01", "currency": "usd"}
        open_row(sheet, "r1", "p1", NOW - 120)
        res = gl_cli._book_recovered_costs({"stopped": ["p1"], "failed": [], "since": {"p1": 1}}, client=sheet)
        self.assertIn("costs_reconciled", res)
        self.assertEqual(sheet.cost_rows[("r1", "p1")]["status"], "recovered")


if __name__ == "__main__":
    unittest.main()
