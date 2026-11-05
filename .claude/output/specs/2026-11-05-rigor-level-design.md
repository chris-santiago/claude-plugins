# Rigor Level Design Spec

## 1. Scope

A project-scaled **rigor level** (`light`, `standard`, `heavy`) that sets how deep testing goes at every step that decides depth: the plan's `Cases:` rows, the coder's tests, the reviewers' severity for a missing case, and the mutation tester's breaks, gating, and model. A resolver derives the level from the repo (size, a language binding, numeric or ML dependencies), a project's `CLAUDE.md` overrides it, and a plan task may raise it for that task. One reference table defines what each level means per role. Two rules hold at every level: realistic cases come first, and a test that can't fail is a serious finding. Intent: `.claude/output/intent/2026-11-05-rigor-level-intent.md`.

## 2. Goals

- A small project gets `light` depth with no setup, and a large multi-language numeric project gets `heavy`.
- Mutation effort and gating scale with the level, so a small codebase gets few breaks and a survivor outside the plan's rows doesn't force a fix.
- Below `heavy`, a missing esoteric case is a note, not a fix round.
- A test that can't fail is S3 at every level.
- Every brief and every mutation dispatch states the level and the reasons for it.
- A plan task can raise its own level, never lower it.

## 3. Non-goals

- `bug-hunt` and `test-sweep`: the user invokes them to hunt edge cases on purpose, so the level never throttles them.
- `*-review-lite`, the design reviewers, and the intent reviewer: unchanged.
- Mechanical enforcement in triage (an `edge` tag, a tier cap by level). Reviewers apply the level when they assign severity; a cap is a later add-on only if real runs show reviewers ignoring it.
- Lowering a task below the project level, and per-run levels that ignore the project.
- Migrating existing stores or plans: a plan with no `Rigor:` lines resolves every task to the project level.

## 4. System behavior

### 4.1 The project level

Resolution, highest priority first:

1. **`CLAUDE.md` line.** The repo-root `CLAUDE.md` holds `Test rigor: <level>` (case-insensitive, optionally a list item or bold label). That level wins, with the reason `set in CLAUDE.md`. Any other value is an error naming the allowed values; it never falls back.
2. **Heuristic**, applied in this order: base, then floor, then raise.
   - **Size sets the base.** Count non-blank lines in tracked source files. Under 5,000 lines is `light`, 5,000 to 30,000 is `standard`, over 30,000 is `heavy`. Tests, vendored and generated code, and non-source files don't count (Section 6.3).
   - **A language binding floors the level at `standard`.** A binding is a declared bridge between languages in a tracked `Cargo.toml` or `pyproject.toml` (Section 6.3). Two unrelated languages in one repo are not a binding.
   - **Numeric or ML dependencies raise the level one step**, capped at `heavy` (Section 6.3).
3. **Default.** Outside a git work tree, or with no tracked source, the level is `standard`, with the reason saying why.

The result is a level plus its reasons, e.g. `standard: 4.2k source lines (python); numpy +1` or `heavy: set in CLAUDE.md`. It depends only on the repo's tracked files and `CLAUDE.md`, so the same inputs give the same level and nothing is stored.

### 4.2 Task levels

A plan task may carry `Rigor: standard` or `Rigor: heavy`. The task's level is the higher of that line and the project level. A line equal to the project level is accepted. A line below it, or an unknown value, is refused when the task's brief is built, naming the task, its line, and the project level and its reasons. A task without the line takes the project level.

### 4.3 The rigor table

One reference document defines each role's behavior per level. Contracts point to their row instead of restating it.

