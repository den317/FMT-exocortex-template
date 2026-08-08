#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Load only the guard under test; sourcing update.sh would execute the updater.
eval "$(awk '
  /^validate_no_install_values_in_staged_additions\(\)/ { capture=1 }
  capture { print }
  capture && /^}/ { exit }
' "$ROOT/update.sh")"
declare -F validate_no_install_values_in_staged_additions >/dev/null

SCRIPT_DIR="$TMP/template"
WORKSPACE_DIR="$TMP/workspace"
mkdir -p "$SCRIPT_DIR" "$WORKSPACE_DIR"
git -C "$SCRIPT_DIR" init -q
git -C "$SCRIPT_DIR" config user.email test@example.invalid
git -C "$SCRIPT_DIR" config user.name 'Install path guard test'

cat >"$WORKSPACE_DIR/.exocortex.env" <<EOF
WORKSPACE_DIR=$WORKSPACE_DIR
HOME_DIR=/root
CLAUDE_PATH=/root/.claude
IWE_TEMPLATE=$SCRIPT_DIR
IWE_RUNTIME=$WORKSPACE_DIR/.iwe-runtime
EOF

# Existing tracked install-like values are outside the updater's responsibility.
# An unrelated staged addition must not be blocked by historical container docs.
cat >"$SCRIPT_DIR/existing.md" <<'EOF'
The container user has HOME=/root and stores Claude config in /root/.claude.
EOF
git -C "$SCRIPT_DIR" add existing.md
git -C "$SCRIPT_DIR" commit -qm baseline
printf 'Safe update line.\n' >>"$SCRIPT_DIR/existing.md"
git -C "$SCRIPT_DIR" add existing.md
APPLIED_PATHS=(existing.md)
validate_no_install_values_in_staged_additions

# A value newly introduced by the updater must still block the commit.
printf 'Leaked workspace: %s\n' "$WORKSPACE_DIR" >"$SCRIPT_DIR/leak.md"
git -C "$SCRIPT_DIR" add leak.md
APPLIED_PATHS=(existing.md)
validate_no_install_values_in_staged_additions

# Once the leaking path belongs to this updater run, the guard must reject it.
APPLIED_PATHS=(existing.md leak.md)
if validate_no_install_values_in_staged_additions 2>"$TMP/guard.err"; then
    echo 'guard accepted a newly added install value' >&2
    exit 1
fi
grep -Fq 'install-value WORKSPACE_DIR' "$TMP/guard.err"
if grep -Fq -- "$WORKSPACE_DIR" "$TMP/guard.err"; then
    echo 'guard disclosed the install value in diagnostics' >&2
    exit 1
fi

# Deleting a leaked value makes the tree safer and must not be rejected.
git -C "$SCRIPT_DIR" reset -q HEAD -- .
git -C "$SCRIPT_DIR" checkout -q -- .
printf 'legacy %s\nkeep\n' "$WORKSPACE_DIR" >"$SCRIPT_DIR/remove-leak.md"
git -C "$SCRIPT_DIR" add remove-leak.md
git -C "$SCRIPT_DIR" commit -qm 'add legacy fixture'
grep -v 'legacy' "$SCRIPT_DIR/remove-leak.md" >"$TMP/cleaned"
mv "$TMP/cleaned" "$SCRIPT_DIR/remove-leak.md"
git -C "$SCRIPT_DIR" add remove-leak.md
APPLIED_PATHS=(remove-leak.md)
validate_no_install_values_in_staged_additions

echo 'PASS: install-path guard checks only staged additions'
