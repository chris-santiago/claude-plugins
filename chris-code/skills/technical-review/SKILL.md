---
name: technical-review
description: Use when reviewing mathematical correctness, algorithmic logic, research alignment, or numerical stability in a codebase. Triggers include loss functions, estimators, optimization steps, statistical methods, probabilistic models, numerical methods, or any code that implements a published algorithm. Also use when the user says "technical review", "math review", "verify the algorithm", "check the formulas", or "does this match the paper".
---

# Technical Review

Review mathematical correctness, algorithmic logic, research alignment, and numerical stability. This skill does NOT cover code quality, API design, or idiom compliance — those are handled by `*-review` skills and `*-quality-reviewer` agents.

**Announce at start:** "I'm using the technical-review skill to review mathematical and algorithmic correctness."

## Before Starting

Auto-discover project context by reading:
1. `pyproject.toml` / `setup.cfg` / `package.json` — package name, description, dependencies
2. `README.md` — stated purpose, claimed methods, referenced papers
3. Source directory structure — identify modules with mathematical content

Report what you found and ask the user to confirm scope and priority before proceeding.

## Review Sections

### 1. Claim Audit

Identify what the package claims to implement:
- Algorithms, estimators, loss functions, optimizers, filters, samplers, numerical methods
- Referenced papers, textbooks, or standards
- Stated assumptions, limitations, and domains of validity

Flag: undocumented behavior, unsupported claims, hidden assumptions, scope gaps between docs and implementation.

### 2. Mathematical Correctness

For every mathematically meaningful component:
- Extract the implemented formula in plain math notation
- Identify the intended mathematical object being computed
- Compare the implementation to the documented formula or cited paper
- State whether the implementation is exact, approximate, heuristic, or inconsistent
- Examine assumptions, domains, constraints, and invariants
- Check dimensional consistency and parameterization
- Verify gradients/derivatives if relevant
- Check convergence assumptions or optimization behavior if relevant

Review explicitly if present:
- Loss functions, estimators, probabilistic models
- Normalization/scaling, regularization
- Matrix operations / decompositions
- Filtering / smoothing, optimization steps
- Monte Carlo methods, sequence models
- Metrics and calibration methods

When useful, provide: corrected formula, pseudocode, a minimal counterexample, or a test that would catch the issue.

### 3. Algorithmic Logic

Check whether the implementation matches the intended algorithm:
- Control flow vs. algorithm specification
- Edge cases, branch conditions, defaults, fallback behavior
- Correctness of batching, indexing, masking, broadcasting, iteration, aggregation
- State handling, mutability, caching, hidden side effects
- Data validation and shape/type assumptions

Look especially for:
- Off-by-one errors in algorithm-critical loops
- Silent shape mismatches in tensor/matrix operations
- Train/eval leakage (normalization stats, dropout, augmentation)
- Misuse of randomness or seeds affecting statistical properties
- Incorrect handling of NaN/inf/zero divisions
- Numerically unstable expressions (log of near-zero, catastrophic cancellation, overflow in exp)
- Inconsistent units or coordinate systems

### 4. Research Alignment

For each algorithmic or mathematical claim:
- Identify the likely source (paper, textbook, standard, canonical implementation)
- Summarize the claimed method in 1-3 sentences
- Compare the implementation to that reference
- Note deviations and whether they appear intentional
- Classify: harmless, beneficial, risky, or unjustified

Evidence scale:
- **Verified**: matches reference in source
- **Partial**: partially matches reference
- **Weak**: claim present but implementation evidence is weak
- **Unverifiable**: could not verify from provided materials

Rules:
- Prefer peer-reviewed papers, official specifications, textbooks, or original method papers
- If no published research exists, use authoritative documentation or de facto standard implementations, and say so
- Never claim a method is research-backed if it is only a project convention
- Do not invent citations, benchmarks, or paper results

### 5. Numerical Stability

Identify expressions at risk of:
- Catastrophic cancellation (subtracting nearly equal numbers)
- Overflow/underflow in exp, log, softmax, sigmoid
- Loss of precision in accumulation (float32 summation of many terms)
- Division by zero or near-zero denominators
- Ill-conditioned matrix operations
- Non-deterministic floating-point reduction order

For each risk, state whether it's a confirmed bug or a latent risk, and suggest a numerically stable alternative.

## Findings Format

For each finding, include:
- **Tag**: `[math-bug]`, `[math-risk]`, `[research-mismatch]`, `[logic-bug]`, `[logic-risk]`, `[stability-risk]`, `[unverifiable-claim]`
- **Severity**: critical / high / medium / low
- **Location**: file:line or file:function
- **Finding**: concrete description
- **Evidence**: what you checked and what you found
- **Fix**: specific recommendation

## Output

### Findings Table

| Severity | Tag | Location | Finding | Fix |
|----------|-----|----------|---------|-----|

### Verdict

- Top issues requiring attention (ordered by severity)
- Confidence level: high / medium / low
- Unresolved questions requiring domain expertise
- Whether external domain expert review is needed

Save the review to `docs/reviews/YYYY-MM-DD-technical-review.md` and commit.
