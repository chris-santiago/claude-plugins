---
name: finishing-a-development-branch
description: Use when implementation is complete, all tests pass, and you need to decide how to integrate the work - guides completion of development work by presenting structured options for merge, PR, or cleanup
---

# Finishing a Development Branch

## Overview

Guide completion of development work by presenting clear options and handling chosen workflow.

**Core principle:** Verify tests → Detect environment → Present options → Execute choice → Clean up.

**Announce at start:** "I'm using the finishing-a-development-branch skill to complete this work."

## The Process

### Step 1: Verify Completion

**PREREQUISITE:** `chris-code:verification-before-completion` must have passed (tests, lints, full review, spec-blind intent re-check, and the mutation re-check when the user chose to run it), with `ledger.py triage --task close` at `done`. If it hasn't been run yet, invoke it now and wait for its close to finish before proceeding.

A green test suite, a `*-review-lite` commit gate, or the subagent-driven-development whole-change gate do not satisfy this prerequisite. Those are diff-level checks; the verification close adds three gates they never run: the `*-design-reviewer` cohesion review, the `intent-reviewer` spec-blind behavior check, and, when the user chooses it, the `mutation-tester` gate that proves the tests can actually detect a change. If all you have run is tests, lint, and a lite gate, you have not run verification-before-completion. Don't present integration options until its close has reached `done`: every blocking finding fixed and re-checked, deferred or ruled by the user.

### Step 2: Detect Environment

**Determine workspace state before presenting options:**

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
```

This determines which menu to show and how cleanup works:

| State | Menu | Cleanup |
|-------|------|---------|
| `GIT_DIR == GIT_COMMON` (normal repo) | Standard 4 options | No worktree to clean up |
| `GIT_DIR != GIT_COMMON`, named branch | Standard 4 options | Provenance-based (see Step 6) |
| `GIT_DIR != GIT_COMMON`, detached HEAD | Reduced 3 options (no merge) | No cleanup (externally managed) |

### Step 3: Determine Base Branch

```bash
# Try common base branches
git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null
```

Or ask: "This branch split from main - is that correct?"

### Step 4: Present Options

**Normal repo and named-branch worktree — present exactly these 4 options:**

```
Implementation complete. What would you like to do?

1. Merge back to <base-branch> locally
2. Push and create a Pull Request
3. Keep the branch as-is (I'll handle it later)
4. Discard this work

Which option?
```

**Detached HEAD — present exactly these 3 options:**

```
Implementation complete. You're on a detached HEAD (externally managed workspace).

1. Push as new branch and create a Pull Request
2. Keep as-is (I'll handle it later)
3. Discard this work

Which option?
```

**Don't add explanation** - keep options concise.

### Step 5: Execute Choice

#### Option 1: Merge Locally

The merge and its test run happen in the checkout that holds `<base-branch>`, so leave the worktree first. Before you leave it, note its path, and for an SDD run resolve `SDD_SCRIPTS` and `STORE` (Step 6): resolved from anywhere else, `STORE` names a different store.

- **A worktree this session entered with `EnterWorktree`:** call `ExitWorktree({ action: "keep" })`. It returns the session to the original checkout and leaves the worktree and its branch on disk. A `cd` in Bash is not a substitute: it doesn't move the session. Then run the block below without its first two lines.
- **Any other worktree, or a normal repo:** run the block below as written. Its `cd` holds for that one command.

If you can't tell which it is (after a compaction, say), call `ExitWorktree({ action: "keep" })`. Outside a worktree session it does nothing and says so, and then the second case applies.

```bash
# Skip these two lines when ExitWorktree already returned the session to the original checkout
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"

# Merge first — verify success before removing anything
git checkout <base-branch>
git pull
git merge <feature-branch>

# Verify tests on merged result
<test command>

# Only after merge succeeds: cleanup worktree (Step 6), then delete branch
```

Then: Cleanup worktree (Step 6), then delete branch:

```bash
git branch -d <feature-branch>
```

#### Option 2: Push and Create PR

```bash
# Push branch
git push -u origin <feature-branch>

# Create PR
gh pr create --title "<title>" --body "$(cat <<'EOF'
## Summary
<2-3 bullets of what changed>

## Test Plan
- [ ] <verification steps>

## Follow-ups
<open follow-ups and landed disclosures from `ledger.py report`, when an SDD run built the change; omit otherwise>
EOF
)"
```

**Do NOT clean up worktree** — user needs it alive to iterate on PR feedback. If you leave it, leave with `ExitWorktree({ action: "keep" })`.

#### Option 3: Keep As-Is

Report: "Keeping branch <name>. Worktree preserved at <path>."

**Don't cleanup worktree.** If you leave it, leave with `ExitWorktree({ action: "keep" })`.

#### Option 4: Discard

**Confirm first:**
```
This will permanently delete:
- Branch <name>
- All commits: <commit-list>
- Worktree at <path>

Type 'discard' to confirm.
```

Wait for exact confirmation.

If confirmed, run Step 6 (the run's store, then the worktree). Then force-delete the branch, if Step 6 left it:
```bash
git branch -D <feature-branch>
```

### Step 6: Cleanup Workspace

**Only runs for Options 1 and 4.** Options 2 and 3 always preserve the worktree.

#### The run's store

If an SDD run built the change, clean up its store before the worktree goes. `SDD_SCRIPTS` is `<this skill's base directory>/../subagent-driven-development/scripts`, and `STORE=$(python3 "$SDD_SCRIPTS/ledger.py" store-dir)`, or the session's `--store` override. Resolve `STORE` from inside the worktree: it is an absolute path, and `report` and `clear` find the run from it, so they still work once Option 1 has returned the session to the original checkout.

First run `python3 "$SDD_SCRIPTS/ledger.py" report --store "$STORE"` and give the user its open follow-ups and landed disclosures in your summary: removing the store destroys them.

Then clear the store, which also deletes the run's break-check copy and build cache from the system temp folder (deleting the store's folder alone would leave them):

