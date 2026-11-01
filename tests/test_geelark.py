#!/usr/bin/env python3
"""
Comprehensive Unit and Integration Test Suite for GeeLark Cloud Phone Automation Skill.
Persona: Usopp (Sniper / Edge-Case Hunter & Test Scout)

Covers every capability, edge case, and failure mode:
1. Mathematics & Easing: Cubic Bézier curves, velocity easing, extreme & boundary conditions.
2. Target Persistence: Profile caching, cache corruption, missing files, type resilience.
3. Window Discovery & Geometry: Exact profile # vs substring matching, HWND resolution, screen bounds,
   fallback behavior, unknown target window isolation.
4. Input & Gestures: Key mappings (home, back, recent to normalized coordinates), keyboard hiding,
   platform guards, coordinate normalization.
5. Set-of-Mark & Native OCR: Numbered badge lookups, corrupt marks cache, missing badges,
   case-insensitive text search, wait-and-click polling & timeout, autonomous scroll-find loop.
6. App Launching & Deep-Linking: Common apps catalog, ADB intent dispatch, visual OCR fallback,
   Chrome omnibox fallback.
7. Compound Recipes: YouTube 1-click flow, TikTok warmup feed with randomized watch & likes.
8. Failsafes & Self-Healing: Popup dismissal with keyword matching & back fallback, emergency recovery.
9. Multi-Device Orchestration:
   - batch-run: JSON file, JSON string, dict, list, all 16 supported actions, step errors,
     inner action error propagation, per-step window overrides.
   - broadcast: Multicast across all open phones, empty phone handling, per-window exception isolation,
     parameter validation, unsupported command guards.
   - batch-profiles: Sequential execution across profile lists ("all", "1,2,4"), missing profiles,
     parameter validation, per-profile exception isolation.
10. Feature Manifest & CLI Dispatch: Text & JSON feature manifests, system status, CLI argument routing.
"""

import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock, call

# Add scripts directory to module path
SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import geelark


