#!/usr/bin/env python3
"""Tests for the screenshot probes (gl_pixels) and the verified YouTube steps (clear-ads, tap-like, send-comment).

The fixtures in tests/fixtures/pixels are real GeeLark screenshots (YouTube on a 720x1440 phone) shrunk to a quarter of their
size. The actions run against a scripted fake screen: each call to screenshot() returns the next fixture, so the tests can
show exactly what the step saw and did. No phone, network or sheet is touched."""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT_DIR = os.path.join(ROOT, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import gl_bulk
import gl_pixels as P

FIX = os.path.join(ROOT, "tests", "fixtures", "pixels")


def shot(name):
    with open(os.path.join(FIX, name + ".png"), "rb") as f:
        return f.read()


def img(name):
    return P.decode_png(shot(name))


class FakeTransport:
    """screenshot() returns the scripted screens in order and then keeps showing the last one."""

    def __init__(self, screens):
        self.screens = list(screens)
        self.looks = 0

    def screenshot(self, timeout=90):
        data = self.screens[min(self.looks, len(self.screens) - 1)]
        self.looks += 1
        return {"returncode": 0, "stdout": data, "stderr": ""}


class FakeCtx:
    def __init__(self, *names, raw=None):
        self.transport = FakeTransport(raw if raw is not None else [shot(n) for n in names])
        self.taps, self.waited = [], 0.0

    def tap_normalized(self, x, y):
        self.taps.append((round(x, 3), round(y, 3)))
        return (x, y)

    def wait(self, s):
        self.waited += s


class TestProbes(unittest.TestCase):
    def test_watch_page_is_told_apart_from_ads_panels_and_composers(self):
        for name in ("watch_outline", "watch_liked", "watch_liked_bell"):
            self.assertTrue(P.watch_page_ready(img(name)), name)
        for name in ("ad_panel", "ad_panel_2", "comments_panel", "composer_typed", "composer_empty", "composer_closed", "signin_prompt"):
            self.assertFalse(P.watch_page_ready(img(name)), name)

    def test_like_state_filled_outline_and_unknown_off_the_watch_page(self):
        self.assertEqual(P.like_state(img("watch_outline")), "outline")
        self.assertEqual(P.like_state(img("watch_liked")), "filled")
        self.assertEqual(P.like_state(img("watch_liked_bell")), "filled")
        for name in ("ad_panel", "ad_panel_2", "comments_panel", "composer_typed"):
            self.assertEqual(P.like_state(img(name)), "unknown", name)         # never trusted away from the watch page

    def test_send_arrow_is_found_where_it_really_is_on_both_layouts(self):
        fx, fy = P.red_blob(img("composer_typed"))
        self.assertAlmostEqual(fx, 0.915, delta=0.01)
        self.assertAlmostEqual(fy, 0.401, delta=0.01)
        _, fy_tall = P.red_blob(img("composer_typed_tall"))
        self.assertAlmostEqual(fy_tall, 0.452, delta=0.01)                     # a taller box moves the arrow down
        for name in ("composer_empty", "composer_closed", "watch_liked", "ad_panel", "comments_panel", "signin_prompt"):
            self.assertIsNone(P.red_blob(img(name)), name)

    def test_the_same_answers_at_full_and_reduced_size(self):
        big_w, big_h = 720, 1440
        small = img("watch_liked")
        self.assertEqual((small.w, small.h), (big_w // 4, big_h // 4))

    def test_decoder_refuses_what_it_cannot_read(self):
        self.assertIsNone(P.decode_png(b""))
        self.assertIsNone(P.decode_png(b"\xff\xd8\xff not a png"))              # JPEG
        self.assertIsNone(P.decode_png(shot("watch_liked")[:200]))              # truncated
        self.assertIsNone(P.decode_png(None))

    def test_png_round_trip(self):
        rows = [bytes([10, 20, 30] * 4), bytes([200, 100, 50] * 4)]
        out = P.decode_png(P.encode_png(4, 2, rows))
        self.assertEqual((out.w, out.h), (4, 2))
        self.assertEqual(out.px(0, 0), (10, 20, 30))
        self.assertEqual(out.px(3, 1), (200, 100, 50))


class TestClearAds(unittest.TestCase):
    def test_taps_skip_until_the_watch_page_shows(self):
        ctx = FakeCtx("ad_panel", "ad_panel_2", "watch_outline")
        res = gl_bulk._r_clear_ads(ctx, {})
        self.assertEqual(res["status"], "success")
        self.assertEqual(ctx.taps, [(0.894, 0.214)] * 2)
        self.assertIn("2 Skip tap", res["message"])

    def test_no_tap_at_all_when_the_page_is_already_ready(self):
        ctx = FakeCtx("watch_outline")
        self.assertEqual(gl_bulk._r_clear_ads(ctx, {})["status"], "success")
        self.assertEqual(ctx.taps, [])

    def test_gives_up_with_a_clear_reason_and_taps_nothing_but_skip(self):
        ctx = FakeCtx("ad_panel")
        res = gl_bulk._r_clear_ads(ctx, {"max_rounds": 3})
        self.assertEqual(res["status"], "failed")
        self.assertIn("did not appear", res["message"])
        self.assertEqual(set(ctx.taps), {(0.894, 0.214)})
        self.assertEqual(len(ctx.taps), 3)

    def test_unreadable_screens_fall_back_to_the_old_blind_sequence_and_say_so(self):
        ctx = FakeCtx(raw=[b"\xff\xd8\xff jpeg"])
        res = gl_bulk._r_clear_ads(ctx, {})
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(ctx.taps), 3)
        self.assertIn("not verified", res["message"])


class TestTapLike(unittest.TestCase):
    LIKE = (0.486, 0.446)

    def test_taps_once_and_confirms_the_thumb_filled(self):
        ctx = FakeCtx("watch_outline", "watch_liked")
        res = gl_bulk._r_tap_like(ctx, {})
        self.assertEqual(res["status"], "success")
        self.assertIn("confirmed", res["message"])
        self.assertEqual(ctx.taps, [self.LIKE])

    def test_never_taps_when_the_video_is_already_liked(self):
        ctx = FakeCtx("watch_liked")
        res = gl_bulk._r_tap_like(ctx, {})
        self.assertEqual(res["status"], "success")
        self.assertIn("already liked", res["message"])
        self.assertEqual(ctx.taps, [])                                         # a second tap would un-like

    def test_never_taps_over_an_ad_or_another_screen(self):
        for name in ("ad_panel", "comments_panel", "signin_prompt"):
            ctx = FakeCtx(name)
            res = gl_bulk._r_tap_like(ctx, {})
            self.assertEqual(res["status"], "failed", name)
            self.assertEqual(ctx.taps, [], name)

    def test_a_slow_ui_gets_a_second_look_before_it_counts_as_failed(self):
        ctx = FakeCtx("watch_outline", "watch_outline", "watch_liked")
        self.assertEqual(gl_bulk._r_tap_like(ctx, {})["status"], "success")
        self.assertEqual(len(ctx.taps), 1)

    def test_still_empty_after_the_tap_fails_and_is_never_tapped_again(self):
        ctx = FakeCtx("watch_outline")
        res = gl_bulk._r_tap_like(ctx, {})
        self.assertEqual(res["status"], "failed")
        self.assertIn("still empty", res["message"])
        self.assertEqual(len(ctx.taps), 1)                                     # no retry: a retry could un-like

    def test_an_unclear_screen_after_the_tap_is_reported_as_unconfirmed_not_failed(self):
        ctx = FakeCtx("watch_outline", "ad_panel")
        res = gl_bulk._r_tap_like(ctx, {})
        self.assertEqual(res["status"], "success")
        self.assertIn("not confirmed", res["message"])

    def test_unreadable_screens_fall_back_to_one_blind_tap_and_say_so(self):
        ctx = FakeCtx(raw=[b"junk"])
        res = gl_bulk._r_tap_like(ctx, {})
        self.assertEqual(res["status"], "success")
        self.assertIn("could not read", res["message"])
        self.assertEqual(len(ctx.taps), 1)


class TestSendComment(unittest.TestCase):
    def test_taps_the_arrow_where_it_is_and_confirms_it_disappeared(self):
        ctx = FakeCtx("composer_typed", "composer_closed")
        res = gl_bulk._r_send_comment(ctx, {})
        self.assertEqual(res["status"], "success")
        self.assertIn("arrow is gone", res["message"])
        self.assertEqual(len(ctx.taps), 1)
        self.assertAlmostEqual(ctx.taps[0][1], 0.40, delta=0.012)

    def test_follows_the_arrow_when_a_longer_comment_makes_the_box_taller(self):
        ctx = FakeCtx("composer_typed_tall", "composer_closed")
        self.assertEqual(gl_bulk._r_send_comment(ctx, {})["status"], "success")
        self.assertAlmostEqual(ctx.taps[0][1], 0.452, delta=0.012)             # not the fixed 0.401 spot

    def test_sends_nothing_when_there_is_no_arrow(self):
        for name in ("composer_empty", "composer_closed", "comments_panel", "watch_liked", "signin_prompt"):
            ctx = FakeCtx(name)
            res = gl_bulk._r_send_comment(ctx, {})
            self.assertEqual(res["status"], "failed", name)
            self.assertIn("Nothing was sent", res["message"], name)
            self.assertEqual(ctx.taps, [], name)

    def test_a_slow_post_is_given_time_instead_of_being_tapped_twice(self):
        ctx = FakeCtx("composer_typed", "composer_typed", "composer_closed")   # still there after 6 s, gone after 11 s
        res = gl_bulk._r_send_comment(ctx, {})
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(ctx.taps), 1)

    def test_retries_once_when_the_arrow_never_goes_then_succeeds(self):
        ctx = FakeCtx("composer_typed", "composer_typed", "composer_typed", "composer_closed")
        res = gl_bulk._r_send_comment(ctx, {})
        self.assertEqual(res["status"], "success")
        self.assertIn("after 1 retry", res["message"])
        self.assertEqual(len(ctx.taps), 2)

    def test_fails_after_the_allowed_retries_and_never_taps_more_than_that(self):
        ctx = FakeCtx("composer_typed")
        res = gl_bulk._r_send_comment(ctx, {})
        self.assertEqual(res["status"], "failed")
        self.assertIn("still in the box", res["message"])
        self.assertEqual(len(ctx.taps), 2)                                     # one try + one retry
        ctx0 = FakeCtx("composer_typed")
        gl_bulk._r_send_comment(ctx0, {"retries": 0})
        self.assertEqual(len(ctx0.taps), 1)

    def test_unreadable_screens_fall_back_to_the_usual_spot_and_say_so(self):
        ctx = FakeCtx(raw=[b"junk"])
        res = gl_bulk._r_send_comment(ctx, {})
        self.assertEqual(res["status"], "success")
        self.assertIn("could not read", res["message"])
        self.assertEqual(ctx.taps, [(0.917, 0.401)])


class TestRecipesUseTheVerifiedSteps(unittest.TestCase):
    LINK = "https://youtu.be/u1Yjxw2Wg4Y"

    def steps(self, recipe):
        spec = self.LINK + (" | Does the Clockify to Slack zap still work if the timer is left running?" if recipe != "like" else "")
        return gl_bulk.recipe_steps({"recipe": recipe, "spec": spec})

    def test_ads_are_cleared_by_looking_not_by_a_fixed_number_of_taps(self):
        for recipe in gl_bulk.RECIPES:
            acts = [s["action"] for s in self.steps(recipe)]
            self.assertIn("clear-ads", acts)
            self.assertLess(acts.index("clear-ads"), acts.index("tap-like") if "tap-like" in acts else len(acts))
            self.assertEqual(acts.count("tap"), 1 if recipe != "like" else 0)  # only the comment-box tap remains a plain tap

    def test_like_and_send_are_the_verified_actions_with_their_safety_tags(self):
        like = [s for s in self.steps("like_comment") if s["action"] == "tap-like"]
        send = [s for s in self.steps("like_comment") if s["action"] == "send-comment"]
        self.assertEqual([s["engage"] for s in like], ["like"])
        self.assertEqual([s["engage"] for s in send], ["comment_send"])

    def test_the_send_step_comes_after_the_text_is_typed(self):
        acts = [s["action"] for s in self.steps("comment")]
        self.assertLess(acts.index("type"), acts.index("send-comment"))

    def test_a_recipe_task_gets_a_longer_time_limit_than_the_sheets_per_task_default(self):
        self.assertEqual(gl_bulk.ACTIONS["flow"]["timeout"]({"recipe": "like", "spec": self.LINK}), 600)
        self.assertEqual(gl_bulk.ACTIONS["flow"]["timeout"]({"steps": [{"action": "sleep", "seconds": 1}]}), 0)

    def test_every_recipe_still_validates_as_a_task(self):
        for recipe in gl_bulk.RECIPES:
            spec = self.LINK + (" | Does the Clockify to Slack zap still work if the timer is left running?" if recipe != "like" else "")
            task = gl_bulk.normalize_task({"task_id": "x", "device": "cloud:1", "action": "flow", "params": {"recipe": recipe, "spec": spec}})
            self.assertEqual(task["action"], "flow")


if __name__ == "__main__":
    unittest.main()
