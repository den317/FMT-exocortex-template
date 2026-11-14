#!/usr/bin/env bash
# Regression coverage for issue #1235: iwe-env-bootstrap.sh's optional
# backup_dir: lookup used a pipeline whose exit code, under pipefail, killed
# the whole assignment when the key was absent (the common case --
# params.yaml.example doesn't set one). bash 3.2 (macOS's /bin/bash, what
# backup-icloud.sh's #!/bin/bash shebang resolves to) doesn't suspend errexit
# inside a sourced file the way bash 4.4+/5 do, so the caller silently died
# right there instead of falling through to the default backup path.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BOOTSTRAP="$ROOT/.claude/lib/iwe-env-bootstrap.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail=0
pass() { echo "  ✅ PASS: $*"; }
fail_test() { echo "  ❌ FAIL: $*" >&2; fail=1; }

# A real bash 3.2 if present (the only interpreter that actually exposes this
# bug) is preferred; fall back to whatever /bin/bash is if 3.2 isn't found,
# noting that the test is then weaker (may pass on a newer /bin/bash too).
BASH32=""
for cand in /bin/bash /usr/bin/bash; do
    if [ -x "$cand" ] && "$cand" -c 'echo $BASH_VERSION' 2>/dev/null | grep -q '^3\.2'; then
        BASH32="$cand"
        break
    fi
done
if [ -z "$BASH32" ]; then
    echo "  ⚠️  bash 3.2 not found on this machine -- test runs against /bin/bash as a weaker check" >&2
    BASH32="/bin/bash"
fi

mkdir -p "$TMP/ws"
echo "# no backup_dir key -- same as params.yaml.example" > "$TMP/ws/params.yaml"

out=$(env -i HOME="$HOME" PATH=/usr/bin:/bin WORKSPACE_DIR="$TMP/ws" "$BASH32" -c \
    "set -euo pipefail; source '$BOOTSTRAP' || exit 1; echo REACHED" 2>&1)
rc=$?
if [ "$rc" -eq 0 ]; then pass "missing backup_dir: key does not kill the sourcing shell (rc=0)"; else fail_test "missing backup_dir: key killed the shell (rc=$rc): $out"; fi
if printf '%s' "$out" | grep -q '^REACHED$'; then
    pass "control flow reaches the line after source (bootstrap did not exit early)"
else
    fail_test "REACHED not printed -- bootstrap exited before returning control: $out"
fi

[ "$fail" -eq 0 ] && echo "test_1235_backup_bootstrap: ALL PASS" || echo "test_1235_backup_bootstrap: FAILURES ABOVE"
exit "$fail"
