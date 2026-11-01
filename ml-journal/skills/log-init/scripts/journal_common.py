"""journal_common.py — Repo and journal path resolution shared by the ml-journal scripts.

The repo is untrusted: the scripts run from the plugin, never from the repo,
and refuse a symlinked .project-log/ or journal.jsonl, which a hostile repo
could commit to redirect reads and writes to a file outside it.
"""

import os
import subprocess
import sys

LOG_DIR_NAME = ".project-log"
JOURNAL_NAME = "journal.jsonl"
# Script copies an older /log-init put in .project-log/. Never run; only detected.
LEGACY_SCRIPTS = ("journal_log.py", "journal_query.py")
LEGACY_NOTICE = (
    "NOTE: this repo uses the legacy ml-journal layout (journal scripts copied into "
    ".project-log/). Those copies are no longer used; run /log-init to upgrade."
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
