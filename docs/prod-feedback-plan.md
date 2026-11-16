# Feedback on prod: plan

Status: agreed in outline (2026-11-15), not built. Gamma's feedback box (see
[gamma-feedback.md](gamma-feedback.md)) is the testbed; this is what changes when
signed-in players, not just allowlisted reviewers, can use it on prod.

## Roles

- **Any signed-in player**: submit a note, read the inbox, +1 a note.
- **Admin** (the owner; the allowlisted Steam IDs): resolve and reopen. Enforced in the
  Lambda (403 for anyone else), not only by hiding buttons.

## Admin works from S3, not the web

Prod has no endpoint that can close a note. `tools/feedback_admin.py`, run with the
owner's AWS credentials, lists open notes and resolves or reopens one. The inbox reads
S3, so a change shows at once. The script fills the commit from `git rev-parse HEAD`
and writes with a conditional put (`If-Match`) so it cannot overwrite a concurrent
change. Gamma keeps its web Resolve while the workflow is tried there.

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

One object per vote at `feedback-votes/<note-id>/<steam-id>`, written with
`If-None-Match: *`, so a second +1 from the same player fails and once-per-player holds
without locking. A counter on the note would lose votes when a +1 and an admin edit race.
The author's note counts as their +1. The inbox reads counts by listing each vote prefix;
revisit if the inbox passes a few hundred notes.

## Privacy and limits

- The API returns no one else's Steam ID. Players see "you" on their own notes; only the
  admin script shows authors.
- Per-player daily cap on submissions, the existing length caps, and the kill switch the
  other prod functions honor.
- Inbox also filters by category (bug, feature request, improvement idea).

## Open

- Whether every signed-in player sees every note (the plan assumes yes).
- Prod's bucket takes versioning with the same flag gamma uses; see the stack.
