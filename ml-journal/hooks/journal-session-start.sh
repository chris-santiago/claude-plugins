#!/usr/bin/env bash
# journal-session-start.sh — Inject latest checkpoint as session context on startup
#
# Fires on SessionStart hook.
# If the repo's journal has a checkpoint, emits it as additionalContext so
# Claude sees it at session open. If the repo still uses the legacy layout
# (scripts copied into .project-log/), adds a note to upgrade via /log-init.
# Exits silently if not in a repo, or there is neither a checkpoint nor a note.

set -euo pipefail

# jq builds the hook's JSON output; without it, stay silent rather than error.
command -v jq >/dev/null 2>&1 || exit 0

# shellcheck source=journal-hook-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/journal-hook-lib.sh"
journal_hook_init

# --- Latest checkpoint (empty if none, or if the script refuses the journal) ---
CHECKPOINT_OUTPUT="$(python3 -I "$SCRIPTS_DIR/journal_query.py" --latest-checkpoint 2>/dev/null)" || CHECKPOINT_OUTPUT=""
# Match the sentinel line exactly so a real checkpoint that merely mentions the
# phrase is still injected.
[ "$CHECKPOINT_OUTPUT" = "No checkpoint found in journal." ] && CHECKPOINT_OUTPUT=""

# --- Assemble context (printf expands \n into real newlines) ---
CONTEXT=""
if [ -n "$CHECKPOINT_OUTPUT" ]; then
    CONTEXT="$(printf 'A session checkpoint was found in this project journal. Here is the latest state:\n\n%s\n\nRun `/resume` to acknowledge this state and decide how to proceed. Run `/log-status` for a full journal overview.' "$CHECKPOINT_OUTPUT")"
fi
if journal_hook_is_legacy; then
    NOTICE='This repo uses the legacy ml-journal layout: journal scripts copied into .project-log/. Those copies are no longer used. Tell the user and suggest running `/log-init` to upgrade.'
    if [ -n "$CONTEXT" ]; then
        CONTEXT="$(printf '%s\n\n%s' "$CONTEXT" "$NOTICE")"
    else
        CONTEXT="$NOTICE"
    fi
fi
[ -n "$CONTEXT" ] || exit 0

# SessionStart context belongs under hookSpecificOutput; a top-level
# additionalContext is not part of the hook output schema and is dropped.
jq -n --arg ctx "$CONTEXT" '{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": $ctx
  }
}'

exit 0
