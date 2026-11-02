#!/usr/bin/env python3
"""Tests for the robustness layer: ADB helpers, process lock, cloud client, ADB input, version consistency."""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT_DIR = os.path.join(ROOT, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import geelark
import gl_base
import gl_cloud
import gl_input
import gl_win32
import gl_adb
import gl_lock
from _version import __version__


class TestAdbRunner(unittest.TestCase):
    def test_timeout_is_reported_not_raised(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("adb", 1)):
            res = gl_adb.run_adb(["devices"])
        self.assertEqual(res["returncode"], gl_adb.RC_TIMEOUT)
        self.assertTrue(res["timed_out"])

    def test_missing_adb_is_reported_not_raised(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("adb")):
            res = gl_adb.run_adb(["devices"])
        self.assertEqual(res["returncode"], gl_adb.RC_NOT_FOUND)

    def test_timeout_is_always_passed_to_subprocess(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
            gl_adb.run_adb(["devices"])
        self.assertIn("timeout", run.call_args.kwargs)

    def test_serial_is_validated(self):
        res = gl_adb.run_adb(["shell", "id"], device="x; rm -rf /")
        self.assertEqual(res["returncode"], 2)

    def test_devices_command_never_gets_dash_s(self):
        with patch.dict(os.environ, {"GEELARK_ADB_DEVICE": "abc"}):
            with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
                gl_adb.run_adb(["devices"])
        self.assertNotIn("-s", run.call_args[0][0])

    def test_env_device_is_applied_to_other_commands(self):
        with patch.dict(os.environ, {"GEELARK_ADB_DEVICE": "abc"}):
            with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")) as run:
                gl_adb.run_adb(["shell", "id"])
        self.assertEqual(run.call_args[0][0][-4:-2], ["-s", "abc"])

    def test_resolve_device_unique_vs_ambiguous(self):
        gl_adb._device_cache.update(at=0.0, devices=[])
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEELARK_ADB_DEVICE", None)
            with patch.object(gl_adb, "run_adb", return_value={"returncode": 0, "stdout": "List of devices attached\nA\tdevice\n"}):
                self.assertEqual(gl_adb.resolve_device(), "A")
            gl_adb._device_cache.update(at=0.0, devices=[])
            two = "List of devices attached\nA\tdevice\nB\tdevice\n"
            with patch.object(gl_adb, "run_adb", return_value={"returncode": 0, "stdout": two}):
                self.assertIsNone(gl_adb.resolve_device())
        self.assertEqual(gl_adb.resolve_device("explicit"), "explicit")
        gl_adb._device_cache.update(at=0.0, devices=[])

    def test_screen_size_prefers_override(self):
        out = "Physical size: 1080x2400\nOverride size: 720x1600"
        with patch.object(gl_adb, "run_adb", return_value={"returncode": 0, "stdout": out}):
            self.assertEqual(gl_adb.screen_size("A"), (720, 1600))

    def test_keyevent_maps_codes(self):
        with patch.object(gl_adb, "run_adb", return_value={"returncode": 0, "stdout": "", "stderr": ""}) as run:
            self.assertTrue(gl_adb.keyevent("A", "home"))
            run.assert_called_with(["shell", "input", "keyevent", "KEYCODE_HOME"], device="A")
        self.assertIsNone(gl_adb.keyevent("A", "bogus"))
        self.assertIsNone(gl_adb.keyevent(None, "home"))


class TestAdbInputIntegration(unittest.TestCase):
    def test_send_key_prefers_adb_keyevent(self):
        with patch.object(gl_adb, "resolve_device", return_value="A"), \
             patch.object(gl_adb, "keyevent", return_value={"returncode": 0}) as ke, \
             patch.object(gl_input, "tap") as tap:
            res = geelark.send_key("back")
        self.assertEqual(res["via"], "adb")
        ke.assert_called_once_with("A", "back")
        tap.assert_not_called()

    def test_send_key_falls_back_to_tap(self):
        with patch.object(gl_adb, "resolve_device", return_value=None), \
             patch.object(gl_adb, "keyevent", return_value=None), \
             patch.object(gl_input, "tap", return_value={"status": "success"}) as tap:
            geelark.send_key("home", target=3)
        tap.assert_called_once_with(0.50, 0.97, target=3, normalized=True)

    def test_adb_keys_can_be_disabled(self):
        with patch.dict(os.environ, {"GEELARK_ADB_KEYS": "0"}), \
             patch.object(gl_adb, "keyevent") as ke, \
             patch.object(gl_input, "tap", return_value={"status": "success"}):
            geelark.send_key("back")
        ke.assert_not_called()

    def test_tap_gui_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEELARK_INPUT_MODE", None)
            self.assertIsNone(geelark._adb_input_device())

    def test_tap_uses_adb_in_adb_mode(self):
        with patch.dict(os.environ, {"GEELARK_INPUT_MODE": "adb"}), \
             patch.object(gl_adb, "resolve_device", return_value="A"), \
             patch.object(gl_adb, "tap_normalized", return_value={"coords": [10, 20]}):
            res = geelark.tap(0.1, 0.2, normalized=True)
        self.assertEqual(res["via"], "adb")
        self.assertEqual(res["coords"], [10, 20])

    def test_swipe_uses_adb_in_adb_mode(self):
        with patch.dict(os.environ, {"GEELARK_INPUT_MODE": "adb"}), \
             patch.object(gl_adb, "resolve_device", return_value="A"), \
             patch.object(gl_adb, "swipe_normalized", return_value={"from": [1, 2], "to": [3, 4]}):
            res = geelark.swipe(0.5, 0.8, 0.5, 0.2, normalized=True)
        self.assertEqual(res["via"], "adb")

    def test_session_roundtrip_with_device_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "session.json")
            with patch.object(gl_base, "SESSION_CACHE_PATH", path):
                geelark.set_active_target("4", adb_device="emulator-5554")
                self.assertEqual(geelark.get_active_target(), "4")
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("GEELARK_ADB_DEVICE", None)
                    self.assertEqual(geelark.get_active_adb_device(), "emulator-5554")
                geelark.set_active_target("7")  # keeps the stored device
                self.assertEqual(geelark.get_active_target(), "7")
                self.assertEqual([f for f in os.listdir(d) if f.endswith(".tmp")], [])


class TestProfileMatching(unittest.TestCase):
    """Regression: target '4' used to match the app window 'GeeLark 4.5.3' and click it."""

    def test_numeric_target_never_matches_app_window_version(self):
        wins = [{"hwnd": 9, "title": "GeeLark 4.5.3", "is_phone": False, "rect": {}}]
        with patch.object(gl_win32, "list_windows", return_value=wins):
            self.assertIsNone(geelark.find_target_window("4"))

    def test_numeric_target_is_whole_number_on_phone_windows(self):
        wins = [
            {"hwnd": 9, "title": "GeeLark 4.5.3", "is_phone": False},
            {"hwnd": 14, "title": "Phone 14", "is_phone": True},
            {"hwnd": 4, "title": "Phone 4 cloud", "is_phone": True},
        ]
        with patch.object(gl_win32, "list_windows", return_value=wins):
            self.assertEqual(geelark.find_target_window("4")["hwnd"], 4)
            self.assertIsNone(geelark.find_target_window("1"))

    def test_text_target_still_substring_matches(self):
        wins = [{"hwnd": 9, "title": "GeeLark 4.5.3", "is_phone": False}]
        with patch.object(gl_win32, "list_windows", return_value=wins):
            self.assertEqual(geelark.find_target_window("GeeLark")["hwnd"], 9)


class TestDeviceLock(unittest.TestCase):
    def test_lock_serializes_and_times_out(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "l.lock")
            a = gl_lock.DeviceLock(path, timeout=1).acquire()
            try:
                b = gl_lock.DeviceLock(path, timeout=0.3)
                t0 = time.monotonic()
                with self.assertRaises(gl_lock.LockTimeout):
                    b.acquire()
                self.assertGreaterEqual(time.monotonic() - t0, 0.25)
            finally:
                a.release()
            with gl_lock.DeviceLock(path, timeout=0.5):
                pass  # free again after release

    def test_lock_released_on_exception(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "l.lock")
            with self.assertRaises(ValueError):
                with gl_lock.DeviceLock(path, timeout=0.5):
                    raise ValueError("boom")
            with gl_lock.DeviceLock(path, timeout=0.5):
                pass

    def test_cross_process_exclusion(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "l.lock")
            code = (
                "import sys; sys.path.insert(0, sys.argv[1]); import gl_lock, time;"
                "l = gl_lock.DeviceLock(sys.argv[2], timeout=0.3);"
                "\ntry:\n l.acquire(); print('GOT')\nexcept gl_lock.LockTimeout:\n print('BUSY')"
            )
            with gl_lock.DeviceLock(path, timeout=1):
                out = subprocess.run([sys.executable, "-c", code, SCRIPT_DIR, path], capture_output=True, text=True, timeout=20)
            self.assertEqual(out.stdout.strip(), "BUSY")

    def test_cli_returns_busy_exit_code_when_locked(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "l.lock")
            env = dict(os.environ, GEELARK_LOCK_PATH=path, GEELARK_LOCK_TIMEOUT="0.3")
            with gl_lock.DeviceLock(path, timeout=1):
                out = subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "geelark.py"), "recover"],
                                     capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(out.returncode, 3)
            self.assertIn("busy", out.stderr)

    def test_read_only_commands_skip_lock(self):
        for cmd in ("features", "status", "list-windows", "use", "export-schema", "cloud-list"):
            self.assertIn(cmd, geelark.LOCK_FREE_COMMANDS)
        for cmd in ("tap", "capture", "find-text", "recover", "batch-run"):
            self.assertNotIn(cmd, geelark.LOCK_FREE_COMMANDS)


