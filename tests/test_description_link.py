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
        res = self.run_task(phone)
        self.assertNotEqual(res["status"], "success")
        self.assertIn("confirm", res["message"])
        self.assertEqual(phone.taps, [(457, 534)])

    def test_no_tap_in_the_first_fifteen_seconds_when_no_ad_was_seen(self):
        phone = Phone([[]])
        self.run_task(phone, step=1)
        self.assertTrue(phone.tap_times and phone.tap_times[0] >= 15, phone.tap_times)

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
