// -------------------------------------------------------------------------
// Chart creation
// -------------------------------------------------------------------------

// Chart.js defaults its labels to Helvetica/Arial. Every chart on the page is
// a label next to other labels, so inherit the page's own stack (body,
// dashboard.css) instead of rendering the data in a second typeface.
Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';

// Shared y-axis config for win-% charts: cap at 105 for headroom above 100,
// hide the 105 tick label, and force a 100 tick to always exist
const WIN_PCT_Y_AXIS = {
  max: 105,
  ticks: { color: "#bcbcd0", stepSize: 25, callback: v => v <= 100 ? v : null },
  afterBuildTicks: axis => {
    if (!axis.ticks.some(t => t.value === 100))
      axis.ticks.push({ value: 100 });
  },
};

function makeBarChart(id, colors, yLabel, tooltipFn) {
  return new Chart(document.getElementById(id), {
    type: "bar",
    data: {
      labels: DATA.characters.map(fmtCharName),
      datasets: [{
        data:            DATA.characters.map(() => 0),
        backgroundColor: colors,
        borderRadius:    5,
        borderSkipped:   false,
        meta:            [],
      }],
    },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        ...(tooltipFn ? { tooltip: { callbacks: {
          title: ctx => ctx[0].label,
          label: ctx => tooltipFn(ctx.dataset.meta?.[ctx.dataIndex]),
        } } } : {}),
      },
      scales: {
        x: { grid: { color: "#3f4147" }, ticks: { color: "#bcbcd0" } },
        y: {
          grid:        { color: "#3f4147" },
          ticks:       { color: "#bcbcd0" },
          title:       { display: true, text: yLabel, color: "#999" },
          beginAtZero: true,
          ...(yLabel === "Win %" ? WIN_PCT_Y_AXIS : {}),
        },
      },
    },
  });
}

const fmtHrsMin = m => {
  if (m == null) return "—";
  const totalMin = Math.round(m);
  return totalMin >= 60 ? `${Math.floor(totalMin/60)}h ${totalMin%60}m` : `${totalMin}m`;
};
const fmtHrsMinSec = m => {
  if (m == null) return "—";
  const totalSec = Math.round(m * 60);
  const h = Math.floor(totalSec / 3600);
  const min = Math.floor((totalSec % 3600) / 60);
  const sec = totalSec % 60;
  return h > 0 ? `${h}h ${min}m ${sec}s` : `${min}m ${sec}s`;
};

// Single shared pattern for every chart/table tooltip in the dashboard:
// a "Label: value" line per stat, then a "Runs: N" line (collapsed with the
// win/loss record when available) last.
const runsRecord = (n, wins, losses) =>
  wins != null && losses != null ? `Runs: ${n} (${wins}W / ${losses}L)` : `Runs: ${n}`;

const floorChart     = makeBarChart("charFloorChart",     DATA.charColors, "Median Floor",
  s => s ? ` Median floor: ${s.median_floor ?? "—"} (${s.wins}W / ${s.losses}L)` : null);
const timeChart      = makeBarChart("charTimeChart",      DATA.charColors, "Median Minutes",
  s => s ? ` Median time: ${fmtHrsMin(s.median_min)} (${s.wins}W / ${s.losses}L)` : null);
const totalTimeChart = makeBarChart("charTotalTimeChart", DATA.charColors, "Hours",
  s => s ? ` Total time: ${s.total_hrs ?? 0}h (${s.wins}W / ${s.losses}L)` : null);

const _shareLabels = DATA.characters.map(fmtCharName);
const timeShareChart = new Chart(document.getElementById("charTimeShareChart"), {
  type: "doughnut",
  data: {
    labels:   _shareLabels,
    datasets: [{ data: [], backgroundColor: DATA.charColors, borderWidth: 2, borderColor: "#13132a" }],
  },
  options: {
    responsive: true,
    cutout: "60%",
    plugins: {
      legend: { position: "bottom", labels: { color: "#bcbcd0", boxWidth: 12, padding: 8, font: { size: 11 } } },
      tooltip: {
        callbacks: {
          title: ctx => ctx[0].label,
          label: ctx => {
            const s = ctx.dataset.meta?.[ctx.dataIndex];
            const hrs = s ? (s.total_hrs ?? 0) : 0;
            return s
              ? ` ${ctx.parsed.toFixed(1)}% of time played — ${hrs}h (${s.wins}W / ${s.losses}L)`
              : ` ${ctx.parsed.toFixed(1)}% of time played — ${hrs}h`;
          },
        },
      },
    },
  },
});

