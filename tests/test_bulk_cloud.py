#!/usr/bin/env python3
"""Cloud-phone support in bulk runs: opt-in start, task isolation, and the guarantee that phones get stopped.
Uses fake cloud up/down, fake ADB and a fake sheet; nothing is started or billed."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for d in (os.path.join(ROOT, "scripts"), os.path.dirname(os.path.abspath(__file__))):
    if d not in sys.path:
        sys.path.insert(0, d)

import gl_bulk
import gl_cloudadb
import test_bulk
from test_bulk import FakeAdb, FakeSheet, PatchedCase

CLOUD_SERIAL = "10.1.2.3:5555"


class FakeCloud:
    def __init__(self, up_error=None, down_error=None):
        self.up_calls, self.down_calls = [], []
        self.up_error, self.down_error = up_error, down_error

    def up(self, pid, log_dir, timeout=180):
        self.up_calls.append(pid)
        if self.up_error:
            raise gl_cloudadb.CloudError(self.up_error)
        return CLOUD_SERIAL

    def down(self, pid, log_dir, attempts=3):
        self.down_calls.append(pid)
        if self.down_error:
            raise gl_cloudadb.CloudError(self.down_error)
        return True


class CloudCase(PatchedCase):
    def setUp(self):
        self.cloud = FakeCloud()
        self.fake = self.use_fake(FakeAdb(devices=("A", CLOUD_SERIAL), focus="com.google.android.youtube"))
        self.fake.devices = ["A"]          # the cloud serial only appears after `up`
        self.fake.state[CLOUD_SERIAL] = "device"
        for p in (patch.object(gl_cloudadb, "cloud_up", side_effect=self.cloud.up),
                  patch.object(gl_cloudadb, "cloud_down", side_effect=self.cloud.down)):
            p.start()
            self.addCleanup(p.stop)

    def run_tasks(self, tasks, **kw):
        sheet = kw.pop("sheet", FakeSheet())
        res = gl_bulk.run_bulk(tasks=tasks, client=sheet, log_dir=self.tmp.name, retries=0, **kw)
        return res, sheet


class TestCloudBulk(CloudCase):
    def key(self, task_id, device="", name="home"):
        return {"task_id": task_id, "device": device, "action": "key", "params": {"name": name}}

    def test_cloud_tasks_are_not_started_without_opt_in(self):
        res, sheet = self.run_tasks([self.key("c1", "cloud:abc"), self.key("l1")])
        self.assertEqual(self.cloud.up_calls, [])
        self.assertEqual(self.cloud.down_calls, [])
        by = {r["task_id"]: r for r in sheet.reports}
        self.assertEqual(by["l1"]["status"], "success")
        self.assertEqual(by["c1"]["status"], "skipped")
        self.assertIn("--cloud", by["c1"]["message"])
        self.assertTrue(any("not started" in l["message"] for l in sheet.logs))

    def test_cloud_phone_started_used_and_stopped(self):
        res, sheet = self.run_tasks([self.key("c1", "cloud:abc"), self.key("c2", "cloud:abc", "back")], cloud=True)
        self.assertEqual(self.cloud.up_calls, ["abc"])
        self.assertEqual(self.cloud.down_calls, ["abc"])
        self.assertEqual(len(self.fake.calls_for(CLOUD_SERIAL, "shell", "input", "keyevent")), 2)
        by = {r["task_id"]: r for r in sheet.reports}
        self.assertEqual({by["c1"]["status"], by["c2"]["status"]}, {"success"})
        self.assertEqual(by["c1"]["device"], "cloud:abc")      # sheet shows the cloud id, not the changing ip:port
        self.assertEqual(res["cloud"]["stopped"], ["cloud:abc"])
        self.assertEqual(res["cloud"]["stop_failures"], [])
        self.assertIn("phone-minutes", sheet.summaries[0]["notes"])
        self.assertTrue(any("billing starts" in l["message"] for l in sheet.logs))

    def test_cloud_worker_never_takes_any_phone_tasks(self):
        tasks = [self.key(f"any{i}") for i in range(4)] + [self.key("c1", "cloud:abc")]
        res, sheet = self.run_tasks(tasks, cloud=True)
        self.assertEqual(len(self.fake.calls_for(CLOUD_SERIAL, "shell", "input", "keyevent")), 1)
        self.assertEqual(len(self.fake.calls_for("A", "shell", "input", "keyevent")), 4)
        self.assertEqual(res["success"], 5)

    def test_phone_is_stopped_when_up_fails(self):
        self.cloud.up_error = "glogin: wrong password"
        res, sheet = self.run_tasks([self.key("c1", "cloud:abc")], cloud=True)
        self.assertEqual(self.cloud.down_calls, ["abc"])            # a half-started phone still bills
        self.assertTrue(any("could not" in l["message"] or "glogin" in l["message"] for l in sheet.logs if l["level"] == "error"))
        self.assertEqual([r["status"] for r in sheet.reports], ["skipped"])

    def test_phone_is_stopped_when_a_task_blows_up(self):
        with patch.object(gl_bulk, "execute_task", side_effect=RuntimeError("kaboom")):
            res, sheet = self.run_tasks([self.key("c1", "cloud:abc")], cloud=True)
        self.assertEqual(self.cloud.down_calls, ["abc"])
        self.assertTrue(any("crashed" in l["message"] for l in sheet.logs))

    def test_stop_failure_is_loud(self):
        self.cloud.down_error = "api timeout"
        res, sheet = self.run_tasks([self.key("c1", "cloud:abc")], cloud=True)
        self.assertEqual(res["cloud"]["stop_failures"], ["abc"])
        errs = [l for l in sheet.logs if l["level"] == "error" and "STOP FAILED" in l["message"]]
        self.assertEqual(len(errs), 1)
        self.assertIn("STOP FAILED", sheet.summaries[0]["notes"])

    def test_max_cloud_phones_cap(self):
        tasks = [self.key(f"c{i}", f"cloud:p{i}") for i in range(3)]
        res, sheet = self.run_tasks(tasks, cloud=True, max_cloud_phones=2)
        self.assertEqual(sorted(self.cloud.up_calls), ["p0", "p1"])
        self.assertEqual(sorted(self.cloud.down_calls), ["p0", "p1"])
        by = {r["task_id"]: r["status"] for r in sheet.reports}
        self.assertEqual(by["c2"], "skipped")
        self.assertTrue(any("limit" in l["message"] for l in sheet.logs))

    def test_sheet_mode_discovers_and_starts_cloud_phones(self):
        sheet = FakeSheet([self.key("c1", "cloud:abc"), self.key("any1")])
        res = gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name, cloud=True)
        self.assertEqual(self.cloud.up_calls, ["abc"])
        self.assertEqual(self.cloud.down_calls, ["abc"])
        self.assertEqual({r["task_id"]: r["status"] for r in sheet.reports}, {"c1": "success", "any1": "success"})

    def test_sheet_mode_without_opt_in_leaves_cloud_tasks_pending(self):
        sheet = FakeSheet([self.key("c1", "cloud:abc")])
        res = gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name)
        self.assertEqual(self.cloud.up_calls, [])
        self.assertEqual([t["task_id"] for t in sheet.queue], ["c1"])   # untouched, still claimable later

    def test_only_cloud_work_and_no_local_devices_still_runs(self):
        self.fake.devices = []
        res, sheet = self.run_tasks([self.key("c1", "cloud:abc")], cloud=True)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["success"], 1)

    def test_dry_run_lists_cloud_phones_without_starting_them(self):
        res = gl_bulk.run_bulk(tasks=[self.key("c1", "cloud:abc"), self.key("c2", "cloud:def")], dry_run=True, log_dir=self.tmp.name)
        self.assertEqual(res["cloud_phones_needed"], ["cloud:abc", "cloud:def"])
        self.assertEqual(self.cloud.up_calls, [])

    def test_invalid_cloud_device_rejected(self):
        for bad in ("cloud:", "cloud:a b", "cloud:x;y"):
            with self.assertRaises(gl_bulk.TaskError):
                gl_bulk.normalize_task({"action": "check-device", "device": bad})
        self.assertEqual(gl_bulk.normalize_task({"action": "check-device", "device": "cloud:Ab_1-2"})["device"], "cloud:Ab_1-2")


class TestCloudAdbWrapper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch("time.sleep")
        p.start()
        self.addCleanup(p.stop)

    def test_find_script_env_override_and_missing(self):
        f = os.path.join(self.tmp.name, "geelark_adb.py")
        open(f, "w").write("")
        with patch.dict(os.environ, {"GEELARK_CLOUD_ADB": f}):
            self.assertEqual(gl_cloudadb.find_script(), f)
        with patch.dict(os.environ, {"GEELARK_CLOUD_ADB": ""}), patch("os.path.isfile", return_value=False):
            with self.assertRaises(gl_cloudadb.CloudError):
                gl_cloudadb.find_script()

    def test_up_returns_validated_serial_and_registers(self):
        with patch.object(gl_cloudadb, "_run", return_value={"status": "success", "serial": "1.2.3.4:5555"}) as r:
            self.assertEqual(gl_cloudadb.cloud_up("abc", self.tmp.name, 90), "1.2.3.4:5555")
        self.assertEqual(r.call_args[0][0][:3], ["up", "--id", "abc"])
        self.assertIn("abc", gl_cloudadb.leftover_phones(self.tmp.name))   # tracked as billing until stopped

    def test_up_rejects_bad_results(self):
        for res in ({"status": "error", "message": "no"}, {"status": "success", "serial": "garbage"}, {"status": "success"}):
            with patch.object(gl_cloudadb, "_run", return_value=res):
                with self.assertRaises(gl_cloudadb.CloudError):
                    gl_cloudadb.cloud_up("abc", self.tmp.name)

    def test_down_clears_registry_and_retries(self):
        gl_cloudadb._registry_update(self.tmp.name, lambda d: d.__setitem__("abc", {}))
        results = [{"status": "error", "message": "busy"}, {"status": "success"}]
        with patch.object(gl_cloudadb, "_run", side_effect=results) as r:
            self.assertTrue(gl_cloudadb.cloud_down("abc", self.tmp.name))
        self.assertEqual(r.call_count, 2)
        self.assertEqual(gl_cloudadb.leftover_phones(self.tmp.name), {})
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, gl_cloudadb.REGISTRY_NAME)))

    def test_down_failure_keeps_phone_registered_and_raises(self):
        gl_cloudadb._registry_update(self.tmp.name, lambda d: d.__setitem__("abc", {}))
        with patch.object(gl_cloudadb, "_run", return_value={"status": "error", "message": "nope"}):
            with self.assertRaises(gl_cloudadb.CloudError):
                gl_cloudadb.cloud_down("abc", self.tmp.name, attempts=2)
        self.assertIn("abc", gl_cloudadb.leftover_phones(self.tmp.name))

    def test_stop_leftovers(self):
        for pid in ("a", "b"):
            gl_cloudadb._registry_update(self.tmp.name, lambda d, pid=pid: d.__setitem__(pid, {}))

        def fake_run(args, timeout):
            return {"status": "success"} if args[2] == "a" else {"status": "error", "message": "x"}
        with patch.object(gl_cloudadb, "_run", side_effect=fake_run):
            res = gl_cloudadb.stop_leftovers(self.tmp.name)
        self.assertEqual(res["stopped"], ["a"])
        self.assertEqual([f["id"] for f in res["failed"]], ["b"])

    def test_subprocess_output_parsing(self):
        class P:
            stdout, stderr, returncode = "not json", "", 1
        with patch.object(gl_cloudadb, "find_script", return_value="x.py"), patch("subprocess.run", return_value=P()):
            res = gl_cloudadb._run(["down", "--id", "a"], 5)
        self.assertEqual(res["status"], "error")
        with patch.object(gl_cloudadb, "find_script", return_value="x.py"), \
                patch("subprocess.run", side_effect=subprocess.TimeoutExpired("x", 5)):
            with self.assertRaises(gl_cloudadb.CloudError):
                gl_cloudadb._run(["up"], 5)

    def test_leftover_warning_on_next_run(self):
        gl_cloudadb._registry_update(self.tmp.name, lambda d: d.__setitem__("stale1", {}))
        fake = FakeAdb(devices=("A",))
        patches = test_bulk.adb_patches(fake)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        sheet = FakeSheet()
        gl_bulk.run_bulk(tasks=[{"action": "check-device"}], client=sheet, log_dir=self.tmp.name)
        self.assertTrue(any("stale1" in l["message"] and "bulk-cloud-stop" in l["message"] for l in sheet.logs))


class TestCloudCliAndSheet(unittest.TestCase):
    def test_commands_registered(self):
        import geelark
        import webhook_bridge
        self.assertIn("bulk-cloud-stop", geelark.LOCK_FREE_COMMANDS)
        self.assertNotIn("bulk-cloud-stop", webhook_bridge.ALLOWED_COMMANDS)

    def test_cli_dry_run_reports_cloud_phones(self):
        with tempfile.TemporaryDirectory() as d:
            tf = os.path.join(d, "t.json")
            json.dump([{"action": "check-device", "device": "cloud:abc"}], open(tf, "w"))
            env = {k: v for k, v in os.environ.items() if not k.startswith("GEELARK_SHEETS")}
            out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "geelark.py"), "bulk-run", "--tasks", tf, "--dry-run", "--log-dir", d],
                                 capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout)["cloud_phones_needed"], ["cloud:abc"])

    def test_cli_bulk_cloud_stop_with_nothing_to_stop(self):
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "geelark.py"), "bulk-cloud-stop", "--log-dir", d],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout)["stopped"], [])

    def test_apps_script_supports_devices_and_exact_claims(self):
        src = open(os.path.join(ROOT, "sheets", "apps_script.gs"), encoding="utf-8").read()
        for token in ("case 'devices'", "function devices_", "body.exact"):
            self.assertIn(token, src)

    def test_client_pending_devices_and_exact_claim_payload(self):
        import gl_sheets
        c = gl_sheets.SheetsClient("https://script.google.com/macros/s/X/exec", "s")
        with patch.object(c, "call", return_value={"ok": True, "devices": ["cloud:a", "B"]}):
            self.assertEqual(c.pending_devices(), ["cloud:a", "B"])
        with patch.object(c, "call", return_value={"ok": True, "tasks": []}) as call:
            c.claim("cloud:a", exact=True)
        self.assertEqual(call.call_args.kwargs["exact"], True)


if __name__ == "__main__":
    unittest.main()
