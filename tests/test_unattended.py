#!/usr/bin/env python3
"""Unattended-run behaviour: idle polling, cloud-only mode, sheet-controlled settings, failure policy,
runtime cap, overlap lock and signal handling. Fake ADB / cloud / sheet; nothing is started or billed."""

import json
import os
import signal
import sys
import tempfile
import time
import unittest
from unittest import mock
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for d in (os.path.join(ROOT, "scripts"), os.path.dirname(os.path.abspath(__file__))):
    if d not in sys.path:
        sys.path.insert(0, d)

import gl_bulk
import gl_cli
import gl_cloudadb
import gl_lock
import gl_sheets
from test_bulk import FakeAdb, FakeSheet, PatchedCase
from test_bulk_cloud import CLOUD_SERIAL, CloudCase, FakeCloud


_REAL_SLEEP = time.sleep  # captured before test fixtures patch time.sleep


def key(task_id, device="", name="home"):
    return {"task_id": task_id, "device": device, "action": "key", "params": {"name": name}}


class TestIdle(CloudCase):
    def test_empty_queue_is_idle_and_writes_nothing(self):
        sheet = FakeSheet()
        res = gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name, only_cloud=True)
        self.assertEqual(res["status"], "idle")
        self.assertEqual((sheet.reports, sheet.logs, sheet.summaries), ([], [], []))
        self.assertEqual(self.cloud.up_calls, [])

    def test_only_blank_device_tasks_are_idle_in_cloud_only_mode(self):
        sheet = FakeSheet([key("a"), key("b")])
        res = gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name, only_cloud=True)
        self.assertEqual(res["status"], "idle")
        self.assertEqual(res["waiting_without_cloud_device"], 2)
        self.assertEqual(len(sheet.queue), 2)                       # untouched
        self.assertEqual((sheet.reports, sheet.logs, sheet.summaries), ([], [], []))

    def test_cloud_only_ignores_local_adb_phones(self):
        sheet = FakeSheet([key("l1", "A"), key("c1", "cloud:abc")])
        res = gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name, only_cloud=True)
        self.assertEqual(res["workers"], ["cloud:abc"])
        self.assertEqual([r["task_id"] for r in sheet.reports], ["c1"])
        self.assertEqual(self.fake.calls_for("A", "shell", "input", "keyevent"), [])
        self.assertEqual([t["task_id"] for t in sheet.queue], ["l1"])
        self.assertEqual(self.cloud.down_calls, ["abc"])

    def test_cloud_only_implies_cloud_opt_in(self):
        sheet = FakeSheet([key("c1", "cloud:abc")])
        gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name, only_cloud=True, cloud=False)
        self.assertEqual(self.cloud.up_calls, ["abc"])

    def test_queue_read_failure_is_an_error_not_a_crash(self):
        class Broken(FakeSheet):
            def pending_summary(self):
                raise gl_sheets.SheetsError("devices failed: request_failed")
        res = gl_bulk.run_bulk(client=Broken(), log_dir=self.tmp.name, only_cloud=True)
        self.assertEqual(res["status"], "error")
        self.assertEqual(self.cloud.up_calls, [])


class TestProbe(CloudCase):
    def test_probe_reports_work_without_starting_anything(self):
        sheet = FakeSheet([key("c1", "cloud:abc")])
        res = gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name, only_cloud=True, probe=True)
        self.assertEqual(res["status"], "work")
        self.assertEqual(res["waiting_devices"], ["cloud:abc"])
        self.assertEqual(self.cloud.up_calls, [])
        self.assertEqual(len(sheet.queue), 1)                         # nothing claimed
        self.assertEqual((sheet.reports, sheet.logs, sheet.summaries), ([], [], []))

    def test_probe_idle_when_nothing_waits(self):
        res = gl_bulk.run_bulk(client=FakeSheet(), log_dir=self.tmp.name, only_cloud=True, probe=True)
        self.assertEqual(res["status"], "idle")

    def test_probe_ignores_blank_device_tasks_in_cloud_only_mode(self):
        res = gl_bulk.run_bulk(client=FakeSheet([key("a")]), log_dir=self.tmp.name, only_cloud=True, probe=True)
        self.assertEqual(res["status"], "idle")


