#!/bin/bash
# claude-peer-adapter.sh — адаптер Claude для peer-conversation (роль напарника)
# see DP.SC.154 (симметричный аналог kimi-peer-adapter.sh)
#
# Вызывается агентом-ПИСАТЕЛЕМ (Kimi или другим) когда Claude выступает НАПАРНИКОМ.
# Принимает аргументы в стиле kimi-peer-adapter.sh, читает промпт из stdin,
# передаёт Claude headless (-p), возвращает ответ в stdout.
#
# Контракт безопасности (WP-458, WP-510): адаптер принимает только текстовую
# проекцию через stdin. Он не получает рабочих каталогов и не даёт Claude
# файловые или shell-инструменты.
# Использование:
#   bash scripts/claude-peer-adapter.sh < peer-prompt.md > peer.md 2> peer.err
# Промпт передаётся файлом, не inline `echo "$peer_prompt" | ...` — иначе текст
# промпта попадает в командную строку и хук B7.7c ложно блокирует повторные
# вызовы (bug-2026-06-30-peer-adapter-b77c-block).

set -euo pipefail

# Claude Code can access its macOS Keychain credentials only outside Codex's
# seatbelt. Running the adapter inside that sandbox produced intermittent blank
# output that looked like success. A caller must use the approved external
# route (`sandbox_permissions=require_escalated` in Codex); do not retry this
# branch or ask the pilot to run /login.
if [ "${CODEX_SANDBOX:-}" = "seatbelt" ]; then
  echo "ERROR: Claude peer adapter must run outside the Codex sandbox to access macOS Keychain. Re-run through the approved external route; /login is not required." >&2
  exit 69
fi

# CLAUDE_BIN auto-detect: env override → PATH → user-local fallbacks.
# Системные пути (homebrew, /usr/local/bin) обычно в PATH и подхватываются через command -v.
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || true)}"
if [ -z "$CLAUDE_BIN" ]; then
  for candidate in \
    "$HOME/.local/bin/claude" \
    "$HOME/.npm-global/bin/claude" \
    "$HOME/.nvm/versions/node/*/bin/claude"; do
    # Expand glob (для nvm-paths)
    for resolved in $candidate; do
      [ -x "$resolved" ] && CLAUDE_BIN="$resolved" && break 2
    done
  done
fi
if [ -z "$CLAUDE_BIN" ] || [ ! -x "$CLAUDE_BIN" ]; then
  echo "ERROR: claude binary not found. Install Claude CLI or set CLAUDE_BIN env var." >&2
  echo "  Install: https://docs.claude.com/en/docs/claude-code/setup" >&2
  exit 1
fi

# Модель не выбирает адаптер: без явного --model Claude CLI применяет свою
# настроенную по умолчанию модель. Это сохраняет разделение между личностью,
# каналом и конструктивной реализацией.
MODEL_ARG=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p)              shift ;;
    --model)
      [ $# -ge 2 ] || { echo "ERROR: --model requires a value" >&2; exit 1; }
      MODEL_ARG=("--model" "$2"); shift 2 ;;
    --add-dir)
      echo "ERROR: --add-dir is disabled for claude-peer-adapter.sh. Put a minimal text projection in stdin instead." >&2
      exit 64
      ;;
    --permission-mode)
      echo "ERROR: permission mode is fixed to dontAsk for claude-peer-adapter.sh." >&2
      exit 64
      ;;
    # WP-516 Ф5: неизвестный флаг — явная ошибка (§0в.1 whitelist: -p, --model,
    # --add-dir; у claude --add-dir и --permission-mode запрещены отдельно, выше).
    *)
      echo "ERROR: unknown flag '$1'. Known: -p, --model" >&2
      exit 1
      ;;
  esac
done

# Модель передаётся только при явном выборе вызывающего агента. Адаптер не
# назначает и не подменяет конструктивную реализацию напарника.

# WP-510 Ф17: text-only must be fail-closed. `plan` plus a deny-list did not
# provide that boundary: Claude could still call Agent, whose child discovered
# ToolSearch and MCP, then the parent timed out without stdout. `--safe-mode`
# removes project customizations/hooks/MCP, while the empty `--allowedTools` allow-list
# disables every tool namespace (including future tools not known today).
# `--no-session-persistence` prevents this ephemeral reviewer from leaving a
# resumable conversation. --add-dir remains forbidden above.
#
# This is still a Claude Code policy boundary, not an OS sandbox. Sensitive
# material requires a separately isolated runner and explicit pilot approval.
#
# perl alarm 300: 5-minute hard timeout, same as kimi-peer-adapter.sh.
# On timeout: SIGALRM → exit 142 → caller sees exit≠0 + empty file → reports to pilot.
#
# One turn is insufficient even for a text-only request: Claude can use it to
# formulate an internal plan, then exits with "Reached max turns (1)" before
# emitting the answer. Two turns preserve the no-tools boundary but guarantee
# one turn remains for delivery of the response (WP-7 Ф65).
CLAUDE_PEER_MAX_TURNS="${CLAUDE_PEER_MAX_TURNS:-2}"
case "$CLAUDE_PEER_MAX_TURNS" in
  ''|*[!0-9]*)
    echo "ERROR: CLAUDE_PEER_MAX_TURNS must be a positive integer." >&2
    exit 64
    ;;
