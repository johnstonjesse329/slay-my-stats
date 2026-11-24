"""
tools/build_showcase.py — Build the home page's showcase (users/_showcase.json.gz)
and the fight benchmark now, instead of waiting for the daily job.

The daily Benchmark Lambda (infra/lambda/ingest/benchmark.py) builds both from every
published run, but only prod has it; gamma has no such job, and prod's copy is
what the nightly seed would bring over once prod ships it. This runs the very same
refresh from this checkout against any data bucket.

Usage:
    python tools/build_showcase.py
        Gamma bucket, dry run: reads the bucket, writes nothing, prints what would be
        written and the showcase's contents.
    python tools/build_showcase.py --write
        Same, then writes users/_fight-demand.json.gz and users/_showcase.json.gz.
    python tools/build_showcase.py --bucket slay-my-stats-data --write
        Another bucket (prod's is refused unless you pass it explicitly).

    python tools/build_showcase.py --local
        No AWS: reads this checkout's local_data/ (the runs you uploaded or ran the
        site on) and writes users/_fight-demand.json.gz and users/_showcase.json.gz
        there, so tools/serve_site.py shows the home page showcase. Turn data comes from
        local_data/telemetry/ and, where that has none, from the telemetry kept with
        the act-validation work (local_data/act_validation/confirmation/telemetry/).
        The tabs only fill from runs in the last 30 days with turn data, so on a
        local copy a tab can be short or absent.

The bucket modes need AWS credentials (`aws login`).
"""

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))  # tools.power_curve, run.py
sys.path.insert(0, str(_REPO_ROOT / "infra" / "lambda" / "ingest"))

GAMMA = "slay-my-stats-gamma-data"


class _ReadOnly:
    """A store that reads through and only reports what a put would have written."""

    def __init__(self, store):
        self._store = store
        self.puts = {}

    def __getattr__(self, name):
        return getattr(self._store, name)

    def put(self, key, data, *args, **kwargs):
        self.puts[key] = data
        return None


class _LocalTelemetry:
    """A DirStore over local_data/ that, for a run with no telemetry of its own, reads the
    telemetry kept under act_validation/confirmation/telemetry/<steam id>/<ts>.json.gz."""

    def __init__(self, store, fallback):
        self._store = store
        self._fallback = fallback

    def __getattr__(self, name):
        return getattr(self._store, name)

    def get(self, key):
        got = self._store.get(key)
        if got is None and key.startswith("telemetry/"):
            path = self._fallback / key.split("/", 1)[1]
            if path.is_file():
                return (path.read_bytes(), path.stat().st_mtime, "fallback", {})
        return got


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bucket", default=GAMMA)
    ap.add_argument("--write", action="store_true", help="write the results (default: dry run)")
    ap.add_argument("--local", action="store_true",
                    help="build from local_data/ instead of a bucket, and write it there")
    args = ap.parse_args()
    os.environ["DATA_BUCKET"] = args.bucket
    import benchmark
    import handler
    if args.local:
        local = _REPO_ROOT / "local_data"
        handler._store = _LocalTelemetry(handler.DirStore(local),
                                         local / "act_validation" / "confirmation" / "telemetry")
        args.write = True
    store = handler._get_store()
    if not args.write:
        store = _ReadOnly(store)
        handler._store = store
    benchmark.refresh({}, None)
    if not args.write:
        for key, data in store.puts.items():
            print(f"would write {key} ({len(data)} bytes)")
            if key == benchmark.SHOWCASE_KEY:
                print(json.dumps(handler._unpack(data), indent=1))


if __name__ == "__main__":
    main()
