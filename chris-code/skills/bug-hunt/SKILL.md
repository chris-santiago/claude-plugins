---
name: bug-hunt
description: Repeatable parallel test-writing campaign for Python and Rust code. Dispatches one bug-hunter agent per subsystem to find edge-case bugs across the codebase. Use when the user says /bug-hunt, "write edge case tests", "find bugs", "test coverage sweep", or wants a systematic bug-finding pass. Accepts an optional subsystem name to scope a single subsystem.
---

# Bug Hunt

Parallel edge-case test campaign. One `bug-hunter` agent per subsystem writes tests, runs them, and reports failures as bugs.

## Procedure

### Step 1 — Discover subsystems

If the user provided a subsystem name (e.g. `/bug-hunt auth`), hunt only that subsystem: go straight to item 3 for it.

Otherwise, discover subsystems by exploring the project:

1. Read the project's CLAUDE.md, README, and directory structure.
2. Identify logical subsystems — modules, packages, crates, or functional areas with distinct responsibilities.
3. For each subsystem, determine the six inputs its agent needs:
   - **Key**: short kebab-case name (e.g. `auth`, `data-pipeline`, `rendering`)
   - **Mode**: `Py`, `Rs` or `Py+Rs`, the languages the `bug-hunter` agent writes tests in
   - **Source scope**: paths containing the subsystem's implementation
   - **Existing tests**: paths containing existing tests for the subsystem
   - **Test output paths**: where the new test file for each language goes, named `test_bug_hunt_<key>` in the project's test directory and following its conventions
   - **Build/run commands**: how to build the project and run that test file, for each language in the mode
4. A subsystem in any other language has no agent mode. Leave it out and tell the user it isn't covered.
5. Present the discovered subsystem table to the user for confirmation before dispatching agents.

### Step 2 — Dispatch agents in parallel

Dispatch one `chris-code:bug-hunter` agent per subsystem, all in a **single message** so they run in parallel. Each dispatch carries that subsystem's six inputs and nothing else:

```
Subsystem: <key>
Mode: <Py | Rs | Py+Rs>
Source paths: <source scope>
Existing test paths: <existing tests>
Test output paths: <one path per language in the mode>
Build/run commands: <how to build, and how to run each new test file>
```

The agent's own contract says how to hunt and what to return, so don't restate its job, and don't narrow it: the agent disregards a dispatch that tells it to skip a category or downplay a failure.

### Step 3 — Run the new tests

Run the new test files yourself with the same commands you gave the agents, to confirm the failures they reported. Examples:

- Python: `pytest tests/test_bug_hunt_*.py --tb=short -q`
- Rust: `cargo test -- bug_hunt --nocapture`
- Mixed: run each language's test runner separately

### Step 4 — Write the report

Append a timestamped run section to `.claude/output/bug-hunt/BUG_REPORT.md`. Format:

```markdown
## Run — <ISO timestamp>

### <subsystem-key>
- Tests added: N  |  Failures: N
- Status: clean | BUGS FOUND

<failure details if any — test name, error message>
```

Create the file if it does not exist. Never overwrite — always append.

### Step 5 — Print summary table

Example:

```
| Subsystem        | Mode | Tests | Fails | Status     |
|------------------|------|-------|-------|------------|
| auth             | Py   | 12    | 2     | BUGS FOUND |
| data-pipeline    | Py   | 8     | 0     | clean      |
| rendering        | Rs   | 15    | 1     | BUGS FOUND |
```

Then list every failing test with its error, grouped by subsystem. These are the bugs.

## Output artifacts

| Artifact | Path | Committed? |
|---|---|---|
| Bug report | `.claude/output/bug-hunt/BUG_REPORT.md` | No (gitignored) |
| Test files | Named `test_bug_hunt_<subsystem>` in the project's test directory, following project conventions | Yes |

All test files are real and should be committed after review. Failing tests are kept with a `# BUG:` / `// BUG:` comment — they are the bug evidence.

## Remediate, or defer

bug-hunt finds, it never fixes. Before stopping, **offer the handoff**: *"Bugs captured in `BUG_REPORT.md` and as failing tests. Remediate now in batch, or keep for later?"*

On accept, hand the bug-set to `chris-code:remediating-issues` (batch) — it frames each as an end-state and fixes them through `chris-code:coherent-change` batch mode (one `chris-code:lean-spec` → `chris-code:lean-plan` → execution), with the failing tests becoming the regression coverage. On defer, the report and tests wait for that same route.

## Repeatability

Running `/bug-hunt` again reruns all agents. Each agent overwrites its test file (fresh read of current source). Previously-fixed bugs will now pass. `BUG_REPORT.md` accumulates all runs with timestamps.