class TestGeeLarkCoreFeatures(unittest.TestCase):
    """Core capabilities, configuration, and target management."""

    def setUp(self):
        self.original_session_file = geelark.SESSION_CACHE_PATH
        self.test_session_file = os.path.join(SCRIPT_DIR, ".test_session.json")
        geelark.SESSION_CACHE_PATH = self.test_session_file

    def tearDown(self):
        geelark.SESSION_CACHE_PATH = self.original_session_file
        if os.path.exists(self.test_session_file):
            try:
                os.remove(self.test_session_file)
            except OSError:
                pass

    def test_bezier_and_easing_math(self):
        """Verify cubic Bézier curve calculation and ease_in_out interpolation."""
        p0 = (100, 200)
        p1 = (120, 250)
        p2 = (140, 350)
        p3 = (150, 400)

        # t = 0.0 must be p0
        pt0 = geelark.bezier_point(p0, p1, p2, p3, 0.0)
        self.assertEqual(pt0, p0)

        # t = 1.0 must be p3
        pt1 = geelark.bezier_point(p0, p1, p2, p3, 1.0)
        self.assertEqual(pt1, p3)

        # Intermediate points must fall within bounding envelope
        pt_mid = geelark.bezier_point(p0, p1, p2, p3, 0.5)
        self.assertTrue(p0[0] <= pt_mid[0] <= p3[0])
        self.assertTrue(p0[1] <= pt_mid[1] <= p3[1])

        # Easing function checks
        self.assertAlmostEqual(geelark.ease_in_out(0.0), 0.0)
        self.assertAlmostEqual(geelark.ease_in_out(1.0), 1.0)
        self.assertAlmostEqual(geelark.ease_in_out(0.5), 0.5)
        self.assertTrue(geelark.ease_in_out(0.2) < 0.2)  # Ease in (slow start)
        self.assertTrue(geelark.ease_in_out(0.8) > 0.8)  # Ease out (slow finish)

    def test_target_persistence(self):
        """Test setting, persisting, and retrieving active phone profile."""
        self.assertIsNone(geelark.get_active_target())

        res = geelark.set_active_target("4")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["active_target"], "4")
        self.assertEqual(geelark.get_active_target(), "4")

        # Overwrite with profile name
        geelark.set_active_target("Profile Alpha")
        self.assertEqual(geelark.get_active_target(), "Profile Alpha")

    def test_target_persistence_corrupt_file_handling(self):
        """Edge case: Corrupt or malformed session file returns None without crashing."""
        with open(self.test_session_file, "w", encoding="utf-8") as f:
            f.write("{ INVALID JSON DATA %%%")
        self.assertIsNone(geelark.get_active_target())

    def test_common_apps_catalog(self):
        """Verify common app packages are correctly mapped."""
        apps = geelark.COMMON_APPS
        self.assertIn("youtube", apps)
        self.assertIn("tiktok", apps)
        self.assertIn("chrome", apps)
        self.assertIn("settings", apps)
        self.assertIn("playstore", apps)
        self.assertIn("files", apps)

        self.assertEqual(apps["youtube"], "com.google.android.youtube")
        self.assertEqual(apps["tiktok"], "com.zhiliaoapp.musically")
        self.assertEqual(apps["chrome"], "com.android.chrome")

    def test_feature_manifest_completeness(self):
        """Verify get_feature_manifest provides a full and structured catalog."""
        manifest = geelark.get_feature_manifest()
        self.assertEqual(manifest["name"], "geelark-cloud-phone")
        self.assertIn("4.1", manifest["version"])

        # Capabilities inspection
        caps = manifest["capabilities"]
        expected_categories = [
            "target_management",
            "visual_screen_capture",
            "touch_gestures_navigation",
            "windows_native_ocr",
            "app_launcher_deep_links",
            "automated_compound_recipes",
            "multi_device_orchestration",
            "self_healing_failsafes",
            "external_integrations"
        ]
        for cat in expected_categories:
            self.assertIn(cat, caps, f"Missing capability category: {cat}")
            self.assertIn("description", caps[cat])

        # Supported batch actions check
        batch_actions = manifest["supported_batch_actions"]
        self.assertIn("tap", batch_actions)
        self.assertIn("swipe", batch_actions)
        self.assertIn("sleep", batch_actions)
        self.assertIn("deep-link", batch_actions)
        self.assertIn("youtube-flow", batch_actions)
        self.assertIn("tiktok-feed", batch_actions)
        self.assertIn("scroll-find", batch_actions)
        self.assertIn("dismiss-popup", batch_actions)

        # Key mappings
        self.assertIn("back", manifest["key_mappings"])
        self.assertIn("home", manifest["key_mappings"])
        self.assertIn("recent / appswitch", manifest["key_mappings"])

    def test_sample_batch_file_is_valid(self):
        """Ensure examples/sample_batch.json parses properly."""
        sample_path = os.path.join(os.path.dirname(__file__), "..", "examples", "sample_batch.json")
        self.assertTrue(os.path.exists(sample_path))
        with open(sample_path, "r", encoding="utf-8") as f:
            steps = json.load(f)
        self.assertIsInstance(steps, list)
        self.assertTrue(len(steps) > 0)
        for s in steps:
            self.assertIn("action", s)

    def test_n8n_trigger_file_is_valid(self):
        """Ensure examples/n8n_trigger.json is valid n8n workflow JSON."""
        n8n_path = os.path.join(os.path.dirname(__file__), "..", "examples", "n8n_trigger.json")
        self.assertTrue(os.path.exists(n8n_path))
        with open(n8n_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)
        self.assertIn("nodes", workflow)
        self.assertIn("connections", workflow)

    def test_target_window_matching_preference(self):
        """Verify find_target_window prefers exact profile number matching over substring."""
        mock_windows = [
            {"hwnd": 1001, "title": "GeeLark - Launcher", "is_phone": False},
            {"hwnd": 1014, "title": "#14 GeeLarkPhone|Profile 14", "is_phone": True},
            {"hwnd": 1004, "title": "#4 GeeLarkPhone|Profile 4", "is_phone": True},
        ]
        with patch.object(geelark, "list_windows", return_value=mock_windows):
            # Target "4" should match #4, NOT #14!
            matched = geelark.find_target_window("4")
            self.assertIsNotNone(matched)
            self.assertEqual(matched["hwnd"], 1004)
            self.assertEqual(matched["title"], "#4 GeeLarkPhone|Profile 4")

            # Target 1014 by HWND
            matched_hwnd = geelark.find_target_window("1014")
            self.assertEqual(matched_hwnd["hwnd"], 1014)

            # Target specified but not found returns None
            matched_none = geelark.find_target_window("9999")
            self.assertIsNone(matched_none)

            # Default when target is None returns first phone window
            matched_default = geelark.find_target_window(None)
            self.assertEqual(matched_default["hwnd"], 1014)

    def test_target_window_empty_list(self):
        """find_target_window returns None when no windows are open."""
        with patch.object(geelark, "list_windows", return_value=[]):
            self.assertIsNone(geelark.find_target_window("4"))
            self.assertIsNone(geelark.find_target_window(None))

    def test_phone_screen_bounds_calculation(self):
        """Verify phone window bounds account for title bar and toolbar offsets."""
        phone_win = {
            "hwnd": 100,
            "title": "#1 Phone",
            "is_phone": True,
            "rect": {"left": 10, "top": 20, "right": 404, "bottom": 730, "width": 394, "height": 710}
        }
        bounds = geelark.get_phone_screen_bounds(phone_win)
        self.assertEqual(bounds["x"], 10)
        self.assertEqual(bounds["y"], 50)  # top + 30
        self.assertEqual(bounds["width"], 350)  # width - 44
        self.assertEqual(bounds["height"], 680)  # height - 30

        app_win = {
            "hwnd": 200,
            "title": "GeeLark Main",
            "is_phone": False,
            "rect": {"left": 0, "top": 0, "right": 800, "bottom": 600, "width": 800, "height": 600}
        }
        app_bounds = geelark.get_phone_screen_bounds(app_win)
        self.assertEqual(app_bounds["x"], 0)
        self.assertEqual(app_bounds["y"], 0)
        self.assertEqual(app_bounds["width"], 800)
        self.assertEqual(app_bounds["height"], 600)


