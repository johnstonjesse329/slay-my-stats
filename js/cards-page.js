// =========================================================================
// Cards page
// =========================================================================

let cardsIncludeColorless   = true;
let cardsIncludeOtherChars = false;
let cardsActiveType   = "all";
let cardsActiveRarity = "all";
let cardsNameFilter   = "";
let cardsSortKey      = "pickRate";
let cardsSortDir      = -1; // -1 = descending

(function initCardsFilters() {
  // Colorless checkbox (always relevant, regardless of character selection)
  document.getElementById("cards-include-colorless").addEventListener("change", (e) => {
    cardsIncludeColorless = e.target.checked;
    renderCardsPage();
  });

  // Card name filter
  document.getElementById("cards-name-filter").addEventListener("input", (e) => {
    cardsNameFilter = e.target.value.trim().toLowerCase();
    renderCardsPage();
  });

  // "Include other characters' cards" checkbox (only relevant when one character is selected)
  document.getElementById("cards-include-other-chars").addEventListener("change", (e) => {
    cardsIncludeOtherChars = e.target.checked;
    renderCardsPage();
  });

  // Type buttons
  ["all","attack","skill","power"].forEach(t => {
    document.getElementById(`cards-type-${t}`).addEventListener("click", () => {
      cardsActiveType = t;
      ["all","attack","skill","power"].forEach(x => {
        const btn = document.getElementById(`cards-type-${x}`);
        btn.classList.toggle("active", x === t);
        btn.style.color = x === t ? "#e0c468" : "";
        btn.style.borderColor = x === t ? "#e0c468" : "";
      });
      renderCardsPage();
    });
  });

  // Rarity buttons
  ["all","common","uncommon","rare"].forEach(r => {
    document.getElementById(`cards-rarity-${r}`).addEventListener("click", () => {
      cardsActiveRarity = r;
      ["all","common","uncommon","rare"].forEach(x => {
        const btn = document.getElementById(`cards-rarity-${x}`);
        btn.classList.toggle("active", x === r);
        btn.style.color = x === r ? "#e0c468" : "";
        btn.style.borderColor = x === r ? "#e0c468" : "";
      });
      renderCardsPage();
    });
  });
})();

const RARITY_COLOR = { Common: "#ccc", Uncommon: "#aad4ff", Rare: "#ffd700" };
const TYPE_COLOR   = { Attack: "#e05c5c", Skill: "#5b9bd5", Power: "#c49fe8" };

function aggregateCards() {
  const byCard = {};
  filterRuns().forEach(run => {
    Object.entries(run.cardsOffered || {}).forEach(([id, locs]) => {
      if (!byCard[id]) byCard[id] = { offered: 0, picked: 0, wonWhenPicked: 0, wonWhenSkipped: 0, skippedRuns: 0 };
      const b = byCard[id];
      // Each entry in locs is one time the card appeared in a reward screen in this run.
      // A card can appear multiple times in a run (e.g. offered twice). Count each appearance.
      locs.forEach(loc => {
        b.offered++;
        if (loc.picked) {
          b.picked++;
          if (run.won) b.wonWhenPicked++;
        } else {
          b.skippedRuns++;  // incremented per skip appearance, not per run — use carefully
          if (run.won) b.wonWhenSkipped++;
        }
      });
    });
  });
  return byCard;
}

