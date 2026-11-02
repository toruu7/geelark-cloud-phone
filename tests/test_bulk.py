#!/usr/bin/env python3
"""Tests for bulk automation: task validation, ADB actions, parallel runner, sheet client and reporting.
Everything runs against a fake ADB and a fake sheet; no phone or network is touched."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT_DIR = os.path.join(ROOT, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import gl_adb
import gl_bulk
import gl_sheets

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class FakeAdb:
    """Records calls and returns canned results per device."""

    def __init__(self, devices=("A", "B"), focus="com.google.android.youtube"):
        self.devices = list(devices)
        self.focus = focus
        self.calls = []
        self.state = {d: "device" for d in devices}
        self.fail_next = {}   # device -> number of upcoming `monkey` calls to fail
        self.ui_xml = ""
        self.lock = threading.Lock()

    def run_adb(self, args, device=None, timeout=None):
        with self.lock:
            self.calls.append((device, [str(a) for a in args]))
        a = [str(x) for x in args]
        if a[:2] == ["shell", "monkey"]:
            with self.lock:
                if self.fail_next.get(device, 0) > 0:
                    self.fail_next[device] -= 1
                    return {"returncode": 1, "stdout": "", "stderr": "boom"}
            return {"returncode": 0, "stdout": "Events injected: 1", "stderr": ""}
        if a[:3] == ["shell", "dumpsys", "window"]:
            return {"returncode": 0, "stdout": f"mCurrentFocus=Window{{abc u0 {self.focus}/com.x.Main}}", "stderr": ""}
        if a[:3] == ["shell", "wm", "size"]:
            return {"returncode": 0, "stdout": "Physical size: 1000x2000", "stderr": ""}
        if a[:2] == ["exec-out", "uiautomator"]:
            return {"returncode": 0, "stdout": self.ui_xml, "stderr": ""}
        if a[:3] == ["shell", "getprop", "ro.product.model"]:
            return {"returncode": 0, "stdout": "Pixel", "stderr": ""}
        if a[:2] == ["shell", "am"] and "start" in a and any("BAD" in x for x in a):
            return {"returncode": 0, "stdout": "Error: Activity not started, unable to resolve Intent", "stderr": ""}
        return {"returncode": 0, "stdout": "", "stderr": ""}

    def get_state(self, device):
        return self.state.get(device, "offline")

    def list_devices(self, use_cache=True):
        return list(self.devices)

    def calls_for(self, device, *prefix):
        return [c for d, c in self.calls if d == device and c[:len(prefix)] == list(prefix)]


class FakeSheet:
    def __init__(self, tasks=None, claim_error=False):
        self.queue = list(tasks or [])
        self.reports, self.logs, self.summaries = [], [], []
        self.claim_error = claim_error
        self.lock = threading.Lock()
        self.reject_writes = False

    def claim(self, worker, limit=1, exact=False):
        if self.claim_error:
            raise gl_sheets.SheetsError("claim failed: unauthorized")
        with self.lock:
            for i, t in enumerate(self.queue):
                dev = t.get("device") or ""
                if dev == worker or (dev == "" and not exact):
                    return [self.queue.pop(i)]
        return []

    def pending_devices(self):
        return sorted({t.get("device") for t in self.queue if t.get("device")})

    def call(self, verb, **payload):
        if self.reject_writes:
            return {"ok": False, "error": "request_failed"}
        with self.lock:
            {"report": self.reports, "log": self.logs, "summary": self.summaries}[verb].append(payload)
        return {"ok": True}

    def ping(self):
        return {"ok": True}


def adb_patches(fake):
    return [
        patch.object(gl_adb, "run_adb", side_effect=fake.run_adb),
        patch.object(gl_adb, "get_state", side_effect=fake.get_state),
        patch.object(gl_adb, "list_devices", side_effect=fake.list_devices),
        patch.object(gl_adb, "run_adb_bytes", return_value={"returncode": 0, "stdout": PNG, "stderr": ""}),
        patch("time.sleep"),
    ]


class PatchedCase(unittest.TestCase):
    def use_fake(self, fake):
        for p in adb_patches(fake):
            p.start()
            self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        return fake


class TestTaskValidation(unittest.TestCase):
    def test_valid_task_defaults(self):
        t = gl_bulk.normalize_task({"action": "open-app", "params": '{"name":"youtube"}'})
        self.assertEqual(t["action"], "open-app")
        self.assertEqual(t["device"], "")
        self.assertTrue(t["task_id"])

    def test_rejects_unknown_and_dangerous_actions(self):
        for act in ("shell", "adb", "rm", "", "install"):
            with self.assertRaises(gl_bulk.TaskError):
                gl_bulk.normalize_task({"action": act})

    def test_params_must_be_json_object_and_small(self):
        for bad in ("not json", "[1,2]", '"x"', "x" * (gl_bulk.MAX_PARAMS_BYTES + 1)):
            with self.assertRaises(gl_bulk.TaskError):
                gl_bulk.normalize_task({"action": "sleep", "params": bad})

    def test_device_serial_validated(self):
        with self.assertRaises(gl_bulk.TaskError):
            gl_bulk.normalize_task({"action": "check-device", "device": "x; rm -rf /"})
        gl_bulk.normalize_task({"action": "check-device", "device": "98.98.125.37:21127"})

    def test_per_action_parameter_rules(self):
        bad = [
            ("open-app", {}), ("open-app", {"name": "not a package!"}), ("deep-link", {"url": "javascript alert"}),
            ("deep-link", {"url": "no-scheme.com"}), ("key", {"name": "power"}), ("tap", {"x": 2, "y": 0.5}),
            ("tap", {"x": "a", "y": 1}), ("swipe", {"x1": 0, "y1": 0, "x2": 1}), ("type", {"text": "héllo"}),
            ("type", {"text": "x" * 501}), ("sleep", {"seconds": 99999}), ("click-text", {}),
            ("flow", {}), ("flow", {"steps": []}), ("flow", {"steps": [{"action": "flow", "steps": []}]}),
            ("flow", {"steps": [{"action": "key", "name": "nope"}]}),
        ]
        for action, params in bad:
            with self.assertRaises(gl_bulk.TaskError, msg=f"{action} {params}"):
                gl_bulk.normalize_task({"action": action, "params": params})

    def test_good_parameters_accepted(self):
        good = [
            ("open-app", {"name": "tiktok"}), ("open-app", {"name": "com.example.app"}),
            ("deep-link", {"url": "https://youtube.com/watch?v=a&t=3"}), ("deep-link", {"url": "tiktok://user/1"}),
            ("key", {"name": "back", "repeat": 3}), ("tap", {"x": 0.5, "y": 0.5}), ("type", {"text": "hello world"}),
            ("sleep", {"seconds": 2}), ("screenshot", {}), ("assert-text", {"text": "Home"}),
            ("flow", {"steps": [{"action": "key", "name": "home"}, {"action": "sleep", "seconds": 1}]}),
        ]
        for action, params in good:
            gl_bulk.normalize_task({"action": action, "params": params})

    def test_load_tasks_file_json_and_csv(self):
        with tempfile.TemporaryDirectory() as d:
            jp = os.path.join(d, "t.json")
            json.dump({"tasks": [{"action": "key", "params": {"name": "home"}}]}, open(jp, "w"))
            self.assertEqual(len(gl_bulk.load_tasks_file(jp)), 1)
            cp = os.path.join(d, "t.csv")
            open(cp, "w", encoding="utf-8").write('task_id,device,action,params\nt1,A,key,"{""name"": ""home""}"\n')
            rows = gl_bulk.load_tasks_file(cp)
            self.assertEqual(rows[0]["task_id"], "t1")
            self.assertEqual(gl_bulk.normalize_task(rows[0])["params"], {"name": "home"})
            json.dump({"nope": 1}, open(jp, "w"))
            with self.assertRaises(gl_bulk.TaskError):
                gl_bulk.load_tasks_file(jp)


class TestActions(PatchedCase):
    def ctx(self, device="A"):
        import time
        return gl_bulk.Ctx(device, "t1", "run", time.monotonic() + 60, os.path.join(self.tmp.name, "shots"))

    def run_action(self, fake, action, params, device="A"):
        return gl_bulk.ACTIONS[action]["run"](self.ctx(device), params)

    def test_deep_link_is_shell_quoted(self):
        fake = self.use_fake(FakeAdb())
        url = "https://y.com/w?v=1&t=3; reboot"
        res = self.run_action(fake, "deep-link", {"url": url})
        self.assertEqual(res["status"], "success")
        sent = fake.calls_for("A", "shell", "am", "start")[0]
        self.assertEqual(sent[-1], gl_adb.shell_quote(url))
        self.assertTrue(sent[-1].startswith("'") and sent[-1].endswith("'"))

    def test_deep_link_reports_unresolvable_intent(self):
        fake = self.use_fake(FakeAdb())
        res = self.run_action(fake, "deep-link", {"url": "https://BAD.example/x"})
        self.assertEqual(res["status"], "failed")

    def test_type_quotes_and_encodes_spaces(self):
        fake = self.use_fake(FakeAdb())
        self.run_action(fake, "type", {"text": "a b;$(x)", "enter": True})
        typed = fake.calls_for("A", "shell", "input", "text")[0]
        self.assertEqual(typed[-1], gl_adb.shell_quote("a%sb;$(x)"))
        self.assertTrue(fake.calls_for("A", "shell", "input", "keyevent"))

    def test_open_app_verifies_foreground(self):
        fake = self.use_fake(FakeAdb(focus="com.google.android.youtube"))
        self.assertEqual(self.run_action(fake, "open-app", {"name": "youtube"})["status"], "success")

    def test_open_app_fails_when_other_app_has_focus(self):
        fake = self.use_fake(FakeAdb(focus="com.android.settings"))
        res = gl_bulk._r_open_app(gl_bulk.Ctx("A", "t", "r", 10 ** 12, "x"), {"name": "youtube", "verify_s": 1})
        self.assertEqual(res["status"], "failed")
        self.assertIn("com.android.settings", res["message"])

    def test_open_app_launch_failure(self):
        fake = self.use_fake(FakeAdb())
        fake.fail_next["A"] = 1
        self.assertEqual(self.run_action(fake, "open-app", {"name": "youtube"})["status"], "failed")

    def test_key_repeat_and_tap_swipe_use_screen_size(self):
        fake = self.use_fake(FakeAdb())
        self.assertEqual(self.run_action(fake, "key", {"name": "back", "repeat": 2})["status"], "success")
        self.assertEqual(len(fake.calls_for("A", "shell", "input", "keyevent")), 2)
        res = self.run_action(fake, "tap", {"x": 0.5, "y": 0.25})
        self.assertEqual(res["output"]["coords"], [500, 500])
        self.assertEqual(self.run_action(fake, "swipe", {"x1": 0.5, "y1": 0.8, "x2": 0.5, "y2": 0.2})["status"], "success")

    def test_screenshot_saved_and_validated(self):
        fake = self.use_fake(FakeAdb())
        res = self.run_action(fake, "screenshot", {})
        self.assertEqual(res["status"], "success")
        self.assertTrue(os.path.exists(res["output"]["path"]))
        with patch.object(gl_adb, "run_adb_bytes", return_value={"returncode": 0, "stdout": b"garbage", "stderr": ""}):
            self.assertEqual(self.run_action(fake, "screenshot", {})["status"], "failed")

    def test_ui_tree_click_and_assert(self):
        fake = self.use_fake(FakeAdb())
        fake.ui_xml = ('<?xml version="1.0"?><hierarchy><node text="Skip" content-desc="" clickable="true" '
                       'bounds="[100,200][300,260]"/><node text="Other" content-desc="" bounds="[0,0][10,10]"/></hierarchy>'
                       "UI hierchary dumped to: /dev/tty")
        res = self.run_action(fake, "click-text", {"text": "skip"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["output"]["coords"], [200, 230])
        self.assertTrue(fake.calls_for("A", "shell", "input", "tap", "200", "230"))
        self.assertEqual(self.run_action(fake, "assert-text", {"text": "Other"})["status"], "success")
        self.assertEqual(self.run_action(fake, "assert-text", {"text": "Missing"})["status"], "failed")
        self.assertEqual(self.run_action(fake, "assert-text", {"text": "Missing", "absent": True})["status"], "success")

    def test_ui_parser_rejects_doctype_and_garbage(self):
        self.assertEqual(gl_bulk.parse_ui_nodes('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><hierarchy></hierarchy>'), [])
        self.assertEqual(gl_bulk.parse_ui_nodes("nonsense"), [])
        self.assertEqual(gl_bulk.parse_ui_nodes('<?xml version="1.0"?><hierarchy><node'), [])

    def test_flow_stops_on_first_failure_and_reports_steps(self):
        fake = self.use_fake(FakeAdb())
        steps = [{"action": "key", "name": "home"}, {"action": "assert-text", "text": "Nope"}, {"action": "key", "name": "back"}]
        res = self.run_action(fake, "flow", {"steps": steps})
        self.assertEqual(res["status"], "failed")
        self.assertEqual([s["status"] for s in res["output"]], ["success", "failed"])
        res2 = self.run_action(fake, "flow", {"steps": steps, "continue_on_error": True})
        self.assertEqual(len(res2["output"]), 3)

    def test_check_device(self):
        fake = self.use_fake(FakeAdb())
        res = self.run_action(fake, "check-device", {})
        self.assertEqual(res["output"]["model"], "Pixel")
        fake.state["A"] = "offline"
        self.assertEqual(self.run_action(fake, "check-device", {})["status"], "failed")

    def test_sleep_respects_deadline(self):
        self.use_fake(FakeAdb())
        import time
        ctx = gl_bulk.Ctx("A", "t", "r", time.monotonic() - 1, "x")
        with self.assertRaises(gl_bulk.TaskTimeout):
            gl_bulk.ACTIONS["sleep"]["run"](ctx, {"seconds": 5})


class TestRunner(PatchedCase):
    def run_local(self, fake, tasks, **kw):
        self.use_fake(fake)
        sheet = FakeSheet()
        res = gl_bulk.run_bulk(tasks=tasks, client=sheet, log_dir=self.tmp.name, retries=kw.pop("retries", 1), **kw)
        return res, sheet

    def test_tasks_run_in_parallel_on_their_devices(self):
        fake = FakeAdb(devices=("A", "B"))
        tasks = [{"task_id": f"a{i}", "device": "A", "action": "key", "params": {"name": "home"}} for i in range(3)]
        tasks += [{"task_id": f"b{i}", "device": "B", "action": "key", "params": {"name": "back"}} for i in range(2)]
        res, sheet = self.run_local(fake, tasks)
        self.assertEqual((res["total"], res["success"], res["failed"]), (5, 5, 0))
        self.assertEqual(len(fake.calls_for("A", "shell", "input", "keyevent")), 3)
        self.assertEqual(len(fake.calls_for("B", "shell", "input", "keyevent")), 2)
        self.assertEqual(len(sheet.reports), 5)
        self.assertEqual(len(sheet.summaries), 1)
        self.assertEqual(sheet.summaries[0]["success"], 5)

    def test_any_device_tasks_are_shared(self):
        fake = FakeAdb(devices=("A", "B"))
        tasks = [{"task_id": f"t{i}", "action": "key", "params": {"name": "home"}} for i in range(6)]
        res, sheet = self.run_local(fake, tasks)
        self.assertEqual(res["success"], 6)
        self.assertEqual({r["task_id"] for r in sheet.reports}, {f"t{i}" for i in range(6)})

    def test_retry_then_success_records_attempts(self):
        fake = FakeAdb(devices=("A",))
        fake.fail_next["A"] = 1
        res, sheet = self.run_local(fake, [{"task_id": "r", "action": "open-app", "params": {"name": "youtube"}}])
        self.assertEqual(res["success"], 1)
        self.assertEqual(sheet.reports[0]["attempts"], 2)
        self.assertTrue(any(l["level"] == "warning" for l in sheet.logs))

    def test_failure_after_retries_is_reported_failed(self):
        fake = FakeAdb(devices=("A",))
        fake.fail_next["A"] = 5
        res, sheet = self.run_local(fake, [{"task_id": "r", "action": "open-app", "params": {"name": "youtube"}}], retries=2)
        self.assertEqual((res["success"], res["failed"]), (0, 1))
        self.assertEqual(sheet.reports[0]["attempts"], 3)
        self.assertEqual(sheet.reports[0]["status"], "failed")

    def test_invalid_tasks_are_reported_not_dropped(self):
        fake = FakeAdb(devices=("A",))
        tasks = [{"task_id": "bad", "action": "shell", "params": {"cmd": "id"}},
                 {"task_id": "ok", "action": "key", "params": {"name": "home"}}]
        res, sheet = self.run_local(fake, tasks)
        self.assertEqual((res["total"], res["success"], res["failed"]), (2, 1, 1))
        bad = [r for r in sheet.reports if r["task_id"] == "bad"][0]
        self.assertEqual(bad["status"], "error")
        self.assertIn("unknown action", bad["message"])
        self.assertFalse(fake.calls_for("A", "shell", "id"))

    def test_offline_device_reported_as_other(self):
        fake = FakeAdb(devices=("A",))
        fake.state["A"] = "offline"
        res, sheet = self.run_local(fake, [{"task_id": "o", "action": "key", "params": {"name": "home"}}], retries=0)
        self.assertEqual(sheet.reports[0]["status"], "offline")
        self.assertEqual((res["failed"], res["other"]), (0, 1))

    def test_tasks_for_missing_device_are_skipped_and_reported(self):
        fake = FakeAdb(devices=("A",))
        res, sheet = self.run_local(fake, [{"task_id": "z", "device": "Z", "action": "key", "params": {"name": "home"}}])
        self.assertEqual(sheet.reports[0]["status"], "skipped")
        self.assertEqual(res["other"], 1)
        self.assertEqual(res["total"], 1)

    def test_max_tasks_caps_work(self):
        fake = FakeAdb(devices=("A", "B"))
        tasks = [{"task_id": f"t{i}", "action": "key", "params": {"name": "home"}} for i in range(10)]
        res, sheet = self.run_local(fake, tasks, max_tasks=4)
        self.assertEqual(res["success"], 4)

    def test_worker_survives_unexpected_exception(self):
        fake = FakeAdb(devices=("A",))
        tasks = [{"task_id": "x", "action": "key", "params": {"name": "home"}}, {"task_id": "y", "action": "key", "params": {"name": "back"}}]
        self.use_fake(fake)
        real = gl_bulk.ACTIONS["key"]["run"]
        calls = {"n": 0}

        def flaky(ctx, p):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("kaboom")
            return real(ctx, p)
        sheet = FakeSheet()
        with patch.dict(gl_bulk.ACTIONS["key"], {"run": flaky}):
            res = gl_bulk.run_bulk(tasks=tasks, client=sheet, log_dir=self.tmp.name, retries=0)
        statuses = {r["task_id"]: r["status"] for r in sheet.reports}
        self.assertEqual(statuses, {"x": "error", "y": "success"})
        self.assertEqual(res["total"], 2)

    def test_timeout_status(self):
        fake = FakeAdb(devices=("A",))
        res, sheet = self.run_local(fake, [{"task_id": "s", "action": "sleep", "params": {"seconds": 100}}], task_timeout=0.0, retries=2)
        self.assertEqual(sheet.reports[0]["status"], "timeout")
        self.assertEqual(sheet.reports[0]["attempts"], 1)  # timeouts are not retried
        self.assertEqual(res["failed"], 1)

    def test_no_devices(self):
        res, sheet = self.run_local(FakeAdb(devices=()), [{"action": "key", "params": {"name": "home"}}])
        self.assertEqual(res["status"], "error")
        self.assertTrue(any(l["level"] == "error" for l in sheet.logs))

    def test_dry_run_touches_nothing(self):
        fake = self.use_fake(FakeAdb())
        sheet = FakeSheet()
        res = gl_bulk.run_bulk(tasks=[{"action": "key", "params": {"name": "home"}}, {"action": "shell"}],
                               client=sheet, dry_run=True, log_dir=self.tmp.name)
        self.assertTrue(res["dry_run"])
        self.assertEqual((len(res["valid"]), len(res["invalid"])), (1, 1))
        self.assertEqual(fake.calls, [])
        self.assertEqual((sheet.reports, sheet.logs, sheet.summaries), ([], [], []))

    def test_dry_run_requires_task_file(self):
        self.use_fake(FakeAdb())
        res = gl_bulk.run_bulk(tasks=None, client=FakeSheet(), dry_run=True, log_dir=self.tmp.name)
        self.assertEqual(res["status"], "error")

    def test_no_task_source(self):
        self.use_fake(FakeAdb())
        self.assertEqual(gl_bulk.run_bulk(tasks=None, client=None, log_dir=self.tmp.name)["status"], "error")

    def test_local_log_always_written(self):
        fake = FakeAdb(devices=("A",))
        res, _ = self.run_local(fake, [{"task_id": "l", "action": "key", "params": {"name": "home"}}])
        kinds = [json.loads(line)["kind"] for line in open(res["log"], encoding="utf-8")]
        self.assertIn("task", kinds)
        self.assertIn("summary", kinds)

    def test_sheet_queue_claim_run_report(self):
        fake = self.use_fake(FakeAdb(devices=("A", "B")))
        rows = [{"task_id": "s1", "device": "", "action": "open-app", "params": '{"name":"youtube"}'},
                {"task_id": "s2", "device": "B", "action": "key", "params": '{"name":"home"}'},
                {"task_id": "s3", "device": "", "action": "teleport", "params": ""}]
        sheet = FakeSheet(rows)
        res = gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name)
        by_id = {r["task_id"]: r for r in sheet.reports}
        self.assertEqual(by_id["s1"]["status"], "success")
        self.assertEqual(by_id["s2"]["status"], "success")
        self.assertEqual(by_id["s3"]["status"], "error")
        self.assertEqual((res["total"], res["success"], res["failed"]), (3, 2, 1))
        self.assertEqual(sheet.queue, [])

    def test_sheet_claim_failure_stops_worker_and_is_logged(self):
        self.use_fake(FakeAdb(devices=("A",)))
        sheet = FakeSheet(claim_error=True)
        res = gl_bulk.run_bulk(client=sheet, log_dir=self.tmp.name)
        self.assertEqual(res["total"], 0)
        self.assertEqual(len([l for l in sheet.logs if "could not fetch tasks" in l["message"]]), 3)

    def test_failed_sheet_writes_are_spooled_then_flushed(self):
        fake = self.use_fake(FakeAdb(devices=("A",)))
        sheet = FakeSheet()
        sheet.reject_writes = True
        res = gl_bulk.run_bulk(tasks=[{"task_id": "p", "action": "key", "params": {"name": "home"}}], client=sheet, log_dir=self.tmp.name)
        self.assertGreater(res["sheet_write_failures"], 0)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, gl_sheets.SPOOL_NAME)))
        self.assertEqual(res["success"], 1)  # task still ran and is in the local log
        sheet.reject_writes = False
        flushed = gl_sheets.flush_spool(sheet, self.tmp.name)
        self.assertEqual(flushed["remaining"], 0)
        self.assertGreater(flushed["sent"], 0)
        self.assertEqual(sheet.reports[0]["task_id"], "p")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, gl_sheets.SPOOL_NAME)))


class _Resp:
    def __init__(self, text):
        self._t = text.encode()

    def read(self):
        return self._t

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestSheetsClient(unittest.TestCase):
    URL = "https://script.google.com/macros/s/ABC/exec"

    def setUp(self):
        p = patch("time.sleep")
        p.start()
        self.addCleanup(p.stop)

    def test_url_must_be_apps_script_https(self):
        for bad in ("http://script.google.com/x", "https://evil.com/exec", "https://script.google.com.evil.com/x", "", None):
            with self.assertRaises(gl_sheets.SheetsError):
                gl_sheets.SheetsClient(bad, "secret")
        gl_sheets.SheetsClient(self.URL, "secret")
        gl_sheets.SheetsClient("https://script.googleusercontent.com/macros/echo", "secret")

    def test_secret_required_and_from_env(self):
        with self.assertRaises(gl_sheets.SheetsError):
            gl_sheets.SheetsClient(self.URL, "")
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(gl_sheets.SheetsClient.from_env())
        with patch.dict(os.environ, {"GEELARK_SHEETS_URL": self.URL, "GEELARK_SHEETS_SECRET": "s3cret"}):
            self.assertIsNotNone(gl_sheets.SheetsClient.from_env())

    def test_call_sends_secret_in_body_not_url_and_parses(self):
        c = gl_sheets.SheetsClient(self.URL, "s3cret")
        with patch("urllib.request.urlopen", return_value=_Resp('{"ok": true, "tasks": [{"task_id": "1"}]}')) as uo:
            self.assertEqual(c.claim("A")[0]["task_id"], "1")
        req = uo.call_args[0][0]
        self.assertNotIn("s3cret", req.full_url)
        self.assertEqual(json.loads(req.data)["secret"], "s3cret")
        self.assertEqual(json.loads(req.data)["worker"], "A")

    def test_secret_not_in_repr_or_errors(self):
        c = gl_sheets.SheetsClient(self.URL, "s3cret")
        self.assertNotIn("s3cret", repr(c))
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            res = c.call("ping")
        self.assertNotIn("s3cret", json.dumps(res))

    def test_retries_then_gives_up_without_raising(self):
        c = gl_sheets.SheetsClient(self.URL, "s", retries=2)
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")) as uo:
            res = c.call("ping")
        self.assertFalse(res["ok"])
        self.assertEqual(uo.call_count, 3)

    def test_non_retryable_http_error_stops_immediately(self):
        c = gl_sheets.SheetsClient(self.URL, "s", retries=3)
        err = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(b""))
        self.addCleanup(err.close)
        with patch("urllib.request.urlopen", side_effect=err) as uo:
            self.assertFalse(c.call("ping")["ok"])
        self.assertEqual(uo.call_count, 1)

    def test_transient_401_is_retried(self):
        c = gl_sheets.SheetsClient(self.URL, "s", retries=2)
        err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b""))
        self.addCleanup(err.close)
        with patch("urllib.request.urlopen", side_effect=[err, _Resp('{"ok": true}')]) as uo:
            self.assertTrue(c.call("ping")["ok"])
        self.assertEqual(uo.call_count, 2)

    def test_non_json_and_error_responses(self):
        c = gl_sheets.SheetsClient(self.URL, "s")
        with patch("urllib.request.urlopen", return_value=_Resp("<html>login</html>")):
            self.assertEqual(c.call("ping")["error"], "non_json_response")
        with patch("urllib.request.urlopen", return_value=_Resp('{"ok": false, "error": "unauthorized"}')):
            with self.assertRaises(gl_sheets.SheetsError):
                c.claim("A")


class TestCliAndBackend(unittest.TestCase):
    def test_cli_exit_codes_and_dry_run(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            tf = os.path.join(d, "t.json")
            json.dump([{"action": "key", "params": {"name": "home"}}, {"action": "nope"}], open(tf, "w"))
            env = {k: v for k, v in os.environ.items() if not k.startswith("GEELARK_SHEETS")}
            out = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "geelark.py"), "bulk-run", "--tasks", tf, "--dry-run", "--log-dir", d],
                                 capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            data = json.loads(out.stdout)
            self.assertEqual((len(data["valid"]), len(data["invalid"])), (1, 1))
            out = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "geelark.py"), "bulk-run"],
                                 capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(out.returncode, 1)

    def test_bulk_commands_are_lock_free_and_not_on_bridge(self):
        import geelark
        import webhook_bridge
        for c in ("bulk-run", "bulk-check", "bulk-flush"):
            self.assertIn(c, geelark.LOCK_FREE_COMMANDS)
            self.assertNotIn(c, webhook_bridge.ALLOWED_COMMANDS)  # long-running + mutating: CLI only

    def test_apps_script_present_and_defines_protocol(self):
        src = open(os.path.join(ROOT, "sheets", "apps_script.gs"), encoding="utf-8").read()
        for token in ("function doPost", "LockService", "case 'claim'", "case 'report'", "case 'log'", "case 'summary'", "SECRET", "STALE_MINUTES"):
            self.assertIn(token, src)
        self.assertNotRegex(src, r"SECRET\s*=\s*['\"][^'\"]+['\"]")  # no hardcoded secret

    def test_apps_script_headers_match_python_payloads(self):
        src = open(os.path.join(ROOT, "sheets", "apps_script.gs"), encoding="utf-8").read()
        self.assertIn("body.task_action", src)
        for col in ("task_id", "device", "action", "params", "status", "attempts", "worker", "claimed_at", "finished_at", "result",
                    "run_id", "duration_s", "message", "output"):
            self.assertIn(f"'{col}'", src)


class TestBaseDeepLinkQuoting(unittest.TestCase):
    def test_existing_deep_link_quotes_url(self):
        import geelark
        with patch.object(gl_adb, "run_adb", return_value={"returncode": 0, "stdout": "", "stderr": ""}) as r:
            geelark.deep_link("https://y.com/w?v=1&t=3")
        self.assertEqual(r.call_args[0][0][-1], "'https://y.com/w?v=1&t=3'")


if __name__ == "__main__":
    unittest.main()