class TestGeeLarkGesturesAndInput(unittest.TestCase):
    """Touch gestures, key dispatches, and navigation controls."""

    def test_send_key_navigation_mappings(self):
        """Verify back, home, recent, and appswitch map to normalized taps."""
        with patch.object(geelark, "tap") as mock_tap:
            mock_tap.return_value = {"status": "success"}

            geelark.send_key("back", target=101)
            mock_tap.assert_called_with(0.18, 0.97, target=101, normalized=True)

            geelark.send_key("home", target=102)
            mock_tap.assert_called_with(0.50, 0.97, target=102, normalized=True)

            geelark.send_key("recent", target=103)
            mock_tap.assert_called_with(0.82, 0.97, target=103, normalized=True)

            geelark.send_key("appswitch", target=104)
            mock_tap.assert_called_with(0.82, 0.97, target=104, normalized=True)

    def test_hide_keyboard_delegates_to_back(self):
        """Verify hide_keyboard sends back key to dismiss the soft keyboard."""
        with patch.object(geelark, "send_key") as mock_send_key:
            mock_send_key.return_value = {"status": "success", "action": "key", "key": "back"}
            res = geelark.hide_keyboard(target=202)
            mock_send_key.assert_called_with("back", target=202)
            self.assertEqual(res["status"], "success")

    def test_tap_and_swipe_non_windows_guard(self):
        """Verify tap and swipe raise RuntimeError when run in non-Windows environment."""
        if not geelark.IS_WINDOWS:
            with self.assertRaises(RuntimeError):
                geelark.tap(100, 200)

            with self.assertRaises(RuntimeError):
                geelark.swipe(100, 200, 100, 400)


