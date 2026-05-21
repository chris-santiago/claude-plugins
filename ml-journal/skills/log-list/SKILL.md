---
name: log-list
description: List recent journal entries of a specific type. Use when the user says "show recent issues", "list decisions", "show my hypotheses", "what experiments have we logged", "list post mortems", or any phrasing asking to see entries of a particular type. Optionally filtered by time window.
---

## Step 1: Check journal exists

Run `git rev-parse --show-toplevel` to find repo root.

If `.project-log/journal.jsonl` does not exist, say: "No journal found in this repo. Run `/journal-init` to set one up." Stop.

## Step 2: Determine type and time window

From the user's request, identify:

**Type** — one of: `issue`, `resolution`, `decision`, `discovery`, `hypothesis`, `experiment`, `post_mortem`, `lesson`, `memo`, `summary`, `checkpoint`, `git`

If the type is ambiguous or not specified, ask: "Which entry type? (issue / resolution / decision / discovery / hypothesis / experiment / post_mortem / lesson / memo / summary / checkpoint / git)"

**Since** (optional) — if the user says "recent", "this week", "last 24 hours", "today", etc., convert to the appropriate `--since` value:
- "today" → `1d`
- "this week" / "recent" → `7d`
- "last 24 hours" → `24h`
- Specific number: use as stated, e.g. "last 3 days" → `3d`
- No time qualifier → omit `--since` (show all)

## Step 3: Run query

**Special case — issues:** When type is `issue` and no time qualifier is given, use `--unresolved-issues` to show only open (unresolved) issues:

```bash
python3 <repo-root>/.project-log/journal_query.py --unresolved-issues
```

For all other types, or when a time qualifier is given with `issue`:

```bash
python3 <repo-root>/.project-log/journal_query.py --list <type> [--since <Nd|Nh>]
```

## Step 4: Surface output

Display formatted output as-is.

If the list is long (>10 entries), offer: "Want me to summarize these? Use `/journal-summarize` for a prose synthesis."
