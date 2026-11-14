# Detector #7 fixture (issue #1106, mutation-testing round 1, mutant 5):
# single-quoted literal inside a function call, on the Python side. The old
# regex never applied to .py files at all for this quote style — only
# `"DS-strategy"` (double-quoted) was recognized, and only under roles/.
import os

path = os.path.join('/x', 'DS-strategy')