// Bars side by side: each character's own win % at each ascension. A character
// with no runs at an ascension gets no bar there (null), not a 0% one.
const ascWinChart = new Chart(document.getElementById("ascWinChart"), {
  type: "bar",
  data: {
    labels:   DATA.ascensions,
    datasets: [],
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: "#ccc", boxWidth: 12 } },
      tooltip: {
        callbacks: {
          title: ctx => `Ascension ${ctx[0].label}`,
          label: ctx => {
            const n = ctx.dataset.runCounts?.[ctx.dataIndex] ?? 0;
            const w = ctx.dataset.winCounts?.[ctx.dataIndex] ?? 0;
            return ` ${ctx.dataset.label} — ${ctx.parsed.y}% (${w}W / ${n - w}L)`;
          },
        },
      },
    },
    scales: {
      x: {
        grid:  { display: false },
        ticks: { color: "#bcbcd0" },
        title: { display: true, text: "Ascension", color: "#999" },
      },
      y: {
        grid:        { color: "#3f4147" },
        title:       { display: true, text: "Win %", color: "#999" },
        beginAtZero: true,
        ...WIN_PCT_Y_AXIS,
      },
    },
  },
});

function aggregateAscBarDatasets(filteredRuns) {
  const byCharAsc = {};
  filteredRuns.forEach(run => {
    const bucket = (byCharAsc[run.char] ??= {});
    const b = (bucket[run.asc] ??= { wins: 0, runs: 0 });
    b.runs += 1;
    if (run.won) b.wins += 1;
  });

  return DATA.characters.map((char, i) => {
    const color = DATA.charColors[i];
    const bucket = byCharAsc[char] || {};
    const cells = DATA.ascensions.map(asc => bucket[asc] || { wins: 0, runs: 0 });
    return {
      label: fmtCharName(char),
      data:      cells.map(b => b.runs ? +(b.wins / b.runs * 100).toFixed(1) : null),
      runCounts: cells.map(b => b.runs),
      winCounts: cells.map(b => b.wins),
      backgroundColor: color,
    };
  });
}

function updateAscWinChart(filteredRuns) {
  ascWinChart.data.datasets = aggregateAscBarDatasets(filteredRuns);
  ascWinChart.update();
}

// -------------------------------------------------------------------------
// Win % by month (per character) — dotted vlines mark game version changes
// -------------------------------------------------------------------------

