---
name: requesting-code-review
description: Use for ad-hoc code review — when stuck, before refactoring, or for a fresh perspective outside the normal workflow review gates
---

# Requesting Code Review

Dispatch a review for a fresh perspective on work in progress. This skill is for **ad-hoc reviews** outside the normal workflow gates (which handle reviews automatically).

**When the automated pipeline handles it:**
- Per-task review → `*-quality-reviewer` agents (subagent-driven-development)
- Pre-merge review → `*-review` skills (verification-before-completion)
- Commit gate → `*-review-lite` agents (executing-plans)

**When to use this skill instead:**
- Stuck and want a fresh perspective
- Before a major refactor (baseline check)
- After fixing a complex bug (confidence check)
- Any time you want an independent review outside the normal flow

## How to Request

### Option A: Scope-matched review (preferred)

Dispatch the matching `*-review` skill based on file types changed — same mechanism as verification-before-completion Step 3:

1. Check which file types were modified
2. Match against `*-review` skills by `scope.extensions`
3. Invoke the matched skill(s)

This gives you the senior-level refactoring review with all the embedded principles.

### Option B: Git-range review (for cross-cutting changes)

When changes span multiple languages or don't fit a single `*-review` skill, dispatch a general reviewer with a git range:

```bash
BASE_SHA=$(git merge-base HEAD main)  # or specific commit
HEAD_SHA=$(git rev-parse HEAD)
```

Dispatch using `./code-reviewer.md` template:

```
Agent tool:
  model: opus
  description: "Review code changes"
  prompt: [fill template with DESCRIPTION, PLAN_OR_REQUIREMENTS, BASE_SHA, HEAD_SHA]
```

## Acting on Feedback

- **Critical:** Fix immediately
- **Important:** Fix before proceeding
- **Minor:** Note for later
- **Disagree:** Push back with technical reasoning — reviewers can be wrong
