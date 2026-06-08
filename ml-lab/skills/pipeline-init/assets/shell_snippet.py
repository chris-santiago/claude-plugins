# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "torch>=2.8",
#   "numpy",
#   "scikit-learn",
#   "metaflow>=2.19",
#   "hydra-core",
#   "omegaconf",
#   "pyyaml",
# ]
# ///
"""Verbatim-copyable toolchain shell for a Metaflow + Hydra flow run with `uv`.

Copy this block UNCHANGED into the top of your flow module. It is the invariant
core of the pipeline standard: the PEP 723 header, the repo-src `sys.path`
insert, the Hydra->Metaflow `Config` wiring, and the lazy-metaflow import guard.
Everything below the marked region is your domain code (components + DAG).
"""

from __future__ import annotations

import pathlib
import sys

# --- repo-package import shim ------------------------------------------------
# `uv run flow.py run` is PEP 723 *script* mode: it does NOT install the local
# repo package. A bare `from <project> import ...` then raises ModuleNotFoundError
# at RUN time even though unit tests pass (tests run in *project* mode, where the
# editable install is already on sys.path). Anchor the insert to __file__ (NOT
# CWD) so it resolves no matter which directory `uv run` is launched from.
# Adjust parents[N] so the joined path points at the dir containing your package.
_SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# --- Hydra -> Metaflow Config wiring -----------------------------------------
# __file__-anchored absolute conf dir. A CWD-relative default="conf/config.yaml"
# breaks when the flow is launched from the repo root.
_CONF_DIR = pathlib.Path(__file__).parent.parent / "conf"


def hydra_parser(text: str) -> dict:
    """Metaflow Config parser: Hydra-compose the conf tree into a plain dict.

    Caller selects config groups via a `hydra_overrides` list embedded in the
    Config value, stripped before compose so it never lands in the resolved cfg.
    CLI override form (two positional args, BEFORE `run`):
        uv run flow.py --config-value cfg "hydra_overrides: [experiment=X]" run
    """
    import yaml
    from hydra import compose, initialize_config_dir
    from hydra.core.global_hydra import GlobalHydra
    from omegaconf import OmegaConf

    raw = yaml.safe_load(text) or {}
    overrides = raw.pop("hydra_overrides", [])
    GlobalHydra.instance().clear()  # singleton; must clear before re-init
    with initialize_config_dir(config_dir=str(_CONF_DIR.resolve()), version_base="1.3"):
        cfg = compose(config_name="config", overrides=overrides)
    return OmegaConf.to_container(cfg, resolve=True)


# --- lazy-metaflow import guard ----------------------------------------------
# Keep FlowSpec + every metaflow / @card import inside this guard so the module
# imports without metaflow installed (needed for `import flow` in unit tests).
# Define `Config` (and the FlowSpec subclass) only when metaflow is available.
try:
    from metaflow import Config, FlowSpec, card, step  # noqa: F401
    from metaflow.cards import Image, Markdown  # noqa: F401

    _METAFLOW_AVAILABLE = True
except ImportError:
    _METAFLOW_AVAILABLE = False

# verified against metaflow 2.19.x
