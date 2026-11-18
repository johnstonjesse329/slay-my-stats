"""
Where visitors come from: summarizes CloudFront access logs.

    aws s3 sync s3://<prefix>-access-logs/site/ logs/
    python tools/visit_sources.py logs/ [--days 30]   # --days 0: all time

Counts page loads only (the SPA shell: /, /u/..., /about, /upload...), so
assets and data fetches don't inflate it. Groups by the Referer's host;
"(direct)" means no Referer: typed, bookmarked, an app, or a site that
strips it. A ?ref= or ?utm_source= on a shared link wins over the Referer,
so tag the links you post (e.g. /?ref=reddit).

The morning digest email has these too, for the day before, with the page and tab views.
"""
import argparse, collections, datetime, gzip, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "infra" / "lambda" / "ingest"))
import views  # noqa: E402  (shared with the morning digest, which emails the same counts daily)


def rows(folder: pathlib.Path):
    for f in sorted(folder.rglob("*.gz")):
        yield from views.log_rows(gzip.open(f, "rt", encoding="utf-8", errors="replace"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=pathlib.Path)
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    since = (datetime.date.today() - datetime.timedelta(days=args.days)).isoformat() if args.days else ""
    counts, total = collections.Counter(), 0
    for r in rows(args.folder):
        if r.get("date", "") < since or not views.is_page_load(r):
            continue
        counts[views.source(r)] += 1
        total += 1
    for name, n in counts.most_common(25):
        print(f"{n:6d}  {n / total:5.1%}  {name}")
    print(f"{total:6d}  page loads" + (f" in the last {args.days} days" if args.days else ", all time"))


if __name__ == "__main__":
    main()
