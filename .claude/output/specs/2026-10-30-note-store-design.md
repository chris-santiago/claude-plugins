# Orchestrator Note Store Design Spec

Intent ledger: `.claude/output/intent/2026-10-30-note-store-intent.md`.

## 1. Scope

SDD's orchestrator holds cross-task knowledge (notes owed to later tasks, standing rules, follow-ups, docs debts, questions for the user, its own judgment calls, resume state, the stage map, live agent ids) with no durable home, so a long run improvises a free-form notes file that grows without bound, is never consumed, and silently drops items. This feature makes that knowledge typed entries in the SDD store, written and read only through `ledger.py`, consumed by `task_brief.py`, enforced by the ledger's gates, and surfaced by two views: `run-state` for resuming and `report` for the completion report. The skills that drive or close an SDD run are updated so the store is the only path notes travel.

## 2. Goals

- Every note kind has a typed entry, a defined consumer and a defined end of life.
- A note owed to a task reaches that task's brief automatically; the task cannot complete with it undelivered unless a waiver is logged with a reason.
- Standing rules reach every later brief and every in-flight task.
- Disclosures and questions block their owner (a task or the close) until resolved.
- Resuming needs only `ledger.py run-state` plus the records and `git log`.
- The completion report is built from `ledger.py report`; nothing that must be reported can be deleted unreported.
- The stage map is recorded, and overlapping footprints within a stage are refused.
- Concurrent writers cannot interleave or race the store's read-check-append commands.

## 3. Non-goals

- Task runners (a later sub-project that builds on this).
- Tracking `/tmp` inventories, baseline directories, scratch files, reviewer-focus hints or telemetry. These stay in checkpoint narrative or the dispatch.
- Enforcing who writes a note. Authority is a prose rule, like `user ruling:` notes today.
- Migrating existing free-form notes files by script. A one-time import is a prompt rule (judgment).
- Windows file locking. The lock is POSIX `flock`.
- Changes to lean-plan's handoff, the plan format, or the record schemas agents write.

## 4. System behavior

### 4.1 Note kinds

| Kind | Target | Delivered by | Ends when | Blocks |
|---|---|---|---|---|
| `task-note` | `for`: a task | the target's brief (or session delivery) | its target completes, or it is resolved (superseded or withdrawn) | target's `complete` while undelivered; `close-round` while active |
| `run-note` | every task | every brief (or session delivery) | it is resolved (retired) | `complete` of any unfinished task it has not reached |
| `disclosure` | `owner`: a task or `close` | the owner task's brief | it is resolved with where it landed | owner's `complete`, or `close-round` (any open disclosure) |
| `question` | `owner`: a task or `close` | `run-state` and `open`; the orchestrator asks the user | it is resolved with a `user ruling:` note | owner's `complete`, or `close-round` (any open question) |
| `follow-up` | none | `report` | resolved (fixed in the run), or reported at completion | nothing |
| `disposition` | optional `from` task | `report` | never; it is an audit entry | nothing |
| `checkpoint` | the run | `run-state` (newest only) | superseded by the next checkpoint | nothing |

A note has exactly one kind; content that is two kinds is filed as two notes. Every note carries `from` (the task or scope it arose in, optional) and text. Only the orchestrator files notes (prose rule).

### 4.2 Delivery

A note is *required* for task T when T is unfinished (no `complete` entry) and the note is active and one of: a `task-note` for T, a `run-note`, or a `disclosure` owned by T. It is *delivered* to T when a `delivery` entry for T lists its id, or a `waiver` entry for (T, id) exists. *Undelivered* = required minus delivered.

- `task_brief.py` embeds every required note for its task (task-notes and run-notes under "Cross-task notes", owned disclosures under "Disclosures this task owes") and, after writing the brief, appends a `delivery` entry (`via: "brief"`) listing exactly the ids it embedded. A delivery append that fails after the brief is written leaves the notes undelivered, which the gate catches.
- A session that executes tasks itself (executing-plans) delivers with `ledger.py notes --task N --deliver` (`via: "session"`), which records every currently required id.
- A required note that does not apply to an in-flight task can be waived: `ledger.py notes --task N --waive <id> --reason TEXT`. A waiver is reported with the dispositions.
- Questions owned by a task are never embedded: they go to the user, not the coder.

