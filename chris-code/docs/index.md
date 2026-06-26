# chris-code

chris-code turns Claude Code into an **opinionated software-engineering workflow** rather than a free-form chat assistant. It routes any non-trivial change through a fixed pipeline — brainstorm intent, write a lean spec, hand off a thin plan, dispatch a coder subagent per task, run staged review, and gate drift before it reaches `main`. It ships 25 skills, 13 dedicated agents, and review gates that re-read the actual code instead of trusting an agent's summary.

## When to use it

- You want Claude to **design before it codes** — settle *what* and *why* before *how*.
- You want the main context window kept clean by **offloading focused work to subagents**.
- You want **agent-generated drift caught** by review gates before it lands.
- You work primarily in **Python or Rust** (the coder and review agents are language-scoped), though the workflow skills are language-agnostic.

If you just want a quick one-off answer, you don't need chris-code. It earns its keep on changes substantial enough to deserve a design and a review.

## Install

chris-code is distributed through a personal Claude Code marketplace. Add it to `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "chris-code": {
      "source": { "source": "github", "repo": "chris-santiago/claude-plugins" }
    }
  },
  "enabledPlugins": {
    "chris-code@chris-code": true
  }
}
```

Claude Code fetches and caches the plugin automatically. (The repo also ships `ml-lab` and `ml-journal`; enable those separately if you want them.) Full install options — local directory, manual cache — are in the [repository README](https://github.com/chris-santiago/claude-plugins#installation).

## Where to go next

- **[Start with the tutorial →](tutorials/getting-started.md)** — take one change from idea to merged, end to end.
- **[Browse the how-to guides →](how-to/index.md)** — task recipes: fix a bug, run a determined change, review a branch, run a quality campaign.
- **[Read the reference →](reference/index.md)** — the full catalog of skills and agents, and how dispatch works.
- **[Understand the design →](explanation/index.md)** — why a fixed pipeline, what the gates actually prove, and when to dispatch vs. stay in-session.
