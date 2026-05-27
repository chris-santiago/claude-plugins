---
name: technical-review
description: Use when reviewing mathematical correctness, algorithmic logic, research alignment, numerical stability, or ML performance/scaling in Python ML code. Triggers include loss functions, estimators, optimization steps, statistical methods, probabilistic models, numerical methods, or any code that implements a published algorithm. Covers PyTorch, Lightning, scikit-learn, scipy, numpy, lightgbm, and other ML/scientific Python libraries. Also use when the user says "technical review", "math review", "verify the algorithm", "check the formulas", or "does this match the paper".
scope:
  extensions: [".py"]
---

# Technical Review

Review mathematical correctness, algorithmic logic, research alignment, numerical stability, and ML performance/scaling in Python ML code. This skill does NOT cover general code quality, API design, or idiom compliance — those are handled by `*-review` skills and `*-quality-reviewer` agents.

**Announce at start:** "I'm using the technical-review skill to review mathematical and algorithmic correctness."

## Before Starting

Auto-discover project context by reading:
1. `pyproject.toml` / `setup.cfg` — package name, description, ML dependencies (torch, lightning, sklearn, scipy, numpy, lightgbm, xgboost, etc.)
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

### 6. Performance and Scaling

Review computational efficiency with attention to ML-specific patterns:

**Algorithmic complexity:**
- Asymptotic complexity of core operations — does it scale with dataset/feature/batch size as expected?
- Unnecessary recomputation inside training loops (recomputing constants, rebuilding indexes, redundant forward passes)
- Quadratic or worse operations hidden in data preprocessing or attention mechanisms

**Memory:**
- Tensors retained on GPU unnecessarily (missing `.detach()`, `.cpu()`, or `del`)
- Intermediate allocations that grow with batch/sequence length
- Gradient accumulation memory vs. large-batch alternatives
- DataLoader memory: full dataset loaded when streaming is feasible

**Vectorization and data movement:**
- Python loops over tensor elements where vectorized ops exist (numpy, torch, scipy)
- Unnecessary CPU-GPU transfers in hot paths (`.item()`, `.numpy()`, `.cpu()` inside loops)
- Missing `pin_memory`, inefficient `collate_fn`, untuned `num_workers`
- Operations that force synchronization (`.item()` in training loop)

**Framework-specific:**
- PyTorch: `torch.compile` applicability, inefficient custom autograd, missing `torch.no_grad()` in inference
- scikit-learn: fitting inside a loop when `partial_fit` or warm starts apply, n_jobs underuse
- scipy: dense operations where sparse would suffice, redundant matrix copies
- numpy: repeated allocations where pre-allocated buffers work

**Classify each finding as:**
- **Confirmed bottleneck** — measured or structurally obvious (O(n^2) where O(n) exists)
- **Likely bottleneck** — pattern matches common perf issues but needs profiling
- **Optimization opportunity** — correct but slower than necessary

## Findings Format

For each finding, include:
- **Tag**: `[math-bug]`, `[math-risk]`, `[research-mismatch]`, `[logic-bug]`, `[logic-risk]`, `[stability-risk]`, `[perf-bottleneck]`, `[perf-risk]`, `[unverifiable-claim]`
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

Save the review to `.claude/output/reviews/YYYY-MM-DD-technical-review.md`.