// Bucket key uses local-time year/month per the project's local-time convention
// for all date display/filtering.
function monthKey(ts) {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(key) {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

// Groups filtered runs into chronological month buckets, computing win% per
// character per month, plus which builds were first seen in which month (for
// the version-change vlines). A build only counts as "new this month" if it
// has at least MIN_BUILD_RUNS runs total in the filtered set, to avoid noise
// from a handful of stray runs on a build that was barely played.
function aggregateMonthlyWinPct(filteredRuns) {
  const MIN_BUILD_RUNS = 3;
  const months = new Set();
  const byMonth = {}; // monthKey -> { [char]: {wins, total} }
  const buildTotals = {};
  const buildFirstTs = {}; // build -> earliest run.ts seen (exact date, not month-bucketed)

  filteredRuns.forEach(run => {
    const key = monthKey(run.ts);
    months.add(key);
    if (!byMonth[key]) byMonth[key] = {};
    if (!byMonth[key][run.char]) byMonth[key][run.char] = { wins: 0, total: 0 };
    const b = byMonth[key][run.char];
    b.total++;
    if (run.won) b.wins++;

    buildTotals[run.build] = (buildTotals[run.build] || 0) + 1;
    if (!buildFirstTs[run.build] || run.ts < buildFirstTs[run.build]) buildFirstTs[run.build] = run.ts;
  });

  const sortedMonths = [...months].sort();
  // Group first-seen builds by month index — a month can introduce more than
  // one build (e.g. a quick hotfix), so each index maps to a list, not a single build.
  const buildsByIndex = {};
  Object.entries(buildFirstTs)
    .filter(([build]) => buildTotals[build] >= MIN_BUILD_RUNS)
    .forEach(([build, ts]) => {
      const index = sortedMonths.indexOf(monthKey(ts));
      if (index < 0) return;
      if (!buildsByIndex[index]) buildsByIndex[index] = [];
      buildsByIndex[index].push({ build, ts });
    });
  const buildChangeMonths = Object.entries(buildsByIndex)
    .map(([index, builds]) => ({ index: +index, builds: builds.sort((a, b) => a.ts - b.ts) }));

  return { months: sortedMonths, byMonth, buildChangeMonths };
}

let monthlyWinChart = null;

// Draws dashed vertical lines at the given x-axis indices, one per month a
// new game build first appeared (see aggregateMonthlyWinPct's MIN_BUILD_RUNS
// filtering). Modeled on makeVlinePlugin (Run Detail's HP chart), but keys
// off explicit indices since months don't have a per-point "type" to match.
function buildChangeVlinePlugin(buildChangeMonths) {
  return {
    id: "buildVlines",
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: { top, bottom }, scales: { x } } = chart;
      ctx.save();
      ctx.setLineDash([3, 4]);
      ctx.lineWidth = 1;
      ctx.strokeStyle = "#e0c46899";
      buildChangeMonths.forEach(({ index }) => {
        const px = x.getPixelForValue(index);
        ctx.beginPath();
        ctx.moveTo(px, top);
        ctx.lineTo(px, bottom);
        ctx.stroke();
      });
      ctx.restore();

      // Build version labels, drawn solid (no dash) just above the chart area.
      // Stack upward if a month introduced more than one build.
      ctx.save();
      ctx.font = "11px sans-serif";
      ctx.fillStyle = "#e0c468";
      ctx.textBaseline = "bottom";
      ctx.textAlign = "center";
      buildChangeMonths.forEach(({ index, builds }) => {
        const px = x.getPixelForValue(index);
        builds.forEach((b, i) => {
          // Labels are centered on the vline; a version first seen in the very
          // first or last month sits near a canvas edge, where centering would
          // push half the label off-canvas. Clamp horizontally so it can't clip.
          const half = ctx.measureText(b.build).width / 2;
          const cx = Math.min(Math.max(px, 4 + half), ctx.canvas.width - 4 - half);
          ctx.fillText(b.build, cx, top - 2 - i * 13);
        });
      });
      ctx.restore();
    },
  };
}

function updateMonthlyWinChart(filteredRuns) {
  const { months, byMonth, buildChangeMonths } = aggregateMonthlyWinPct(filteredRuns);
  // The version labels are stacked upward one per build (13px apart) above the
  // plot area, so a month that introduced many builds needs that much headroom
  // or the stack clips off the top of the chart. Reserve padding for the
  // tallest stack rather than a fixed 16px that only fits one or two labels.
  const maxBuildStack = buildChangeMonths.reduce((m, g) => Math.max(m, g.builds.length), 0);

  const datasets = DATA.characters.map((char, i) => {
    const color = DATA.charColors[i];
    const data = months.map(m => {
      const b = (byMonth[m] || {})[char];
      return b && b.total > 0 ? +(b.wins / b.total * 100).toFixed(1) : null;
    });
    const counts = months.map(m => (byMonth[m] || {})[char]?.total ?? 0);
    const wins   = months.map(m => (byMonth[m] || {})[char]?.wins ?? 0);
    return {
      label: fmtCharName(char),
      data, counts, wins,
      borderColor: color,
      backgroundColor: color,
      borderWidth: 2,
      pointRadius: 3,
      tension: 0.3,
      fill: false,
      spanGaps: true,
    };
  });

  if (monthlyWinChart) { monthlyWinChart.destroy(); monthlyWinChart = null; }

  const ctx = document.getElementById("monthlyWinChart").getContext("2d");
  monthlyWinChart = new Chart(ctx, {
    type: "line",
    data: { labels: months.map(monthLabel), datasets },
    plugins: [buildChangeVlinePlugin(buildChangeMonths)],
    options: {
      responsive: true, maintainAspectRatio: false,
      layout: { padding: { top: 16 + (maxBuildStack - 1) * 13 } },
      interaction: { mode: "index", intersect: false },
      plugins: {
        // Chart.js's own top-of-canvas legend row sits directly in the space
        // the build-version labels above draw into -- layout.padding.top
        // only reserves room above the legend, not between it and
        // chartArea.top, so the two collide. Bottom, below the x-axis,
        // doesn't compete with them.
        legend: { position: "bottom", labels: { color: "#ccc", boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: ctx => {
              if (ctx.raw == null) return null;
              const n = ctx.dataset.counts?.[ctx.dataIndex] ?? 0;
              const w = ctx.dataset.wins?.[ctx.dataIndex] ?? 0;
              return ` ${ctx.dataset.label} — ${ctx.formattedValue}% (${w}W / ${n - w}L)`;
            },
          },
        },
      },
      scales: {
        x: {
          grid:  { color: "#3f4147" },
          ticks: { color: "#bcbcd0" },
        },
        y: {
          grid:        { color: "#3f4147" },
          title:       { display: true, text: "Win %", color: "#999" },
          beginAtZero: true,
          max:         100,
          ticks:       { color: "#bcbcd0", stepSize: 25 },
        },
      },
    },
  });
}

