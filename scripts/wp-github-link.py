#!/usr/bin/env python3
"""Link an IWE WP context to exactly one GitHub issue.

# see DP.SC.NNN, DP.ROLE.NNN, WP-34

GitHub is the only API boundary. Linear receives the issue through its native
GitHub integration and is deliberately not called here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    state: str
    url: str
    created_at: str
    repository: str


@dataclass(frozen=True)
class AdoptionConfig:
    repositories: tuple[str, ...]
    adopt_from: str


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
        text = re.sub(
            r"^github_issue:.*$", replacement, text, count=1, flags=re.MULTILINE
        )
    else:
        text = text.replace("\n---\n", f"\n{replacement}\n---\n", 1)
    context.path.write_text(text, encoding="utf-8")


def write_repo(context: Context, repo: str) -> None:
    text = context.path.read_text(encoding="utf-8")
    replacement = f'github_repo: "{repo}"'
    if re.search(r"^github_repo:", text, flags=re.MULTILINE):
        text = re.sub(
            r"^github_repo:.*$", replacement, text, count=1, flags=re.MULTILINE
        )
    else:
        text = text.replace("\n---\n", f"\n{replacement}\n---\n", 1)
    context.path.write_text(text, encoding="utf-8")


def validate_repo(repo: str) -> str:
    name = repo.rsplit("/", 1)[-1]
    if name not in ALLOWED_REPOS or "/" not in repo:
        raise LinkError(
            f"owner-repository must be OWNER/{{{','.join(sorted(ALLOWED_REPOS))}}}: {repo}"
        )
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


def parse_issue(raw: object, repository: str) -> Issue:
    if not isinstance(raw, dict):
        raise LinkError("GitHub issue is not an object")
    try:
        number = int(raw["number"])
        title = str(raw["title"]).strip()
        state = str(raw["state"]).upper()
        url = str(raw["url"])
        created_at = str(raw["createdAt"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LinkError(f"invalid GitHub issue payload: {raw!r}") from exc
    if not title or state not in {"OPEN", "CLOSED"}:
        raise LinkError(f"invalid GitHub issue #{number}: title/state")
    if issue_repo(url) != repository:
        raise LinkError(f"invalid GitHub issue #{number}: URL repository mismatch")
    try:
        dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LinkError(f"invalid GitHub issue #{number}: createdAt") from exc
    return Issue(
        number, title, str(raw.get("body") or ""), state, url, created_at, repository
    )


def read_adoption_config(path: Path) -> AdoptionConfig:
    text = path.read_text(encoding="utf-8")
    cutover = re.search(
        r'^github_wp_adopt_from:\s*["\']?([^"\'\n]+)', text, re.MULTILINE
    )
    header = re.search(r"^github_wp_adoption_repositories:\s*$", text, re.MULTILINE)
    repositories: list[str] = []
    if header:
        for line in text[header.end() :].splitlines():
            match = re.match(r'^\s+-\s*["\']?([^"\'\n]+)', line)
            if not match:
                if line.strip() and not line.startswith((" ", "\t", "#")):
                    break
                continue
            repositories.append(match.group(1).strip())
    if not repositories:
        return AdoptionConfig((), "")
    if not cutover:
        raise LinkError(
            "INVALID_CONFIG: adoption cutover is required when repositories are configured"
        )
    for repo in repositories:
        validate_repo(repo)
    try:
        dt.datetime.fromisoformat(cutover.group(1).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise LinkError(
            "INVALID_CONFIG: github_wp_adopt_from must be ISO-8601"
        ) from exc
    return AdoptionConfig(tuple(repositories), cutover.group(1).strip())


def list_adoption_issues(config: AdoptionConfig) -> list[Issue]:
    issues: list[Issue] = []
    cutover = dt.datetime.fromisoformat(config.adopt_from.replace("Z", "+00:00"))
    for repo in config.repositories:
        raw = gh_json(
            [
                "issue",
                "list",
                "--repo",
                repo,
                "--state",
                "all",
                "--limit",
                "1000",
                "--search",
                f"created:>={config.adopt_from[:10]}",
                "--json",
                "number,title,body,state,url,createdAt",
            ]
        )
        if not isinstance(raw, list):
            raise LinkError("GitHub issue list returned a non-list response")
        for item in raw:
            issue = parse_issue(item, repo)
            created = dt.datetime.fromisoformat(issue.created_at.replace("Z", "+00:00"))
            if created >= cutover:
                issues.append(issue)
    return sorted(
        issues, key=lambda item: (item.created_at, item.repository, item.number)
    )


def context_paths(governance: Path) -> list[Path]:
    paths = list((governance / "inbox").glob("WP-*/WP-*.md"))
    paths.extend((governance / "archive" / "wp-contexts").glob("WP-*.md"))
    paths.extend((governance / "archive" / "wp-contexts").glob("WP-*/WP-*.md"))
    return sorted(set(paths))


def links_by_url(governance: Path) -> dict[str, list[Context]]:
    links: dict[str, list[Context]] = {}
    for path in context_paths(governance):
        try:
            context = read_frontmatter(path)
        except LinkError:
            continue
        if context.github_issue:
            links.setdefault(context.github_issue, []).append(context)
    return links


def next_wp(registry: Path) -> int:
    numbers = [
        int(value)
        for value in re.findall(
            r"^\|\s*[*~]*(?:WP-)?(\d+)",
            registry.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    ]
    if not numbers:
        raise LinkError("WP Registry contains no WP rows")
    return max(numbers) + 1


def registry_row(registry: Path, wp: int, title: str, status: str) -> None:
    lines = registry.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if (
            line.lstrip().startswith("|---")
            and index
            and lines[index - 1].lstrip().startswith("| #")
        ):
            headers = [
                cell.strip() for cell in lines[index - 1].strip().strip("|").split("|")
            ]
            aliases = {
                "Приоритет": "P",
                "Статус": "Ст",
                "Репозитории": "Репо",
                "Репозиторий": "Репо",
            }
            safe_title = title.replace("|", "\\|")
            governance = registry.parents[1].name
            location = (
                f"archive/wp-contexts/WP-{wp:03d}.md"
                if status == "✅"
                else f"inbox/WP-{wp:03d}/"
            )
            values = {
                "#": str(wp),
                "P": "—",
                "Название": f"**{safe_title}**",
                "Ст": status,
                "Репо": f"{governance}/{location}",
                "Бюджет": "TBD",
            }
            cells = [values.get(aliases.get(name, name), "—") for name in headers]
            lines.insert(index + 1, "| " + " | ".join(cells) + " |\n")
            registry.write_text("".join(lines), encoding="utf-8")
            return
    raise LinkError("WP Registry table header not found")


def render_adopted_context(issue: Issue, wp: int) -> str:
    local_status = "done" if issue.state == "CLOSED" else "pending"
    body = issue.body.strip() or "Описание в GitHub Issue отсутствует."
    return f'''---
wp: {wp}
title: "{issue.title.replace(chr(34), chr(39))}"
status: {local_status}
priority: TBD
budget: TBD
created: {issue.created_at[:10]}
last_session: {issue.created_at[:10]}
related: []
hypothesis: "—"
hypothesis_relation: "operational"
activation: on-demand
github_issue: "{issue.url}"
github_repo: "{issue.repository}"
---

# WP-{wp:03d}: {issue.title}

## Проблема

{body}

## Артефакт

Выполнена работа по GitHub Issue #{issue.number} — {issue.title}.

## Связки с РП

| РП | Сила | Тип | Что передаётся |
|----|------|-----|----------------|
| — | — | — | нет связок |

## Фазы реализации

- [{"x" if issue.state == "CLOSED" else " "}] Выполнить работу, описанную в GitHub Issue #{issue.number}.

## Осталось

**Следующий шаг:** {"Работа уже закрыта во внешней Issue." if issue.state == "CLOSED" else "Уточнить выполнение по исходной GitHub Issue."}
'''


def rebuild_active(governance: Path) -> None:
    script = Path(__file__).with_name("build-active-wp.py")
    env = os.environ.copy()
    env["IWE_ROOT"] = str(governance.parent)
    env["IWE_GOVERNANCE_REPO"] = governance.name
    proc = subprocess.run(
        [sys.executable, str(script)],
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode:
        raise LinkError(
            f"active-wp rebuild failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )


def require_active_wp(active: Path, wp: int) -> None:
    if not active.exists():
        raise LinkError(
            f"INVALID_LOCAL_STATE: active-wp was not created for WP-{wp:03d}"
        )
    marker = re.compile(
        rf"^\|\s*(?:~~)?(?:\*\*)?(?:WP-)?0*{wp}(?:[-.]\w+)?(?:\*\*)?(?:~~)?\s*\|",
        re.MULTILINE,
    )
    if not marker.search(active.read_text(encoding="utf-8")):
        raise LinkError(f"INVALID_LOCAL_STATE: WP-{wp:03d} missing from active-wp")


def adopt_issue(issue: Issue, governance: Path) -> dict[str, object]:
    existing = links_by_url(governance).get(issue.url, [])
    if len(existing) > 1:
        raise LinkError(f"CONFLICT: {issue.url} is linked by {len(existing)} WPs")
    if existing:
        return {
            "status": "ALREADY_LINKED",
            "wp": f"WP-{existing[0].wp:03d}",
            "url": issue.url,
        }
    registry = governance / "docs" / "WP-REGISTRY.md"
    active = governance / "current" / "active-wp.md"
    wp = next_wp(registry)
    closed = issue.state == "CLOSED"
    path = (
        (governance / "archive" / "wp-contexts" / f"WP-{wp:03d}.md")
        if closed
        else (governance / "inbox" / f"WP-{wp:03d}" / f"WP-{wp:03d}.md")
    )
    with tempfile.TemporaryDirectory() as directory:
        snapshot = Path(directory)
        shutil.copy2(registry, snapshot / "registry")
        if active.exists():
            shutil.copy2(active, snapshot / "active")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_adopted_context(issue, wp), encoding="utf-8")
            registry_row(registry, wp, issue.title, "✅" if closed else "⏳")
            rebuild_active(governance)
            require_active_wp(active, wp)
        except Exception:
            path.unlink(missing_ok=True)
            if path.parent.name == f"WP-{wp:03d}":
                path.parent.rmdir()
            shutil.copy2(snapshot / "registry", registry)
            if (snapshot / "active").exists():
                shutil.copy2(snapshot / "active", active)
            else:
                active.unlink(missing_ok=True)
            raise
    return {
        "status": "CREATED",
        "wp": f"WP-{wp:03d}",
        "url": issue.url,
        "state": issue.state,
    }


def reconcile(
    governance: Path, config: AdoptionConfig, *, audit_only: bool = False
) -> dict[str, object]:
    if not config.repositories:
        return {"status": "OK", "disabled": True, "created": []}
    issues = list_adoption_issues(
        config
    )  # network first: no local writes on UNAVAILABLE
    links = links_by_url(governance)
    conflicts = [
        {"url": issue.url, "wps": [f"WP-{c.wp:03d}" for c in links.get(issue.url, [])]}
        for issue in issues
        if len(links.get(issue.url, [])) > 1
    ]
    if conflicts:
        return {"status": "CONFLICT", "conflicts": conflicts, "created": []}
    missing = [issue for issue in issues if not links.get(issue.url)]
    if audit_only:
        return {
            "status": "DRIFT" if missing else "OK",
            "missing": [issue.url for issue in missing],
            "conflicts": [],
        }
    created = [adopt_issue(issue, governance) for issue in missing]
    return {
        "status": "OK",
        "created": created,
        "already_linked": len(issues) - len(missing),
    }


def matching_issues(repo: str, wp: int) -> list[dict[str, object]]:
    issues = gh_json(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--limit",
            "100",
            "--search",
            f"WP-{wp} in:title",
            "--json",
            "number,title,state,url",
        ]
    )
    if not isinstance(issues, list):
        raise LinkError("GitHub issue list returned a non-list response")
    marker = re.compile(rf"^WP-{wp}(?:\s|:|$)")
    return [issue for issue in issues if marker.search(str(issue.get("title", "")))]


def issue_repo(url: str) -> str:
    match = re.match(r"^https://github\.com/([^/]+/[^/]+)/issues/\d+$", url)
    if not match:
        raise LinkError(f"invalid GitHub issue URL in context: {url}")
    return match.group(1)


def issue_number(url: str) -> int:
    match = re.match(r"^https://github\.com/[^/]+/[^/]+/issues/(\d+)$", url)
    if not match:
        raise LinkError(f"invalid GitHub issue URL in context: {url}")
    return int(match.group(1))


def issue_by_identity(url: str, repo: str) -> dict[str, object]:
    """Load a linked issue by immutable repository+number, never by title."""
    number = issue_number(url)
    raw = gh_json(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "number,title,state,url",
        ]
    )
    if not isinstance(raw, dict):
        raise LinkError("GitHub issue view returned a non-object response")
    if int(raw.get("number", -1)) != number or str(raw.get("url", "")) != url:
        raise LinkError(f"GitHub returned wrong identity for {url}")
    return raw


def create_issue(context: Context, repo: str) -> str:
    repo = validate_repo(repo)
    if context.github_repo and context.github_repo != repo:
        raise LinkError(
            f"WRONG_REPO WP-{context.wp}: context points to {context.github_repo}, requested {repo}"
        )
    if context.github_issue and issue_repo(context.github_issue) != repo:
        raise LinkError(
            f"WRONG_REPO WP-{context.wp}: context URL points to {issue_repo(context.github_issue)}, requested {repo}"
        )
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
        [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            f"WP-{context.wp} {context.title}",
            "--body",
            body,
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode:
        raise LinkError(
            f"GitHub create failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
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
                [
                    "gh",
                    "issue",
                    "close",
                    created_number,
                    "--repo",
                    repo,
                    "--reason",
                    "not planned",
                    "--comment",
                    f"Duplicate created by concurrent WP-{context.wp} linkage; canonical issue: {canonical['url']}",
                ],
                check=False,
                text=True,
                capture_output=True,
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
        return (
            "WRONG_REPO",
            f"WP-{context.wp}: context points to {context.github_repo}, expected {repo}",
        )
    if context.github_issue and issue_repo(context.github_issue) != repo:
        return (
            "WRONG_REPO",
            f"WP-{context.wp}: context URL points to {issue_repo(context.github_issue)}, expected {repo}",
        )
    if context.github_issue:
        issue = issue_by_identity(context.github_issue, repo)
    else:
        # Legacy WP-first contexts without a stored identity can only be
        # discovered by their machine-readable WP marker in the title.
        matches = matching_issues(repo, context.wp)
        if len(matches) > 1:
            return "DUPLICATE", f"WP-{context.wp}: {len(matches)} issues in {repo}"
        if not matches:
            return "MISSING", f"WP-{context.wp}: no issue in {repo}"
        issue = matches[0]
    active = context.status not in {"done", "closed", "cancelled", "archived"}
    issue_open = issue.get("state") == "OPEN"
    if active != issue_open:
        return (
            "STALE",
            f"WP-{context.wp}: context={context.status}, issue={issue.get('state')}",
        )
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
    audit.add_argument("--params", type=Path)
    adopt = sub.add_parser("adopt")
    adopt.add_argument("--governance", type=Path, required=True)
    adopt.add_argument("--repo", required=True)
    adopt.add_argument("--issue", type=int, required=True)
    reconcile_command = sub.add_parser("reconcile")
    reconcile_command.add_argument("--governance", type=Path, required=True)
    reconcile_command.add_argument("--params", type=Path, required=True)
    return parser


def audit_contexts(governance: Path) -> tuple[list[dict[str, str]], int]:
    results: list[dict[str, str]] = []
    pre_cutover = 0
    for path in context_paths(governance):
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
            if args.params:
                report = reconcile(
                    args.governance, read_adoption_config(args.params), audit_only=True
                )
                print(json.dumps(report, ensure_ascii=False))
                return 0 if report["status"] == "OK" else 1
            results, pre_cutover = audit_contexts(args.governance)
            print(
                json.dumps(
                    {
                        "status": "OK"
                        if all(item["status"] == "OK" for item in results)
                        else "DRIFT",
                        "pre_cutover": pre_cutover,
                        "items": results,
                    },
                    ensure_ascii=False,
                )
            )
            return 0 if all(item["status"] == "OK" for item in results) else 1
        if args.command == "adopt":
            repo = validate_repo(args.repo)
            raw = gh_json(
                [
                    "issue",
                    "view",
                    str(args.issue),
                    "--repo",
                    repo,
                    "--json",
                    "number,title,body,state,url,createdAt",
                ]
            )
            print(
                json.dumps(
                    adopt_issue(parse_issue(raw, repo), args.governance),
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "reconcile":
            report = reconcile(args.governance, read_adoption_config(args.params))
            print(json.dumps(report, ensure_ascii=False))
            return 0 if report["status"] == "OK" else 1
        context = read_frontmatter(args.context)
        if args.command == "create":
            print(
                json.dumps(
                    {"status": "OK", "url": create_issue(context, args.repo)},
                    ensure_ascii=False,
                )
            )
            return 0
        status, detail = check_context(context, args.repo)
        print(json.dumps({"status": status, "detail": detail}, ensure_ascii=False))
        return 0 if status == "OK" else 1
    except LinkError as exc:
        detail = str(exc)
        if detail.startswith("CONFLICT"):
            status = "CONFLICT"
        elif detail.startswith("INVALID_CONFIG"):
            status = "INVALID_CONFIG"
        elif detail.startswith("INVALID_LOCAL_STATE"):
            status = "INVALID_LOCAL_STATE"
        elif detail.startswith("invalid "):
            status = "INVALID"
        else:
            status = "UNAVAILABLE"
        print(
            json.dumps({"status": status, "detail": detail}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
