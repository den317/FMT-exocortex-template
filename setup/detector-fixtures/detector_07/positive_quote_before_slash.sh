#!/bin/bash
# Detector #7 fixture (issue #1106, mutation-testing round 1, mutant 1):
# a quote sits directly BEFORE the slash. The old regex's "/DS-strategy[/\"]"
# alternative required a slash or quote right AFTER "DS-strategy", not
# before — this form slipped through as false-green.
REG="DS-strategy/docs/WP-REGISTRY.md"