// -------------------------------------------------------------------------
// Rest site win % line charts — one per act, Heal vs Smith, all chars combined
// -------------------------------------------------------------------------

const REST_WIN_X = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const REST_CHOICE_COLORS = { HEAL: "#9ecfff", SMITH: "#7ec8a0" };

function makeRestWinChart(id) {
  return new Chart(document.getElementById(id), {
    type: "line",
    data: { labels: REST_WIN_X, datasets: [] },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: "#ccc", boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: items => `${items[0].label} times chosen`,
            label: ctx => {
              if (ctx.raw == null) return null;
              const n = ctx.dataset.counts?.[ctx.dataIndex] ?? 0;
              const w = ctx.dataset.wins?.[ctx.dataIndex] ?? 0;
              return ` ${ctx.dataset.label} — ${ctx.raw.toFixed(0)}% (${w}W / ${n - w}L)`;
            },
            afterLabel: ctx => {
              if (ctx.raw == null) return [];
              const chars = ctx.dataset.chars?.[ctx.dataIndex] ?? {};
              return Object.entries(chars)
                .sort((a, b) => b[1].total - a[1].total)
                .map(([char, s]) => {
                  const pct = s.total > 0 ? Math.round(s.wins / s.total * 100) : 0;
                  const label = fmtCharName(char);
                  return `   ${label} — win rate: ${pct}% (${s.wins}W / ${s.total - s.wins}L)`;
                });
            },
          },
        },
      },
      scales: {
        x: {
          grid: { color: "#3f4147" }, ticks: { color: "#bcbcd0" },
          title: { display: true, text: "Times chosen across full run", color: "#999" },
        },
        y: {
          grid: { color: "#3f4147" },
          title: { display: true, text: "Win %", color: "#999" },
          beginAtZero: true, min: 0,
          ...WIN_PCT_Y_AXIS,
        },
      },
    },
  });
}

const restWinChartAll = makeRestWinChart("restWinChartAll");

function aggregateRestWinRates(filteredRuns) {
  // freq[act][choice][count] = { wins, total }
  const freq = {};
  [...REST_ACTS, "FULL"].forEach(act => {
    freq[act] = {};
    REST_CHOICES.forEach(ch => { freq[act][ch] = {}; });
  });

  filteredRuns.forEach(run => {
    const rc = run.restChoices || {};
    const reachedAct3 = rc["3"] !== undefined;

    REST_ACTS.forEach(act => {
      const actChoices = rc[String(act)];
      if (actChoices === undefined) return;
      REST_CHOICES.forEach(choice => {
        const count = actChoices[choice] || 0;
        const b = freq[act][choice];
        if (!b[count]) b[count] = { wins: 0, total: 0, chars: {} };
        b[count].total += 1;
        if (run.won) b[count].wins += 1;
        const c = b[count].chars;
        if (!c[run.char]) c[run.char] = { wins: 0, total: 0 };
        c[run.char].total += 1;
        if (run.won) c[run.char].wins += 1;
      });
    });

    if (reachedAct3) {
      REST_CHOICES.forEach(choice => {
        const totalCount = REST_ACTS.reduce((s, act) => s + ((rc[String(act)] || {})[choice] || 0), 0);
        const b = freq["FULL"][choice];
        if (!b[totalCount]) b[totalCount] = { wins: 0, total: 0, chars: {} };
        b[totalCount].total += 1;
        if (run.won) b[totalCount].wins += 1;
        const c = b[totalCount].chars;
        if (!c[run.char]) c[run.char] = { wins: 0, total: 0 };
        c[run.char].total += 1;
        if (run.won) c[run.char].wins += 1;
      });
    }
  });

  // Convert to arrays aligned to REST_WIN_X — null where no runs
  const result = {};
  [...REST_ACTS, "FULL"].forEach(act => {
    result[act] = {};
    REST_CHOICES.forEach(choice => {
      result[act][choice] = {
        values: REST_WIN_X.map(x => {
          const b = freq[act][choice][x];
          return (b && b.total >= 1) ? +(b.wins / b.total * 100).toFixed(1) : null;
        }),
        counts: REST_WIN_X.map(x => (freq[act][choice][x] || {}).total || 0),
        wins:   REST_WIN_X.map(x => (freq[act][choice][x] || {}).wins  || 0),
        chars:  REST_WIN_X.map(x => (freq[act][choice][x] || {}).chars  || {}),
      };
    });
  });

  return result;
}

