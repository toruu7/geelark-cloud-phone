import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import gl_bulk  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
VIDEO = "https://www.youtube.com/watch?v=Bm84BAtOfQw"


def node(text="", desc="", bounds=(0, 0, 100, 50), clickable=False):
    return {"text": text, "desc": desc, "bounds": bounds, "clickable": clickable}


AD = [node(desc="Skip ad", bounds=(605, 301, 710, 353)), node(text="Skip", bounds=(625, 313, 677, 340)),
      node(text="Sponsored", clickable=True), node(desc="More info", clickable=True)]
SHEET = [node(text="Description"), node(text="Try it at danmartell.com/offer today", bounds=(100, 800, 600, 840), clickable=True)]


class Phone:
    """A scripted phone: ui_nodes() replays `screens` (the last one repeats); every tap and key is recorded."""

    def __init__(self, screens, foreground="com.google.android.youtube/.WatchActivity"):
        self.screens = list(screens)
        self.foreground = foreground
        self.taps, self.keys, self.cmds, self.tap_times = [], [], [], []
        self.now = [0]
        self.kind = "api"
        self.label = "fake"

    def run(self, args, timeout=None):
        a = [str(x) for x in args]
        self.cmds.append(a)
        if a[:3] == ["shell", "input", "tap"]:
            self.taps.append((int(a[3]), int(a[4])))
            self.tap_times.append(self.now[0])
        if a[:3] == ["shell", "input", "keyevent"]:
            self.keys.append(a[3])
        if a[:3] == ["shell", "wm", "size"]:
            return {"returncode": 0, "stdout": "Physical size: 720x1440", "stderr": ""}
        if "dumpsys" in a:
            return {"returncode": 0, "stdout": f"mCurrentFocus=Window{{x u0 {self.foreground}}}", "stderr": ""}
        return {"returncode": 0, "stdout": "", "stderr": ""}

    def screenshot(self, timeout=90):
        return {"returncode": 0, "stdout": PNG, "stderr": ""}

    def state(self):
        return "device"

    def next_screen(self):
        return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]


