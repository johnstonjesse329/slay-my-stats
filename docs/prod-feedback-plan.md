# Feedback on prod: plan

Status: agreed (2026-11-15), not built. Storage settled on DynamoDB the same day.
Gamma's feedback box (see [gamma-feedback.md](gamma-feedback.md)) is the testbed; this
is what changes when signed-in players, not just allowlisted reviewers, can use it on prod.

## Environments

Prod is public; gamma is a private preview for specific people. Feedback follows that:

- Every note carries `env` (`prod` or `gamma`), set by the Lambda from the request origin.
  The client cannot send or change it. Existing gamma notes are backfilled as `gamma`.
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
- **Admin** (the owner; the allowlisted Steam IDs): resolve, reopen and backlog. Enforced in the
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

Gamma stays on S3 until the table is built and tried there.

## Admin works from the AWS side, not the web

Prod has no endpoint that can close a note. `tools/feedback_admin.py`, run with the
owner's AWS credentials, lists open notes and resolves or reopens one. The inbox reads
the table, so a change shows at once. The script fills the commit from
`git rev-parse HEAD` and uses a conditional update (the note must still be in the state
the script read) so it cannot overwrite a concurrent change. Gamma keeps its web Resolve
while the workflow is tried there.

## Outcomes

A resolved note carries an `outcome`:

| outcome | needs | meaning |
| --- | --- | --- |
| `done` | commit (linked to GitHub, the repo is public) and a close note | we built or fixed it |
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
- Gamma's existing notes are test junk; the table starts empty and they are not moved.
