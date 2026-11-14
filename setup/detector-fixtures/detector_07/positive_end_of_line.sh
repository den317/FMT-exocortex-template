#!/bin/bash
# Detector #7 fixture (issue #1106, mutation-testing round 2): literal at
# the very end of a line, right after a space, nothing trailing it (no
# slash / quote / brace). The old " DS-strategy[ /]" alternative required a
# trailing space or slash after the literal, which end-of-line doesn't
# provide.
cat <<MSG
Default governance repo is DS-strategy
MSG
