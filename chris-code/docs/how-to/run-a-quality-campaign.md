# Run a quality campaign

Use these when you want to go hunting rather than ship a specific change — proactively finding bugs, gaps, and unfinished work across a codebase.

## Find edge-case bugs

```
/bug-hunt
```

Dispatches one `bug-hunter` agent per subsystem in parallel. Each writes edge-case tests against its subsystem and reports failures as bugs. Pass a subsystem name to scope it to one. The agents *find* bugs; they don't fix them — feed confirmed failures to [`remediating-issues`](remediate-a-bug.md).

## Sweep the API surface

```
/test-sweep
```

An iterative, combinatorial test-and-fix campaign: it writes systematic test modules targeting cross-cutting dimensions of the API, runs them, fixes failures via TDD, then uses the failure patterns to derive the next suite. Runs for N rounds or until convergence, pausing only for genuine design decisions.

## Surface unfinished work

```
/code-archaeology
```

Finds unimplemented features, silently dropped parameters, dead code paths, skipped tests, and spec-vs-implementation gaps. Run it before marking a milestone done or before a major refactor.

## Check ML/numerical correctness

```
/technical-review
```

For Python ML code: reviews mathematical correctness, algorithmic logic, numerical stability, and research alignment — the things a general review misses (loss functions, estimators, optimization steps, anything implementing a published algorithm).

## You have now

Surfaced a concrete list of defects, coverage gaps, or unfinished work. Each campaign *produces findings*; route the real ones into [`remediating-issues`](remediate-a-bug.md) to fix them coherently.
