#!/usr/bin/env python3
"""Tests for the account-safety features: per-phone daily like/comment limits, the no-duplicate-comment rule, random
wait/tap variation and the Settings-tab plumbing. Fake ADB and fake sheet; no phone or network is touched."""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import gl_bulk
from test_bulk import PatchedCase, FakeAdb, FakeSheet


def like(i, dev="A"):
    return {"task_id": f"like{i}", "device": dev, "action": "tap", "params": {"x": 0.5, "y": 0.5, "engage": "like"}}


def comment(i, text, dev="A"):
    return [
        {"task_id": f"c{i}-open", "device": dev, "action": "tap", "params": {"x": 0.5, "y": 0.5, "engage": "comment_open"}},
        {"task_id": f"c{i}-type", "device": dev, "action": "type", "params": {"text": text, "engage": "comment_type"}},
        {"task_id": f"c{i}-send", "device": dev, "action": "tap", "params": {"x": 0.9, "y": 0.4, "engage": "comment_send"}},
    ]


class TestGuardUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_like_limit_per_phone(self):
        g = gl_bulk.EngagementGuard(self.tmp.name, max_likes=2)
        for _ in range(2):
            self.assertIsNone(g.check("P1", "like"))
            g.record("P1", "like")
        self.assertIn("like limit", g.check("P1", "like"))
        self.assertIsNone(g.check("P2", "like"))                     # another phone has its own allowance

    def test_comment_limit_blocks_the_whole_comment(self):
        g = gl_bulk.EngagementGuard(self.tmp.name, max_comments=1)
        self.assertIsNone(g.check("P1", "comment_open"))
        self.assertIsNone(g.check("P1", "comment_type", "first comment here"))
        self.assertIsNone(g.check("P1", "comment_send"))
        g.record("P1", "comment_send")
        why = g.check("P1", "comment_open")
        self.assertIn("comment limit", why)
        self.assertEqual(g.check("P1", "comment_type", "another one"), why)   # typing and sending are blocked too
        self.assertEqual(g.check("P1", "comment_send"), why)

    def test_identical_comment_blocked_across_phones_and_case_punctuation(self):
        g = gl_bulk.EngagementGuard(self.tmp.name)
        g.check("P1", "comment_open")
        self.assertIsNone(g.check("P1", "comment_type", "Great video! Which part was hardest?"))
        g.check("P2", "comment_open")
        why = g.check("P2", "comment_type", "great video  which part was hardest")
        self.assertIn("already used", why)
        self.assertEqual(g.check("P2", "comment_send"), why)         # nothing is sent

    def test_counts_survive_a_restart_but_reset_next_day(self):
        g = gl_bulk.EngagementGuard(self.tmp.name, max_likes=1, today="2026-11-23")
        g.record("P1", "like")
        again = gl_bulk.EngagementGuard(self.tmp.name, max_likes=1, today="2026-11-23")
        self.assertIsNotNone(again.check("P1", "like"))
        tomorrow = gl_bulk.EngagementGuard(self.tmp.name, max_likes=1, today="2026-11-24")
        self.assertIsNone(tomorrow.check("P1", "like"))

    def test_zero_means_none_allowed_and_none_means_unlimited(self):
        self.assertIsNotNone(gl_bulk.EngagementGuard(self.tmp.name, max_likes=0).check("P1", "like"))
        g = gl_bulk.EngagementGuard(self.tmp.name)
        for _ in range(50):
            g.record("P1", "like")
        self.assertIsNone(g.check("P1", "like"))


