"""
Drive the game to export its card, relic, potion and enchantment data and to
render every card face.

Why this exists
---------------
card_final/ used to be composited here from card_chrome/ by
tools/bake_finished_cards.py, and card_data.json was re-derived from the compiled
game by tools/extract_card_data.py. Both were re-implementations, and both got
things wrong: Tank's 1.5x damage taken multiplier was read as an int, so its card
said "Take 0% more damage" where the game says 50%, and the text grammar was a
hand-written port that dropped constructs the game supports.

tools/ExportCards.cs, run inside the recovered Godot project, asks the game instead -- it
formats each description with the game's own formatters and renders each card
through the game's own card scene -- so the output is exact by construction
rather than by re-derivation. This script is the repo-side driver for it: build,
run, and put the exported JSON where the repo expects it.

Run before tools/import_game_data.py, which folds that JSON into the site's data
files. tools/refresh_game_data.py runs both.

    python tools/export_game_data.py [--data-only]

Needs the Godot .NET editor (see GODOT below) and the recovery project, which holds
the game's own assets. The exporter's source lives here (tools/ExportCards.cs), not in
the recovery: the recovery is deleted and rebuilt on every game update, and took the
only copy with it once. This script installs it into the recovery on each run.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The recovered Godot project: the game's .pck unpacked, plus tools/ExportCards.cs.
# Sits beside the repo, since it is 3,500+ files of the game's own source and
# never ships.
RECOVERY = Path(os.environ.get("STS2_RECOVERY",
                               ROOT.parent / "sts2-history-dashboard" / "pck_recover_full"))

# Where ExportCards.cs writes (Godot's user:// for that project).
EXPORT_DIR = Path(os.environ.get(
    "STS2_EXPORT_DIR", Path.home() / "AppData" / "Roaming" / "SlayTheSpire2" / "card_export"))

# Godot 4.5.x .NET has no single install location, so look in the likely places
# and let GODOT override. The *console* build is what prints the exporter's log;
# the plain one detaches from stdio on Windows.
_GODOT_NAMES = ["Godot_v4.5.2-stable_mono_win64_console.exe", "godot_console.exe",
                "Godot_v4.5.2-stable_mono_win64.exe", "Godot.app/Contents/MacOS/Godot"]


def find_godot(explicit: str | None = None) -> Path | None:
    for candidate in (explicit, os.environ.get("GODOT")):
        if candidate and Path(candidate).exists():
            return Path(candidate)
    search = [ROOT.parent / "sts2-history-dashboard", Path.home() / "Downloads",
              Path("C:/Program Files"), Path("/Applications")]
    for base in search:
        if not base.exists():
            continue
        for name in _GODOT_NAMES:
            for hit in sorted(base.rglob(name))[:1]:
                return hit
    return shutil.which("godot") and Path(shutil.which("godot")) or None


EXPORTER_SRC = ROOT / "tools" / "ExportCards.cs"
AUTOLOAD_LINE = 'ExportCards="*res://tools/ExportCards.cs"'


def install_exporter(recovery: Path) -> None:
    """Put the exporter into the recovered project and register it as an autoload.

    The recovery is a fresh unpack of the game, so neither exists after a refresh.
    Idempotent: the autoload line is added once, and the source is always re-copied
    so an edit here is what runs.
    """
    dest = recovery / "tools" / "ExportCards.cs"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXPORTER_SRC, dest)

    project = recovery / "project.godot"
    text = project.read_text(encoding="utf-8")
    if AUTOLOAD_LINE in text:
        return
    marker = "[autoload]"
    if marker not in text:
        raise SystemExit(f"{project} has no [autoload] section to register the exporter in")
    nl = "\r\n" if "\r\n" in text else "\n"
    text = text.replace(marker, marker + nl + nl + AUTOLOAD_LINE, 1)
    project.write_text(text, encoding="utf-8", newline="")
    print(f"registered the exporter autoload in {project}", flush=True)


def run(argv, **kwargs) -> subprocess.CompletedProcess:
    """Log the command, then run it -- these steps take minutes, so a silent
    failure is worse than a noisy log."""
    print(f"$ {' '.join(str(a) for a in argv)}", flush=True)
    return subprocess.run([str(a) for a in argv], **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", help="path to the Godot .NET editor executable")
    parser.add_argument("--recovery", help="path to the recovered Godot project")
    parser.add_argument("--data-only", action="store_true",
                        help="export the JSON and skip rendering card faces")
    args = parser.parse_args()

    recovery = Path(args.recovery) if args.recovery else RECOVERY
    if not (recovery / "project.godot").exists():
        raise SystemExit(
            f"No recovered project at {recovery}\n"
            "  Pass --recovery, or set STS2_RECOVERY. It needs a GDRE recovery of the\n"
            "  game's .pck (see tools/refresh_game_data.py).")
    install_exporter(recovery)

    godot = find_godot(args.godot)
    if godot is None:
        raise SystemExit(
            "Godot not found. Download the .NET build of 4.5.x (mono_win64.zip, not\n"
            "  win64.zip -- the non-.NET one cannot run the game's C#), then pass\n"
            "  --godot <exe> or set GODOT.")

    # Godot does not rebuild C# on run, so a stale assembly silently exports stale
    # data -- the failure looks like "the fix did nothing".
    print("Building the exporter...", flush=True)
    build = run(["dotnet", "build", "-v", "quiet", "--nologo"], cwd=recovery,
                capture_output=True, text=True)
    if build.returncode != 0:
        print(build.stdout[-4000:], file=sys.stderr)
        raise SystemExit(f"dotnet build failed ({build.returncode})")

    env = dict(os.environ, EXPORT_CARDS="1")
    env.pop("RENDER_ALL", None)
    env.pop("EXPORT_MADSCIENCE", None)
    if not args.data_only:
        env["RENDER_ALL"] = "1"          # every card face
        env["EXPORT_MADSCIENCE"] = "1"   # the per-roll variants, which need their own bake

    # A windowed run is required: --headless selects the dummy renderer, which
    # produces no pixels. Quit-after is a wall-clock guard in frames.
    budget = 1800 if args.data_only else 108000
    print(f"Exporting from the game ({'data only' if args.data_only else 'data + card faces'})...",
          flush=True)
    t0 = time.time()
    proc = run([godot, "--path", recovery, "--quit-after", budget], env=env,
               capture_output=True, text=True)
    log = (proc.stdout or "") + (proc.stderr or "")

    # The exporter prints its own summary line, and the file has to be newer than
    # this run. Without both checks a Godot crash would leave the *previous*
    # export in place and this script would copy it and report success -- the
    # exact silent-staleness failure that made the old hand-baked cards wrong.
    marker = "[export] card_game_data.json:"
    if marker not in log:
        print(log[-4000:], file=sys.stderr)
        raise SystemExit(f"the exporter never reported success (exit {proc.returncode}); "
                         f"see the log above. Nothing was copied.")
    exported = EXPORT_DIR / "card_game_data.json"
    if not exported.exists() or exported.stat().st_mtime < t0 - 2:
        raise SystemExit(f"{exported} was not rewritten by this run -- refusing to copy a stale "
                         f"export. Nothing was copied.")
    data = json.loads(exported.read_text(encoding="utf-8"))
    target = ROOT / "card_game_data.json"
    shutil.copy2(exported, target)
    print(f"--- copied {target.name} ({time.time() - t0:.0f}s): "
          f"{len(data['Cards'])} cards, {len(data['Relics'])} relics, "
          f"{len(data['Potions'])} potions, {len(data['Enchantments'])} enchantments, "
          f"{len(data['Variants'])} variants")

    if not args.data_only:
        if "card faces failed to render" in log or "[render] wrote" not in log:
            print(log[-4000:], file=sys.stderr)
            raise SystemExit("Some card faces failed to render. card_final/ was left as it was.")
        rendered = sorted((EXPORT_DIR / "card_final").glob("*.webp"))
        fresh = [f for f in rendered if f.stat().st_mtime >= t0 - 2]
        if not fresh:
            print(log[-4000:], file=sys.stderr)
            raise SystemExit("No faces were rendered by this run. Nothing was copied to card_final/.")
        out = ROOT / "card_final"
        out.mkdir(exist_ok=True)
        # Replace the set rather than add to it, so a card the game dropped doesn't linger.
        for old in out.glob("*.webp"):
            old.unlink()
        for face in fresh:
            shutil.copy2(face, out / face.name)
        print(f"--- rendered {len(fresh)} card faces into card_final/")
    print("Next: python tools/import_game_data.py", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
