"""
Page views, counted from CloudFront's standard access logs.

The site asks for /seen.txt once for each page or tab it shows (site/boot.js's noteView),
its query naming which: p, the path (/, /about, /u/<slug>, any page added later); t, a
player page's tab (overview, detail, cards, ...); r, the run Run Detail is showing. The
logs keep each request, so nothing else is stored or paid for. The morning digest
(handler.views_section) counts yesterday's and emails them; tools/visit_sources.py reads
the same logs by hand. Names are taken from the requests as they come, so a new page or
tab is counted the day it ships; anything that doesn't look like one is dropped.

No address or user agent is kept: the counts are all that's saved.
"""
import collections
import gzip
import re
import urllib.parse

PING = "/seen.txt"
# Asset and data requests, which aren't page loads. .html: the page bodies boot.js fetches
# (/page-about.html), not loads of the site; /index.html itself still counts.
PAGE_EXTS = (".js", ".css", ".png", ".jpg", ".webp", ".svg", ".ico", ".json", ".gz", ".woff2", ".map",
             ".txt", ".mp3", ".ogg", ".html")
_SEG = r"[a-z0-9]{1,40}(?:-[a-z0-9]{1,40}){0,6}"
_PATH = re.compile(rf"^/(?:{_SEG}(?:/{_SEG})?)?$")
_NAME = re.compile(rf"^{_SEG}$")
_RUN = re.compile(r"^\d{1,12}$")
# How many of each long list a day keeps: the top ones are what's read.
KEEP = 200


def log_rows(lines):
    """Each request in a standard log (its lines, gunzipped) as {field: value}."""
    fields = []
    for line in lines:
        if line.startswith("#Fields:"):
            fields = line.split()[1:]
        elif not line.startswith("#") and fields:
            yield dict(zip(fields, line.rstrip("\n").split("\t")))


def read_log(raw: bytes):
    return log_rows(gzip.decompress(raw).decode("utf-8", "replace").splitlines())


def _decode(value: str) -> str:
    # CloudFront writes the query URL-encoded, and encodes a % it was sent again.
    for _ in range(3):
        nxt = urllib.parse.unquote_plus(value)
        if nxt == value:
            break
        value = nxt
    return value


def query(row: dict) -> dict:
    raw = row.get("cs-uri-query", "-")
    if raw in ("", "-"):
        return {}
    return {k: _decode(v) for k, v in urllib.parse.parse_qsl(raw, keep_blank_values=True)}


def is_bot(row: dict) -> bool:
    return "bot" in _decode(row.get("cs(User-Agent)", "")).lower()


def is_page_load(row: dict) -> bool:
    """A load of the site itself (every page is the same index.html), not an asset, a data
    file or a view ping."""
    uri = row.get("cs-uri-stem", "")
    return (row.get("cs-method", "GET") == "GET" and row.get("sc-status", "")[:1] in ("2", "3")
            and (uri == "/index.html" or not uri.lower().endswith(PAGE_EXTS)) and not is_bot(row))


def source(row: dict) -> str:
    """Where a page load came from: a ?ref= or ?utm_source= on the link, else the Referer's
    host; "(direct)" when there's neither."""
    q = query(row)
    for key in ("ref", "utm_source"):
        if q.get(key):
            return f"?{key}={q[key]}"
    ref = _decode(row.get("cs(Referer)", "-"))
    host = urllib.parse.urlparse(ref).netloc.lower()
    return host.removeprefix("www.") if host else "(direct)"


def view(row: dict):
    """(path, tab, run) for a view ping, or None for anything else or anything malformed."""
    if row.get("cs-uri-stem") != PING or row.get("sc-status", "")[:1] not in ("2", "3") or is_bot(row):
        return None
    q = query(row)
    path, tab, run = q.get("p", ""), q.get("t") or None, q.get("r") or None
    if not _PATH.match(path) or (tab and not _NAME.match(tab)) or (run and not _RUN.match(run)):
        return None
    return path, tab, run


def page_of(path: str) -> str:
    """Every player's page is one page: /u/<player>."""
    return "/u/<player>" if path.startswith("/u/") else path


def count_views(rows, day: str | None = None) -> dict:
    """One day's counts from its log rows (only rows dated `day`, when given): views by page,
    by player-page tab, by player and by run; distinct visitors; page loads by source."""
    pages, tabs, players, runs, sources = (collections.Counter() for _ in range(5))
    visitors, loads, views = set(), 0, 0
    for row in rows:
        if day and row.get("date") != day:
            continue
        v = view(row)
        if v:
            path, tab, run = v
            views += 1
            visitors.add(row.get("c-ip"))
            pages[page_of(path)] += 1
            if path.startswith("/u/"):
                slug = path[3:]
                players[slug] += 1
                if tab:
                    tabs[tab] += 1
                if tab == "detail" and run:
                    runs[f"{slug}#{run}"] += 1
        elif is_page_load(row):
            loads += 1
            sources[source(row)] += 1
    return {"day": day, "views": views, "visitors": len(visitors), "loads": loads,
            "pages": dict(pages), "tabs": dict(tabs), "players": dict(players.most_common(KEEP)),
            "runs": dict(runs.most_common(KEEP)), "sources": dict(sources.most_common(50))}


def _table(rows, cols, width=0):
    width = max([width] + [len(r[0]) for r in rows])
    out = []
    for name, *nums in rows:
        out.append("  " + name.ljust(width) + "".join(f"{n:>10,}" for n in nums))
    head = "  " + " " * width + "".join(f"{c:>10}" for c in cols)
    return "\n".join([head] + out)


def format_views(today: dict, earlier: list[dict], domain: str) -> tuple[str, str]:
    """The email section: yesterday's counts next to the last week's (today plus up to six
    earlier days, whichever were kept), and yesterday's top players, runs and sources."""
    days = [today] + earlier
    span = f"{len(days)} days" if len(days) > 1 else "1 day"

    def total(key, name=None):
        return sum((d.get(key, {}).get(name, 0) if name else d.get(key, 0)) for d in days)

    headline = f"Page views: {today['views']:,} yesterday, {total('views'):,} in {span}"
    cols = ("yesterday", span)
    parts = [f"Visitors: {today['visitors']:,} yesterday. Page loads: {today['loads']:,}."]

    def by(key, label):
        names = sorted({n for d in days for n in d.get(key, {})},
                       key=lambda n: (-today.get(key, {}).get(n, 0), -total(key, n), n))
        if names:
            parts.append(f"\n{label}\n" + _table(
                [(n, today.get(key, {}).get(n, 0), total(key, n)) for n in names], cols))

    by("pages", "By page")
    by("tabs", "Player pages, by tab (detail is Runs; each run opened counts there)")
    top = sorted(today.get("players", {}).items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    if top:
        parts.append("\nTop player pages, yesterday\n" + "\n".join(
            f"  {n:>6,}  {slug}  https://{domain}/u/{slug}" for slug, n in top))
    top = sorted(today.get("runs", {}).items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    if top:
        parts.append("\nTop runs, yesterday\n" + "\n".join(
            f"  {n:>6,}  https://{domain}/u/{key.replace('#', '#detail/')}" for key, n in top))
    top = sorted(today.get("sources", {}).items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    if top:
        parts.append("\nWhere page loads came from, yesterday\n" + "\n".join(
            f"  {n:>6,}  {name}" for name, n in top))
    return headline, "\n".join(parts)
