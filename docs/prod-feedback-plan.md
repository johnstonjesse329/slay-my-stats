# Feedback on prod: plan

Status: agreed (2026-11-15). Storage settled on DynamoDB the same day. Built for gamma
(2026-11-16, the table, `env`, the Environment filter and the +1 transactions); prod not built.
Gamma's feedback box (see [gamma-feedback.md](gamma-feedback.md)) is the testbed; this
is what changes when signed-in players, not just allowlisted reviewers, can use it on prod.

## Environments

Prod is public; gamma is a private preview for specific people. Feedback follows that:

- Every note carries `env` (`prod` or `gamma`), fixed by which Lambda wrote it: each stage's
  stack sets `FEEDBACK_ENV` on its function. Nothing in the request can set or change it (an
  Origin header can be forged by a script; the Origin check stays, only as a guard against
  writes from other sites). Existing gamma notes are copied in as `gamma`.
- **Prod** lists and accepts only `prod` notes, for any signed-in player. Its Lambda has no
  read access to gamma's notes.
- **Gamma** (allowlisted people) reads both environments, with an Environment filter
  (Gamma / Prod / Both) and an env tag on each note, so what is about the preview and what
  is about the live site stay apart. Never the reverse.
- Notes get a stable id, **FB-n**, from one sequence across both environments (built on
  gamma already: `seq` on the note, shown in the panel and emails). A commit or close note
  can cite `FB-12` and it never points at two notes.
- **Backlog** (built on gamma): an open note we will take on, but not now, with an optional
  reason. It leaves the Open list and counts, and shows under its own filter.

## Roles

- **Any signed-in player**: submit a note, read the inbox, +1 a note.
- **Admin** (the owner only, `ownerSteamId`): resolve, reopen and backlog. Enforced in the
  Lambda (403 for anyone else), not only by hiding buttons.

## Storage: one DynamoDB table

Prod feedback moves from one S3 object per note to a single on-demand DynamoDB table.
It is the stack's first database, an amendment to the S3 / CloudFront / one-Lambda design,
chosen because the inbox needs things S3 can only do by scanning: filter by status or
category, sort, count +1s, and enforce once-per-player.

- **Notes**: one item per note, keyed by id, with `env`, `seq` and an optional `backlog`. Note ids sort by time, newest first.
- **Open / Backlog / Resolved / category views**: global secondary indexes, so the inbox reads one
  page with a Query instead of fetching objects one by one.
- **Page-scoped view**: an index on the note's page path.
- **Pagination**: 25 notes a page using the Query's last key. The inbox loads only when a
  player opens Feedback, never with the page.
- **Recovery**: point-in-time recovery on, and a retained removal policy so tearing the
  stack down keeps the table.
- **Cost**: on-demand, about $0.625 per million writes, $0.125 per million reads, storage
  free under 25 GB. Expect cents a month (verified against the AWS price list, us-west-2).

Gamma moved from S3 to the table on 2026-11-16 (see "Moving gamma over" below).

## Admin works from the AWS side, not the web

Prod has no endpoint that can close a note. `tools/feedback_admin.py`, run with the
owner's AWS credentials, lists open notes and resolves or reopens one. The inbox reads
the table, so a change shows at once. When there is a commit, the script fills it from
`git rev-parse HEAD` and uses a conditional update (the note must still be in the state
the script read) so it cannot overwrite a concurrent change. Gamma keeps its web Resolve
while the workflow is tried there.

## Outcomes

A resolved note carries an `outcome`:

| outcome | needs | meaning |
| --- | --- | --- |
| `done` | a close note; a commit when there is one (linked to GitHub, the repo is public) | we built or fixed it |
| `declined` | close note saying why | we decided not to |
| `duplicate` | the id of the other note | already reported |

Close notes are visible to every user: an unexplained "declined" reads as ignored.
The inbox gets a status filter, **Open** (default), **Resolved** and **All**; Resolved
lists newest first with outcome, why and commit. A "What changed" page built from the
`done` notes is optional and waits until the filter proves too buried.

## +1s

One vote item per player per note, written in a transaction with the note's counter
increment. The vote item is created with `attribute_not_exists`, so a second +1 from the
same player fails and the counter never moves: once-per-player holds without locking, and
the count is exact. The author's note counts as their +1. Inbox counts come straight from
the note's counter.

## Privacy and limits

- The API returns no one else's Steam ID. Players see "you" on their own notes; only the
  admin script shows authors.
- Per-player daily cap on submissions, the existing length caps, and the kill switch the
  other prod functions honor.
- Inbox also filters by category (bug, feature request, improvement idea).

## Build order

1. On gamma, with S3: the `outcome` field, Open / Backlog / Resolved / All and category
   filters, FB-n ids and Backlog (done).
2. The `env` field, the Environment filter on gamma, and the one-way read rule.
3. The DynamoDB table, the Lambda's role check, +1 transactions and pagination, tried on
   gamma first.
4. `tools/feedback_admin.py`, then prod.

## Decided

- Every signed-in player sees every prod note; only gamma reviewers see gamma notes.
- Gamma reviewers see prod notes too; prod never sees gamma's.
- ~~Gamma's existing notes are test junk; the table starts empty.~~ Revised 2026-11-16: commits
  and docs cite FB-2 to FB-27, so gamma's S3 notes are copied into the table as `gamma` notes,
  kept for history and still usable on gamma. Prod starts empty (it never reads `gamma`).
  New notes continue the sequence from FB-28.
- The table lives in a small stack of its own, deployed only when the table changes (below).
- Gamma first: the table, `env`, the Environment filter and the +1 transactions go to gamma;
  prod sign-in sessions and `tools/feedback_admin.py` are the next pass.

