#!/usr/bin/env python3
"""The `webhook` task: run a GeeLark custom automation through an n8n webhook and follow it to the end.
Fake webhook and fake GeeLark API; nothing is sent anywhere."""

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for d in (os.path.join(ROOT, "scripts"), os.path.dirname(os.path.abspath(__file__))):
    if d not in sys.path:
        sys.path.insert(0, d)

import gl_bulk
import gl_cloud

URL = "https://n8n.example.com/webhook/geelark-run"
TOKEN = "s3cret-webhook-token"


class Ctx:
    def __init__(self, phone_id="555", deadline_in=10000):
        self.phone_id = phone_id
        self.task_id = "t1"
        self.run_id = "r1"
        self.deadline = gl_bulk.time.monotonic() + deadline_in

    def wait(self, s):
        pass


def query_reply(status, **extra):
    return {"status": "success", "response": {"data": {"items": [dict({"id": "G1", "status": status}, **extra)]}}}


class Fakes:
    """Context manager: fake webhook + fake GeeLark API + a fake clock so polling never really sleeps."""

    def __init__(self, post=(200, '{"task_id": "G1"}'), statuses=(2, 3), **query_extra):
        self.post, self.statuses, self.query_extra = post, list(statuses), query_extra
        self.posts, self.queries, self.cancels = [], [], []
        self.clock = [1000.0]

    def post_json(self, url, payload, headers, timeout=30):
        self.posts.append((url, payload, headers))
        return self.post

    def api(self, endpoint, payload=None, **kw):
        if endpoint == "/open/v1/task/query":
            self.queries.append(payload)
            st = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return query_reply(st, **self.query_extra)
        if endpoint == "/open/v1/task/cancel":
            self.cancels.append(payload)
            return {"status": "success", "response": {"data": {}}}
        raise AssertionError(endpoint)

    def __enter__(self):
        env = {"GEELARK_N8N_WEBHOOK_URL": URL, "GEELARK_N8N_WEBHOOK_TOKEN": TOKEN}
        self.patches = [mock.patch.dict(os.environ, env), mock.patch.object(gl_bulk, "_post_json", self.post_json),
                        mock.patch.object(gl_cloud, "cloud_api_request", self.api),
                        mock.patch.object(gl_bulk.time, "monotonic", lambda: self.clock[0]),
                        mock.patch.object(gl_bulk.time, "sleep", lambda s: self.clock.__setitem__(0, self.clock[0] + s))]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.patches:
            p.stop()


class TestValidation(unittest.TestCase):
    def test_spec_parses_flow_and_json_params(self):
        self.assertEqual(gl_bulk._webhook_args({"spec": '562316 | {"Title": "hi"}'}), ("562316", {"Title": "hi"}))
        self.assertEqual(gl_bulk._webhook_args({"spec": "562316"}), ("562316", None))
        gl_bulk.validate_action("webhook", {"spec": "562316 | {\"a\": 1}", "max_wait_s": 900})

    def test_bad_input_is_rejected(self):
        for bad in ({}, {"spec": "bad flow id!"}, {"spec": "123 | not json"}, {"spec": "123 | [1,2]"},
                    {"spec": "123", "max_wait_s": 5}, {"spec": "123", "max_wait_s": 99999}, {"spec": "123", "track": "yes"}):
            with self.assertRaises(gl_bulk.TaskError, msg=str(bad)):
                gl_bulk.validate_action("webhook", bad)

    def test_the_task_gets_a_longer_time_limit_than_the_global_one(self):
        self.assertEqual(gl_bulk.ACTIONS["webhook"]["timeout"]({"max_wait_s": 900}), 960)


