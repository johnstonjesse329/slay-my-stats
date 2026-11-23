# Feedback batch SOP

In a fresh Codex session rooted at this repository, ask **“Process the open
production feedback through Gamma using the slay-feedback skill.”** To continue, ask
**“Resume the feedback batch”** or reply with a decision such as `ok FB-42`
or `change FB-42: keep the filter selected when I switch runs`.

## Intake and assignment

1. Keep one active orchestrator per checkout and retain
   `local_data/feedback/batch.json` across sessions. Start with `queue --env prod --ids`
   and refresh production intake once for a new pass. Save the scoped IDs under
   `local_data/feedback/` and reuse them on resume. Honor explicit limits or
   requests to include Gamma reports.
2. Use one intake agent for reports missing a disposition. Record the outcome
   for every scoped ID, including duplicates, requests for a product decision,
   already deployed fixes and blockers. Reconcile existing worktrees and
   handoffs before assigning new work. Group by shared code and acceptance
   checks so one patch can cover related reports.
3. Fetch `origin/gamma` and record its commit. Use one worktree and topic branch
   per group under `local_data/feedback/worktrees/`. Parallelize groups with
   independent edits. Serialize groups with overlapping edits unless they form
   one coherent change. Share the existing `infra\.venv` by absolute path. Use
   worktree-local build output and read-only access to shared prerequisites.
   Give preview servers distinct ports when needed.
4. Use GPT-6.2 Sol for orchestration and independent verification. Use Terra for
   bounded implementation with a concrete acceptance check, and Sol where a fix
   crosses systems or the diagnosis is still uncertain. Start at medium effort
   and reuse agents within closely related work when they have useful context.

## Run and verify the batch

- The worker implements and runs focused development checks. A separate verifier
  reviews and tests the exact candidate against recorded acceptance checks. The
  orchestrator handles scheduling, checkpoints, integration and deployment.
  See the [delegation briefs](../skills/slay-feedback/references/briefs.md).
- Send agents IDs and references. Read evidence in the main thread only when a
  decision depends on it. Save full shell output locally. Use worker completion
  events and blocking tool waits within the available limits. Avoid short polls
  and repeated test runs while waiting for a handoff.
- Checkpoint each candidate before assigning verification. For a failed or
  inconclusive result, record what was checked and the evidence path. Allow one
  targeted retry after a specific code change or repaired prerequisite. If there
  is no credible next step, defer immediately. After a second failed attempt,
  preserve the candidate and worktree and give the owner the two results and the
  exact decision or input needed. Continue independent groups. Starting a fresh
  thread or reassigning the report does not reset the limit.
- If validation setup stalls before a candidate exists, use the same initial
  attempt and targeted retry. Record the attempts in a handoff and set the
  report to `blocked` with the missing prerequisite or decision.
- Resume a validation-blocked report after the owner supplies the missing input
  or explicitly requests a retry. Preserve the failed attempts in the handoffs,
  clear `blocker` and `validation_failures` for the authorized retry, and restore
  its candidate checkpoint. Use `status: built` when a candidate exists, or
  `status: planned` when implementation is pending.
- Check allowance when the client exposes it at existing handoff points. Aim to
  finish with at least a quarter of the five-hour allowance available. If the
  forecast deteriorates, reuse checks, consolidate overlapping work and surface
  expensive unresolved decisions early. Record allowance at start/end when
  available, wall time and verified/blocked counts to compare completed passes.

## Batch checkpoints

`queue` summarizes the saved checkpoints by group. Resume `ready to close`,
`integration`, `candidate`, `verification pending`, `validation failed`,
`reopened`, `assigned`, or `queued` work as appropriate. `candidate` means the
recorded SHA passed verification. Skip `waiting for owner`, `waiting for
production`, and `blocked` until their decision, release, or blocker is addressed.

The orchestrator updates the batch record after assignment, worker completion,
review, deployment, and owner response. Keep the existing `status` values
used by the batch CLI. Store agent review, deployment and owner decisions in
their own fields, so a passed agent review can never set `status: approved`.
Use `record-candidate --id FB-42 --base <sha> --commit <sha> --checks "..." --handoff <path>`
and `record-review --id FB-42 --commit <sha> --verdict <verdict> --handoff <path>`.
Repeat `--id` for reports with the same result. Add `--reason` for a failed or
inconclusive verification. The command blocks those IDs on the second distinct
failure, even if the candidate SHA changed. Re-recording the same evidence path
does not spend another attempt.

