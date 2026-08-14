#!/usr/bin/env python3
"""Read-only three-way preview of an upstream FMT release.

The command clones upstream into a temporary directory and compares an explicitly
accepted base revision, a candidate revision, and the current den317 HEAD. It
never checks out, copies, commits, pushes, or merges candidate files.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_UPSTREAM = "https://github.com/TserenTserenov/FMT-exocortex-template.git"
SENSITIVE_PATHS = {"update.sh", "setup.sh", "update-manifest.json"}


class IntakeError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    process = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise IntakeError(f"git {' '.join(args)}: {detail}")
    return process.stdout.strip()


def resolve_commit(repo: Path, revision: str, label: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        tag_ref = f"refs/tags/{revision}"
        try:
            git(repo, "show-ref", "--verify", "--quiet", tag_ref)
        except IntakeError:
            raise IntakeError(f"{label} must be a full commit SHA or an existing tag: {revision}")
        revision = tag_ref
    try:
        resolved = git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}")
    except IntakeError as error:
        raise IntakeError(f"{label} revision is unavailable: {revision}") from error
    return resolved


def tree(repo: Path, revision: str) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    output = git(repo, "ls-tree", "-r", "-z", revision)
    for record in output.split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        mode, object_type, object_id = metadata.split()
        if object_type == "blob":
            result[path] = (mode, object_id)
    return result


def classify(
    base: tuple[str, str] | None,
    candidate: tuple[str, str] | None,
    current: tuple[str, str] | None,
) -> str:
    upstream_changed = candidate != base
    den317_changed = current != base
    if not upstream_changed and not den317_changed:
        return "unchanged"
    if upstream_changed and not den317_changed:
        if base is None:
            return "upstream-added"
        if candidate is None:
            return "upstream-deleted"
        return "upstream-only"
    if not upstream_changed and den317_changed:
        return "den317-only"
    if candidate == current:
        return "both-same"
    return "both-diverged"


def load_manifest(den317: Path) -> dict[str, object]:
    try:
        return json.loads((den317 / "update-manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntakeError("den317 update-manifest.json is missing or invalid") from error


def accepted_base(manifest: dict[str, object], requested: str | None) -> tuple[str, str]:
    provenance = manifest.get("upstream_provenance")
    if not isinstance(provenance, dict):
        raise IntakeError("den317 manifest has no upstream_provenance")
    tag = provenance.get("accepted_tag")
    sha = provenance.get("accepted_sha")
    if not isinstance(tag, str) or not tag or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise IntakeError("den317 manifest has invalid upstream_provenance")
    if requested and requested not in {tag, sha}:
        raise IntakeError(f"requested base {requested} differs from attested base {tag}@{sha}")
    return tag, sha


def build_report(
    upstream: Path,
    den317: Path,
    args: argparse.Namespace,
    manifest: dict[str, object],
    base_tag: str,
    attested_sha: str,
) -> dict[str, object]:
    base_sha = resolve_commit(upstream, attested_sha, "attested base")
    tag_sha = resolve_commit(upstream, base_tag, "attested base tag")
    if tag_sha != base_sha:
        raise IntakeError(f"attested tag {base_tag} resolves to {tag_sha}, expected {base_sha}")
    candidate_sha = resolve_commit(upstream, args.target, "target")
    current_sha = git(den317, "rev-parse", "--verify", "HEAD^{commit}")

    base_tree = tree(upstream, base_sha)
    candidate_tree = tree(upstream, candidate_sha)
    current_tree = tree(den317, current_sha)
    delivered = {entry["path"] for entry in manifest.get("files", []) if "path" in entry}
    excluded = set(manifest.get("excluded_paths", []))
    paths = sorted(set(base_tree) | set(candidate_tree) | set(current_tree))

    files = []
    counts: Counter[str] = Counter()
    blockers = []
    for path in paths:
        category = classify(base_tree.get(path), candidate_tree.get(path), current_tree.get(path))
        if category == "unchanged":
            continue
        scope = "delivered" if path in delivered else "excluded" if path in excluded else "unlisted"
        entry = {"path": path, "classification": category, "delivery_scope": scope}
        files.append(entry)
        counts[category] += 1
        if category == "both-diverged":
            blockers.append({"path": path, "reason": "both upstream and den317 changed"})
        if path in SENSITIVE_PATHS and candidate_tree.get(path) != base_tree.get(path):
            blockers.append({"path": path, "reason": "sensitive update-channel file changed"})

    return {
        "schema_version": 1,
        "mode": "read-only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream": args.upstream,
        "base_ref": base_tag,
        "base_sha": base_sha,
        "target_ref": args.target,
        "target_sha": candidate_sha,
        "den317_sha": current_sha,
        "verdict": "blocked" if blockers else "reviewable",
        "counts": dict(sorted(counts.items())),
        "blockers": blockers,
        "files": files,
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Upstream intake preview",
        "",
        f"- Mode: `{report['mode']}`",
        f"- Verdict: `{report['verdict']}`",
        f"- Base: `{report['base_ref']}` → `{report['base_sha']}`",
        f"- Candidate: `{report['target_ref']}` → `{report['target_sha']}`",
        f"- den317: `{report['den317_sha']}`",
        "",
        "## Counts",
        "",
    ]
    counts = report["counts"]
    assert isinstance(counts, dict)
    lines.extend(f"- `{key}`: {value}" for key, value in counts.items())
    blockers = report["blockers"]
    assert isinstance(blockers, list)
    lines.extend(["", "## Blockers", ""])
    if blockers:
        lines.extend(f"- `{item['path']}` — {item['reason']}" for item in blockers)
    else:
        lines.append("- none")
    files = report["files"]
    assert isinstance(files, list)
    lines.extend(["", "## Files", "", "| Path | Classification | Delivery scope |", "|---|---|---|"])
    lines.extend(
        f"| `{item['path']}` | `{item['classification']}` | `{item['delivery_scope']}` |"
        for item in files
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    parser.add_argument("--base", help="optional assertion; must match the attested tag or SHA")
    parser.add_argument("--target", required=True, help="candidate upstream tag or SHA")
    parser.add_argument("--den317", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", type=Path, help="report path; stdout when omitted")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    den317 = args.den317.resolve()
    if git(den317, "status", "--porcelain"):
        raise IntakeError("den317 working tree is dirty; commit or stash before intake")
    manifest = load_manifest(den317)
    base_tag, base_sha = accepted_base(manifest, args.base)
    if args.output:
        output = args.output.resolve()
        if output == den317 or den317 in output.parents:
            raise IntakeError("report output must be outside the den317 working tree")

    with tempfile.TemporaryDirectory(prefix="iwe-upstream-intake-") as temporary:
        upstream = Path(temporary) / "upstream"
        subprocess.run(
            ["git", "clone", "--quiet", "--no-checkout", "--", args.upstream, str(upstream)],
            check=True,
        )
        report = build_report(upstream, den317, args, manifest, base_tag, base_sha)

    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else markdown(report)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (IntakeError, subprocess.CalledProcessError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
