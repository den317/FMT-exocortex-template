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


def governance_fixture(directory: str) -> Path:
    governance = Path(directory) / "DS-strategy"
    (governance / "docs").mkdir(parents=True)
    (governance / "current").mkdir()
    (governance / "inbox" / "WP-34").mkdir(parents=True)
    (governance / "archive" / "wp-contexts").mkdir(parents=True)
    (governance / "docs" / "WP-REGISTRY.md").write_text(
        "| # | P | Название | Ст | Репо | Бюджет |\n|---|---|---|---|---|---|\n| 34 | P3 | **Связь** | ⏳ | DS-strategy | 1h |\n",
        encoding="utf-8",
    )
    context_file(str(governance / "inbox" / "WP-34"))
    (governance / "current" / "active-wp.md").write_text("before\n", encoding="utf-8")
    return governance


def issue(
    number: int, *, state: str = "OPEN", created: str = "2026-08-15T12:00:00Z"
) -> MODULE.Issue:
    return MODULE.Issue(
        number,
        f"Issue {number}",
        f"Body {number}",
        state,
        f"https://github.com/den317/DS-strategy/issues/{number}",
        created,
        "2026-08-15T13:00:00Z" if state == "CLOSED" else "",
        "den317/DS-strategy",
    )


class LinkTests(unittest.TestCase):
    def test_adopt_new_issue_creates_one_wp_without_github_create(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            governance = governance_fixture(directory)
            result = MODULE.adopt_issue(issue(21), governance)
            self.assertEqual(result["status"], "CREATED")
            context = governance / "inbox" / "WP-035" / "WP-035.md"
            self.assertIn(
                'github_issue: "https://github.com/den317/DS-strategy/issues/21"',
                context.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "| 35 |",
                (governance / "docs" / "WP-REGISTRY.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "| 35 | — | **Issue 21** |",
                (governance / "current" / "active-wp.md").read_text(encoding="utf-8"),
            )

    def test_repeat_adopt_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            governance = governance_fixture(directory)
            first = MODULE.adopt_issue(issue(21), governance)
            second = MODULE.adopt_issue(issue(21), governance)
            self.assertEqual(first["wp"], second["wp"])
            self.assertEqual(second["status"], "ALREADY_LINKED")

    def test_reconcile_multiple_issues_allocates_unique_wps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            governance = governance_fixture(directory)
            config = MODULE.AdoptionConfig(
                ("den317/DS-strategy",), "2026-08-15T10:00:00Z"
            )
            with patch.object(
                MODULE,
                "list_adoption_issues",
                return_value=[issue(21), issue(22), issue(23)],
            ):
                report = MODULE.reconcile(governance, config)
            self.assertEqual(
                [item["wp"] for item in report["created"]],
                ["WP-035", "WP-036", "WP-037"],
            )

    def test_closed_issue_is_adopted_as_closed_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            governance = governance_fixture(directory)
            MODULE.adopt_issue(issue(24, state="CLOSED"), governance)
            context = governance / "archive" / "wp-contexts" / "WP-035.md"
            self.assertIn("status: done", context.read_text(encoding="utf-8"))
            self.assertIn(
                "| ✅ |",
                (governance / "docs" / "WP-REGISTRY.md").read_text(encoding="utf-8"),
            )

    def test_linked_issue_close_archives_wp_without_questions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            governance = governance_fixture(directory)
            MODULE.adopt_issue(issue(21), governance)
            config = MODULE.AdoptionConfig(
                ("den317/DS-strategy",), "2026-08-15T10:00:00Z"
            )
            with patch.object(
                MODULE, "list_adoption_issues", return_value=[issue(21, state="CLOSED")]
            ):
                report = MODULE.reconcile(governance, config)
            self.assertEqual(report["closed"][0]["wp"], "WP-035")
            self.assertFalse(governance.joinpath("inbox/WP-035").exists())
            card = governance / "archive" / "wp-contexts" / "WP-035" / "WP-035.md"
            text = card.read_text(encoding="utf-8")
            self.assertIn("status: done", text)
            self.assertIn("closed_date: 2026-08-15", text)
            self.assertIn("closure_enrichment: pending", text)
            self.assertIn("GitHub Issue #21 закрыта", text)
            self.assertIn(
                "| ✅ |",
                (governance / "docs" / "WP-REGISTRY.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "DS-strategy/archive/wp-contexts/WP-035/",
                (governance / "docs" / "WP-REGISTRY.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "| ~~35~~ |",
                (governance / "current" / "active-wp.md").read_text(encoding="utf-8"),
            )

    def test_auto_close_postcondition_failure_rolls_back_move_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            governance = governance_fixture(directory)
            MODULE.adopt_issue(issue(21), governance)
            context = MODULE.read_frontmatter(
                governance / "inbox" / "WP-035" / "WP-035.md"
            )
            registry = governance / "docs" / "WP-REGISTRY.md"
            active = governance / "current" / "active-wp.md"
            registry_before = registry.read_bytes()
            active_before = active.read_bytes()
            with patch.object(
                MODULE,
                "rebuild_active",
                side_effect=lambda _: active.write_text("missing\n", encoding="utf-8"),
            ):
                with self.assertRaisesRegex(MODULE.LinkError, "INVALID_LOCAL_STATE"):
                    MODULE.auto_close_context(
                        context, issue(21, state="CLOSED"), governance
                    )
            card = governance / "inbox" / "WP-035" / "WP-035.md"
            self.assertTrue(card.exists())
            self.assertIn("status: pending", card.read_text(encoding="utf-8"))
            self.assertEqual(registry.read_bytes(), registry_before)
            self.assertEqual(active.read_bytes(), active_before)
            self.assertFalse(governance.joinpath("archive/wp-contexts/WP-035").exists())

    def test_pre_cutover_issue_is_not_listed(self) -> None:
        config = MODULE.AdoptionConfig(("den317/DS-strategy",), "2026-08-15T10:00:00Z")
        raw = [
            {
                "number": 20,
                "title": "old",
                "body": "",
                "state": "OPEN",
                "url": "https://github.com/den317/DS-strategy/issues/20",
                "createdAt": "2026-08-15T09:59:59Z",
            }
        ]
        with patch.object(MODULE, "gh_json", return_value=raw):
            self.assertEqual(MODULE.list_adoption_issues(config), [])

    def test_duplicate_local_links_are_conflict_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            governance = governance_fixture(directory)
            url = issue(21).url
            context_file(str(governance / "inbox" / "WP-34"), url=url)
            second = governance / "archive" / "wp-contexts" / "WP-33.md"
            second.write_text(
                f'---\nwp: 33\ntitle: "duplicate"\nstatus: done\ngithub_issue: "{url}"\ngithub_repo: "den317/DS-strategy"\n---\n',
                encoding="utf-8",
            )
            registry_before = (governance / "docs" / "WP-REGISTRY.md").read_text(
                encoding="utf-8"
            )
            config = MODULE.AdoptionConfig(
                ("den317/DS-strategy",), "2026-08-15T10:00:00Z"
            )
            with patch.object(MODULE, "list_adoption_issues", return_value=[issue(21)]):
                report = MODULE.reconcile(governance, config)
            self.assertEqual(report["status"], "CONFLICT")
            self.assertEqual(
                (governance / "docs" / "WP-REGISTRY.md").read_text(encoding="utf-8"),
                registry_before,
            )

    def test_github_unavailable_happens_before_local_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            governance = governance_fixture(directory)
            registry = governance / "docs" / "WP-REGISTRY.md"
            before = registry.read_text(encoding="utf-8")
            config = MODULE.AdoptionConfig(
                ("den317/DS-strategy",), "2026-08-15T10:00:00Z"
            )
            with patch.object(
                MODULE,
                "list_adoption_issues",
                side_effect=MODULE.LinkError("GitHub unavailable"),
            ):
                with self.assertRaises(MODULE.LinkError):
                    MODULE.reconcile(governance, config)
            self.assertEqual(registry.read_text(encoding="utf-8"), before)

    def test_missing_active_wp_postcondition_rolls_back_all_local_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            governance = governance_fixture(directory)
            registry = governance / "docs" / "WP-REGISTRY.md"
            active = governance / "current" / "active-wp.md"
            registry_before = registry.read_bytes()
            active_before = active.read_bytes()
            with patch.object(MODULE, "rebuild_active"):
                with self.assertRaisesRegex(MODULE.LinkError, "INVALID_LOCAL_STATE"):
                    MODULE.adopt_issue(issue(21), governance)
            self.assertEqual(registry.read_bytes(), registry_before)
            self.assertEqual(active.read_bytes(), active_before)
            self.assertFalse(governance.joinpath("inbox/WP-035").exists())

    def test_audit_reports_post_cutover_issue_without_wp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            governance = governance_fixture(directory)
            config = MODULE.AdoptionConfig(
                ("den317/DS-strategy",), "2026-08-15T10:00:00Z"
            )
            with patch.object(MODULE, "list_adoption_issues", return_value=[issue(21)]):
                report = MODULE.reconcile(governance, config, audit_only=True)
            self.assertEqual(report["status"], "DRIFT")
            self.assertEqual(report["missing"], [issue(21).url])

    def test_empty_adoption_scope_is_cleanly_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            params = Path(directory) / "params.yaml"
            params.write_text(
                'github_wp_adoption_repositories: []\ngithub_wp_adopt_from: ""\n',
                encoding="utf-8",
            )
            config = MODULE.read_adoption_config(params)
            report = MODULE.reconcile(Path(directory), config)
            self.assertEqual(report, {"status": "OK", "disabled": True, "created": []})

    def test_all_rituals_run_reconciliation_before_reasoning(self) -> None:
        template = SCRIPT.parents[1]
        ritual_paths = [
            template / ".claude/skills/day-open/SKILL.md",
            template / ".claude/skills/day-close/SKILL.md",
            template / ".claude/skills/week-close/SKILL.md",
            template / ".claude/skills/strategy-session/SKILL.md",
        ]
        for path in ritual_paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn('wp-github-link.py" reconcile', text, path)
            self.assertLess(
                text.index("reconcile --governance"),
                text.index("Extensions (before)"),
                path,
            )

    def test_create_reuses_exact_wp_issue_and_writes_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = context_file(directory)
            issue = {
                "number": 15,
                "title": "WP-34 Связь",
                "state": "OPEN",
                "url": "https://github.com/den317/DS-strategy/issues/15",
            }
            with patch.object(MODULE, "matching_issues", return_value=[issue]):
                url = MODULE.create_issue(
                    MODULE.read_frontmatter(path), "den317/DS-strategy"
                )
            self.assertEqual(url, issue["url"])
            self.assertIn(f'github_issue: "{url}"', path.read_text(encoding="utf-8"))

    def test_create_blocks_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = MODULE.read_frontmatter(context_file(directory))
            with patch.object(
                MODULE, "matching_issues", return_value=[{"url": "a"}, {"url": "b"}]
            ):
                with self.assertRaisesRegex(MODULE.LinkError, "DUPLICATE"):
                    MODULE.create_issue(context, "den317/DS-strategy")

    def test_create_blocks_existing_wrong_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = context_file(
                directory, url="https://github.com/den317/IWE/issues/29"
            )
            context = MODULE.read_frontmatter(path)
            with self.assertRaisesRegex(MODULE.LinkError, "WRONG_REPO"):
                MODULE.create_issue(context, "den317/DS-strategy")

    def test_check_detects_stale_active_wp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = MODULE.read_frontmatter(context_file(directory))
            issue = {
                "title": "WP-34 Связь",
                "state": "CLOSED",
                "url": "https://github.com/den317/DS-strategy/issues/15",
            }
            with patch.object(MODULE, "matching_issues", return_value=[issue]):
                status, _ = MODULE.check_context(context, "den317/DS-strategy")
            self.assertEqual(status, "STALE")

    def test_check_uses_saved_identity_when_issue_was_renamed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            url = "https://github.com/den317/DS-strategy/issues/29"
            context = MODULE.read_frontmatter(context_file(directory, url=url))
            renamed = {
                "number": 29,
                "title": "Renamed many times without WP marker",
                "state": "CLOSED",
                "url": url,
            }
            with (
                patch.object(MODULE, "gh_json", return_value=renamed) as github,
                patch.object(MODULE, "matching_issues") as title_search,
            ):
                status, detail = MODULE.check_context(context, "den317/DS-strategy")
            self.assertEqual(status, "STALE")
            self.assertIn("issue=CLOSED", detail)
            github.assert_called_once_with(
                [
                    "issue",
                    "view",
                    "29",
                    "--repo",
                    "den317/DS-strategy",
                    "--json",
                    "number,title,state,url",
                ]
            )
            title_search.assert_not_called()

    def test_check_detects_wrong_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = context_file(
                directory, url="https://github.com/den317/IWE/issues/29"
            )
            context = MODULE.read_frontmatter(path)
            issue = {
                "title": "WP-34 Связь",
                "state": "OPEN",
                "url": "https://github.com/den317/DS-strategy/issues/15",
            }
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
            archive = governance / "archive" / "wp-contexts" / "WP-33"
            archive.mkdir(parents=True)
            (archive / "WP-33.md").write_text(
                '---\nwp: 33\ntitle: "Старый"\nstatus: done\n---\n# WP-33\n',
                encoding="utf-8",
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
                {
                    "number": 15,
                    "title": "WP-34 Связь",
                    "state": "OPEN",
                    "url": "https://github.com/den317/DS-strategy/issues/15",
                },
                {"number": 16, "title": "WP-34 Связь", "state": "OPEN", "url": created},
            ]
            create_result = subprocess.CompletedProcess(
                [], 0, stdout=created + "\n", stderr=""
            )
            close_failure = subprocess.CompletedProcess(
                [], 1, stdout="", stderr="denied"
            )
            with (
                patch.object(MODULE, "matching_issues", side_effect=[[], issues]),
                patch.object(
                    MODULE.subprocess, "run", side_effect=[create_result, close_failure]
                ),
            ):
                with self.assertRaisesRegex(
                    MODULE.LinkError, "reconciliation could not close"
                ):
                    MODULE.create_issue(context, "den317/DS-strategy")


if __name__ == "__main__":
    unittest.main()
