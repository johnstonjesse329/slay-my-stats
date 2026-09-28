"""
build_site.py — Static site builder for slay-my-stats.com

Builds dist/, the folder that gets synced to the S3 site bucket and served
through CloudFront. Unlike run.py's self-contained HTML file, the static
site has no data embedded in it: game art already lives in the bucket at
root-absolute paths mirroring this repo's folders (/card_final/..,
/card_portraits/.., /node_icons/.., /relic_images/.., /potion_images/..),
reference data (card/relic/potion metadata, encounter groupings, ...) is
published once as /catalog.json, and per-run data comes from a per-user
blob at /users/steam-<steamid64>.json.gz (see tools/build_user_blob.py).
site/boot.js fetches /catalog.json + the user blob at page load, builds
window.DATA from them, then loads /app.js — the same js/*.js bundle run.py
inlines, just fetched instead of embedded.

Usage:
    python build_site.py
        Cleans dist/ and rebuilds it from card_data.json / relic_data.json /
        potion_data.json, dashboard.css, js/*.js, and (if
        present) site/boot.js.
"""

import json
import shutil
import sys
from pathlib import Path

# Make run.py importable regardless of cwd (mirrors tools/build_user_blob.py).
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import run

_DIST = _HERE / "dist"
_SITE_BOOT_JS = _HERE / "site" / "boot.js"



def repo_url(p: Path) -> str:
    """
    Turn an absolute path under the repo root into the root-absolute URL the
    live site serves it at, e.g.
        <repo>/card_portraits/ironclad/bash.png -> /card_portraits/ironclad/bash.png
    Passed as the url_for maker to run.py's build_card_images() /
    build_node_icons() / build_card_final_images() / resolve_image_paths(),
    in place of their default Path.as_uri (file:// URIs for the local build).
    """
    return "/" + p.relative_to(run._HERE).as_posix()


def build_catalog() -> dict:
    """
    Everything run.py's build_html() computes that ISN'T per-run: card/relic/
    potion metadata, encounter groupings, and image URL maps. Only the
    committed repo folders count here (card_portraits/, node_icons/,
    relic_images/, potion_images/, card_final/) — no pck_recover_full
    fallback, since that gitignored extraction never ships to the bucket.
    """
    card_data = (
        json.loads(run._CARD_DATA_FILE.read_text(encoding="utf-8"))
        if run._CARD_DATA_FILE.exists() else {}
    )
    relic_data = (
        json.loads(run._RELIC_DATA_FILE.read_text(encoding="utf-8"))
        if run._RELIC_DATA_FILE.exists() else {}
    )
    relic_data = run.resolve_image_paths(relic_data, url_for=repo_url)
    potion_data = (
        json.loads(run._POTION_DATA_FILE.read_text(encoding="utf-8"))
        if run._POTION_DATA_FILE.exists() else {}
    )
    potion_data = run.resolve_image_paths(potion_data, url_for=repo_url)

    return {
        "charColorMap":       run.CHAR_COLORS,
        "encGroups":          run.ENCOUNTER_GROUPS,
        "cardImages":         run.build_card_images(url_for=repo_url),
        "cardImageOverrides": run._PORTRAIT_OVERRIDES,
        "cardData":           card_data,
        "cardChar":           run.build_card_char(card_data),
        "relicData":          relic_data,
        "potionData":         potion_data,
        "nodeIcons":          run.build_node_icons(url_for=repo_url),
        "cardFinal":          run.build_card_final_images(url_for=repo_url),
    }


def build_index_html() -> str:
    """
    dist/index.html — same head as run.py's HTML (meta, title, Chart.js CDN)
    but with dashboard.css linked instead of inlined, and /boot.js (not an
    embedded DATA blob) driving the page.
    """
    body = run.dashboard_body_html("Slay the Spire 2 run history.")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Slay the Spire 2 — Run History</title>
  <link rel="icon" type="image/png" href="/node_icons/elite.png">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
  <link rel="stylesheet" href="/dashboard.css">
</head>
<body>
{body}
<script src="/boot.js"></script>
</body>
</html>"""


def main():
    if _DIST.exists():
        shutil.rmtree(_DIST)
    _DIST.mkdir(parents=True)

    written = []  # (relative path, byte size), for the summary printout

    def write(rel_path: str, content) -> None:
        out = _DIST / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        out.write_bytes(data)
        written.append((rel_path, len(data)))

    write("index.html", build_index_html())
    write("app.js", run.read_dashboard_js())
    write("dashboard.css", (_HERE / "dashboard.css").read_text(encoding="utf-8"))

    if _SITE_BOOT_JS.exists():
        write("boot.js", _SITE_BOOT_JS.read_text(encoding="utf-8"))
    else:
        print(f"WARNING: {_SITE_BOOT_JS} does not exist yet — dist/boot.js not written.")

    catalog_json = json.dumps(build_catalog(), separators=(",", ":"))
    write("catalog.json", catalog_json)

    print("Wrote dist/:")
    for rel_path, size in written:
        print(f"  {rel_path:<24} {size:>12,} bytes")
    print(f"Total: {sum(size for _, size in written):,} bytes across {len(written)} files")


if __name__ == "__main__":
    main()