esac
[ "$CLAUDE_PEER_MAX_TURNS" -ge 2 ] || {
  echo "ERROR: CLAUDE_PEER_MAX_TURNS must be at least 2 to reserve a response turn." >&2
  exit 64
}

CLAUDE_STDERR="$(mktemp)"
trap 'rm -f "$CLAUDE_STDERR"' EXIT

CLAUDE_OUTPUT=$(perl -e 'alarm 300; exec @ARGV' -- \
  "$CLAUDE_BIN" -p \
  --safe-mode \
  --allowedTools "" \
  --permission-mode dontAsk \
  --max-turns "$CLAUDE_PEER_MAX_TURNS" \
  --no-session-persistence \
  ${MODEL_ARG[@]+"${MODEL_ARG[@]}"} \
  "$@" 2>"$CLAUDE_STDERR") && CLAUDE_EXIT=0 || CLAUDE_EXIT=$?

# Auth-failure detection (peer-session 2026-08-04-08-wp7-f44-sandbox-review):
# macOS Keychain can be unreachable from a sandboxed child process (e.g. a
# Codex workspace-write sandbox) even when the pilot's own Claude Code login
# is valid — that surfaces as literal "Not logged in" text, not necessarily a
# non-zero exit. stderr is checked unconditionally (diagnostic channel);
# stdout only when the process itself also exited non-zero, so a genuine
# reply that happens to discuss login/auth text isn't misclassified as a
# failure (this environment discusses login issues often).
AUTH_PATTERN='Not logged in|Please run.*login'
if grep -qE "$AUTH_PATTERN" "$CLAUDE_STDERR" 2>/dev/null || \
   { [ "$CLAUDE_EXIT" -ne 0 ] && printf '%s' "$CLAUDE_OUTPUT" | grep -qE "$AUTH_PATTERN"; }; then
  echo "ERROR: Claude peer call looks unauthenticated (Not logged in). Common sandbox/Keychain artifact, not necessarily lost login — verify from a trusted terminal before re-running /login." >&2
  if [ -s "$CLAUDE_STDERR" ]; then
    echo "--- claude stderr (tail) ---" >&2
    tail -20 "$CLAUDE_STDERR" >&2
  fi
  # WP-516 Ф5: канонический код 6 = auth failure (§0в.1); ранее был 4,
  # что конфликтовало с фактическим «add-dir error» у kimi/codex-адаптеров.
  exit 6
fi

if [ "$CLAUDE_EXIT" -ne 0 ]; then
  echo "ERROR: Claude peer call failed with exit code $CLAUDE_EXIT." >&2
  [ -s "$CLAUDE_STDERR" ] && tail -20 "$CLAUDE_STDERR" >&2
  exit "$CLAUDE_EXIT"
fi

if ! printf '%s' "$CLAUDE_OUTPUT" | grep -q '[[:alnum:]]'; then
  echo "ERROR: Claude peer call returned no substantive response." >&2
  [ -s "$CLAUDE_STDERR" ] && tail -20 "$CLAUDE_STDERR" >&2
  # WP-516 Ф5: канонический код 7 = empty response after trimming (§0в.1);
  # ранее был 5, что переопределяло каноническое «pidfile lock».
  exit 7
fi

# WP-516 Ф5 (§0в.1): stdout обязан начинаться с frontmatter; ответ без
# frontmatter = нарушение формата → exit 1 с диагностикой.
# Проверка — для peer-реплик turn-loop. Служебные вызовы писателя
# (review/verify/synth), чей вывод — НЕ peer-реплика, отключают её
# через IWE_PEER_PLAIN=1 (слой IWE-интеграции, §0в.1).
if [ "${IWE_PEER_PLAIN:-0}" != "1" ]; then
  # awk одним процессом: 'sed | head' под pipefail ловит SIGPIPE на длинной
  # валидной реплике и роняет адаптер без диагностики (review-02, WP-516 Ф5).
  _FIRST_LINE=$(printf '%s\n' "$CLAUDE_OUTPUT" | awk 'length { print; exit }')
  _FM_FENCES=$(printf '%s\n' "$CLAUDE_OUTPUT" | grep -c '^---$' || true)
  if [ "$_FIRST_LINE" != "---" ] || [ "${_FM_FENCES:-0}" -lt 2 ]; then
    echo "ERROR: peer response missing frontmatter (first non-empty line must be '---' with a closing '---')." >&2
    exit 1
  fi
fi

printf '%s\n' "$CLAUDE_OUTPUT"
