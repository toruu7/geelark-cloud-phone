#!/usr/bin/env python3
"""The unattended cloud agent gets its skills from the repository it clones (.claude/skills).
These tests keep that package complete, safe, and consistent with the runner."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import gl_cloudadb
import sync_cloud_adb

SKILLS = os.path.join(ROOT, ".claude", "skills")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "missing frontmatter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)


class TestVendoredSkill(unittest.TestCase):
    def test_vendored_files_present(self):
        base = os.path.join(SKILLS, "geelark-cloud-adb")
        for rel in ("SKILL.md", "README.md", "LICENSE", "UPSTREAM.txt", os.path.join("scripts", "geelark_adb.py")):
            self.assertTrue(os.path.isfile(os.path.join(base, rel)), rel)

    def test_skill_name_matches_folder(self):
        self.assertEqual(frontmatter(read(".claude", "skills", "geelark-cloud-adb", "SKILL.md"))["name"], "geelark-cloud-adb")

    def test_upstream_note_has_a_commit(self):
        self.assertRegex(read(".claude", "skills", "geelark-cloud-adb", "UPSTREAM.txt"), r"commit: [0-9a-f]{40}")

    def test_vendored_cli_has_the_commands_the_agent_uses(self):
        src = read(".claude", "skills", "geelark-cloud-adb", "scripts", "geelark_adb.py")
        for cmd in ('"up"', '"down"', '"shot"', '"ui"', '"focus"'):
            self.assertIn(cmd, src)

    def test_vendored_cli_runs(self):
        out = subprocess.run([sys.executable, os.path.join(SKILLS, "geelark-cloud-adb", "scripts", "geelark_adb.py"), "--help"],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("up", out.stdout)


class TestOperatorSkill(unittest.TestCase):
    def setUp(self):
        self.text = read(".claude", "skills", "geelark-daily-operator", "SKILL.md")

    def test_frontmatter(self):
        fm = frontmatter(self.text)
        self.assertEqual(fm["name"], "geelark-daily-operator")
        self.assertIn("unattended", fm["description"])

    def test_safety_rules_stay_in_place(self):
        for phrase in ("never ask for confirmation", "Never like, follow", "Never print", "Run the runner **once**",
                       "every phone stopped", "may still be billing"):
            self.assertIn(phrase, self.text, phrase)

    def test_references_real_commands(self):
        for cmd in ("bulk-run --only-cloud --probe", "bulk-run --only-cloud", "bulk-cloud-stop", "geelark_adb.py up --id",
                    "geelark_adb.py down --id"):
            self.assertIn(cmd, self.text, cmd)
        helped = subprocess.run([sys.executable, os.path.join(SCRIPTS, "geelark.py"), "bulk-run", "--help"], capture_output=True, text=True, timeout=60).stdout
        for flag in ("--only-cloud", "--probe"):
            self.assertIn(flag, helped)
        sub = subprocess.run([sys.executable, os.path.join(SCRIPTS, "geelark.py"), "--help"], capture_output=True, text=True, timeout=60).stdout
        self.assertIn("bulk-cloud-stop", sub)

    def test_mentions_only_the_three_required_variables(self):
        for name in ("GEELARK_API_TOKEN", "GEELARK_SHEETS_URL", "GEELARK_SHEETS_SECRET"):
            self.assertIn(name, self.text)
        self.assertNotRegex(self.text, r"script\.google\.com/macros/s/[A-Za-z0-9_\-]{20,}")

    def test_the_skill_stays_short_enough_to_follow(self):
        self.assertLess(len(self.text.splitlines()), 80)


class TestRunnerFindsVendoredScript(unittest.TestCase):
    def test_vendored_copy_is_preferred_over_siblings_and_home(self):
        vendored = os.path.join(ROOT, ".claude", "skills", "geelark-cloud-adb", "scripts", "geelark_adb.py")
        with patch.dict(os.environ, {"GEELARK_CLOUD_ADB": ""}), patch("os.path.isfile", return_value=True):
            self.assertEqual(os.path.normcase(gl_cloudadb.find_script()), os.path.normcase(vendored))

    def test_explicit_env_override_still_wins(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "geelark_adb.py")
            open(f, "w").close()
            with patch.dict(os.environ, {"GEELARK_CLOUD_ADB": f}):
                self.assertEqual(gl_cloudadb.find_script(), f)

    def test_vendored_path_is_inside_this_repo_so_one_clone_is_enough(self):
        with patch.dict(os.environ, {"GEELARK_CLOUD_ADB": ""}):
            found = gl_cloudadb.find_script()
        self.assertTrue(os.path.abspath(found).startswith(os.path.abspath(ROOT)), found)


class TestSync(unittest.TestCase):
    def _src(self, d, marker="v1"):
        os.makedirs(os.path.join(d, "scripts"))
        for rel in sync_cloud_adb.FILES:
            with open(os.path.join(d, rel), "w", encoding="utf-8", newline="\n") as f:
                f.write(f"{rel} {marker}\n")

    def test_local_sync_copies_then_reports_no_change(self):
        with tempfile.TemporaryDirectory() as s, tempfile.TemporaryDirectory() as dest:
            self._src(s)
            changed, commit = sync_cloud_adb.sync_from_local(s, dest)
            self.assertEqual(set(changed), set(sync_cloud_adb.FILES) | {"UPSTREAM.txt"})
            again, _ = sync_cloud_adb.sync_from_local(s, dest)
            self.assertEqual(again, [])

    def test_local_sync_detects_a_single_changed_file(self):
        with tempfile.TemporaryDirectory() as s, tempfile.TemporaryDirectory() as dest:
            self._src(s)
            sync_cloud_adb.sync_from_local(s, dest)
            with open(os.path.join(s, "SKILL.md"), "w", encoding="utf-8", newline="\n") as f:
                f.write("SKILL.md v2\n")
            changed, _ = sync_cloud_adb.sync_from_local(s, dest)
            self.assertEqual(changed, ["SKILL.md"])

    def test_github_sync_pins_the_commit_and_uses_it_for_every_file(self):
        urls = []

        def fake(url):
            urls.append(url)
            if "/commits/" in url:
                return json.dumps({"sha": "a" * 40}).encode()
            return b"data\r\n"                                     # CRLF from a Windows-side fetch is normalized
        with tempfile.TemporaryDirectory() as dest:
            changed, commit = sync_cloud_adb.sync_from_github("main", dest, fetch=fake)
            self.assertEqual(commit, "a" * 40)
            raw = [u for u in urls if "raw.githubusercontent.com" in u]
            self.assertEqual(len(raw), len(sync_cloud_adb.FILES))
            self.assertTrue(all("/" + "a" * 40 + "/" in u for u in raw))   # fetched at the pinned sha, not a moving branch
            with open(os.path.join(dest, "SKILL.md"), "rb") as f:
                self.assertEqual(f.read(), b"data\n")
            self.assertIn("a" * 40, open(os.path.join(dest, "UPSTREAM.txt")).read())

    def test_vendored_copy_has_no_crlf(self):
        for rel in ("SKILL.md", os.path.join("scripts", "geelark_adb.py"), "UPSTREAM.txt"):
            with open(os.path.join(SKILLS, "geelark-cloud-adb", rel), "rb") as f:
                self.assertNotIn(b"\r\n", f.read(), rel)


class TestRoutinePrompt(unittest.TestCase):
    def test_prompt_is_self_contained_and_secret_free(self):
        text = read("deploy", "claude-routine", "prompt.txt")
        self.assertIn(".claude/skills/geelark-daily-operator/SKILL.md", text)
        self.assertIn("follow it exactly", text)
        self.assertNotRegex(text, r"(?i)(token|secret)\s*[:=]\s*\S{12,}")
        self.assertLess(len(text), 1200)


if __name__ == "__main__":
    unittest.main()
