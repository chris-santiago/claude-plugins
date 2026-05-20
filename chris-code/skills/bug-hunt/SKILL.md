---
name: bug-hunt
description: Repeatable parallel test-writing campaign for any project. Dispatches one bug-hunter agent per subsystem to find edge-case bugs across the codebase. Use when the user says /bug-hunt, "write edge case tests", "find bugs", "test coverage sweep", or wants a systematic bug-finding pass. Accepts an optional subsystem name to scope a single subsystem.
---

# Bug Hunt

Parallel edge-case test campaign. One `bug-hunter` agent per subsystem writes tests, runs them, and reports failures as bugs.

## Procedure

### Step 1 — Discover subsystems

If the user provided a subsystem name (e.g. `/bug-hunt auth`), run only that subsystem.

Otherwise, discover subsystems by exploring the project:

1. Read the project's CLAUDE.md, README, and directory structure.
2. Identify logical subsystems — modules, packages, crates, or functional areas with distinct responsibilities.
3. For each subsystem, determine:
   - **Key**: short kebab-case name (e.g. `auth`, `data-pipeline`, `rendering`)
   - **Mode**: what languages are involved — `Py`, `Rs`, `Py+Rs`, `TS`, or other
   - **Source scope**: paths containing the subsystem's implementation
   - **Existing tests**: paths containing existing tests for the subsystem
4. Present the discovered subsystem table to the user for confirmation before dispatching agents.

### Step 2 — Dispatch agents in parallel

Send ALL active subsystems in a **single message** as parallel Agent tool calls — one per subsystem.

Prompt template per agent (fill in the blanks):

```
Subsystem: <key>
Mode: <language mode>
Source paths: <source scope>
Existing test paths: <existing tests>

You are a bug-hunter agent. Your job is to:
1. Read all source files in scope
2. Identify edge cases, boundary conditions, error paths, and under-tested logic
3. Write a focused test file exercising those cases
4. Run the tests
5. Return your verdict: tests added count, list of failures (test name + error), status (clean / bugs-found)

Write tests that are minimal, targeted, and follow the project's existing test patterns.
```

### Step 3 — Run the new tests

Use the project's established test runner. Examples:

- Python: `pytest tests/test_bug_hunt_*.py --tb=short -q`
- Rust: `cargo test -- bug_hunt --nocapture`
- TypeScript/JS: `npm test -- --grep bug_hunt` or equivalent
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

## Repeatability

Running `/bug-hunt` again reruns all agents. Each agent overwrites its test file (fresh read of current source). Previously-fixed bugs will now pass. `BUG_REPORT.md` accumulates all runs with timestamps.
