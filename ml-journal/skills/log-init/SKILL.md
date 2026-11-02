---
name: log-init
description: Initialize the project journal in the current git repo, or upgrade a repo set up with an older ml-journal (scripts copied into .project-log/). Creates .project-log/journal.jsonl only; all journal code runs from the installed skills. Use when the user says /log-init, "set up journal", "initialize journal", "set up project logging", or "upgrade the journal".
---

All journal code runs from the installed ml-journal skills (plugin or manual copy); a repo holds data only (`.project-log/journal.jsonl`). In the steps below, `SETUP` means:

```bash
python3 -I "${CLAUDE_SKILL_DIR}/scripts/journal_setup.py"
```

Trust is recorded in a per-user list outside any repo (`~/.local/share/ml-journal/trusted-repos.json`; `$XDG_DATA_HOME/ml-journal/` instead when `XDG_DATA_HOME` is an absolute path). Only trusted journals have their checkpoints loaded automatically at session start.

## Step 1: Inspect

Run `SETUP inspect --plugin-root "${CLAUDE_PLUGIN_ROOT}"`. The plugin root is passed as data, never as a path: it is substituted only when ml-journal is installed as a plugin, so `inspect` uses it to tell the two install types apart. Pass it exactly as written, even if it appears unsubstituted: outside a plugin it is meant to expand to empty, and a guessed path would misreport the install. If it fails because this is not a git repo, tell the user and stop.

The JSON report gives `journal_exists`, `trusted`, `legacy_copies`, `needs_upgrade`, `claude_md` (`exists`, `symlinked`, `stale_sections`, `customized_sections`, `current_sections`, `absent_sections`, `unmanaged_refs`), and `hooks` (`plugin`, `settings`; used in Step 6).

## Step 2: Upgrade a legacy repo

If `needs_upgrade` is true: run `SETUP upgrade --dry-run` and show its output, including the diff. Explain in one line: older ml-journal copied its scripts into `.project-log/`; they are no longer used, and the journal data is not touched. Ask: `► Apply this upgrade? (y/n)`. On yes, run `SETUP upgrade` and show its output.

If `needs_upgrade` is false but `claude_md.unmanaged_refs` is not empty, there is nothing to apply; just list those lines.

Either way, `report` lines and `unmanaged_refs` are `CLAUDE.md` lines the upgrade does not edit. Tell the user to fix them by hand: they should call a journal skill (e.g. `/log-list`) instead of a script. If `claude_md.symlinked` is true, `CLAUDE.md` is a symlink, which the upgrade never reads or edits; say so, and suggest the user check its target by hand.

## Step 3: Initialize a new journal

Skip if `journal_exists` is true.

Tell the user `.project-log/journal.jsonl` will be created, and ask: `► Create it in <repo-root>? (y/n)`. On yes:

```bash
SETUP init
python3 -I "${CLAUDE_SKILL_DIR}/scripts/journal_log.py" --type memo --description "Journal initialized"
python3 -I "${CLAUDE_SKILL_DIR}/scripts/journal_query.py" --status
```

If any command fails, show the error and stop.

`SETUP init` also trusts the new journal on this machine, since the user just created it, unless the repo's git history already has a journal (one could arrive with a checkout). Relay its output.

## Step 4: Trust an existing journal

Skip if `trusted` is true, or if `SETUP init` printed `trusted:` in Step 3.

The journal already existed, or exists in the repo's git history (for example, a cloned repo, a new machine, a repo set up before trust was added, or one trusted by ml-journal 0.5, which kept trust elsewhere). Explain in one line that checkpoint text comes from the repo, so only trust journals written by the user or people they trust. Ask:
```
► Trust this repo's journal on this machine? Its latest checkpoint will then load automatically at session start. (y/n)
```
On yes, run `SETUP trust` and show its output. On no, say checkpoints will not load automatically and `/resume` will ask before showing one.

## Step 5: Offer CLAUDE.md journal sections

Skip if `claude_md.exists` is false or `claude_md.absent_sections` is empty.

Ask:
```
► Add journal sections to your CLAUDE.md?
  They tell Claude to consult the journal before planning, use /log-commit for
  commits, and propose logging decisions, discoveries, issues, resolutions,
  lessons, and results as they happen. You still confirm every entry. (y/n)
```

On yes, run `SETUP add-sections` and show its output.

## Step 6: Confirm

Tell the user what was done (upgraded, initialized, trusted, or already current), and list the available skills: `/log-entry`, `/checkpoint`, `/resume`, `/log-status`, `/log-list`, `/log-summarize`, `/log-commit`, `/research-note`, `/research-report`.

Then check `hooks` from the Step 1 report:
- `plugin` is false and `settings` is empty: ml-journal was installed by copying skills and no hooks are registered, so checkpoints are not auto-saved before compaction or loaded at session start. Say so, and offer `SETUP hook-config`, which prints the `hooks` block to merge into `~/.claude/settings.json`. Without hooks, `/checkpoint` and `/resume` do the same jobs by hand.
- `plugin` is true and `settings` is not empty: the hooks are registered twice (by the plugin and by hand), which writes duplicate checkpoints. Tell the user to remove the ml-journal hooks from the listed files.
- Otherwise say nothing about hooks.
