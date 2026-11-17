# Feedback verification — November 16, 2026

## FB-22: initial loading

Implementation: 9364aab (versioned monthly data caching) and f612494 (deferred Cards DOM).
Three fresh Chromium contexts per variant, local splitswigs profile, 1920 × 1080. Controlled comparison changes only the Cards prefetch delay from 6000 ms to 0 ms; sampled 600 ms after overview rows appear. This isolates deferred rendering, not a historical whole-build comparison.

Every eager sample had 11,149 DOM nodes and 1,148 image elements; every deferred sample had 2,353 nodes and 117 images (79% and 90% fewer). Resource entries dropped 56 to 53; transferred resource bytes dropped 4,088,405 to 4,016,980. DOMContentLoaded medians were 77.9 ms eager and 80.1 ms deferred: no demonstrated navigation-time gain. Deferred work still happens on Cards intent or after six seconds; no claim of permanent payload removal. Raw samples: local_data/feedback/evidence/FB-22-measurements.json.

## FB-25: feedback notifications

Implementation: 58ba434. Read-only AWS verification found both deployed schedules ENABLED: daily cron(0 8 ? * TUE-SUN *), weekly cron(0 8 ? * MON *), America/Chicago. Monday intentionally sends weekly only, avoiding two digests that morning. Daily report covers the preceding 24 hours; weekly covers seven days. Quiet daily reports send nothing.

Existing CloudWatch executions for both daily and weekly reported sent=true and ended normally with no exceptions. The SNS alert topics have confirmed email subscriptions, with no SMS subscriptions. Feedback creation does not publish per-note alerts. This verifies successful application submission to SNS, not receipt in a personal mailbox; no test notifications were sent.

## FB-26: mobile synergy sizes

Cards now use two columns through 600 px, up from three narrow columns. Inline relic panels occupy one card-width grid cell with 48 px art; landscape up to 899 px uses 56 px relic art. Desktop rules remain unchanged.

Visually inspected the reported run (1792337104) at desktop 1920 × 1080 and named Playwright iPhone 16 portrait/landscape in WebKit. No horizontal page overflow. Evidence: local_data/feedback/evidence/FB-26-{desktop,iphone-portrait,iphone-landscape}.png. The existing broad explorer test could not load its older milworkz fixture locally; checks used the actual reported splitswigs run instead.