class TestSettings(unittest.TestCase):
    def test_sheet_values_are_parsed(self):
        cfg, ignored = gl_bulk.resolve_settings({}, {"max_likes_per_day": "8", "max_comments_per_day": "3",
                                                     "wait_jitter_pct": "30", "tap_jitter_pct": "1",
                                                     "phone_start_stagger_s": "600"})
        self.assertEqual(ignored, [])
        self.assertEqual((cfg["max_likes_per_day"], cfg["max_comments_per_day"]), (8, 3))
        self.assertAlmostEqual(cfg["wait_jitter"], 0.30)
        self.assertAlmostEqual(cfg["tap_jitter"], 0.01)
        self.assertEqual(cfg["start_stagger"], 600.0)

    def test_blank_means_off_and_bad_values_are_ignored(self):
        cfg, ignored = gl_bulk.resolve_settings({}, {"max_likes_per_day": "", "wait_jitter_pct": "500", "tap_jitter_pct": "x"})
        self.assertIsNone(cfg["max_likes_per_day"])
        self.assertEqual(cfg["wait_jitter"], 0.0)
        self.assertEqual(len(ignored), 2)


class TestJitter(unittest.TestCase):
    def test_sleep_varies_within_bounds(self):
        waits = []
        with patch.object(gl_bulk.Ctx, "wait", lambda self, s: waits.append(s), create=True):
            gl_bulk._WAIT_JITTER = 0.3
            try:
                for _ in range(40):
                    gl_bulk._r_sleep(gl_bulk.Ctx.__new__(gl_bulk.Ctx), {"seconds": 10})
            finally:
                gl_bulk._WAIT_JITTER = 0.0
        self.assertTrue(all(7.0 <= w <= 13.0 for w in waits))
        self.assertGreater(len(set(round(w, 2) for w in waits)), 10)

    def test_jitter_is_off_by_default(self):
        waits = []
        with patch.object(gl_bulk.Ctx, "wait", lambda self, s: waits.append(s), create=True):
            res = gl_bulk._r_sleep(gl_bulk.Ctx.__new__(gl_bulk.Ctx), {"seconds": 10})
        self.assertEqual(waits, [10.0])
        self.assertEqual(res["message"], "slept 10s")


class TestRunnerLimits(PatchedCase):
    def run_local(self, tasks, **kw):
        if not getattr(self, "_faked", False):        # use_fake makes a new temp dir each call; reuse one so runs share state
            self.use_fake(FakeAdb(devices=("A", "B")))
            self._faked = True
        sheet = FakeSheet()
        res = gl_bulk.run_bulk(tasks=tasks, client=sheet, log_dir=self.tmp.name, retries=0, **kw)
        return res, {r["task_id"]: r for r in sheet.reports}

    def test_third_like_is_skipped_when_limit_is_two(self):
        res, rep = self.run_local([like(i) for i in range(3)], max_likes_per_day=2)
        self.assertEqual([rep[f"like{i}"]["status"] for i in range(3)], ["success", "success", "skipped"])
        self.assertIn("account safety", rep["like2"]["message"])

    def test_second_comment_is_skipped_entirely_at_limit_one(self):
        tasks = comment(1, "Nice walkthrough, what tool did you use for the dashboard?") + \
                comment(2, "Really clear explanation, how long did the setup take you?")
        res, rep = self.run_local(tasks, max_comments_per_day=1)
        self.assertEqual([rep[f"c1-{k}"]["status"] for k in ("open", "type", "send")], ["success"] * 3)
        self.assertEqual([rep[f"c2-{k}"]["status"] for k in ("open", "type", "send")], ["skipped"] * 3)

    def test_same_comment_on_two_phones_posts_once(self):
        text = "Helpful breakdown, which step took you longest to get right?"
        tasks = comment(1, text, "A") + comment(2, text, "B")
        res, rep = self.run_local(tasks)
        sent = [rep[f"c{i}-send"]["status"] for i in (1, 2)]
        self.assertEqual(sorted(sent), ["skipped", "success"])

    def test_tasks_without_marker_are_never_limited(self):
        tasks = [{"task_id": f"t{i}", "device": "A", "action": "tap", "params": {"x": 0.5, "y": 0.5}} for i in range(5)]
        res, rep = self.run_local(tasks, max_likes_per_day=0, max_comments_per_day=0)
        self.assertTrue(all(r["status"] == "success" for r in rep.values()))

    def test_limits_carry_over_between_runs_on_the_same_day(self):
        self.run_local([like(0)], max_likes_per_day=1)
        res, rep = self.run_local([like(1)], max_likes_per_day=1)
        self.assertEqual(rep["like1"]["status"], "skipped")


