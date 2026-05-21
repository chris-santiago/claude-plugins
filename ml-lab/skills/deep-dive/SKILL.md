---
name: deep-dive
description: Generate a comprehensive technical deep-dive document for an ML experiment or research project. Reads experiment scripts, results schemas, journal decisions, and existing docs to produce DEEP_DIVE.md — a reference document covering data construction, model architecture, scoring mechanics, statistical methods, per-test detail, quality gates, aggregation, and key design decisions with sources cited. Use when the user says /deep-dive, "write a deep dive", "document this experiment", "create a technical reference for this project", "write up the implementation details", or "document how this works end-to-end".
---

## Step 1: Orient

Find the repo root and the experiment directory to document.

```bash
git rev-parse --show-toplevel
```

If the user specified an experiment path (e.g., `experiments/rerun` or `src/pipeline`), use that as `<experiment-root>`. Otherwise use the repo root.

Check whether a journal exists:

```bash
ls <repo-root>/.project-log/journal.jsonl 2>/dev/null && echo "journal: present" || echo "journal: absent"
```

Record **journal_present = true/false**. Do not stop if absent — proceed with graceful degradation (see Step 3).

## Step 2: Survey project structure

Find all relevant artifacts under `<experiment-root>`. Run these in parallel:

```bash
# Entry-point scripts
find <experiment-root> -name "*.py" | sort

# Existing documentation
find <experiment-root> \( -name "*.md" -o -name "*.txt" \) | sort
ls <repo-root>/HYPOTHESIS.md <repo-root>/CONCLUSIONS.md <repo-root>/REPORT.md 2>/dev/null

# Sample results schemas
find <experiment-root> -name "results.json" | head -5

# Output artifacts
find <experiment-root> \( -name "*.png" -o -name "*.pdf" -o -name "*.csv" \) | head -20

# Check for existing deep dive
ls <experiment-root>/DEEP_DIVE.md 2>/dev/null
```

Then read (do not skip):
- All found `*.md` plan docs, HYPOTHESIS.md, CONCLUSIONS.md, REPORT.md
- Every entry-point Python script. If there are more than 6 scripts, read them all — prioritize those with `main()` or `if __name__ == "__main__"` blocks
- One sample `results.json` per distinct script (to extract the actual results schema — do not infer)

**If you cannot read a file, record it as unreadable. Do not guess its contents.**

## Step 3: Query journal (if present)

If `journal_present = true`, run all of these:

```bash
python3 <repo-root>/.project-log/journal_query.py --list decision
python3 <repo-root>/.project-log/journal_query.py --list discovery
python3 <repo-root>/.project-log/journal_query.py --list hypothesis
python3 <repo-root>/.project-log/journal_query.py --list experiment
python3 <repo-root>/.project-log/journal_query.py --list issue
python3 <repo-root>/.project-log/journal_query.py --unresolved-issues
```

Collect every decision entry: its ID (short hash), message, and rationale body. These become the authoritative citations in Section 9 (Design Decisions).

If `journal_present = false`, skip this step entirely. Design decisions will cite code comments, git log lines, or plan doc sections instead of journal IDs.

## Step 4: Report inventory and confirm

Before writing anything, show this inventory:

```
Deep-dive inventory
──────────────────────────────────────────────────
Experiment root:   <path>
Scripts found:     <N> — <name1>, <name2>, ...
Results schemas:   <list of results.json files sampled>
Figures / outputs: <N> files found
Existing docs:     <list>
Journal:           present (<N> decisions) / absent

Sections planned:
  ✓ Overview & Motivation
  ✓ Contributions / Claims        [source: <HYPOTHESIS.md / plan doc / exploratory>]
  ✓ Infrastructure & Setup
  ✓ Reproducibility Design
  ✓ Per-experiment deep dives     [<N> scripts/phases]
  ✓ Quality Gates
  [✓/✗] Aggregation & Reporting  [multi-seed found / single-run only]
  ✓ Reading the Outputs
  ✓ Key Design Decisions          [<N> journal entries / code comments only]

Degraded sections (missing artifacts):
  <list what will be omitted or abbreviated, and why>
```

Ask: `► Proceed with deep dive? (y/n)`

Do not write until confirmed.

## Step 5: Synthesize DEEP_DIVE.md

Write the document using the required section structure below.

**Anti-hallucination rules — enforced throughout:**
- Every code snippet or mechanism description must cite its source: `file.py:line_start–line_end`
- Every design decision must cite one of: journal ID `xxxxxxxx`, `git log --oneline` hash, code comment at `file.py:NN`, or plan doc §N
- If no source exists for a decision, place it under an "Undocumented choices" subsection — do not fabricate rationale
- If you could not read a file, say so and leave the subsection blank rather than inventing content
- Smoke-test results are not production results; never present them as experiment findings

**Depth scales with scope:**
- Single script, single run → ~3–5k words
- 2–3 scripts / multi-seed → ~8–15k words
- Large multi-phase investigation (3+ scripts, consistency checkers, aggregation) → 15k+ words is appropriate; do not artificially compress

---

### Required sections

#### 1. Overview & Motivation

What research question does this investigation answer? Why does the problem matter operationally or scientifically? What is the scope (synthetic/real data, single/multi-phase, pre-registered/exploratory)?

#### 2. Contributions / Claims

**Pre-registered work:** List each claim with its pre-registered verdict criterion and the final verdict (Confirmed / Not confirmed / Inconclusive). Cite HYPOTHESIS.md or the plan doc section that defines each claim.

