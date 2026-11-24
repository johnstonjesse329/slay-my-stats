"""
deploy.py — Push the committed site + infra to AWS.

Runs automatically from githooks/pre-push whenever main or gamma is pushed
(enable once per clone with `git config core.hooksPath githooks`), or by hand:

    infra\\.venv\\Scripts\\python.exe tools/deploy.py

Steps:
  0. Check site/pages/ file names, since the stack routes a URL per page.
  1. `cdk diff`. If the stack changed, print the diff and ask y/N before
     `cdk deploy`. No changes -> skip straight to the site.
  2. `build_site.py`, then upload only changed site files and art. Site files are compared
     with top-level S3 objects. Art is compared with the stage's content manifest.
  3. Prod only: CloudFront invalidation of the uploaded paths that keep their
     name (index.html, the manifest, art; /* past ten of them). Content-hashed
     files are new names, never cached, so they're left out. Gamma's CloudFront
     caches nothing, so it never invalidates. The first 1,000 paths a month are
     free, across both stages.

Neither upload re-sends a file whose bytes didn't change, so a new
Cache-Control value won't reach what's already up there. Push it to the whole
bucket by hand, once, with `tools/deploy.py --reheader`.

`--stage gamma` deploys the same checkout to gamma.slay-my-stats.com instead: a
separate copy of the stack for trying a change against real CloudFront first.
Pushing the gamma branch does the same; pushing main always deploys production.

    infra\\.venv\\Scripts\\python.exe tools/deploy.py --stage gamma

`--reheader` takes `--stage` too. `DEPLOY_YES=1` skips the y/N on gamma's stack changes, so
it can run with nobody at the terminal. Production only skips it for `DEPLOY_YES=prod`, a
value nothing sets by accident: the prompt reads the console, so without it a push run by
an agent or an editor just stalls there.

After the stack step, the ingest Function URL gets an empty POST. Any answer below 500 means the
function started (it answers 404 there: uploads come through /auth/upload, the mod through /mod); a 5xx or no answer fails the
deploy before the site goes up, which is how a bundle that crashes on import (a 502 for every
upload from the mod) gets caught on gamma rather than found in the mod's log.

After smoke checks, a changed parser version or known-ID list triggers a profile and stats rebuild.
Each stage records the inputs of its last successful rebuild in its own data bucket. A failure
warns and leaves the previous marker in place so the next deploy retries.

Production only deploys a commit that gamma has already deployed and passed that check on. A
successful gamma deploy of a commit writes it to `slay-my-stats-gamma-ok` inside the git directory
(shared by worktrees); a prod deploy of any other commit stops. `DEPLOY_SKIP_GAMMA=1` overrides it for
a hotfix.

A push deploys the pushed commit, not whatever the checkout holds: the commit is exported with
`git archive` to the main checkout's `local_data/deploy-build/` and built there, borrowing the main
checkout's ignored inputs (the infra venv, `infra/cdk.context.json`, the game art and data). So a push
can go from any worktree, and no checkout has to be clean or on that commit. By hand, `--ref <commit>`
does the same; without `--ref` the working tree is deployed as it is, uncommitted changes and all.

    infra\\.venv\\Scripts\\python.exe tools/deploy.py --stage gamma --ref origin/gamma

Only one deploy runs at a time, of any stage or stack, across every checkout and worktree: each takes
`slay-my-stats-deploy.lock` in the git directory first, and a second one stops, saying who holds it,
from which commit and since when. A deploy that dies without releasing it (a closed terminal) leaves
it behind; after checking nothing is still deploying:

    infra\\.venv\\Scripts\\python.exe tools/deploy.py --lock-status
    infra\\.venv\\Scripts\\python.exe tools/deploy.py --break-lock

The feedback table both stages share (infra/slay_my_stats/feedback_stack.py) is its own stack, and
no push touches it. Deploy it by hand, with its diff and a y/N, only when that file changes:

    infra\\.venv\\Scripts\\python.exe tools/deploy.py --feedback-table

That records the commit in `slay-my-stats-feedback-ok` in the git directory. A push stops while the
file differs from what was last deployed, so a stage never ships code for a table that isn't there.

The alarms on prod's CloudFront metrics (infra/slay_my_stats/edge_alarms_stack.py) are a stack in
us-east-1, where CloudFront's metrics are. No push touches it either; deploy it by hand, with its
diff and a y/N, when that file changes:

    infra\\.venv\\Scripts\\python.exe tools/deploy.py --edge-alarms

Skip the whole thing for one push with `SKIP_DEPLOY=1 git push` or
`git push --no-verify`.
"""

