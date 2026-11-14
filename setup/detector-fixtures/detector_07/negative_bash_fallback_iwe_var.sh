#!/bin/bash
# Detector #7 fixture (issue #1106): the canonical legitimate bash fallback,
# used throughout this codebase (roles/strategist/scripts/strategist.sh,
# roles/synchronizer/scripts/daily-report.sh, roles/synchronizer/scripts/
# templates/strategist.sh, templates/extractor.sh). The hyphen from the
# default-value operator sits directly against the first letter of the
# literal below — not a word boundary by this regex's definition (hyphen is
# a word character here, since the literal is itself hyphenated) — so this
# line must NOT match, same as before #1106.
# (Note for fixture maintainers: don't quote the literal by name in THIS
# comment block — test-detectors.sh scans the whole file with no
# comment-awareness, so a bare quoted mention here would false-match too.)
GOVERNANCE_DIR="${IWE_WORKSPACE:-$HOME/IWE}/${IWE_GOVERNANCE_REPO:-DS-strategy}"
