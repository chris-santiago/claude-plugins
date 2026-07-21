# Speaker companion — An introduction to chris-code

One section per slide, numbered in lockstep with the deck. Deliver the narrative; the "details not on the slide" are prompts for questions and asides.

---

## Slide 1 — An introduction to chris-code

Open by framing the audience gap. Everyone here has used Claude Code as a chat assistant: you ask, it types. This deck is about a different mode of working — a plugin that turns that same assistant into a disciplined engineering workflow, with opinions about *how* a change should be made. The promise for the next twenty minutes: by the end you'll understand what chris-code is, why it's shaped the way it is, and how a single change moves through it from idea to merged.

Set expectations that this is a *concepts* talk, not a tour of commands. The point is the philosophy — once you have that, the specific skills are self-explanatory.

**Details not on the slide**

- chris-code is one of three plugins in the same repo (alongside `ml-lab` and `ml-journal`); this talk is only about chris-code.
- It branched from an open-source project called *superpowers* — worth mentioning now only if someone already knows it; there's a dedicated slide later.

---

## Slide 2 — The starting problem

Motivate the whole framework by naming the failure modes of free-form assistance. Three of them. First: a free-form assistant starts typing immediately, which is fine for trivia but fatal for anything with a real design space — the first approach that compiles silently *becomes* the design, and the reasoning that would have found a better one never happens. Second: agent-written changes land unreviewed, so drift reaches `main` before a human reads it against the original ask. Third: a fresh agent that never heard your conversation reconstructs your intent — and does it confidently, which is worse than doing it hesitantly.

Land the blockquote: chris-code is a set of skills and agents that impose a fixed workflow to close exactly these three gaps. Define the two nouns now because they recur on every later slide: a *skill* is a reusable instruction module; an *agent* is a subagent with a defined role that runs in its own context.

**Details not on the slide**

- These three failure modes map to the three later principles: design-before-code, the review gates, and the intent-carrying brief. You can foreshadow that.
- "Confidently wrong" is the expensive one — a hesitant wrong answer gets caught, a confident one gets merged.

---

## Slide 3 — What chris-code is

This is the map for the whole talk. Every non-trivial change runs the same path: brainstorm, lean spec, lean plan, execute, verify, finish. Group it into three phases so it's memorable — DESIGN settles what and why, BUILD dispatches a coder per task, PROVE gates the result before anyone says "done."

Point at the orange arc under the figure: the intent ledger. It's frozen in your words at the very first step and re-checked against the actually-shipped behavior at the verify step. Intent bookends the whole pipeline. That arc is the single most important idea on the slide, so don't rush past it — it's what makes the difference between "the code matches the spec" and "the system does what you asked."

Close on scale: 25 skills, 13 agents, mostly auto-dispatched. The user rarely names a tool; they describe the work and the routing is mechanical.

**Details not on the slide**

- Every subsequent slide zooms into one box or one arc of this figure. Tell the audience that so they can place each principle.
- "Non-trivial" is load-bearing — a one-off question doesn't enter this pipeline at all (revisited on the when-to-use slide).

---

## Slide 4 — Principle 1: design before code

`brainstorming` is a *hard gate*, not a suggestion. No implementation begins until a design exists and the user has approved it. Emphasize the anti-pattern it explicitly rejects: "this is too simple to need a design." The design can be one paragraph, but it has to exist and be approved.

Then the intent ledger, which the pipeline slide previewed. Up to seven observable acceptance statements, in the user's words. The subtle part, worth stating slowly: the *assistant* drafts them from the dialogue, and the *user* approves them — it's a lightweight confirm step, not a writing assignment handed back to the user. And it's frozen: it changes only by explicit user decision.

The "why" box is the payoff. The ledger lives *outside* the spec on purpose. A spec gets elaborated and reframed as design proceeds; if intent lived inside it, a spec-conformance check could quietly redefine the goal and still pass. Keeping the ledger separate gives the final gate an oracle the spec can't edit.

**Details not on the slide**

- "Observable acceptance statement" means something you could watch the running system do and judge met-or-not — not an implementation step, not a design decision.
- This connects directly to slide 12, step 5: the spec-blind intent re-check reads this exact ledger.

---

## Slide 5 — Principle 2: two kinds of work

The key move here is that chris-code does *not* force everything through a full brainstorm. It forks on one question: is *what to build* already settled? If no, the work is design-open and goes to `brainstorming`. If yes, it's a determined change and goes to a different engine.

Define "determined" carefully because the intuition is misleading: determined means the intended behavior is settled — a refactor, a migration, an already-specced feature — and the only open question is which implementation fits. Hammer the caveat on the slide: determined is *not* the same as trivial. A determined change can be large and subtle; "settled behavior" narrows the *what*, not the *how*.