function updateRestWinCharts(filteredRuns) {
  const rates = aggregateRestWinRates(filteredRuns);
  const datasets = REST_CHOICES.map(choice => ({
    label:                REST_CHOICE_LABELS[choice],
    data:                 rates["FULL"][choice].values,
    counts:               rates["FULL"][choice].counts,
    wins:                 rates["FULL"][choice].wins,
    chars:                rates["FULL"][choice].chars,
    borderColor:          REST_CHOICE_COLORS[choice],
    backgroundColor:      REST_CHOICE_COLORS[choice] + "22",
    borderWidth:          2,
    pointRadius:          4,
    pointBackgroundColor: REST_CHOICE_COLORS[choice],
    tension:              0.3,
    fill:                 false,
    spanGaps:             true,
  }));
  restWinChartAll.data.labels   = REST_WIN_X;
  restWinChartAll.data.datasets = datasets;
  restWinChartAll.update();
}

// -------------------------------------------------------------------------
// Elite death/survival rate by total elites fought so far in the run —
// bar charts
//
// The x-axis is CUMULATIVE across the whole run, not reset to 1 at the
// start of each act — Act 3's first elite isn't a fresh "1st elite," it
// comes after surviving everything in Acts 1 and 2, so it belongs at
// whatever total elite count the run has actually reached by then
// (commonly 4-6, sometimes higher). Resetting per act made an Act 3 elite
// look like the same kind of moment as an Act 1 elite, which understates
// how far into the run — and how much risk has already compounded — that
// fight actually represents.
//
// The death-rate chart is per-fight risk: of runs that reached this total
// elite count, what % died on that specific fight (not later). It trends
// downward as the total climbs, because reaching a higher total always
// implies surviving everything before it — that's real, not a bug.
//
// The win-rate chart is a DIFFERENT question: of runs that fought exactly
// N total elites (by the run's end), what % won the whole run? This is
// correlational, not causal — strong runs naturally fight more elites, so
// it will trend up regardless of whether taking more elites helps — but
// it's the number the user actually wants here (wins vs. failures by
// elites taken), not the per-fight rate above.
//
// Ascension is a second, separate confound (A8 gives enemies more HP, A9
// more damage) that used to be handled here with a hardcoded A0-7/A8+
// split. The page's shared ascension filter (sharedActiveAscs) now does
// that job for every chart on Overview, these included, so the split was
// redundant — removed in favor of the page-level filter.
// -------------------------------------------------------------------------

const ACT_COLORS = { 1: "#9ecfff", 2: "#e8a930", 3: "#e05c5c" };

// Upper bound derived from the actual data (not hardcoded) so a future run
// that fights more elites than any run so far isn't silently folded into
// the top bucket. Recomputed against DATA.runsData (not the live filtered
// set) purely to size the two charts' shared x-axis once at load; the
// bars themselves are populated per the active filter in updateEliteActCharts.
const ELITE_TOTAL_X = Array.from(
  { length: Math.max(0, ...DATA.runsData.map(run => (run.timeline || []).filter(n => n.type === "elite").length)) },
  (_, i) => i + 1
);

const eliteOrdinalTooltipTitle = items =>
  `${items[0].label}${{1:"st",2:"nd",3:"rd"}[items[0].label] || "th"} elite of the run`;
const eliteTotalTooltipTitle = items => `${items[0].label} elites fought this run`;

