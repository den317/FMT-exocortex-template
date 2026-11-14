#!/bin/bash
# test-strategist-mark-done.sh -- issue #1134 acceptance test for the `mark-done` command of
# roles/strategist/scripts/strategist.sh and its wiring into already_ran_today(). A scenario closed
# by hand outside its own schedule (e.g. week-close run Sunday evening instead of waiting for
# Monday's automatic week-review) used to be invisible to the next automatic run: week-review's
# status file compares to "today" and session-prep's generic check only greps today's rotated log,
# neither can see a different day's manual completion. `mark-done` records it against the ISO week
# instead, which already_ran_today() now consults before its own date-scoped checks.
#
# Two layers, both against a disposable $HOME:
#   A. the REAL helper functions cut out of the runner by name (function-level cases);
#   B. the REAL runner end to end (`strategist.sh mark-done ...`) via subprocess.
#
# Usage: bash setup/test-strategist-mark-done.sh

set -uo pipefail
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SELF_DIR")"
SCRIPT="${STRATEGIST_SCRIPT_UNDER_TEST:-$REPO_ROOT/roles/strategist/scripts/strategist.sh}"
TEST_ROOT="$(cd -P "$(mktemp -d "${TMPDIR:-/tmp}/iwe-strategist-mark-done-test.XXXXXX")" && pwd -P)"

FAIL_COUNT=0
PASS_COUNT=0
fail() { echo "  ❌ FAIL: $*" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }
pass() { echo "  ✅ PASS: $*"; PASS_COUNT=$((PASS_COUNT + 1)); }

cleanup() { local rc=$?; [ "${KEEP:-0}" = "1" ] || rm -rf "$TEST_ROOT"; exit "$rc"; }
trap cleanup EXIT INT TERM

extract_block() {  # <start regex> <end regex, first match at or after start>
    local start end
    start=$(grep -n -m1 "$1" "$SCRIPT" | cut -d: -f1)
    [ -n "$start" ] || { echo "cannot find '$1' in $SCRIPT" >&2; exit 2; }
    end=$(awk -v s="$start" -v pat="$2" 'NR >= s && $0 ~ pat { print NR; exit }' "$SCRIPT")
    sed -n "${start},${end}p" "$SCRIPT"
}

echo "=== A. Function-level: _mark_done_file / _marked_done_this_week ==="
export LOG_DIR="$TEST_ROOT/logs"
mkdir -p "$LOG_DIR"
eval "$(extract_block '^_mark_done_file() {' '^}')"
eval "$(extract_block '^_marked_done_this_week() {' '^}')"

if _marked_done_this_week session-prep; then fail "A1: unmarked scenario reads as marked"; else pass "A1: unmarked scenario is not marked"; fi

touch "$(_mark_done_file session-prep "$(date +%G-W%V)")"
if _marked_done_this_week session-prep; then pass "A2: marking this week is seen immediately"; else fail "A2: mark not detected"; fi
if _marked_done_this_week week-review; then fail "A3: marking one scenario leaked into another"; else pass "A3: scenarios stay independent"; fi

touch "$(_mark_done_file week-review "2020-W01")"
if _marked_done_this_week week-review; then fail "A4: a mark for a past week counted for the current week"; else pass "A4: marks are week-specific, not scenario-wide"; fi

echo ""
echo "=== B. End to end: the real 'mark-done' CLI subcommand ==="
TEST_HOME="$TEST_ROOT/home"
mkdir -p "$TEST_HOME/IWE"

run_cli() { HOME="$TEST_HOME" bash "$SCRIPT" mark-done "$@"; }

if out=$(run_cli bogus-scenario 2>&1); then
    fail "B1: unknown scenario name was accepted"
else
    case "$out" in *"week-review или session-prep"*) pass "B1: unknown scenario name rejected with an actionable message" ;;
        *) fail "B1: rejected for the wrong reason: $out" ;;
    esac
fi

if out=$(run_cli week-review --week not-a-week 2>&1); then
    fail "B2: malformed --week was accepted"
else
    case "$out" in *"YYYY-Www"*) pass "B2: malformed --week rejected with the expected format hint" ;;
        *) fail "B2: rejected for the wrong reason: $out" ;;
    esac
fi

if out=$(run_cli session-prep --bogus-flag 2>&1); then
    fail "B3: unknown flag was accepted"
else
    pass "B3: unknown flag rejected"
fi

CURRENT_WEEK=$(date +%G-W%V)
run_cli week-review >/dev/null
MARK_FILE="$TEST_HOME/logs/strategist/mark-done-week-review-$CURRENT_WEEK"
if [ -f "$MARK_FILE" ]; then pass "B4: 'mark-done week-review' (default week) creates the current week's marker"; else fail "B4: marker file not created at $MARK_FILE"; fi

run_cli week-review --clear >/dev/null
if [ -f "$MARK_FILE" ]; then fail "B5: --clear did not remove the marker"; else pass "B5: --clear removes the marker"; fi

run_cli session-prep --week 2099-W05 >/dev/null
EXPLICIT_FILE="$TEST_HOME/logs/strategist/mark-done-session-prep-2099-W05"
if [ -f "$EXPLICIT_FILE" ]; then pass "B6: an explicit --week is honored over today's week"; else fail "B6: explicit --week ignored"; fi

echo ""
echo "============================================"
echo "  Results: $PASS_COUNT PASS, $FAIL_COUNT FAIL"
echo "============================================"
[ "$FAIL_COUNT" -eq 0 ]
