#!/usr/bin/env bash
# Regression coverage for issue #1234: .githooks/pre-commit unconditionally ran
# a fork's own (stale, excluded_paths, never-synced-by-update.sh) copy of
# setup/integration-contract-validator.sh, the same file CI already skips on
# forks via `if: github.repository == 'TserenTserenov/FMT-exocortex-template'`.
# The hook now applies the equivalent check locally: origin's normalized URL
# must match the canonical repo, else the step is skipped with a message
# instead of running a stale validator or silently doing nothing.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
HOOK="$ROOT/.githooks/pre-commit"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail=0
pass() { echo "  ✅ PASS: $*"; }
fail_test() { echo "  ❌ FAIL: $*" >&2; fail=1; }

make_repo() {  # <dir> <origin-url>
    local dir="$1" origin="$2"
    mkdir -p "$dir/.githooks" "$dir/setup" "$dir/.claude" "$dir/scripts"
    cp "$HOOK" "$dir/.githooks/pre-commit"
    chmod +x "$dir/.githooks/pre-commit"
    # The hook fails closed without a secret scanner -- a stub that always
    # passes, since secret scanning is not what this test covers.
    printf '#!/usr/bin/env bash\nexit 0\n' > "$dir/scripts/pre-commit-secret-scan.sh"
    chmod +x "$dir/scripts/pre-commit-secret-scan.sh"
    git -C "$dir" init -q
    git -C "$dir" config user.email "t@t.com"
    git -C "$dir" config user.name "t"
    git -C "$dir" config core.hooksPath .githooks
    git -C "$dir" remote add origin "$origin"
    echo "init" > "$dir/README.md"
    git -C "$dir" add README.md
    git -C "$dir" commit -q -m init
}

# A stub validator: always exits 0 and leaves a marker file -- the hook
# only shows a validator's stdout on FAILURE, so a successful run is
# otherwise invisible in commit output; the marker is how this test knows
# whether the hook actually invoked it.
make_stub_validator() {  # <dir>
    local marker="$1/.validator-ran"
    cat > "$1/setup/integration-contract-validator.sh" <<EOF
#!/usr/bin/env bash
: > "$marker"
exit 0
EOF
    chmod +x "$1/setup/integration-contract-validator.sh"
}

# --- 1. Fork origin (not the canonical repo): skip message, commit succeeds,
# stub validator (if present) is NOT invoked.
FORK="$TMP/fork"
make_repo "$FORK" "https://github.com/SomeoneElse/forked-template.git"
make_stub_validator "$FORK"
echo "x" > "$FORK/.claude/changed.md"
git -C "$FORK" add .claude/changed.md
out=$(git -C "$FORK" commit -q -m "touch .claude" 2>&1)
rc=$?
if [ "$rc" -eq 0 ]; then pass "fork origin: commit succeeds"; else fail_test "fork origin: commit failed: $out"; fi
if printf '%s' "$out" | grep -q 'пропущен'; then
    pass "fork origin: explicit skip message shown"
else
    fail_test "fork origin: no skip message: $out"
fi
if [ -f "$FORK/.validator-ran" ]; then
    fail_test "fork origin: stale validator was invoked anyway: $out"
else
    pass "fork origin: stub validator not invoked"
fi

# --- 2. Canonical origin, validator present and passing: commit succeeds,
# the marker proves the hook actually ran it (success leaves no trace in
# commit output -- the hook only shows a validator's stdout on failure).
CANON="$TMP/canon"
make_repo "$CANON" "git@github.com:TserenTserenov/FMT-exocortex-template.git"
make_stub_validator "$CANON"
echo "x" > "$CANON/.claude/changed.md"
git -C "$CANON" add .claude/changed.md
out=$(git -C "$CANON" commit -q -m "touch .claude" 2>&1)
rc=$?
if [ "$rc" -eq 0 ]; then pass "canonical origin: commit succeeds"; else fail_test "canonical origin: commit failed: $out"; fi
if [ -f "$CANON/.validator-ran" ]; then
    pass "canonical origin: validator was actually invoked"
else
    fail_test "canonical origin: validator did not run: $out"
fi

[ "$fail" -eq 0 ] && echo "test_1234_fork_precommit: ALL PASS" || echo "test_1234_fork_precommit: FAILURES ABOVE"
exit "$fail"
