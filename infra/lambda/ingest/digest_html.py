"""
The morning digest as an HTML email: the same numbers the plain-text part carries
(handler.build_digest, feedback.report_data, views.format_views), laid out as tables.

Mail clients ignore <style> blocks and most CSS, so everything is inline styles on
nested tables, which every client draws the same. Only the site owner gets it.
"""
from html import escape
from datetime import datetime, timezone

INK, MUTED, LINK, RULE, SOFT_RULE = "#222", "#888", "#1a5fb4", "#ddd", "#eee"
WARN = "#b35c00"
BADGES = {"new": ("#e3f1e3", "#2a7a2a"), "Bug": ("#fbe3e3", "#a12a2a"),
          "Feature request": ("#e3ecfb", "#2a4fa1"), "Improvement idea": ("#f1ecdf", "#7a6630"),
          "Kudos": ("#efe3fb", "#6a2aa1")}
SHORT = {"Feature request": "Feature", "Improvement idea": "Idea"}
# Held IDs are TYPE.MODNAME-ID for modded content, TYPE.ID for anything else.
HELD_SHOWN = 15
NOTE_CHARS = 140


def _n(v) -> str:
    return f"{v:,}"


def _a(url: str, text: str) -> str:
    return f'<a href="{escape(url)}" style="color:{LINK};text-decoration:none">{escape(text)}</a>'


def _badge(label: str) -> str:
    bg, fg = BADGES.get(label, ("#eee", "#555"))
    return (f'<span style="background:{bg};color:{fg};padding:1px 6px;border-radius:8px;'
            f'font-size:10px;white-space:nowrap">{escape(SHORT.get(label, label))}</span>')


def _table(head, rows, right=(), size=13) -> str:
    """A ruled table. `head` names the columns, `rows` are lists of cell HTML (already
    escaped), `right` the column numbers to right-align (numbers)."""
    def cell(tag, i, body, rule, extra=""):
        align = "right" if i in right else "left"
        return (f'<{tag} style="padding:5px 6px;border-bottom:1px solid {rule};text-align:{align};'
                f'vertical-align:top{extra}">{body}</{tag}>')
    th = "".join(cell("th", i, escape(h), RULE, f";color:{MUTED};font-size:11px;font-weight:600")
                 for i, h in enumerate(head))
    trs = "".join("<tr>" + "".join(cell("td", i, c, SOFT_RULE) for i, c in enumerate(r)) + "</tr>"
                  for r in rows)
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'font-size:{size}px">{"<tr>" + th + "</tr>" if head else ""}{trs}</table>')


def _section(title: str, sub: str = "") -> str:
    sub = f'<div style="font-size:12px;color:{MUTED};margin-top:2px">{sub}</div>' if sub else ""
    return (f'<tr><td style="padding:22px 24px 6px"><div style="font-size:16px;font-weight:600">'
            f'{title}</div>{sub}</td></tr>')


def _block(html: str, bottom: int = 0) -> str:
    return f'<tr><td style="padding:0 24px {bottom}px">{html}</td></tr>'


def _tiles(tiles) -> str:
    cells = []
    for label, value, note, color in tiles:
        note = f' <span style="font-size:12px;font-weight:400;color:{MUTED}">{escape(note)}</span>' if note else ""
        cells.append(f'<td width="{100 // len(tiles)}%" style="padding:8px 10px;background:#f7f5f0;'
                     f'border-radius:6px;vertical-align:top"><div style="font-size:11px;color:{MUTED}">'
                     f'{escape(label)}</div><div style="font-size:20px;font-weight:600;color:{color}">'
                     f'{escape(value)}{note}</div></td>')
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            + '<td width="8"></td>'.join(cells) + "</tr></table>")


def held_groups(ids: list[str]) -> list[tuple[str, str]]:
    """Held IDs (most held first) grouped by the mod in their name, as (source, IDs) rows:
    a mod with two or more IDs gets its own row with the prefix dropped from each; mods
    named once share "Other mods"; IDs naming no mod (a newer patch) go under "No mod
    prefix". Each row keeps the order of its first ID."""
    by_mod = {}  # insertion order: each mod where its first ID came
    for full in ids:
        name = full.split(".", 1)[-1]
        mod, _, rest = name.partition("-") if "-" in name else ("", "", name)
        by_mod.setdefault(mod, []).append((rest, name))
    rows, others = [], []
    for mod in by_mod:
        if mod and len(by_mod[mod]) == 1:
            others.append(by_mod[mod][0][1])
        elif mod:
            rows.append((mod, ", ".join(r for r, _ in by_mod[mod])))
    if others:
        rows.append(("Other mods", ", ".join(others)))
    if "" in by_mod:
        rows.append(("No mod prefix", ", ".join(r for r, _ in by_mod[""])))
    return rows


