# Gamma feedback

After deploying the site and gamma CDK stack, signed-in gamma reviewers see
**Feedback** in the lower right on every page. Production does not show it.

- Choose **Pin to element / region**, then click an element or drag a rectangle.
- Choose **Whole page** for a general comment, enter the comment, and send it.
- **Inbox** shows the latest 200 shared notes, including resolved notes.
- **Open location** opens the original page and highlights the element or saved
  region. Layout changes can invalidate a selector; saved target text and viewport
  dimensions remain available in the copied report.
- **Resolve / Reopen** tracks review. All allowed gamma reviewers can do this.
- **Copy open notes** copies the loaded unresolved notes, with page URLs, target
  details, author Steam IDs, and timestamps, ready to paste into Codex.

Notes are private JSON objects under `feedback/` in the gamma data bucket. They
are accessed through `/auth/feedback`, not through the public profile behavior.
The endpoint verifies the existing signed gamma session independently of
CloudFront, checks the Steam allowlist, and checks Origin on writes. The gamma
auth Lambda receives access only to that prefix. Notes do not include screenshots.
The inbox is intentionally bounded to the most recent 200 notes; older objects
remain in the bucket. Newest keys sort first without a separate shared index.

Verification:

```powershell
infra/.venv/Scripts/python.exe build_site.py
infra/.venv/Scripts/python.exe -m unittest infra.tests.test_feedback infra.tests.test_gamma_auth
infra/.venv/Scripts/python.exe tools/test_feedback_browser.py
```

The browser test uses a mocked inbox, Chromium at 1920 × 1080, and WebKit with
Playwright's iPhone 16 portrait and landscape presets. Screenshots are written
to `.playwright-mcp/feedback-*.png`. The feature is also visible on localhost for
UI development; the normal local server does not emulate the authenticated inbox.
