import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import gl_bulk  # noqa: E402
import gl_cloudadb  # noqa: E402
import gl_transport  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class FakeApi:
    """Stands in for gl_cloud.cloud_api_request."""

    def __init__(self):
        self.calls = []
        self.running = False
        self.shell = {}

    def __call__(self, endpoint, payload=None, api_token=None, retries=2, timeout=15):
        self.calls.append((endpoint, payload))
        ok = lambda data: {"status": "success", "response": {"code": 0, "data": data}}
        if endpoint == "/open/v1/phone/start":
            self.running = True
            return ok({"successDetails": [{"id": payload["ids"][0]}], "failDetails": []})
        if endpoint == "/open/v1/phone/stop":
            self.running = False
            return ok({"successDetails": [{"id": payload["ids"][0]}], "failDetails": []})
        if endpoint == "/open/v1/phone/status":
            return ok({"successDetails": [{"id": payload["ids"][0], "status": 0 if self.running else 2}], "failDetails": []})
        if endpoint == "/open/v1/shell/execute":
            cmd = payload["cmd"]
            for key, out in self.shell.items():
                if key in cmd:
                    return ok({"status": True, "output": out})
            return ok({"status": True, "output": ""})
        return {"status": "error", "message": "unexpected " + endpoint}


class TestApiTransport(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        p = mock.patch("gl_cloud.cloud_api_request", self.api)
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tempfile.mkdtemp()

    def test_shell_maps_to_command(self):
        self.api.shell["echo hi"] = "hi\n"
        t = gl_transport.ApiTransport("123")
        res = t.run(["shell", "echo", "hi"])
        self.assertEqual((res["returncode"], res["stdout"]), (0, "hi"))
        self.assertEqual(self.api.calls[-1], ("/open/v1/shell/execute", {"id": "123", "cmd": "echo hi"}))

    def test_uiautomator_dump_uses_a_file(self):
        t = gl_transport.ApiTransport("123")
        t.run(["exec-out", "uiautomator", "dump", "/dev/tty"])
        self.assertIn("uiautomator dump " + gl_transport.UI_DUMP_PATH, self.api.calls[-1][1]["cmd"])

    def test_unsupported_command_is_an_error_not_a_call(self):
        res = gl_transport.ApiTransport("123").run(["push", "a", "b"])
        self.assertEqual(res["returncode"], 2)
        self.assertEqual(self.api.calls, [])

    def test_state(self):
        t = gl_transport.ApiTransport("123")
        self.assertEqual(t.state(), "shut down")
        self.api.running = True
        self.assertEqual(t.state(), "device")

    def test_up_down_and_registry(self):
        self.api.shell["boot_completed"] = "1"
        with mock.patch("time.sleep"):
            t = gl_transport.cloud_up("123", self.tmp, timeout=30)
        self.assertEqual(t.kind, "api")
        self.assertIn("123", gl_cloudadb.leftover_phones(self.tmp))
        gl_transport.cloud_down("123", self.tmp)
        self.assertFalse(self.api.running)
        self.assertEqual(list(gl_cloudadb.leftover_phones(self.tmp)), [])

    def test_stop_leftovers_uses_api(self):
        self.api.running = True
        gl_cloudadb._registry_update(self.tmp, lambda d: d.__setitem__("123", {"since": 1}))
        with mock.patch("time.sleep"):
            gl_transport.stop_leftovers(self.tmp)
        self.assertFalse(self.api.running)

    def test_task_runs_over_the_api(self):
        self.api.running = True
        self.api.shell["wm size"] = "Physical size: 1080x2400"
        t = gl_transport.ApiTransport("123")
        ctx = gl_bulk.Ctx(t, "t1", "r1", __import__("time").monotonic() + 60, self.tmp)
        hit = ctx.tap_normalized(0.5, 0.5)
        self.assertEqual(hit["coords"], [540, 1200])
        self.assertEqual(self.api.calls[-1][1]["cmd"], "input tap 540 1200")
        self.assertEqual(ctx.state(), "device")

    def test_screenshot_accepts_png(self):
        class T(gl_transport.ApiTransport):
            def screenshot(self, timeout=90):
                return {"returncode": 0, "stdout": PNG, "stderr": ""}
        ctx = gl_bulk.Ctx(T("123"), "t1", "r1", __import__("time").monotonic() + 60, self.tmp)
        res = gl_bulk._r_screenshot(ctx, {})
        self.assertEqual(res["status"], "success")
        self.assertTrue(os.path.exists(res["output"]["path"]))


    def test_second_screenshot_in_one_task_does_not_overwrite_the_first(self):
        class T(gl_transport.ApiTransport):
            def screenshot(self, timeout=90):
                return {"returncode": 0, "stdout": PNG, "stderr": ""}
        ctx = gl_bulk.Ctx(T("123"), "t1", "r1", __import__("time").monotonic() + 60, self.tmp)
        first = gl_bulk._r_screenshot(ctx, {})["output"]["path"]
        second = gl_bulk._r_screenshot(ctx, {})["output"]["path"]
        self.assertNotEqual(first, second)
        self.assertTrue(os.path.exists(first) and os.path.exists(second))


if __name__ == "__main__":
    unittest.main()
