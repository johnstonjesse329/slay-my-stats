# Project notes

## Docs move with the change

When a change works, update what it touches before calling it done: the README,
the architecture diagram (`docs/slay-my-stats-architecture.drawio`, then re-export
`images/aws-architecture.png`), docstrings and comments. `python tools/check_docs.py`
catches the AWS part (a resource missing from the diagram, or drawn but gone); the
pre-commit hook runs it whenever infra, docs or the README are in a commit.

## What's new copy comes from the owner

The What's new page intro and every post in `site/whats-new/` are the owner's words, not ours.
Draft one when asked and suggest edits to theirs. Trimming, organizing and tightening are fine,
but keep their voice: don't swap in different phrasing or tone, and never add claims, features or
detail they didn't write. Show the exact before and after in the message that asks for approval,
as for any public text.

Open: a way to suggest flagship changes worth a post (so the owner can pick what to write up).
Not built; ask before inventing one.

## Branches: gamma is the base, main is prod

`gamma` is the trunk for new work. Branch every change from the current
`origin/gamma` (not `main`), merge it back into `gamma` with `--no-ff`, and push
`gamma` to deploy it there. Prod is downstream: merge `gamma` into `main` and push
`main`. Nothing reaches `main` except through `gamma`, so prod gets everything
that was on gamma at that point. A change that must not ship is reverted on
`gamma` first. Deploy steps are in the memory runbook.

## Worktrees: assume someone else is working here too

Other sessions work in this repo at the same time, on the same files and
branches. Assume they are, even when nothing shows it.

- Do every change in a worktree of your own, branched from a fresh
  `origin/gamma`: `git worktree add -b <branch> "../smst-wt-<branch>" origin/gamma`.
  Never switch branches, stash, commit or reset in the main checkout or in
  someone else's worktree; their uncommitted work is theirs.
- Don't build on a local branch you didn't make. Re-fetch before merging or
  pushing: if `origin/gamma` moved, merge onto the new tip, and say what else
  is riding along before it goes to prod.
- Deploys push from the main checkout (it holds the ignored `cdk.context.json`
  and art). Only push from it when it is clean and on the commit you mean to
  ship; if another session is mid-change there, wait or ask.
- Removing a worktree: unlink its junctions first (`cmd /c rmdir <junction>`).
  `git worktree remove` deletes through a junction into the main checkout's art.

## Screenshots

The README screenshots (`images/site-overview.png`, `site-run-detail.png`,
`site-card-stats.png`) show the live UI. When a change alters what one of those
pages looks like, retake that screenshot in the same change. Build a preview
(`python build_site.py`, then `python tools/serve_site.py`) from a folder with
the Steam ID in its path so co-op runs read the right player.

## The C: drive is not scratch space

Experimental work here once left a virtualenv on `C:` holding over two million
files, which slowed the machine and every indexer on it. The repo lives on `E:`,
but Python and browser tooling still default to `C:`: the pip and uv caches,
Playwright's browsers, `%TEMP%`, and any venv created outside the repo.

- Install only into the repo's `infra\.venv`. Do not add packages to the system
  Python, and do not create a second venv outside the repo for one experiment.
- After an experiment, remove what it left behind: throwaway venvs, generated
  `local_data/` output, `.playwright-mcp/`, a stale `dist/`, downloaded archives
  and temp copies. Keep `infra\.venv` — it is gitignored and reused.
- When the work is done, purge what the installs cached: `python -m pip cache purge`,
  `uv cache clean`, and delete downloaded browser builds that are no longer needed.
- Before calling a long task finished, check the counts below and clean up if they grew:

```powershell
foreach ($p in "$env:LOCALAPPDATA\pip\cache", "$env:LOCALAPPDATA\uv\cache",
               "$env:LOCALAPPDATA\ms-playwright", "$env:TEMP") {
    "{0,10:N0} files  {1}" -f (Get-ChildItem $p -Recurse -File -Force -ErrorAction SilentlyContinue |
        Measure-Object).Count, $p
}
```