class TestSequencingAndPolicy(CloudCase):
    def test_tasks_for_one_phone_run_in_order(self):
        sheet = FakeSheet([key(f"t{i}", "cloud:abc") for i in range(5)])
        gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name, only_cloud=True)
        self.assertEqual([r["task_id"] for r in sheet.reports], [f"t{i}" for i in range(5)])
        self.assertEqual(self.cloud.up_calls, ["abc"])               # one boot for the whole sequence
        self.assertEqual(self.cloud.down_calls, ["abc"])

    def test_two_phones_run_in_parallel_each_in_order(self):
        tasks = [key(f"a{i}", "cloud:aa") for i in range(3)] + [key(f"b{i}", "cloud:bb") for i in range(3)]
        sheet = FakeSheet(tasks)
        res = gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name, only_cloud=True, max_cloud_phones=2)
        self.assertEqual(res["success"], 6)
        for prefix in "ab":
            ids = [r["task_id"] for r in sheet.reports if r["task_id"].startswith(prefix)]
            self.assertEqual(ids, [f"{prefix}{i}" for i in range(3)])
        self.assertEqual(sorted(self.cloud.down_calls), ["aa", "bb"])

    def _failing_run(self, policy):
        tasks = [{"task_id": "t0", "device": "cloud:abc", "action": "assert-text", "params": {"text": "never there"}},
                 key("t1", "cloud:abc"), key("t2", "cloud:abc")]
        sheet = FakeSheet(tasks)
        gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name, only_cloud=True, retries=0, on_failure=policy)
        return {r["task_id"]: r for r in sheet.reports}, sheet

    def test_on_failure_continue_keeps_going(self):
        by, _ = self._failing_run("continue")
        self.assertEqual([by[t]["status"] for t in ("t0", "t1", "t2")], ["failed", "success", "success"])

    def test_on_failure_stop_skips_the_rest_for_that_phone_but_still_reports_them(self):
        by, sheet = self._failing_run("stop")
        self.assertEqual([by[t]["status"] for t in ("t0", "t1", "t2")], ["failed", "skipped", "skipped"])
        self.assertIn("on_failure", by["t1"]["message"])
        self.assertEqual(self.fake.calls_for(CLOUD_SERIAL, "shell", "input", "keyevent"), [])   # skipped tasks never touched the phone
        self.assertEqual(self.cloud.down_calls, ["abc"])
        self.assertEqual(sheet.queue, [])

    def test_failure_on_one_phone_does_not_stop_another(self):
        tasks = [{"task_id": "a0", "device": "cloud:aa", "action": "assert-text", "params": {"text": "nope"}}, key("a1", "cloud:aa"),
                 key("b0", "cloud:bb"), key("b1", "cloud:bb")]
        sheet = FakeSheet(tasks)
        gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name, only_cloud=True, retries=0, on_failure="stop", max_cloud_phones=2)
        by = {r["task_id"]: r["status"] for r in sheet.reports}
        self.assertEqual(by, {"a0": "failed", "a1": "skipped", "b0": "success", "b1": "success"})

    def test_max_runtime_stops_new_tasks_and_leaves_them_pending(self):
        sheet = FakeSheet([key(f"t{i}", "cloud:abc") for i in range(4)])
        real = gl_bulk.execute_task

        def slow(*a, **k):
            _REAL_SLEEP(0.3)            # real time passes while the fixture's time.sleep is a no-op
            return real(*a, **k)
        with patch.object(gl_bulk, "execute_task", side_effect=slow):
            res = gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name, only_cloud=True, max_runtime=0.2)
        self.assertEqual(len(sheet.reports), 1)                                  # first task ran, deadline passed during it
        self.assertEqual(len(sheet.queue), 3)                                    # the rest were never claimed: still pending
        self.assertTrue(any("max runtime" in l["message"] for l in sheet.logs))
        self.assertEqual(self.cloud.down_calls, ["abc"])                         # phone still stopped


class TestSettings(unittest.TestCase):
    def test_precedence_cli_over_sheet_over_default(self):
        cfg, ign = gl_bulk.resolve_settings({"retries": 3}, {"retries": 2, "max_cloud_phones": "4", "task_timeout_s": "300"})
        self.assertEqual((cfg["retries"], cfg["max_cloud_phones"], cfg["task_timeout"]), (3, 4, 300.0))
        self.assertEqual(ign, [])
        cfg, _ = gl_bulk.resolve_settings({}, {})
        self.assertEqual(cfg, gl_bulk.DEFAULT_SETTINGS)

    def test_units_and_policy(self):
        cfg, _ = gl_bulk.resolve_settings({}, {"max_runtime_min": "30", "on_failure": "Stop", "task_delay_s": "5"})
        self.assertEqual((cfg["max_runtime"], cfg["on_failure"], cfg["task_delay"]), (1800.0, "stop", 5.0))

    def test_invalid_sheet_values_are_ignored_and_reported(self):
        cfg, ign = gl_bulk.resolve_settings({}, {"retries": "lots", "max_cloud_phones": 99, "task_timeout_s": 1, "on_failure": "explode"})
        self.assertEqual((cfg["retries"], cfg["max_cloud_phones"], cfg["task_timeout"], cfg["on_failure"]), (1, 2, 120.0, "continue"))
        self.assertEqual(len(ign), 4)

    def test_blank_sheet_values_use_defaults_silently(self):
        cfg, ign = gl_bulk.resolve_settings({}, {"retries": "", "on_failure": ""})
        self.assertEqual((cfg["retries"], cfg["on_failure"], ign), (1, "continue", []))

    def test_truthy(self):
        for v in (True, "TRUE", "true", "Yes", "1", "on", " checked "):
            self.assertTrue(gl_sheets.truthy(v), v)
        for v in (False, "FALSE", "", None, "0", "no", "off"):
            self.assertFalse(gl_sheets.truthy(v), v)


