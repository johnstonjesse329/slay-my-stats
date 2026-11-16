# Gamma feedback

After deploying the site and gamma CDK stack, signed-in gamma reviewers get a
gold **Feedback** button in the lower right on every page, carrying the number of
open notes on the page they are looking at. Production shows neither. It opens
one panel with two views, **New note** and **Inbox**; either is closed with the
panel's X or Escape.

**New note** writes one:

- Choose **Pin to an element or region**, then click an element or drag a rectangle.
- Choose **Comment on the page** for a general comment, enter it, and send it.
  The composer shows the exact page URL that goes with the note, including its
  hash and query, so a report can be reopened without guessing the host.
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
- **Resolve / Reopen** tracks review. All allowed gamma reviewers can do this.
- **Copy open notes** copies the loaded unresolved notes, with page URLs, target
  details, author Steam IDs, and timestamps, ready to paste into Codex.
- Notes load 25 at a time; **Load more** fetches the next page.

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

The browser test uses a mocked inbox, Chromium at 1920 x 1080, and WebKit with
Playwright's iPhone 16 portrait and landscape presets. Screenshots are written
to `.playwright-mcp/feedback-*.png`. The feature is also visible on localhost for
UI development; the normal local server does not emulate the authenticated inbox.