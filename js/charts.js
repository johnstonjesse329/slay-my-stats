// -------------------------------------------------------------------------
// Chart creation
// -------------------------------------------------------------------------

// Chart.js defaults its labels to Helvetica/Arial. Every chart on the page is
// a label next to other labels, so inherit the page's own stack (body,
// dashboard.css) instead of rendering the data in a second typeface.
Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';
// Canvas text can't read dashboard.css's type scale, so this is --fs-sm in px.
Chart.defaults.font.size = 14;

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
      ctx.font = "13px sans-serif";
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
// Act Boss Defeated, by Rest Site Choices: a Heal chart and a Smith chart,
// one line per act
//
// A run is on an act's line once it reaches that act's boss. Every rest site
// of the act comes before the boss, so the act's count is complete, and a run
// that died earlier in the act is on none of the lines. A point is the share
// of those runs that defeated the boss -- in Act 3 every boss there (two at
// Ascension 10), which is winning the run. Only Heal and Smith are drawn: the
// relic-granted options (Dig, Lift, Hatch, ...) are ~3% of rest picks.
// -------------------------------------------------------------------------

const REST_ACTS = [1, 2, 3];
const REST_CHOICES = ["HEAL", "SMITH"];
const ACT_COLORS = { 1: "#9ecfff", 2: "#e8a930", 3: "#e05c5c" };

// Sized from the data, like ELITE_TOTAL_X below and for the same reason.
const REST_ACT_X = Array.from(
  { length: 1 + Math.max(0, ...DATA.runsData.flatMap(run =>
      Object.values(run.restChoices || {}).flatMap(c => REST_CHOICES.map(ch => c[ch] || 0)))) },
  (_, i) => i
);

function makeRestActChart(id) {
  return new Chart(document.getElementById(id), {
    type: "line",
    data: {
      labels: REST_ACT_X,
      datasets: REST_ACTS.map(act => ({
        label: `Act ${act}`, data: [],
        borderColor: ACT_COLORS[act], backgroundColor: ACT_COLORS[act],
        borderWidth: 2.5, pointRadius: 4, pointHoverRadius: 6, tension: 0.25,
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: "#ccc", boxWidth: 12 } },
        tooltip: {
          callbacks: {
            title: items => `${items[0].label} times chosen`,
            label: ctx => {
              if (ctx.parsed.y == null) return null;
              const n = ctx.dataset.counts[ctx.dataIndex];
              const w = ctx.dataset.beat[ctx.dataIndex];
              return ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(0)}% defeated the boss (${w}W / ${n - w}L)`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false }, ticks: { color: "#bcbcd0" },
          title: { display: true, text: "Times chosen", color: "#999" },
        },
        y: {
          grid: { color: "#3f4147" },
          title: { display: true, text: "Act boss defeated %", color: "#999" },
          beginAtZero: true,
          ...WIN_PCT_Y_AXIS,
        },
      },
    },
  });
}

const restActCharts = {
  HEAL:  makeRestActChart("restHealChart"),
  SMITH: makeRestActChart("restSmithChart"),
};

// bucket[choice][act][timesChosen] = { runs, beat }: the runs that reached
// that act's boss having made that choice that many times in the act, and
// how many of them defeated the boss. A run past an act's boss has nodes in
// a later act; the last act's boss is defeated only by winning.
function aggregateRestActs(filteredRuns) {
  const bucket = {};
  REST_CHOICES.forEach(ch => {
    bucket[ch] = {};
    REST_ACTS.forEach(act => { bucket[ch][act] = {}; });
  });

  filteredRuns.forEach(run => {
    const timeline = run.timeline || [];
    const lastAct = timeline.length ? timeline[timeline.length - 1].act : 0;
    const bossActs = new Set(timeline.filter(n => n.type === "boss").map(n => n.act));
    REST_ACTS.forEach(act => {
      if (!bossActs.has(act)) return;
      const defeated = run.won || act < lastAct;
      const chosen = (run.restChoices || {})[act] || {};
      REST_CHOICES.forEach(ch => {
        const b = (bucket[ch][act][chosen[ch] || 0] ??= { runs: 0, beat: 0 });
        b.runs += 1;
        if (defeated) b.beat += 1;
      });
    });
  });

  return bucket;
}

function updateRestActCharts(filteredRuns) {
  const bucket = aggregateRestActs(filteredRuns);
  REST_CHOICES.forEach(ch => {
    const chart = restActCharts[ch];
    REST_ACTS.forEach((act, i) => {
      const ds = chart.data.datasets[i];
      const cells = REST_ACT_X.map(n => bucket[ch][act][n] || { runs: 0, beat: 0 });
      // Same floor as the elites chart: one or two runs would put a 0% or
      // 100% dot on the line.
      ds.data   = cells.map(b => b.runs >= ELITE_CHECKPOINT_MIN_RUNS ? +(b.beat / b.runs * 100).toFixed(1) : null);
      ds.counts = cells.map(b => b.runs);
      ds.beat   = cells.map(b => b.beat);
    });
    chart.update();
  });
}

// -------------------------------------------------------------------------
// Elites and how the run ended: two charts
//
// Both count elites across the WHOLE run, not reset per act: an Act 3 elite
// comes after everything in Acts 1 and 2, and what the earlier ones gave
// (relics, cards, gold) is still with the run.
//
// "Win % by Elites Defeated" asks where a run has taken
// enough elites to be safer. A run counts once per act boss it reached, at
// the number of elites it had beaten by then, so along one line every run
// is at the same point and only the elite total differs. Counting by "beat
// its Nth elite" alone would mix that with simply being further into the
// run. It is still correlational: a strong run is the one that can afford
// another elite.
//
// The win-rate chart is a DIFFERENT question: of runs that fought exactly
// N total elites (by the run's end), what % won the whole run? Also
// correlational, for the same reason.
//
// Ascension is a second, separate confound (A8 gives enemies more HP, A9
// more damage) that used to be handled here with a hardcoded A0-7/A8+
// split. The page's shared ascension filter (sharedActiveAscs) now does
// that job for every chart on Overview, these included, so the split was
// redundant — removed in favor of the page-level filter.
// -------------------------------------------------------------------------

// Upper bound derived from the actual data (not hardcoded) so a future run
// that fights more elites than any run so far isn't silently folded into
// the top bucket. Recomputed against DATA.runsData (not the live filtered
// set) purely to size the chart's x-axis once at load; the chart itself is
// populated per the active filter in updateEliteActCharts.
const ELITE_TOTAL_X = Array.from(
  { length: Math.max(0, ...DATA.runsData.map(run => (run.timeline || []).filter(n => n.type === "elite").length)) },
  (_, i) => i + 1
);

// A point is only drawn with at least this many runs behind it: one or two
// runs would put a 0% or 100% dot on the line.
const ELITE_CHECKPOINT_MIN_RUNS = 10;
// A run can reach an act boss having beaten no elites at all.
const ELITE_CHECKPOINT_X = [0, ...ELITE_TOTAL_X];

const eliteCheckpointChart = new Chart(document.getElementById("eliteCheckpointChart"), {
  type: "line",
  data: {
    labels: ELITE_CHECKPOINT_X,
    datasets: Object.keys(ACT_COLORS).map(act => ({
      label: `At the Act ${act} boss`, data: [],
      borderColor: ACT_COLORS[act], backgroundColor: ACT_COLORS[act],
      borderWidth: 2.5, pointRadius: 4, pointHoverRadius: 6, tension: 0.25,
    })),
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { labels: { color: "#ccc", boxWidth: 12 } },
      tooltip: {
        callbacks: {
          title: items => `${items[0].label} elites defeated so far`,
          label: ctx => {
            if (ctx.parsed.y == null) return null;
            const n = ctx.dataset.counts[ctx.dataIndex];
            const w = ctx.dataset.wins[ctx.dataIndex];
            return ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(0)}% won the run (${w}W / ${n - w}L)`;
          },
        },
      },
    },
    scales: {
      x: {
        grid: { display: false }, ticks: { color: "#bcbcd0" },
        title: { display: true, text: "Elites defeated", color: "#999" },
      },
      y: {
        grid: { color: "#3f4147" },
        title: { display: true, text: "Win %", color: "#999" },
        beginAtZero: true,
        ...WIN_PCT_Y_AXIS,
      },
    },
  },
});