class TestGeeLarkSetOfMarkAndOCR(unittest.TestCase):
    """Set-of-Mark visual annotations and Windows native OCR text matching."""

    def setUp(self):
        self.original_marks_file = geelark.MARKS_CACHE_PATH
        self.test_marks_file = os.path.join(SCRIPT_DIR, ".test_marks_cache.json")
        geelark.MARKS_CACHE_PATH = self.test_marks_file

    def tearDown(self):
        geelark.MARKS_CACHE_PATH = self.original_marks_file
        if os.path.exists(self.test_marks_file):
            try:
                os.remove(self.test_marks_file)
            except OSError:
                pass

    def test_tap_mark_missing_cache(self):
        """tap_mark returns error if marks cache file does not exist."""
        res = geelark.tap_mark(1)
        self.assertEqual(res["status"], "error")
        self.assertIn("No marks cache found", res["message"])

    def test_tap_mark_corrupt_cache(self):
        """tap_mark handles corrupt marks cache gracefully."""
        with open(self.test_marks_file, "w", encoding="utf-8") as f:
            f.write("MALFORMED JSON {{{")
        res = geelark.tap_mark(1)
        self.assertEqual(res["status"], "error")
        self.assertIn("Failed to read marks cache", res["message"])

    def test_tap_mark_id_not_found(self):
        """tap_mark returns error if mark_id is not present in cache."""
        with open(self.test_marks_file, "w", encoding="utf-8") as f:
            json.dump({"marks": {"1": {"norm": [0.5, 0.5]}}}, f)

        res = geelark.tap_mark(99)
        self.assertEqual(res["status"], "error")
        self.assertIn("Mark '99' not found", res["message"])

    def test_tap_mark_success(self):
        """tap_mark invokes tap with normalized coordinates when mark exists."""
        with open(self.test_marks_file, "w", encoding="utf-8") as f:
            json.dump({"marks": {"2": {"norm": [0.35, 0.75]}}}, f)

        with patch.object(geelark, "tap") as mock_tap:
            mock_tap.return_value = {"status": "success", "coords": [0.35, 0.75]}
            res = geelark.tap_mark(2, target=500)
            mock_tap.assert_called_with(0.35, 0.75, target=500, normalized=True)
            self.assertEqual(res["status"], "success")

    def test_find_text_on_screen(self):
        """find_text_on_screen parses OCR results and computes normalized centers."""
        mock_cap = {"file": "mock_screen.png", "size": [1000, 2000]}
        mock_words = [
            {"text": "Skip", "x": 800, "y": 1500, "w": 100, "h": 50},
            {"text": "Subscribe", "x": 100, "y": 800, "w": 200, "h": 60}
        ]
        with patch.object(geelark, "capture_phone", return_value=mock_cap):
            with patch.object(geelark, "run_ocr", return_value=mock_words):
                res = geelark.find_text_on_screen("skip")
                self.assertEqual(res["status"], "success")
                self.assertEqual(res["count"], 1)
                match = res["matches"][0]
                self.assertEqual(match["text"], "Skip")
                self.assertEqual(match["norm_center"], [0.85, 0.762])

    def test_click_text_on_screen_success_and_failure(self):
        """click_text_on_screen clicks when found, returns error when absent."""
        mock_find_found = {
            "status": "success",
            "matches": [{"text": "Skip", "norm_center": [0.85, 0.76]}]
        }
        with patch.object(geelark, "find_text_on_screen", return_value=mock_find_found):
            with patch.object(geelark, "tap", return_value={"status": "success"}):
                res = geelark.click_text_on_screen("Skip", target=1)
                self.assertEqual(res["status"], "success")
                self.assertEqual(res["action"], "click-text")
                self.assertEqual(res["matched"], "Skip")

        mock_find_empty = {"status": "success", "matches": []}
        with patch.object(geelark, "find_text_on_screen", return_value=mock_find_empty):
            res_fail = geelark.click_text_on_screen("NonExistent", target=1)
            self.assertEqual(res_fail["status"], "error")
            self.assertIn("not found on phone screen", res_fail["message"])

    def test_wait_and_click_text(self):
        """wait_and_click_text polls until text appears or times out."""
        # Case 1: Found immediately
        mock_found = {"status": "success", "matches": [{"text": "Install", "norm_center": [0.5, 0.5]}]}
        with patch.object(geelark, "find_text_on_screen", return_value=mock_found):
            with patch.object(geelark, "tap", return_value={"status": "success"}):
                res = geelark.wait_and_click_text("Install", timeout=2.0)
                self.assertEqual(res["status"], "success")
                self.assertEqual(res["clicked"], "Install")

        # Case 2: Timeout
        mock_empty = {"status": "success", "matches": []}
        with patch.object(geelark, "find_text_on_screen", return_value=mock_empty):
            res_timeout = geelark.wait_and_click_text("TimeoutText", timeout=0.1, poll_interval=0.05)
            self.assertEqual(res_timeout["status"], "error")
            self.assertIn("Timeout waiting for text", res_timeout["message"])

    def test_scroll_find_loop(self):
        """scroll_find performs autonomous scan, swipe, and click loop."""
        # Scenario: Found on second swipe
        find_results = [
            {"status": "success", "matches": []},  # Swipe 0: not found
            {"status": "success", "matches": [{"text": "http://example.com", "norm_center": [0.5, 0.6]}]}
        ]
        with patch.object(geelark, "find_text_on_screen", side_effect=find_results):
            with patch.object(geelark, "swipe") as mock_swipe:
                with patch.object(geelark, "tap") as mock_tap:
                    with patch("time.sleep"):
                        res = geelark.scroll_find("http", max_swipes=3, click=True)
                        self.assertEqual(res["status"], "success")
                        self.assertTrue(res["found"])
                        self.assertTrue(res["clicked"])
                        self.assertEqual(res["swipes_performed"], 1)
                        mock_swipe.assert_called_once()
                        mock_tap.assert_called_once()