| Field | What to record |
|---|---|
| `env`, `id`, `seq`, `inbox_status` | Source, stored note ID, stable public `FB-n`, and last observed inbox state |
| `group`, `plan`, `acceptance` | Assignment, intended change, and per-report acceptance check |
| `branch`, `worktree`, `base_commit` | Where to resume implementation |
| `commit`, `checks`, `agent_review` | Candidate, check summary, and reviewer verdict |
| `validation_failures`, `blocker` | Failed attempts and the immediate reason the owner needs to intervene |
| `handoffs` | Repo-relative paths to the intake, implementation, and review handoffs, keyed by role |
| `integration_commit`, `integration_worktree` | Exact commit and checkout saved before a Gamma push |
| `gamma_commit`, `gamma_url` | Verified deployed commit containing the fix and the review URL |
| `owner_decision`, `close_note` | Decision with `action` (`ok` or `change`), reviewed `gamma_commit` and optional `note`, plus public resolution text in `close_note` |

Use the saved handoff paths to retrieve the detailed results on resume. When a
revision needs a new handoff, save it to a new path and update the corresponding
checkpoint. Keep the earlier file with its review and evidence.

## Integrate and deploy

Use a clean integration worktree, leaving any unrelated checkout edits alone.
Once every scoped report has a verified fix or a recorded disposition, integrate
the passing commits on current `origin/gamma` and run combined checks. If one
commit mixes passing and failed behavior, split out the verified changes only
when the verifier can confirm the resulting commit independently. Otherwise
defer that shared commit and continue with unrelated fixes. Send
behavioral changes made during integration to the verifier. Keep each topic
commit reachable from the integrated commit so it can be verified before cleanup.

Check that `core.hooksPath` selects the repo's `githooks` in the integration
worktree. Push the candidate to `origin` using the explicit destination
`HEAD:refs/heads/gamma` and the existing deploy hook. Use a normal
fast-forward push. If the push is rejected or the smoke check fails, check
the remote ref and the deploy result before retrying. Verify the fetched
`origin/gamma` SHA and the smoke check for the same commit before recording
it as deployed. Find the passed smoke SHA in `slay-my-stats-gamma-ok` in the
directory returned by `git rev-parse --path-format=absolute --git-common-dir`.
The hook can deploy before the ref update succeeds, so verify both on resume.

- If the fetched ref and this clone's smoke marker agree and contain the
  reviewed work, reuse that deployment when there is no evidence of a later
  or partial deploy.
- If the candidate passed smoke and is still a fast-forward of the fetched
  ref, retry the normal Gamma push. If the ref diverged, integrate on the
  current tip and review the resulting candidate.
- If the fetched ref contains the reviewed work and deployment evidence
  is missing or uncertain, explicitly deploy the fetched commit with
  `tools/deploy.py --stage gamma --ref <sha>` using the repo venv. An up-to-date
  Git push does not send the Gamma ref to the deploy hook.

Leave production promotion to a separate owner-authorized
release workflow. For enforcement when running unattended, use credentials
scoped to Gamma deployment and push access restricted to Gamma.

Give the owner one checklist covering the scope. For fixes include `FB-n`,
source, direct Gamma URL and what to inspect. For deferred reports list the
blocker and the input needed. Verify URLs against the trusted Gamma origin.
Follow the junction and branch cleanup procedure in
[AGENTS.md](../AGENTS.md) after verifying the merged topic commits.

## Process owner decisions

- On `ok FB-n`, record the owner decision with the reviewed Gamma commit. For a
  Gamma report, record `status: approved` and a close note, inspect the `resolve --id FB-42` dry run,
  then repeat with `--apply`. Owner-approved duplicate or decline dispositions can use
  the corresponding status. A Gamma duplicate link must refer to a Gamma note.
- For a production report, the production release workflow can close the report
  with owner authorization once the fix ships to production.
- On an owner backlog, run `backlog --id FB-n --reason "..."` (dry run), then
  repeat with `--apply`. It works on Gamma and production notes, as the inbox's
  Backlog button does; the reason is optional and shown publicly, so it needs the
  owner's approval like a close note. `--off` takes a note back out.
- On `change FB-n …`, save the reviewed SHA and requested change in
  `owner_decision`, set `status: planned`, and clear the prior candidate, review,
  integration and Gamma checkpoints (`commit`, `checks`, `agent_review`,
  `integration_commit`, `integration_worktree`, `gamma_commit`, `gamma_url`)
  and the prior validation budget (`validation_failures`, `blocker`).
  Keep prior evidence in its handoff. Send the revision through independent
  review and deploy it to Gamma for sign-off. Leave unanswered reports open.
