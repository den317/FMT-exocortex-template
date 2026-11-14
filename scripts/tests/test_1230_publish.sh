#!/usr/bin/env bash
# Regression coverage for issue #1230: lib/publish-gate.sh::publish_commit()
# always calls ds-publish.sh with --exact-commit SHA (same value as
# --from-commit) and optionally --run-id ID. ds-publish.sh used to parse
# neither flag and hit usage()+exit on every such call, leaving the commit
# local. Both flags are now accepted; --exact-commit is validated against
# the resolved commit, --run-id only rides into the status line.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
SCRIPT="$ROOT/seed/strategy/scripts/ds-publish.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail=0
pass() { echo "  ✅ PASS: $*"; }
fail_test() { echo "  ❌ FAIL: $*" >&2; fail=1; }

# A throw-away repo with two commits and itself as "origin" (ds-publish.sh
# only needs a reachable remote, not a real server).
REPO="$TMP/repo"
mkdir -p "$REPO"
git init -q "$REPO"
git -C "$REPO" config user.email "t@t.com"
git -C "$REPO" config user.name "t"
echo "a" > "$REPO/f.txt"; git -C "$REPO" add f.txt; git -C "$REPO" commit -q -m "c1"
SHA1=$(git -C "$REPO" rev-parse HEAD)
echo "b" > "$REPO/f.txt"; git -C "$REPO" add f.txt; git -C "$REPO" commit -q -m "c2"
SHA2=$(git -C "$REPO" rev-parse HEAD)
git -C "$REPO" remote add origin "$REPO"

# --- 1. --exact-commit equal to --from-commit + --run-id: no usage() bailout.
out=$(bash "$SCRIPT" "$REPO" normal --from-commit "$SHA2" --exact-commit "$SHA2" --run-id "run-42" 2>&1)
rc=$?
if [ "$rc" -eq 0 ]; then pass "matching --exact-commit + --run-id: exit 0"; else fail_test "matching --exact-commit: expected exit 0, got $rc: $out"; fi
if printf '%s' "$out" | grep -q 'usage:'; then
    fail_test "matching --exact-commit: fell through to usage(): $out"
else
    pass "matching --exact-commit: no usage() bailout"
fi
if printf '%s' "$out" | grep -q '\[run=run-42\]'; then
    pass "--run-id: shown in the status line"
else
    fail_test "--run-id: not found in output: $out"
fi

# --- 2. --exact-commit that disagrees with --from-commit: explicit die, not
# a silent publish of the wrong commit.
out=$(bash "$SCRIPT" "$REPO" normal --from-commit "$SHA2" --exact-commit "$SHA1" 2>&1)
rc=$?
if [ "$rc" -ne 0 ]; then pass "mismatched --exact-commit: non-zero exit ($rc)"; else fail_test "mismatched --exact-commit: expected non-zero exit, got 0: $out"; fi
if printf '%s' "$out" | grep -q 'does not match'; then
    pass "mismatched --exact-commit: explicit mismatch message"
else
    fail_test "mismatched --exact-commit: no explicit mismatch message: $out"
fi
if printf '%s' "$out" | grep -q '^ds-publish: published as'; then
    fail_test "mismatched --exact-commit: published anyway (silent wrong-commit publish): $out"
else
    pass "mismatched --exact-commit: did not publish"
fi

# --- 3. No new flags at all: unchanged behaviour (existing callers never
# pass --exact-commit/--run-id).
out=$(bash "$SCRIPT" "$REPO" normal --from-commit "$SHA1" --reason "legacy call" 2>&1)
rc=$?
if [ "$rc" -eq 0 ]; then pass "legacy call without new flags: exit 0"; else fail_test "legacy call: expected exit 0, got $rc: $out"; fi

[ "$fail" -eq 0 ] && echo "test_1230_publish: ALL PASS" || echo "test_1230_publish: FAILURES ABOVE"
exit "$fail"
