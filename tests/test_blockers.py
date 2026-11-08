#!/usr/bin/env python3
"""Blocker detection: a screenshot of a wall (bot check, "Video unavailable", Chrome first run...) fails the task.
The wording below is copied from real screenshots taken during the 9-phone test."""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for d in (os.path.join(ROOT, "scripts"), os.path.dirname(os.path.abspath(__file__))):
    if d not in sys.path:
        sys.path.insert(0, d)

import gl_bulk
from test_description_link import PNG, Phone, node


def labels(*texts):
    return [node(text=t) for t in texts]


class TestFindBlocker(unittest.TestCase):
    def kind(self, *texts):
        hit = gl_bulk.find_blocker(labels(*texts))
        return hit[0] if hit else None

    def test_the_screens_seen_in_the_test(self):
        # curly apostrophes are what Android really shows
        self.assertEqual(self.kind("Sign in to confirm you’re not a bot", "Cancel", "Confirm"), "bot check")
        self.assertEqual(self.kind("Video unavailable", "This content isn’t available.", "Skip video"), "video unavailable")
        self.assertEqual(self.kind("Welcome to Chrome", "Accept & continue"), "Chrome first-run screen")

    def test_other_walls(self):
        self.assertEqual(self.kind("Verify it’s you"), "Google verification prompt")
        self.assertEqual(self.kind("Your account has been suspended"), "account problem")
        self.assertEqual(self.kind("Sign in to confirm your age"), "age check")
        self.assertEqual(self.kind("Something went wrong"), "app error")
        self.assertEqual(self.kind("You're offline"), "no connection")
        self.assertEqual(self.kind("We detected unusual traffic from your computer network"), "bot check")

    def test_matches_a_content_description_too(self):
        self.assertEqual(gl_bulk.find_blocker([node(desc="Video unavailable")])[0], "video unavailable")

    def test_ordinary_screens_are_not_blockers(self):
        # real labels from healthy screens: feed, watch page, ad panel, the harmless prompts
        self.assertIsNone(gl_bulk.find_blocker(labels(
            "Home", "Shorts", "Subscriptions", "You", "Subscribe", "Comments 553", "Search", "Sponsored", "Skip ad",
            "Turn on accessibility controls for the video player?", "Dismiss", "SETTINGS",
            "Picture-in-picture has been disabled for optimal viewing on this device.")))
        self.assertIsNone(gl_bulk.find_blocker([]))
        self.assertIsNone(gl_bulk.find_blocker([node(), node(text="   ")]))

    def test_first_hit_wins_and_reports_the_text(self):
        kind, text = gl_bulk.find_blocker(labels("Home", "Sign in to confirm you’re not a bot"))
        self.assertEqual(kind, "bot check")
        self.assertIn("not a bot", text)


class TestScreenshotFailsOnABlocker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def shoot(self, screen, params=None, tries=3):
        phone = Phone([screen])
        phone.ui_tries = tries
        ctx = gl_bulk.Ctx(phone, "t1", "r1", time.monotonic() + 600, self.tmp)
        ui = mock.Mock(side_effect=lambda c: screen)
        with mock.patch.object(gl_bulk, "ui_nodes", ui):
            res = gl_bulk._r_screenshot(ctx, params or {})
        return res, ui, phone

    def test_blocker_fails_the_task_but_keeps_the_evidence(self):
        res, _, _ = self.shoot(labels("Video unavailable", "Skip video"))
        self.assertEqual(res["status"], "failed")
        self.assertIn("video unavailable", res["message"])
        self.assertEqual(res["output"]["blocker"], "video unavailable")
        self.assertTrue(os.path.exists(res["output"]["path"]))        # the screenshot is still saved

    def test_clean_screen_succeeds(self):
        res, ui, _ = self.shoot(labels("Home", "Shorts"))
        self.assertEqual(res["status"], "success")
        self.assertEqual(ui.call_count, 1)

    def test_unreadable_screen_is_not_a_blocker(self):
        res, _, _ = self.shoot([])                                    # a playing video cannot be read
        self.assertEqual(res["status"], "success")
        self.assertNotIn("blocker", res["output"])

    def test_check_can_be_switched_off_and_then_the_screen_is_not_read(self):
        res, ui, _ = self.shoot(labels("Video unavailable"), {"blockers": False})
        self.assertEqual(res["status"], "success")
        self.assertEqual(ui.call_count, 0)

    def test_the_read_is_a_single_attempt_and_the_setting_is_restored(self):
        seen = []

        def spy(ctx):
            seen.append(ctx.transport.ui_tries)
            return []
        phone = Phone([[]])
        phone.ui_tries = 3
        ctx = gl_bulk.Ctx(phone, "t1", "r1", time.monotonic() + 600, self.tmp)
        with mock.patch.object(gl_bulk, "ui_nodes", spy):
            gl_bulk._r_screenshot(ctx, {})
        self.assertEqual(seen, [1])
        self.assertEqual(phone.ui_tries, 3)

    def test_validation(self):
        gl_bulk._v_screenshot({})
        gl_bulk._v_screenshot({"blockers": False})
        with self.assertRaises(gl_bulk.TaskError):
            gl_bulk._v_screenshot({"blockers": "no"})


if __name__ == "__main__":
    unittest.main()
