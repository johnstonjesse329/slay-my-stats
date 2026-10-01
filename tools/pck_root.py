"""
Where the full PCK extraction (pck_recover_full/, ~3 GB, gitignored) lives.

This repo was split off from sts2-history-dashboard and doesn't carry its own
copy, so every tool that reads the extraction asks here instead of assuming
<repo>/pck_recover_full.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_pck_root() -> Path:
    """STS2_PCK_ROOT if set; else this repo's own pck_recover_full/ if there is
    one; else a `sts2-history-dashboard/pck_recover_full` next to ROOT or one
    of its ancestors, so it works whether the two repos are true siblings or a
    couple of directories apart (e.g. inside a worktree under one of them).
    """
    env = os.environ.get("STS2_PCK_ROOT")
    if env:
        return Path(env)
    own = ROOT / "pck_recover_full"
    if own.exists():
        return own
    for ancestor in (ROOT, *ROOT.parents):
        candidate = ancestor.parent / "sts2-history-dashboard" / "pck_recover_full"
        if candidate.exists():
            return candidate
    # Nothing found: return the in-repo path so a caller's "source not found"
    # message names somewhere sensible.
    return own
