# The assurance model

chris-code runs a lot of review gates. It's tempting to read a green pipeline as proof the change is correct. It isn't, and the framework is deliberately honest about that. Understanding *what the gates actually buy* is the difference between earned confidence and false confidence.

## The completion gate, concretely

`verification-before-completion` runs five steps in order, and a step that fails stops the line:

1. **Tests** — the full suite, zero failures. Not a subset, not "the tests I think are relevant."
2. **Lints** — the project linter, zero errors or warnings.
3. **Full review** — the scope-matched `*-design-reviewer` agents, read-only, returning PASS or CONCERNS.
4. **Requirements** — every spec/plan requirement traced to the code that implements it and a test that verifies it, with nothing implemented that wasn't asked for.
5. **Intent re-check** — the spec-blind `intent-reviewer` compares the running system to the frozen intent ledger.

A **PASS is not "nothing to do."** A gate can pass while carrying findings, and **PASS-with-findings is not clean**: each finding is verified real (via `receiving-code-review` — neither reflexively obeyed nor dismissed), then in-scope findings are fixed *in this change* and only a genuinely separable, larger improvement is deferred. Shipping an in-scope finding as "TODO: later" defeats the gate. The rest of this page is about *what those five steps do and don't prove*.

## More passes raise recall, not residual assurance

Stacking review stages does not multiply into a proof. Most of the gates are LLM judgments that share a model, a training distribution, and often a framing — so they tend to miss the same things together. Only about **two axes are genuinely independent**: the deterministic linter (not an LLM at all) and conformance (does the behavior match the spec/intent). The rest are correlated re-reads.

The consequence: more passes surface **more** issues (higher recall), but a clean run means *"nothing these lenses caught,"* not *"nothing is wrong."* So chris-code weights **diversity over quantity** — a check that fails *differently* (a deterministic linter, a spec-blind behavior check, an actual failing test, a human read) is worth more than another same-model re-review of the same diff.

## Conformance is not correctness

Every spec-anchored gate answers "does the code match the spec?" None of them asks "is the spec *right*?" A build can pass spec review, design review, and requirements tracing while faithfully implementing a spec that drifted from what you actually asked for.

That gap is why chris-code separates **intent** from **conformance**:

- A small **intent ledger** is frozen during `brainstorming` — up to seven observable acceptance statements in your words. You approve it; you don't author it. It lives *outside* the spec precisely so a spec-conformance check can't quietly redefine it.
- The **conformance pair** closes the loop. `spec-reviewer` checks code against the spec (per task). `intent-reviewer` is **spec-blind**: at completion it compares the *running system* to the *intent ledger*, never reading the spec. It earns its place by being decorrelated from every spec-anchored gate above it — it catches the one failure they structurally cannot.

The boundary is honest too: the intent re-check catches a spec that drifted from the ask. It does **not** validate that the ask itself was right — that judgment stays with you.

## Checklists are a floor, not a ceiling

The coder and quality-review agents carry inlined review checklists. Clearing every item is the *minimum* bar, not sufficiency — a change can pass every listed check and still be wrong for a reason no checklist enumerates. The agents are told to judge the whole change, then apply the rules, rather than treating a clean checklist as a passing grade.

## The integrator is the unguarded seam

Every doer is told "Do Not Trust the Report" — verify by reading the actual code, not an agent's summary. But the *orchestrator* decides what to integrate from exactly those summaries, one compression removed from the evidence, and nobody points that discipline back at its own inputs. chris-code closes this: before integrating a *judgment-shaped* verdict (a cohesion call, a "cannot verify," a conflict), the orchestrator re-reads the actual code slice rather than the summary, and reviewers flag their own lossiness to say where to look first. A verdict you haven't grounded in its evidence is an assertion laundered into a decision.

## What to take away

The gates are worth running — they catch real drift. Just don't read green as proof of its absence. The assurance comes from the *independent* and *decorrelated* checks (the linter, the spec-blind intent re-check, real tests, your own read), not from the number of passes.
