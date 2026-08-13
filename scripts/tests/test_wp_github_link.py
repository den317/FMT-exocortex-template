#!/usr/bin/env python3
"""Unit tests for wp-github-link.py."""

from __future__ import annotations

import importlib.util
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "wp-github-link.py"
SPEC = importlib.util.spec_from_file_location("wp_github_link", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def context_file(directory: str, *, status: str = "pending", url: str = "") -> Path:
    path = Path(directory) / "WP-34.md"
    path.write_text(
        f'---\nwp: 34\ntitle: "Связь"\nstatus: {status}\ngithub_issue: "{url}"\ngithub_repo: "den317/DS-strategy"\n---\n# WP-34\n',
        encoding="utf-8",
    )
    return path


class LinkTests(unittest.TestCase):
    def test_create_reuses_exact_wp_issue_and_writes_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = context_file(directory)
            issue = {"number": 15, "title": "WP-34 Связь", "state": "OPEN", "url": "https://github.com/den317/DS-strategy/issues/15"}
            with patch.object(MODULE, "matching_issues", return_value=[issue]):
                url = MODULE.create_issue(MODULE.read_frontmatter(path), "den317/DS-strategy")
            self.assertEqual(url, issue["url"])
            self.assertIn(f'github_issue: "{url}"', path.read_text(encoding="utf-8"))

    def test_create_blocks_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = MODULE.read_frontmatter(context_file(directory))
            with patch.object(MODULE, "matching_issues", return_value=[{"url": "a"}, {"url": "b"}]):
                with self.assertRaisesRegex(MODULE.LinkError, "DUPLICATE"):
                    MODULE.create_issue(context, "den317/DS-strategy")

    def test_create_blocks_existing_wrong_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = context_file(directory, url="https://github.com/den317/IWE/issues/29")
            context = MODULE.read_frontmatter(path)
            with self.assertRaisesRegex(MODULE.LinkError, "WRONG_REPO"):
                MODULE.create_issue(context, "den317/DS-strategy")

    def test_check_detects_stale_active_wp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = MODULE.read_frontmatter(context_file(directory))
            issue = {"title": "WP-34 Связь", "state": "CLOSED", "url": "https://github.com/den317/DS-strategy/issues/15"}
            with patch.object(MODULE, "matching_issues", return_value=[issue]):
                status, _ = MODULE.check_context(context, "den317/DS-strategy")
            self.assertEqual(status, "STALE")

    def test_check_detects_wrong_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = context_file(directory, url="https://github.com/den317/IWE/issues/29")
            context = MODULE.read_frontmatter(path)
            issue = {"title": "WP-34 Связь", "state": "OPEN", "url": "https://github.com/den317/DS-strategy/issues/15"}
            with patch.object(MODULE, "matching_issues", return_value=[issue]):
                status, _ = MODULE.check_context(context, "den317/DS-strategy")
            self.assertEqual(status, "WRONG_REPO")

    def test_repo_allowlist_blocks_unknown_repository(self) -> None:
        with self.assertRaises(MODULE.LinkError):
            MODULE.validate_repo("den317/unknown")

    def test_audit_includes_archive_and_counts_pre_cutover(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            governance = Path(directory)
            inbox = governance / "inbox" / "WP-34"
            inbox.mkdir(parents=True)
            context_file(str(inbox))
            archive = governance / "archive" / "wp-contexts"
            archive.mkdir(parents=True)
            (archive / "WP-33.md").write_text(
                '---\nwp: 33\ntitle: "Старый"\nstatus: done\n---\n# WP-33\n', encoding="utf-8"
            )
            with patch.object(MODULE, "check_context", return_value=("OK", "linked")):
                results, pre_cutover = MODULE.audit_contexts(governance)
            self.assertEqual(len(results), 1)
            self.assertEqual(pre_cutover, 1)

    def test_invalid_json_becomes_link_error(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="not-json", stderr="")
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(MODULE.LinkError, "invalid JSON"):
                MODULE.gh_json(["issue", "list"])

    def test_reconciliation_close_failure_is_not_reported_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = MODULE.read_frontmatter(context_file(directory))
            created = "https://github.com/den317/DS-strategy/issues/16"
            issues = [
                {"number": 15, "title": "WP-34 Связь", "state": "OPEN", "url": "https://github.com/den317/DS-strategy/issues/15"},
                {"number": 16, "title": "WP-34 Связь", "state": "OPEN", "url": created},
            ]
            create_result = subprocess.CompletedProcess([], 0, stdout=created + "\n", stderr="")
            close_failure = subprocess.CompletedProcess([], 1, stdout="", stderr="denied")
            with patch.object(MODULE, "matching_issues", side_effect=[[], issues]), patch.object(
                MODULE.subprocess, "run", side_effect=[create_result, close_failure]
            ):
                with self.assertRaisesRegex(MODULE.LinkError, "reconciliation could not close"):
                    MODULE.create_issue(context, "den317/DS-strategy")


if __name__ == "__main__":
    unittest.main()
