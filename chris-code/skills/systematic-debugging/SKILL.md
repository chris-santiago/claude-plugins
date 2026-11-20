---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** Find the root cause before attempting a fix. A fix aimed at the symptom leaves the cause in place and often adds a second bug.

If a step seems not to apply, do it anyway or ask. Don't decide on your own that its purpose is already met.

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for any technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Performance problems
- Build failures
- Integration issues

For a small bug each phase takes a minute. Scale the depth to the bug, not the order.

**Use this especially when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- Previous fix didn't work
- You don't fully understand the issue

**Don't skip when:**
- Issue seems simple (simple bugs have root causes too)
- You're in a hurry (rushing guarantees rework)
- Manager wants it fixed now (systematic is faster than thrashing)

## The Four Phases

Work the phases in order, finishing each before the next.

### Phase 1: Root Cause Investigation

**Before attempting any fix:**

1. **Read Error Messages Carefully**
   - Don't skip past errors or warnings
   - They often contain the exact solution
   - Read stack traces completely
   - Note line numbers, file paths, error codes

2. **Reproduce Consistently**
   - Can you trigger it reliably?
   - What are the exact steps?
   - Does it happen every time?
   - If not reproducible → gather more data, don't guess

3. **Check Recent Changes**
   - What changed that could cause this?
   - Git diff, recent commits
   - New dependencies, config changes
   - Environmental differences

4. **Gather Evidence in Multi-Component Systems**

   **When system has multiple components (CI → build → signing, API → service → database):**

   **Before proposing fixes, add diagnostic instrumentation:**
   ```
   For each component boundary:
     - Log what data enters component
     - Log what data exits component
     - Verify environment/config propagation
     - Check state at each layer

   Run once to gather evidence showing where it breaks
   Then analyze evidence to identify failing component
   Then investigate that specific component
   ```

   **This reveals:** Which layer fails (e.g., config → service ✓, service → database ✗)

5. **Check System Boundaries**
   - Bugs hide where assumptions diverge: FFI, serialization/deserialization, API layers, language boundaries
   - Each boundary can coerce types, lose nulls, change precision, or silently drop data
   - If the bug crosses a boundary, instrument both sides independently

6. **Trace Data Flow**

   **When error is deep in call stack:**

   See `root-cause-tracing.md` in this directory for the complete backward tracing technique.

   **Quick version:**
   - Where does bad value originate?
   - What called this with bad value?
   - Keep tracing up until you find the source
   - Fix at source, not at symptom

### Phase 2: Pattern Analysis

**Find the pattern before fixing:**

1. **Find Working Examples**
   - Locate similar working code in same codebase
   - What works that's similar to what's broken?

2. **Compare Against References**
   - If implementing pattern, read reference implementation completely
   - Don't skim - read every line
   - Understand the pattern fully before applying

3. **Identify Differences**
   - What's different between working and broken?
   - List every difference, however small
   - Don't assume "that can't matter"

4. **Understand Dependencies**
   - What other components does this need?
   - What settings, config, environment?
   - What assumptions does it make?

### Phase 3: Hypothesis and Testing

**Scientific method:**

1. **Form Single Hypothesis**
   - State clearly: "I think X is the root cause because Y"
   - Write it down
   - Be specific, not vague

2. **Test Minimally**
   - Make the smallest possible change to test hypothesis
   - One variable at a time
   - Don't fix multiple things at once

3. **Verify Before Continuing**
   - Did it work? Yes → Phase 4
   - Didn't work? Form new hypothesis
   - Don't add more fixes on top

4. **When You Don't Know**
   - Say "I don't understand X"
   - Don't pretend to know
   - Ask for help
   - Research more

### Phase 4: Implementation

**Fix the root cause, not the symptom:**

1. **Create Failing Test Case**
   - Simplest possible reproduction
   - Automated test if possible
   - One-off test script if no framework
   - Write it before the fix
   - Use `chris-code:test-driven-development` for writing proper failing tests
   - After the fix, invoke `chris-code:regression-test` to ensure full regression coverage (sibling paths, boundary cases, property assertions)

2. **Implement Single Fix**
   - Address the root cause identified
   - One change at a time
   - No "while I'm here" improvements
   - No bundled refactoring
   - The root cause is known, so the fix is now a *determined change*. When more than one implementation is plausible, hand it to `chris-code:coherent-change` — it researches the codebase's patterns, defends the most coherent implementation against the alternatives, implements it, and lite-reviews it before handing back. You then run this phase's close (the failing test from Step 1, regression coverage, verify).

3. **Verify Fix**
   - Test passes now?
   - No other tests broken?
   - Issue actually resolved?

4. **If Fix Doesn't Work**
   - Stop
   - Count: How many fixes have you tried?
   - If < 3: Return to Phase 1, re-analyze with new information
   - **If ≥ 3: stop and question the architecture (step 5 below)**
   - Don't attempt Fix #4 without architectural discussion

5. **If 3+ Fixes Failed: Question Architecture**

   **Pattern indicating architectural problem:**
   - Each fix reveals new shared state/coupling/problem in different place
   - Fixes require "massive refactoring" to implement
   - Each fix creates new symptoms elsewhere

   **Stop and question fundamentals:**
   - Is this pattern fundamentally sound?
   - Are we "sticking with it through sheer inertia"?
   - Should we refactor architecture vs. continue fixing symptoms?

   **Discuss with the user before attempting more fixes**

   This is not a failed hypothesis - this is a wrong architecture.

## Rationalizations — All Mean "Return to Phase 1"

| Excuse | Reality |
|--------|---------|
| "Quick fix, investigate later" | First fix sets the pattern. Do it right from the start. |
| "Issue is simple, skip the process" | Simple issues have root causes too. Process is fast for simple bugs. |
| "Emergency, no time" | Systematic is FASTER than guess-and-check thrashing. |
| "I see the problem, let me fix it" | Seeing symptoms ≠ understanding root cause. |
| "Multiple fixes at once saves time" | Can't isolate what worked. Creates new bugs. |
| "I'll write the test after" | Untested fixes don't stick. Test first proves it. |
| "One more fix attempt" (after 2+) | 3+ failures = architectural problem. Question the pattern, not another fix. |

## Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, gather evidence | Understand what and why |
| **2. Pattern** | Find working examples, compare | Identify differences |
| **3. Hypothesis** | Form theory, test minimally | Confirmed or new hypothesis |
| **4. Implementation** | Create test, fix, verify | Bug resolved, tests pass |

## When Process Reveals "No Root Cause"

If systematic investigation reveals issue is truly environmental, timing-dependent, or external:

1. You've completed the process
2. Document what you investigated
3. Implement appropriate handling (retry, timeout, error message)
4. Add monitoring/logging for future investigation

**But:** most "no root cause" conclusions are an unfinished investigation.

## Supporting Techniques

These techniques are part of systematic debugging and available in this directory:

- **`root-cause-tracing.md`** - Trace bugs backward through call stack to find original trigger
- **`defense-in-depth.md`** - Add validation at multiple layers after finding root cause
- **`condition-based-waiting.md`** - Replace arbitrary timeouts with condition polling

**Related skills:**
- **chris-code:test-driven-development** - For creating failing test case (Phase 4, Step 1)
- **chris-code:regression-test** - For full regression coverage after the fix (Phase 4, Step 1)
- **chris-code:coherent-change** - For implementing the determined fix coherently once the root cause is known (Phase 4, Step 2)
- **chris-code:verification-before-completion** - Verify fix worked before claiming success
