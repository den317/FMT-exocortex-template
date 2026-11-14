#!/usr/bin/env bash
# Regression coverage for issue #1229 (the wp-sync-bundle.sh half): the
# self-relative lookup of scripts/lib/git-sync-status.sh never considered
# $IWE_SCRIPTS (from .iwe-paths), so a custom layout where .claude/scripts/
# and scripts/lib/ are not siblings under the same root always reported
# checker_unavailable even when the library existed elsewhere. The
# self-relative lookup must stay first and unconditional (fixture isolation);
# $IWE_SCRIPTS is only a fallback for when it fails.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
BUNDLE="$ROOT/.claude/scripts/wp-sync-bundle.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail=0
pass() { echo "  ✅ PASS: $*"; }
fail_test() { echo "  ❌ FAIL: $*" >&2; fail=1; }

# A copy of the bundle script at a path with no scripts/lib/git-sync-status.sh
# next to it, so the self-relative lookup for THAT library is guaranteed to
# miss. wp-sync-bundle.sh also hard-requires scripts/lib/wp-num.sh (issue
# #954, unrelated to #1229) before it gets anywhere near the git-sync code --
# that one has to resolve normally (copied into the isolated tree at the same
# relative layout) or every run here fails before the behaviour under test
# even executes.
mkdir -p "$TMP/isolated/.claude/scripts" "$TMP/isolated/scripts/lib" "$TMP/real-scripts/lib"
cp "$BUNDLE" "$TMP/isolated/.claude/scripts/wp-sync-bundle.sh"
cp "$ROOT/scripts/lib/wp-num.sh" "$TMP/isolated/scripts/lib/wp-num.sh"
cp "$ROOT/scripts/lib/git-sync-status.sh" "$TMP/real-scripts/lib/git-sync-status.sh"

# wp-sync-bundle.sh requires a governance repo with docs/WP-REGISTRY.md under
# $IWE_WORKSPACE before it ever reaches the git-sync code under test -- an
# unrelated precondition. Point it at a throw-away one instead of relying on
# whatever happens to live at the real $HOME/IWE (which made this pass
# locally while CI's clean $HOME/IWE-less runner failed it outright).
mkdir -p "$TMP/fake-ws/governance/docs"
: > "$TMP/fake-ws/governance/docs/WP-REGISTRY.md"

# --- 1. No IWE_SCRIPTS set: self-relative misses, no fallback available,
# stays checker_unavailable/degraded (the pre-fix, still-correct behaviour).
out=$(env -u IWE_SCRIPTS IWE_WORKSPACE="$TMP/fake-ws" bash "$TMP/isolated/.claude/scripts/wp-sync-bundle.sh" WP-1 2>&1)
if printf '%s' "$out" | grep -q 'GIT_SYNC_STATUS: checker_unavailable'; then
    pass "no IWE_SCRIPTS: library not found, degraded as before"
else
    fail_test "no IWE_SCRIPTS: expected checker_unavailable: $out"
fi

# --- 2. IWE_SCRIPTS pointing at the real library: fallback kicks in, the
# library actually loads (status moves off checker_unavailable/library_missing,
# proving check_git_sync_status ran instead of the stub branch).
out=$(env IWE_SCRIPTS="$TMP/real-scripts" IWE_WORKSPACE="$TMP/fake-ws" bash "$TMP/isolated/.claude/scripts/wp-sync-bundle.sh" WP-1 2>&1)
if printf '%s' "$out" | grep -q 'пробую \$IWE_SCRIPTS/lib/git-sync-status.sh'; then
    pass "IWE_SCRIPTS set: fallback attempted"
else
    fail_test "IWE_SCRIPTS set: fallback message not found: $out"
fi
if printf '%s' "$out" | grep -q 'GIT_SYNC_STATUS: checker_unavailable' && printf '%s' "$out" | grep -q 'library_missing'; then
    fail_test "IWE_SCRIPTS set: still reports library_missing -- fallback did not load the library: $out"
else
    pass "IWE_SCRIPTS set: no longer reports library_missing"
fi

[ "$fail" -eq 0 ] && echo "test_1229_sync_bundle: ALL PASS" || echo "test_1229_sync_bundle: FAILURES ABOVE"
exit "$fail"
