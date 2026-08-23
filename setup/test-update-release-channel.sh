#!/bin/bash
# test-update-release-channel.sh — WP-529 F7 follow-up (pilot decision
# 2026-08-21): update.sh delivers the LAST PUBLISHED RELEASE by default, not
# the moving main — an external user proved the old contract shipped red,
# unreleased main while still reporting the last release's version number.
#
# Extracts resolve_delivery_ref() out of the real update.sh (same technique as
# scripts/tests/lib/extract-update-download-batch.sh) and drives it with a
# stubbed curl: no network, each case asserts what RAW_BASE gets pinned to.
#
# Bash 3.2 compatible. Usage: bash setup/test-update-release-channel.sh

set -uo pipefail
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SELF_DIR")"
UPDATE_SH="$REPO_ROOT/update.sh"

FAIL_COUNT=0
PASS_COUNT=0
fail() { echo "  ❌ FAIL: $*" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }
pass() { echo "  ✅ PASS: $*"; PASS_COUNT=$((PASS_COUNT + 1)); }

FUNCS=$(mktemp)
CHANNEL_FUNCS=$(mktemp)
CHANNEL_ROOT=$(mktemp -d)
trap 'rm -f "$FUNCS" "$CHANNEL_FUNCS"; rm -rf "$CHANNEL_ROOT"' EXIT
awk '
    /^resolve_delivery_ref\(\) \{$/ { found=1 }
    found { print }
    found && /^\}$/ { exit }
' "$UPDATE_SH" > "$FUNCS"
[ -s "$FUNCS" ] || { echo "FATAL: resolve_delivery_ref extraction is empty — marker no longer matches update.sh" >&2; exit 2; }

sed -n '/^read_update_channel_value() {$/,/^configure_update_channel$/p' "$UPDATE_SH" | sed '$d' > "$CHANNEL_FUNCS"
[ -s "$CHANNEL_FUNCS" ] || { echo "FATAL: verified-channel function extraction is empty" >&2; exit 2; }

TAG_SHA="1111111111111111111111111111111111111111"
MAIN_SHA="2222222222222222222222222222222222222222"

# run_case CHANNEL HAS_RELEASES HAS_PY -> prints resulting RAW_BASE + output
run_case() {
    local channel="$1" has_releases="$2" has_py="$3"
    (
        set -uo pipefail
        REPO="owner/tmpl"
        BRANCH="main"
        API_BASE="https://api.github.com/repos/$REPO"
        RAW_BASE="https://raw.githubusercontent.com/$REPO/$BRANCH"
        CURL_BASE_OPTS="--max-time 2"
        _CURL_SSL_OPT=""
        UPDATE_CHANNEL="$channel"
        PY_BIN="$(command -v python3 || echo python3)"
        HAS_RELEASES="$has_releases"
        HAS_PY="$has_py"
        py_available() { [ "$HAS_PY" = "yes" ]; }
        curl() {
            local url=""
            for a in "$@"; do case "$a" in http*) url="$a" ;; esac; done
            case "$url" in
                */releases/latest)
                    [ "$HAS_RELEASES" = "yes" ] || return 22
                    printf '{"tag_name": "v9.9.9", "name": "v9.9.9"}\n' ;;
                */commits/v9.9.9) printf '{"sha": "%s"}\n' "$TAG_SHA" ;;
                */commits/main)   printf '{"sha": "%s"}\n' "$MAIN_SHA" ;;
                *) return 22 ;;
            esac
        }
        # shellcheck disable=SC1090
        . "$FUNCS"
        resolve_delivery_ref
        echo "RAW_BASE=$RAW_BASE"
    )
}

echo "=== 1. release channel (default): pinned to the release tag's SHA ==="
OUT=$(run_case release yes yes)
echo "$OUT" | grep -q "RAW_BASE=.*/$TAG_SHA$" && pass "RAW_BASE pinned to release SHA" || fail "expected release SHA pin, got: $OUT"
echo "$OUT" | grep -q "релиз v9.9.9" && pass "announces the release tag" || fail "no release announcement: $OUT"

echo "=== 2. release channel, no releases published: explicit fallback to main ==="
OUT=$(run_case release no yes)
echo "$OUT" | grep -q "RAW_BASE=.*/$MAIN_SHA$" && pass "falls back to pinned main SHA" || fail "expected main fallback, got: $OUT"
echo "$OUT" | grep -q "Не удалось определить последний релиз" && pass "fallback is announced, not silent" || fail "silent fallback: $OUT"

echo "=== 3. IWE_UPDATE_CHANNEL=main: the old moving-branch contract, pinned ==="
OUT=$(run_case main yes yes)
echo "$OUT" | grep -q "RAW_BASE=.*/$MAIN_SHA$" && pass "main channel pins main SHA" || fail "expected main pin, got: $OUT"
echo "$OUT" | grep -q "релиз" && fail "main channel must not consult releases: $OUT" || pass "releases API not consulted on main channel"

echo "=== 4. release channel without python3: pinned to the tag itself ==="
OUT=$(run_case release yes no)
echo "$OUT" | grep -q "RAW_BASE=.*/v9.9.9$" && pass "RAW_BASE pinned to tag without python" || fail "expected tag pin, got: $OUT"

echo "=== 5. verified fork: env identity wins and defaults to an immutable main snapshot ==="
mkdir -p "$CHANNEL_ROOT/template"
cat > "$CHANNEL_ROOT/.exocortex.env" <<'EOF'
IWE_UPDATE_REPO=den317/FMT-exocortex-template
IWE_UPDATE_BRANCH=main
EOF
OUT=$(
    unset IWE_UPDATE_REPO IWE_UPDATE_BRANCH IWE_UPDATE_CHANNEL
    SCRIPT_DIR="$CHANNEL_ROOT/template"
    WORKSPACE_DIR="$CHANNEL_ROOT"
    DEFAULT_UPDATE_REPO="TserenTserenov/FMT-exocortex-template"
    DEFAULT_UPDATE_BRANCH="main"
    REPO="$DEFAULT_UPDATE_REPO"
    BRANCH="$DEFAULT_UPDATE_BRANCH"
    UPDATE_CHANNEL="release"
    EXIT_USAGE=1
    # shellcheck disable=SC1090
    . "$CHANNEL_FUNCS"
    configure_update_channel
    printf 'REPO=%s\nBRANCH=%s\nCHANNEL=%s\nRAW_BASE=%s\n' "$REPO" "$BRANCH" "$UPDATE_CHANNEL" "$RAW_BASE"
)
echo "$OUT" | grep -q '^REPO=den317/FMT-exocortex-template$' && pass "fork repository loaded from protected env" || fail "fork repo not selected: $OUT"
echo "$OUT" | grep -q '^CHANNEL=main$' && pass "verified fork defaults to main-before-SHA-pin" || fail "fork channel did not select main: $OUT"
echo "$OUT" | grep -q '^RAW_BASE=https://raw.githubusercontent.com/den317/FMT-exocortex-template/main$' && pass "self-update and payload share the fork base" || fail "fork RAW_BASE mismatch: $OUT"

echo
echo "Result: $PASS_COUNT PASS, $FAIL_COUNT FAIL"
[ "$FAIL_COUNT" -eq 0 ] && exit 0 || exit 1
