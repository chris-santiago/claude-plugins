# The assurance model

chris-code runs a lot of review gates. It's tempting to read a green pipeline as proof the change is correct. It isn't, and the framework is deliberately honest about that. Understanding *what the gates actually buy* is the difference between earned confidence and false confidence.

## The completion gate, concretely

`verification-before-completion` has six steps. Tests and lints run first, and a failure there is fixed before anything else runs. The four review steps then run together as one close round (below the list):

1. **Tests** — the full suite, zero failures. Not a subset, not "the tests I think are relevant."
2. **Lints** — the project linter, zero errors or warnings.
3. **Full review** — the scope-matched `*-design-reviewer` agents, read-only, returning PASS or CONCERNS.
4. **Requirements** — every spec/plan requirement traced to the code that implements it and a test that verifies it, with nothing implemented that wasn't asked for.
5. **Intent re-check** — the spec-blind `intent-reviewer` compares the running system to the frozen intent ledger.
6. **Mutation re-check** — the `mutation-tester` agent, in an isolated worktree, deliberately breaks the changed code and confirms a test fails, reverting each break. It uses no external mutation-testing tool (it edits the code and runs the project's own tests, so it is language-agnostic) and gates when a test executes changed code but doesn't fail when it's broken — a trivial test that proves nothing. Runs when the change includes testable source.

Steps 3, 5, and 6 are independent read-only reviews of the same committed HEAD, so they are dispatched together as one **close round**, with the Step 4 trace done alongside, and every finding is triaged once. Trivial findings are fixed inline; the non-trivial set goes through `remediating-issues` as one batch, and a second round re-checks only what that remediation could have changed. The cap is two rounds: whatever non-trivial work survives goes to you. [The close round](execution-mechanics.md#the-close-round) has the details.

A **PASS is not "nothing to do."** A gate can pass while carrying findings, and **PASS-with-findings is not clean**: each finding is verified real (via `receiving-code-review` — neither reflexively obeyed nor dismissed), then in-scope findings are fixed *in this change* and only a genuinely separable, larger improvement is deferred. Shipping an in-scope finding as "TODO: later" defeats the gate. The rest of this page is about *what those six steps do and don't prove*.

## More passes raise recall, not residual assurance

Stacking review stages does not multiply into a proof. Most of the gates are LLM judgments that share a model, a training distribution, and often a framing — so they tend to miss the same things together. Only a few axes are genuinely independent: the deterministic linter (not an LLM at all), conformance (does the behavior match the spec/intent), and the mutation gate (which breaks the code and runs the real tests — its verdict is test execution, not another LLM re-read). The rest are correlated re-reads.

The consequence: more passes surface **more** issues (higher recall), but a clean run means *"nothing these lenses caught,"* not *"nothing is wrong."* So chris-code weights **diversity over quantity** — a check that fails *differently* (a deterministic linter, a spec-blind behavior check, a mutation probe of test strength, an actual failing test, a human read) is worth more than another same-model re-review of the same diff.

## Conformance is not correctness

Every spec-anchored gate answers "does the code match the spec?" None of them asks "is the spec *right*?" A build can pass spec review, design review, and requirements tracing while faithfully implementing a spec that drifted from what you actually asked for.

That gap is why chris-code separates **intent** from **conformance**:

- A small **intent ledger** is frozen during `brainstorming` — up to seven observable acceptance statements in your words. You approve it; you don't author it. It lives *outside* the spec precisely so a spec-conformance check can't quietly redefine it.
- The **conformance pair** closes the loop. `spec-reviewer` checks code against the spec (per task). `intent-reviewer` is **spec-blind**: at completion it compares the *running system* to the *intent ledger*, never reading the spec. It earns its place by being decorrelated from every spec-anchored gate above it — it catches the one failure they structurally cannot.

The boundary is honest too: the intent re-check catches a spec that drifted from the ask. It does **not** validate that the ask itself was right — that judgment stays with you.

## Checklists are a floor, not a ceiling

The coder and quality-review agents carry inlined review checklists. Clearing every item is the *minimum* bar, not sufficiency — a change can pass every listed check and still be wrong for a reason no checklist enumerates. The agents are told to judge the whole change, then apply the rules, rather than treating a clean checklist as a passing grade.

## The integrator is the unguarded seam

Every doer is told "Do Not Trust the Report" — verify by reading the actual code, not an agent's summary. But the *orchestrator* decides what to integrate from exactly those summaries, one compression removed from the evidence, and nobody points that discipline back at its own inputs. chris-code closes this: before integrating a *judgment-shaped* verdict (a cohesion call, a "cannot verify," a conflict), the orchestrator grounds it by dispatch — it states a decidable claim and sends `claim-checker` to read the code and return a verdict word plus verbatim quoted lines, evidence mandatory, so the grounding doesn't cost the orchestrator its own context and the quoted lines terminate the chain (quotation needs no grounding of its own). Reviewers flag their own lossiness to say what to ground first. A verdict you haven't grounded in its evidence is an assertion laundered into a decision.

## What to take away

The gates are worth running — they catch real drift. Just don't read green as proof of its absence. The assurance comes from the *independent* and *decorrelated* checks (the linter, the spec-blind intent re-check, the mutation probe of test strength, real tests, your own read), not from the number of passes.
