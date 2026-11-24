"""
tools/art_manifest.py -- the served art, pinned in git.

The art folders (card_final/, thumbs/, ui_icons/, ...) are gitignored, and
every worktree reads the repo folder's copy. Whatever was on disk at deploy
time used to become the site's catalog, so a bake from a stale checkout
silently changed local, gamma and prod (2026-11-23: a pre-FB-45 map bake
dropped ui_icons/map/marked_x.png). tools/art_manifest.json lists every
served art file with its sha256, written by the bake scripts, so:

  * a re-bake shows up in `git diff tools/art_manifest.json`;
  * tools/deploy.py and tools/serve_site.py refuse to run when the art on
    disk differs from the manifest of the code being built;
  * bake scripts refuse to run from a checkout behind origin/gamma.

    python tools/art_manifest.py            check disk against the manifest
    python tools/art_manifest.py --write    rewrite the whole manifest from disk
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "tools" / "art_manifest.json"
# The folders tools/deploy.py uploads and build_site.py's catalog points at.
ART_DIRS = ["card_final", "card_portraits", "node_icons", "relic_images", "potion_images",
            "event_images", "enchantment_images", "ui_icons", "thumbs"]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan(root: Path = ROOT, prefixes=ART_DIRS) -> dict[str, str]:
    """{relative posix path: sha256} for every file under the given prefixes."""
    out = {}
    for prefix in prefixes:
        base = root / prefix
        if base.is_file():
            out[prefix] = _digest(base)
            continue
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                out[p.relative_to(root).as_posix()] = _digest(p)
    return out


def load(manifest: Path = MANIFEST) -> dict[str, str]:
    return json.loads(manifest.read_text(encoding="utf-8"))["files"]


def save(files: dict[str, str], manifest: Path = MANIFEST) -> None:
    body = {"note": "Written by the bake scripts (tools/art_manifest.py). Do not edit by hand.",
            "files": dict(sorted(files.items()))}
    manifest.write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")


def update(prefixes, root: Path = ROOT, manifest: Path = MANIFEST) -> None:
    """Re-record everything under prefixes (folders or files, relative to root) after a bake."""
    files = load(manifest) if manifest.exists() else {}
    for prefix in prefixes:
        p = prefix.rstrip("/")
        files = {k: v for k, v in files.items() if k != p and not k.startswith(p + "/")}
    files.update(scan(root, prefixes))
    save(files, manifest)
    print(f"art manifest: recorded {', '.join(prefixes)} -> {manifest.relative_to(root).as_posix()}")


def problems(art_root: Path, manifest: Path = MANIFEST) -> list[str]:
    """What differs between the art under art_root and the manifest: missing,
    changed and unlisted files. Empty when they match."""
    if not manifest.exists():
        return [f"{manifest.name} is missing: run `python tools/art_manifest.py --write` "
                f"after a bake from an up-to-date checkout and commit it"]
    want = load(manifest)
    have = scan(art_root)
    out = [f"missing: {k}" for k in sorted(want.keys() - have.keys())]
    out += [f"different: {k}" for k in sorted(k for k in want.keys() & have.keys() if want[k] != have[k])]
    out += [f"not in manifest: {k}" for k in sorted(have.keys() - want.keys())]
    return out


def require_match(art_root: Path, manifest: Path = MANIFEST, what: str = "this") -> None:
    found = problems(art_root, manifest)
    if found:
        shown = "\n  ".join(found[:20]) + (f"\n  ... and {len(found) - 20} more" if len(found) > 20 else "")
        raise SystemExit(
            f"Refusing to run {what}: the art in {art_root} doesn't match {manifest.name} "
            f"({len(found)} file(s)):\n  {shown}\n"
            "Re-bake from an up-to-date origin/gamma checkout (see README \"Art\"), "
            "or restore the art the manifest lists.")


def require_up_to_date(root: Path = ROOT) -> None:
    """Bake scripts call this first: a checkout behind origin/gamma would write
    an older bake over the shared art."""
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    git("fetch", "--quiet", "origin", "gamma")
    if git("rev-parse", "--verify", "--quiet", "refs/remotes/origin/gamma").returncode:
        raise SystemExit("Refusing to bake: no origin/gamma to compare this checkout with.")
    if git("merge-base", "--is-ancestor", "refs/remotes/origin/gamma", "HEAD").returncode:
        raise SystemExit("Refusing to bake: this checkout is behind origin/gamma. Bake from a "
                         "checkout of the current origin/gamma (or a branch that contains it).")


def main(argv) -> int:
    if "--write" in argv:
        save(scan())
        print(f"wrote {MANIFEST.relative_to(ROOT).as_posix()} ({len(load())} files)")
        return 0
    found = problems(ROOT)
    for line in found:
        print(line)
    print("art matches the manifest" if not found else f"{len(found)} difference(s)")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
