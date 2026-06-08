---
name: pipeline-init
description: Use when an ml-lab investigation outgrows a single-cell PoC and must be promoted to a config-driven Metaflow flow. Scaffolds the Metaflow + Hydra bundle into the investigation's flow directory, migrates PoC logic into the component seams, and runs the lint → reviewer → determinism gate sequence before declaring the promotion complete.
---

This skill is the promotion layer of the pipeline enforcement model: **prevent → lint → review → prove**. It runs when an ad-hoc PoC has accumulated enough structure to warrant a config-driven, reproducible pipeline. It is never a mechanical step — promotion is a judgment call made by the orchestrator.

---

## 1. When to promote

The default signal is: **more than one analysis cell, or more than one distinct analysis or diagnostic.** A PoC that computes a single number under a single condition is not a promotion candidate. A PoC that iterates over multiple data conditions, trains multiple methods, or branches into two or more diagnostics is.

This threshold is a recommendation, not a gate. The orchestrator may promote earlier when tracking reproducibility matters from the start, or may stay ad-hoc longer when the hypothesis is still unstable. Quick one-number PoCs are explicitly excluded: the overhead of a pipeline serves no purpose when there is nothing yet to orchestrate.

---

## 2. Scaffolding procedure

**Resolve the plugin path first.** The bundle and scripts ship inside this plugin, so locate it portably (works from any working directory): read `installPath` for the `ml-lab` entry in `<claude-config>/installed_plugins.json` — the same resolution the ml-lab skill uses for `derive_verdict.py`. Call it `$PLUGIN_DIR`; the bundle lives at `$PLUGIN_DIR/skills/pipeline-init/assets/` and the gate scripts at `$PLUGIN_DIR/skills/pipeline-init/scripts/` (used in §6).

Create the flow directory (conventionally `flow/`) under the investigation root if it does not exist. Stamp the bundle from `$PLUGIN_DIR/skills/pipeline-init/assets/` into place:

1. Copy `assets/shell_snippet.py` wiring into the top of your new flow module verbatim (see §7 — the shell is the one seam that is copied unchanged).
2. Copy `assets/reference_flow.py` alongside the flow source as the annotated starting point. Read it carefully; adapt its DAG and component bodies to the investigation's domain. It is a model to follow, not a template to fill in.
3. Copy the `assets/conf/` scaffold into `flow/conf/`: this means `config.yaml`, the `data/`, `method/`, `experiment/`, and `training/` group directories, and `SCHEMA.md`. Rename the exemplar YAML files to match the investigation's actual data variant, methods, and experiment name. The group names `data/` and `method/` are the standard names; do not rename them.
4. Keep `assets/COMPONENT_CONTRACT.md` as a reference; it documents the four seam signatures you must implement.

The promoted flow is a **single source of truth**: it embodies only the final, debated methodology. It does not carry forward the throwaway PoC's artifacts, numbers, or assumptions — the critic/defender debate exists precisely to redirect those, and the investigation journal (not the pipeline) is where superseded assumptions are recorded.

---

## 3. Migrate the PoC into the seams

The PoC's logic maps to four component functions. Implement each as a plain module-level function in the flow module (unit-testable via bare import, with no Metaflow dependency):

**`make_data(data_spec, data_axes, seed) -> Dataset`**
The PoC's data-generation logic becomes this function. `data_axes` is the data-affecting subset of the current cell and overrides `data_spec` values — this is what makes the dataset-keyed `foreach` correct (the dataset is generated once per `(data_axes + seed)` combination, not once per full configuration cell). Declare which axes are data-affecting in the experiment YAML's `data_axes` list.

**`build_model(model_spec) -> nn.Module`**
The PoC's model construction becomes this function. Keep it standalone: `train_arm` composes it.

**`train_arm(method_spec, data, seed, train_cfg) -> TrainResult`**
Dispatched on `method_spec["kind"]` via `TRAIN_REGISTRY`. Every method kind the investigation uses must appear in the registry. An unknown kind must RAISE — never silently default a new method to agnostic or axis-dependent.

Classify each method kind as either:
- **Axis-agnostic:** the trained model does not depend on the training-axis value; the method trains once and is evaluated at every training-axis value.
- **Axis-dependent:** the loss bakes in the training-axis value; the method retrains per value.