import contextlib
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import io
import json
import mimetypes
import re
import os
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
# SRC is where the code being deployed is built from; LOCAL holds the ignored inputs every build
# needs (the infra venv, infra/cdk.context.json, the game art and data). main() points LOCAL at the
# main checkout, and SRC at a fresh export when deploying a commit (see export_commit()).
SRC = _HERE
LOCAL = _HERE
# Production's names; use_stage() swaps in another stage's. They mirror what
# infra/slay_my_stats/slay_my_stats_stack.py names things per stage.
SITE_BUCKET = "slay-my-stats-site"
DOMAIN_NAME = "slay-my-stats.com"
STACK_NAME = "SlayMyStatsStack"
STAGES = {
    "prod": (SITE_BUCKET, DOMAIN_NAME, STACK_NAME),
    "gamma": ("slay-my-stats-gamma-site", "gamma.slay-my-stats.com", "SlayMyStatsGammaStack"),
}
# The data bucket each stage's profiles live in (infra/slay_my_stats/slay_my_stats_stack.py).
# The shared feedback table's stack and the one file that defines it.
FEEDBACK_STACK = "SlayMyStatsFeedbackStack"
FEEDBACK_STACK_FILE = "infra/slay_my_stats/feedback_stack.py"
# The us-east-1 alarms on prod's CloudFront metrics.
EDGE_ALARMS_STACK = "SlayMyStatsEdgeAlarmsStack"
DATA_BUCKETS = {"prod": "slay-my-stats-data", "gamma": "slay-my-stats-gamma-data"}
PROFILE_REBUILD_KEY = "analytics/deploy/profile-rebuild.json"
ART_MANIFEST_KEY = "analytics/deploy/art-manifest.json"
# Pushing one of these branches deploys its stage (see check_pre_push).
DEPLOY_BRANCHES = {"main": "prod", "gamma": "gamma"}
# One deploy at a time, across every checkout and worktree: this file in the git directory they share.
LOCK_NAME = "slay-my-stats-deploy.lock"
# Past this, the holder has most likely died without releasing it. Still never taken over on its
# own (a long cdk deploy is possible); the refusal just says so and points at --break-lock.
LOCK_STALE_MINUTES = 60
# A deployed commit is built here, under the main checkout (gitignored, and on its drive).
EXPORT_DIR = Path("local_data") / "deploy-build"
# Ignored top-level entries of the main checkout that an export does NOT borrow: outputs, caches
# and scratch rather than inputs. Everything else ignored at the top (the art folders and the game
# data JSONs) is linked or copied in, so a new data file needs no change here.
NOT_INPUTS = {"dist", "local_data", "output", "__pycache__", ".playwright-mcp", "cdk.out"}
# Mirrors the root-absolute art paths build_site.py's catalog points at.
BAKED_ART_DIRS = ("card_final", "card_portraits", "node_icons", "relic_images", "potion_images",
                  "event_images", "enchantment_images", "ui_icons", "thumbs")
COMMITTED_ART_DIRS = ("encounter_art",)
ART_DIRS = (*BAKED_ART_DIRS, *COMMITTED_ART_DIRS)
ZERO_SHA = "0" * 40

# Art is the bulk of what the site serves -- one Run Detail session pulls a few
# hundred card faces and relic images -- and it changes only when the game does.
# Without a Cache-Control header the browser just guesses, and re-asks
# CloudFront for art it already has, which is the site's largest source of
# requests. 30 days takes almost all of those repeat requests away while
# keeping the blast radius small: art filenames aren't content-hashed, so a
# re-baked card is stale for returning visitors until their copy expires, and a
# month is short enough to ride out after a patch without renaming every file.
# A CloudFront invalidation clears the edge but never a browser's own cache.
ART_CACHE_CONTROL = "public, max-age=2592000"

# The dist/ files that aren't content-hashed (index.html, the manifest, the
# fonts and previews) can change with a deploy, so browsers get five minutes: enough that
# moving around the site doesn't re-ask for 600 KB of script and catalog, short
# enough that a deploy reaches someone already on the site almost at once.
# HTML is the entry point, so browsers always check it (a 304 when unchanged).
# s-maxage is for CloudFront alone: every prod deploy invalidates what it uploads,
# so the edge can hold a file for a day rather than going back to S3 every
# five minutes -- or on every single request, for the HTML.
DIST_CACHE_CONTROL = "public, max-age=300, s-maxage=86400"
HTML_CACHE_CONTROL = "public, max-age=0, must-revalidate, s-maxage=86400"

# What reheader() stamps back on, by extension: everything build_site.py writes
# to dist/, and the two image types the art folders hold.
CONTENT_TYPES = {
    ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
    ".png": "image/png", ".webp": "image/webp", ".woff2": "font/woff2", ".txt": "text/plain",
}
ART_EXTENSIONS = [".png", ".webp"]


# build_site.py names app, catalog, boot and the CSS/JS after a hash of their
# content (app.3fa91c20ab.js), so one name is one file forever: a year, immutable.
HASHED_CACHE_CONTROL = "public, max-age=31536000, immutable"
_HASHED_KEY = re.compile(r"\.[0-9a-f]{10}\.(js|css|json)$")


def dist_cache_control(key: str) -> str:
    if _HASHED_KEY.search(key):
        return HASHED_CACHE_CONTROL
    return HTML_CACHE_CONTROL if key.endswith(".html") else DIST_CACHE_CONTROL


class DeployError(Exception):
    pass


def set_stage(stage: str) -> None:
    """Point the deploy at a stage's bucket, domain and stack."""
    global SITE_BUCKET, DOMAIN_NAME, STACK_NAME
    SITE_BUCKET, DOMAIN_NAME, STACK_NAME = STAGES[stage]


def use_stage(argv) -> str:
    """Point the deploy at the stage named by `--stage <name>` (default prod)."""
    stage = argv[argv.index("--stage") + 1] if "--stage" in argv[:-1] else "prod"
    if "--stage" in argv[-1:] or stage not in STAGES:
        raise DeployError(f"--stage takes one of: {', '.join(STAGES)}")
    set_stage(stage)
    return stage


