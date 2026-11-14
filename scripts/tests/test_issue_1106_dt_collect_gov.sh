#!/usr/bin/env bash
# issue #1106: dt-collect.sh resolved GOVERNANCE_DIR with a literal
# "DS-strategy" fallback, ignoring IWE_GOVERNANCE_REPO — unlike every
# comparable script in this codebase (roles/strategist/scripts/strategist.sh,
# roles/synchronizer/scripts/daily-report.sh, roles/synchronizer/scripts/
# templates/*.sh, roles/extractor/scripts/extractor.sh all nest
# "${IWE_GOVERNANCE_REPO:-DS-strategy}"). No regression test covered this
# resolution before (see setup/detector-fixtures/detector_07/ for the
# separate regex-gap regression that let the hardcode itself go unnoticed).
#
# This runs the REAL script through its public --dry-run interface against
# a disposable workspace — no internals poked directly, no network (HOME is
# redirected so ~/.config/aist/env is never sourced, WAKATIME_API_KEY/
# NEON_URL/DT_USER_ID are explicitly unset so collect_wakatime() short-
# circuits and the Neon-write branch is skipped by --dry-run itself).
#
# Observable result: collect_registry() counts literal "| ✅" occurrences in
# $GOVERNANCE_DIR/docs/WP-REGISTRY.md and reports it as
# .["2_7_iwe"].registry_done in the dry-run JSON. Pointing IWE_GOVERNANCE_REPO
# at a repo name that only exists under that name proves GOVERNANCE_DIR
# actually followed the override rather than a hardcoded default.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/roles/synchronizer/scripts/dt-collect.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail=0
mkdir -p "$TMP/home"

registry_done_count() {
    # Reads dry-run JSON on stdin, prints .["2_7_iwe"].registry_done (or a
    # diagnostic string) so callers get an observable, comparable value.
    python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('2_7_iwe', {}).get('registry_done', 'MISSING'))
except Exception as e:
    print('PARSE_ERROR:' + str(e))
"
}

# --- Case 1: IWE_GOVERNANCE_REPO set to a non-default repo name, and ONLY
# that repo populated — a hardcoded "DS-strategy" fallback would find
# nothing (the directory doesn't exist at all in this workspace).
WS1="$TMP/ws-custom"
mkdir -p "$WS1/custom-gov-repo/docs"
cat > "$WS1/custom-gov-repo/docs/WP-REGISTRY.md" <<'EOF'
| # | P | Название | Ст | Репо | Бюджет |
|---|---|----------|----|------|--------|
| 1 | P1 | Test WP | ✅ | custom-gov-repo | 1h |
EOF

out1=$(env -u WAKATIME_API_KEY -u NEON_URL -u DT_USER_ID -u GOVERNANCE_DIR \
    HOME="$TMP/home" IWE_WORKSPACE="$WS1" IWE_GOVERNANCE_REPO="custom-gov-repo" \
    bash "$SCRIPT" --dry-run 2>"$TMP/case1.log")
done1=$(printf '%s' "$out1" | registry_done_count)
if [ "$done1" != "1" ]; then
    echo "FAIL (case 1): IWE_GOVERNANCE_REPO=custom-gov-repo — expected registry_done=1, got '$done1'" >&2
    echo "--- stderr ---" >&2
    cat "$TMP/case1.log" >&2
    fail=1
fi

# --- Case 2: no override at all — must still fall back to "DS-strategy"
# (regression guard: the fix must not break the zero-config default).
WS2="$TMP/ws-default"
mkdir -p "$WS2/DS-strategy/docs"
cat > "$WS2/DS-strategy/docs/WP-REGISTRY.md" <<'EOF'
| # | P | Название | Ст | Репо | Бюджет |
|---|---|----------|----|------|--------|
| 1 | P1 | Test WP A | ✅ | DS-strategy | 1h |
| 2 | P1 | Test WP B | ✅ | DS-strategy | 1h |
EOF

out2=$(env -u WAKATIME_API_KEY -u NEON_URL -u DT_USER_ID -u GOVERNANCE_DIR -u IWE_GOVERNANCE_REPO \
    HOME="$TMP/home" IWE_WORKSPACE="$WS2" \
    bash "$SCRIPT" --dry-run 2>"$TMP/case2.log")
done2=$(printf '%s' "$out2" | registry_done_count)
if [ "$done2" != "2" ]; then
    echo "FAIL (case 2): no IWE_GOVERNANCE_REPO override — expected registry_done=2 (DS-strategy default), got '$done2'" >&2
    echo "--- stderr ---" >&2
    cat "$TMP/case2.log" >&2
    fail=1
fi

if [ "$fail" -eq 0 ]; then
    echo "✅ issue #1106 (dt-collect.sh GOVERNANCE_DIR resolution): OK"
fi
exit "$fail"
