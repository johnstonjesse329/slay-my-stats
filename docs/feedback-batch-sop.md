# Feedback batch SOP

How a pile of gamma feedback notes becomes verified, evidenced, closed notes.

## Roles

- **Orchestrator** (the main session): pulls the batch, groups notes by area and the files they
  touch, writes one brief per group, runs the groups one at a time, checks each result against
  its expected output, then reports. Groups run in sequence because they share one working
  tree, `dist/` and the ignored art; parallel agents would collide.
- **Worker** (one subagent per group): fixes only its notes, verifies in a browser, returns
  the result in the format below.

## Steps

1. `python tools/feedback_batch.py pull`, then group (`group`, `plan` per entry in
   `local_data/feedback/batch.json`).
2. Per group, hand the worker a brief with: the entries (`n`, comment, url, selector,
   viewport), the files in scope, the rules in `CLAUDE.md`, and the expected output.
3. The worker edits, runs `node --check js/*.js`, `python build_site.py`,
   `python tools/check_docs.py` and the tests that touch its area, then serves a preview
   (`tools/serve_site.py` from a folder with the Steam ID in the path) and screenshots each
   fixed item at the note's own viewport (phone notes at about 402 wide, scale 3).
4. The worker commits its files on the batch branch and records, per entry, in the batch
   file: `status` = `built` (or `blocked` with the reason), `commit`, `evidence` (screenshot
   path under `local_data/feedback/evidence/`) and `tldr` (one line: what is now true).
5. `python tools/feedback_batch.py evidence > local_data/feedback/evidence/REPORT.md` builds the one-table
   tl;dr list (status, commit, what is now true, screenshot) from the batch file. The orchestrator opens a few screenshots, rejects any without visible proof, and
   re-briefs that item.
6. The owner reviews locally or on gamma. For approved entries set `status: approved`
   and a `close_note`, then `feedback_batch.py resolve` (dry run), then `--apply`.

## Worker output (what comes back)

Per note: `n`, status, commit, `tldr`, evidence path, and anything left undone. Items
that need the owner's call (copy wording, design alternatives) are `blocked`, not guessed.

## Evidence

Screenshots live in `local_data/feedback/evidence/<n>-<slug>.png` (gitignored). They stay
local until the owner decides on S3 (`feedback-evidence/` in the gamma data bucket would
let reviewers see them from the note).