class TestRun(unittest.TestCase):
    def run_task(self, fakes, params=None, ctx=None):
        with fakes:
            return gl_bulk._r_webhook(ctx or Ctx(), params or {"spec": "562316 | {\"Title\": \"hi\"}"})

    def test_success_posts_the_phone_and_flow_then_follows_the_task_to_completion(self):
        f = Fakes(statuses=(1, 2, 2, 3), cost=95)
        res = self.run_task(f)
        self.assertEqual(res["status"], "success", res)
        url, payload, headers = f.posts[0]
        self.assertEqual(url, URL)
        self.assertEqual((payload["phone_id"], payload["flow"], payload["params"]), ("555", "562316", {"Title": "hi"}))
        self.assertEqual(payload["task_id"], "t1")
        self.assertEqual(headers, {"X-Webhook-Token": TOKEN})
        self.assertEqual(len(f.queries), 4)                        # waited through waiting / in progress
        self.assertEqual(res["output"]["geelark_task_id"], "G1")
        self.assertNotIn(TOKEN, str(res))
        self.assertNotIn("n8n.example.com", str(res))

    def test_a_failed_automation_fails_the_task_with_geelarks_reason(self):
        res = self.run_task(Fakes(statuses=(2, 4), failDesc="Device offline", failCode=20129))
        self.assertEqual(res["status"], "failed")
        self.assertIn("Device offline", res["message"])
        self.assertIn("20129", res["message"])

    def test_a_cancelled_automation_fails(self):
        self.assertEqual(self.run_task(Fakes(statuses=(7,)))["status"], "failed")

    def test_an_automation_that_never_finishes_is_cancelled_and_reported(self):
        f = Fakes(statuses=(2,))
        res = self.run_task(f, {"spec": "562316", "max_wait_s": 60, "poll_s": 10})
        self.assertEqual(res["status"], "failed")
        self.assertIn("did not finish", res["message"])
        self.assertEqual(f.cancels, [{"ids": ["G1"]}])             # never leave it running on a phone we are about to stop

    def test_the_global_task_limit_also_ends_the_wait(self):
        f = Fakes(statuses=(2,))
        res = self.run_task(f, {"spec": "562316", "max_wait_s": 3600}, Ctx(deadline_in=90))
        self.assertEqual(res["status"], "failed")
        self.assertEqual(len(f.cancels), 1)

    def test_no_task_id_in_the_answer_is_a_failure_with_a_hint(self):
        res = self.run_task(Fakes(post=(200, '{"ok": true}')))
        self.assertEqual(res["status"], "failed")
        self.assertIn("task id", res["message"])

    def test_task_id_may_come_back_in_other_shapes(self):
        for body in ('{"taskId": "G1"}', '{"data": {"taskId": "G1"}}', '{"task_id": 77}'):
            self.assertEqual(self.run_task(Fakes(post=(200, body), statuses=(3,)))["status"], "success", body)

    def test_untracked_mode_succeeds_without_polling(self):
        f = Fakes(post=(200, "{}"))
        res = self.run_task(f, {"spec": "562316", "track": False})
        self.assertEqual(res["status"], "success")
        self.assertEqual(f.queries, [])

    def test_webhook_errors_are_reported_without_leaking_the_url_or_token(self):
        for post in ((500, "boom " + TOKEN + " " + URL), (0, "connection refused " + URL), (200, '{"status": "failed", "message": "flow missing"}')):
            res = self.run_task(Fakes(post=post))
            self.assertEqual(res["status"], "failed", post)
            self.assertNotIn(TOKEN, res["message"])
            self.assertNotIn("n8n.example.com", res["message"])

    def test_unreadable_geelark_status_gives_up_after_a_few_tries(self):
        f = Fakes()
        f.api = lambda endpoint, payload=None, **kw: {"status": "error", "message": "HTTP 500"}
        with f:
            with mock.patch.object(gl_cloud, "cloud_api_request", f.api):
                res = gl_bulk._r_webhook(Ctx(), {"spec": "562316"})
        self.assertEqual(res["status"], "failed")
        self.assertIn("could not read GeeLark task", res["message"])

    def test_it_needs_a_cloud_phone(self):
        res = self.run_task(Fakes(), ctx=Ctx(phone_id=""))
        self.assertEqual(res["status"], "failed")
        self.assertIn("cloud phone", res["message"])


class TestUrlRules(unittest.TestCase):
    def check(self, url):
        with mock.patch.dict(os.environ, {"GEELARK_N8N_WEBHOOK_URL": url}):
            return gl_bulk._webhook_url()

    def test_unset_is_a_failure(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEELARK_N8N_WEBHOOK_URL", None)
            self.assertIn("not set", gl_bulk._webhook_url()[1])

    def test_only_https_or_local_http(self):
        self.assertTrue(self.check("https://n8n.example.com/webhook/x")[0])
        self.assertTrue(self.check("http://localhost:5678/webhook/x")[0])
        self.assertFalse(self.check("http://n8n.example.com/webhook/x")[0])
        self.assertFalse(self.check("ftp://n8n.example.com/x")[0])

    def test_credentials_in_the_url_are_refused(self):
        self.assertFalse(self.check("https://user:pass@n8n.example.com/x")[0])


class TestExecuteTask(unittest.TestCase):
    def test_execute_task_sets_the_phone_id_and_the_longer_limit(self):
        seen = {}

        def fake_run(ctx, params):
            seen["phone_id"] = ctx.phone_id
            seen["window"] = ctx.deadline - gl_bulk.time.monotonic()
            return gl_bulk.ok("done")

        class Reporter:
            def report(self, *a, **k):
                seen["reported"] = a

            def event(self, *a, **k):
                pass

        class Transport:
            kind, label = "api", "api-555"
            phone_id = "555"

            def state(self):
                return "device"

            def run(self, *a, **k):
                return {"returncode": 0, "stdout": "", "stderr": ""}

        task = {"task_id": "t", "device": "cloud:555", "action": "webhook", "params": {"spec": "123", "max_wait_s": 900}}
        with mock.patch.dict(gl_bulk.ACTIONS["webhook"], {"run": fake_run}):
            gl_bulk.execute_task(Transport(), task, "r", 0, 300, "/tmp", Reporter())
        self.assertEqual(seen["phone_id"], "555")
        self.assertGreater(seen["window"], 900)                    # not cut off at the global 300 s


if __name__ == "__main__":
    unittest.main()
