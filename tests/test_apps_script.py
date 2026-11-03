#!/usr/bin/env python3
"""Runs the Apps Script unit tests (Node, mock spreadsheet) and checks the contract between the sheet and the runner:
the Library must produce tasks the runner accepts, and both sides must agree on actions and settings."""

import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import gl_bulk

NODE = shutil.which("node")


def node_json(*args):
    out = subprocess.run([NODE, *args], capture_output=True, text=True, timeout=60, cwd=ROOT)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "Node.js is not installed; skipping Apps Script tests")
class TestAppsScript(unittest.TestCase):
    def test_apps_script_unit_tests_pass(self):
        out = subprocess.run([NODE, "--test", os.path.join("tests", "apps_script.test.js")],
                             capture_output=True, text=True, timeout=120, cwd=ROOT)
        self.assertEqual(out.returncode, 0, out.stdout[-3000:] + out.stderr[-2000:])

    def test_allowed_actions_match_the_runner(self):
        js = node_json("-e", "const h=require('./tests/apps_script_harness.js');"
                             "console.log(JSON.stringify(h.load().ctx.ALLOWED_ACTIONS))")
        self.assertEqual(sorted(js), sorted(gl_bulk.ACTIONS))

    def test_every_library_task_is_accepted_by_the_runner(self):
        tasks = node_json("tests/apps_script_harness.js", "seed-tasks")
        self.assertGreaterEqual(len(tasks), 15)
        for t in tasks:
            self.assertNotIn("problem", t, t)
            norm = gl_bulk.normalize_task({"task_id": t["task_id"], "device": t["device"], "action": t["action"], "params": t["params"]})
            self.assertEqual(norm["device"], "cloud:abc123", t["name"])

    def test_watch_video_flow_has_the_expected_steps(self):
        tasks = node_json("tests/apps_script_harness.js", "seed-tasks")
        watch = next(t for t in tasks if t["name"] == "Watch YouTube video")
        steps = json.loads(watch["params"])["steps"]
        self.assertEqual([s["action"] for s in steps], ["open-app", "deep-link", "wait-text", "sleep"])
        self.assertEqual(steps[1]["url"], "https://www.youtube.com/watch?v=Bm84BAtOfQw&t=3")   # & survives intact
        self.assertTrue(steps[2]["optional"])
        self.assertEqual(steps[3]["seconds"], 30)

    def test_every_runner_setting_exists_in_the_sheet(self):
        keys = node_json("-e", "const h=require('./tests/apps_script_harness.js');"
                               "console.log(JSON.stringify(h.load().ctx.DEFAULT_SETTINGS.map(s=>s[0])))")
        wanted = {spec[0] for spec in gl_bulk._SHEET_SETTINGS.values()} | {"on_failure", "paused"}
        self.assertTrue(wanted <= set(keys), wanted - set(keys))

    def test_sheet_settings_defaults_are_valid_for_the_runner(self):
        defaults = node_json("-e", "const h=require('./tests/apps_script_harness.js');"
                                   "console.log(JSON.stringify(Object.fromEntries(h.load().ctx.DEFAULT_SETTINGS.map(s=>[s[0],s[1]]))))")
        cfg, ignored = gl_bulk.resolve_settings({}, defaults)
        self.assertEqual(ignored, [], "the sheet's own default settings must be accepted by the runner")
        self.assertEqual(cfg["on_failure"], "continue")


if __name__ == "__main__":
    unittest.main()