Note from the figure that design-open work doesn't stay design-open: brainstorming settles the design, and then it rejoins the same spec-plan-build path as determined work. Two front doors, one hallway.

**Details not on the slide**

- The line "many implementations pass, only one fits" is the entire thesis of the next two slides — plant it here.
- If asked "how do I know which one I'm in": if you can write the change as one sentence and the only argument left is *how*, it's determined.

---

## Slide 6 — The coherent-change engine

This is the intellectual core of the talk, so slow down. Determined work runs through the `coherent-change` engine, and its premise is the thing most people get wrong: a change can work and still be wrong.

Walk the logic. Every candidate implementation that compiles has the *same behavior* — so the tests, which check behavior, can't tell them apart. The difference between a good and bad implementation is things tests are blind to: did it reuse the helper the codebase already has, or reinvent it? Did it mirror the neighbors' error convention, or introduce a third one? That difference is invisible on the day you ship and expensive the day the next reader hits the seam.

So the engine's central move: the coherent implementation is *discovered from the codebase*, not invented. It dispatches parallel Explore agents to inventory the affected code before proposing anything. And the tell that the research isn't finished is beautifully simple — if you can only name one approach, you haven't looked hard enough. Close on the blockquote: working isn't coherent, and shipping the first thing that compiles is how debt accretes one reasonable-looking diff at a time.

**Details not on the slide**

- "Coherent" here means fits-the-codebase: reuses its patterns, respects its contracts, reads like the code around it.
- This engine isn't usually invoked alone — front-ends like bug remediation and debugging call it. For an intro audience that's a detail; mention only if asked.

---

## Slide 7 — What the engine produces

The engine's output is a *defended choice*, and the whole slide is that one figure. The framing line to deliver: the point is not a working diff, it's a *defensible* one.

Walk the five bands quickly but deliberately, because each one closes a specific way of being wrong. Reframe: the few facts from research that change the problem. Proposed change: concrete and minimal — what changes, what's deleted, what's deliberately left alone. Correct across every case: a table over *all* affected cases, plus the honesty line "cases I might be missing, and how I'd find them" — that line is what turns asserting coverage into proving it. Why it's most coherent: reuse, idiom-fit, smallest blast radius. Defense of alternatives: a real rebuttal of every rejected option, not a dismissal.

The meta-point: this structure is what makes a change *reviewable*. A reviewer can check the reasoning that rejected the alternatives, not just the diff that survived.

**Details not on the slide**

- The Iron Law at the top of the figure — research before proposing — is the engine's one non-negotiable rule.
- Point 3's "cases I might be missing" line is the direct fix for the classic failure where a change handles the happy path and silently breaks a sibling branch.

---

## Slide 8 — Principle 3: lean artifacts

Step back to the pipeline. Between design and execution sit two documents, and they're deliberately thin. The rule is a phrase worth repeating: "contracts stay, choreography goes." A lean spec keeps behavior, interfaces, invariants, and acceptance criteria. A lean plan keeps what to do and where. Neither keeps the *how* — the code — because the implementing agent will rewrite pasted code anyway, so writing it is wasted effort that also creates a plan-versus-reality mismatch.

Give them the concrete test: if a line would change when you reimplement the feature in another language, it's choreography and belongs in the plan, not the spec; and actual code belongs in neither.

End with the forward hook: this leanness isn't just tidiness. The lean spec is the mechanism that makes the next principle — dispatch — safe. That's a genuine cause-and-effect, not a slogan, and the next slide explains why.

**Details not on the slide**

- This is the sharpest divergence from the parent project, whose plans included full code "as if the engineer has zero context." Coming up on slide 13.
- "Word-efficiency" is an explicit principle in the skill: every line must be load-bearing; length is treated as a smell.

---

## Slide 9 — Principle 4: dispatch, and the intent channel

Now the payoff of lean artifacts. chris-code offloads focused work to subagents to keep the orchestrator — the main planning session — from filling up with noise. But dispatch has a cost, so there's a rule for when it's safe: dispatch when the task's context is recoverable from artifacts; stay in-session when the *why* lives only in the conversation.

Use the figure to make it concrete. The orchestrator hands the coder a *brief* — mostly pointers: the contract built in an earlier task lives here, read these spec sections, obey these constraints verbatim. But look at the highlighted line: INTENT. A fresh coder can recover *what* and *where* by reading the spec and the repo. It cannot recover *why* — the outcome the change is supposed to produce — because that lived only in your conversation. So the brief must carry it. The grey panel states the whole lesson: hand over only what and where, and a capable coder will ship the wrong thing correctly.

Mention the return leg briefly (bottom-left of the figure): what a subagent hands back is a compression, so the orchestrator re-reads the actual code slice rather than trusting the summary.

**Details not on the slide**

- "Ships the wrong thing correctly" is the memorable line — a coder optimizing a diff without the goal produces clean code that solves the wrong problem.
- The loop is two-sided: coders are instructed to *demand* the why and escalate rather than guess when a brief omits it.

