# Project notes

## Docs move with the change

When a change works, update what it touches before calling it done: the README,
the architecture diagram (`docs/slay-my-stats-architecture.drawio`, then re-export
`images/aws-architecture.png`), docstrings and comments. `python tools/check_docs.py`
catches the AWS part (a resource missing from the diagram, or drawn but gone); the
pre-commit hook runs it whenever infra, docs or the README are in a commit.

## Screenshots

The README screenshots (`images/site-overview.png`, `site-run-detail.png`,
`site-card-stats.png`) show the live UI. When a change alters what one of those
pages looks like, retake that screenshot in the same change. Build a preview
(`python build_site.py`, then `python tools/serve_site.py`) from a folder with
the Steam ID in its path so co-op runs read the right player.