function renderCardsPage() {
  const raw  = aggregateCards();
  const cardData = DATA.cardData || {};
  const cardChar = DATA.cardChar || {};

  // The "include other characters' cards" checkbox only makes sense when one
  // character is selected (it reveals the rare case of a card from a
  // different character's pool showing up in that character's offers).
  const otherCharGroup = document.getElementById("cards-other-char-group");
  otherCharGroup.style.display = sharedActiveChar === "ALL" ? "none" : "";

  // Build rows, filtering by type/rarity
  const rows = Object.entries(raw).map(([id, b]) => {
    const meta = cardData[id] || {};
    const pool = cardChar[id] || "other";
    return {
      id,
      title:    DATA.cardLabels[id] || id,
      type:     meta.type    || "—",
      rarity:   meta.rarity  || "—",
      pool,
      owner:    pool === "colorless" ? "Colorless" : fmtCharName(pool),
      offered:  b.offered,
      picked:   b.picked,
      pickRate: b.offered ? +(b.picked / b.offered * 100).toFixed(1) : 0,
      skipped:  b.skippedRuns,
      winPicked:  b.picked       ? +(b.wonWhenPicked  / b.picked       * 100).toFixed(1) : null,
      winSkipped: b.skippedRuns  ? +(b.wonWhenSkipped / b.skippedRuns  * 100).toFixed(1) : null,
    };
  }).filter(r => {
    if (r.pool === "colorless" && !cardsIncludeColorless) return false;
    if (sharedActiveChar !== "ALL" && !cardsIncludeOtherChars) {
      if (r.pool !== sharedActiveChar && r.pool !== "colorless") return false;
    }
    if (cardsActiveType   !== "all" && r.type.toLowerCase()   !== cardsActiveType)   return false;
    if (cardsActiveRarity !== "all" && r.rarity.toLowerCase() !== cardsActiveRarity) return false;
    if (cardsNameFilter && !r.title.toLowerCase().includes(cardsNameFilter)) return false;
    return true;
  });

  // Sort
  const STRING_COLS = new Set(["title", "owner", "type", "rarity"]);
  rows.sort((a, b) => {
    const av = a[cardsSortKey], bv = b[cardsSortKey];
    let cmp;
    if (STRING_COLS.has(cardsSortKey)) {
      cmp = String(av ?? "").localeCompare(String(bv ?? ""));
    } else {
      cmp = (av ?? -Infinity) - (bv ?? -Infinity);
    }
    return cardsSortDir * (cmp || a.title.localeCompare(b.title));
  });

  // Visible caption rather than a heading tooltip, which phones never show.
  const scopeLabel = sharedActiveChar === "ALL"
    ? "all characters"
    : fmtCharName(sharedActiveChar);
  const cardsCaption = document.getElementById("cards-caption");
  if (cardsCaption) cardsCaption.textContent =
    `${rows.length} card${rows.length !== 1 ? "s" : ""} offered under the current filters (${scopeLabel}).`;

  // Header
  const cols = [
    { key: "title",      label: "Card",            align: "left",   width: "160px" },
    { key: "owner",      label: "Pool",            align: "left",   width: "100px" },
    { key: "type",       label: "Type",            align: "left",   width: "70px"  },
    { key: "rarity",     label: "Rarity",          align: "left",   width: "90px"  },
    { key: "offered",    label: "Offered",         align: "center", width: "70px"  },
    { key: "pickRate",   label: "Pick Rate",       align: "center", width: "80px"  },
    { key: "winPicked",  label: "Win % if Picked", align: "center", width: "110px" },
    { key: "winSkipped", label: "Win % if Skipped",align: "center", width: "120px" },
  ];

  const thStyle = (col) => `style="text-align:${col.align};cursor:pointer;user-select:none;white-space:nowrap;padding:0.3rem 0.5rem;font-size:0.72rem;text-transform:uppercase;letter-spacing:.05em;width:${col.width};color:${cardsSortKey === col.key ? "#e0c468" : "#bcbcd0"}"`;
  document.getElementById("cards-thead").innerHTML = `<tr>
    ${cols.map(c => `<th ${thStyle(c)} data-sort="${c.key}" tabindex="0">${c.label}${cardsSortKey === c.key ? (cardsSortDir < 0 ? " ▾" : " ▴") : ""}</th>`).join("")}
  </tr>`;

  // Attach sort listeners
  document.getElementById("cards-thead").querySelectorAll("th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      if (cardsSortKey === k) cardsSortDir *= -1;
      else { cardsSortKey = k; cardsSortDir = -1; }
      renderCardsPage();
    });
    bindEnterSpace(th);
  });

  // Body
  // Win rates backed by fewer than 5 samples are rendered faded with a
  // tooltip, so a lucky 1-pick 100% doesn't visually outrank a real signal
  const pct = (v, color, n = null) => {
    if (v == null) return `<span style="color:#8a8aa0">—</span>`;
    if (n != null && n < 5)
      return `<span style="color:${color};opacity:0.45" data-tip="Small sample: ${n} ${n === 1 ? "run" : "runs"}">⚠ ${v}%</span>`;
    return `<span style="color:${color};font-weight:${v >= 50 ? "800" : "400"};${v >= 50 ? "font-size:0.88rem;" : ""}">${v}%</span>`;
  };

  document.getElementById("cards-tbody").innerHTML = rows.map(r => {
    // Same real-card thumbnail + hover tooltip as every other card reference
    // in the app (Personal Bests, deck tiles, node rewards) -- a bare name
    // was the odd one out here. The tooltip itself is wired up below via
    // showFloatingHtmlTooltip rather than the usual .card-tooltip-wrap
    // markup, since this table lives inside a scrolling .pivot-wrap
    // (overflow-y:auto) that would clip an absolutely-positioned popup.
    const src = cardImgSrc(r.id);
    // The thumbnail and the name are one trigger, so hovering, tapping or
    // tabbing to either opens the card.
    const icon = src
      ? `<span style="display:inline-block;vertical-align:middle;margin-right:6px;line-height:0">
          <img loading="lazy" src="${thumbSrc(src)}" alt="" style="width:22px;height:22px;object-fit:contain;border-radius:4px;vertical-align:middle">
        </span>`
      : "";
    return `<tr>
    <td style="padding:0.18rem 0.5rem;font-size:0.83rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><span class="fav-item" data-card-id="${r.id}" tabindex="0" style="cursor:pointer">${icon}${r.title}</span></td>
    <td style="padding:0.18rem 0.5rem;font-size:0.75rem;color:${CHAR_COLOR_MAP[r.owner.toUpperCase()] || "#bcbcd0"}">${r.owner}</td>
    <td style="padding:0.18rem 0.5rem;font-size:0.75rem;color:${TYPE_COLOR[r.type] || "#bcbcd0"}">${r.type}</td>
    <td style="padding:0.18rem 0.5rem;font-size:0.75rem;color:${RARITY_COLOR[r.rarity] || "#bcbcd0"}">${r.rarity}</td>
    <td style="padding:0.18rem 0.5rem;text-align:center;font-size:0.83rem;color:#bcbcd0">${r.offered}</td>
    <td style="padding:0.18rem 0.5rem;text-align:center">${pct(r.pickRate, "#ccc")}</td>
    <td style="padding:0.18rem 0.5rem;text-align:center">${pct(r.winPicked,  "#ccc", r.picked)}</td>
    <td style="padding:0.18rem 0.5rem;text-align:center">${pct(r.winSkipped, "#ccc", r.skipped)}</td>
  </tr>`;
  }).join("");

  document.getElementById("cards-tbody").querySelectorAll(".fav-item[data-card-id]").forEach(el => {
    const show = () => showFloatingHtmlTooltip(el, buildCardTooltip(el.dataset.cardId, 0));
    el.addEventListener("mouseenter", show);
    el.addEventListener("mouseleave", hideFloatingHtmlTooltip);
    // Tap or keyboard: focus shows it; the next tap anywhere blurs it (tooltip.js).
    el.addEventListener("focus", show);
    el.addEventListener("blur", hideFloatingHtmlTooltip);
  });
}

