# journal-hook-lib.sh — Shared setup for the ml-journal hooks (sourced, not run)
#
# The hooks fire in every repo, so everything in the working tree is untrusted.
# They only ever run the scripts next to them in skills/log-init/, which also
# refuse a symlinked .project-log/ or journal. They live inside the skill so a
# manual skills-only install (no plugin system) carries them too.

# Sets REPO_ROOT, JOURNAL and SCRIPTS_DIR, or exits 0 silently when the hook
# should not act: not a git repo, or no journal.
journal_hook_init() {
    REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
    JOURNAL="$REPO_ROOT/.project-log/journal.jsonl"
    [ -f "$JOURNAL" ] || exit 0
    SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts" && pwd)"
}

# True when the repo still has the legacy layout: journal scripts copied into
# .project-log/ by an older /log-init. Checks existence only; never runs them.
journal_hook_is_legacy() {
    local name
    for name in journal_log.py journal_query.py; do
        if [ -e "$REPO_ROOT/.project-log/$name" ] || [ -L "$REPO_ROOT/.project-log/$name" ]; then
            return 0
        fi
    done
    return 1
}
