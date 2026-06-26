---
marp: true
theme: gaia
class: lead
paginate: true
backgroundColor: #fbfbfd
color: #1d1d1f
header: 'chris-code ← superpowers'
footer: 'Coming from superpowers'
style: |
  section { font-size: 26px; }
  h1 { color: #1a1a2e; }
  h2 { color: #16213e; }
  strong { color: #0a5; }
  :not(pre):not(marp-pre) > code {
    background: #e8eaf6; color: #283593;
    padding: 1px 6px; border-radius: 4px; font-weight: 500;
  }
  table { font-size: 21px; }
  section.lead h1 { font-size: 54px; }

  /* primitives */
  .chev { color:#aab; font-size:22px; line-height:1; text-align:center; }
  .node { display:inline-block; border:1.5px solid #c5cae9; background:#eef1fb; color:#1a1a2e; border-radius:10px; padding:7px 16px; font-weight:600; font-size:18px; }
  .design{ background:#e8eaf6; border-color:#9fa8da; }
  .exec{ background:#d7f5e3; border-color:#7fd6a6; }
  .task{ background:#fff3cd; border-color:#ffd966; }
  .done{ background:#e2e8f0; border-color:#aab4c4; }
  .redn{ background:#ffe2e2; border-color:#ef9a9a; color:#a02828; }
  .cap { text-align:center; font-size:18px; color:#444; margin-top:22px; }
  .gnum{ width:30px; height:30px; border-radius:50%; background:#0a5; color:#fff; font-size:16px; display:inline-flex; align-items:center; justify-content:center; flex:none; font-weight:700; }

  /* cards */
  .cards{ display:flex; gap:22px; justify-content:center; margin-top:34px; }
  .card{ flex:1; background:#fff; border:1px solid #e3e3ee; border-top:5px solid #0a5; border-radius:12px; padding:18px; box-shadow:0 2px 10px rgba(0,0,0,.06); }
  .cardnum{ font-size:30px; font-weight:800; color:#0a5; line-height:1; }
  .cardttl{ font-weight:700; font-size:20px; margin:8px 0 6px; color:#16213e; }
  .cardtxt{ font-size:16px; color:#444; line-height:1.45; }

  /* before/after compare */
  .cmp{ display:flex; gap:16px; justify-content:center; align-items:stretch; margin-top:24px; }
  .panel{ flex:1; border-radius:12px; padding:16px 20px; }
  .sp{ background:#f3f4f6; border:1.5px solid #cfd3da; }
  .cc{ background:#e7f7ee; border:1.5px solid #7fd6a6; }
  .panel h3{ margin:0 0 10px; font-size:20px; }
  .sp h3{ color:#7a7f87; } .cc h3{ color:#0a7a4a; }
  .panel .r{ font-size:17px; padding:5px 0; color:#222; }
  .panel .note{ margin-top:10px; font-size:15px; color:#666; font-style:italic; }
  .vsbadge{ align-self:center; font-weight:800; color:#aab; font-size:22px; }

  /* shift list */
  .shiftlist{ display:flex; flex-direction:column; gap:11px; margin:28px auto 0; max-width:740px; }
  .shift{ display:flex; align-items:center; gap:14px; font-size:22px; background:#fff; border:1px solid #e3e3ee; border-radius:10px; padding:10px 18px; }

  /* dispatch fan-out */
  .filechip{ display:inline-block; background:#1a1a2e; color:#fff; padding:7px 16px; border-radius:8px; font-weight:600; font-size:18px; }
  .dispatch{ text-align:center; margin-top:8px; }
  .router{ color:#777; font-size:16px; margin:6px 0; }
  .lanes{ display:flex; gap:18px; justify-content:center; margin-top:4px; }
  .lane{ flex:1; display:flex; flex-direction:column; align-items:center; gap:8px; }
  .lanehdr{ font-weight:700; font-size:16px; padding:5px 4px; width:100%; border-radius:7px; }
  .green{ background:#d7f5e3; border:1.5px solid #7fd6a6; }
  .yellow{ background:#fff3cd; border:1.5px solid #ffd966; }
  .red{ background:#ffd9d9; border:1.5px solid #ef9a9a; }
  .indigo{ background:#e8eaf6; border:1.5px solid #9fa8da; }
  .muted{ background:#f0f0f0; border:1.5px solid #ddd; color:#aaa; text-decoration:line-through; }
  .lanenote{ font-size:14px; color:#666; }

  /* gate compare (review) */
  .gatecompare{ margin-top:26px; }
  .gaterow{ display:flex; align-items:center; gap:8px; margin:10px 0; }
  .glbl{ width:120px; font-weight:700; font-size:17px; }
  .gmini{ padding:8px 14px; border-radius:9px; font-size:16px; font-weight:600; border:1.5px solid; }
  .gmini.base{ background:#eef1fb; border-color:#9fa8da; color:#1a1a2e; }
  .gmini.add{ background:#d7f5e3; border-color:#7fd6a6; color:#0a7a4a; }
  .gsep{ color:#9fa8da; font-size:18px; }

  /* parallelism bands */
  .band{ border-radius:12px; padding:14px 18px; margin:10px 0; }
  .bad{ background:#fdeeee; border:1.5px dashed #ef9a9a; }
  .good{ background:#e7f7ee; border:1.5px solid #7fd6a6; }
  .bandhdr{ font-weight:700; font-size:18px; margin-bottom:8px; }
  .bandnote{ font-size:15px; color:#666; margin-top:6px; }
  .par{ display:flex; gap:10px; }
  .pt{ background:#fff; border:1.5px solid #ef9a9a; border-radius:8px; padding:6px 14px; font-size:16px; font-weight:600; color:#a02828; }
  .xmark{ color:#c0392b; font-weight:800; } .check{ color:#0a7a4a; font-weight:800; }
  .stagerow{ display:flex; align-items:center; gap:12px; margin:4px 0; }
  .stagelbl{ width:78px; font-weight:700; color:#16213e; font-size:16px; }
  .t{ background:#d7f5e3; border:1.5px solid #7fd6a6; border-radius:8px; padding:6px 14px; font-weight:600; font-size:16px; }
  .tw{ background:#fff3cd; border-color:#ffd966; }

  /* decision tree (worktree) */
  .tree{ display:flex; flex-direction:column; align-items:center; gap:4px; margin-top:14px; }
  .branchrow{ display:flex; gap:40px; justify-content:center; margin-top:8px; align-items:flex-start; }
  .branch{ display:flex; flex-direction:column; align-items:center; gap:8px; }
  .ylabel{ font-weight:700; color:#555; font-size:16px; }
  .twobox{ display:flex; flex-direction:column; gap:8px; }

  /* checklist */
  .checklist{ max-width:860px; margin:24px auto 0; }
  .ci{ font-size:19px; padding:6px 0; color:#222; }

  /* what's new */
  .newhdr{ font-weight:700; color:#0a7a4a; font-size:19px; margin:18px 0 8px; text-align:center; }
  .chiprow{ display:flex; flex-wrap:wrap; gap:6px; justify-content:center; max-width:920px; margin:0 auto; }
  .chip{ display:inline-block; background:#e8eaf6; border:1px solid #c5cae9; color:#283593; border-radius:14px; padding:5px 13px; font-size:16px; font-weight:600; }
  .arow{ font-size:17px; text-align:center; padding:3px 0; color:#222; }
---

<!-- _class: lead -->

# Coming from superpowers?

### You already know 80% of chris-code.

Same `brainstorm → plan → execute → review → finish` pipeline.
Same skill names. Same TDD and systematic-debugging discipline.

This deck is the other **20%**, and the *why*.

---

## What feels different, day to day

<div class="cards">
<div class="card"><div class="cardnum">1</div><div class="cardttl">Shorter specs &amp; plans</div><div class="cardtxt">No more 2,500-word specs or 10k-word plans full of code the implementer throws away.</div></div>
<div class="card"><div class="cardnum">2</div><div class="cardttl">Dedicated agents</div><div class="cardtxt">Coding and review run through named agents auto-dispatched by file type. You rarely pick one.</div></div>
<div class="card"><div class="cardnum">3</div><div class="cardttl">Same gates, every task</div><div class="cardtxt">Spec compliance → code quality → pre-commit lint. Nothing is "too small to review."</div></div>
</div>

---

## Five thematic shifts

<div class="shiftlist">
<div class="shift"><span class="gnum">1</span><span><b>Lean artifacts</b> over exhaustive ones</span></div>
<div class="shift"><span class="gnum">2</span><span><b>A real agent layer</b>, dispatched by scope</span></div>
<div class="shift"><span class="gnum">3</span><span><b>Review</b> is a uniform, multi-stage gate</span></div>
<div class="shift"><span class="gnum">4</span><span><b>Parallelism</b> is a feature, not a footgun</span></div>
<div class="shift"><span class="gnum">5</span><span><b>Native tools</b> first, with a hard gate</span></div>
</div>

---

## 1 · Lean artifacts over exhaustive ones

<div class="cmp">
<div class="panel sp"><h3>superpowers</h3><div class="r">Spec written "as if zero context"</div><div class="r">Plan: complete code in every step</div><div class="r">specs grew past 2,500 w · plans 5,000–10,000 w</div><div class="note">agents discarded the pasted code and rewrote it</div></div>
<div class="vsbadge">→</div>
<div class="panel cc"><h3>chris-code</h3><div class="r">Spec = invariants only</div><div class="r">Plan = what &amp; where, no code</div><div class="r">code written against the real repo</div><div class="note">"contracts stay, choreography goes"</div></div>
</div>

---

## 2 · A real agent layer, dispatched by scope

<p class="cap" style="margin-top:6px">superpowers dispatches a generic <code>Task (general-purpose)</code> subagent steered by a prompt template. chris-code routes to dedicated agents:</p>

<div class="dispatch">
<div class="filechip">a .py file in a torch project</div>
<div class="router">↓ &nbsp; dispatched by scope (extension + deps) &nbsp; ↓</div>
<div class="lanes">
<div class="lane"><div class="lanehdr green">coder — exclusive</div><div class="node green">pytorch-coder ✓</div><div class="node muted">python-coder</div><div class="lanenote">most-specific wins</div></div>
<div class="lane"><div class="lanehdr yellow">quality-reviewer — additive</div><div class="node yellow">python-quality-reviewer</div><div class="node yellow">pytorch-quality-reviewer</div><div class="lanenote">all matching fire</div></div>
<div class="lane"><div class="lanehdr red">review-lite — commit gate</div><div class="node red">python-review-lite</div><div class="lanenote">idiom + lint, per commit</div></div>
<div class="lane"><div class="lanehdr indigo">design-reviewer — verification gate</div><div class="node design">python-design-reviewer</div><div class="lanenote">senior cohesion, read-only</div></div>
</div>
</div>

---

## 3 · Review: kept the spine, hardened it

<div class="gatecompare">
<div class="gaterow"><span class="glbl">superpowers</span><span class="gmini base">self-review</span><span class="gsep">→</span><span class="gmini base">spec review</span><span class="gsep">→</span><span class="gmini base">quality review</span><span class="gsep">→</span><span class="gmini base">final review</span></div>
<div class="gaterow"><span class="glbl">chris-code</span><span class="gmini base">spec compliance</span><span class="gsep">→</span><span class="gmini base">code quality</span><span class="gsep">→</span><span class="gmini add">+ commit lint gate</span><span class="gsep">→</span><span class="gmini add">+ full-diff pass</span></div>
</div>

<p class="cap">Same two-stage spine. chris-code makes the reviewers <b>dedicated, scope-dispatched agents</b>, adds a <b>mandatory lint gate</b> and a <b>spec-blind intent re-check</b>, and re-reads the actual code at every gate. More gates raise <i>recall</i>, not proof — the decorrelated axes (deterministic lint, spec-blind intent) carry the weight, not repetition.</p>

---

## 4 · Parallelism is a feature, not a footgun

<div class="band bad"><div class="bandhdr"><span class="xmark">✗</span> superpowers — "dispatch parallel implementers" is a Red Flag</div><div class="par"><span class="pt">implementer A</span><span class="pt">implementer B</span><span class="pt">implementer C</span></div><div class="bandnote">unscheduled: they edit the same files and collide</div></div>

<div class="band good"><div class="bandhdr"><span class="check">✓</span> chris-code — map file footprints, then stage</div><div class="stagerow"><span class="stagelbl">Stage 1</span><span class="t">A · api/</span><span class="t">B · db/</span><span class="t">C · ui/</span></div><div class="stagerow"><span class="stagelbl">Stage 2</span><span class="t tw">D · api/ + db/ (waits — overlaps A &amp; B)</span></div></div>

---

## 5 · Native tools first, with a hard gate

<div class="tree">
<div class="node">Need an isolated workspace (with consent)</div>
<div class="chev">↓</div>
<div class="node design">Native worktree tool available? (e.g. EnterWorktree)</div>
<div class="branchrow">
<div class="branch"><div class="ylabel">YES</div><div class="node exec">use it — both agree</div></div>
<div class="branch"><div class="ylabel">NO native tool</div><div class="twobox"><div class="node done">superpowers: git worktree fallback (announced)</div><div class="node redn">chris-code: STOP &amp; warn — hard gate</div></div></div>
</div>
</div>

<p class="cap">The split is only at "no native tool": superpowers falls back; chris-code refuses, because a silent fallback once caused real damage.</p>

---

## What stayed the same

<div class="checklist">
<div class="ci"><span class="check">✓</span> <b>brainstorming</b> — intent → approaches → design</div>
<div class="ci"><span class="check">✓</span> <b>test-driven-development</b> — RED-GREEN-REFACTOR</div>
<div class="ci"><span class="check">✓</span> <b>systematic-debugging</b> — four phases, Iron Law</div>
<div class="ci"><span class="check">✓</span> <b>finishing-a-development-branch</b> — merge / PR / keep / discard</div>
<div class="ci"><span class="check">✓</span> <b>dispatching-parallel-agents</b>, <b>receiving-code-review</b>, <b>using-chris-code</b> (light edits)</div>
</div>

---

## Skills you know — what changed most

Where muscle memory will mislead you. Framed before → after:

| Skill | superpowers | chris-code |
|---|---|---|
| **writing-plans** | the plan skill: exhaustive, full code per step | slimmed to `lean-plan`; spec → `lean-spec` |
| **subagent-driven-development** | 2-stage review; parallel discouraged | 3 gates/task, scope dispatch, staged parallelism |
| **verification-before-completion** | "what command proves this? run it" | 5 steps: tests → lints → review → requirements → spec-blind intent re-check |
| **requesting-code-review** | primary, mandatory path | demoted to ad-hoc; base `HEAD~1` → `merge-base HEAD main` |

---

## What's new, and why

<div class="newhdr">New skills (11)</div>
<div class="chiprow"><span class="chip">lean-spec</span><span class="chip">coherent-change</span><span class="chip">remediating-issues</span><span class="chip">regression-test</span><span class="chip">python-review</span><span class="chip">rust-review</span><span class="chip">technical-review</span><span class="chip">bug-hunt</span><span class="chip">test-sweep</span><span class="chip">code-archaeology</span><span class="chip">release</span></div>

<div class="newhdr">New agents (13) — the layer superpowers doesn't have</div>
<div class="arow">3 coders (<code>python</code> / <code>pytorch</code> / <code>rust</code>) — exclusive, most-specific wins</div>
<div class="arow">3 quality-reviewers — additive post-spec review</div>
<div class="arow">2 review-lite gates — pre-commit idiom + lint</div>
<div class="arow">2 design-reviewers (<code>python</code> / <code>rust</code>) — senior cohesion at the verification gate</div>
<div class="arow">2 conformance reviewers — <code>spec-reviewer</code> (promoted from a prompt template) + <code>intent-reviewer</code> (spec-blind, new)</div>
<div class="arow"><code>bug-hunter</code> — adversarial edge-case test writer</div>

---

<!-- _class: lead -->

## The net

chris-code is a **true superset**: every superpowers skill is present (one renamed, one split), plus 11 new skills and a 13-agent layer.

**Same spine.** Leaner artifacts, mechanical dispatch, harder gates.

Full write-up: `superpowers-comparison.md`
