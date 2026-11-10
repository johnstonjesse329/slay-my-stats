"""
Where visitors come from: summarizes CloudFront access logs.

    aws s3 sync s3://<prefix>-access-logs/site/ logs/
    python tools/visit_sources.py logs/ [--days 30]

Counts page loads only (the SPA shell: /, /u/..., /about, /upload...), so
assets and data fetches don't inflate it. Groups by the Referer's host;
"(direct)" means no Referer: typed, bookmarked, an app, or a site that
strips it. A ?ref= or ?utm_source= on a shared link wins over the Referer,
so tag the links you post (e.g. /?ref=reddit).
"""
import argparse, collections, datetime, gzip, pathlib, urllib.parse

PAGE_EXTS = (".js", ".css", ".png", ".jpg", ".webp", ".svg", ".ico", ".json", ".gz", ".woff2", ".map", ".txt", ".mp3", ".ogg")


def rows(folder: pathlib.Path):
    fields = []
    for f in sorted(folder.rglob("*.gz")):
        for line in gzip.open(f, "rt", encoding="utf-8", errors="replace"):
            if line.startswith("#Fields:"):
                fields = line.split()[1:]
            elif not line.startswith("#") and fields:
                yield dict(zip(fields, line.rstrip("\n").split("\t")))


def source(row: dict) -> str:
    q = urllib.parse.parse_qs(urllib.parse.unquote(row.get("cs-uri-query", "")))
    for key in ("ref", "utm_source"):
        if q.get(key):
            return f"?{key}={q[key][0]}"
    ref = urllib.parse.unquote(row.get("cs(Referer)", "-"))
    host = urllib.parse.urlparse(ref).netloc.lower()
    return host.removeprefix("www.") if host else "(direct)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=pathlib.Path)
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    since = (datetime.date.today() - datetime.timedelta(days=args.days)).isoformat()
    counts, total = collections.Counter(), 0
    for r in rows(args.folder):
        uri = r.get("cs-uri-stem", "")
        if r.get("date", "") < since or r.get("sc-status", "")[:1] not in ("2", "3") or uri.lower().endswith(PAGE_EXTS):
            continue
        if "bot" in urllib.parse.unquote(r.get("cs(User-Agent)", "")).lower():
            continue
        counts[source(r)] += 1
        total += 1
    for name, n in counts.most_common(25):
        print(f"{n:6d}  {n / total:5.1%}  {name}")
    print(f"{total:6d}  page loads in the last {args.days} days")


if __name__ == "__main__":
    main()
