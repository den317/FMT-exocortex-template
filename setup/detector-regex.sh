#!/bin/bash
# detector-regex.sh — shared source-of-truth для regex'ов detector'ов.
#
# Цель: устранить DRY-нарушение (regex дублировался в integration-contract-validator.sh
# и test-detectors.sh — при правке regex в одном месте второе расходилось).
# Найдено: subagent post-release verify 0.29.18.
#
# Usage:
#   source "$(dirname "$0")/detector-regex.sh"
#   if grep -qE "$DETECTOR_07_REGEX" "$file"; then ...
#
# При добавлении detector_08+ — пополнять этот файл, source'ить из обоих скриптов.
#
# see VR.SC.006 (release-verification-protocol), VR.M.006 (5-layer verification)

# Detector #7: prompts_python_shell_coverage — bare DS-strategy в
# prompts/.py/.sh файлах.
# История regex: 0.29.5 базовый, 0.29.14 расширен на backtick+slash паттерн
# (subagent post-release verify нашёл gap, Євгений нашёл бы на fresh clone).
# issue #748 (post-release audit v0.40.0): расширен на голый quoted-литерал
# ("DS-strategy" / 'DS-strategy', без trailing слэша) — пример-YAML/значение
# в markdown-промпте, не только путь.
# issue #1106 (post-release audit v0.41.5/v0.41.6, two independent rounds):
# та версия перечисляла формы по одной (backtick+slash, quoted) и пропускала
# всё остальное — 5, затем ~16 найденных mutant-форм (quote-then-slash,
# bare path segment без trailing-символа, parens, tilde-path, .git suffix,
# конец строки после пробела и т.д.), включая РЕАЛЬНЫЙ хардкод в
# roles/synchronizer/scripts/dt-collect.sh:37 (GOVERNANCE_DIR игнорировал
# IWE_GOVERNANCE_REPO). Заменили перечисление форм на настоящую границу
# слова: совпадение только если по обе стороны от "DS-strategy" стоит НЕ
# [A-Za-z0-9_-] (или начало/конец строки) — дефис внутри самого токена
# ("DS-strategy") не считается границей, поэтому `${IWE_GOVERNANCE_REPO:-
# DS-strategy}`/`${GOVERNANCE_REPO:-DS-strategy}` (легитимный bash-fallback,
# дефис от ":-" стоит вплотную к "D") по-прежнему НЕ матчится этим regex'ом —
# они остаются на попечении per-line whitelist'а в integration-contract-
# validator.sh (который проверяет конкретное имя переменной перед ":-", а
# не любое).
export DETECTOR_07_REGEX='(^|[^A-Za-z0-9_-])[Dd][Ss]-[Ss][Tt][Rr][Aa][Tt][Ee][Gg][Yy]([^A-Za-z0-9_-]|$)'

# (При добавлении detector_08+ — добавлять здесь как DETECTOR_NN_REGEX)