Register both classifications in `is_axis_agnostic_method(kind)`. This function must also raise on unknown kind — silently treating an axis-dependent method as agnostic trains it only once across all axis values, a silent correctness error.

**`metric(scores, labels, **cfg) -> float`**
Binds to the investigation's existing primary evaluation metric — the one already established in `HYPOTHESIS.md` and computed in the PoC. Do not introduce a new metric here. The `cfg` kwargs carry training-axis values when the metric is parameterized by them (e.g., `k` from `eval_k`).

**Axis split:** Identify which PoC axes affect the generated data (data-axes) and which affect only training or evaluation (training-axes). Declare the data-axes in the experiment YAML. The `foreach` grain is `(data_axes + seed)` — each dataset is generated once and all methods that share that data train in-process on the shared tensors.

---

## 4. Declare the determinism contract

There is **no** reproduce-the-PoC gate. The PoC is a throwaway debate seed; validating against it would enshrine exactly the pre-debate assumptions the investigation is meant to challenge, and carry potentially-wrong work into the source-of-truth pipeline. The experiment's *findings* are certified by the existing ml-lab machinery (pre-specified verdicts, trivial-baseline comparison, bootstrap CIs, the debate, peer review) — not by reproduction.

What the flow *does* declare is its **determinism contract** in the experiment YAML — how reproducible its own aggregated outputs are:

```yaml
determinism: order_independent   # default | single_worker | nondeterministic
```

- **`order_independent`** — outputs identical across worker counts (the strong claim).
- **`single_worker`** — pinned to `--max-workers 1` because a dependency is nondeterministic under parallelism (e.g. gensim in the ATO investigation); determinism claimed only at one worker.
- **`nondeterministic`** — the explicit escape hatch: no reproducibility claim; the determinism gate is skipped. Use this rather than silently shipping a flow whose numbers move between runs.

The flow echoes the declared value as a run artifact so any reader of a finished run knows the claim. See `conf/SCHEMA.md`. Add per-analysis `check_<analysis>(run)` helpers as needed for your own inspection, but they are not a promotion gate.

---

## 5. Preserve canonical artifacts

Promotion does not replace the investigation's source-of-truth artifacts:

- **`HYPOTHESIS.md`** stays unchanged. It is the canonical claim the investigation is testing, and the promoted flow must reproduce the evidence for that claim.
- **`INVESTIGATION_LOG.jsonl`** stays append-only. Log each scaffolding action, component migration decision, and gate result via `uv run log_entry.py` as usual.

The Metaflow datastore supersedes the loose result files the PoC may have written (`stats_*.json`, `results_*.jsonl`, etc.). Those files can be archived but should not be the source of truth once the flow is running. Bad assumptions and abandoned PoC directions belong in `INVESTIGATION_LOG.jsonl` (the audit trail), never carried forward into the flow.

---

## 6. The gate — blocking

Run these three steps in order. Each must pass before the promotion is complete.

**Step 1 — Deterministic lint (blocking)**

Using `$PLUGIN_DIR` resolved in §2:

```bash
uv run "$PLUGIN_DIR/skills/pipeline-init/scripts/flow-lint.py" <flow.py>
```

The linter checks five mechanical anti-patterns via stdlib `ast` only (no project deps, no flow import):
- `merge-artifacts-module`: `merge_artifacts()` missing `include=`/`exclude=` (raises on `nn.Module` artifacts)
- `cwd-relative-config`: `Config(default=...)` not anchored to `__file__` (breaks under `uv run` script mode)
- `per-config-foreach`: `foreach` grain is per-method/config rather than per-dataset/data-cell
- `bare-project-import`: first-party import with no preceding `sys.path.insert` shim
- `module-global-experiment-const`: module-level numeric constant read inside a `@step`/`@card` body

Must exit 0. Fix every finding before proceeding. Do not override or bypass the linter.

**Step 2 — Fidelity review (blocking)**

Dispatch the `pipeline-reviewer` agent. Provide the promoted flow source and the investigation's source-of-truth documents (`HYPOTHESIS.md`, the original PoC script, `CONCLUSIONS.md` if it exists). The reviewer checks five intent-fidelity invariants: split convention, per-epoch reshuffle symmetry, axes-match-source, same-name/different-quantity metrics, and sweep-override inflation.

