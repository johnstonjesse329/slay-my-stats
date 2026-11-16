# Gamma feedback

After deploying the site and gamma CDK stack, signed-in gamma reviewers get a
gold **Feedback** button in the lower right on every page, carrying the number of
open notes on the page they are looking at. Production shows neither. It opens
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
  be collapsed; that choice lasts for the session.
- **Open location** opens the original page and highlights the element or saved
  region. Layout changes can invalidate a selector; saved target text and viewport
  dimensions remain available in the copied report.
- A **status** filter (Open by default, Resolved, All) and a **type** filter (any,
  bug, feature request, improvement idea) narrow the inbox. The Lambda applies them,
  so a narrow filter may scan several notes per page and hand back fewer than 25.
- **Search** and an **author** filter narrow the notes already loaded (Load more brings in older
  ones). Search reads the comment, close note, pinned text, path and names.
- **+1** sits on each note's title row: one per signed-in person, tapped again to take it back,
  with the count of everyone who agreed. The Lambda stores the ids on the note (`plus`, at most 50)
  and a repeat of the same request changes and writes nothing.
- **Resolve / Reopen** tracks review. All allowed gamma reviewers can do this.
  Resolving picks an **outcome**: *Done* needs a commit and a close note about what
  changed, *Declined* needs a close note saying why, *Duplicate* needs the id of the
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

The gamma data bucket is retained when the stack is deleted and is versioned, so an
overwritten or deleted note can be recovered from its earlier versions. Versions of
everything but `feedback/` expire after 30 days; feedback versions are kept.

The panel can be dragged by its header and resized from its bottom-right corner; it
keeps its place between openings. On screens 600px wide or narrower it is instead a
full-width bottom sheet (no dragging or resizing, 16px inputs so iOS doesn't zoom, larger
tap targets). **Clear** on the New note tab drops a pinned
element and the typed text.

**Emails.** The gamma stack also emails the alert address: each morning (8 AM
Central, Tuesday to Sunday) the notes that came in over the last day with the number open, and nothing
on a quiet day; on Mondays one weekly email instead (never two) with the open total, the notes that came in and the ones
resolved that week, and the open notes. Both name the author by Steam name. Notes resolved before resolutions were
timestamped have no date and are not counted as resolved in a week.

Notes are private JSON objects under `feedback/` in the gamma data bucket. Each
note stores the page's exact `url` (gamma origin, path, query and hash) next to
the same-site `path`, which **Open location** uses. They are accessed through
`/auth/feedback`, not through the public profile behavior. The endpoint verifies
the existing signed gamma session independently of CloudFront, checks the Steam
allowlist, and checks Origin on writes. The gamma auth Lambda receives access
only to that prefix. Notes do not include screenshots.

Newest keys sort first, so a page is one `list_objects_v2` walk: the cursor is the
last key read. A whole-site page needs 25 notes, while a page-scoped view skips
other paths (up to 400 objects read in one request). There is no shared index, so
nothing can disagree with the objects themselves.

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