## Gamma build design (2026-11-16)

### The feedback stack

`SlayMyStatsFeedbackStack` in `infra/app.py`, holding only the table `slay-my-stats-feedback`:
on-demand, point-in-time recovery, deletion protection, `RemovalPolicy.RETAIN`, TTL on
`expires` (throttle counters only). The stage
stacks refer to it by name and ARN, not a CloudFormation export, so neither stack locks the
other. A normal push never touches it: `tools/deploy.py --feedback-table` deploys it, with the
diff and a y/N first. deploy.py stops a normal push whose commits change the feedback stack's
file since its last deploy (recorded in the git dir, like `slay-my-stats-gamma-ok`) and says
to run `--feedback-table`. Both stages share it, so an index is only ever added, never removed
or renamed while a Lambda reads it.

### Items

Partition key `env`, sort key `sk`.

| item | `env` | `sk` | other fields |
| --- | --- | --- | --- |
| note | `gamma` / `prod` | the note id, `feedback/<9999999999-created>-<uuid>.json` | everything a note has today, `plus_count`, index keys below |
| +1 | same as the note | `vote#<note id>#<steam id>` | `at` |
| throttle | the stage's env | `rate#<steam id>#<UTC hour>` | `n`, `expires` |
| FB-n counter | `counter` | `seq` | `value` |

Note ids keep today's shape, so `duplicate_of`, `?feedback=` links and the migrated notes
need no change, and ascending order is newest first.

Indexes, each partitioned on `env` (so the IAM rule below covers them too), projecting all fields:

| index | sort key | serves |
| --- | --- | --- |
| `ByState` | `st` = `<open/backlog/resolved>#<id>` | status filter |
| `ByStateCategory` | `stcat` = `<state>#<category>#<id>` | status and type together |
| `ByCategory` | `cat` = `<category>#<id>` | All plus a type |
| `ByPage` | `pg` = `<sha256(path)[:20]>#<id>` | This page (raw paths can pass the 1 KB key limit) |

All with no type is the base table, read with `begins_with(sk, "feedback/")` so +1 and
throttle items never show. A page view applies status and type as a filter; one
page holds few notes. Every write that changes state rewrites `st`/`stcat`, and the indexes
follow.

### Writes

- **Create:** increment the counter (`ADD value 1`, returns the new FB-n), then one
  transaction: put the note (`attribute_not_exists`) and the author's +1. A failed
  transaction leaves a gap in the numbers, never a repeat.
- **Resolve / reopen / backlog:** one `UpdateItem`, conditioned on `st` still being what was
  read, so two reviewers can't overwrite each other; reopen appends to `history`.
- **+1:** transaction: put the vote (`attribute_not_exists`) and `ADD plus_count 1`. Taking it
  back: delete the vote (`attribute_exists`) and `ADD plus_count -1`. A repeat fails the
  condition and changes nothing.
- **Throttle (FB-24):** every write first bumps a per-player counter in the same `env`,
  `sk` = `rate#<steam id>#<UTC hour>`, with `ADD n 1` conditioned on `n` being under the cap
  (60 writes an hour, of which at most 10 new notes); over it, 429 and nothing else is
  written. A TTL field deletes the counter after a day. Before this, gamma had no rate limit,
  only the 50-voter cap on a note.
- Only admins (`ADMIN_STEAM_IDS`, set from `ownerSteamId`) resolve, reopen or backlog:
  403 otherwise. Nobody resolves a `prod` note from gamma (gamma's role can only read them).

### Reads

- 25 notes a page. The cursor is the last note's key, base64 JSON, checked strictly (known
  fields only, an `env` this Lambda may read). Filtered queries keep reading until 25 or
  the end, capped per request.
- Gamma's Environment filter (Gamma, the default / Prod / Both). Both queries each env and
  merges newest first; the cursor holds one key per env.
- The API sends `plus_count` and `plus_mine` (one BatchGetItem of the page's votes for the
  caller), not the list of who voted. The panel switches from `note.plus` to these. That is
  the prod privacy rule, applied on gamma first.
- Each note carries its `env`; the panel tags it and hides Resolve/Backlog on `prod` notes.

### Access (IAM, `dynamodb:LeadingKeys`)

| role | read | write |
| --- | --- | --- |
| gamma auth Lambda | `gamma`, `prod`, `counter` | `gamma`, `counter` |
| gamma digest Lambda | `gamma` | none |
| prod (next pass) | `prod`, `counter` | `prod`, `counter` |

Proved on gamma with real refused calls (a write to `prod`, a query on an index for an env
it may not read), not by reading the policy.

### Moving gamma over

1. `tools/deploy.py --feedback-table` creates the table.
2. `tools/feedback_migrate.py` (dry run by default; `--apply` writes) copies every S3 note as
   `env=gamma` with its seq, outcome, backlog and history; each `plus` id becomes a vote item and
   `plus_count`. Puts are `attribute_not_exists`, so a rerun only adds what is new. The counter
   is raised to the highest seq, never lowered. S3 is only read; the versioned copies stay.
3. Deploy gamma with the table-backed Lambda, then rerun the migration to catch notes sent in
   between.
4. Port `feedback_batch.py` (pull/resolve) and the digest Lambda to the table.

### Tests

`moto` (into `infra\.venv` only, test-only, not in the Lambda bundle) runs the real
conditions and transactions locally: create numbering, +1 once per player, the conditional
resolve, cursors, Both merge, the 403s, migration rerun. The browser test's mocked inbox
moves to `plus_count`/`plus_mine` and an env tag. Then a gamma run in a real browser.