class _Args:
    def __init__(self, **kw):
        base = dict(tasks=None, devices=None, retries=None, max_workers=None, max_tasks=None, task_timeout=None, task_delay=None,
                    max_runtime=None, on_failure=None, dry_run=False, no_sheet=False, log_dir=None, cloud=False,
                    max_cloud_phones=None, cloud_up_timeout=180, only_cloud=False, fail_on_error=False, probe=False)
        base.update(kw)
        self.__dict__.update(base)


class _SettingsSheet(FakeSheet):
    def __init__(self, settings, **kw):
        super().__init__(**kw)
        self._settings = settings

    def settings(self):
        return self._settings


class TestCliWrapper(unittest.TestCase):
    def setUp(self):
        self.out = []
        p = patch("builtins.print", side_effect=lambda *a, **k: self.out.append(a[0] if a else ""))
        p.start()
        self.addCleanup(p.stop)

    def test_paused_in_sheet_starts_nothing(self):
        sheet = _SettingsSheet({"paused": "TRUE"})
        with patch.object(gl_sheets.SheetsClient, "from_env", return_value=sheet), patch.object(gl_bulk, "run_bulk") as rb:
            code = gl_cli._bulk_run(_Args(only_cloud=True))
        self.assertEqual(code, 0)
        rb.assert_not_called()
        self.assertEqual(json.loads(self.out[-1])["status"], "paused")

    def test_sheet_settings_flow_into_the_run(self):
        sheet = _SettingsSheet({"retries": "2", "on_failure": "stop", "max_runtime_min": "45", "max_cloud_phones": "3"})
        with patch.object(gl_sheets.SheetsClient, "from_env", return_value=sheet), \
                patch.object(gl_bulk, "run_bulk", return_value={"status": "idle"}) as rb:
            self.assertEqual(gl_cli._bulk_run(_Args(only_cloud=True)), 0)
        kw = rb.call_args.kwargs
        self.assertEqual((kw["retries"], kw["on_failure"], kw["max_runtime"], kw["max_cloud_phones"]), (2, "stop", 2700.0, 3))
        self.assertTrue(kw["only_cloud"])

    def test_cli_flag_beats_sheet(self):
        sheet = _SettingsSheet({"retries": "2"})
        with patch.object(gl_sheets.SheetsClient, "from_env", return_value=sheet), \
                patch.object(gl_bulk, "run_bulk", return_value={"status": "idle"}) as rb:
            gl_cli._bulk_run(_Args(retries=0))
        self.assertEqual(rb.call_args.kwargs["retries"], 0)

    def test_second_runner_on_same_machine_gets_busy_not_an_error(self):
        lock_path = os.path.join(os.path.dirname(gl_lock.DeviceLock().path), "geelark-bulk-run.lock")
        sheet = _SettingsSheet({})
        with gl_lock.DeviceLock(lock_path, timeout=1):
            with patch.object(gl_sheets.SheetsClient, "from_env", return_value=sheet), patch.object(gl_bulk, "run_bulk") as rb:
                code = gl_cli._bulk_run(_Args(only_cloud=True))
        self.assertEqual(code, 0)
        rb.assert_not_called()
        self.assertEqual(json.loads(self.out[-1])["status"], "busy")

    def test_lock_released_after_run(self):
        sheet = _SettingsSheet({})
        with patch.object(gl_sheets.SheetsClient, "from_env", return_value=sheet), \
                patch.object(gl_bulk, "run_bulk", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                gl_cli._bulk_run(_Args(only_cloud=True))
        with patch.object(gl_sheets.SheetsClient, "from_env", return_value=sheet), \
                patch.object(gl_bulk, "run_bulk", return_value={"status": "idle"}):
            self.assertEqual(gl_cli._bulk_run(_Args(only_cloud=True)), 0)
        self.assertEqual(json.loads(self.out[-1])["status"], "idle")

    def test_only_cloud_without_a_source_is_an_error(self):
        with patch.object(gl_sheets.SheetsClient, "from_env", return_value=None):
            self.assertEqual(gl_cli._bulk_run(_Args(only_cloud=True)), 1)

    def test_exit_codes(self):
        sheet = _SettingsSheet({})
        with patch.object(gl_sheets.SheetsClient, "from_env", return_value=sheet):
            with patch.object(gl_bulk, "run_bulk", return_value={"status": "success", "failed": 2}):
                self.assertEqual(gl_cli._bulk_run(_Args(fail_on_error=True)), 4)
                self.assertEqual(gl_cli._bulk_run(_Args()), 0)
            with patch.object(gl_bulk, "run_bulk", return_value={"status": "error", "message": "x"}):
                self.assertEqual(gl_cli._bulk_run(_Args()), 1)

    def test_probe_cli_needs_no_lock_and_no_cloud_skill(self):
        sheet = _SettingsSheet({}, tasks=[key("c1", "cloud:abc")])
        lock_path = os.path.join(os.path.dirname(gl_lock.DeviceLock().path), "geelark-bulk-run.lock")
        with gl_lock.DeviceLock(lock_path, timeout=1):                # a run is in progress; probing must still work
            with patch.object(gl_sheets.SheetsClient, "from_env", return_value=sheet):
                code = gl_cli._bulk_run(_Args(only_cloud=True, probe=True))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.out[-1])["status"], "work")

    def test_probe_without_sheet_is_an_error(self):
        with patch.object(gl_sheets.SheetsClient, "from_env", return_value=None):
            self.assertEqual(gl_cli._bulk_run(_Args(only_cloud=True, probe=True)), 1)

    def test_idle_exit_code_is_zero(self):
        sheet = _SettingsSheet({})
        with patch.object(gl_sheets.SheetsClient, "from_env", return_value=sheet), \
                patch.object(gl_bulk, "run_bulk", return_value={"status": "idle"}):
            self.assertEqual(gl_cli._bulk_run(_Args(only_cloud=True)), 0)