```bash
python3 "$SDD_SCRIPTS/ledger.py" clear --store "$STORE"
```

`clear` refuses while follow-ups, disclosures or questions are open. The user has just seen them in the report: once they confirm it is their record of them, run it again with `--discard-open`.

Then remove the store's folder (task briefs, reports, review diffs, ledger records and progress log):

```bash
rm -rf "$STORE"   # the absolute path resolved above: `.sdd/` at the worktree's root, or the session's `--store` override
```

A store inside a worktree also goes when the worktree is removed below; the explicit removal covers a normal repo and a relocated store. Run `clear` either way: the copy and the cache live outside the worktree.

#### The worktree

Which case applies decides who removes it. We clean up only a worktree in one of our own locations: `.worktrees/`, `worktrees/`, `.claude/worktrees/`, or `~/.config/chris-code/worktrees/`.

**Normal repo** (`GIT_DIR == GIT_COMMON`, Step 2): no worktree to clean up. Done.

**A worktree this session entered with `EnterWorktree`,** in one of our locations. Leave it with `ExitWorktree` before anything removes it:

- *Option 1:* the session already left it with `ExitWorktree({ action: "keep" })` (Step 5). From the original checkout, remove what it kept:

  ```bash
  git worktree remove <the worktree's path>
  git worktree prune  # Self-healing: clean up any stale registrations
  ```

- *Option 4:* call `ExitWorktree({ action: "remove", discard_changes: true })`. The user's typed `discard` is the confirmation `discard_changes` needs. It returns the session to the original checkout and deletes the worktree and its branch. It won't remove a worktree the session entered by `path` (one made with `git worktree add`): leave that one with `action: "keep"`, then remove it from the original checkout with `git worktree remove --force <the worktree's path>`.

If `ExitWorktree` answers that no worktree session is active, the session didn't enter this worktree with the tool: treat it as the next case.

**A worktree the session didn't enter with the tool** (it started inside one made by hand), in one of our locations. The session can't leave it, so the commands run from the main repo root:

```bash
WORKTREE_PATH=$(git rev-parse --show-toplevel)
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
git worktree remove "$WORKTREE_PATH"
git worktree prune  # Self-healing: clean up any stale registrations
```

**Otherwise** (a worktree anywhere else, however the session got into it): The host environment (harness) or whoever made it owns this workspace. Do NOT remove it. If your platform provides a workspace-exit tool, use it. Otherwise, leave the workspace in place.

## Quick Reference

| Option | Merge | Push | Keep Worktree | Cleanup Branch |
|--------|-------|------|---------------|----------------|
| 1. Merge locally | yes | - | - | yes |
| 2. Create PR | - | yes | yes | - |
| 3. Keep as-is | - | - | yes | - |
| 4. Discard | - | - | - | yes (force) |

## Red Flags

- Never skip verification (invoke `chris-code:verification-before-completion` first)
- Never merge without verifying tests on the merged result
- Never delete work without typed "discard" confirmation
- Never force-push without explicit user request
- Never clean up worktrees you didn't create (provenance check)
- Never run `git worktree remove` from inside the worktree. Leave with `ExitWorktree` first when the session entered it with `EnterWorktree`, and `cd` to the main repo root otherwise
- Always remove worktree before deleting its branch (order matters)
- Only clean up worktrees for Options 1 and 4 — Option 2 (PR) needs the worktree alive
