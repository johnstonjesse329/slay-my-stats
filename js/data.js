/*
  All the JavaScript that powers the interactive dashboard.

  DATA is provided as a global before this bundle runs: for the local build,
  run.py's build_html() emits an inline `const DATA = ...;` ahead of the
  concatenated js/*.js; on the live site, boot.js fetches /catalog.json and
  the user's data blob, builds `window.DATA` from them, then loads /app.js.

  Shape of DATA:
    characters      : ["DEFECT", "IRONCLAD", ...]
    charColors      : ["#5b9bd5", "#e05c5c", ...]
    ascensions      : [0, 1, 2, ...]
    runsData        : [{char, asc, won, floor, mins, cards, relics, ts, mp, mode}, ...]
*/

Chart.defaults.color = "#bcbcd0";
Chart.defaults.scale.ticks.color = "#bcbcd0";
Chart.defaults.scales.category.ticks.color = "#bcbcd0";

