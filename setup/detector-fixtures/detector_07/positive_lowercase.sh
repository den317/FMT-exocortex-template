#!/bin/bash
# Detector #7 fixture (issue #1224): lowercase mutant. GitHub resolves
# repository URLs case-insensitively (redirects to the canonical spelling),
# so this mutant is functionally equivalent to the hardcoded "DS-strategy"
# the detector exists to catch, and used to slip past it entirely.
GOV='ds-strategy'