---

## Slide 10 — Parallelism without collisions

Dispatch raises an obvious worry: if you run several coders at once, don't they collide? chris-code's answer is scheduling, not prohibition. Before dispatching, the orchestrator maps each task's file footprint — every source and test file it will touch — and groups tasks into stages where nothing overlaps.

Walk the figure. Stage 1: Tasks A and B touch different files, so they run in parallel. Then a barrier — wait for all reviews to pass. Stage 2: Task C touches parser.py again, the same file Task A touched, so it can't run alongside; it waits. Another barrier. Stage 3: two more disjoint tasks run together. The rule is mechanical: share a file, get serialized; otherwise, run concurrently.

The contrast with the parent project is the punchline: superpowers lists parallel implementers as a *red flag* because they collide. chris-code gets the speed of parallelism safely by scheduling around the collisions instead of banning the technique.

**Details not on the slide**

- "When in doubt, serialize" is the actual heuristic — the cost of a collision is higher than the cost of waiting.
- Footprint includes test files, not just source; two tasks editing the same `conftest.py` are serialized even if their source files differ.

---

## Slide 11 — Principle 5: prove it, honestly

chris-code runs a lot of review gates, and the honest slide is the one that says: green does not mean correct. This is where the framework earns trust by *not* overclaiming.

Use the two columns. On the left, most of the gates are LLM judgments that share a model, a training distribution, and a framing — so they tend to miss the same things together. Stacking more of them raises *recall* (you catch more), but it never multiplies into a proof, because the passes are correlated. On the right are the genuinely independent axes: a deterministic linter that isn't an LLM at all, a spec-blind intent re-check, an actual failing test, and your own read. Those fail *differently*, so each one adds real assurance. The design principle: diversity over quantity.

Define conformance because it's the crux: conformance asks "does the code match the spec." It is not correctness — a build can conform perfectly to a spec that drifted from what you asked for. That gap is exactly why the intent re-check on the next slide is spec-blind.

**Details not on the slide**

- The takeaway phrasing: green means "nothing these lenses caught," not "nothing is wrong."
- This honesty is itself a feature — a framework that claimed green = correct would be lying, and users would over-trust it.

---

## Slide 12 — The completion gate

Make the previous slide concrete: here is the actual gate that runs before anything is called done. Five steps, in order, and a failing step stops the line. Tests: full suite, zero failures. Lints: zero warnings. Design review: the senior read-only reviewers return PASS or CONCERNS. Requirements: every spec item traced to both the code that implements it and a test that verifies it. And step five, the one that matters most: a spec-blind intent-reviewer compares the shipped behavior to the frozen ledger from slide 4.

Stress two things. First, a PASS is not "nothing to do" — a gate can pass while carrying findings, and PASS-with-findings is not clean; the findings get triaged and the in-scope ones fixed now. Second, step 5 is the only gate that never reads the spec, which is precisely what lets it catch a spec that drifted from the ask — the failure every spec-anchored gate structurally cannot see.

**Details not on the slide**

- Steps 1–4 are conformance-flavored; step 5 is the decorrelated intent axis from the previous slide, made operational.
- "Traced to code *and* a test" (step 4) is stricter than it sounds: an untested requirement fails the gate even if the code is present.

---

## Slide 13 — Zooming out: the surface area

Having walked the pipeline, pull back and show the whole toolbox — because newcomers routinely underestimate the breadth. Twenty-five skills, organized into eight functional groups: design and planning, execution, the change engine, testing, completion, review, quality campaigns, and meta. The reassuring part to say out loud: you don't memorize these. Most fire automatically — invoked by the pipeline, by another skill, or by a phrase in your request — so you describe the work and the right skill runs.

Then land the quiet thesis on the figure's footer: even at the skill layer, thirteen of the twenty-five are about testing, review, or debugging, against nine about building. The tool spends more of itself on checking work than on producing it. That sets up the next slide, which makes the same point far more sharply at the agent layer.

**Details not on the slide**

- The color tags (build / assure / meta) are a soft visual; the precise claim is the 13-of-25 count in the footer.
- The eight groups map to the docs' own Reference structure, so anyone who opens the docs later sees the same organization.

---

## Slide 14 — One coder, ten checkers

This is the slide that makes the breadth *mean* something. Thirteen dedicated agents — a layer superpowers doesn't have at all — and the split is stark: three write code, ten check it. The row of squares makes it visceral; three blue, ten amber.

Walk the roles so the ten isn't abstract: three coders (Python, PyTorch, Rust); three quality reviewers that check principle-adherence and bugs after spec compliance passes; two commit-lite gates for fast idiom-and-lint checks; two senior design reviewers at the final gate; the two-agent conformance pair (spec and intent); and one adversarial test-writer. For every agent that authors a change, more than three exist purely to verify it. That ratio *is* the philosophy — a free-form assistant is all author and no auditor, and chris-code deliberately inverts that.

