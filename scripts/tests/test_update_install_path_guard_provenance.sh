#!/usr/bin/env bash
set -euo pipefail

# issue #459: the guard must not confuse text that merely COINCIDES with a
# local install-value against text actually introduced by substitution. This
# exercises the upstream-history exception that test_update_install_path_guard.sh
# does not cover (that fixture has no upstream remote at all, so historical_lines
# is always empty there and the guard stays fail-closed for every case).
#
# Scope note (matches the consensus reached in the peer session that produced
# this fix, sessions/2026-08/18/2026-08-18-09-implement-issue-fixes/05-peer.md):
# the exception covers a line that already appeared in this SAME file's own
# upstream history — not anywhere else in the repo. A line that is new to
# THIS file, even if it happens to appear verbatim in some other file, is
# still a genuine leak from this file's point of view.

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

eval "$(awk '
  /^validate_no_install_values_in_applied_additions\(\)/ { capture=1 }
  capture { print }
  capture && /^}/ { exit }
' "$ROOT/update.sh")"
declare -F validate_no_install_values_in_applied_additions >/dev/null

UPSTREAM="$TMP/upstream.git"
SCRIPT_DIR="$TMP/template"
WORKSPACE_DIR="$TMP/workspace"
mkdir -p "$WORKSPACE_DIR"

git init -q --bare "$UPSTREAM"
git init -q "$SCRIPT_DIR"
git -C "$SCRIPT_DIR" config user.email test@example.invalid
git -C "$SCRIPT_DIR" config user.name 'Provenance guard test'
git -C "$SCRIPT_DIR" remote add origin "$UPSTREAM"

cat >"$WORKSPACE_DIR/.exocortex.env" <<EOF
WORKSPACE_DIR=$WORKSPACE_DIR
HOME_DIR=/root
USER_NAME=root
CLAUDE_PATH=/synthetic-test-root/bin/claude
IWE_TEMPLATE=$SCRIPT_DIR
IWE_RUNTIME=$WORKSPACE_DIR/.iwe-runtime
EOF

# Upstream release 1: docs/example.md already carries a line that happens to
# be identical to this pilot's local CLAUDE_PATH — pure coincidence, unrelated
# to any substitution mechanism. Then the line is removed in release 2.
mkdir -p "$SCRIPT_DIR/docs"
cat >"$SCRIPT_DIR/docs/example.md" <<'EOF'
# Example config
A common Claude install path is /synthetic-test-root/bin/claude on a synthetic test machine.
Keep this line stable across releases.
EOF
git -C "$SCRIPT_DIR" add docs/example.md
git -C "$SCRIPT_DIR" commit -qm 'release 1: mention a common install path in docs'
git -C "$SCRIPT_DIR" push -q origin HEAD:main
git -C "$SCRIPT_DIR" branch -q --set-upstream-to=origin/main 2>/dev/null ||
    git -C "$SCRIPT_DIR" branch -q -u origin/main

cat >"$SCRIPT_DIR/docs/example.md" <<'EOF'
# Example config
Keep this line stable across releases.
EOF
git -C "$SCRIPT_DIR" add docs/example.md
git -C "$SCRIPT_DIR" commit -qm 'release 2: drop the example path line'
git -C "$SCRIPT_DIR" push -q origin HEAD:main

# Upstream release 3: the SAME line reappears in docs/example.md (e.g. a
# revert, or the author re-adding the example). It coincides with the local
# CLAUDE_PATH, but this exact file already carried this exact line before —
# not a new leak, just history repeating within the same file.
cat >"$SCRIPT_DIR/docs/example.md" <<'EOF'
# Example config
A common Claude install path is /synthetic-test-root/bin/claude on a synthetic test machine.
Keep this line stable across releases.
EOF
APPLIED_PATHS=(docs/example.md)
if ! validate_no_install_values_in_applied_additions 2>"$TMP/coincidence.err"; then
    echo 'guard rejected a line that coincidentally matches install-path but already existed verbatim in this same file upstream' >&2
    cat "$TMP/coincidence.err" >&2
    exit 1
fi

# Negative control: a genuinely NEW line in the SAME file, never seen before
# in this file's history, must still be blocked even though the file itself
# has legitimate prior history.
git -C "$SCRIPT_DIR" add docs/example.md
git -C "$SCRIPT_DIR" commit -qm 'release 3: bring the example path line back'
git -C "$SCRIPT_DIR" push -q origin HEAD:main
cat >"$SCRIPT_DIR/docs/example.md" <<'EOF'
# Example config
A common Claude install path is /synthetic-test-root/bin/claude on a synthetic test machine.
Keep this line stable across releases.
Debug note: my personal claude binary lives at /synthetic-test-root/bin/claude and nowhere else was this written before.
EOF
APPLIED_PATHS=(docs/example.md)
if validate_no_install_values_in_applied_additions 2>"$TMP/leak.err"; then
    echo 'guard accepted a genuinely new line containing a leaked install value' >&2
    exit 1
fi
grep -Fq 'CLAUDE_PATH' "$TMP/leak.err"

# Cross-file check: a DIFFERENT file re-using the exact same wording is still
# a genuine leak from that file's own point of view — provenance is scoped
# per file, not repo-wide (matches the consensus wording: "той же строки в
# файле раньше", not "где-то в апстриме").
cat >"$SCRIPT_DIR/docs/other-file.md" <<'EOF'
A common Claude install path is /synthetic-test-root/bin/claude on a synthetic test machine.
EOF
APPLIED_PATHS=(docs/other-file.md)
if validate_no_install_values_in_applied_additions 2>"$TMP/crossfile.err"; then
    echo 'guard incorrectly treated another file historical line as provenance for a new file' >&2
    exit 1
fi

# Fail-closed check: with no upstream ref configured at all, even a
# historically-seen line must be blocked (no silent bypass without history).
git -C "$SCRIPT_DIR" branch --unset-upstream 2>/dev/null || true
APPLIED_PATHS=(docs/example.md)
if validate_no_install_values_in_applied_additions 2>"$TMP/noupstream.err"; then
    echo 'guard silently bypassed protection when no upstream ref is configured' >&2
    exit 1
fi

# Cold-context review Critical finding: a leak that is fully COMMITTED to the
# local template repo (not just sitting in the uncommitted working tree) must
# still be caught. The guard used to derive "what this run touched" from
# `git diff` (working tree vs HEAD) — for a file with zero working-tree
# delta (e.g. update.sh ran a second time after a partial manual commit, or
# a pre-commit hook auto-committed), that diff is empty and the file was
# silently skipped from scanning entirely, even though it genuinely leaked
# an install path. Reproduced live before the fix: this exact scenario
# passed with exit 0 and no diagnostic.
git -C "$SCRIPT_DIR" branch -q --set-upstream-to=origin/main
cat >"$SCRIPT_DIR/docs/committed-leak.md" <<'EOF'
This file was fully committed with a leaked path already inside it:
/synthetic-test-root/bin/claude — never seen anywhere in upstream history before.
EOF
git -C "$SCRIPT_DIR" add docs/committed-leak.md
git -C "$SCRIPT_DIR" commit -qm 'accidentally committed a leak before update.sh ran the guard'
APPLIED_PATHS=(docs/committed-leak.md)
if validate_no_install_values_in_applied_additions 2>"$TMP/committed-leak.err"; then
    echo 'guard accepted a fully-committed leak with zero working-tree diff (the Critical review finding)' >&2
    exit 1
fi
grep -Fq 'CLAUDE_PATH' "$TMP/committed-leak.err"

echo 'PASS: install-path guard distinguishes coincidental same-file history from genuine leaks'