// Shared chart builder. `datasetSpecs` is an array of {label, color} — one
// per act for the death-rate chart, or a single neutral series for the
// win-rate chart (which is a whole-run outcome, not an act-specific one,
// so per-act coloring wouldn't mean anything there).
function makeEliteRateChart(id, xLabel, yLabel, xVals, datasetSpecs, tooltipTitleFn, labelFn) {
  return new Chart(document.getElementById(id), {
    type: "bar",
    data: {
      labels: xVals,
      // A dataset spec can opt into `type: "line"` (with matching line
      // styling) to overlay a trend on top of the bar series sharing the
      // same chart — Chart.js supports mixed bar+line datasets natively.
      datasets: datasetSpecs.map(spec => spec.type === "line" ? {
        type: "line", label: spec.label, data: [],
        borderColor: spec.color + "aa", backgroundColor: spec.color,
        borderWidth: 2, borderDash: [5, 4],
        pointRadius: 3, pointHoverRadius: 5, pointBackgroundColor: spec.color + "cc",
        tension: 0.2, fill: false, order: 0,
      } : {
        label: spec.label, data: [],
        backgroundColor: spec.color, borderRadius: 4, borderSkipped: false, order: 1,
      }),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      // "index"+intersect:false makes the whole x-axis column hoverable,
      // not just the filled pixels of a bar — needed because a genuine 0%
      // bar renders at (or near) zero height, which is otherwise an
      // unhoverable target no matter how it's sized. Removes the need for
      // a fake non-zero stand-in value tuned to survive different charts'
      // y-axis scales.
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: datasetSpecs.length > 1, labels: { color: "#ccc", boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: tooltipTitleFn,
            label: ctx => {
              const trueVal = ctx.dataset.trueData?.[ctx.dataIndex];
              if (trueVal == null) return null;
              const n = ctx.dataset.counts?.[ctx.dataIndex] ?? 0;
              const w = ctx.dataset.wins?.[ctx.dataIndex] ?? 0;
              return labelFn(ctx.dataset.label, trueVal, n, w);
            },
          },
        },
      },
      scales: {
        x: {
          grid: { color: "#3f4147" }, ticks: { color: "#bcbcd0" },
          title: { display: true, text: xLabel, color: "#999" },
        },
        y: {
          grid: { color: "#3f4147" }, ticks: { color: "#bcbcd0" },
          title: { display: true, text: yLabel, color: "#999" },
          beginAtZero: true,
        },
      },
    },
  });
}

const eliteDeathRateChart = makeEliteRateChart(
  "eliteDeathRateChart", "Total elites fought so far this run", "Death Rate %", ELITE_TOTAL_X,
  [
    ...[1, 2, 3].map(act => ({ label: `Act ${act}`, color: ACT_COLORS[act] })),
    { label: "Combined", color: "#e0e0e0", type: "line" },
  ],
  eliteOrdinalTooltipTitle,
  (label, trueVal, n, w) => ` ${label}: ${trueVal.toFixed(0)}% died (${w}W / ${n - w}L)`
);

const eliteWinRateChart = makeEliteRateChart(
  "eliteWinRateChart", "Total elites fought this run", "Overall Win %", ELITE_TOTAL_X,
  [{ label: "All acts", color: "#7ec8a0" }],
  eliteTotalTooltipTitle,
  (label, trueVal, n, w) => ` ${trueVal.toFixed(0)}% won the run (${w}W / ${n - w}L)`
);

const FIGHT_TYPES = new Set(["monster", "elite", "boss"]);

