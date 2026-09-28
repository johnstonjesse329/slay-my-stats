"""
deploy.py — Push the committed site + infra to AWS.

Runs automatically from githooks/pre-push whenever main is pushed (enable
once per clone with `git config core.hooksPath githooks`), or by hand:

    infra\\.venv\\Scripts\\python.exe tools/deploy.py

Steps:
  1. `cdk diff`. If the stack changed, print the diff and ask y/N before
     `cdk deploy`. No changes -> skip straight to the site.
  2. `build_site.py`, then `aws s3 sync` dist/ and the game-art folders to
     the site bucket (never --delete; art uses --size-only so an unchanged
     checkout doesn't re-upload thousands of images just because mtimes moved).
  3. CloudFront invalidation of /* (one path, well inside the 1,000 free
     invalidation paths a month), so index.html/app.js don't serve stale.

Skip the whole thing for one push with `SKIP_DEPLOY=1 git push` or
`git push --no-verify`.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
_INFRA = _HERE / "infra"
SITE_BUCKET = "slay-my-stats-site"
DOMAIN_NAME = "slay-my-stats.com"
# Mirrors the root-absolute art paths build_site.py's catalog points at.
ART_DIRS = ["card_final", "card_portraits", "node_icons", "relic_images", "potion_images"]
ZERO_SHA = "0" * 40


class DeployError(Exception):
    pass


def run(args, *, cwd=_HERE, env=None, capture=False) -> subprocess.CompletedProcess:
    """Run a command with stdin detached (in pre-push, stdin is git's ref list)."""
    exe = shutil.which(args[0])
    if exe is None:
        raise DeployError(f"'{args[0]}' is not on PATH")
    print("$", " ".join(args), flush=True)
    result = subprocess.run(
        [exe, *args[1:]], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        capture_output=capture, text=True,
    )
    if result.returncode != 0:
        if capture:
            print(result.stdout + result.stderr)
        raise DeployError(f"{args[0]} exited with {result.returncode}")
    return result


def git(*args) -> str:
    return subprocess.run(
        ["git", *args], cwd=_HERE, stdin=subprocess.DEVNULL,
        capture_output=True, text=True,
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

    diff = run(["cdk", "diff"], cwd=_INFRA, env=env, capture=True)
    output = diff.stdout + diff.stderr
    if "There were no differences" in output:
        print("Infra: no changes.")
        return
    print(output)
    if not ask("Deploy these infra changes?"):
        raise DeployError("infra deploy declined")
    run(["cdk", "deploy", "--require-approval", "never"], cwd=_INFRA, env=env)


def deploy_site() -> None:
    run([sys.executable, str(_HERE / "build_site.py")])
    run(["aws", "s3", "sync", str(_HERE / "dist"), f"s3://{SITE_BUCKET}", "--no-progress"])
    for d in ART_DIRS:
        run(["aws", "s3", "sync", str(_HERE / d), f"s3://{SITE_BUCKET}/{d}",
             "--size-only", "--no-progress"])

    dist_id = run([
        "aws", "cloudfront", "list-distributions", "--output", "text",
        "--query", f"DistributionList.Items[?contains(Aliases.Items, '{DOMAIN_NAME}')].Id",
    ], capture=True).stdout.strip()
    if not dist_id:
        raise DeployError(f"no CloudFront distribution found for {DOMAIN_NAME}")
    run(["aws", "cloudfront", "create-invalidation", "--distribution-id", dist_id,
         "--paths", "/*", "--output", "text", "--query", "Invalidation.Id"])


def main() -> int:
    pre_push = "--pre-push" in sys.argv
    try:
        if pre_push and not check_pre_push(sys.stdin.read().splitlines()):
            return 0
        if not pre_push and git("status", "--porcelain", "--untracked-files=no"):
            print("Note: deploying a working tree with uncommitted changes.")
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