LINK = "https://youtu.be/u1Yjxw2Wg4Y"


def recipe_task(i, recipe, spec, dev="A"):
    return {"task_id": f"r{i}", "device": dev, "action": "flow", "params": {"recipe": recipe, "spec": spec}}


class TestRecipes(unittest.TestCase):
    def kinds(self, steps):
        return [s.get("engage") for s in steps if s.get("engage")]

    def test_like_recipe_has_only_the_like(self):
        steps = gl_bulk.recipe_steps({"recipe": "like", "spec": LINK})
        self.assertEqual(self.kinds(steps), ["like"])
        self.assertEqual(steps[0]["url"], "https://www.youtube.com/watch?v=u1Yjxw2Wg4Y")
        self.assertEqual(steps[-1], {"action": "force-stop", "name": "youtube"})

    def test_comment_recipe_has_no_like(self):
        steps = gl_bulk.recipe_steps({"recipe": "comment", "spec": LINK + " | Nice walkthrough, what tool did you use?"})
        self.assertEqual(self.kinds(steps), ["comment_open", "comment_type", "comment_send"])
        self.assertEqual([s["text"] for s in steps if s["action"] == "type"], ["Nice walkthrough, what tool did you use?"])

    def test_like_comment_recipe_has_both_and_two_proof_screenshots(self):
        steps = gl_bulk.recipe_steps({"recipe": "like_comment", "spec": LINK + " | Great breakdown overall"})
        self.assertEqual(self.kinds(steps), ["like", "comment_open", "comment_type", "comment_send"])
        self.assertEqual(sum(1 for s in steps if s["action"] == "screenshot"), 2)
        self.assertLessEqual(len(steps), gl_bulk.MAX_STEPS)

    def test_no_recipe_ever_taps_the_subscribe_button_row(self):
        # y 0.43-0.46 is the Subscribe / bell / Like row on a watch page; only the Like button's own x is allowed there.
        for recipe in gl_bulk.RECIPES:
            for s in gl_bulk.recipe_steps({"recipe": recipe, "spec": LINK + " | Helpful comparison, thank you"}):
                if s["action"] == "tap" and 0.42 <= s["y"] <= 0.47:
                    self.assertEqual((s["x"], s["y"]), gl_bulk._TAP_LIKE)

    def test_link_formats_are_accepted(self):
        for link in ("https://www.youtube.com/watch?v=u1Yjxw2Wg4Y&t=5", "https://youtu.be/u1Yjxw2Wg4Y?si=x",
                     "https://www.youtube.com/shorts/u1Yjxw2Wg4Y"):
            self.assertIn("u1Yjxw2Wg4Y", gl_bulk.recipe_steps({"recipe": "like", "spec": link})[0]["url"])

    def test_bad_input_is_rejected_when_the_task_is_validated(self):
        bad = [("like", "not a link"), ("comment", LINK), ("comment", LINK + " | "), ("comment", LINK + " | ab"),
               ("comment", LINK + " | café is great"), ("comment", LINK + " | " + "x" * 400), ("share", LINK)]
        for recipe, spec in bad:
            with self.assertRaises(gl_bulk.TaskError, msg=f"{recipe} {spec[:30]}"):
                gl_bulk.normalize_task(recipe_task(0, recipe, spec))

    def test_valid_recipe_task_passes_normalisation(self):
        t = gl_bulk.normalize_task(recipe_task(0, "like_comment", LINK + " | Really clear explanation, thanks"))
        self.assertEqual(t["action"], "flow")


