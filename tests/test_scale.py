#!/usr/bin/env python3
"""Running many cloud phones: shared API throttle, per-phone and daily phone-minute caps, and waves.
Fake phones and a fake sheet; nothing is started or billed."""

import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for d in (os.path.join(ROOT, "scripts"), os.path.dirname(os.path.abspath(__file__))):
    if d not in sys.path:
        sys.path.insert(0, d)

import gl_bulk
import gl_cli
import gl_cloud
from test_bulk_cloud import CloudCase


class TestThrottle(unittest.TestCase):
    def setUp(self):
        gl_cloud._call_times.clear()
        self.addCleanup(gl_cloud._call_times.clear)

    def test_calls_over_the_limit_wait_for_the_window(self):
        clock = [0.0]
        slept = []

        def fake_sleep(s):
            slept.append(s)
            clock[0] += s

        with mock.patch.dict(os.environ, {"GEELARK_API_RATE_PER_MIN": "3"}):
            for _ in range(3):
                gl_cloud._throttle(now=lambda: clock[0], sleep=fake_sleep)
            self.assertEqual(slept, [])                        # three calls fit in the window
            gl_cloud._throttle(now=lambda: clock[0], sleep=fake_sleep)
        self.assertTrue(slept and sum(slept) >= 59.9)          # the fourth waits for the first to age out

    def test_zero_disables_the_throttle(self):
        with mock.patch.dict(os.environ, {"GEELARK_API_RATE_PER_MIN": "0"}):
            for _ in range(500):
                gl_cloud._throttle(now=lambda: 0.0, sleep=lambda s: self.fail("should not wait"))

    def test_default_is_below_the_api_limit(self):
        self.assertLess(gl_cloud.DEFAULT_RATE_PER_MIN, 200)


class TestSettings(unittest.TestCase):
    def test_caps_have_defaults_and_read_the_sheet(self):
        cfg, ignored = gl_bulk.resolve_settings({}, {})
        self.assertEqual((cfg["max_phone_minutes"], cfg["daily_phone_minutes"]), (8.0, 120.0))
        cfg, ignored = gl_bulk.resolve_settings({}, {"max_phone_minutes": "12", "daily_phone_minutes": "200"})
        self.assertEqual((cfg["max_phone_minutes"], cfg["daily_phone_minutes"]), (12.0, 200.0))
        self.assertEqual(ignored, [])

    def test_cli_beats_sheet_and_nonsense_is_ignored(self):
        cfg, _ = gl_bulk.resolve_settings({"daily_phone_minutes": 30.0}, {"daily_phone_minutes": "200"})
        self.assertEqual(cfg["daily_phone_minutes"], 30.0)
        cfg, ignored = gl_bulk.resolve_settings({}, {"max_phone_minutes": "abc", "daily_phone_minutes": "0"})
        self.assertEqual((cfg["max_phone_minutes"], cfg["daily_phone_minutes"]), (8.0, 120.0))
        self.assertEqual(len(ignored), 2)


class TestCaps(CloudCase):
    def key(self, task_id, device="", name="home"):
        return {"task_id": task_id, "device": device, "action": "key", "params": {"name": name}}

    def test_per_phone_cap_stops_new_tasks_but_not_the_running_one(self):
        tasks = [self.key(f"c{i}", "cloud:abc") for i in range(1, 5)]
        res, sheet = self.run_tasks(tasks, cloud=True, max_phone_minutes=0.001, task_delay=0.2)   # cap = 0.06 s
        by = {r["task_id"]: r["status"] for r in sheet.reports}
        self.assertEqual(by["c1"], "success")
        self.assertEqual(res["caps"]["phones_capped"], ["cloud:abc"])
        self.assertTrue(any("per-phone cap" in l["message"] for l in sheet.logs))
        self.assertEqual(self.cloud.down_calls, ["abc"])       # the phone is still stopped

    def test_each_cloud_phone_logs_its_minutes_and_cost(self):
        tasks = [self.key("c1", "cloud:abc")]
        res, sheet = self.run_tasks(tasks, cloud=True, cost_per_minute=0.5, currency="EUR")
        self.assertEqual(len(sheet.costs), 1)
        row = sheet.costs[0]
        self.assertEqual((row["device"], row["phone_id"], row["currency"]), ("cloud:abc", "abc", "EUR"))
        self.assertGreater(row["minutes"] + 1, 0)
        self.assertAlmostEqual(row["cost"], round(row["minutes"] * 0.5, 4), places=2)
        self.assertEqual(list(res["cloud"]["per_phone_minutes"]), ["cloud:abc"])
        self.assertIsNotNone(res["cloud"]["estimated_cost"])

    def test_without_a_rate_minutes_are_logged_and_cost_is_blank(self):
        res, sheet = self.run_tasks([self.key("c1", "cloud:abc")], cloud=True)
        self.assertEqual(sheet.costs[0]["cost"], "")
        self.assertIsNone(res["cloud"]["estimated_cost"])

    def test_a_cost_row_is_written_even_when_the_phone_never_came_up(self):
        self.cloud.up_error = "boom"
        res, sheet = self.run_tasks([self.key("c1", "cloud:abc")], cloud=True, cost_per_minute=1)
        self.assertEqual(len(sheet.costs), 1)               # it was started (billing may have begun), so it is counted

    def test_cost_settings_come_from_the_sheet(self):
        cfg, ignored = gl_bulk.resolve_settings({}, {"cost_per_phone_minute": "0.004", "currency": "eur"})
        self.assertEqual((cfg["cost_per_minute"], cfg["currency"]), (0.004, "EUR"))
        cfg, ignored = gl_bulk.resolve_settings({}, {"cost_per_phone_minute": "abc", "currency": "not a currency"})
        self.assertEqual((cfg["cost_per_minute"], cfg["currency"]), (None, "USD"))
        self.assertEqual(len(ignored), 2)

    def test_no_cap_runs_everything(self):
        tasks = [self.key(f"c{i}", "cloud:abc") for i in range(1, 4)]
        res, sheet = self.run_tasks(tasks, cloud=True, max_phone_minutes=None, daily_phone_minutes=None)
        self.assertEqual(res["success"], 3)
        self.assertEqual(res["caps"]["phones_capped"], [])

    def test_daily_cap_already_used_up_starts_no_phone(self):
        gl_bulk.add_daily_used_s(self.tmp.name, 125 * 60)      # 125 min used earlier today
        res, sheet = self.run_tasks([self.key("c1", "cloud:abc")], cloud=True, daily_phone_minutes=120)
        self.assertEqual(self.cloud.up_calls, [])              # nothing started, nothing billed
        self.assertTrue(res["caps"]["daily_cap_reached"])
        self.assertTrue(any("daily cap" in l["message"] for l in sheet.logs))

    def test_daily_total_is_saved_across_runs(self):
        self.run_tasks([self.key("c1", "cloud:abc")], cloud=True, daily_phone_minutes=120)
        used = gl_bulk.daily_used_s(self.tmp.name)
        self.assertGreater(used, 0)
        self.run_tasks([self.key("c2", "cloud:abc")], cloud=True, daily_phone_minutes=120)
        self.assertGreater(gl_bulk.daily_used_s(self.tmp.name), used)

    def test_day_total_resets_on_a_new_day(self):
        gl_bulk.add_daily_used_s(self.tmp.name, 500, today="2026-11-07")
        self.assertEqual(gl_bulk.daily_used_s(self.tmp.name, today="2026-11-08"), 0.0)
        self.assertEqual(gl_bulk.daily_used_s(self.tmp.name, today="2026-11-07"), 500.0)


