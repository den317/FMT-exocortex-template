#!/usr/bin/env python3
"""Link an IWE WP context to exactly one GitHub issue.

# see DP.SC.NNN, DP.ROLE.NNN, WP-34

GitHub is the only API boundary. Linear receives the issue through its native
GitHub integration and is deliberately not called here.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ALLOWED_REPOS = {"DS-strategy", "IWE", "FMT-exocortex-template"}


class LinkError(RuntimeError):
    """A safe, user-actionable linkage failure."""


@dataclass(frozen=True)
class Context:
    path: Path
    wp: int
    title: str
    status: str
    github_issue: str
    github_repo: str


def read_frontmatter(path: Path) -> Context:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise LinkError(f"context has no YAML frontmatter: {path}")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise LinkError(f"context frontmatter is not closed: {path}")
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        match = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"')
    try:
        wp = int(values["wp"])
        title = values["title"]
    except (KeyError, ValueError) as exc:
        raise LinkError(f"context requires numeric wp and title: {path}") from exc
    return Context(
        path,
        wp,
        title,
        values.get("status", "pending"),
        values.get("github_issue", ""),
        values.get("github_repo", ""),
    )


def write_issue_url(context: Context, url: str) -> None:
    text = context.path.read_text(encoding="utf-8")
    replacement = f'github_issue: "{url}"'
    if re.search(r"^github_issue:", text, flags=re.MULTILINE):
        text = re.sub(r"^github_issue:.*$", replacement, text, count=1, flags=re.MULTILINE)
    else:
        text = text.replace("\n---\n", f"\n{replacement}\n---\n", 1)
    context.path.write_text(text, encoding="utf-8")


def write_repo(context: Context, repo: str) -> None:
    text = context.path.read_text(encoding="utf-8")
    replacement = f'github_repo: "{repo}"'
    if re.search(r"^github_repo:", text, flags=re.MULTILINE):
        text = re.sub(r"^github_repo:.*$", replacement, text, count=1, flags=re.MULTILINE)
    else:
        text = text.replace("\n---\n", f"\n{replacement}\n---\n", 1)
    context.path.write_text(text, encoding="utf-8")


def validate_repo(repo: str) -> str:
    name = repo.rsplit("/", 1)[-1]
    if name not in ALLOWED_REPOS or "/" not in repo:
        raise LinkError(f"owner-repository must be OWNER/{{{','.join(sorted(ALLOWED_REPOS))}}}: {repo}")
    return repo


def gh_json(args: list[str]) -> object:
    proc = subprocess.run(["gh", *args], check=False, text=True, capture_output=True)
    if proc.returncode:
        message = proc.stderr.strip() or proc.stdout.strip() or "unknown GitHub error"
        raise LinkError(f"GitHub unavailable: {message}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise LinkError(f"GitHub returned invalid JSON: {exc}") from exc


def matching_issues(repo: str, wp: int) -> list[dict[str, object]]:
    issues = gh_json([
        "issue", "list", "--repo", repo, "--state", "all", "--limit", "100",
        "--search", f'WP-{wp} in:title', "--json", "number,title,state,url",
    ])
    if not isinstance(issues, list):
        raise LinkError("GitHub issue list returned a non-list response")
    marker = re.compile(rf"^WP-{wp}(?:\s|:|$)")
    return [issue for issue in issues if marker.search(str(issue.get("title", "")))]


def issue_repo(url: str) -> str:
    match = re.match(r"^https://github\.com/([^/]+/[^/]+)/issues/\d+$", url)
    if not match:
        raise LinkError(f"invalid GitHub issue URL in context: {url}")
    return match.group(1)


def create_issue(context: Context, repo: str) -> str:
    repo = validate_repo(repo)
    if context.github_repo and context.github_repo != repo:
        raise LinkError(f"WRONG_REPO WP-{context.wp}: context points to {context.github_repo}, requested {repo}")
    if context.github_issue and issue_repo(context.github_issue) != repo:
        raise LinkError(f"WRONG_REPO WP-{context.wp}: context URL points to {issue_repo(context.github_issue)}, requested {repo}")
    matches = matching_issues(repo, context.wp)
    if len(matches) > 1:
        raise LinkError(f"DUPLICATE WP-{context.wp}: {len(matches)} issues in {repo}")
    if matches:
        url = str(matches[0]["url"])
        write_repo(context, repo)
        write_issue_url(context, url)
        return url
    context_reference = f"inbox/WP-{context.wp}/WP-{context.wp}.md"
    body = (
        f"## Рабочий продукт\n\n"
        f"**WP-ID:** WP-{context.wp}\n"
        f"**Источник истины:** `{context_reference}`\n\n"
        f"## Результат\n\n{context.title}\n\n"
        "Linear issue создаётся штатной интеграцией GitHub ↔ Linear."
    )
    proc = subprocess.run(
        ["gh", "issue", "create", "--repo", repo, "--title", f"WP-{context.wp} {context.title}", "--body", body],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode:
        raise LinkError(f"GitHub create failed: {proc.stderr.strip() or proc.stdout.strip()}")
    url = proc.stdout.strip()
    # GitHub has no idempotency key for issue creation. Reconcile immediately:
    # if a concurrent runner won the race, close only the issue created by this
    # process and keep the lowest-numbered canonical issue.
    reconciled = matching_issues(repo, context.wp)
    if len(reconciled) > 1:
        canonical = min(reconciled, key=lambda item: int(item["number"]))
        if url != canonical["url"]:
            created_number = url.rsplit("/", 1)[-1]
            close_proc = subprocess.run(
                ["gh", "issue", "close", created_number, "--repo", repo, "--reason", "not planned", "--comment", f"Duplicate created by concurrent WP-{context.wp} linkage; canonical issue: {canonical['url']}"],
                check=False, text=True, capture_output=True,
            )
            if close_proc.returncode:
                raise LinkError(
                    f"DUPLICATE WP-{context.wp}: reconciliation could not close {url}: "
                    f"{close_proc.stderr.strip() or close_proc.stdout.strip()}"
                )
        url = str(canonical["url"])
    write_repo(context, repo)
    write_issue_url(context, url)
    return url


def check_context(context: Context, repo: str) -> tuple[str, str]:
    repo = validate_repo(repo)
    if context.github_repo and context.github_repo != repo:
        return "WRONG_REPO", f"WP-{context.wp}: context points to {context.github_repo}, expected {repo}"
    if context.github_issue and issue_repo(context.github_issue) != repo:
        return "WRONG_REPO", f"WP-{context.wp}: context URL points to {issue_repo(context.github_issue)}, expected {repo}"
    matches = matching_issues(repo, context.wp)
    if len(matches) > 1:
        return "DUPLICATE", f"WP-{context.wp}: {len(matches)} issues in {repo}"
    if not matches:
        return "MISSING", f"WP-{context.wp}: no issue in {repo}"
    issue = matches[0]
    active = context.status not in {"done", "closed", "cancelled", "archived"}
    issue_open = issue.get("state") == "OPEN"
    if active != issue_open:
        return "STALE", f"WP-{context.wp}: context={context.status}, issue={issue.get('state')}"
    return "OK", f"WP-{context.wp}: {issue.get('url')}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "check"):
        command = sub.add_parser(name)
        command.add_argument("--context", type=Path, required=True)
        command.add_argument("--repo", required=True, help="GitHub OWNER/repository")
    audit = sub.add_parser("audit")
    audit.add_argument("--governance", type=Path, required=True)
    return parser


def audit_contexts(governance: Path) -> tuple[list[dict[str, str]], int]:
    results: list[dict[str, str]] = []
    pre_cutover = 0
    paths = list((governance / "inbox").glob("WP-*/WP-*.md"))
    paths.extend((governance / "archive" / "wp-contexts").glob("WP-*.md"))
    for path in sorted(set(paths)):
        raw = path.read_text(encoding="utf-8")
        if not re.search(r'^github_repo:\s*"?\S+', raw, flags=re.MULTILINE):
            pre_cutover += 1
            continue  # legacy IDs/schemas are not parsed or migrated implicitly
        context = read_frontmatter(path)
        if not context.github_repo:
            pre_cutover += 1
            continue  # migrate explicitly, never guess an owner
        status, detail = check_context(context, context.github_repo)
        results.append({"wp": f"WP-{context.wp}", "status": status, "detail": detail})
    return results, pre_cutover


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "audit":
            results, pre_cutover = audit_contexts(args.governance)
            print(json.dumps({"status": "OK" if all(item["status"] == "OK" for item in results) else "DRIFT", "pre_cutover": pre_cutover, "items": results}, ensure_ascii=False))
            return 0 if all(item["status"] == "OK" for item in results) else 1
        context = read_frontmatter(args.context)
        if args.command == "create":
            print(json.dumps({"status": "OK", "url": create_issue(context, args.repo)}, ensure_ascii=False))
            return 0
        status, detail = check_context(context, args.repo)
        print(json.dumps({"status": status, "detail": detail}, ensure_ascii=False))
        return 0 if status == "OK" else 1
    except LinkError as exc:
        print(json.dumps({"status": "UNAVAILABLE", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
