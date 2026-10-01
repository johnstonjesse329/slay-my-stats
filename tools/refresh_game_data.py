"""
One-command, re-runnable refresh of every generated game-data artifact.

The game is on the beta branch and updates often, so this has to be trivial to
re-run. It also has to be *safe* to re-run: the previous pipeline read card
stats from the game DLL but text and images from `pck_recover_full/`, with
nothing tying the two to the same build. When the DLL was newer than the
extraction (3 months newer, in practice) it silently emitted cards with stats
but no title, description or art. This script makes that impossible: every
artifact is stamped with the inputs that produced it, and a completeness check
fails loudly rather than shipping blanks.

    python tools/refresh_game_data.py                # full refresh
    python tools/refresh_game_data.py --skip-recovery  # reuse pck_recover_full/
    python tools/refresh_game_data.py --check          # verify only, change nothing
    python tools/refresh_game_data.py --stale          # installed build vs composed assets?

Recovery is skipped automatically when the .pck hash matches what produced the
current extraction, so a re-run costs seconds rather than minutes.

Requires: Pillow, numpy, pythonnet (see the individual tools), plus GDRE Tools
for the recovery step: https://github.com/GDRETools/gdsdecomp/releases
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent

# Card names, arrows and em-dashes all flow through this script's output. On
# Windows the console defaults to cp1252, where printing any of them raises
# UnicodeEncodeError and kills the run — so make our own streams UTF-8 before
# anything prints. (Sub-tools get the same treatment via run_step's env.)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

PCK_DIR       = ROOT / "pck_recover_full"
PROVENANCE    = ROOT / "data_provenance.json"
CARD_DATA     = ROOT / "card_data.json"
RELIC_DATA    = ROOT / "relic_data.json"
PORTRAIT_DIR  = ROOT / "card_portraits"
RELIC_IMG_DIR = ROOT / "relic_images"
POTION_DATA   = ROOT / "potion_data.json"
POTION_IMG_DIR = ROOT / "potion_images"
CHROME_DIR    = ROOT / "card_chrome"
CARD_FINAL_DIR = ROOT / "card_final"

# Cards with no single static description: their text is a nested conditional
# over runtime state, so there is nothing to extract. Mad Science is generated
# at an event — its description branches on the rolled card type and on eight
# possible riders. The dashboard shows the title, which is the useful part;
# inventing prose here would be worse than showing none.
DYNAMIC_TEXT_CARDS = {"CARD.MAD_SCIENCE"}

GAME_DIR_NAME = "Slay the Spire 2"
DLL_RELPATH   = Path("data_sts2_windows_x86_64") / "sts2.dll"
PCK_NAME      = "SlayTheSpire2.pck"
RELEASE_INFO  = "release_info.json"


# ---------------------------------------------------------------------------
# Locating things
# ---------------------------------------------------------------------------
def steam_libraries():
    """Every Steam library root, from libraryfolders.vdf.

    Not a hardcoded C:\\Program Files (x86) path — games are commonly on a
    second drive (this project's own install is on E:).
    """
    roots = []
    for base in (Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam",
                 Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Steam",
                 Path.home() / ".steam" / "steam",
                 Path.home() / "Library" / "Application Support" / "Steam"):
        vdf = base / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
                roots.append(Path(m.group(1).replace("\\\\", "\\")))
    return roots


def find_game(explicit=None):
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise SystemExit(f"--game path does not exist: {p}")
        return p
    for lib in steam_libraries():
        cand = lib / "steamapps" / "common" / GAME_DIR_NAME
        if cand.exists():
            return cand
    raise SystemExit(f"Could not find '{GAME_DIR_NAME}' in any Steam library.\n"
                     f"Searched: {', '.join(str(r) for r in steam_libraries()) or '(none found)'}\n"
                     "Pass --game <path> explicitly.")


def find_gdre(explicit=None):
    if explicit:
        return Path(explicit)
    env = os.environ.get("GDRE_TOOLS")
    if env:
        return Path(env)
    for parent in (Path.home() / "tools", Path.home() / "Downloads", Path.home() / "Desktop"):
        if parent.exists():
            hits = sorted(parent.glob("GDRE_tools-*/gdre_tools.exe"))
            if hits:
                return hits[-1]          # highest version name sorts last
    return None


# ---------------------------------------------------------------------------
def sha256(path, chunk=8 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_provenance():
    if PROVENANCE.exists():
        try:
            return json.loads(PROVENANCE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def file_stamp(path):
    """Second-precision local mtime, matching what the provenance records."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime))


def read_release_info(game):
    """The game's real build identity lives in release_info.json inside the
    install (its exe reports a placeholder 1.0.0.0). Returns version/commit/
    date, or None when the file is absent or unreadable."""
    f = game / RELEASE_INFO
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return {"version": d.get("version"), "commit": d.get("commit"), "date": d.get("date")}


def staleness(explicit_game=None):
    """Is the installed game build the same one the composed assets came from?

    Compares the installed release_info.json against the version recorded in
    data_provenance.json at compose time. release_info.json is tiny, so this is
    instant — no re-hashing of the ~2 GB .pck. Older provenance (or installs
    without release_info.json) falls back to comparing file mtimes.

    Returns an exit code: 0 = up to date, 2 = stale (run the refresh), 1 =
    could not determine (error).
    """
    game = find_game(explicit_game)
    pck, dll = game / PCK_NAME, game / DLL_RELPATH
    missing = [str(p) for p in (pck, dll) if not p.exists()]
    if missing:
        print("Cannot determine the installed build — missing " + ", ".join(missing))
        return 1
    prov = load_provenance()
    if not prov:
        print("No data_provenance.json yet — the assets have never been composed.")
        print("Run: python tools/refresh_game_data.py")
        return 2

    rel = read_release_info(game)
    if rel and prov.get("gameVersion"):
        old = (prov.get("gameVersion"), prov.get("buildCommit"), prov.get("buildDate"))
        new = (rel.get("version"), rel.get("commit"), rel.get("date"))
        if all(v is not None for v in new) and old == new:
            print(f"UP TO DATE — installed build {new[0]} matches the composed assets "
                  f"(composed {prov.get('generatedAt', '?')}).")
            print("No asset refresh needed.")
            return 0
        print(f"STALE — installed build is {new[0] or '?'} (commit {new[1] or '?'}, "
              f"{new[2] or '?'}) but the composed assets are from {old[0] or '?'} "
              f"(commit {old[1] or '?'}).")
        print("Run: python tools/refresh_game_data.py")
        return 2

    # Pre-version provenance or no release_info.json: mtime compare. A content
    # change always updates the file's mtime, so equal stamps prove no change.
    if file_stamp(pck) == prov.get("pckModified") and file_stamp(dll) == prov.get("dllModified"):
        print(f"UP TO DATE — installed .pck/.dll are unchanged since the assets were "
              f"composed ({prov.get('generatedAt', '?')}).")
        print("No asset refresh needed.")
        return 0
    print(f"STALE — installed game files differ from the build the composed assets "
          f"came from ({prov.get('generatedAt', '?')}).")
    print("Run: python tools/refresh_game_data.py")
    return 2


def run_step(name, argv):
    """Run a sub-tool, echoing its output and returning it.

    Forces UTF-8 on the child: the tools print arrows, em-dashes and card
    names, and Windows' default cp1252 console encoding makes that a crash
    (UnicodeEncodeError) rather than a display glitch.
    """
    print(f"\n=== {name} ===", flush=True)
    t0 = time.time()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    r = subprocess.run([sys.executable, *argv], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    print(out.rstrip())
    if r.returncode != 0:
        raise SystemExit(f"{name} failed (exit {r.returncode})")
    print(f"--- {name} ok ({time.time()-t0:.1f}s)")
    return out


# ---------------------------------------------------------------------------
def completeness_report():
    """Every card needs title+desc+portrait; every relic needs title+image.

    Returns (problems, stats). A non-empty `problems` means the generated data
    is internally inconsistent — almost always because the DLL is newer than
    pck_recover_full/ and the fix is to re-run without --skip-recovery.
    """
    problems, stats = [], {}
    cards   = json.loads(CARD_DATA.read_text(encoding="utf-8")) if CARD_DATA.exists() else {}
    relics  = json.loads(RELIC_DATA.read_text(encoding="utf-8")) if RELIC_DATA.exists() else {}
    potions = json.loads(POTION_DATA.read_text(encoding="utf-8")) if POTION_DATA.exists() else {}
    stats["cards"], stats["relics"], stats["potions"] = len(cards), len(relics), len(potions)

    def add(label, ids):
        if ids:
            problems.append(f"{len(ids)} {label}: " + ", ".join(sorted(ids)[:8])
                            + (" ..." if len(ids) > 8 else ""))

    add("card(s) with no title", [k for k, v in cards.items() if not (v.get("title") or "").strip()])
    add("relic(s) with no title", [k for k, v in relics.items() if not (v.get("title") or "").strip()])
    add("potion(s) with no title", [k for k, v in potions.items() if not (v.get("title") or "").strip()])

    # A blank description is only a bug if the game HAS one and we lost it in
    # conversion. Curses and statuses (Dazed, Greed, Ascender's Bane, ...) ship
    # an empty description on purpose — the game draws their "Unplayable." line
    # from a flag, not from this string. So diff against localization rather
    # than treating empty as broken.
    loc_file = PCK_DIR / "localization" / "eng" / "cards.json"
    if loc_file.exists():
        loc = json.loads(loc_file.read_text(encoding="utf-8"))
        lost = [k for k, v in cards.items()
                if k not in DYNAMIC_TEXT_CARDS
                and not (v.get("desc") or "").strip()
                and (loc.get(f"{k.split('.', 1)[1]}.description") or "").strip()]
        add("card(s) whose description was dropped in conversion", lost)

    # Relic images are recorded as repo-relative paths; they must actually exist.
    missing_img = [k for k, v in relics.items()
                   if not v.get("imagePath") or not (ROOT / v["imagePath"]).exists()]
    # RELIC.DEPRECATED_RELIC is a removed placeholder with no art anywhere.
    missing_img = [k for k in missing_img if k != "RELIC.DEPRECATED_RELIC"]
    add("relic(s) with no image", missing_img)

    # DEPRECATED_POTION is a removed placeholder and MOCK_* are test fixtures;
    # neither has art and neither can appear in a real run.
    missing_potion_img = [k for k, v in potions.items()
                          if (not v.get("imagePath") or not (ROOT / v["imagePath"]).exists())
                          and "DEPRECATED" not in k and "MOCK_" not in k]
    add("potion(s) with no image", missing_potion_img)

    portrait_files = list(PORTRAIT_DIR.rglob("*.png")) if PORTRAIT_DIR.exists() else []
    portraits = {p.stem for p in portrait_files}
    stats["portrait_files"] = len(portrait_files)
    stats["portrait_names"] = len(portraits)
    # Mirrors _PORTRAIT_OVERRIDES in run.py — a few cards' art is filed under a
    # different stem (Mad Science has one portrait per resulting card type).
    aliases = {"stack": "smokestack", "mad_science": "mad_science_attack"}
    add("card(s) with no portrait",
        [k for k in cards
         if "DEPRECATED" not in k
         and aliases.get(k.split(".", 1)[1].lower(), k.split(".", 1)[1].lower()) not in portraits])

    stats["relic_images"] = len(list(RELIC_IMG_DIR.rglob("*.webp"))) if RELIC_IMG_DIR.exists() else 0
    stats["potion_images"] = len(list(POTION_IMG_DIR.glob("*.webp"))) if POTION_IMG_DIR.exists() else 0
    stats["chrome"] = len(list(CHROME_DIR.glob("*.png"))) if CHROME_DIR.exists() else 0

    final_files = {p.stem for p in CARD_FINAL_DIR.glob("*.webp")} if CARD_FINAL_DIR.exists() else set()
    stats["card_final"] = len(final_files)
    add("card(s) with no finished bake",
        [k for k in cards if "DEPRECATED" not in k
         and not ({k, f"{k}_UP"} <= final_files)])
    return problems, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", help="path to the 'Slay the Spire 2' install dir")
    ap.add_argument("--gdre", help="path to gdre_tools.exe")
    ap.add_argument("--skip-recovery", action="store_true",
                    help="reuse the existing pck_recover_full/ even if the .pck changed")
    ap.add_argument("--force-recovery", action="store_true",
                    help="re-run the recovery even if the .pck hash is unchanged")
    ap.add_argument("--check", action="store_true",
                    help="only run the completeness check; change nothing")
    ap.add_argument("--stale", action="store_true",
                    help="compare the installed game build to the last-composed assets; "
                         "exit 0 = current, 2 = run the refresh")
    args = ap.parse_args()

    if args.check:
        problems, stats = completeness_report()
        print("stats:", json.dumps(stats))
        prov = load_provenance()
        if prov:
            print(f"generated {prov.get('generatedAt','?')} "
                  f"from game build dated {prov.get('pckModified','?')}")
        for p in problems:
            print("  !", p)
        raise SystemExit(1 if problems else 0)

    if args.stale:
        raise SystemExit(staleness(args.game))

    game = find_game(args.game)
    dll  = game / DLL_RELPATH
    pck  = game / PCK_NAME
    for p in (dll, pck):
        if not p.exists():
            raise SystemExit(f"Missing {p} — is the game installed and up to date?")
    print(f"game : {game}")

    print("hashing inputs (the .pck is ~2 GB, this takes a moment)...", flush=True)
    pck_hash, dll_hash = sha256(pck), sha256(dll)
    prev = load_provenance()
    pck_unchanged = prev.get("pckSha256") == pck_hash and PCK_DIR.exists()

    if args.skip_recovery or (pck_unchanged and not args.force_recovery):
        why = "--skip-recovery" if args.skip_recovery else "pck unchanged since last recovery"
        print(f"\n=== recovery skipped ({why}) ===")
        if not PCK_DIR.exists():
            raise SystemExit(f"{PCK_DIR} does not exist — a recovery is required at least once.")
    else:
        gdre = find_gdre(args.gdre)
        if not gdre or not gdre.exists():
            raise SystemExit(
                "GDRE Tools not found. Download a release and either pass --gdre <path>,\n"
                "set GDRE_TOOLS, or unpack it as ~/tools/GDRE_tools-<version>/gdre_tools.exe\n"
                "  https://github.com/GDRETools/gdsdecomp/releases")
        staging = ROOT / "pck_recover_new"
        shutil.rmtree(staging, ignore_errors=True)
        print(f"\n=== GDRE recovery ({gdre.name}) ===", flush=True)
        t0 = time.time()
        r = subprocess.run([str(gdre), "--headless", f"--recover={pck}", f"--output={staging}"])
        if r.returncode != 0 or not (staging / "images").exists():
            raise SystemExit(f"Recovery failed (exit {r.returncode}); left {staging} in place.")
        # Swap only once the new extraction looks sane, so a failed run never
        # destroys a working one.
        old = ROOT / "pck_recover_old"
        shutil.rmtree(old, ignore_errors=True)
        if PCK_DIR.exists():
            PCK_DIR.rename(old)
        staging.rename(PCK_DIR)
        shutil.rmtree(old, ignore_errors=True)
        print(f"--- recovery ok ({time.time()-t0:.0f}s)")

    # Assets before data: extract_card_data.py records relic imagePaths and
    # expects the files to already be there.
    run_step("portraits", ["tools/downscale_portraits.py"])
    run_step("relic/potion art + node icons", ["tools/downscale_art.py"])
    extract_out = run_step("card/relic data", ["tools/extract_card_data.py", str(dll)])
    run_step("card chrome", ["tools/bake_card_chrome.py"])
    run_step("finished cards", ["tools/bake_finished_cards.py"])
    run_step("thumbnails", ["tools/bake_thumbs.py"])

    problems, stats = completeness_report()
    # extract_card_data.py drops entries the localization doesn't know about
    # (a blank title renders worse than falling back to the prettified id).
    # Those rows are gone by the time completeness_report() runs, so surface
    # its warnings here — otherwise dropping them would hide the very skew
    # this script exists to catch.
    problems += [ln.strip().lstrip("! ") for ln in extract_out.splitlines()
                 if ln.strip().startswith("! skipped")]
    # release_info.json is the game's real build identity (version + commit +
    # build date) — its exe reports a placeholder 1.0.0.0. Record it here so a
    # later --stale check can compare versions instead of re-hashing the 2 GB
    # .pck. The hashes stay as ground truth; mtimes are the fallback for
    # installs without release_info.json.
    rel = read_release_info(game)

    PROVENANCE.write_text(json.dumps({
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gamePath": str(game),
        "gameVersion": (rel or {}).get("version"),
        "buildCommit": (rel or {}).get("commit"),
        "buildDate": (rel or {}).get("date"),
        "pckSha256": pck_hash,
        "pckModified": file_stamp(pck),
        "dllSha256": dll_hash,
        "dllModified": file_stamp(dll),
        "stats": stats,
        "problems": problems,
    }, indent=2), encoding="utf-8")

    print("\n=== summary ===")
    print(json.dumps(stats, indent=2))
    if problems:
        print("\nINCOMPLETE — the generated data has gaps:")
        for p in problems:
            print("  !", p)
        print("\nIf the DLL is newer than pck_recover_full/, re-run without --skip-recovery.")
        raise SystemExit(1)
    print("\nAll cards and relics have text and art. Wrote", PROVENANCE.name)


if __name__ == "__main__":
    main()
