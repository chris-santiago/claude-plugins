#!/usr/bin/env bash
# journal-session-start.sh — Inject latest checkpoint as session context on startup
#
# Fires on SessionStart hook.
# If a journal with a checkpoint exists in the current repo, emits the latest
# checkpoint as additionalContext so Claude sees it at session open.
# Exits silently if not in a repo or no journal/checkpoint exists.

set -euo pipefail

# --- Find repo root ---
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0

# --- Check journal exists ---
JOURNAL="$REPO_ROOT/.project-log/journal.jsonl"
[ -f "$JOURNAL" ] || exit 0

# --- Check query script exists ---
QUERY_SCRIPT="$REPO_ROOT/.project-log/journal_query.py"
[ -f "$QUERY_SCRIPT" ] || exit 0

# --- Get latest checkpoint ---
CHECKPOINT_OUTPUT="$(python3 "$QUERY_SCRIPT" --latest-checkpoint 2>/dev/null)" || exit 0

# Exit silently if no checkpoint
echo "$CHECKPOINT_OUTPUT" | grep -q "No checkpoint found" && exit 0
[ -z "$CHECKPOINT_OUTPUT" ] && exit 0

# --- Emit additionalContext ---
CONTEXT="A session checkpoint was found in this project journal. Here is the latest state:\n\n$CHECKPOINT_OUTPUT\n\nRun \`/resume\` to acknowledge this state and decide how to proceed. Run \`/journal-status\` for a full journal overview."

jq -n --arg ctx "$CONTEXT" '{
  "additionalContext": $ctx
}'

exit 0
