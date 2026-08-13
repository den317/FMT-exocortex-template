#!/usr/bin/env bash
# Verifies WP-34 default owner-repository routing.
set -euo pipefail

TEMPLATE_ROOT=$(cd "$(dirname "$0")/../.." && pwd)

run_case() {
  local expected_repo=$1
  shift
  local root
  root=$(mktemp -d)

  cp -R "$TEMPLATE_ROOT/seed/strategy" "$root/DS-strategy"
  # shellcheck source=lib/seed_strategy_fixture.sh
  source "$TEMPLATE_ROOT/scripts/tests/lib/seed_strategy_fixture.sh"
  ensure_weekplan_fixture "$root/DS-strategy"

  mkdir -p "$root/FMT-exocortex-template/scripts"
  cat > "$root/FMT-exocortex-template/scripts/wp-github-link.py" <<'FAKE'
#!/usr/bin/env python3
import os, sys
with open(os.environ["LINK_LOG"], "w", encoding="utf-8") as out:
    out.write("\n".join(sys.argv[1:]))
FAKE
  chmod +x "$root/FMT-exocortex-template/scripts/wp-github-link.py"
  cat > "$root/params.yaml" <<'YAML'
github_wp_sync_enabled: true
github_owner: "den317"
github_wp_default_repo: "DS-strategy"
YAML

  LINK_LOG="$root/link.log" IWE_ROOT="$root" IWE_GOVERNANCE_REPO=DS-strategy \
    bash "$TEMPLATE_ROOT/scripts/create-wp.sh" \
      --title "Default repo test" --budget 1h --priority P4 \
      --hypothesis "—:infra" --hypothesis-relation operational \
      --no-consent-check "$@" >/dev/null

  grep -Fx -- "$expected_repo" "$root/link.log" >/dev/null || {
    echo "FAIL: expected repo $expected_repo" >&2
    cat "$root/link.log" >&2
    return 1
  }
  rm -rf "$root"
}

run_case "den317/DS-strategy"
run_case "den317/IWE" --repo IWE
echo "PASS: DS-strategy is default and explicit --repo wins"