class FakeClient:
    def __init__(self, devices):
        self.devices = devices

    def pending_summary(self):
        return {"devices": self.devices, "blank": 0}


def result(**kw):
    base = {"status": "success", "run_id": "r", "total": 2, "success": 2, "failed": 0, "other": 0, "workers": ["cloud:a"],
            "cloud": {"started": ["cloud:a"], "stopped": ["cloud:a"], "stop_failures": [], "phone_minutes": 2.0},
            "caps": {"daily_cap_reached": False, "phones_capped": []}, "sheet_write_failures": 0}
    base.update(kw)
    return base


class TestWaves(unittest.TestCase):
    cfg = {"max_runtime": None}

    def more(self, res, client, tasks=None, wave=0, waves=3, cfg=None, started=None):
        return gl_cli._more_waves(res, client, tasks, cfg or self.cfg, started if started is not None else time.monotonic(), wave, waves)

    def test_goes_on_while_cloud_phones_still_wait(self):
        self.assertTrue(self.more(result(), FakeClient(["cloud:b"])))

    def test_stops_when_nothing_cloud_is_waiting(self):
        self.assertFalse(self.more(result(), FakeClient([])))
        self.assertFalse(self.more(result(), FakeClient(["192.168.0.5:5555"])))   # local phones do not count

    def test_stops_after_the_wave_limit(self):
        self.assertFalse(self.more(result(), FakeClient(["cloud:b"]), wave=2, waves=3))
        self.assertFalse(self.more(result(), FakeClient(["cloud:b"]), wave=0, waves=1))

    def test_stops_when_a_cap_was_hit_or_nothing_started_or_interrupted(self):
        client = FakeClient(["cloud:b"])
        self.assertFalse(self.more(result(caps={"daily_cap_reached": True}), client))
        self.assertFalse(self.more(result(cloud={"started": []}), client))
        self.assertFalse(self.more(result(interrupted=True), client))
        self.assertFalse(self.more(result(status="error"), client))

    def test_stops_when_max_runtime_is_used_up_and_never_in_task_file_mode(self):
        client = FakeClient(["cloud:b"])
        self.assertFalse(self.more(result(), client, cfg={"max_runtime": 60}, started=time.monotonic() - 120))
        self.assertFalse(self.more(result(), client, tasks=[{"task_id": "x"}]))

    def test_merge_adds_up_the_waves(self):
        w1 = result(run_id="r1", total=10, success=9, failed=1, workers=["cloud:a"],
                    cloud={"started": ["cloud:a"], "stopped": ["cloud:a"], "stop_failures": [], "phone_minutes": 5.0})
        w2 = result(run_id="r2", total=6, success=6, failed=0, workers=["cloud:b"],
                    cloud={"started": ["cloud:b"], "stopped": ["cloud:b"], "stop_failures": ["b"], "phone_minutes": 3.5},
                    caps={"daily_cap_reached": True, "phones_capped": ["cloud:b"]})
        out = gl_cli._merge_waves([w1, w2])
        self.assertEqual((out["total"], out["success"], out["failed"]), (16, 15, 1))
        self.assertEqual(out["workers"], ["cloud:a", "cloud:b"])
        self.assertEqual(out["cloud"]["started"], ["cloud:a", "cloud:b"])
        self.assertEqual(out["cloud"]["stop_failures"], ["b"])
        self.assertEqual(out["cloud"]["phone_minutes"], 8.5)
        self.assertTrue(out["caps"]["daily_cap_reached"])
        self.assertEqual((out["waves"], out["run_ids"]), (2, ["r1", "r2"]))

    def test_single_wave_is_returned_unchanged(self):
        r = result()
        self.assertIs(gl_cli._merge_waves([r]), r)


if __name__ == "__main__":
    unittest.main()
