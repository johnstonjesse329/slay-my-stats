# Gamma feedback

After deploying the site and gamma CDK stack, signed-in gamma reviewers get a
gold **Feedback** button in the lower right on every page, carrying the number of
open notes on the page they are looking at. Production shows the same button to
everyone, leading to the Steam sign-in while signed out; its notes are `env=prod`. It opens
one panel with two views, **New note** and **Inbox**; either is closed with the
panel's X or Escape.

**New note** writes one:

- Choose **Pick on page**, then click near what you mean (or drag across it).
- Choose **Whole page** for a general comment, enter it, and send it.
  The composer shows the exact page URL that goes with the note, including its
  hash and query, so a report can be reopened without guessing the host.
- Sending closes the panel and the Feedback button reads **Sent** for a moment; reopening
  lands on the Inbox, where the new note is.
- Pick a type: **Bug**, **Feature request** or **Improvement idea**. It is required,
  is stored on the note as `category` and shows on it in the inbox and the emails.
  Notes from before categories have none.
- The composer lists earlier notes for that same element, region or whole page,
  with who wrote them and whether they are resolved, so the same point is not
  raised twice.

**Inbox** reviews them:

- **This page** (the default) and **Whole site** switch what the inbox shows.
- Notes are grouped into one bucket per whole page and per pinned element or
  region, newest bucket first, each with its note and open counts. A bucket can
  start collapsed, each showing its newest comment; **Expand all** / **Collapse all** opens
  or closes every one, and an open one stays open for the session. On **This page** the
  list follows the site's tabs and runs.
- **Open location** opens the original page and highlights the element or saved
  region, with the inbox showing that note's group open and the note marked. Layout changes can invalidate a selector; saved target text and viewport
  dimensions remain available in the copied report.
- A **status** filter (Open by default, Backlog, Resolved, All) and a **type** filter (any,
  bug, feature request, improvement idea, kudos) narrow the inbox. The Lambda applies them,
  so a narrow filter may scan several notes per page and hand back fewer than 25.
- **Search** and an **author** filter narrow the notes already loaded (Load more brings in older
  ones). Search reads the comment, close note, pinned text, path and names.
- **+1** sits on each note's title row: one per signed-in person, tapped again to take it back,
  with the count of everyone who agreed. Each +1 is its own item in the table and the note keeps
  only the count (`plus_count`), so the inbox never sends who agreed, only whether you did. A
  repeat of the same request changes nothing.
- Every note has a stable id, **FB-n**, shown on its title row and in the emails. The Lambda
  takes it from one counter in the table when the note is created, shared by gamma and prod, so
  numbers never repeat between them. It never changes, so a commit message or close note can cite `FB-12`.
- An **environment** picker (Gamma, Prod, Both) appears beside the filters when the inbox can read
  more than its own notes, as gamma's can. Gamma is the default. A note from the other one is
  marked with its name and is read-only here: its +1 and Resolve belong to the site it was sent from.
- Each player may make 60 changes an hour (UTC), at most 10 of them new notes; past that the
  Lambda answers 429 and the panel says so.
- **Backlog** marks an open note we will take on, but not now, with an optional reason
  (`backlog`: who, when, why). It leaves the Open list and the Feedback button's count, shows
  under the Backlog filter and as its own number in the digests, and **Move to open**
  takes it back. Resolving a note clears it.
- **Resolve / Reopen** tracks review. Only the owner (`ownerSteamId`) can do this, and Backlog too; other
  reviewers don't see the buttons and the Lambda answers 403.
  Resolving picks an **outcome**: *Done* needs a close note about what changed (a commit is
  optional and links to GitHub), *Declined* needs a close note saying why, *Duplicate* needs the id of the
  other note. The note records who resolved it, when, the outcome, the close note and
  the commit, and the Lambda refuses a resolve missing what its outcome needs. Resolved
  notes leave the Open list and show under Resolved with their outcome. Reopening keeps
  that resolution in the note's `history`, so a note closed, reopened and closed again
  shows every step. Notes resolved before outcomes existed show as plain Resolved.
