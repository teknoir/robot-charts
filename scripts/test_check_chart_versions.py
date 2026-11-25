#!/usr/bin/env python3
"""Unit tests for scripts/check_chart_versions.py.

Each test builds a throwaway git repo with a gh-pages branch holding
index.yaml and local refs/remotes/origin/* refs, so no network is used.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name("check_chart_versions.py")

CHART = """\
apiVersion: v2
name: {name}
description: test chart
type: application
version: {version}
"""


def chart_yaml(name: str, version: str) -> str:
    return CHART.format(name=name, version=version)


def index_yaml(entries: dict) -> str:
    if not entries:
        body = "  {}"
    else:
        lines = []
        for name, version in entries.items():
            lines.extend(
                [
                    f"  {name}:",
                    "  - apiVersion: v2",
                    f"    name: {name}",
                    f'    version: "{version}"',
                    '    created: "2026-01-01T00:00:00.000000000Z"',
                ]
            )
        body = "\n".join(lines)
    return f'apiVersion: v1\nentries:\n{body}\ngenerated: "2026-01-01T00:00:00Z"\n'


class TempRepo:
    """A temporary git repo with main, gh-pages and origin/* refs."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.git("init", "-b", "main")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed:\n{proc.stderr}")
        return proc

    def write(self, rel: str, content: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def set_remote_ref(self, remote_branch: str, rev: str = "HEAD") -> None:
        sha = self.git("rev-parse", rev).stdout.strip()
        self.git("update-ref", f"refs/remotes/origin/{remote_branch}", sha)

    def delete_remote_ref(self, remote_branch: str) -> None:
        self.git("update-ref", "-d", f"refs/remotes/origin/{remote_branch}")

    def run(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        child_env = dict(os.environ)
        child_env.pop("GITHUB_BASE_REF", None)
        if env:
            child_env.update(env)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.root,
            env=child_env,
            capture_output=True,
            text=True,
        )

    def seed(self, index_entries: dict | None = None) -> str:
        """Build the base commit, a gh-pages index and origin refs; return the base sha."""
        self.write("README.md", "# robot-charts\n")
        self.write("charts/foo/Chart.yaml", chart_yaml("foo", "0.1.0"))
        self.write("charts/foo/templates/configmap.yaml", "kind: ConfigMap\nmetadata:\n  name: foo\n")
        self.write("charts/bar/Chart.yaml", chart_yaml("bar", "0.1.0"))
        self.write("charts/bar/templates/configmap.yaml", "kind: ConfigMap\nmetadata:\n  name: bar\n")
        base = self.commit("base")
        self.git("checkout", "-b", "gh-pages")
        self.write("index.yaml", index_yaml({} if index_entries is None else index_entries))
        self.commit("index")
        self.git("checkout", "main")
        self.set_remote_ref("main", "main")
        self.set_remote_ref("gh-pages", "gh-pages")
        return base


class CheckChartVersionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = TempRepo(self.tmp.name)
        self.base = self.repo.seed({"foo": "0.1.0"})

    def test_no_change(self) -> None:
        result = self.repo.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no chart changes", result.stdout)

    def test_changed_chart_with_new_version(self) -> None:
        self.repo.write("charts/foo/Chart.yaml", chart_yaml("foo", "0.2.0"))
        self.repo.write("charts/foo/templates/configmap.yaml", "kind: ConfigMap\nmetadata:\n  name: foo2\n")
        self.repo.commit("bump foo")
        result = self.repo.run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ok charts/foo 0.2.0", result.stdout)

    def test_changed_chart_same_version_already_published(self) -> None:
        self.repo.write("charts/foo/templates/configmap.yaml", "kind: ConfigMap\nmetadata:\n  name: foo2\n")
        self.repo.commit("change foo without bump")
        result = self.repo.run()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("already published", result.stdout)
        self.assertIn("charts/foo", result.stdout)
        self.assertIn("did not change", result.stdout)

    def test_readme_change_outside_charts(self) -> None:
        self.repo.write("README.md", "# robot-charts\n\nmore docs\n")
        self.repo.commit("docs")
        result = self.repo.run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_deleted_chart(self) -> None:
        self.repo.git("rm", "-r", "charts/foo")
        self.repo.commit("delete foo")
        result = self.repo.run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_name_dir_mismatch(self) -> None:
        self.repo.write("charts/foo/Chart.yaml", chart_yaml("wrong", "0.2.0"))
        self.repo.commit("rename chart")
        result = self.repo.run()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("must be named after the chart", result.stdout)

    def test_missing_gh_pages_ref(self) -> None:
        self.repo.delete_remote_ref("gh-pages")
        result = self.repo.run()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("gh-pages", result.stderr)

    def test_two_charts_changed_one_bad(self) -> None:
        self.repo.write("charts/foo/templates/configmap.yaml", "kind: ConfigMap\nmetadata:\n  name: foo2\n")
        self.repo.write("charts/bar/Chart.yaml", chart_yaml("bar", "0.2.0"))
        self.repo.commit("touch both")
        result = self.repo.run()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("charts/foo", result.stdout)
        self.assertIn("already published", result.stdout)
        self.assertIn("ok charts/bar 0.2.0", result.stdout)

    def test_github_base_ref_env(self) -> None:
        self.repo.git("branch", "release", self.base)
        self.repo.set_remote_ref("release", "release")
        self.repo.delete_remote_ref("main")
        self.repo.write("charts/foo/Chart.yaml", chart_yaml("foo", "0.2.0"))
        self.repo.commit("bump foo")
        result = self.repo.run(env={"GITHUB_BASE_REF": "release"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("origin/release", result.stdout)
        self.assertIn("ok charts/foo 0.2.0", result.stdout)


if __name__ == "__main__":
    unittest.main()
