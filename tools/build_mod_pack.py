"""Build the mod's snapshot from a local copy of the site's data and report its size.

    python tools/build_mod_pack.py <data folder> <output folder>
    python tools/build_mod_pack.py --gamma

<data folder> holds users/ (published profiles and users/_fight-demand.json.gz). The Lambda
reads the totals from users/_stats.json.gz; this counts them from the published profiles.

--gamma publishes mod/v1/ in gamma's bucket from gamma's totals and fight lines, since
gamma has no benchmark Lambda. Needs AWS credentials (`aws login`). It never writes to prod.
"""
import gzip
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "infra" / "lambda" / "ingest")]

import build_site  # noqa: E402
import handler  # noqa: E402
import mod_pack  # noqa: E402

GAMMA = "slay-my-stats-gamma-data"


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def profile_runs(users: Path):
    """(slug, runs) of every published profile."""
    for blob in sorted(users.glob("*.json.gz")):
        if blob.name.startswith("_"):
            continue
        slug = blob.name.removesuffix(".json.gz")
        doc = read(blob)
        runs = list(doc.get("runs") or [])
        for month in doc.get("months") or {}:
            runs += read(users / slug / f"{month}.json.gz")["runs"]
        yield slug, runs


def game_data(folder: Path) -> dict:
    """What the Lambda's bundle carries, built here."""
    static_file = folder / "mod_synergy.json"
    if not build_site.write_mod_synergy(static_file):
        sys.exit("power_data.json is missing")
    static = json.loads(static_file.read_text(encoding="utf-8"))
    static_file.unlink()
    return static


def publish_gamma(store=None):
    store = store or handler.S3Store(GAMMA)
    found = {key: store.get(key) for key in (handler.STATS_KEY, "users/_fight-demand.json.gz")}
    missing = [key for key, got in found.items() if got is None]
    if missing:
        sys.exit(f"{GAMMA} has no {', '.join(missing)}: seed it first (tools/seed_gamma.py)")
    stats, benchmark = (handler._unpack(got[0]) for got in found.values())
    with tempfile.TemporaryDirectory() as folder:
        static = game_data(Path(folder))
    mod_pack.publish(store, benchmark, stats, time.time(), static)


def main(data: Path, out: Path):
    stats, players = handler.empty_stats(), 0
    for slug, runs in profile_runs(data / "users"):
        players += 1
        handler.merge_stats(stats, handler.tally(runs, slug))
    benchmark = read(data / "users" / "_fight-demand.json.gz")
    out.mkdir(parents=True, exist_ok=True)
    pack, name, body = mod_pack.build(benchmark, stats, game_data(out), time.time())
    packed = mod_pack.encode(pack)
    (out / "pack.json.gz").write_bytes(packed)
    (out / name).write_bytes(body)

    def kb(value):
        return f"{len(mod_pack.encode(value)) / 1024:.0f} KB"

    print(f"{players} players, {stats['solo']['runs'] + stats['multi']['runs']} counted runs")
    print(f"pack {len(packed) / 1024:.0f} KB gzipped; synergy {len(body) / 1024:.0f} KB, "
          f"{len(gzip.compress(body)) / 1024:.0f} KB gzipped")
    print(f"  alone: ruler {kb(pack['ruler'])}")
    for lane, parts in pack["lanes"].items():
        print(f"  alone, {lane}: " + ", ".join(f"{k} {kb(v)}" for k, v in parts.items()))


if __name__ == "__main__":
    if sys.argv[1:] == ["--gamma"]:
        publish_gamma()
        sys.exit()
    if len(sys.argv) != 3 or sys.argv[1].startswith("-"):
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
