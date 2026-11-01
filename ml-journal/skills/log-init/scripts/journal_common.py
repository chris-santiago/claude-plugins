"""journal_common.py — Repo and journal path resolution shared by the ml-journal scripts.

The repo is untrusted: the scripts run from the plugin, never from the repo,
and refuse a symlinked .project-log/ or journal.jsonl, which a hostile repo
could commit to redirect reads and writes to a file outside it.

Checkpoint text comes from the repo, so it is shown automatically only for
repos this machine has trusted. The trust list is a JSON file in the plugin
data dir, never in the repo.
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

LOG_DIR_NAME = ".project-log"
JOURNAL_NAME = "journal.jsonl"
# Script copies an older /log-init put in .project-log/. Never run; only detected.
LEGACY_SCRIPTS = ("journal_log.py", "journal_query.py")
LEGACY_NOTICE = (
    "NOTE: this repo uses the legacy ml-journal layout (journal scripts copied into "
    ".project-log/). Those copies are no longer used; run /log-init to upgrade."
)
TRUST_STORE_NAME = "trusted-repos.json"
TRUST_SCHEMA = 1
UNTRUSTED_EXIT = 3  # journal_query.py --trusted-only: checkpoint withheld
UNTRUSTED_NOTICE = (
    "NOT LOADED: this repo's journal is not trusted on this machine, so its latest checkpoint "
    "was not shown. Checkpoint text comes from the repo and could have been written by anyone "
    "who commits to it. Run /log-init to trust this repo's journal."
)


def repo_root():
    """Return the git root of the current directory, or exit with an error."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit("ERROR: Not inside a git repository.")


def log_dir(root):
    return os.path.join(root, LOG_DIR_NAME)


def legacy_copies(root):
    """Names of legacy script copies present in the repo's .project-log/ (existence check only)."""
    return [n for n in LEGACY_SCRIPTS if os.path.lexists(os.path.join(log_dir(root), n))]


def warn_if_legacy(root):
    """Print the upgrade note to stderr in a legacy repo.

    The SessionStart hook shows the same note, but organizations can block
    hooks; printing it from every script call keeps it visible through skills.
    stderr keeps stdout clean for callers that parse it.
    """
    if legacy_copies(root):
        print(LEGACY_NOTICE, file=sys.stderr)


def journal_path(root=None):
    """Return the repo's journal path, refusing a symlinked .project-log/ or journal."""
    root = root or repo_root()
    directory = log_dir(root)
    journal = os.path.join(directory, JOURNAL_NAME)
    for path in (directory, journal):
        if os.path.islink(path):
            sys.exit(f"ERROR: Refusing to use symlinked journal path: {path}")
    return journal


# --- Trust list -----------------------------------------------------------------


def trust_key(root):
    """Identify a repo by its real git common dir, so all worktrees of one repo share trust."""
    try:
        common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit("ERROR: Not inside a git repository.")
    return os.path.realpath(os.path.join(root, common))


def registered_worktrees(common_dir):
    """Real paths of the worktrees git has registered for common_dir; empty on any error.

    A directory whose .git file points at another repo's git dir resolves to that
    repo's common dir but is not one of its worktrees, so it must not share its trust.
    """
    try:
        out = subprocess.check_output(
            ["git", "--git-dir", common_dir, "worktree", "list", "--porcelain", "-z"],
            stderr=subprocess.DEVNULL,
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()
    prefix = "worktree "
    return {os.path.realpath(f[len(prefix):]) for f in out.split("\0") if f.startswith(prefix)}


def _is_own_worktree(root, key):
    return os.path.realpath(root) in registered_worktrees(key)


def trust_store_path(data_dir):
    return os.path.join(data_dir, TRUST_STORE_NAME)


def _load_store(data_dir):
    """Return the repos mapping, {} if there is no store, or None if the store is unusable."""
    try:
        with open(trust_store_path(data_dir), encoding="utf-8") as f:
            store = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    repos = store.get("repos") if isinstance(store, dict) else None
    if not isinstance(repos, dict) or not all(isinstance(v, dict) for v in repos.values()):
        return None
    return repos


def is_trusted(root, data_dir):
    """True only if data_dir holds a well-formed store listing this repo, and root is
    a registered worktree of it. Never raises for a bad store."""
    if not data_dir:
        return False
    repos = _load_store(data_dir)
    if not repos:
        return False
    key = trust_key(root)
    return key in repos and _is_own_worktree(root, key)


def trust_repo(root, data_dir):
    """Add this repo to the trust list. Return True if newly added, False if already trusted."""
    if not data_dir:
        sys.exit("ERROR: no plugin data directory; cannot record trust (CLAUDE_PLUGIN_DATA is unset).")
    repos = _load_store(data_dir)
    if repos is None:
        sys.exit(
            f"ERROR: {trust_store_path(data_dir)} is malformed; fix or delete it, then retry. "
            "Refusing to overwrite it."
        )
    key = trust_key(root)
    if not _is_own_worktree(root, key):
        sys.exit(f"ERROR: {root} is not a registered worktree of its git dir {key}; refusing to trust it.")
    if key in repos:
        return False
    repos[key] = {"trusted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "worktree": root}
    os.makedirs(data_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=data_dir, prefix=".trusted-repos-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"schema": TRUST_SCHEMA, "repos": repos}, f, indent=2)
            f.write("\n")
        os.replace(tmp, trust_store_path(data_dir))
    except BaseException:
        os.unlink(tmp)
        raise
    return True