**Exploratory work:** List findings with supporting evidence. Label them as findings, not pre-registered claims.

#### 3. Infrastructure & Setup

- Directory layout (annotated tree showing what goes where)
- How to run: prerequisites, one-liner for a single run, one-liner for a full multi-seed run
- Dependency management (inline `# /// script` blocks, pyproject.toml, conda env, etc.)
- Any required external resources (data files, API keys, remote services) and how to obtain them

#### 4. Reproducibility Design

- How randomness is controlled: which seed parameters exist, what RNG library is used, what parallelism constraints (`workers=1`, `n_jobs=1`, or equivalent) ensure determinism
- Smoke-test protocol: what `--smoke` does, what it validates, what it explicitly does not validate
- What "reproducible" means for this project (exact bit-for-bit vs. statistically stable across seeds)

#### 5. Per-experiment deep dives

One numbered subsection per script or experimental phase (§5.1, §5.2, …). Each covers:

**§5.x.0 Theoretical motivation**
Why this experiment or phase was designed the way it was — the intellectual rationale, not just a description of what it does. What prior result or question motivated the specific design choices? What would a skeptical colleague ask first? This section must be written in prose, not bullet points. Omit only if the script is purely mechanical (data prep, aggregation) with no design choices to explain.

**§5.x.1 Data construction**
How input data is generated or loaded. Key parameters and their defaults. What changes across seeds. Format of the data passed to downstream steps. Cite the relevant function(s) with `file.py:line_range`.

**§5.x.2 Model / algorithm**
What is trained or applied. Key hyperparameters, their values, and **why those values** (cite source). What variants are compared and how they differ. **Include the actual instantiation code** (extracted from the script, not paraphrased). Cite with `file.py:line_range`.

**§5.x.3 Scoring mechanics**
How raw model output is converted to a scalar prediction, anomaly score, or evaluation metric. All scorer or metric variants defined — **include the formula** for each (mathematical or code form), not just the name. When each applies. Cite scorer implementations with `file.py:line_range`.

**§5.x.4 Statistical methods**
Inference method used (bootstrap CI, permutation test, t-test, none, etc.) and **why that method is appropriate** for this experimental structure. If bootstrap: paired vs. unpaired and why, number of resamples. Significance criterion (e.g., CI excludes zero, lower bound exceeds baseline, p < 0.05). What happens if the criterion is not met. **Include the resampling code** (extracted, not paraphrased). Cite with `file.py:line_range`.

**§5.x.5 Tests / ablations in detail**
For each named test or ablation: what it tests, how it is computed, what result is stored in the output schema, and how to interpret it. Note common misinterpretations. Cite implementation with `file.py:line_range`.

**§5.x.6 Execution flow**
Numbered step-by-step walkthrough of what the script does in order (e.g., `[1/7] Generate data → [2/7] Train model → …`). Note any abort conditions inline. Note which steps are skipped in smoke mode.

**§5.x.7 Results schema**
Annotated JSON (or CSV/NPZ) structure of the output file, extracted from an actual output file. Every field annotated with what it contains and its units. Private or intermediate fields noted as such.

#### 6. Quality Gates

- **Per-run abort conditions:** What causes a non-zero exit, at what step, and what it means for the investigation. Table format: `| Phase | Condition | Exit code | What to do |`
- **Consistency checkers:** If consistency-check scripts exist, document each check (label, what it verifies, pass/fail semantics). Include the invocation command.
- **Verdict stability rules:** How to interpret verdict agreement across seeds (e.g., 5/5 → report as stated; 4/5 → investigate; ≤3/5 → reframe).

#### 7. Aggregation & Reporting *(omit if single-run; label clearly if multi-seed)*

- How results combine across seeds: formula for mean, std, min, max
- CI aggregation: how per-seed CIs are combined for paper reporting
- Paper reporting format: what goes in the main results table, what goes in supplementary
- Seed sensitivity statement template (fill-in-the-blank version the paper author copies and completes)

#### 8. Reading the Outputs

**Figures:** For each figure file (or figure type): what it shows, which claim it supports, how to read it correctly, and one common misreading to avoid.

**Key metrics:** For each primary metric in results.json — what a healthy value looks like, what an anomalous value suggests, and what to do if the value is unexpected.

#### 9. Key Design Decisions

One subsection per non-obvious choice a colleague would question. Use this format:

> ### Why [choice]?
>
> **Source:** `journal ID xxxxxxxx` | `file.py:NN` (code comment) | plan doc §N
>
> [Rationale — what alternatives were considered and why this choice was made. Keep to ≤4 sentences.]

If `journal_present = false`, cite the nearest available source. If no source exists:

> ### [Choice] *(undocumented)*
>
> No decision record found. The choice appears at `file.py:NN`. Rationale not recorded.

---

*Document generated by /deep-dive on [date]. Script versions: [list script names and git HEAD]. If this document conflicts with a journal decision entry or the scripts, trust the journal/scripts over this document.*

---

## Step 6: Determine output path

Default output: `<experiment-root>/DEEP_DIVE.md`

If `<experiment-root>/DEEP_DIVE.md` already exists, ask:

`DEEP_DIVE.md already exists at <path>. Overwrite, or save as DEEP_DIVE_<YYYYMMDD>.md? (overwrite / new)`

## Step 7: Show draft and confirm

Show the section outline and the first 60 lines of the draft as a preview.

Ask: `► Save to <path>? (y/n)`

## Step 8: Write file

Write to the confirmed path.

Confirm: `<path> written — <N> lines, <N> sections. Cite this document in REPORT.md or the PR description for reproducibility.`