### 4.3 Gates

- `append --type complete --task N` refuses, listing ids, while N has: an undelivered note; an open disclosure or question owned by N; an open escalation (existing).
- `close-round` refuses while any disclosure or question is open, or any task-note is active (unresolved with an unfinished target). Checked before the existing round checks' append, so a refusal appends nothing.
- `stage` refuses a footprint that shares a path with another unfinished task's latest footprint in the same stage, naming the task and paths.
- `clear` refuses while any follow-up, disclosure or question is open, listing them, unless `--discard-open` is passed (the user confirmed the loss).
- `append --type complete --task run` is refused; `run` is a scope for rulings only.

### 4.4 Rulings

Task-scoped rulings are unchanged (`append --type progress --task N --note "user ruling: ..."`, `resolve` of escalations). A run-level ruling is `append --type progress --task run --note "user ruling: ..."`. A ruling that sets a standing rule is also filed as a `run-note` quoting it. `report` lists every ruling: progress entries and resolutions whose note starts `user ruling:` (case-insensitive), including those resolving questions.

### 4.5 Views

`run-state` (markdown, read-only) shows, in order:
1. Stages: each stage with its tasks, each task's state (`complete`, `in flight`: any delivery, record or snapshot exists, else `not started`) and footprint; tasks that have state but no stage entry listed as unstaged.
2. In-flight tasks' non-trivial fix counts.
3. Notes owed: per unfinished task, its undelivered notes; then active task-notes whose target has not started.
4. Open disclosures and questions, with owners.
5. Count of open blocking items from `open`.
6. Handles: latest per (task, role) for unfinished tasks (and `final`), marked valid only in the session that created them.
7. The newest checkpoint, with its timestamp.

`report` (markdown, read-only) shows: user rulings; follow-ups (open filed ones, then `unlisted case:` concerns derived from coder records, then resolved ones with their resolution); dispositions and waivers; disclosures (resolved with where they landed, open ones flagged); questions (ruled, open ones flagged).

`notes --task N` prints the notes required for N with delivered or undelivered marks, plus questions owned by N.

`open` additionally lists, as blocking items: each undelivered note per unfinished task, each open disclosure and each open question. Follow-ups, dispositions and checkpoints are not listed.

`read` renders every new entry type in readable form, never as the raw "unknown entry" fallback.

### 4.6 Resolution

`resolve <note id> --note TEXT` closes an open `task-note`, `run-note`, `follow-up`, `disclosure` or `question`, using the existing resolution entry. Text is required for every note kind; a question's must start `user ruling:`. `checkpoint` and `disposition` ids are not resolvable. Record-derived resolvable items keep today's rules.

### 4.7 Task brief

`task_brief.py` drops `--note` (argparse rejects it). It reads the store's log during its read-only validation phase; a malformed log fails the brief loudly with nothing written. Superseded or retired notes are never embedded. With no required notes, "Cross-task notes" renders `(none)` and the disclosures section is omitted.

## 5. Architecture

- `ledger.py` remains the single authority for the store: it owns every new entry type, the derivations (required, delivered, active, open), the gates, the lock and both views. Derivations are pure functions over the log and records, exported for `task_brief.py`.
- `task_brief.py` stays a pure assembler plus one delivery append through an exported ledger function; it never writes `progress.jsonl` directly.
- Prompts own judgment: what to file, which kind, when to waive, when to checkpoint, what to ask the user. Scripts own storage, derivation and refusal.

## 6. Canonical interfaces / data contracts

### 6.1 Entries (appended to `progress.jsonl`)

All new entries carry `"at"`: UTC ISO-8601 to the second. Existing entry types are unchanged.

```json
{"type": "note", "id": "note#<kind>[<8 hex>]", "kind": "task-note|run-note|disclosure|question|follow-up|disposition|checkpoint",
 "text": "...", "from": 4, "for": 14, "owner": 14, "at": "..."}
{"type": "delivery", "task": 14, "notes": ["note#task-note[...]"], "via": "brief|session", "at": "..."}
{"type": "waiver", "task": 14, "note": "note#run-note[...]", "reason": "...", "at": "..."}
{"type": "stage", "task": 14, "stage": 3, "files": ["src/a.py", "tests/test_a.py"], "at": "..."}
{"type": "handle", "task": 14, "role": "python-coder", "agent": "<agent id>", "at": "..."}
```