class TestRecipeRunner(PatchedCase):
    def run_local(self, tasks, **kw):
        if not getattr(self, "_faked", False):
            self.use_fake(FakeAdb(devices=("A", "B")))
            p = patch.object(gl_bulk.Ctx, "wait", lambda self, s: None, create=True)   # recipes contain real waits
            p.start()
            self.addCleanup(p.stop)
            self._faked = True
        sheet = FakeSheet()
        res = gl_bulk.run_bulk(tasks=tasks, client=sheet, log_dir=self.tmp.name, retries=1, **kw)
        return res, {r["task_id"]: r for r in sheet.reports}

    def test_like_comment_flow_succeeds_and_counts(self):
        res, rep = self.run_local([recipe_task(1, "like_comment", LINK + " | Great breakdown, thanks for sharing")])
        self.assertEqual(rep["r1"]["status"], "success")
        g = gl_bulk.EngagementGuard(self.tmp.name)
        self.assertEqual(g.counts("A"), (1, 1))

    def test_limits_apply_inside_a_flow_and_skip_the_newest_tap(self):
        tasks = [recipe_task(1, "like_comment", LINK + " | First comment about the setup steps"),
                 recipe_task(2, "like_comment", LINK + " | Second comment about the results")]
        taps = []
        real = gl_bulk.ACTIONS["tap"]["run"]

        def record(ctx, p):
            taps.append((ctx.task_id, round(p["x"], 3), round(p["y"], 3)))
            return real(ctx, p)
        with patch.dict(gl_bulk.ACTIONS["tap"], {"run": record}):
            res, rep = self.run_local(tasks, max_likes_per_day=1, max_comments_per_day=1)
        self.assertEqual(rep["r1"]["status"], "success")
        self.assertEqual(rep["r2"]["status"], "skipped")             # both parts at their limit: nothing posted
        send = (round(gl_bulk._TAP_SEND[0], 3), round(gl_bulk._TAP_SEND[1], 3))
        self.assertIn(("r1",) + send, taps)                          # the first flow really sent...
        self.assertNotIn(("r2",) + send, taps)                       # ...the second tapped nothing it was blocked from
        for kind_pos in (gl_bulk._TAP_LIKE, gl_bulk._TAP_COMMENT_BOX, gl_bulk._TAP_SEND):
            self.assertNotIn(("r2", round(kind_pos[0], 3), round(kind_pos[1], 3)), taps)

    def test_like_limit_reached_still_allows_the_comment(self):
        self.run_local([recipe_task(1, "like", LINK)], max_likes_per_day=1)
        res, rep = self.run_local([recipe_task(2, "like_comment", LINK + " | Helpful walkthrough, thank you")], max_likes_per_day=1)
        self.assertEqual(rep["r2"]["status"], "success")
        g = gl_bulk.EngagementGuard(self.tmp.name)
        self.assertEqual(g.counts("A"), (1, 1))                      # no second like, one comment

    def test_duplicate_comment_across_phones_inside_flows(self):
        text = LINK + " | Useful comparison, which one would you pick"
        res, rep = self.run_local([recipe_task(1, "comment", text, "A"), recipe_task(2, "comment", text, "B")])
        self.assertEqual(sorted(rep[k]["status"] for k in ("r1", "r2")), ["skipped", "success"])

    def test_a_failed_recipe_flow_is_never_retried(self):
        calls = {"n": 0}
        real = gl_bulk.ACTIONS["tap"]["run"]

        def boom(ctx, p):
            calls["n"] += 1
            return gl_bulk.fail("tap failed")
        with patch.dict(gl_bulk.ACTIONS["tap"], {"run": boom}):
            res, rep = self.run_local([recipe_task(1, "like", LINK)])
        self.assertEqual(rep["r1"]["status"], "failed")
        self.assertEqual(calls["n"], 1)                              # one attempt only, despite retries=1


if __name__ == "__main__":
    unittest.main()
