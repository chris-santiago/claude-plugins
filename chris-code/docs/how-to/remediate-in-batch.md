# Remediate findings in batch

Use this when a sweep has surfaced many changes at once — an **audit** (`code-archaeology`, `bug-hunt`) or a senior **review** (`python-review`, `rust-review`, `technical-review`). Rather than fixing one at a time, the whole set runs as one coordinated change.

## Steps

1. **Run the discovery skill** (audit or review). It terminates at an artifact — a report, or a set of proposed end-states — and **offers**: remediate now in batch, or keep for later.
2. **Accept, and triage routes by finding type:**
    - **Bug-type** findings → `remediating-issues` (batch).
    - **Structural / design / algorithmic** changes → `coherent-change` (batch mode).
3. **The engine runs batch mode:** one **consolidated research pass** over the subsystem, a defended choice per change (reconciled against the shared map, so conflicts between findings surface), then the whole set routed into **one `lean-spec` → one `lean-plan` → `subagent-driven-development`**.
4. **Execution** runs staged by file footprint; the close (regression coverage for bugs, `verification-before-completion`, `finishing-a-development-branch`) runs once over the coordinated change.

## You have now

Turned a list of findings into one coordinated, defended, staged change — not a scatter of independent patches. Or, if you deferred: the artifact waits, and you hand it to the same route whenever you're ready.

!!! note "Findings are end-states, not fixes"
    Each finding only needs to say *what should be true*; `coherent-change` finds the method. A finding that suggests a fix is just candidate A — the engine still defends the most coherent method against the alternatives.