- `for` only on `task-note` (positive int). `owner` only on `disclosure` and `question` (positive int or `"close"`). `from` optional on every kind (positive int, `"final"` or `"run"`).
- Note id: `note#<kind>[` + first 8 hex of sha1 over the canonical JSON of `{kind, text, for, owner, from}` (absent keys omitted) + `]`. Filing a note whose id already exists is refused, naming the existing id and its state.
- `stage`: positive int stage; non-empty file list; paths normalized (posix normpath, no leading `./`). The latest `stage` entry per task wins.
- `handle`: task is a positive int or `"final"`; the latest per (task, role) wins.
- `progress` and `resolution` keep their shapes; `progress.task` additionally accepts `"run"`.

### 6.2 Commands

```
ledger.py note --kind KIND --text TEXT [--for N] [--owner N|close] [--from N|final|run]   # prints the id
ledger.py notes --task N [--deliver | --waive ID --reason TEXT]
ledger.py stage --task N --stage K --files PATH...
ledger.py handle --task N|final --role NAME --agent ID
ledger.py run-state
ledger.py report
ledger.py append --type progress|complete --task N|final|run --note TEXT
ledger.py resolve ID --note TEXT
ledger.py clear [--discard-open]
```

All take `--store DIR`. Argument errors exit 2 (argparse); refusals raise `RecordError` and exit 1 with a message naming the offending ids and the remedy. Kind/flag mismatches (`task-note` without `--for`, `--owner` on a follow-up, `--for` on anything but a task-note) are refusals. So is a target that can never consume the note: a task-note `--for`, or a disclosure or question `--owner`, naming a completed task (the remedy names `--owner close`).

### 6.3 Exported functions (for `task_brief.py` and tests)

Pure derivations over a loaded log (and records where named): required, delivered and undelivered notes for a task; active notes by kind; open note items; and one append function for a delivery entry that takes the store lock. Names are an implementation choice; the set of behaviors is the contract.

### 6.4 Lock

Every command that appends to or deletes from the store (`append`, `note`, `notes --deliver/--waive`, `stage`, `handle`, `resolve`, `snapshot`, `close-round`, `clear`, `check`'s history append, and `task_brief.py`'s delivery append) holds an exclusive `flock` on `<store>/.lock` across its read, its checks and its write. Read-only commands take no lock. `clear` never deletes `.lock`.

## 7. Invariants and constraints

- `progress.jsonl` stays append-only; no command rewrites or truncates it except `clear`.
- Every refusal appends nothing and writes nothing.
- A failed brief writes neither a brief file nor a delivery entry.
- Existing entry types, record schemas, ids, and every existing command's behavior on stores without new entries are unchanged; existing tests keep passing.
- The stale-store and close-gate-remediation recognition in SDD's Durable Progress (close rounds and the `close-gate remediation r1:` note) is unaffected by new entry types.
- `load_progress_log` still fails loudly on the first malformed line; new readers inherit that.
- No skill or script prose calls ledger scripts by a relative `scripts/` path (`tests/test_scripts_path.py`).

## 8. Key decisions and tradeoffs

- **One store, every kind.** Follow-ups and disclosures live with task notes, not in verification's artifacts: one authority, and verification and executing-plans already use this store. Rejected: split by consumer (two registers drift).
- **Delivery is recorded, not inferred.** The gate compares required notes to logged deliveries, so a note filed after a brief is caught. Rejected: per-note resolve (bookkeeping without a check) and embed-only (keeps the silent miss).
- **Run-notes gate in-flight tasks, with logged waivers.** Evidence: a standing rule dropped out of briefs twice in the motivating run. Waivers keep the gate absolute while making exceptions reviewable.
- **Disclosures and questions have owners.** Owners are usually known when the debt arises; gating the owner keeps the debt from piling onto one late task. `close` is the owner of last resort.
- **`question` and `disposition` are kinds.** A question blocks until the user rules (the escalation contract without a decision doc); a disposition never blocks and makes the orchestrator's solo judgment calls auditable.
- **Rulings stay rulings.** Run-level rulings use the existing ruling log with a `run` scope; run-notes are only delivery vehicles that may quote a ruling.
- **Handles are recorded.** Without them, continuing the original agent after compaction silently degrades to a cold dispatch. They are session-scoped; the existing fresh-dispatch fallback stays.
- **Stage map in the store, refusing overlap.** Turns the parallelism rule into a check and survives compaction. Rejected: plan-declared footprints (changes the plan format; footprints grow mid-run).
- **`--note` removed from `task_brief.py`.** An ad-hoc note path would reopen the silent miss and compete with the store.
- **Checkpoints are narrative, newest wins.** They hold only what the store cannot derive; history stays in the log.
- **Guarded `clear`.** Today it silently deletes everything; the guard turns loss into a user confirmation.