- **Copy all notes (N)** copies every note in the list (resolved or not, in a collapsed
  group or not), with page URLs, target details, author Steam IDs and timestamps,
  ready to paste into Codex. Each note also has its own **Copy details** for just that one.
- The number on the Feedback button is the open notes on the page you are on, and a
  page includes its `#hash`, so it is re-read when you move to another tab or run.
  The inbox's **Whole site** and **Copy all notes** count every note on the site.
- Authors and resolvers show by Steam display name. The Lambda looks the name up when it
  serves a note (cached for six hours); names are never stored on the note. If Steam
  can't be asked, the note shows `Steam …1234` (the last four digits of the ID, in a
  muted tone), unless the panel already saw that person's name this session, in which
  case it keeps the name. Every note has the same fixed layout: author left and time
  right on the first line, then the status and type tags with **Open location**.
- Opening a note from its link shows where it points but leaves the entry empty,
  so an existing note can't be sent a second time.
- Notes load 25 at a time; **Load more** fetches the next page.

The feedback table has point-in-time recovery (35 days) and deletion protection, and is
retained if its stack is deleted. The notes from before the table (FB-2 to FB-27) were copied
into it from `feedback/` in the gamma data bucket by `tools/feedback_migrate.py`; those objects
and their versions stay there, untouched.

The panel can be dragged by its header and resized from its bottom-right corner or its left edge; it
keeps its place between openings. On screens 600px wide or narrower it is instead a
full-width bottom sheet (no dragging or resizing, 16px inputs so iOS doesn't zoom, larger
tap targets). **Clear** on the New note tab drops a pinned
element and the typed text.

**Emails.** The gamma stack also emails the alert address: each morning (8 AM
Central, Tuesday to Sunday) the notes that came in over the last day with the number open, and nothing
on a quiet day; on Mondays one weekly email instead (never two) with the open total (with the backlog counted apart), the notes that came in and the ones
resolved that week, and the open notes. Both name the author by Steam name. Notes resolved before resolutions were
timestamped have no date and are not counted as resolved in a week.

Notes are items in the DynamoDB table `slay-my-stats-feedback` (its own stack,
`infra/slay_my_stats/feedback_stack.py`), partitioned by `env`: gamma's are `env=gamma`.
Each note stores the page's exact `url` (gamma origin, path, query and hash) next to
the same-site `path`, which **Open location** uses. They are accessed through
`/auth/feedback`, not through the public profile behavior. The endpoint verifies
the existing signed gamma session independently of CloudFront, checks the Steam
allowlist, and checks Origin on writes. IAM lets the gamma auth Lambda read the
gamma and prod partitions and write only gamma's (and the FB-n counter); prod's
ingest Lambda reads and writes only prod's, and the production digest Lambda reads both. Notes do not include screenshots.

Note ids sort newest first, so a page is one query: on the table for the whole site,
or on an index for a status, a type or one page (`ByState`, `ByStateCategory`,
`ByCategory`, `ByPage`). The cursor is the last key read, per environment when
reading Both. A request reads at most 400 items, so a narrow filter can hand back
fewer than 25 with more to load.

Verification:

```powershell
infra/.venv/Scripts/python.exe build_site.py
infra/.venv/Scripts/python.exe -m unittest infra.tests.test_feedback infra.tests.test_gamma_auth
infra/.venv/Scripts/python.exe tools/test_feedback_browser.py
```

The browser test (set `FEEDBACK_TEST_DIST` to serve a copy of `dist/` instead of `dist/`) uses a mocked inbox, Chromium at 1920 x 1080, and WebKit with
Playwright's iPhone 16 portrait and landscape presets. Screenshots are written
to `.playwright-mcp/feedback-*.png`. The feature is also visible on localhost for
UI development; the normal local server does not emulate the authenticated inbox.