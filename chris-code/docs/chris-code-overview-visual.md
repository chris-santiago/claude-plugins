---
marp: true
theme: gaia
class: lead
paginate: true
backgroundColor: #fbfbfd
color: #1d1d1f
header: 'chris-code'
footer: '5-minute overview'
style: |
  section { font-size: 26px; }
  h1 { color: #1a1a2e; }
  h2 { color: #16213e; }
  strong { color: #0a5; }
  :not(pre):not(marp-pre) > code {
    background: #e8eaf6; color: #283593;
    padding: 1px 6px; border-radius: 4px; font-weight: 500;
  }
  table { font-size: 22px; }
  section.lead h1 { font-size: 56px; }

  /* ---- diagram primitives ---- */
  .chev { color:#aab; font-size:22px; line-height:1; margin:1px 0; text-align:center; }
  .node { display:inline-block; border:1.5px solid #c5cae9; background:#eef1fb; color:#1a1a2e; border-radius:10px; padding:7px 16px; font-weight:600; font-size:19px; }
  .design{ background:#e8eaf6; border-color:#9fa8da; }
  .exec{ background:#d7f5e3; border-color:#7fd6a6; }
  .task{ background:#fff3cd; border-color:#ffd966; }
  .done{ background:#e2e8f0; border-color:#aab4c4; }
  .flow{ display:flex; flex-direction:column; align-items:center; gap:1px; margin-top:14px; }
  .legend{ display:flex; gap:24px; justify-content:center; margin-top:18px; font-size:16px; color:#555; }
  .legend span{ display:inline-flex; align-items:center; gap:7px; }
  .dot{ width:13px; height:13px; border-radius:3px; display:inline-block; }

  /* cards */
  .cards{ display:flex; gap:22px; justify-content:center; margin-top:30px; }
  .card{ flex:1; background:#fff; border:1px solid #e3e3ee; border-top:5px solid #0a5; border-radius:12px; padding:18px; box-shadow:0 2px 10px rgba(0,0,0,.06); }
  .cardnum{ font-size:30px; font-weight:800; color:#0a5; line-height:1; }
  .cardttl{ font-weight:700; font-size:20px; margin:8px 0 6px; color:#16213e; }
  .cardtxt{ font-size:16px; color:#444; line-height:1.45; }

  /* split */
  .split{ display:flex; gap:26px; justify-content:center; margin-top:24px; }
  .col{ flex:1; border-radius:12px; padding:16px 20px; }
  .stay{ background:#e7f7ee; border:1.5px solid #7fd6a6; }
  .go{ background:#f3f4f6; border:1.5px solid #cfd3da; }
  .colhdr{ font-weight:800; font-size:21px; margin-bottom:10px; }
  .stay .colhdr{ color:#0a7a4a; }
  .go .colhdr{ color:#7a7f87; }
  .col .item{ font-size:18px; padding:4px 0; color:#222; }
  .go .item{ color:#999; text-decoration:line-through; }
  .col .sub{ margin-top:8px; font-size:15px; color:#666; }

  /* dispatch */
  .filechip{ display:inline-block; background:#1a1a2e; color:#fff; padding:7px 16px; border-radius:8px; font-weight:600; font-size:19px; }
  .dispatch{ text-align:center; margin-top:10px; }
  .router{ color:#777; font-size:16px; margin:6px 0; }
  .lanes{ display:flex; gap:18px; justify-content:center; margin-top:4px; }
  .lane{ flex:1; display:flex; flex-direction:column; align-items:center; gap:8px; }
  .lanehdr{ font-weight:700; font-size:16px; padding:5px 4px; width:100%; border-radius:7px; }
  .green{ background:#d7f5e3; border:1.5px solid #7fd6a6; }
  .yellow{ background:#fff3cd; border:1.5px solid #ffd966; }
  .red{ background:#ffd9d9; border:1.5px solid #ef9a9a; }
  .muted{ background:#f0f0f0; border:1.5px solid #ddd; color:#aaa; text-decoration:line-through; }
  .lanenote{ font-size:14px; color:#666; }

  /* gates */
  .gates{ display:flex; align-items:center; justify-content:center; gap:8px; margin-top:32px; }
  .gate{ width:175px; height:104px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:6px; background:#eef1fb; border:2px solid #9fa8da; border-radius:12px; font-weight:700; font-size:18px; color:#1a1a2e; text-align:center; }
  .gnum{ width:26px; height:26px; border-radius:50%; background:#0a5; color:#fff; font-size:15px; display:flex; align-items:center; justify-content:center; }
  .garrow{ font-size:26px; color:#9fa8da; }
  .cap{ text-align:center; font-size:18px; color:#444; margin-top:24px; }

  /* staged parallelism */
  .stages{ margin-top:22px; }
  .stagerow{ display:flex; align-items:center; gap:16px; margin:6px 0; }
  .stagelbl{ width:90px; font-weight:700; color:#16213e; font-size:18px; }
  .tasks{ display:flex; gap:12px; }
  .t{ background:#d7f5e3; border:1.5px solid #7fd6a6; border-radius:9px; padding:8px 16px; font-weight:600; font-size:18px; }
  .tw{ background:#fff3cd; border-color:#ffd966; }
  .barrier{ text-align:center; color:#888; font-size:15px; margin:10px 0; border-top:1px dashed #ccc; padding-top:8px; }

  /* verification funnel */
  .vstack{ display:flex; flex-direction:column; align-items:center; gap:2px; margin-top:16px; }
  .vbar{ border-radius:9px; padding:9px 0; font-weight:600; font-size:18px; text-align:center; color:#16213e; background:#e8eaf6; border:1.5px solid #9fa8da; }
  .v1{ width:90%; } .v2{ width:78%; } .v3{ width:66%; } .v4{ width:54%; } .v5{ width:42%; }
  .vdone{ width:34%; background:#d7f5e3; border:1.5px solid #7fd6a6; border-radius:9px; padding:9px 0; text-align:center; font-weight:700; color:#0a7a4a; }
  .vchev{ color:#aab; font-size:18px; }
---

<!-- _class: lead -->

# chris-code

### An opinionated Claude Code workflow

Design before it codes. Review before it lands.

`25 skills · 13 agents · uniform review gates`

---

## What it is

A personal **Claude Code plugin** that turns the assistant from a free-form chat tool into a **fixed engineering pipeline**.

Drop it into any repo. Describe a feature (or type `/brainstorming`) and the workflow takes over:

> brainstorm intent → write a lean spec → hand off a thin plan → dispatch a coder per task → review in stages → gate every commit.

Derived from [obra/superpowers](https://github.com/obra/superpowers), redesigned around three failures it kept hitting:

---

## Why it exists: three failures

<div class="cards">
<div class="card"><div class="cardnum">1</div><div class="cardttl">Spec &amp; plan bloat</div><div class="cardtxt">Specs grew past 2,500 words; plans piled on another 5,000–10,000 words of code.</div></div>
<div class="card"><div class="cardnum">2</div><div class="cardttl">Shadow code</div><div class="cardtxt">Plans mandated complete code per step. Agents discarded it and rewrote against the real repo.</div></div>
<div class="card"><div class="cardnum">3</div><div class="cardttl">Inconsistent review</div><div class="cardtxt">Review folded into a single self-check pass, applied unevenly across tasks.</div></div>
</div>

> The rest of this deck is how chris-code answers each.

---

## The core idea

### "Contracts stay, choreography goes."

<div class="split">
<div class="col stay"><div class="colhdr">Contracts stay</div><div class="item">Spec invariants</div><div class="item">Public APIs &amp; signatures</div><div class="item">Data schemas</div><div class="sub">spec: contracts only</div></div>
<div class="col go"><div class="colhdr">Choreography goes</div><div class="item">Step-by-step code</div><div class="item">Inline scaffolds</div><div class="item">"do this, then that"</div><div class="sub">plan: what/where, no code</div></div>
</div>

<p class="cap">Agents ignored prescriptive code blocks and rewrote them anyway. Plans now say <b>what</b> and <b>where</b>; code is written against the real repo.</p>

---

## The pipeline

<div class="flow">
<div class="node design">brainstorming &nbsp;·&nbsp; intent, approaches, questions</div>
<div class="chev">↓</div>
<div class="node design">lean-spec &nbsp;·&nbsp; contracts only</div>
<div class="chev">↓</div>
<div class="node design">lean-plan &nbsp;·&nbsp; execution handoff</div>
<div class="chev">↓</div>
<div class="node exec">using-git-worktrees → subagent-driven-development</div>
<div class="chev">↓</div>
<div class="node task">per task: coder → spec → quality → commit gate</div>
<div class="chev">↓</div>
<div class="node done">verification-before-completion</div>
<div class="chev">↓</div>
<div class="node done">finishing-a-development-branch</div>
</div>

<div class="legend">
<span><span class="dot" style="background:#9fa8da"></span>Design</span>
<span><span class="dot" style="background:#7fd6a6"></span>Execution</span>
<span><span class="dot" style="background:#ffd966"></span>Per task</span>
<span><span class="dot" style="background:#aab4c4"></span>Completion</span>
</div>

---

## The agent layer

<div class="dispatch">
<div class="filechip">a .py file in a torch project</div>
<div class="router">↓ &nbsp; dispatched by scope (extension + deps) &nbsp; ↓</div>
<div class="lanes">
<div class="lane"><div class="lanehdr green">coder — exclusive</div><div class="node green">pytorch-coder ✓</div><div class="node muted">python-coder</div><div class="lanenote">most-specific wins</div></div>
<div class="lane"><div class="lanehdr yellow">quality-reviewer — additive</div><div class="node yellow">python-quality-reviewer</div><div class="node yellow">pytorch-quality-reviewer</div><div class="lanenote">all matching fire</div></div>
<div class="lane"><div class="lanehdr red">review-lite — commit gate</div><div class="node red">python-review-lite</div><div class="lanenote">idiom + lint, per commit</div></div>
<div class="lane"><div class="lanehdr" style="background:#e8eaf6;border:1.5px solid #9fa8da;color:#1a1a2e">design-reviewer — verification gate</div><div class="node design">python-design-reviewer</div><div class="lanenote">senior cohesion, read-only</div></div>
</div>
</div>

---

## Review is a uniform, multi-stage gate

<div class="gates">
<div class="gate"><span class="gnum">1</span>Spec<br>compliance</div>
<div class="garrow">→</div>
<div class="gate"><span class="gnum">2</span>Code<br>quality</div>
<div class="garrow">→</div>
<div class="gate"><span class="gnum">3</span>Commit<br>lint gate</div>
<div class="garrow">→</div>
<div class="gate"><span class="gnum">4</span>Full-diff<br>pass</div>
</div>

<p class="cap">The <b>same</b> gates on every task. No task is "small enough to skip." <b>Do Not Trust the Report</b> — reviewers re-read the code, not the summary. More stages raise <i>recall</i>, not proof: they catch more, they don't certify the rest is clean.</p>

---

## Parallelism is a feature, not a footgun

<div class="stages">
<div class="stagerow"><div class="stagelbl">Stage 1</div><div class="tasks"><div class="t">Task A · api/</div><div class="t">Task B · db/</div><div class="t">Task C · ui/</div></div></div>
<div class="barrier">file footprints mapped up front · non-overlapping tasks run concurrently</div>
<div class="stagerow"><div class="stagelbl">Stage 2</div><div class="tasks"><div class="t tw">Task D · api/ + db/ (waits — overlaps A &amp; B)</div></div></div>
</div>

<p class="cap">Superpowers flagged parallel implementers as dangerous. chris-code solves it by <b>scheduling</b>, not prohibition.</p>

---

## Verification before "done"

<div class="vstack">
<div class="vbar v1">1 · Tests — full suite, zero failures</div>
<div class="vchev">↓</div>
<div class="vbar v2">2 · Lints — zero errors / warnings</div>
<div class="vchev">↓</div>
<div class="vbar v3">3 · Full review — scope-matched *-design-reviewer agents</div>
<div class="vchev">↓</div>
<div class="vbar v4">4 · Requirements — every item traced</div>
<div class="vchev">↓</div>
<div class="vbar v5">5 · Intent re-check — spec-blind, behavior vs the original ask</div>
<div class="vchev">↓</div>
<div class="vdone">✓ may claim done</div>
</div>

<p class="cap">No completion claim without fresh evidence. "I'm confident" → run the commands. <b>Green means these lenses caught nothing, not that nothing's wrong</b> — the independent axes (deterministic lint, spec-blind intent) carry more than another same-model re-read.</p>

---

## Beyond the pipeline: quality campaigns

On-demand skills for when you want to go hunting:

- **`bug-hunt`** — parallel adversarial edge-case tests across subsystems
- **`test-sweep`** — iterative combinatorial test-and-fix campaign
- **`code-archaeology`** — dead code, stubs, spec-vs-impl gaps
- **`technical-review`** — math / algorithm / numerical correctness for ML
- **`python-review` · `rust-review`** — senior refactor & API-design passes
- **`release`** — version bump + changelog + GitHub release

---

## Remediation & coherent change

<p class="cap" style="margin-top:6px">A bug, a refactor, an API alignment — the behavior is settled, only the <b>implementation</b> is open. One engine handles all of them: find the fix that fits the codebase, and defend it against the alternatives.</p>

<div class="flow">
<div class="node design">remediating-issues &nbsp;·&nbsp; systematic-debugging &nbsp;·&nbsp; lean-spec &nbsp;·&nbsp; direct</div>
<div class="chev">↓ &nbsp; feed a <b>determined</b> change</div>
<div class="node exec">coherent-change &nbsp;·&nbsp; research → defend the most coherent fix → implement → lite-review</div>
<div class="chev">↓ &nbsp; hand back a working, lite-reviewed change</div>
<div class="node task">caller closes &nbsp;·&nbsp; regression / coverage → design-reviewer gate → land</div>
</div>

<p class="cap">Signature output: a <b>defended choice</b> — every candidate rooted in how the codebase already solves it, plus why the chosen one wins. Ship the fix that looks like it was always there.</p>

---

<!-- _class: lead -->

## How to use it

Drop into any repo. Describe a feature, or type **`/brainstorming`**.

The workflow designs before it codes, keeps the main context clean by offloading to focused subagents, and **catches agent drift before it reaches `main`**.

### That's chris-code.