The reviewer emits structured JSON with `PASS`/`CONCERN`/`FAIL` verdicts. A `FAIL` on any check is blocking. A `CONCERN` is not blocking but must be resolved before the flow is considered production-ready. Address all `FAIL` findings, then re-dispatch the reviewer. The loop continues until no `FAIL` findings remain (or the user explicitly overrides — document any override in the investigation log).

**Step 3 — Determinism gate (verify the declared contract)**

This is the **prove** layer: confirm the flow holds the determinism contract it declared in `experiment.determinism`. It validates the flow against *itself*, not against the PoC.

- **`order_independent`:** run the flow at two different worker counts and diff the run output contract:
  ```bash
  # run twice, e.g. with --max-workers 1 and --max-workers 8, then:
  uv run "$PLUGIN_DIR/skills/pipeline-init/scripts/determinism-check.py" <run_a> <run_b>
  ```
  Exit 0 (identical aggregates) is required.
- **`single_worker`:** run twice at `--max-workers 1` and diff; cross-worker is not asserted.
- **`nondeterministic`:** the check is N/A and self-skips (it reads the contract from the run). This escape hatch is for experiments that genuinely cannot be deterministic under parallelism (e.g. gensim in the ATO investigation) — it must be a deliberate declaration, not a silent gap.

The experiment's *findings* are not gated here — verdicts, baselines, bootstrap CIs, the debate, and peer review own that. This gate only proves the pipeline's numbers are execution-invariant as declared.

Only after all three steps pass is the promotion complete.

---

## 7. Seam-treatment table

| Seam | Asset | Treatment |
|------|-------|-----------|
| Seam 1 — shell | `assets/shell_snippet.py` | Verbatim copy into the flow module top. The PEP 723 header, `sys.path` shim, Hydra parser, and lazy-metaflow guard are the invariant core. Do not modify. |
| Seam 2 — DAG | `assets/reference_flow.py` | Default shape only, not a mandate. The enforced invariants are: `foreach` grain is `(data_axes + seed)`, analysis branches are pure readers of train artifacts (train→analyze separation), `merge_artifacts` is scoped. A legitimately different-shaped flow that honors these invariants passes. |
| Seam 3 — component contract | `assets/COMPONENT_CONTRACT.md` | The four signatures you fill: `make_data`, `build_model`, `train_arm` (registry-dispatched, raises on unknown kind), `metric` (binds to the investigation's existing primary metric). |
| Seam 4 — conf schema | `assets/conf/SCHEMA.md` + exemplars | The durable config contract. `data/` and `method/` are the standard group names. Training knobs (`epochs`, `lr`, `batch`, `hidden`) live in the `training/` group and are fallbacks; method YAMLs must not hard-set them. The run output contract (`lift_results`, `aggregate_results`, `an_result`) is pinned as the SSOT read-surface. |
| Seam 5 — fidelity | `scripts/flow-lint.py` + `agents/pipeline-reviewer.md` | Lint checks mechanical invariants deterministically. The reviewer checks intent-fidelity invariants by judgment (five checks: split, reshuffle, axes, metric quantity, sweep inflation). Both must pass. |
| Determinism gate (prove) | `scripts/determinism-check.py` | Verifies the flow holds its declared `experiment.determinism` contract by diffing two runs' aggregates. Validates the flow against itself, not the PoC. `nondeterministic` is the explicit escape hatch. |

---

## Constraints

- **uv-native throughout.** All scripts run via `uv run`. Never invoke `python3` directly.
- **Enforcement guards invariants, not shape.** The lint and reviewer guard the five seam invariants. A legitimately different DAG that honors them passes. Policing step granularity or topology is out of scope.
- **The reference flow is a starting point to adapt.** Only the shell (`shell_snippet.py`) is verbatim. Everything else in `reference_flow.py` — the DAG, the component bodies, the analysis branches — is annotated domain code that you replace with the investigation's actual logic.
- **Raise on unknown method kinds.** Both `train_arm` and `is_axis_agnostic_method` must raise on unknown `kind`. Silently defaulting a new method misclassifies it and produces wrong training behavior without any error.
