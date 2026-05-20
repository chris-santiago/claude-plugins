---
name: code-archaeology
description: Use when surfacing unimplemented features, silently dropped parameters, dead code paths, skipped tests, or spec-vs-impl gaps in any codebase — especially before marking a milestone done, before a major refactor, or when behavior a user expects is mysteriously absent. Trigger phrases: "what's not implemented", "find unfinished work", "what's silently dropped", "audit for stubs", "find deferred features", /code-archaeology.
---

# Code Archaeology

Systematically sweep the codebase for comments, stubs, and structural patterns that reveal planned-but-unbuilt behavior. The most dangerous gaps are not `TODO` comments — they are **silent drops**: parameters accepted, warnings suppressed, match arms that fall through to default no-ops.

## Dispatch Strategy

Split by domain and run agents in parallel. Each reads every file in scope — grep first to find candidates, then read surrounding context.

**Discover scope by exploring the project first.** Identify:
- Primary language(s) and their source directories
- Test directories and documentation directories
- Any spec/design documents

Then dispatch one agent per domain area:

| Agent | Scope |
|---|---|
| Per-language agent (Python, Rust, TS, etc.) | Each language's source directories |
| Tests + Docs | Test directories, spec files, design docs, README |

## Language-Specific Patterns

### Python

**Obvious:** `# TODO`, `# FIXME`, `raise NotImplementedError`, `raise ValueError("not yet...")`, `pass` in non-abstract methods.

**Non-obvious — these matter more:**

- Frozensets/sets with inline comments listing "accepted but not rendered" items
- `warn_once(...)` or `warnings.warn(...)` calls — anything behind a warning is silently degraded
- `_ = param` — explicit discard of an accepted parameter
- Parameters in the docstring that don't appear in the function body
- Parameters that immediately `raise ValueError` for any non-default value (signature promises, implementation refuses)
- `if False:` or hardcoded-`False` branch guards on feature paths

### Rust

**Obvious:** `todo!()`, `unimplemented!()`, `// TODO`, `// FIXME`.

**Non-obvious — these matter more:**

- `_ => {}` / `_ => None` / `_ => Ok(Vec::new())` in match arms on dispatch tables — the canonical silent drop
- `#[allow(dead_code)]` on an entire module or struct (not a single field) — blanket suppression hides unused helpers
- `let _ = value` — explicit discard in a function body
- `eprintln!` / `println!` in non-test code — debug output left in production
- Struct fields declared but never read anywhere in the crate
- Doc comments saying "no-op", "reserved", or "not yet wired" — verify the code actually matches

### TypeScript / JavaScript

**Obvious:** `// TODO`, `// FIXME`, `throw new Error("not implemented")`.

**Non-obvious:**

- `console.log` / `console.warn` in production code
- Parameters destructured but unused
- `as any` type casts hiding incomplete implementations
- Empty catch blocks or `catch (e) { /* ignore */ }`
- Interface members declared optional that the implementation never sets

### Tests + Docs

- `@pytest.mark.skip`, `@pytest.mark.xfail`, `#[ignore]`, `.skip()` — read the reason
- `pass` or `assert True` / `expect(true)` inside a test body — stubs never filled in
- Commented-out assertions
- Spec sections with "not yet", "deferred", "TBD", "pending"
- Documented public API parameters — cross-check against implementation for silent gaps

### Verification required before reporting

Comments saying "Reserved for future use", "no-op today", "deferred", or "accepted but not yet wired" are **candidates**, not confirmed gaps. Before reporting any such comment as a finding, verify the actual code path:

1. Does the parameter/feature actually have a code path that does something?
2. Is the comment stale (implementation was added after the comment was written)?

If the implementation exists and is wired end-to-end, classify the finding as `STALE_COMMENT` (comment no longer matches code), not `SILENT_DROP`. Stale comments are low-severity cleanup, not bugs.

## Output Format

Each agent returns structured findings:

```
FILE: <path>
LINE: <number>
TYPE: [TODO | FIXME | STUB | todo!() | SILENT_DROP | DEAD_PARAM | SKIP | SPEC_GAP | STALE_COMMENT | other]
COMMENT/CODE: <exact text>
WHAT'S MISSING: <one sentence — or for STALE_COMMENT: "Comment says X but code already does Y">
VERIFIED: <yes — traced code path | no — comment only>
```

## Synthesis

After all agents return, group findings into a prioritized report:

1. **Active bugs** — code wired incorrectly (wrong key, missing branch in dispatch)
2. **Skipped tests** — known bugs never fixed
3. **Silent drops** — accepted by API, never forwarded or used
4. **Features raise at runtime** — documented, raise on use
5. **Missing spec implementations** — not present in source at all
6. **Stale docs** — comments/docstrings that no longer match the implementation

Save the report to `.claude/output/code-archaeology/YYYY-MM-DD-code-archaeology.md`.