// "Died" from this elite means either dying on the elite itself, or
// surviving it but dying on the very next fight afterward (skipping over
// rest sites/shops/events/treasure in between) — overextension can show up
// as HP too low to survive the fight right after, not just the elite
// itself. Denominator is still every run that reached this elite.
//
// Bucketed by TOTAL elites fought so far in the run (not reset per act) —
// Act 3's first elite isn't a fresh "1st elite," it comes after surviving
// everything in Acts 1 and 2, so it belongs at whatever total elite count
// the run has actually reached by then. Each bucket is also tagged with
// which act that elite belonged to, so it can still be colored/split by
// act for comparison, while the x-position itself already encodes how
// many elites came before it — no separate low/high split needed.
//
// bucket[act][totalSoFar] = { reachedThisElite, diedOnThisElite }
function aggregateEliteOrdinalDeaths(filteredRuns) {
  const bucket = {};
  REST_ACTS.forEach(act => { bucket[act] = {}; });

  filteredRuns.forEach(run => {
    const tl = run.timeline || [];
    let totalSoFar = 0;
    tl.forEach((node, idx) => {
      if (node.type !== "elite") return;
      totalSoFar += 1;
      const actBucket = bucket[node.act];
      const b = actBucket[totalSoFar] || (actBucket[totalSoFar] = { reachedThisElite: 0, diedOnThisElite: 0 });
      b.reachedThisElite += 1;

      if (node.hpAfter <= 0) {
        b.diedOnThisElite += 1;
      } else {
        const nextFight = tl.slice(idx + 1).find(n => FIGHT_TYPES.has(n.type));
        if (nextFight && nextFight.hpAfter <= 0) b.diedOnThisElite += 1;
      }
    });
  });

  return bucket;
}

// winBucket[totalElites] = { overallWins, overallTotal } — of runs that
// fought exactly totalElites elites across the WHOLE run (final count,
// not per-act), how many won vs. didn't. Not split by act — this is a
// whole-run outcome, so per-act coloring wouldn't mean anything here.
function aggregateElitesPerRun(filteredRuns) {
  const bucket = {};
  filteredRuns.forEach(run => {
    const total = (run.timeline || []).filter(n => n.type === "elite").length;
    const b = bucket[total] || (bucket[total] = { overallWins: 0, overallTotal: 0 });
    b.overallTotal += 1;
    if (run.won) b.overallWins += 1;
  });
  return bucket;
}

function updateEliteActCharts(filteredRuns) {
  const deathBucket = aggregateEliteOrdinalDeaths(filteredRuns);
  const winBucket    = aggregateElitesPerRun(filteredRuns);

  [1, 2, 3].forEach((act, i) => {
    const ds = eliteDeathRateChart.data.datasets[i];
    const actBucket = deathBucket[act];
    ds.trueData = ELITE_TOTAL_X.map(n => {
      const b = actBucket[n];
      return b && b.reachedThisElite >= 1 ? +(b.diedOnThisElite / b.reachedThisElite * 100).toFixed(1) : null;
    });
    ds.data = ds.trueData;
    ds.counts = ELITE_TOTAL_X.map(n => (actBucket[n] || {}).reachedThisElite || 0);
    ds.wins   = ELITE_TOTAL_X.map(n => {
      const b = actBucket[n];
      return b ? b.reachedThisElite - b.diedOnThisElite : 0;
    });
    ds.backgroundColor = ACT_COLORS[act];
  });

  // Combined trendline: same death-rate metric as the bars, pooled across
  // all 3 acts at each x-position instead of split by act — overlaid on
  // top so the overall shape (does risk climb or fall as elites taken
  // increases) is visible at a glance instead of needing to eyeball 3
  // separate bar heights per x-position.
  {
    const ds = eliteDeathRateChart.data.datasets[3];
    const reachedByX = ELITE_TOTAL_X.map(n =>
      [1, 2, 3].reduce((sum, act) => sum + ((deathBucket[act][n] || {}).reachedThisElite || 0), 0));
    const diedByX = ELITE_TOTAL_X.map(n =>
      [1, 2, 3].reduce((sum, act) => sum + ((deathBucket[act][n] || {}).diedOnThisElite || 0), 0));
    ds.trueData = reachedByX.map((reached, i) => reached >= 1 ? +(diedByX[i] / reached * 100).toFixed(1) : null);
    ds.data = ds.trueData;
    ds.counts = reachedByX;
    ds.wins   = reachedByX.map((reached, i) => reached - diedByX[i]);
  }
  eliteDeathRateChart.update();

  {
    const ds = eliteWinRateChart.data.datasets[0];
    ds.trueData = ELITE_TOTAL_X.map(n => {
      const b = winBucket[n];
      return b && b.overallTotal >= 1 ? +(b.overallWins / b.overallTotal * 100).toFixed(1) : null;
    });
    ds.data = ds.trueData;
    ds.counts = ELITE_TOTAL_X.map(n => (winBucket[n] || {}).overallTotal || 0);
    ds.wins   = ELITE_TOTAL_X.map(n => (winBucket[n] || {}).overallWins || 0);
    ds.backgroundColor = "#7ec8a0";
  }
  eliteWinRateChart.update();
}