def run(args, *, cwd=None, env=None, capture=False, stream=False) -> subprocess.CompletedProcess:
    """
    Run a command with stdin detached (in pre-push, stdin is git's ref list).
    capture: collect output silently (printed only on failure).
    stream: print output live as it arrives and also collect it, for slow
    steps whose output the caller still needs (such as cdk diff), so the
    push doesn't sit silent for minutes.
    """
    cwd = SRC if cwd is None else cwd
    exe = shutil.which(args[0])
    if exe is None:
        raise DeployError(f"'{args[0]}' is not on PATH")
    print("$", " ".join(args), flush=True)
    if stream:
        proc = subprocess.Popen(
            [exe, *args[1:]], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        lines = []
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.append(line)
        result = subprocess.CompletedProcess(proc.args, proc.wait(), "".join(lines), "")
    else:
        result = subprocess.run(
            [exe, *args[1:]], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            capture_output=capture, text=True, encoding="utf-8", errors="replace",  # cdk prints ✨ and └─
        )
    if result.returncode != 0:
        if capture:
            print(result.stdout + result.stderr)
        raise DeployError(f"{args[0]} exited with {result.returncode}")
    return result


def git(*args, cwd=None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd or _HERE, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.strip()


def ask(question: str) -> bool:
    """
    y/N from the terminal itself, since stdin belongs to git in pre-push.
    No terminal (e.g. pushing from an editor's git UI) counts as "no".
    """
    tty = "CONIN$" if os.name == "nt" else "/dev/tty"
    try:
        with open(tty, "r") as con:
            print(f"{question} [y/N] ", end="", flush=True)
            return con.readline().strip().lower() in ("y", "yes")
    except OSError:
        print(f"{question} -- no terminal to answer on, treating as no.")
        return False


def check_pre_push(ref_lines) -> str | None:
    """
    Decide from git's pre-push stdin what this push deploys: the stage
    DEPLOY_BRANCHES names for the branch being pushed and the commit going up,
    or None when it is neither branch. The commit is built from an export, so
    the checkout it is pushed from needn't be on it or clean.
    """
    pushed = {}
    for line in ref_lines:
        parts = line.split()
        if len(parts) == 4 and parts[1] != ZERO_SHA and parts[2].startswith("refs/heads/"):
            branch = parts[2].removeprefix("refs/heads/")
            if branch in DEPLOY_BRANCHES:
                pushed[branch] = parts
    if not pushed:
        return None
    if len(pushed) > 1:
        raise DeployError(f"pushing {' and '.join(pushed)} in one go -- push them one at a time, "
                          "since each push deploys its stage")

    (branch, (_, local_sha, _, remote_sha)), = pushed.items()
    # gamma gets pointed at whatever is being tried next, so a forced push is
    # normal there, and the hook can't tell one from a push git will reject.
    if branch == "main" and remote_sha != ZERO_SHA:
        ff = subprocess.run(["git", "merge-base", "--is-ancestor", remote_sha, local_sha],
                            cwd=_HERE, stdin=subprocess.DEVNULL, capture_output=True)
        if ff.returncode != 0:
            raise DeployError("not a fast-forward of origin/main (fetch first) -- the push would be rejected after deploying")
    return DEPLOY_BRANCHES[branch], local_sha


def use_ref(argv) -> str | None:
    """The commit `--ref <commit, branch or tag>` names, or None to deploy the working tree."""
    if "--ref" not in argv:
        return None
    i = argv.index("--ref")
    if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
        raise DeployError("--ref takes a commit, branch or tag")
    sha = git("rev-parse", "--verify", "--quiet", argv[i + 1] + "^{commit}")
    if not sha:
        raise DeployError(f"--ref {argv[i + 1]}: no such commit here (git fetch first?)")
    return sha


def _venv_bin() -> Path:
    return LOCAL / "infra" / ".venv" / ("Scripts" if os.name == "nt" else "bin")


def _git_common() -> Path:
    common = Path(git("rev-parse", "--git-common-dir"))
    return common if common.is_absolute() else (_HERE / common).resolve()


def main_checkout() -> Path:
    """The checkout the git directory belongs to, where the ignored inputs live for every worktree."""
    common = _git_common()
    return common.parent if common.name == ".git" and common.parent.is_dir() else _HERE


# ---- one deploy at a time ----

_lock_held: Path | None = None


def _read_lock(f: Path) -> dict:
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # gone, or its holder hasn't finished writing it


def _lock_age_minutes(info: dict) -> float | None:
    try:
        return (time.time() - float(info["since"])) / 60
    except (KeyError, TypeError, ValueError):
        return None


def describe_lock(info: dict) -> str:
    age = _lock_age_minutes(info)
    commit = info.get("commit") or ""
    return (f"{info.get('what', 'a deploy')} of {commit[:7] or 'a working tree'}, started "
            f"{info.get('started', '?')}" + (f" ({age:.0f} min ago)" if age is not None else "")
            + f", from {info.get('checkout', '?')} (pid {info.get('pid', '?')} on {info.get('host', '?')})")


@contextlib.contextmanager
def deploy_lock(what: str, commit: str | None):
    """Hold the deploy lock for the block; a second deploy anywhere in the repo stops instead."""
    global _lock_held
    f = _git_common() / LOCK_NAME
    info = {"what": what, "commit": commit, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "since": time.time(), "checkout": str(_HERE), "pid": os.getpid(), "host": socket.gethostname()}
    try:
        fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        held = _read_lock(f)
        age = _lock_age_minutes(held)
        if age is not None and age > LOCK_STALE_MINUTES:
            hint = (f"It has held the lock for over {LOCK_STALE_MINUTES} minutes, so it most likely died. "
                    "Check nothing is still deploying, then: tools/deploy.py --break-lock")
        else:
            hint = "Wait for it to finish and try again (tools/deploy.py --lock-status shows it)."
        raise DeployError(f"another deploy is running: {describe_lock(held)}. {hint}")
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(info, out)
    _lock_held = f
    try:
        yield
    finally:
        held = _read_lock(f)
        # Only ever remove our own lock, not one taken after a --break-lock.
        if held.get("pid") == info["pid"] and held.get("since") == info["since"]:
            with contextlib.suppress(FileNotFoundError):
                f.unlink()
        _lock_held = None


def lock_status(break_it: bool) -> None:
    f = _git_common() / LOCK_NAME
    if not f.exists():
        print("No deploy is running.")
        return
    print("Deploy lock held by: " + describe_lock(_read_lock(f)))
    if break_it:
        f.unlink()
        print("Lock removed.")


# ---- building a commit, not a checkout ----

def _is_link(p: Path) -> bool:
    """A symlink, or a Windows junction (which is_symlink() doesn't report before Python 3.12)."""
    if p.is_symlink():
        return True
    attrs = getattr(os.lstat(p), "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _link_dir(target: Path, link: Path) -> None:
    if os.name == "nt":
        # A junction needs neither admin rights nor developer mode, unlike a directory symlink.
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if r.returncode:
            raise DeployError(f"could not link {link} to {target}: {r.stdout}{r.stderr}".strip())
    else:
        link.symlink_to(target, target_is_directory=True)


def remove_export(out: Path) -> None:
    """Delete an export, unlinking its borrowed folders first so nothing is deleted through them."""
    if not out.exists():
        return
    assert out.name == EXPORT_DIR.name and out.parent.name == EXPORT_DIR.parent.name, out
    for child in out.iterdir():
        if _is_link(child):
            os.rmdir(child) if os.name == "nt" else child.unlink()
    shutil.rmtree(out)


def export_commit(commit: str) -> Path:
    """
    Write `commit`'s tracked files to LOCAL/EXPORT_DIR and borrow the main checkout's ignored
    inputs: folders as links (the art is thousands of files), files as copies, and
    infra/cdk.context.json, which cdk reads from its own folder. Returns the export.
    """
    out = LOCAL / EXPORT_DIR
    remove_export(out)  # a deploy that died part-way leaves one; the lock says no one is using it
    out.mkdir(parents=True)
    print(f"Build: exporting {commit[:7]} to {out}...", flush=True)
    tar = subprocess.run(["git", "archive", "--format=tar", commit], cwd=_HERE,
                         stdin=subprocess.DEVNULL, capture_output=True)
    if tar.returncode:
        raise DeployError("git archive failed: " + tar.stderr.decode(errors="replace").strip())
    with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as t:
        t.extractall(out, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))

    listed = git("ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory", cwd=LOCAL)
    borrowed = []
    # An older main checkout may lack the commit's ignore rule for a new art folder.
    for entry in (*listed.split("\0"), *BAKED_ART_DIRS):
        if not entry:
            continue
        name = entry.rstrip("/")
        if ("/" in name and name != "infra/cdk.context.json") or name in NOT_INPUTS:
            continue
        src, dst = LOCAL / name, out / name
        if dst.exists() or not src.exists():
            continue
        if src.is_dir():
            _link_dir(src, dst)
        else:
            shutil.copy2(src, dst)
        borrowed.append(name)
    print(f"Build: borrowed from {LOCAL}: {', '.join(sorted(borrowed)) or 'nothing'}")
    return out


def finish_export(out: Path) -> None:
    """Keep anything cdk added to the export's cdk.context.json (context lookups), then delete the export."""
    ctx, home = out / "infra" / "cdk.context.json", LOCAL / "infra" / "cdk.context.json"
    if ctx.exists() and home.exists() and ctx.read_bytes() != home.read_bytes():
        shutil.copy2(ctx, home)
        print(f"Note: cdk updated cdk.context.json; copied it back to {home}.")
    remove_export(out)


def _cdk_env() -> dict:
    # cdk.json runs `python app.py`; put the infra venv first so that resolves
    # to the interpreter with aws_cdk installed.
    venv_bin = _venv_bin()
    return {**os.environ, "PATH": f"{venv_bin}{os.pathsep}{os.environ['PATH']}"}


def deploy_infra() -> None:
    """Deploy the stack if it differs."""
    env = _cdk_env()
    print("Infra: comparing the stack with AWS (cdk diff, usually a minute or two)...", flush=True)
    output = run(["cdk", "diff", STACK_NAME], cwd=SRC / "infra", env=env, stream=True).stdout
    if "There were no differences" in output:
        print("Infra: no changes.")
        return
    # DEPLOY_YES answers the question up front, for a run with nobody at the terminal.
    # Any value does it for gamma; production wants the word "prod", so a stray
    # DEPLOY_YES=1 left in the environment can't ship a production stack change.
    yes = os.environ.get("DEPLOY_YES", "")
    if (STACK_NAME == STAGES["gamma"][2] and yes) or (STACK_NAME == STAGES["prod"][2] and yes == "prod"):
        print(f"Infra: deploying these changes (DEPLOY_YES={yes}).")
    elif not ask("Deploy these infra changes?"):
        raise DeployError("infra deploy declined")
    run(["cdk", "deploy", STACK_NAME, "--require-approval", "never"], cwd=SRC / "infra", env=env)


def profile_rebuild_inputs() -> dict:
    """Read the parser version and the stats layout, and generate the same known-ID list CDK packages."""
    src = (SRC / "run.py").read_text(encoding="utf-8")
    version = re.search(r"^PARSER_VERSION = (\d+)\s*$", src, re.MULTILINE)
    if version is None:
        raise DeployError("Could not read PARSER_VERSION from run.py")
    # The site-wide stats are only complete when counted from empty, and the pages hide
    # the "All players" columns of a total counted with an older layout (pickSlots, ...),
    # so changing the layout alone must trigger a recount too.
    handler_src = (SRC / "infra" / "lambda" / "ingest" / "handler.py").read_text(encoding="utf-8")
    layout = [re.search(rf"^{name} = (\d+)\s*$", handler_src, re.MULTILINE)
              for name in ("PICK_SLOTS", "ASC_PICK_VERSION", "EVENTS_VERSION", "OFFERS_VERSION")]
    if not all(layout):
        raise DeployError("Could not read the stats layout (PICK_SLOTS, ASC_PICK_VERSION, EVENTS_VERSION, OFFERS_VERSION) from handler.py")
    known = None
    if all((SRC / name).is_file() for name in ("card_data.json", "relic_data.json")):
        spec = importlib.util.spec_from_file_location("deploy_known_ids", SRC / "tools" / "build_known_ids.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        known = hashlib.sha256(json.dumps(mod.load(), separators=(",", ":")).encode()).hexdigest()
    return {"parser_version": int(version[1]), "stats_layout": ".".join(m[1] for m in layout), "known_ids_sha256": known}


def rebuild_held_runs(stage: str) -> None:
    """Refresh profiles and stats only for inputs the stage has yet to rebuild."""
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    bucket = DATA_BUCKETS[stage]
    python = _venv_bin() / ("python.exe" if os.name == "nt" else "python")
    try:
        inputs = profile_rebuild_inputs()
        s3 = boto3.client("s3")
        try:
            marker = s3.get_object(Bucket=bucket, Key=PROFILE_REBUILD_KEY)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("NoSuchKey", "404"):
                raise
            marker = None
        previous = None
        if marker:
            try:
                previous = json.loads(marker["Body"].read())
            except ValueError:
                pass  # Rebuild and replace an unreadable marker.
        if previous == inputs:
            print(f"Runs: {stage} parser version and known IDs match the last successful rebuild. Skipping.")
            return
        labels = {"parser_version": "parser version", "stats_layout": "stats layout", "known_ids_sha256": "known IDs"}
        changed = ", ".join(labels[key] for key in inputs
                            if not isinstance(previous, dict) or previous.get(key) != inputs[key])
        print(f"Runs: rebuilding {stage} profiles and stats ({changed})...", flush=True)
        run([str(python), str(SRC / "tools" / "rebuild_profiles.py"), "--all", "--strict", "--bucket", bucket], stream=True)
        run([str(python), str(SRC / "tools" / "rebuild_stats.py"), "--bucket", bucket], stream=True)
        condition = {"IfMatch": marker["ETag"]} if marker else {"IfNoneMatch": "*"}
        s3.put_object(Bucket=bucket, Key=PROFILE_REBUILD_KEY,
                      Body=json.dumps(inputs).encode(), ContentType="application/json", **condition)
    except (BotoCoreError, ClientError, DeployError, OSError, ValueError) as exc:
        print(f"Warning: {stage} profile rebuild did not complete ({exc}). The next deploy will retry.",
              file=sys.stderr)


def upload_changed_dist() -> list[str]:
    """
    Upload only the dist/ files whose content differs from S3. `aws s3 sync`
    can't tell: build_site.py rewrites every file, so all of them always look
    newer. Compares MD5 against the S3 ETag, which is the MD5 for any object
    uploaded in one part (dist files are far below the CLI's 8 MB multipart
    threshold). Returns the uploaded keys.
    """
    listing = run([
        "aws", "s3api", "list-objects-v2", "--bucket", SITE_BUCKET, "--delimiter", "/", "--output", "json",
        "--query", "Contents[].[Key, ETag]",
    ], capture=True).stdout
    remote = {key: etag.strip('"') for key, etag in (json.loads(listing) or [])}

    dist = SRC / "dist"
    uploaded = []
    for f in sorted(p for p in dist.rglob("*") if p.is_file()):
        key = f.relative_to(dist).as_posix()
        if remote.get(key) == hashlib.md5(f.read_bytes()).hexdigest():
            continue
        run(["aws", "s3", "cp", str(f), f"s3://{SITE_BUCKET}/{key}", "--no-progress",
             "--content-type", CONTENT_TYPES[f.suffix],
             "--cache-control", dist_cache_control(key)])
        uploaded.append(key)
    return uploaded


def check_art() -> None:
    """Stop unless the art on disk (LOCAL) is exactly what the deployed commit's
    tools/art_manifest.json lists, so a stale or partial bake can't become the catalog."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("art_manifest", Path(__file__).with_name("art_manifest.py"))
    art_manifest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(art_manifest)
    try:
        art_manifest.require_match(LOCAL, SRC / "tools" / "art_manifest.json", "the deploy")
    except SystemExit as e:
        raise DeployError(str(e))
    print("Site: art matches tools/art_manifest.json.", flush=True)


def art_source(folder: str) -> Path:
    """Use the exported commit for tracked art and the main checkout for baked inputs."""
    return SRC if folder in COMMITTED_ART_DIRS else LOCAL


def art_digests() -> dict[str, str]:
    digests = {}
    for folder in ART_DIRS:
        source = art_source(folder)
        root = source / folder
        if not root.is_dir():
            raise DeployError(f"Missing art folder: {root}")
        for path in sorted(root.rglob("*")):
            if path.is_file():
                digests[path.relative_to(source).as_posix()] = hashlib.md5(path.read_bytes()).hexdigest()
    return digests


def save_art_manifest(s3, bucket: str, digests: dict, etag: str | None) -> str:
    condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
    return s3.put_object(Bucket=bucket, Key=ART_MANIFEST_KEY, Body=json.dumps(digests).encode(),
                         ContentType="application/json", **condition)["ETag"]


def read_art_manifest(s3, bucket: str, digests: dict) -> tuple[dict, str]:
    from botocore.exceptions import ClientError

    try:
        obj = s3.get_object(Bucket=bucket, Key=ART_MANIFEST_KEY)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("NoSuchKey", "404"):
            raise
    else:
        with obj["Body"] as body:
            return json.load(body), obj["ETag"]

    # Seed from existing content so the first deploy only sends objects whose bytes differ.
    # Record the baseline before uploading so a failed invalidation can be retried on the next deploy.
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=SITE_BUCKET)
    remote = {obj["Key"]: obj["ETag"].strip('"') for page in pages for obj in page.get("Contents", [])
              if obj["Key"] in digests}
    return remote, save_art_manifest(s3, bucket, remote, None)


def upload_art_object(s3, key: str, digest: str) -> None:
    path = art_source(key.partition("/")[0]) / key
    content_type = CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as body:
        s3.put_object(Bucket=SITE_BUCKET, Key=key, Body=body, CacheControl=ART_CACHE_CONTROL,
                      ContentType=content_type, ContentMD5=base64.b64encode(bytes.fromhex(digest)).decode())


def reheader(stage: str) -> None:
    """
    Set the Cache-Control values above on everything already in the bucket,
    then invalidate it (prod; gamma's CloudFront caches nothing).

    A normal deploy only sends files whose content
    changed, so anything uploaded before these headers existed -- and any art
    folder the game didn't change this round -- would keep serving no
    Cache-Control forever. This rewrites each object's metadata in place (an
    S3-to-S3 copy, so no bytes leave this machine).

    Replacing metadata replaces all of it, Content-Type included, and for a
    copy within S3 the CLI doesn't guess one from the extension the way an
    upload does: left alone, every file comes back as binary/octet-stream and
    the browser downloads index.html instead of showing it. So the type is
    passed explicitly, from CONTENT_TYPES.

    The invalidation is the point, not an afterthought: CloudFront stores a
    response's headers alongside its body, so every edge keeps handing out the
    old header-less response until its own copy expires.

    Run by hand after changing any of the *_CACHE_CONTROL values:
        python tools/deploy.py --reheader
    """
    # The same top-level keys upload_changed_dist() compares against.
    listing = run([
        "aws", "s3api", "list-objects-v2", "--bucket", SITE_BUCKET, "--delimiter", "/", "--output", "json",
        "--query", "Contents[].Key",
    ], capture=True).stdout
    keys = json.loads(listing) or []
    unknown = [key for key in keys if Path(key).suffix not in CONTENT_TYPES]
    if unknown:
        raise DeployError(f"no Content-Type known for {', '.join(unknown)} -- add it to CONTENT_TYPES")
    for key in keys:
        run(["aws", "s3", "cp", f"s3://{SITE_BUCKET}/{key}", f"s3://{SITE_BUCKET}/{key}",
             "--no-progress", "--metadata-directive", "REPLACE",
             "--content-type", CONTENT_TYPES[Path(key).suffix],
             "--cache-control", dist_cache_control(key)])
    for d in ART_DIRS:
        # One pass per image type, since a folder can hold both.
        for ext in ART_EXTENSIONS:
            print(f"Site: re-heading {d}/*{ext}...", flush=True)
            run(["aws", "s3", "cp", f"s3://{SITE_BUCKET}/{d}/", f"s3://{SITE_BUCKET}/{d}/",
                 "--recursive", "--no-progress", "--exclude", "*", "--include", f"*{ext}",
                 "--metadata-directive", "REPLACE",
                 "--content-type", CONTENT_TYPES[ext],
                 "--cache-control", ART_CACHE_CONTROL], stream=True)
    if stage == "prod":
        invalidate(["/*"])


def invalidate(paths: list[str]) -> None:
    """Drop these paths from every CloudFront edge. Each counts against the 1,000 free a month."""
    dist_id = run([
        "aws", "cloudfront", "list-distributions", "--output", "text",
        "--query", f"DistributionList.Items[?contains(Aliases.Items, '{DOMAIN_NAME}')].Id",
    ], capture=True).stdout.strip()
    if not dist_id:
        raise DeployError(f"no CloudFront distribution found for {DOMAIN_NAME}")
    run(["aws", "cloudfront", "create-invalidation", "--distribution-id", dist_id,
         "--paths", *paths, "--output", "text", "--query", "Invalidation.Id"])


def ingest_function_url() -> str:
    """The ingest Lambda's Function URL, from the deployed stack's outputs."""
    url = run([
        "aws", "cloudformation", "describe-stacks", "--stack-name", STACK_NAME, "--output", "text",
        "--query", "Stacks[0].Outputs[?OutputKey=='IngestFunctionUrl'].OutputValue",
    ], capture=True).stdout.strip()
    if not url.startswith("https://"):
        raise DeployError("stack has no IngestFunctionUrl output")
    return url


def smoke_test_ingest(url: str) -> None:
    """
    POST an empty body to the ingest Function URL. The function rejects it (404: nothing is
    served at its root), and that is the pass: it started and answered. A 5xx is Lambda reporting that the
    code failed to load or crashed (a bad import answers 502 to every upload), and no answer at
    all is as bad, so either fails the deploy.
    """
    print(f"Check: ingest function answers ({url})...", flush=True)
    req = urllib.request.Request(url, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    except OSError as e:
        raise DeployError(f"ingest function did not answer: {e}")
    if status >= 500:
        raise DeployError(f"ingest function answered {status} to an empty request -- it is failing "
                          "(likely at import); every upload from the mod would get this. "
                          f"See the {STACK_NAME} Ingest log group in CloudWatch.")
    print(f"Check: ingest function answered {status}, so it starts.")


def _gamma_ok_file() -> Path:
    return _git_common() / "slay-my-stats-gamma-ok"


def record_gamma_ok(commit: str | None) -> None:
    """Remember the commit gamma just deployed and passed the check on. A dirty tree isn't a commit, so it records nothing."""
    if commit:
        _gamma_ok_file().write_text(commit, encoding="utf-8")


def require_gamma_ok(commit: str | None) -> None:
    """Production only takes a commit gamma has already deployed and passed. DEPLOY_SKIP_GAMMA=1 overrides."""
    if os.environ.get("DEPLOY_SKIP_GAMMA") == "1":
        print("Check: skipping the gamma gate (DEPLOY_SKIP_GAMMA=1).")
        return
    head = commit or git("rev-parse", "HEAD")
    f = _gamma_ok_file()
    ok = f.read_text(encoding="utf-8").strip() if f.exists() else ""
    if ok != head:
        raise DeployError(f"gamma hasn't deployed and passed this commit ({head[:7]}"
                          + (f"; it last passed {ok[:7]}" if ok else "; it has no pass recorded") + "). "
                          "Push it to gamma first: DEPLOY_YES=1 git push origin main:gamma. "
                          "For a hotfix, DEPLOY_SKIP_GAMMA=1.")


def _feedback_ok_file() -> Path:
    return _gamma_ok_file().with_name("slay-my-stats-feedback-ok")


def deploy_feedback_table() -> None:
    """Deploy the feedback table's stack: its diff, then a y/N (only DEPLOY_YES=feedback skips it,
    since the table holds every note). Records the commit when the file is committed as deployed."""
    env = _cdk_env()
    print("Feedback table: comparing its stack with AWS (cdk diff)...", flush=True)
    output = run(["cdk", "diff", FEEDBACK_STACK], cwd=SRC / "infra", env=env, stream=True).stdout
    if "There were no differences" in output:
        print("Feedback table: no changes.")
    else:
        if os.environ.get("DEPLOY_YES") == "feedback":
            print("Feedback table: deploying these changes (DEPLOY_YES=feedback).")
        elif not ask("Deploy these feedback table changes?"):
            raise DeployError("feedback table deploy declined")
        run(["cdk", "deploy", FEEDBACK_STACK, "--exclusively", "--require-approval", "never"], cwd=SRC / "infra", env=env)
    if git("status", "--porcelain", "--", FEEDBACK_STACK_FILE):
        print(f"Note: {FEEDBACK_STACK_FILE} has uncommitted changes, so no deploy is recorded; "
              "commit it and run --feedback-table again.")
        return
    _feedback_ok_file().write_text(git("rev-parse", "HEAD"), encoding="utf-8")
    print("Feedback table: deployed; recorded.")


def deploy_edge_alarms() -> None:
    """Deploy the CloudFront alarms' stack: its diff, then a y/N (DEPLOY_YES=edge skips it). Nothing
    gates a push on it: the alarms watch the site, the site never calls them."""
    env = _cdk_env()
    print("Edge alarms: comparing their stack with AWS (cdk diff)...", flush=True)
    output = run(["cdk", "diff", EDGE_ALARMS_STACK], cwd=SRC / "infra", env=env, stream=True).stdout
    if "There were no differences" in output:
        print("Edge alarms: no changes.")
        return
    if os.environ.get("DEPLOY_YES") == "edge":
        print("Edge alarms: deploying these changes (DEPLOY_YES=edge).")
    elif not ask("Deploy these edge alarm changes?"):
        raise DeployError("edge alarms deploy declined")
    run(["cdk", "deploy", EDGE_ALARMS_STACK, "--exclusively", "--require-approval", "never"], cwd=SRC / "infra", env=env)
    print("Edge alarms: deployed. A first deploy emails a subscription link; confirm it.")


def require_feedback_table(commit: str | None) -> None:
    """Stop a deploy while the feedback stack's file (in `commit`, or the working tree) differs from its last --feedback-table deploy."""
    f = _feedback_ok_file()
    done = f.read_text(encoding="utf-8").strip() if f.exists() else ""
    if not done:
        raise DeployError("the feedback table has no deploy recorded. "
                          "Run tools/deploy.py --feedback-table first.")
    if git("diff", "--name-only", done, *([commit] if commit else []), "--", FEEDBACK_STACK_FILE):
        raise DeployError(f"{FEEDBACK_STACK_FILE} changed since the feedback table was last deployed "
                          f"({done[:7]}). Run tools/deploy.py --feedback-table first.")


def deploy_site(stage: str) -> None:
    import boto3

    check_art()
    print("Site: building dist/...", flush=True)
    run([sys.executable, str(SRC / "build_site.py")])
    s3 = boto3.client("s3")
    bucket = DATA_BUCKETS[stage]
    art = art_digests()
    deployed_art, art_etag = read_art_manifest(s3, bucket, art)
    changed_art = {key: digest for key, digest in art.items() if deployed_art.get(key) != digest}
    if changed_art:
        print(f"Site: uploading {len(changed_art)} changed art files...", flush=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda item: upload_art_object(s3, *item), changed_art.items()))
    else:
        print(f"Site: art unchanged ({len(art)} files).", flush=True)

    print("Site: uploading changed dist/ files...", flush=True)
    changed = [*changed_art, *upload_changed_dist()]
    # A content-hashed name was never requested before this upload, so no edge holds it.
    stale = [key for key in changed if not _HASHED_KEY.search(key)]
    if not stale:
        print("Site: nothing cached changed, skipping CloudFront invalidation.")
    elif stage != "prod":
        print(f"Site: {stage}'s CloudFront caches nothing, so no invalidation.")
    else:
        # Each listed path counts against the 1,000 free a month, so past a
        # handful one wildcard is cheaper. /u/* profile URLs are cached under
        # /index.html (the viewer-request rewrite runs before the cache lookup),
        # so invalidating /index.html covers them.
        invalidate(["/*"] if len(stale) > 10 else ["/" + key for key in stale])
    if changed_art:
        save_art_manifest(s3, bucket, {**deployed_art, **changed_art}, art_etag)


def smoke_test_site() -> None:
    """
    Load the deployed site the way a visitor's browser would (tools/smoke_site.py): pages answer,
    nothing that blocks rendering comes from another host, every script and stylesheet is served,
    the catalog and a player's data load. Retries while CloudFront finishes the invalidation.
    A failure here is a deployed site that is broken for visitors, so it fails the deploy.
    """
    print(f"Check: {DOMAIN_NAME} loads for a visitor...", flush=True)
    smoke_env = os.environ.copy()
    smoke_env.pop("SMS_SMOKE_COOKIE", None)
    if STACK_NAME == STAGES["gamma"][2]:
        # Use the same private configuration as CDK, never a credential in argv/logs.
        import hmac
        import hashlib
        import time
        config = json.loads((LOCAL / "infra" / "cdk.context.json").read_text())
        payload = config["gammaAllowedSteamIds"][0] + "." + str(int(time.time()) + 600)
        signature = hmac.new(config["gammaSessionSecret"].encode(), payload.encode(), hashlib.sha256).hexdigest()
        smoke_env["SMS_SMOKE_COOKIE"] = payload + "." + signature
    r = subprocess.run([sys.executable, str(SRC / "tools" / "smoke_site.py"), DOMAIN_NAME],
                       env=smoke_env, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise DeployError("the deployed site fails its visitor check:\n" + (r.stderr or r.stdout))
    print((r.stdout or "").strip())


def check_site_pages() -> None:
    """Fail before cdk runs if a site/pages/ file name can't be a URL, or a What's new post
    (site/whats-new/) has a name or header the page can't use."""
    sys.path.insert(0, str(SRC))
    import build_site
    try:
        for name, f, _ in build_site.site_pages():
            build_site.page_body(name, f)
    except build_site.PageError as e:
        raise DeployError(str(e))


def main() -> int:
    global SRC, LOCAL
    # The cdk diff echoed below has ✨ and └─; a cp1252 console can't print them.
    sys.stdout.reconfigure(errors="replace")
    pre_push = "--pre-push" in sys.argv
    try:
        if "--lock-status" in sys.argv or "--break-lock" in sys.argv:
            lock_status(break_it="--break-lock" in sys.argv)
            return 0
        LOCAL = main_checkout()
        if "--feedback-table" in sys.argv:
            with deploy_lock("feedback table deploy", None):
                deploy_feedback_table()
            return 0
        if "--edge-alarms" in sys.argv:
            with deploy_lock("edge alarms deploy", None):
                deploy_edge_alarms()
            return 0
        if pre_push:
            pushed = check_pre_push(sys.stdin.read().splitlines())
            if pushed is None:
                return 0
            stage, commit = pushed
            set_stage(stage)
        else:
            stage = use_stage(sys.argv)
            commit = use_ref(sys.argv)
        if stage != "prod":
            print(f"Deploying to {stage}: {DOMAIN_NAME}")
        if "--reheader" in sys.argv:
            with deploy_lock(f"{stage} reheader", None):
                reheader(stage)
            print("Re-headed and invalidated. Browsers that already hold a copy "
                  "keep it until they next ask.")
            return 0
        export = None
        if commit is None:
            # No --ref: the working tree as it is. Clean, it is HEAD's commit.
            if git("status", "--porcelain", "--untracked-files=no"):
                print("Note: deploying a working tree with uncommitted changes.")
            else:
                commit = git("rev-parse", "HEAD")
        with deploy_lock(f"{stage} deploy", commit):
            try:
                if "--ref" in sys.argv or pre_push:
                    SRC = export = export_commit(commit)
                check_site_pages()
                require_feedback_table(commit)
                if stage == "prod":
                    require_gamma_ok(commit)
                deploy_infra()
                smoke_test_ingest(ingest_function_url())
                deploy_site(stage)
                smoke_test_site()
                rebuild_held_runs(stage)
                if stage == "gamma":
                    record_gamma_ok(commit)
            finally:
                if export:
                    finish_export(export)
                    SRC = _HERE
    except DeployError as e:
        print(f"Deploy failed: {e}", file=sys.stderr)
        if pre_push:
            print("Push aborted. Skip deploying with SKIP_DEPLOY=1 git push.", file=sys.stderr)
        return 1
    print(f"Deployed{' ' + commit[:7] if commit else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