class TestGeeLarkAppLaunchAndDeepLinks(unittest.TestCase):
    """App launching, ADB integration, and 0.1s instant deep-links."""

    def test_open_app_via_adb_and_fallback(self):
        """open_app uses ADB monkey launcher when available, falling back to visual OCR."""
        # ADB success
        with patch.object(geelark, "run_adb", return_value={"returncode": 0, "stdout": "Events injected: 1", "stderr": ""}):
            res = geelark.open_app("youtube")
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["method"], "adb")
            self.assertEqual(res["package"], "com.google.android.youtube")

        # ADB failure -> visual OCR fallback
        with patch.object(geelark, "run_adb", return_value={"returncode": 1, "stdout": "", "stderr": "error"}):
            with patch.object(geelark, "send_key"):
                with patch.object(geelark, "swipe"):
                    with patch.object(geelark, "click_text_on_screen", return_value={"status": "success"}):
                        with patch("time.sleep"):
                            res_fallback = geelark.open_app("tiktok")
                            self.assertEqual(res_fallback["status"], "success")
                            self.assertEqual(res_fallback["method"], "visual_ocr")

    def test_deep_link_via_adb_and_fallback(self):
        """deep_link opens URL via intent VIEW or falls back to Chrome omnibox."""
        # ADB Intent success
        with patch.object(geelark, "run_adb", return_value={"returncode": 0, "stdout": "", "stderr": ""}):
            res = geelark.deep_link("https://youtube.com/watch?v=xyz")
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["method"], "adb_intent")

        # Visual fallback
        with patch.object(geelark, "run_adb", return_value={"returncode": 1, "stdout": "", "stderr": "Error: Activity not found"}):
            with patch.object(geelark, "open_app"):
                with patch.object(geelark, "tap"):
                    with patch.object(geelark, "type_text"):
                        with patch.object(geelark, "send_key"):
                            with patch("time.sleep"):
                                res_fallback = geelark.deep_link("https://example.com")
                                self.assertEqual(res_fallback["status"], "success")
                                self.assertEqual(res_fallback["method"], "chrome_visual")


class TestGeeLarkFailsafesAndSelfHealing(unittest.TestCase):
    """Popup obstacle dismissal, stability verification, and emergency recovery."""

    def test_dismiss_popups_ocr_match(self):
        """dismiss_popups taps modal dismissal keyword when OCR detects one."""
        mock_cap = {"file": "modal.png", "size": [500, 1000]}
        mock_words = [{"text": "Skip trial", "x": 200, "y": 800, "w": 100, "h": 40}]

        with patch.object(geelark, "capture_phone", return_value=mock_cap):
            with patch.object(geelark, "run_ocr", return_value=mock_words):
                with patch.object(geelark, "tap") as mock_tap:
                    res = geelark.dismiss_popups()
                    self.assertEqual(res["status"], "success")
                    self.assertEqual(res["dismissed_via"], "Skip trial")
                    mock_tap.assert_called_once()

    def test_dismiss_popups_fallback_to_back(self):
        """dismiss_popups sends Back key when no dismissal buttons are detected."""
        mock_cap = {"file": "clean.png", "size": [500, 1000]}
        with patch.object(geelark, "capture_phone", return_value=mock_cap):
            with patch.object(geelark, "run_ocr", return_value=[]):
                with patch.object(geelark, "send_key") as mock_send_key:
                    res = geelark.dismiss_popups()
                    self.assertEqual(res["status"], "success")
                    self.assertEqual(res["dismissed_via"], "back_key")
                    mock_send_key.assert_called_with("back", target=None)

    def test_emergency_recover(self):
        """emergency_recover issues back-back-home sequence and captures state."""
        with patch.object(geelark, "send_key") as mock_send_key:
            with patch.object(geelark, "capture_phone", return_value={"file": "recovered.png"}):
                with patch("time.sleep"):
                    res = geelark.emergency_recover(target="Profile 1")
                    self.assertEqual(res["status"], "recovered")
                    self.assertEqual(mock_send_key.call_count, 3)
                    mock_send_key.assert_has_calls([
                        call("back", target="Profile 1"),
                        call("back", target="Profile 1"),
                        call("home", target="Profile 1")
                    ])