## 9. Acceptance criteria

- Filing each kind validates its flags, prints its id, and refuses a duplicate; resolving checkpoint or disposition ids is refused; resolving a question without `user ruling:` is refused.
- A task-note for task 5 filed before task 5's brief is embedded in it, and task 5 can complete; one filed after the brief blocks `complete` until the brief is rebuilt (new delivery) or a waiver is logged; a superseded task-note is never embedded and never blocks.
- A run-note filed while tasks 5 and 6 are in flight blocks both until each is re-briefed, session-delivered or waived; it does not affect completed tasks; it appears in every later brief; a retired run-note appears in none.
- A disclosure owned by task 7 is embedded in 7's brief and blocks 7's `complete` until resolved; one owned by `close` blocks `close-round`; a question blocks the same way and resolves only with `user ruling:`.
- `close-round` refuses while a task-note targets a task that never completed; a refusal appends nothing.
- `stage` refuses an overlapping path in the same stage between unfinished tasks; allows it across stages, after the other task completes, and when re-staging the same task.
- `clear` refuses with open follow-ups, disclosures or questions and lists them; `--discard-open` clears; `.lock` survives.
- `append --type progress --task run` logs a run-level ruling that `report` lists; `append --type complete --task run` is refused.
- `run-state` on an empty store, a mid-run store and a finished store shows the sections of 4.5 correctly, including unstaged tasks, the newest checkpoint only, and handles for unfinished tasks only.
- `report` lists filed and derived (`unlisted case:`) follow-ups, dispositions, waivers, disclosures with landing notes, questions and rulings.
- `notes --task N --deliver` records exactly the currently required ids; afterwards N has nothing undelivered.
- `task_brief.py` rejects `--note`; a failing brief (any validation error, malformed log) writes no file and no delivery; a successful one logs a delivery listing exactly the embedded ids.
- `read` renders every new entry type; `open` lists undelivered notes, open disclosures and open questions and nothing else new.
- Two processes appending concurrently to one store produce only whole, valid lines, and two concurrent gated commands cannot both pass a check that only one should.
- Every existing test passes unchanged.

## 10. Validation strategy

Behavioral unit tests per entry type, gate, view and refusal, driven through the ledger's command functions and a CLI subprocess per new subcommand; end-to-end tests of `task_brief.py` against a store holding each note kind; a multi-process test for the lock. Skill-level behavior is validated by the intent re-check against the frozen ledger.

## Appendix: prose changes (no design content)

- SDD `SKILL.md`: a "Run Notes" section (kinds and when to file each; only the orchestrator files; never keep cross-task state in a file of your own; one-time import of an existing free-form notes file); pre-flight records the stage map; File Handoffs routes cross-task notes through the store and drops `--note`; unlisted cases are derived; Durable Progress adds `run-state` at start and after compaction, a checkpoint before any pause or `/compact`, handles recorded at dispatch, and the corrected list of commands that read the log; root cause deferred becomes a follow-up note; judgment calls become dispositions; whole-change gate and Red Flags updated; example workflow updated.
- verification-before-completion: completion report from `ledger.py report`; "log as a follow-up" names the note; close-owned questions asked and disclosures landed before `close-round`.
- executing-plans: `notes --task N --deliver` at task start; files notes the same way.
- finishing-a-development-branch: `ledger.py report` before store cleanup, carrying follow-ups and disclosures into the PR body or summary.
- remediating-issues and coherent-change: "log the north-star as a follow-up" means a `follow-up` note inside an SDD run.
- Docs: `execution-mechanics.md`, README's ledger bullets, a ledger command reference page, the skills reference; CHANGELOG 0.10.0.