class TestDescriptionLink(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def run_task(self, phone, step=3, **params):
        ctx = gl_bulk.Ctx(phone, "t1", "r1", 10 ** 9, self.tmp)
        ctx.wait = lambda s: None
        p = {"url": VIDEO, "link_text": "danmartell.com", "ad_wait_s": 30}
        p.update(params)
        now = [0]
        phone.now = now

        def tick():                                          # every call advances the clock: waits are instant in real time
            now[0] += step
            return now[0]
        ctx.deadline = 10 ** 9
        with mock.patch.object(gl_bulk, "ui_nodes", lambda c: phone.next_screen()),              mock.patch.object(gl_bulk.time, "monotonic", tick):
            return gl_bulk._r_description_link(ctx, p)

    # --- validation
    def test_validation(self):
        gl_bulk._v_description_link({"url": VIDEO, "link_text": "danmartell.com"})
        gl_bulk._v_description_link({"spec": VIDEO + " | danmartell.com"})
        for bad in ({"url": "http://youtube.com/x", "link_text": "abc"}, {"url": "https://evil.example/x", "link_text": "abc"},
                    {"url": VIDEO}, {"url": VIDEO, "link_text": "ab"}, {"spec": VIDEO}):
            with self.assertRaises(gl_bulk.TaskError, msg=str(bad)):
                gl_bulk._v_description_link(bad)

    def test_spec_is_split_on_the_bar(self):
        self.assertEqual(gl_bulk._desc_link_args({"spec": VIDEO + " | danmartell.com"}), (VIDEO, "danmartell.com"))

    def test_third_field_of_the_spec_sets_the_tap_height(self):
        self.assertEqual(gl_bulk._desc_link_args({"spec": VIDEO + " | danmartell.com | 0.39"}), (VIDEO, "danmartell.com"))
        self.assertEqual(gl_bulk._desc_row_y({"spec": VIDEO + " | danmartell.com | 0.39"}), 0.39)
        self.assertEqual(gl_bulk._desc_row_y({"spec": VIDEO + " | danmartell.com"}), 0.371)       # default unchanged
        self.assertEqual(gl_bulk._desc_row_y({"more_y": 0.4}), 0.4)
        gl_bulk._v_description_link({"spec": VIDEO + " | danmartell.com | 0.39"})
        for bad in ("abc", "0.9", "0.1"):
            with self.assertRaises(gl_bulk.TaskError, msg=bad):
                gl_bulk._v_description_link({"spec": VIDEO + " | danmartell.com | " + bad})

    def test_the_tap_lands_at_the_height_from_the_spec(self):
        phone = Phone([AD, [], [], [], SHEET])
        res = self.run_task(phone, spec=VIDEO + " | danmartell.com | 0.39")
        self.assertEqual(res["status"], "success", res)
        self.assertIn((457, int(0.39 * 1440)), phone.taps)       # the title row on the newer layout
        self.assertNotIn((457, 534), phone.taps)

    def test_third_field_can_set_x_and_y(self):
        self.assertEqual(gl_bulk._desc_tap({"spec": VIDEO + " | danmartell.com | 0.76,0.39"}), (0.76, 0.39))
        self.assertEqual(gl_bulk._desc_tap({"spec": VIDEO + " | danmartell.com | 0.39"}), (0.636, 0.39))
        self.assertEqual(gl_bulk._desc_tap({"spec": VIDEO + " | danmartell.com"}), (0.636, 0.371))
        for bad in ("0.76,0.39,1", "0.99,0.39", "0.05,0.39", "a,b"):
            with self.assertRaises(gl_bulk.TaskError, msg=bad):
                gl_bulk._v_description_link({"spec": VIDEO + " | danmartell.com | " + bad})

    def test_the_tap_lands_at_x_and_y_from_the_spec(self):
        phone = Phone([AD, [], [], [], SHEET])
        res = self.run_task(phone, spec=VIDEO + " | danmartell.com | 0.76,0.39")
        self.assertEqual(res["status"], "success", res)
        self.assertIn((int(0.76 * 720), int(0.39 * 1440)), phone.taps)

    def test_share_sheet_is_closed_and_nothing_in_it_is_tapped(self):
        share = [node(text="Share"), node(text="Copy link", clickable=True, bounds=(160, 1180, 300, 1280))]
        phone = Phone([AD, [], [], [], share])
        res = self.run_task(phone)
        self.assertNotEqual(res["status"], "success")
        self.assertIn("Share sheet", res["message"])
        self.assertEqual(len(phone.taps), 2)          # skip + the one title-row tap; nothing inside the sheet
        self.assertTrue(phone.keys)                   # Back was pressed to close it

    # --- the safe path
    def test_ad_then_description_then_link(self):
        # ad (twice), then three unreadable reads (ad gone), then the description sheet
        phone = Phone([AD, AD, [], [], [], SHEET])
        res = self.run_task(phone)
        self.assertEqual(res["status"], "success", res)
        # skip tapped (centre of 605..710 x 301..353), then the title row, then the link; never anything else
        self.assertEqual(phone.taps[0], (657, 327))
        self.assertEqual(phone.taps[-1], (350, 820))
        self.assertIn((457, 534), phone.taps)                 # int(0.636*720), int(0.371*1440)
        self.assertEqual(len(phone.taps), 4)                  # skip x2 (ad read twice), title row, link
        self.assertEqual(phone.keys.count(str(gl_bulk.gl_adb.KEYCODES["back"])), 2)   # two Backs
        self.assertEqual(len(res["output"]["screenshots"]), 2)

    # --- every refusal taps nothing it should not
    def test_ad_that_never_ends_taps_only_skip(self):
        phone = Phone([AD])
        res = self.run_task(phone, ad_wait_s=20)
        self.assertNotEqual(res["status"], "success")
        self.assertIn("ad was still on screen", res["message"])
        self.assertNotIn((457, 534), phone.taps)              # the title row was never tapped

    def test_unreadable_page_taps_only_the_title_row_and_never_the_link(self):
        # nothing readable and no ad ever seen: after 15 s the title row may be tapped, but with no confirmation no link is
        phone = Phone([[]])
        res = self.run_task(phone, ad_wait_s=120)
        self.assertNotEqual(res["status"], "success")
        self.assertIn("confirm", res["message"])
        self.assertEqual(phone.taps, [(457, 534)])

    def test_no_tap_before_the_blind_wait_when_no_ad_was_seen(self):
        # an unreadable ad screen looks exactly like "no ad": the fallback wait must outlast a typical pre-roll
        phone = Phone([[]])
        self.run_task(phone, step=1, ad_wait_s=120)
        self.assertTrue(phone.tap_times and phone.tap_times[0] >= 50, phone.tap_times)

    def test_the_blind_wait_can_be_changed_and_is_validated(self):
        phone = Phone([[]])
        self.run_task(phone, step=1, ad_wait_s=120, ad_blind_wait_s=80)
        self.assertTrue(phone.tap_times and phone.tap_times[0] >= 80, phone.tap_times)
        gl_bulk._v_description_link({"spec": VIDEO + " | danmartell.com", "ad_blind_wait_s": 60})
        with self.assertRaises(gl_bulk.TaskError):
            gl_bulk._v_description_link({"spec": VIDEO + " | danmartell.com", "ad_blind_wait_s": 5})

    def test_an_in_feed_ad_below_the_comments_does_not_block_the_task(self):
        feed_ad = [node(text="Sponsored", bounds=(17, 900, 144, 960), clickable=True),
                   node(desc="Learn more", bounds=(100, 1200, 600, 1260), clickable=True)]
        # pre-roll seen once, then the page reads as only the in-feed ad (3 times), then the description sheet
        phone = Phone([AD, feed_ad, feed_ad, feed_ad, SHEET])
        res = self.run_task(phone)
        self.assertEqual(res["status"], "success", res)
        self.assertEqual(phone.taps[-1], (350, 820))

    def test_pre_roll_markers_at_the_top_still_count(self):
        self.assertTrue(gl_bulk._ad_on_screen([node(text="Sponsored", bounds=(17, 375, 144, 434))]))
        self.assertTrue(gl_bulk._ad_on_screen([node(desc="Visit advertiser", bounds=(540, 42, 717, 120))]))
        self.assertFalse(gl_bulk._ad_on_screen([node(text="Sponsored", bounds=(17, 900, 144, 960))]))

    def test_description_not_confirmed_never_taps_the_link(self):
        phone = Phone([AD, [], [], [], []])                   # after the ad, the page stays unreadable
        res = self.run_task(phone)
        self.assertNotEqual(res["status"], "success")
        self.assertIn("confirm", res["message"])
        self.assertEqual(phone.taps[-1], (457, 534))          # only the Skip tap and the title row, no link tap

    def test_ad_panel_opening_instead_of_the_description_stops(self):
        phone = Phone([AD, [], [], [], AD])
        res = self.run_task(phone)
        self.assertNotEqual(res["status"], "success")
        self.assertIn("ad panel", res["message"])

    def test_link_text_missing_from_the_description(self):
        phone = Phone([AD, [], [], [], [node(text="Description"), node(text="nothing useful here")]])
        res = self.run_task(phone)
        self.assertNotEqual(res["status"], "success")
        self.assertIn("not found", res["message"])

    def test_youtube_must_be_in_the_foreground(self):
        phone = Phone([AD, [], [], [], SHEET], foreground="com.android.chrome/.Main")
        res = self.run_task(phone)
        self.assertNotEqual(res["status"], "success")
        self.assertIn("foreground", res["message"])
        self.assertNotIn((457, 534), phone.taps)

    def test_ad_buttons_are_never_matched_as_the_link(self):
        # even a link text of "more" must not hit an ad's "More info"/"Learn more" because the ad gate refuses first
        phone = Phone([AD])
        res = self.run_task(phone, link_text="more", ad_wait_s=20)
        self.assertNotEqual(res["status"], "success")
        self.assertNotIn((52, 25), phone.taps)


class TestRegistered(unittest.TestCase):
    def test_action_is_registered_and_in_the_sheet_script(self):
        self.assertIn("description-link", gl_bulk.ACTIONS)
        with open(os.path.join(os.path.dirname(__file__), "..", "sheets", "apps_script.gs"), encoding="utf-8") as f:
            script = f.read()
        self.assertIn("'description-link'", script)


if __name__ == "__main__":
    unittest.main()