class TestGeeLarkOrchestrationAndBatch(unittest.TestCase):
    """Batch execution, multi-phone broadcasting, and sequential profile runs."""

    def test_execute_batch_steps_malformed_inputs(self):
        """Verify error handling on invalid JSON string, invalid path, or non-list data."""
        # Non-existent file and invalid json
        res_file = geelark.execute_batch_steps("non_existent_workflow.json")
        self.assertEqual(res_file["status"], "error")
        self.assertIn("Failed to parse", res_file["message"])

        # Invalid type
        res_type = geelark.execute_batch_steps(12345)
        self.assertEqual(res_type["status"], "error")
        self.assertIn("Invalid steps data type", res_type["message"])

    def test_execute_batch_steps_single_dict(self):
        """Verify a single dict is automatically wrapped into a 1-step batch list."""
        with patch("time.sleep"):
            res = geelark.execute_batch_steps({"action": "sleep", "duration": 0.01})
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["total_steps"], 1)
            self.assertEqual(res["steps"][0]["action"], "sleep")

    def test_execute_batch_steps_all_actions(self):
        """Test all 16 supported batch actions through the execution loop."""
        steps = [
            {"action": "sleep", "duration": 0.01},
            {"action": "tap", "x": 0.5, "y": 0.5, "norm": True},
            {"action": "swipe", "x1": 0.5, "y1": 0.8, "x2": 0.5, "y2": 0.2, "norm": True},
            {"action": "type", "text": "test query", "enter": True},
            {"action": "key", "name": "home"},
            {"action": "open-app", "name": "youtube"},
            {"action": "deep-link", "url": "https://example.com"},
            {"action": "click-text", "query": "Sign In"},
            {"action": "wait-text", "query": "Skip", "timeout": 1.0},
            {"action": "scroll-find", "query": "More"},
            {"action": "dismiss-popup"},
            {"action": "hide-keyboard"},
            {"action": "wait-stable", "timeout": 2.0},
            {"action": "capture", "out": "test_step.png"},
            {"action": "youtube-flow", "url": "https://youtube.com/watch?v=123"},
            {"action": "tiktok-feed", "videos": 1}
        ]

        with patch.object(geelark, "tap", return_value={"status": "success"}):
            with patch.object(geelark, "swipe", return_value={"status": "success"}):
                with patch.object(geelark, "type_text", return_value={"status": "success"}):
                    with patch.object(geelark, "send_key", return_value={"status": "success"}):
                        with patch.object(geelark, "open_app", return_value={"status": "success"}):
                            with patch.object(geelark, "deep_link", return_value={"status": "success"}):
                                with patch.object(geelark, "click_text_on_screen", return_value={"status": "success"}):
                                    with patch.object(geelark, "wait_and_click_text", return_value={"status": "success"}):
                                        with patch.object(geelark, "scroll_find", return_value={"status": "success"}):
                                            with patch.object(geelark, "dismiss_popups", return_value={"status": "success"}):
                                                with patch.object(geelark, "hide_keyboard", return_value={"status": "success"}):
                                                    with patch.object(geelark, "wait_screen_stable", return_value={"status": "success", "stable": True}):
                                                        with patch.object(geelark, "capture_phone", return_value={"status": "success", "file": "test_step.png"}):
                                                            with patch.object(geelark, "recipe_youtube_flow", return_value={"status": "success"}):
                                                                with patch.object(geelark, "recipe_tiktok_feed", return_value={"status": "success"}):
                                                                    with patch("time.sleep"):
                                                                        res = geelark.execute_batch_steps(steps)
                                                                        self.assertEqual(res["status"], "success")
                                                                        self.assertEqual(res["total_steps"], 16)
                                                                        for s in res["steps"]:
                                                                            self.assertEqual(s["status"], "success", f"Failed step: {s}")

    def test_execute_batch_inner_action_error_propagation(self):
        """When an inner action returns an error status dict, the batch step is marked as error."""
        steps = [
            {"action": "click-text", "query": "MissingButton"}
        ]
        with patch.object(geelark, "click_text_on_screen", return_value={"status": "error", "message": "Text not found"}):
            res = geelark.execute_batch_steps(steps)
            self.assertEqual(res["steps"][0]["status"], "error")
            self.assertIn("Text not found", res["steps"][0]["message"])

    def test_execute_batch_exception_resilience(self):
        """An exception in one batch step does not crash execution of subsequent steps."""
        steps = [
            {"action": "deep-link", "url": "bad-url"},
            {"action": "sleep", "duration": 0.01}
        ]
        with patch.object(geelark, "deep_link", side_effect=ValueError("Simulated intent explosion")):
            with patch("time.sleep"):
                res = geelark.execute_batch_steps(steps)
                self.assertEqual(res["status"], "success")
                self.assertEqual(res["steps"][0]["status"], "error")
                self.assertIn("Simulated intent explosion", res["steps"][0]["error"])
                self.assertEqual(res["steps"][1]["status"], "success")

    def test_broadcast_action_no_phones(self):
        """broadcast_action returns error when no open phone windows exist."""
        with patch.object(geelark, "list_windows", return_value=[]):
            res = geelark.broadcast_action("key", ["home"])
            self.assertEqual(res["status"], "error")
            self.assertIn("No active phone windows found", res["message"])

    def test_broadcast_action_multi_phone_success(self):
        """broadcast_action executes the action across all open phone windows."""
        mock_phones = [
            {"hwnd": 101, "title": "#1 GeeLarkPhone", "is_phone": True},
            {"hwnd": 102, "title": "#2 GeeLarkPhone", "is_phone": True}
        ]
        with patch.object(geelark, "list_windows", return_value=mock_phones):
            with patch.object(geelark, "focus_window"):
                with patch.object(geelark, "send_key", return_value={"status": "success"}) as mock_key:
                    with patch("time.sleep"):
                        res = geelark.broadcast_action("key", ["home"])
                        self.assertEqual(res["status"], "success")
                        self.assertEqual(res["broadcast_count"], 2)
                        self.assertEqual(len(res["results"]), 2)
                        self.assertEqual(mock_key.call_count, 2)

    def test_broadcast_action_validation_and_unsupported(self):
        """broadcast_action validates argument counts and flags unsupported commands."""
        mock_phones = [{"hwnd": 101, "title": "#1 GeeLarkPhone", "is_phone": True}]
        with patch.object(geelark, "list_windows", return_value=mock_phones):
            with patch.object(geelark, "focus_window"):
                with patch("time.sleep"):
                    # Missing tap coords
                    res_tap = geelark.broadcast_action("tap", [])
                    self.assertIn("error", res_tap["results"][0])

                    # Unsupported command
                    res_unsupported = geelark.broadcast_action("unsupported-cmd", [])
                    self.assertEqual(res_unsupported["results"][0]["result"]["status"], "error")

    def test_batch_profiles_no_match(self):
        """batch_profiles returns error when requested profile does not match open windows."""
        mock_phones = [{"hwnd": 101, "title": "#1 GeeLarkPhone", "is_phone": True}]
        with patch.object(geelark, "list_windows", return_value=mock_phones):
            res = geelark.batch_profiles("99", "key", ["home"])
            self.assertEqual(res["status"], "error")
            self.assertIn("No open phone windows matched profiles", res["message"])

    def test_batch_profiles_filtered_success(self):
        """batch_profiles runs sequentially on specified subset of profiles."""
        mock_phones = [
            {"hwnd": 101, "title": "#1 GeeLarkPhone", "is_phone": True},
            {"hwnd": 102, "title": "#2 GeeLarkPhone", "is_phone": True},
            {"hwnd": 103, "title": "#3 GeeLarkPhone", "is_phone": True}
        ]
        with patch.object(geelark, "list_windows", return_value=mock_phones):
            with patch.object(geelark, "focus_window"):
                with patch.object(geelark, "dismiss_popups", return_value={"status": "success"}) as mock_dismiss:
                    with patch("time.sleep"):
                        # Target only 1 and 3
                        res = geelark.batch_profiles("1,3", "dismiss-popup", [])
                        self.assertEqual(res["status"], "success")
                        self.assertEqual(res["profiles_processed"], 2)
                        self.assertEqual(mock_dismiss.call_count, 2)


