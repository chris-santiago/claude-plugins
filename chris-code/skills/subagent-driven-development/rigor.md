# Test rigor levels

How deep a change is tested, reviewed for missing cases, and mutated. There are three levels, ordered `light < standard < heavy`. Each role applies its row of the table below to the level it's given. A contract points here instead of restating its row. When a dispatch supplies the scripts path, this file is `<scripts-path>/../rigor.md`.

## Where the level comes from

`scripts/rigor.py` resolves it. Nothing is stored, so the same repo and plan always give the same level.

1. **`CLAUDE.md`.** A line `Test rigor: light|standard|heavy` in the repo-root `CLAUDE.md` sets the project level. Any other value is an error, never a fallback.
2. **Otherwise, the repo itself.**
   - Counted source lines set the base: under 5,000 is `light`, 5,000 to 30,000 is `standard`, and over 30,000 is `heavy`. Tests, vendored code, generated code and non-source files aren't counted.
   - A language binding (pyo3, napi, wasm-bindgen, cxx, maturin or cffi) raises the level to at least `standard`.
   - Numeric or ML dependencies (numpy, scipy, pandas, polars, torch, jax, tensorflow, scikit-learn, ndarray, nalgebra or arrow) raise it one step, capped at `heavy`.
3. **No git work tree, or no tracked source:** `standard`.

A plan task can carry `- Rigor: standard|heavy` to raise that task above the project level. It can never lower it: `task_brief.py` refuses a lower or unknown value. Every brief opens with `Rigor: <level> (<reasons>)`. That line is the level for the task's coder and every reviewer of the task. A dispatch never restates or lowers it.

## The table

| Role | light | standard | heavy |
|---|---|---|---|
| **Plan `Cases:` rows** | Main paths, and the errors a realistic caller can trigger | light, plus the boundaries the code explicitly handles (a guard, a parser's error branch, an empty collection the code special-cases) | standard, plus esoteric boundaries: `None` where not expected, NaN and inf, extreme sizes, type confusion |
| **Coder tests** | One test per row | One test per row | One test per row, plus the TDD edge-case list where it applies |
| **Reviewer: a missing case** | S3 when a `Cases:` row names it; otherwise S1-S2, unless a realistic caller hits it | S3 when a row names it or the code explicitly handles it; an exotic case is S1-S2 | S3 for any missing boundary case |
| **Mutation breaks** | At most 2 per changed function, only in functions a row names or the change's tests call directly; the targeted test subset | Up to 3 per changed region; the targeted subset | A few per region, every region; the full suite where the covering subset is unclear |
| **Mutation gating** (covered survivors) | Gates when it changes behavior a `Cases:` row names; without a plan, when it sits in a function the change's own tests call directly. Others are advisory | Gates when it changes behavior a row names, or sits in a function the change's tests call directly. Others are advisory | Every covered survivor gates |
| **Mutation model** | sonnet | opus | opus |

A **realistic caller** is one that exists or plausibly will: a caller in the repo, user input, or a file, network or upstream-system input the code reads. An input that only a hostile or type-violating caller would produce is esoteric.

## At every level

- **Realistic first.** Plans, coders and reviewers cover the cases a realistic caller hits before anything esoteric.
- **A test that can't fail is S3.** This includes an assertion the broken state also satisfies ("not None", "no exception"), an assertion on a mock's own return value, and a fixture shaped so the path under test can't break.
- **A `Cases:` row is never optional.** A row in the plan is decided behavior, and no level excuses skipping or weakening it.
- Uncovered survivors and equivalent mutants stay advisory, and on-demand mutation never gates.