| Role | light | standard | heavy |
|---|---|---|---|
| **Plan `Cases:` rows** | Main paths, and the errors a realistic caller can trigger | light, plus the boundaries the code explicitly handles (a guard, a parser's error branch, an empty collection the code special-cases) | standard, plus esoteric boundaries: `None` where not expected, NaN and inf, extreme sizes, type confusion |
| **Coder tests** | One test per row | One test per row | One test per row, plus the TDD edge-case list where it applies |
| **Reviewer: a missing case** | S3 when a `Cases:` row names it; otherwise S1-S2, unless a realistic caller hits it | S3 when a row names it or the code explicitly handles it; an exotic case is S1-S2 | S3 for any missing boundary case (the existing rule) |
| **Mutation breaks** | At most 2 per changed function, only functions a row names or the change's tests call directly; the targeted test subset | Up to 3 per changed region; the targeted subset | A few per region, every region; the full suite where the covering subset is unclear (the existing rule) |
| **Mutation gating** (covered survivors) | Gates when it changes behavior a `Cases:` row names; without a plan, when it sits in a function the change's own tests call directly. Others are advisory | Gates when it changes behavior a row names or sits in a function the change's tests call directly. Others are advisory | Every covered survivor gates (the existing rule) |
| **Mutation model** | sonnet | opus | opus |

A *realistic caller* is one that exists or plausibly will: a caller in the repo, user input, or a file, network, or upstream-system input the code reads. An input only a hostile or type-violating caller produces is esoteric.

### 4.4 Rules at every level

- **Realistic first.** Plans, coders, and reviewers cover the cases a realistic caller hits before anything esoteric.
- **A test that can't fail is S3.** That covers an assertion satisfied by the broken state ("not None", "no exception"), an assertion on a mock's own return value, and a fixture shaped so the path under test can't break.
- **A `Cases:` row is never optional.** A row the plan states is decided behavior; no level excuses skipping or weakening it.
- Uncovered survivors and equivalent mutants stay advisory, and on-demand mutation never gates, as today.

### 4.5 Where the level appears

- **Briefs.** Every task brief states `Rigor: <level> (<reasons>)` for its task. Coders and every reviewer of the task read the level there.
- **Plans.** The planner resolves the project level before writing rows and writes them to it. Self-review checks the rows against the level: no esoteric rows below `heavy` unless the task is raised, and no missing boundaries at `heavy`.
- **Mutation.** The closing-review dispatch carries the project level with its reasons, the plan path when one exists, and the per-file levels (Section 6.2). The tester applies each changed file's level to that file's regions. A `light` dispatch runs the tester on sonnet, the one documented exception to the rule that each role runs on its frontmatter model.
- **TDD.** Its edge-case list is the `heavy` list, preceded by "realistic first". Run without a brief, it uses the project level.

## 5. Architecture

- **Resolver.** A stateless script beside the other SDD scripts. It computes the project level, a task's level from a plan, and the per-file levels from a plan plus a store's stage map. It is importable as a module and runnable as a CLI.
- **Brief builder.** Imports the resolver, resolves the task's level, refuses a lowering or unknown `Rigor:` line, and stamps the level into the brief.
- **Rigor table.** One reference document in SDD's skill directory. Agents locate it from the scripts path their dispatch already carries.
- **Consumers.** lean-plan, the coders and the fallback implementer prompt, the spec and quality reviewers, the mutation tester, verification's mutation step, and the TDD skill each read the level from their input (a brief, a dispatch line, or the resolver) and apply their row of the table.

Data flow: repo and `CLAUDE.md` → resolver → project level → plan rows and `Rigor:` lines → brief stamp → coder and reviewers. At the close: resolver plus plan plus stage map → per-file levels → mutation dispatch.

## 6. Canonical interfaces / data contracts

### 6.1 Levels

Ordered `light < standard < heavy`. "Raise one step" moves up this order, capped at `heavy`.

### 6.2 Resolver CLI

```
rigor.py [--repo DIR]                          # project level
rigor.py [--repo DIR] --plan PLAN --task N     # task N's level
rigor.py [--repo DIR] --plan PLAN --store STORE --files
```

- The first two print one line, `<level>: <reasons>`, and exit 0.
- `--files` prints the project line, then one line per file whose level is above the project's: `<level> <repo-relative path>`. A file's level is the highest of the raised tasks whose latest stage footprint lists it. Files not listed take the project level.
- A bad `CLAUDE.md` value, or a task `Rigor:` line below the project level or unknown, exits 2 with the reason on stderr.
- `--repo` defaults to the current directory's work tree.

Module API: `project_level(repo) -> Resolution` and `task_level(project, declared, task) -> Resolution`, where `declared` is the task's `Rigor:` value (or none), where `Resolution` carries `level` and `reasons`. The brief builder uses the module API.

### 6.3 Heuristic inputs

- **Source files**: tracked files with a source extension: `.py .rs .js .jsx .ts .tsx .go .java .kt .c .cc .cpp .h .hpp .cs .rb .swift .scala`.
- **Excluded from the count**:
  - test files: a `test/` or `tests/` path segment, `test_*.py`, `*_test.py`, `*_test.rs`, `tests.rs`, `*_test.go`, `*.test.*`, `*.spec.*`;
  - vendored or generated paths: a `vendor/`, `third_party/`, `node_modules/`, `build/`, `dist/`, `target/`, or `generated/` segment, and `*_pb2.py`.
- **Binding markers**: a `pyo3`, `napi`, `wasm-bindgen`, or `cxx` dependency in a tracked `Cargo.toml`; a `maturin` build backend, or a `cffi` dependency, in a tracked `pyproject.toml`.
- **Numeric markers**: a dependency named `numpy`, `scipy`, `pandas`, `polars`, `torch`, `jax`, `tensorflow`, or `scikit-learn` in a tracked `pyproject.toml`, `requirements*.txt`, `setup.cfg`, or `environment.yml`; or `ndarray`, `nalgebra`, `polars`, or `arrow` in a tracked `Cargo.toml`. Matching is on dependency names, not substrings of other names.

### 6.4 Plan and brief lines

- Plan task line: `- Rigor: standard|heavy` within the task entry, outside code fences, in the same list-item forms `Cases:` accepts.
- Brief line: `Rigor: <level> (<reasons>)`, near the top of the brief, before the task entry.
- Project line: `Test rigor: light|standard|heavy` in the repo-root `CLAUDE.md`.

### 6.5 Mutation dispatch inputs (added)

`Rigor: <project level> (<reasons>)`, `Plan: <path>` (or `none`), and `File levels:` with the `--files` lines above the project level. The tester's report states the level it applied to each file.

## 7. Invariants and constraints

- The level never lowers below the project level for any task or file.
- A `Cases:` row is required at every level, and a test that can't fail is S3 at every level.
- The resolver is deterministic and stateless: no store writes, no network, no test runs.
- Existing behavior is the `heavy` column. A project resolved or declared `heavy` sees no change from today except the explicit can't-fail S3 rule, and coders naming the TDD edge-case list they already followed.
- A plan or brief without `Rigor:` lines keeps working: every task takes the project level.

## 8. Key decisions and tradeoffs

| Decision | Why | Rejected |
|---|---|---|
| Level reaches plans, coders, reviewers, and mutation (not mutation alone) | Trimming only the last step keeps the upfront cost, and an exhaustive suite makes every mutation run slower | Mutation-only scaling |
| Three levels | A mid-size service fits neither extreme | Two levels |
| Heuristic plus a `CLAUDE.md` override | Small apps get `light` with no setup; a misjudged project is fixed with one line | Declared-only; derived-only; per-run choice |
| Size, binding floor, numeric raise | Size alone rates a small numeric library `light`, where NaN is a realistic case; bindings are where cross-language bugs sit | Size only; size plus any second language |
| Thresholds 5k and 30k lines | The user's sense of a small app is under 5k | 3k |
| Task `Rigor:` raises only | Covers one dangerous function in a small app without letting a plan weaken a large project's gates | Both directions; one level per run |
| One reference table that contracts point to | One place to change; avoids the same rules drifting across about ten contracts | Rules inline in each contract |
| Judgment enforcement, no triage cap | Reviewers already assign severity; the level only has to be agreed, which the brief stamp guarantees | An `edge` tag with a triage tier cap |
| sonnet for `light` mutation | Light breaks are simple and the run should be cheap | opus at every level |
| `light` gating defined by the plan's rows | The plan already decided the core behavior, so the tester doesn't guess | A tester-judged "core path" |
| `bug-hunt` and `test-sweep` unthrottled | They are invoked to hunt edge cases | Applying the level there |

## 9. Acceptance criteria

- A repo with 4,999 counted source lines and no markers resolves `light`; 5,000 resolves `standard`; 30,001 resolves `heavy`.
- Test files, vendored and generated paths, and non-source files don't change the count.
- A 1k-line repo with a `pyo3` dependency resolves `standard`; with `numpy` instead, `standard`; with both, `heavy`. A 40k-line repo with `numpy` stays `heavy`.
- A Python backend plus a JS frontend with no binding marker is not floored.
- `Test rigor: light` in `CLAUDE.md` on a 40k-line repo resolves `light` with `set in CLAUDE.md`; `Test rigor: medium` exits 2 naming the allowed values.
- Outside a git work tree, the level is `standard` with a reason.
- A task with `Rigor: heavy` in a `light` project resolves `heavy`; `Rigor: light` in a `standard` project is refused at brief time, naming both levels; a task with no line takes the project level.
- Every brief carries the `Rigor:` line with reasons.
- `--files` lists exactly the files in raised tasks' footprints, at the highest raising task's level.
- Every coder, the fallback implementer prompt, the spec and quality reviewers, the mutation tester, and TDD reference the rigor table, and the quality reviewers state the can't-fail S3 rule.
- Verification's mutation dispatch carries the level, the plan path, and the file levels, and runs on sonnet at `light`.
- A large Python+Rust project with torch resolves `heavy`.

## 10. Validation strategy

- Unit tests over small throwaway git repos for every resolver rule, boundary, override, refusal, and the per-file map; brief tests for the stamp and the lowering refusal.
- A contract-drift test that each consuming contract names the rigor table, so a contract can't silently drop the level.
- Sanity runs of the resolver on a large Python+Rust project (expect `heavy`, reasons shown) and on this plugin repo, before calling it done.
- The prose table is checked against the intent ledger by reading: statements 3 and 4 map to the light and standard columns, statement 5 to Section 4.4.
