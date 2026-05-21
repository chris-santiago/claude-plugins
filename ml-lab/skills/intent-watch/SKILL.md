---
name: intent-watch
description: Monitor a working directory for file changes that conflict with a source-of-truth document. One monitoring pass per invocation — use with /loop for continuous monitoring (e.g. /loop 2m /intent-watch <dir> <source-of-truth>). Reports clean or flags drift.
---

## Usage

```
/intent-watch <working_dir> <source_of_truth_path>
```

For continuous monitoring every 2 minutes:
```
/loop 2m /intent-watch experiments/self_debate_experiment_vN/ experiments/self_debate_experiment_vN/HYPOTHESIS.md
```

## Arguments

Parse `$ARGUMENTS` as two space-separated tokens:
- First token: `WORKING_DIR` — the directory to monitor
- Second token: `SOURCE_OF_TRUTH` — the binding reference document

If fewer than two arguments are provided, stop and tell the user:
```
Usage: /intent-watch <working_dir> <source_of_truth_path>
Example: /intent-watch experiments/self_debate_experiment_v6/ experiments/self_debate_experiment_v6/HYPOTHESIS.md
```

## Step 1 — Parse Arguments

Extract WORKING_DIR and SOURCE_OF_TRUTH from the arguments. Confirm both paths are accessible before dispatching the agent — if either path does not exist, report the error and stop.

## Step 2 — Dispatch the Monitoring Agent

Dispatch the `intent-monitor` agent with this prompt:

```
Monitor for intent drift.

WORKING_DIR: <WORKING_DIR>
SOURCE_OF_TRUTH: <SOURCE_OF_TRUTH>

Follow your full protocol: read and index the source of truth, detect recent changes via git, evaluate each change against binding constraints, and emit your report.
```

## Step 3 — Surface the Report

Output the agent's report verbatim. Do not summarize, filter, or add commentary. The clean-pass line or conflict report is the complete output of this skill.