class TestSignals(unittest.TestCase):
    def test_sigterm_becomes_keyboard_interrupt_so_phones_get_stopped(self):
        old = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, old)
        gl_cli._install_term_handler()
        handler = signal.getsignal(signal.SIGTERM)
        self.assertTrue(callable(handler))
        with self.assertRaises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)


class TestOptionalSteps(PatchedCase):
    def ctx(self):
        return gl_bulk.Ctx("A", "t", "r", time.monotonic() + 60, "x")

    def test_optional_wait_text_succeeds_when_absent(self):
        fake = self.use_fake(FakeAdb())
        fake.ui_xml = '<?xml version="1.0"?><hierarchy><node text="Other" bounds="[0,0][5,5]"/></hierarchy>'
        res = gl_bulk.ACTIONS["wait-text"]["run"](self.ctx(), {"text": "Skip", "timeout": 0, "click": True, "optional": True})
        self.assertEqual(res["status"], "success")
        self.assertIn("optional", res["message"])
        res = gl_bulk.ACTIONS["wait-text"]["run"](self.ctx(), {"text": "Skip", "timeout": 0, "click": True})
        self.assertEqual(res["status"], "failed")

    def test_optional_wait_text_still_clicks_when_present(self):
        fake = self.use_fake(FakeAdb())
        fake.ui_xml = '<?xml version="1.0"?><hierarchy><node text="Skip" clickable="true" bounds="[10,10][30,30]"/></hierarchy>'
        res = gl_bulk.ACTIONS["wait-text"]["run"](self.ctx(), {"text": "Skip", "timeout": 0, "click": True, "optional": True})
        self.assertEqual(res["output"]["coords"], [20, 20])


class TestKeepAwake(unittest.TestCase):
    def test_sets_and_releases_the_execution_state_on_windows(self):
        calls = []
        with mock.patch.object(gl_cli.sys, "platform", "win32"),              mock.patch.object(gl_cli.keep_awake, "_set", lambda self, flags: calls.append(flags) or 1):
            with gl_cli.keep_awake():
                self.assertEqual(calls, [gl_cli.keep_awake.ES_CONTINUOUS | gl_cli.keep_awake.ES_SYSTEM_REQUIRED])
        self.assertEqual(calls[-1], gl_cli.keep_awake.ES_CONTINUOUS)

    def test_releases_even_when_the_run_raises(self):
        calls = []
        with mock.patch.object(gl_cli.sys, "platform", "win32"),              mock.patch.object(gl_cli.keep_awake, "_set", lambda self, flags: calls.append(flags) or 1):
            with self.assertRaises(RuntimeError):
                with gl_cli.keep_awake():
                    raise RuntimeError("boom")
        self.assertEqual(calls[-1], gl_cli.keep_awake.ES_CONTINUOUS)

    def test_inactive_and_non_windows_do_nothing(self):
        calls = []
        with mock.patch.object(gl_cli.keep_awake, "_set", lambda self, flags: calls.append(flags) or 1):
            with gl_cli.keep_awake(active=False):
                pass
            with mock.patch.object(gl_cli.sys, "platform", "linux"):
                with gl_cli.keep_awake():
                    pass
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
