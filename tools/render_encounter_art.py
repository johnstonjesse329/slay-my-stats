"""Render one image per fight: the monsters you meet, drawn with the game's own
art, for the fight tooltips on the site.

What it does, in order:
  1. tools/encounter_manifest.py reads the PCK extraction for every encounter
     the game ships -- its roster, each monster's Spine skeleton, scale, skin
     and slot position.
  2. Godot (tools/godot/, gitignored) opens tools/encounter_art_project/ and
     draws each fight into a SubViewport, posing every monster on its idle
     frame and keeping the baked ground shadow, then trims and saves a PNG.
     The game's own spine-godot GDExtension is copied out of the extraction
     into the project to load the skeletons; it ships with the game, so it is
     gitignored rather than committed.
  3. Each PNG is scaled to TIP_WIDTH and written to encounter_art/ as a webp.
     Those are committed: the extraction is gitignored and ~3 GB, so the site
     can't rebuild them at deploy time. Being committed, they are pinned by git
     itself and so are not in tools/art_manifest.json, which exists to pin the
     art folders that aren't.

Godot can't read pixels back in headless mode, so step 2 opens a small real
window for a few minutes. That is expected; don't close it.

    python tools/render_encounter_art.py            # everything
    python tools/render_encounter_art.py --manifest-only
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pck_root import find_pck_root

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "tools" / "encounter_art_project"
GODOT = ROOT / "tools" / "godot" / "Godot_v4.5.2-stable_mono_win64_console.exe"
WORK = ROOT / "local_data" / "encounter-art"
ART = ROOT / "encounter_art"

# Keep the source sharp at the tooltip's maximum 280 CSS pixels wide.
TIP_WIDTH = 560
TIP_MAX_HEIGHT = 400
WEBP_QUALITY = 82
# Fractional bounds on the trimmed render. At tooltip size, detached wisps
# and the prism's distant ground shadow otherwise shrink the monsters.
TOOLTIP_FRAMES = {
    "encounter_soul_nexus_elite": (0.23, 0.36, 0.76, 0.90),
    "encounter_infested_prisms_elite": (0.0, 0.0, 1.0, 0.63),
}


def copy_spine_extension(pck: Path) -> None:
    """The game's spine-godot GDExtension, which loads .skel/.atlas at runtime."""
    src = pck / "addons" / "spine"
    if not src.exists():
        sys.exit(f"spine-godot addon not found in the extraction: {src}")
    dst = PROJECT / "addons" / "spine"
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    # Godot loads GDExtensions from this list, which only the editor writes.
    # We never open the editor, so write it ourselves.
    cfg = PROJECT / ".godot" / "extension_list.cfg"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("res://addons/spine/spine_godot_extension.gdextension\n", encoding="utf-8")


def build_manifest(pck: Path) -> Path:
    out = WORK / "manifest.json"
    subprocess.run([sys.executable, str(ROOT / "tools" / "encounter_manifest.py"),
                    str(pck), str(out)], check=True)
    return out


def render(pck: Path, manifest: Path) -> Path:
    if not GODOT.exists():
        sys.exit(f"Godot not found at {GODOT} (tools/godot/ is gitignored -- see the README)")
    out = WORK / "png"
    subprocess.run([str(GODOT), "--path", str(PROJECT), "res://groups.tscn", "--",
                    str(pck), str(out), str(manifest)], check=True)
    return out


def to_webp(png_dir: Path) -> None:
    from PIL import Image
    ART.mkdir(parents=True, exist_ok=True)
    written = 0
    for png in sorted(png_dir.glob("*.png")):
        im = Image.open(png).convert("RGBA")
        box = im.getbbox()          # the renderer trims already; belt and braces
        if box:
            im = im.crop(box)
        frame = TOOLTIP_FRAMES.get(png.stem)
        if frame:
            im = im.crop(tuple(round(edge * size) for edge, size in zip(frame, im.size * 2)))
        im.thumbnail((TIP_WIDTH, TIP_MAX_HEIGHT), Image.LANCZOS)
        im.save(ART / f"{png.stem}.webp", "WEBP", quality=WEBP_QUALITY, method=6)
        written += 1
    total = sum(p.stat().st_size for p in ART.glob("*.webp"))
    print(f"{written} images -> {ART} ({total / 1024 / 1024:.2f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest-only", action="store_true",
                    help="build the manifest and stop, without opening Godot")
    args = ap.parse_args()

    pck = find_pck_root()
    if not pck.exists():
        sys.exit(f"PCK extraction not found at {pck} (set STS2_PCK_ROOT)")
    WORK.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(pck)
    if args.manifest_only:
        return
    copy_spine_extension(pck)
    to_webp(render(pck, manifest))


if __name__ == "__main__":
    main()
