---
name: using-git-worktrees
description: Use when starting feature work that needs isolation from current workspace or before executing implementation plans - ensures an isolated workspace exists via native tools or git worktree fallback
---

# Using Git Worktrees

## Overview

Ensure work happens in an isolated workspace. Prefer your platform's native worktree tools. Fall back to manual git worktrees only when no native tool is available.

**Core principle:** Detect existing isolation first. Then use native tools. Then fall back to git. Never fight the harness.

**Announce at start:** "I'm using the using-git-worktrees skill to set up an isolated workspace."

## Step 0: Detect Existing Isolation

**Before creating anything, check if you are already in an isolated workspace.**

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

**Submodule guard:** `GIT_DIR != GIT_COMMON` is also true inside git submodules. Before concluding "already in a worktree," verify you are not in a submodule:

```bash
# If this returns a path, you're in a submodule, not a worktree — treat as normal repo
git rev-parse --show-superproject-working-tree 2>/dev/null
```

**If `GIT_DIR != GIT_COMMON` (and not a submodule):** You are already in a linked worktree. Skip to Step 3 (Project Setup). Do NOT create another worktree.

Report with branch state:
- On a branch: "Already in isolated workspace at `<path>` on branch `<name>`."
- Detached HEAD: "Already in isolated workspace at `<path>` (detached HEAD, externally managed). Branch creation needed at finish time."

**If `GIT_DIR == GIT_COMMON` (or in a submodule):** You are in a normal repo checkout.

Has the user already indicated their worktree preference in your instructions? If not, ask for consent before creating a worktree:

> "Would you like me to set up an isolated worktree? It protects your current branch from changes."

Honor any existing declared preference without asking. If the user declines consent, work in place and skip to Step 3.

## Step 1: Create Isolated Workspace

### Use `EnterWorktree` (required)

Call the `EnterWorktree` tool. It creates a worktree inside `.claude/worktrees/` and **switches the session's working directory** into it. This is the only mechanism that works mid-session — `git worktree add` + `cd` in bash does NOT change the session's CWD, so Read/Edit/Write/subagents will still target the original directory.

```
EnterWorktree({ name: "feat/my-feature" })
```

To enter an existing worktree instead of creating one:
```
EnterWorktree({ path: "/path/to/existing/worktree" })
```

**When done:** Use `ExitWorktree` with `action: "keep"` (preserve work) or `action: "remove"` (clean exit).

**If `EnterWorktree` is unavailable or fails:**

<HARD-GATE>
Do NOT silently fall back to working in the current directory. This was a major source of bugs — agents thought they were isolated but were modifying the main workspace.

You MUST:
1. **Stop and warn the user explicitly:** "I cannot create an isolated worktree mid-session. Working in-place risks modifying your current branch."
2. **Wait for the user to choose:**
   - Work on a new branch in the current directory (less isolation, user accepts risk)
   - The user creates a worktree manually and starts a new session from it: `git worktree add .worktrees/feat-x -b feat/x && cd .worktrees/feat-x`
3. **Do not proceed with implementation until the user responds.**
</HARD-GATE>

## Step 3: Project Setup

Auto-detect and run appropriate setup:

```bash
# Node.js
if [ -f package.json ]; then npm install; fi

# Rust
if [ -f Cargo.toml ]; then cargo build; fi

# Python
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
if [ -f pyproject.toml ]; then poetry install; fi

# Go
if [ -f go.mod ]; then go mod download; fi
```

## Step 4: Verify Clean Baseline

Run tests to ensure workspace starts clean:

```bash
# Use project-appropriate command
npm test / cargo test / pytest / go test ./...
```

**If tests fail:** Report failures, ask whether to proceed or investigate.

**If tests pass:** Report ready.

### Report

```
Worktree ready at <full-path>
Tests passing (<N> tests, 0 failures)
Ready to implement <feature-name>
```

## Quick Reference

| Situation | Action |
|-----------|--------|
| Already in linked worktree | Skip creation (Step 0) |
| In a submodule | Treat as normal repo (Step 0 guard) |
| `EnterWorktree` available | Use it (Step 1) |
| `EnterWorktree` unavailable | Offer branch-in-place or manual worktree + new session |
| Tests fail during baseline | Report failures + ask |
| No package.json/Cargo.toml | Skip dependency install |

## Red Flags

- Never create a worktree when Step 0 detects existing isolation
- Never use `git worktree add` mid-session — it doesn't switch the session CWD. Use `EnterWorktree`.
- Never proceed with failing baseline tests without asking
