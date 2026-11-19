# Clean up merged branches and worktrees

After a change is pushed and merged, fetch and verify it is present on the
intended upstream branch (`origin/gamma` for Gamma work, `origin/main` for
production work). Remove the completed worktree and its local topic branch
before closing the task. Keep active branches and any unique or uncommitted
work. Check for junctions before removing a Windows worktree and unlink them
without deleting their targets.

# The C: drive is not scratch space

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

# Visual review baseline

For UI changes and "what does this look like" reviews, use these reference
devices unless the user explicitly requests another size:

- Desktop: 1920 × 1080 viewport.
- iPhone 16: portrait and landscape, using Playwright's named iPhone 16 device
  presets (including touch, scale factor, and browser viewport/chrome settings).

Inspect all three layouts. Prefer WebKit for the iPhone checks when available.
Do not substitute generic desktop or phone dimensions for these baselines.
