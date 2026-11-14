#!/bin/bash
# Detector #7 fixture (issue #1106, mutation-testing round 1, mutant 2):
# bare path segment with no trailing slash or quote right after the
# literal. The old regex required "/DS-strategy/" (trailing slash) or
# "/DS-strategy\"" — a bare "&&"-continuation after it matched neither.
cd "$WORKSPACE"/DS-strategy && ls
