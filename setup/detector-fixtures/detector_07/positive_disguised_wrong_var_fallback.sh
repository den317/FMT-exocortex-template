#!/bin/bash
# Detector #7 fixture (issue #1106, mutation-testing round 2 — the
# "disguised fallback" trap): looks like a parameter-expansion default, but
# the variable is NOT the governance-repo override (real shape of the live
# bug this issue found: roles/synchronizer/scripts/dt-collect.sh used
# GOVERNANCE_DIR, a self-referential local variable, as the ":-" operand
# instead of IWE_GOVERNANCE_REPO). $DETECTOR_07_REGEX must still flag this
# as a raw candidate — the variable-name check that actually clears a
# *legitimate* fallback (IWE_)?GOVERNANCE_REPO lives one layer up, in
# integration-contract-validator.sh's per-line whitelist. This fixture only
# proves the base regex doesn't wave it through on sight of "${...:-".
SOME_OTHER_DIR="${SOME_OTHER_VAR:-$WORKSPACE/DS-strategy}"
