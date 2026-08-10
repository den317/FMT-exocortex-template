#!/usr/bin/env bash
# Regression test: compiled role runners dispatch Codex with its supported
# non-interactive interface. It never contacts a model or GitHub: a mock
# `codex` records the arguments that a scheduled run would use.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_RUNTIME="$SCRIPT_DIR/build-runtime.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/iwe-codex-runners.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

WORKSPACE="$TEST_ROOT/workspace"
TEST_HOME="$TEST_ROOT/home"
FAKE_BIN="$TEST_ROOT/bin"
ENV_FILE="$WORKSPACE/.exocortex.env"
MOCK_ARGS="$TEST_ROOT/codex-args"

mkdir -p "$WORKSPACE/DS-strategy" "$TEST_HOME" "$FAKE_BIN"
printf 'export IWE_GOVERNANCE_REPO="DS-strategy"\n' > "$TEST_HOME/.iwe-paths"
cat > "$ENV_FILE" <<EOF
GITHUB_USER="test-user"
WORKSPACE_DIR="$WORKSPACE"
CLAUDE_PATH="codex"
CLAUDE_PROJECT_SLUG="-tmp-iwe-codex-runners"
TIMEZONE_HOUR="4"
TIMEZONE_DESC="4:00 UTC"
HOME_DIR="$TEST_HOME"
GOVERNANCE_REPO="DS-strategy"
IWE_TEMPLATE="$TEMPLATE_DIR"
IWE_RUNTIME="$WORKSPACE/.iwe-runtime"
EOF

cat > "$FAKE_BIN/codex" <<'EOF'
#!/bin/sh
: "${MOCK_ARGS:?MOCK_ARGS is required}"
printf '%s\n' "$@" > "$MOCK_ARGS"
EOF
chmod 700 "$FAKE_BIN/codex"

assert_codex_args() {
    local runner="$1"
    local expected_cwd="$2"
    local expected
    for expected in exec --ephemeral --sandbox workspace-write --approve-for-me -C "$expected_cwd"; do
        if ! grep -Fqx -- "$expected" "$MOCK_ARGS"; then
            echo "FAIL: $runner did not pass expected Codex argument: $expected" >&2
            return 1
        fi
    done
    if grep -Eq -- '--dangerously|--allowedTools|^-p$' "$MOCK_ARGS"; then
        echo "FAIL: $runner passed a Claude-only or unsafe Codex flag" >&2
        return 1
    fi
}

PATH="$FAKE_BIN:$PATH" bash "$BUILD_RUNTIME" --workspace "$WORKSPACE" --env-file "$ENV_FILE" --quiet

env PATH="$FAKE_BIN:$PATH" \
    HOME="$TEST_HOME" \
    IWE_TEMPLATE="$TEMPLATE_DIR" \
    IWE_WORKSPACE="$WORKSPACE" \
    IWE_RUNTIME="$WORKSPACE/.iwe-runtime" \
    IWE_GOVERNANCE_REPO="DS-strategy" \
    AI_CLI="codex" \
    CLAUDE_CLI_PATH="$FAKE_BIN/codex" \
    MOCK_ARGS="$MOCK_ARGS" \
    bash "$WORKSPACE/.iwe-runtime/roles/strategist/scripts/strategist.sh" day-plan
assert_codex_args strategist "$WORKSPACE/DS-strategy"

rm -f "$MOCK_ARGS"
env PATH="$FAKE_BIN:$PATH" \
    HOME="$TEST_HOME" \
    IWE_TEMPLATE="$TEMPLATE_DIR" \
    IWE_WORKSPACE="$WORKSPACE" \
    IWE_RUNTIME="$WORKSPACE/.iwe-runtime" \
    IWE_GOVERNANCE_REPO="DS-strategy" \
    AI_CLI="codex" \
    CLAUDE_CLI_PATH="$FAKE_BIN/codex" \
    MOCK_ARGS="$MOCK_ARGS" \
    bash "$WORKSPACE/.iwe-runtime/roles/extractor/scripts/extractor.sh" on-demand
assert_codex_args extractor "$WORKSPACE"

echo "codex role runner tests passed"