Note the dispatch mechanic in passing, because the next-but-one slide develops it: every one of these is scope-matched by file type, so you never pick an agent by hand.

**Details not on the slide**

- Coders are "exclusive" (the most specific one wins); reviewers are "additive" (all matching ones fire on the same diff). That's why one coder faces many reviewers.
- The bug-hunter writes tests and never fixes — it's a test-writer, not a coder, which is why it sits on the assure side.

---

## Slide 15 — Lineage: a superset of superpowers

Give credit and context. chris-code didn't appear from nowhere; it forked from the open-source *superpowers* project at v5.1.0 and kept the entire brainstorm → plan → execute → review → finish spine. If someone in the room knows superpowers, tell them they already know most of this. The inventory deltas tell the story: skills grew 14 → 25, agents 0 → 13, and a legacy hook went 1 → 0. Every superpowers skill still exists in chris-code — one renamed, one split — so it's a true superset, not a rewrite.

Don't dwell here unless the audience is superpowers users. The single sentence that matters: chris-code is superpowers plus an agent layer, plus lean artifacts, plus a coherence engine. The next slide picks the most important of those additions and makes the case.

**Details not on the slide**

- The six thematic shifts (lean artifacts, scoped agents, uniform review gate, parallelism-as-feature, native-tools-hard-gate, coherence enforcement) are documented in full in the repo's `superpowers-comparison.md` if anyone wants receipts.
- "Hooks 1 → 0" isn't a regression — chris-code moved that behavior into skills; call it out only if asked.

---

## Slide 16 — The dispatch difference

This is the slide to slow down on, because it's the advantage people most often miss. Both projects dispatch subagents. The difference is *what the agent already knows when it arrives*. In superpowers, coding and review run through **generic** subagents steered by a prompt template the orchestrator supplies each time — so code quality depends on the orchestrator remembering to ask for it. If the prompt doesn't mention cohesion, idiom, and API design, the reviewer doesn't check them.

chris-code inverts the burden. Each agent is a **named, scoped role whose system prompt already carries the quality bar**. The coders internalize the review principles so their code passes on the first attempt; the reviewers enforce cohesion, idiom, and API design by definition of what they are. Quality stops being a prompt the orchestrator might forget and becomes a property of *who runs the task*. That's the sentence to land: it can't be forgotten, because it's baked into the agent, not the request.

**Details not on the slide**

- Concrete dispatch example: in a PyTorch repo, `pytorch-coder` beats `python-coder` automatically, and both `python-quality-reviewer` and `pytorch-quality-reviewer` fire on the diff.
- This is why the ratio on slide 14 actually buys something: ten checkers only help if each one reliably checks the right things — which the scoped system prompts guarantee.

---

## Slide 17 — When to use it (and when not)

Be honest about fit, which builds credibility. Reach for chris-code when the change is substantial enough to deserve a design and a review, when you want intent settled before code and drift caught before `main`, and when you work in Python or Rust — because the coder and review agents are language-scoped (the workflow skills themselves are language-agnostic).

And the counter-case, stated plainly: if you just want a quick one-off answer, you don't need any of this. The pipeline is overhead, and overhead only pays off on changes big enough to warrant a design and a review. Saying this out loud stops people from resenting the ceremony on trivia — it's opt-in by the size of the work.

**Details not on the slide**

- Language scoping is about the *agents*, not the philosophy; the design/plan/review discipline applies to any language, you just won't get a bespoke coder agent.
- Good audience question to invite: "what counts as substantial?" — roughly, anything you'd want a colleague to review.

---

## Slide 18 — Recap: five ideas

Land the five takeaways as a memorable set. Design before code — brainstorming is a hard gate and intent is frozen in your words. Determined isn't design-open — settled behavior routes to the coherent-change engine, which defends its choice rather than shipping the first thing that works. Lean artifacts — contracts stay, choreography goes, and that leanness is what makes dispatch lossless. Dispatch by scope but carry intent — a fresh agent recovers what and where by reading, so the brief must carry the why. And green isn't correct — assurance comes from the independent checks, not the number of passes.

Close on the four-verb summary: design it, defend it, dispatch it, prove it. Then point them to the docs — the Explanation section of the chris-code site goes deeper on every one of these — and tell them the entry point is simply `/brainstorming` in any chris-code-enabled session.

**Details not on the slide**

- If you have time for one deeper thread, the richest is slide 6–7 (coherent change); if you have to cut, cut slide 10 (parallelism) — it's mechanics, not philosophy.
- The docs site has a dedicated "Coherent change" explanation page that expands slide 6–7, including how coherence is preserved when a change fans out across parallel tasks.