def _uploads(up: dict, domain: str) -> str:
    out = []
    if up["players"]:
        rows = []
        for p in up["players"]:
            name = _a(f"https://{domain}/u/{p['slug']}", p["name"]) + (" " + _badge("new") if p["new"] else "")
            held = (f'<span style="color:{WARN}">{_n(p["held"])}</span>' if p["held"]
                    else f'<span style="color:#bbb">–</span>')
            rows.append([name, _n(p["added"]), _n(p["uploads"]), held, escape(p["via"])])
        out.append(_section("Uploads") + _block(_table(["Player", "New runs", "Uploads", "Held", "Via"],
                                                       rows, right=(1, 2, 3))))
    extra = []
    if up["held_unnamed"]:
        extra.append(f"Players with no profile yet: {_n(up['held_unnamed'])} run(s), all held.")
    if up["failed"]:
        extra.append(f'<span style="color:#a12a2a">Failed uploads: {len(up["failed"])} '
                     f'({escape(", ".join(sorted(set(up["failed"]))))})</span>')
    if extra:
        out.append(_block(f'<div style="font-size:12px;padding-top:8px">{"<br>".join(extra)}</div>'))
    if up["held_ids"]:
        rows = [[escape(src), f'<span style="font-family:Consolas,Menlo,monospace">{escape(ids)}</span>']
                for src, ids in held_groups(up["held_ids"][:HELD_SHOWN])]
        more = len(up["held_ids"]) - HELD_SHOWN
        sub = "A mod, or a newer patch. Most held first." + (f" {more} more not shown." if more > 0 else "")
        out.append(_section("Held: content the game data doesn't have", sub)
                   + _block(_table(["Source", "IDs"], rows, size=12)))
    return "".join(out)


def _feedback(sites: list[dict]) -> str:
    if not sites:
        return ""
    weekly = sites[0]["period"] == "weekly"
    came = "Came in this week" if weekly else "New today"
    rows = [[escape(s["label"]), f"<b>{_n(s['open'])}</b>", _n(s["new"]), _n(s["resolved"]), _n(s["backlog"])]
            for s in sites]
    out = [_section("Feedback this week" if weekly else "New feedback"),
           _block(_table(["Site", "Open", came, "Resolved", "Backlog"], rows, right=(1, 2, 3, 4)))]
    for s in sites:
        if not s["rows"]:
            continue
        title = {"new": f"{s['label']}, new", "open": f"{s['label']}, still open",
                 "recent": f"{s['label']}, open, most recently touched"}[s["listed"]]
        more = f" · {s['more']} more open" if s["more"] else ""
        rows = []
        for r in s["rows"]:
            text = r["text"] if len(r["text"]) <= NOTE_CHARS else r["text"][:NOTE_CHARS - 1] + "…"
            fb = f"FB-{r['seq']}" if r["seq"] is not None else "note"
            rows.append([f'<span style="white-space:nowrap">{_a(r["url"], fb)}</span>',
                         _badge(r["kind"]) if r["kind"] else "", escape(text),
                         _n(r["plus"]) if r["plus"] else '<span style="color:#bbb">–</span>',
                         escape(r["who"])])
        out.append(f'<tr><td style="padding:14px 24px 4px;font-size:13px;font-weight:600">{escape(title)}'
                   f'<span style="font-weight:400;color:{MUTED}">{escape(more)}</span></td></tr>')
        out.append(_block(_table(["ID", "Type", "Note", "+1", "From"], rows, right=(3,), size=12)))
    return "".join(out)


TAB_NAMES = {"detail": "Runs"}


