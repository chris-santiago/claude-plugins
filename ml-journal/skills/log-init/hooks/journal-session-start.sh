#!/usr/bin/env bash
# journal-session-start.sh — Inject latest checkpoint as session context on startup
#
# Fires on SessionStart hook.
# If the repo's journal has a checkpoint and this machine trusts the repo
# (per-user trust list; see default_data_dir() in journal_common.py), emits it
# as additionalContext so Claude sees it at session open. For an untrusted repo
# the checkpoint text comes from the repo and is never injected; a fixed notice
# is emitted instead. If the repo still uses the legacy layout (scripts copied
# into .project-log/), adds a note to upgrade via /log-init. Exits silently if
# not in a repo, or there is no checkpoint, untrusted notice, or legacy note.

set -euo pipefail

# jq builds the hook's JSON output; without it, stay silent rather than error.
command -v jq >/dev/null 2>&1 || exit 0

# shellcheck source=journal-hook-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/journal-hook-lib.sh"
journal_hook_init

# --- Latest checkpoint (empty if none, or if the script refuses the journal) ---
# Exit 3 means a checkpoint exists but the repo is untrusted: discard the output.
UNTRUSTED=0
STATUS=0
CHECKPOINT_OUTPUT="$(python3 -I "$SCRIPTS_DIR/journal_query.py" --latest-checkpoint --trusted-only 2>/dev/null)" || STATUS=$?
case "$STATUS" in
    0) ;;
    3) UNTRUSTED=1; CHECKPOINT_OUTPUT="" ;;
    *) CHECKPOINT_OUTPUT="" ;;
esac
# Match the sentinel line exactly so a real checkpoint that merely mentions the
# phrase is still injected.
[ "$CHECKPOINT_OUTPUT" = "No checkpoint found in journal." ] && CHECKPOINT_OUTPUT=""

# --- Assemble context (printf expands \n into real newlines) ---
CONTEXT=""
if [ -n "$CHECKPOINT_OUTPUT" ]; then
    CONTEXT="$(printf 'A session checkpoint was found in this project journal. Here is the latest state:\n\n%s\n\nRun `/resume` to acknowledge this state and decide how to proceed. Run `/log-status` for a full journal overview.' "$CHECKPOINT_OUTPUT")"
elif [ "$UNTRUSTED" = 1 ]; then
    CONTEXT='This repo has an ml-journal checkpoint that was not loaded: this machine has not trusted this repo'"'"'s journal, and its text comes from the repo. Tell the user. They can run `/resume` to view it once, or `/log-init` to trust this repo so checkpoints load automatically.'
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
