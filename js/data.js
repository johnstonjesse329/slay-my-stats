/*
  All the JavaScript that powers the interactive dashboard.

  DATA is embedded by run.py at build time: build_html() substitutes the
  const DATA declaration below with the actual JSON before writing the
  output HTML file.

  Shape of DATA:
    characters      : ["DEFECT", "IRONCLAD", ...]
    charColors      : ["#5b9bd5", "#e05c5c", ...]
    ascensions      : [0, 1, 2, ...]
    runsData        : [{char, asc, won, floor, mins, cards, relics, ts, mp, mode}, ...]
*/
const DATA = {chart_data};

Chart.defaults.color = "#bcbcd0";
Chart.defaults.scale.ticks.color = "#bcbcd0";
Chart.defaults.scales.category.ticks.color = "#bcbcd0";

