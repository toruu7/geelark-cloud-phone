#!/usr/bin/env python3
"""Sanity checks for the unattended deployment files: the billing-safety settings must stay in place."""

import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class TestVpsFiles(unittest.TestCase):
    def test_service_has_billing_safety_and_correct_command(self):
        svc = read("deploy", "vps", "geelark-bulk.service")
        self.assertIn("bulk-run --only-cloud", svc)
        self.assertIn("KillMode=mixed", svc)                      # SIGTERM reaches the runner so it can stop phones
        self.assertRegex(svc, r"TimeoutStopSec=\d{3,}")           # ...and it gets time to do so
        self.assertIn("RuntimeMaxSec=", svc)                      # hard cap on a runaway pass
        self.assertIn("ExecStopPost=", svc)
        self.assertIn("bulk-cloud-stop", svc)
        self.assertIn("EnvironmentFile=/etc/geelark.env", svc)
        self.assertIn("NoNewPrivileges=true", svc)
        self.assertIn("Type=oneshot", svc)

    def test_timer_polls_and_targets_the_service(self):
        timer = read("deploy", "vps", "geelark-bulk.timer")
        self.assertIn("OnCalendar=", timer)
        self.assertIn("Unit=geelark-bulk.service", timer)

    def test_env_example_has_no_secrets(self):
        env = read("deploy", "vps", "geelark.env.example")
        for key in ("GEELARK_API_TOKEN", "GEELARK_SHEETS_URL", "GEELARK_SHEETS_SECRET"):
            self.assertRegex(env, rf"(?m)^{key}=$")                # present and empty

    @unittest.skipUnless(shutil.which("bash"), "bash not available")
    def test_install_script_syntax_and_safety(self):
        # forward slashes + cwd: Git Bash on Windows drops backslashes from native paths
        res = subprocess.run(["bash", "-n", "deploy/vps/install.sh"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(res.returncode, 0, res.stderr)
        sh = read("deploy", "vps", "install.sh")
        self.assertIn("set -euo pipefail", sh)
        self.assertIn("install -m 600", sh)                        # secrets file is not world readable
        self.assertIn("[ ! -f /etc/geelark.env ]", sh)             # never overwrites an existing config


class TestGithubWorkflow(unittest.TestCase):
    def setUp(self):
        self.wf = read("deploy", "github", "geelark-bulk.yml")

    def test_no_overlap_and_hard_cap(self):
        self.assertIn("concurrency:", self.wf)
        self.assertIn("cancel-in-progress: false", self.wf)
        self.assertRegex(self.wf, r"timeout-minutes: \d+")

    def test_cheap_probe_gates_the_expensive_steps(self):
        self.assertIn("bulk-run --only-cloud --probe", self.wf)
        self.assertGreaterEqual(self.wf.count("steps.probe.outputs.status == 'work'"), 3)

    def test_cleanup_always_runs(self):
        m = re.search(r"- name: Stop any cloud phone still running\n\s+if: (.+)\n\s+run: (.+)", self.wf)
        self.assertIsNotNone(m)
        self.assertIn("always()", m.group(1))
        self.assertIn("bulk-cloud-stop", m.group(2))

    def test_secrets_come_from_github_secrets_only(self):
        for name in ("GEELARK_API_TOKEN", "GEELARK_SHEETS_URL", "GEELARK_SHEETS_SECRET"):
            self.assertIn(f"{name}: ${{{{ secrets.{name} }}}}", self.wf)
        self.assertNotRegex(self.wf, r"script\.google\.com/macros/s/[A-Za-z0-9_\-]{20,}")
        self.assertNotIn("\t", self.wf)
        self.assertIn("contents: read", self.wf)                   # least privilege

    def test_cron_is_not_more_frequent_than_github_allows(self):
        m = re.search(r'cron: "\*/(\d+) ', self.wf)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 5)


class TestDocs(unittest.TestCase):
    def test_unattended_guide_covers_the_safety_story(self):
        doc = read("references", "unattended.md")
        for word in ("paused", "bulk-cloud-stop", "max_runtime_min", "STOP FAILED", "run_time", "report_email", "Routine", "Library", "Phones"):
            self.assertIn(word, doc)

    def test_skill_md_points_to_the_guide_and_stays_lean(self):
        text = read("SKILL.md")
        self.assertIn("references/unattended.md", text)
        self.assertLess(len(text.splitlines()), 200)


if __name__ == "__main__":
    unittest.main()