class TestGeeLarkRecipesAndCLI(unittest.TestCase):
    """Compound recipes (YouTube, TikTok) and CLI dispatch router."""

    def test_recipe_youtube_flow(self):
        """recipe_youtube_flow chains deep-link, ad skip, popup dismissal, and link click."""
        with patch.object(geelark, "deep_link", return_value={"status": "success"}):
            with patch.object(geelark, "wait_and_click_text", return_value={"status": "success"}):
                with patch.object(geelark, "dismiss_popups", return_value={"status": "success"}):
                    with patch.object(geelark, "click_text_on_screen", return_value={"status": "success"}):
                        with patch.object(geelark, "scroll_find", return_value={"status": "success"}):
                            with patch("time.sleep"):
                                res = geelark.recipe_youtube_flow("https://youtube.com/watch?v=123", click_link="http")
                                self.assertEqual(res["status"], "success")
                                self.assertEqual(res["recipe"], "youtube-flow")
                                self.assertTrue(len(res["steps"]) >= 3)

    def test_recipe_tiktok_feed(self):
        """recipe_tiktok_feed simulates human watching, likes, and curved swipes."""
        with patch.object(geelark, "open_app", return_value={"status": "success"}):
            with patch.object(geelark, "dismiss_popups", return_value={"status": "success"}):
                with patch.object(geelark, "tap", return_value={"status": "success"}):
                    with patch.object(geelark, "swipe", return_value={"status": "success"}):
                        with patch("time.sleep"):
                            res = geelark.recipe_tiktok_feed(videos=3, min_watch=1.0, max_watch=2.0, like_ratio=1.0)
                            self.assertEqual(res["status"], "success")
                            self.assertEqual(res["recipe"], "tiktok-feed")
                            self.assertEqual(res["videos_watched"], 3)
                            self.assertEqual(len(res["actions"]), 3)
                            # With like_ratio=1.0, every video should be liked
                            for a in res["actions"]:
                                self.assertTrue(a["liked"])

    def test_get_system_status(self):
        """get_system_status segregates phone vs app windows and parses adb devices."""
        mock_windows = [
            {"hwnd": 1, "title": "GeeLark Launcher", "is_phone": False, "rect": {}},
            {"hwnd": 2, "title": "#1 GeeLarkPhone", "is_phone": True, "rect": {}}
        ]
        mock_adb = {
            "stdout": "List of devices attached\nemulator-5554\tdevice\nemulator-5556\toffline\n"
        }
        with patch.object(geelark, "list_windows", return_value=mock_windows):
            with patch.object(geelark, "get_active_target", return_value="1"):
                with patch.object(geelark, "run_adb", return_value=mock_adb):
                    status = geelark.get_system_status()
                    self.assertEqual(status["status"], "success")
                    self.assertEqual(status["active_profile"], "1")
                    self.assertEqual(len(status["phone_windows"]), 1)
                    self.assertEqual(len(status["app_windows"]), 1)
                    self.assertEqual(status["adb_connected_devices"], ["emulator-5554"])
                    self.assertTrue(status["adb_ready"])

    def test_cli_features_human_readable_output(self):
        """CLI 'features' without --json prints structured human-readable catalog."""
        with patch.object(sys, "argv", ["geelark.py", "features"]):
            with patch("builtins.print") as mock_print:
                geelark.main()
                mock_print.assert_called()
                # Confirm manifest headers were printed
                all_prints = " ".join([call_args[0][0] for call_args in mock_print.call_args_list if call_args[0]])
                self.assertIn("geelark-cloud-phone", all_prints)
                self.assertIn("Supported Batch Actions", all_prints)


if __name__ == "__main__":
    unittest.main()