class _Resp:
    def __init__(self, body):
        self._b = body.encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestCloudClient(unittest.TestCase):
    def setUp(self):
        patcher = patch("time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rejects_bad_endpoint(self):
        res = geelark.cloud_api_request("/etc/passwd", api_token="t")
        self.assertEqual(res["code"], "invalid_endpoint")
        res = geelark.cloud_api_request("/open/../x@evil.com", api_token="t")
        self.assertEqual(res["code"], "invalid_endpoint")

    def test_success_and_no_token_leak(self):
        with patch("urllib.request.urlopen", return_value=_Resp('{"code":0,"data":{"ok":1}}')):
            res = geelark.cloud_api_request("/open/v1/phone/list", {}, api_token="SECRET-TOKEN")
        self.assertEqual(res["status"], "success")
        self.assertNotIn("SECRET-TOKEN", json.dumps(res))

    def test_api_level_error_surfaces(self):
        with patch("urllib.request.urlopen", return_value=_Resp('{"code":40001,"msg":"bad id"}')):
            res = geelark.cloud_api_request("/open/v1/phone/start", {}, api_token="t")
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["code"], "api_error")
        self.assertEqual(res["message"], "bad id")

    def test_retries_transient_then_succeeds(self):
        err = urllib.error.HTTPError("u", 503, "Unavailable", {}, io.BytesIO(b""))
        self.addCleanup(err.close)
        with patch("urllib.request.urlopen", side_effect=[err, _Resp('{"code":0}')]) as uo:
            res = geelark.cloud_api_request("/open/v1/phone/list", {}, api_token="t")
        self.assertEqual(res["status"], "success")
        self.assertEqual(uo.call_count, 2)

    def test_does_not_retry_client_errors(self):
        err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b""))
        self.addCleanup(err.close)
        with patch("urllib.request.urlopen", side_effect=err) as uo:
            res = geelark.cloud_api_request("/open/v1/phone/list", {}, api_token="t")
        self.assertEqual(res["status"], "error")
        self.assertEqual(uo.call_count, 1)

    def test_gives_up_after_retries(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")) as uo:
            res = geelark.cloud_api_request("/open/v1/phone/list", {}, api_token="t", retries=2)
        self.assertEqual(res["code"], "request_failed")
        self.assertEqual(uo.call_count, 3)

    def test_invalid_json_response(self):
        with patch("urllib.request.urlopen", return_value=_Resp("<html>")):
            res = geelark.cloud_api_request("/open/v1/phone/list", {}, api_token="t")
        self.assertEqual(res["code"], "invalid_json")

    def test_ensure_device_does_not_guess_cloud_id(self):
        with patch.object(gl_win32, "find_target_window", return_value=None), \
             patch.object(gl_win32, "list_windows", return_value=[]), \
             patch.object(gl_cloud, "cloud_api_request") as api, \
             patch.object(geelark.os.path, "exists", return_value=False), \
             patch.dict(os.environ, {"GEELARK_API_TOKEN": "t"}, clear=True):
            res = geelark.ensure_device_ready("4")
        api.assert_not_called()
        self.assertEqual(res["status"], "error")


class TestVersionAndPackaging(unittest.TestCase):
    def _read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return f.read()

    def test_versions_in_sync(self):
        self.assertEqual(json.loads(self._read("skill.json"))["version"], __version__)
        m = re.search(r'^\s*version:\s*"([^"]+)"', self._read("SKILL.md"), re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), __version__)

    def test_skill_frontmatter_is_minimal(self):
        text = self._read("SKILL.md")
        front = text.split("---")[1]
        self.assertIn("name: geelark-cloud-phone", front)
        self.assertIn("description:", front)
        self.assertLess(len(front.splitlines()), 25, "frontmatter should not carry tag lists")
        self.assertLess(len(text.splitlines()), 200, "SKILL.md should stay lean; move detail to references/")

    def test_no_evasion_marketing_language(self):
        banned = re.compile(r"undetectable|antidetect|anti-bot|bot-detection|bypass bot|anti-ban", re.I)
        for name in ("SKILL.md", "README.md", "skill.json", os.path.join("references", "features_and_architecture.md")):
            self.assertIsNone(banned.search(self._read(name)), name)

    def test_no_hardcoded_user_paths(self):
        for name in ("scripts/mcp_stdio.py", "examples/README.md", "INSTALL.md", "SKILL.md"):
            self.assertNotIn("Users\\Backspace", self._read(name).replace("/", "\\"), name)

    def test_bridge_binds_loopback_by_default(self):
        import webhook_bridge
        self.assertEqual(webhook_bridge.DEFAULT_HOST, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
