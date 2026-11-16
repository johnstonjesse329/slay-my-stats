# Shared components audit (2026-11-16)

Read-only audit of where the site repeats the same thing, so edge cases (a missing
character, wrapping names, clipped tooltips) stop recurring. Line numbers are a
snapshot; `js/run-detail.js` was being edited at the time.

No existing test catches a chart that omits a character. `tools/test_profile_filters.py`
counts character columns in two tables only.

## Ranked

| # | Duplicated thing | Copies | Single home | Status |
|---|---|---|---|---|
| 1 | Win/loss/accent colour literals (`#5cba7d`, `#e05c5c`, `#e0c468`) | JS 8/9/16, CSS 18/11 | `--win`, `--loss`, `--warn` in `:root` plus a JS `COLORS` read from them | done: `--win/--loss/--warn` in `dashboard.css`, `COLORS` in `data.js` |
| 2 | Tooltip viewport clamping in run-detail.js (455, 574, 609, 639, 687, 1992); one uses `innerWidth` (includes the scrollbar), the clipped-tooltip bug class | 6 | generalise `clampTooltipPosition` (tooltip.js:40) | done: `viewportSize`, `clampAxis` in `tooltip.js` |
| 3 | Win % rounding/formatting: `toFixed(1)` in charts, `Math.round` in tables | ~35 | `fmtWinPct(w, n)`, `fmtRecord(w, l)` | done: `winPctNum`, `fmtWinPct`, `fmtRecord` in `data.js` |
| 4 | Character colour: indexed by position (`DATA.charColors[i]`), three different fallbacks (`#888`, `#a0a0b8`, `var(--gold)`), `CHAR_COLOR_MAP` depends on load order | many | `charColor(char)` in data.js beside the roster | done: `charColor` in `data.js` |
| 5 | "Phone" defined five ways (CSS 700px/560px, four `matchMedia`/helper copies) | 5 | one `isPhone()` plus a `--bp` constant | done: `isPhone`, `isSmallPhone`, `PHONE_MQ` in `data.js` |
| 6 | Chart chrome colours (`#d2cdea`, `#3f4147`, `#ccc`, `#999`); act charts have no shared legend | 35+ | `CHART_THEME`, `scaleDefaults()` | open |
| 7 | A-level/Dread label built by hand (page-nav.js:290, run-detail.js:222 using `run.asc` not `runAsc`) | 3 | `ascHtml(asc)` beside `ascLabel` | done: `ascHtml` in `data.js` |
| 8 | Title-casing ids (`fmtCharName`, boot.js, item-tips.js, run-detail.js, Python `.title()`) | ~8 | one `titleCaseId`; `.char-label` gets explicit `nowrap` | done: `titleCaseId` in `tooltip.js`, `.char-label` nowrap |
| 9 | Sortable headers (seeds.js vs cards-page.js, different arrows and default direction) | 2 | `makeSortableHeader` | open |
| 10 | About 8 button/pill CSS patterns with no `.btn` base; px sizes below `--fs-xs` | ~8 | `.btn`/`.pill` base, normalise outliers | open |

Also: legend icons use a different lookup (lowercase keys) from `charIconUrl`
(uppercase), touch handling lives in three places (a shared `pointer.js`), and canvas
text sizes can't read the CSS type tokens.

## Test (done)

`tools/test_chart_roster.py`: a Playwright check that every per-character chart has
`datasets.map(label) == DATA.characters.map(fmtCharName)`, run against a fixture with an
unknown sixth character.