// bucket[act][elitesBeaten] = { runs, wins }: the runs that reached that
// act's boss having beaten that many elites so far, and how many of them
// went on to win. Only an act's first boss counts (Ascension 10 has two in
// Act 3), so a run is in each act's line at most once.
function aggregateEliteCheckpoints(filteredRuns) {
  const bucket = {};
  REST_ACTS.forEach(act => { bucket[act] = {}; });

  filteredRuns.forEach(run => {
    let beaten = 0;
    const actsSeen = new Set();
    (run.timeline || []).forEach(node => {
      if (node.type === "elite") {
        if (node.hpAfter > 0) beaten += 1;
      } else if (node.type === "boss" && bucket[node.act] && !actsSeen.has(node.act)) {
        actsSeen.add(node.act);
        const b = (bucket[node.act][beaten] ??= { runs: 0, wins: 0 });
        b.runs += 1;
        if (run.won) b.wins += 1;
      }
    });
  });

  return bucket;
}

function updateEliteActCharts(filteredRuns) {
  const checkpoints = aggregateEliteCheckpoints(filteredRuns);

  REST_ACTS.forEach((act, i) => {
    const ds = eliteCheckpointChart.data.datasets[i];
    const cells = ELITE_CHECKPOINT_X.map(n => checkpoints[act][n] || { runs: 0, wins: 0 });
    ds.data   = cells.map(b => b.runs >= ELITE_CHECKPOINT_MIN_RUNS ? +(b.wins / b.runs * 100).toFixed(1) : null);
    ds.counts = cells.map(b => b.runs);
    ds.wins   = cells.map(b => b.wins);
  });
  eliteCheckpointChart.update();

  // A run that never got to a boss is on none of the lines; say how many.
  const missing = filteredRuns.filter(run => !(run.timeline || []).some(n => n.type === "boss")).length;
  document.getElementById("elite-checkpoint-missing").textContent = missing
    ? `${missing} run${missing !== 1 ? "s" : ""} ended before the Act 1 boss and ${missing !== 1 ? "aren't" : "isn't"} shown.` : "";
}