def _views(today: dict, earlier: list[dict], domain: str) -> str:
    days = [today] + earlier
    span = f"{len(days)} days" if len(days) > 1 else "1 day"

    def total(key, name=None):
        return sum((d.get(key, {}).get(name, 0) if name else d.get(key, 0)) for d in days)

    def names(key):
        return sorted({n for d in days for n in d.get(key, {})},
                      key=lambda n: (-today.get(key, {}).get(n, 0), -total(key, n), n))

    rows = []
    for page in names("pages"):
        rows.append([escape(page), _n(today["pages"].get(page, 0)), _n(total("pages", page))])
        if page == "/u/<player>":
            for tab in names("tabs"):
                label = TAB_NAMES.get(tab, tab.capitalize())
                rows.append([f'<span style="color:#666">&nbsp;&nbsp;&nbsp;{escape(label)}</span>',
                             f'<span style="color:#666">{_n(today.get("tabs", {}).get(tab, 0))}</span>',
                             f'<span style="color:#666">{_n(total("tabs", tab))}</span>'])
    left = _table(["Page / tab", "Yesterday", span], rows, right=(1, 2), size=12)
    sources = sorted(today.get("sources", {}).items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    if sources:
        left += (f'<div style="font-size:11px;color:{MUTED};margin-top:8px">Loads from: '
                 + escape(" · ".join(f"{name} {_n(n)}" for name, n in sources)) + "</div>")
    right = ""
    players = sorted(today.get("players", {}).items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    if players:
        right += _table(["Top player pages", "Views"],
                        [[_a(f"https://{domain}/u/{s}", s), _n(n)] for s, n in players], right=(1,), size=12)
    runs = sorted(today.get("runs", {}).items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    if runs:
        right += '<div style="height:12px"></div>' + _table(
            ["Top runs", "Views"],
            [[_a(f"https://{domain}/u/{k.replace('#', '#detail/')}", k.replace("#", " · ")), _n(n)]
             for k, n in runs], right=(1,), size=12)
    sub = (f"{_n(today['views'])} yesterday · {_n(total('views'))} in {span} · "
           f"{_n(today['visitors'])} visitors · {_n(today['loads'])} page loads")
    return (_section("Page views", escape(sub)) + _block(
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td width="50%" style="vertical-align:top;padding-right:12px">{left}</td>'
        f'<td width="50%" style="vertical-align:top;padding-left:12px">{right}</td></tr></table>'))


def render(up: dict, feedback: list[dict], views: tuple | None, domain: str) -> str:
    """The whole email. `up` is build_digest's data, `feedback` each site's report_data,
    `views` (today, earlier) as views_section counted them, or None when that failed."""
    day = datetime.strptime(up["day"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    when = f"{day:%A} {day.day} {day:%b %Y}"
    if feedback and feedback[0]["period"] == "weekly":
        when += " · weekly feedback"
    if up["players"] or up["held_unnamed"] or up["failed"]:
        title = f"{_n(up['added'])} new run(s) from {_n(len(up['players']))} player(s)"
    else:
        title = "No uploads yesterday"
    held = sum(p["held"] for p in up["players"]) + up["held_unnamed"]
    tiles = [("New players", _n(sum(p["new"] for p in up["players"])), "", INK),
             ("Runs held", _n(held), "", WARN if held else INK),
             ("Site total", _n(up["total_runs"]), f"runs · {_n(up['total_players'])} players", INK)]
    if views:
        tiles.append(("Page views", _n(views[0]["views"]), f"{_n(views[0]['visitors'])} visitors", INK))
    body = (f'<tr><td style="padding:20px 24px 10px"><div style="font-size:12px;color:{MUTED}">'
            f'<a href="https://{domain}/" style="color:{MUTED};text-decoration:none">{escape(domain)}</a>'
            f' · {escape(when)}</div><div style="font-size:22px;font-weight:600;margin-top:4px">'
            f'{escape(title)}</div></td></tr>' + _block(_tiles(tiles))
            + _uploads(up, domain) + _feedback(feedback) + (_views(*views, domain) if views else "")
            + '<tr><td style="height:24px"></td></tr>')
    return ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width"></head>'
            f'<body style="margin:0;background:#f3f1ec;font-family:Segoe UI,Helvetica,Arial,sans-serif;'
            f'color:{INK};font-size:14px"><table role="presentation" width="100%" cellpadding="0" '
            'cellspacing="0" style="background:#f3f1ec"><tr><td align="center" style="padding:16px 8px">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="max-width:780px;background:#fff;border-radius:8px">{body}</table>'
            '</td></tr></table></body></html>')
