"""
deploy.py — Push the committed site + infra to AWS.

Runs automatically from githooks/pre-push whenever main is pushed (enable
once per clone with `git config core.hooksPath githooks`), or by hand:

    infra\\.venv\\Scripts\\python.exe tools/deploy.py

Steps:
  0. Check site/pages/ file names, since the stack routes a URL per page.
  1. `cdk diff`. If the stack changed, print the diff and ask y/N before
     `cdk deploy`. No changes -> skip straight to the site.
  2. `build_site.py` (given the stack's ingest Function URL for the upload
     page), then upload only the dist/ files whose content changed (with
     dist_cache_control()), and `aws s3 sync` the game-art folders with ART_CACHE_CONTROL (never
     --delete; art uses --size-only so an unchanged checkout doesn't
     re-upload thousands of images just because mtimes moved).
  3. CloudFront invalidation of just the uploaded paths (or /* past ten of
     them), so index.html/app.js don't serve stale. Nothing uploaded, no
     invalidation. The first 1,000 paths a month are free.

Neither upload re-sends a file whose bytes didn't change, so a new
Cache-Control value won't reach what's already up there. Push it to the whole
bucket by hand, once, with `tools/deploy.py --reheader`.

`--stage gamma` deploys the same checkout to gamma.slay-my-stats.com instead: a
separate copy of the stack for trying a change against real CloudFront first.
Only by hand; pushing main always deploys production.

    infra\\.venv\\Scripts\\python.exe tools/deploy.py --stage gamma

`--reheader` takes `--stage` too.

Skip the whole thing for one push with `SKIP_DEPLOY=1 git push` or
`git push --no-verify`.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
_INFRA = _HERE / "infra"
# Production's names; use_stage() swaps in another stage's. They mirror what
# infra/slay_my_stats/slay_my_stats_stack.py names things per stage.
SITE_BUCKET = "slay-my-stats-site"
DOMAIN_NAME = "slay-my-stats.com"
STACK_NAME = "SlayMyStatsStack"
STAGES = {
    "prod": (SITE_BUCKET, DOMAIN_NAME, STACK_NAME),
    "gamma": ("slay-my-stats-gamma-site", "gamma.slay-my-stats.com", "SlayMyStatsGammaStack"),
}
# Mirrors the root-absolute art paths build_site.py's catalog points at.
ART_DIRS = ["card_final", "card_portraits", "node_icons", "relic_images", "potion_images", "ui_icons", "thumbs"]
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

# The dist/ files (app.js, catalog.json, the CSS) aren't content-hashed either,
# and they change with every deploy, so browsers get five minutes: enough that
# moving around the site doesn't re-ask for 600 KB of script and catalog, short
# enough that a deploy reaches someone already on the site almost at once.
# HTML is the entry point, so browsers always check it (a 304 when unchanged).
# s-maxage is for CloudFront alone: every deploy invalidates what it uploads,
# so the edge can hold a file for a day rather than going back to S3 every
# five minutes -- or on every single request, for the HTML.
DIST_CACHE_CONTROL = "public, max-age=300, s-maxage=86400"
HTML_CACHE_CONTROL = "public, max-age=0, must-revalidate, s-maxage=86400"


def dist_cache_control(key: str) -> str:
    return HTML_CACHE_CONTROL if key.endswith(".html") else DIST_CACHE_CONTROL


class DeployError(Exception):
    pass


def use_stage(argv) -> str:
    """Point the deploy at the stage named by `--stage <name>` (default prod)."""
    global SITE_BUCKET, DOMAIN_NAME, STACK_NAME
    stage = argv[argv.index("--stage") + 1] if "--stage" in argv[:-1] else "prod"
    if "--stage" in argv[-1:] or stage not in STAGES:
        raise DeployError(f"--stage takes one of: {', '.join(STAGES)}")
    SITE_BUCKET, DOMAIN_NAME, STACK_NAME = STAGES[stage]
    return stage


def run(args, *, cwd=_HERE, env=None, capture=False, stream=False) -> subprocess.CompletedProcess:
    """
    Run a command with stdin detached (in pre-push, stdin is git's ref list).
    capture: collect output silently (printed only on failure).
    stream: print output live as it arrives and also collect it, for slow
    steps whose output the caller still needs (cdk diff, art syncs) so the
    push doesn't sit silent for minutes.
    """
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


def git(*args) -> str:
    return subprocess.run(
        ["git", *args], cwd=_HERE, stdin=subprocess.DEVNULL,
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


def check_pre_push(ref_lines) -> bool:
    """
    Decide from git's pre-push stdin whether this push deploys. Returns False
    when main isn't being pushed; raises (aborting the push) when main is being
    pushed but the checkout doesn't match what's going up, since the build
    reads the working tree, not the pushed commit.
    """
    pushed = None
    for line in ref_lines:
        parts = line.split()
        if len(parts) == 4 and parts[2] == "refs/heads/main" and parts[1] != ZERO_SHA:
            pushed = parts
    if pushed is None:
        return False

    _, local_sha, _, remote_sha = pushed
    if local_sha != git("rev-parse", "HEAD"):
        raise DeployError("pushing main from a commit other than HEAD -- check it out first so the build matches")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise DeployError("uncommitted changes -- commit or set them aside so the build matches the push")
    if remote_sha != ZERO_SHA:
        ff = subprocess.run(["git", "merge-base", "--is-ancestor", remote_sha, local_sha],
                            cwd=_HERE, stdin=subprocess.DEVNULL, capture_output=True)
        if ff.returncode != 0:
            raise DeployError("not a fast-forward of origin/main (fetch first) -- the push would be rejected after deploying")
    return True


def deploy_infra() -> None:
    # cdk.json runs `python app.py`; put the infra venv first so that resolves
    # to the interpreter with aws_cdk installed.
    venv_bin = _INFRA / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    env = {**os.environ, "PATH": f"{venv_bin}{os.pathsep}{os.environ['PATH']}"}

    print("Infra: comparing the stack with AWS (cdk diff, usually a minute or two)...", flush=True)
    output = run(["cdk", "diff", STACK_NAME], cwd=_INFRA, env=env, stream=True).stdout
    if "There were no differences" in output:
        print("Infra: no changes.")
        return
    if not ask("Deploy these infra changes?"):
        raise DeployError("infra deploy declined")
    run(["cdk", "deploy", STACK_NAME, "--require-approval", "never"], cwd=_INFRA, env=env)


def upload_changed_dist() -> list[str]:
    """
    Upload only the dist/ files whose content differs from S3. `aws s3 sync`
    can't tell: build_site.py rewrites every file, so all of them always look
    newer. Compares MD5 against the S3 ETag, which is the MD5 for any object
    uploaded in one part (dist files are far below the CLI's 8 MB multipart
    threshold). Returns the uploaded keys.
    """
    listing = run([
        "aws", "s3api", "list-objects-v2", "--bucket", SITE_BUCKET, "--output", "json",
        "--query", "Contents[?!contains(Key, '/')].[Key, ETag]",
    ], capture=True).stdout
    remote = {key: etag.strip('"') for key, etag in (json.loads(listing) or [])}

    dist = _HERE / "dist"
    uploaded = []
    for f in sorted(p for p in dist.rglob("*") if p.is_file()):
        key = f.relative_to(dist).as_posix()
        if remote.get(key) == hashlib.md5(f.read_bytes()).hexdigest():
            continue
        run(["aws", "s3", "cp", str(f), f"s3://{SITE_BUCKET}/{key}", "--no-progress",
             "--cache-control", dist_cache_control(key)])
        uploaded.append(key)
    return uploaded


def reheader() -> None:
    """
    Set the Cache-Control values above on everything already in the bucket,
    then invalidate it.

    A normal deploy only sends files whose content (dist/) or size (art)
    changed, so anything uploaded before these headers existed -- and any art
    folder the game didn't change this round -- would keep serving no
    Cache-Control forever. This rewrites each object's metadata in place (an
    S3-to-S3 copy, so no bytes leave this machine) and re-guesses Content-Type
    from the extension, which is what the original upload did too.

    The invalidation is the point, not an afterthought: CloudFront stores a
    response's headers alongside its body, so every edge keeps handing out the
    old header-less response until its own copy expires.

    Run by hand after changing any of the *_CACHE_CONTROL values:
        python tools/deploy.py --reheader
    """
    # The same top-level keys upload_changed_dist() compares against.
    listing = run([
        "aws", "s3api", "list-objects-v2", "--bucket", SITE_BUCKET, "--output", "json",
        "--query", "Contents[?!contains(Key, '/')].Key",
    ], capture=True).stdout
    for key in json.loads(listing) or []:
        run(["aws", "s3", "cp", f"s3://{SITE_BUCKET}/{key}", f"s3://{SITE_BUCKET}/{key}",
             "--no-progress", "--metadata-directive", "REPLACE",
             "--cache-control", dist_cache_control(key)])
    for d in ART_DIRS:
        print(f"Site: re-heading {d}/...", flush=True)
        run(["aws", "s3", "cp", f"s3://{SITE_BUCKET}/{d}/", f"s3://{SITE_BUCKET}/{d}/",
             "--recursive", "--no-progress",
             "--metadata-directive", "REPLACE",
             "--cache-control", ART_CACHE_CONTROL], stream=True)
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


def deploy_site() -> None:
    print("Site: building dist/...", flush=True)
    run([sys.executable, str(_HERE / "build_site.py"), "--ingest-url", ingest_function_url()])
    print("Site: uploading changed dist/ files...", flush=True)
    changed = upload_changed_dist()
    for d in ART_DIRS:
        print(f"Site: syncing {d}/ (each uploaded file is listed)...", flush=True)
        out = run(["aws", "s3", "sync", str(_HERE / d), f"s3://{SITE_BUCKET}/{d}",
                   "--size-only", "--no-progress",
                   "--cache-control", ART_CACHE_CONTROL], stream=True).stdout
        # "upload: <local path> to s3://<bucket>/<key>"
        changed += [line.split(f"s3://{SITE_BUCKET}/", 1)[1]
                    for line in out.splitlines() if line.startswith("upload:")]

    if not changed:
        print("Site: no changes, skipping CloudFront invalidation.")
        return
    # Each listed path counts against the 1,000 free a month, so past a
    # handful one wildcard is cheaper. /u/* profile URLs are cached under
    # /index.html (the viewer-request rewrite runs before the cache lookup),
    # so invalidating /index.html covers them.
    invalidate(["/*"] if len(changed) > 10 else ["/" + key for key in changed])


def check_site_pages() -> None:
    """Fail before cdk runs if a site/pages/ file name can't be a URL."""
    sys.path.insert(0, str(_HERE))
    import build_site
    try:
        build_site.site_pages()
    except build_site.PageError as e:
        raise DeployError(str(e))


def main() -> int:
    # The cdk diff echoed below has ✨ and └─; a cp1252 console can't print them.
    sys.stdout.reconfigure(errors="replace")
    pre_push = "--pre-push" in sys.argv
    try:
        stage = "prod" if pre_push else use_stage(sys.argv)
        if stage != "prod":
            print(f"Deploying to {stage}: {DOMAIN_NAME}")
        if "--reheader" in sys.argv:
            reheader()
            print("Re-headed and invalidated. Browsers that already hold a copy "
                  "keep it until they next ask.")
            return 0
        if pre_push and not check_pre_push(sys.stdin.read().splitlines()):
            return 0
        if not pre_push and git("status", "--porcelain", "--untracked-files=no"):
            print("Note: deploying a working tree with uncommitted changes.")
        check_site_pages()
        deploy_infra()
        deploy_site()
    except DeployError as e:
        print(f"Deploy failed: {e}", file=sys.stderr)
        if pre_push:
            print("Push aborted. Skip deploying with SKIP_DEPLOY=1 git push.", file=sys.stderr)
        return 1
    print("Deployed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
