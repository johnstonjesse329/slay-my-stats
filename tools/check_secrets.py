"""
tools/check_secrets.py — Refuse to publish private values.

Run by githooks/pre-commit (what is about to be committed) and githooks/pre-push
(every tracked file, so the deploy can't publish a leak either), so a slip is
caught before it reaches GitHub rather than after.

    python tools/check_secrets.py --staged   # pre-commit: staged files
    python tools/check_secrets.py            # pre-push: all tracked files

Exit status is 1 and the offending lines are printed when something matches.

What it looks for:

    blocked paths     secrets files that must never be committed (CDK context,
                      which holds the real alert email, allowlisted IPs and the
                      AWS account's hosted-zone ids)
    Steam IDs         17-digit ids starting 7656119. This project keeps them out
                      of the repo on purpose (ids/<steamid>.json.gz exists so
                      they never sit under the public users/ path).
    AWS keys          AKIA/ASIA access key ids, and PEM private key blocks
    AWS account ids   a 12-digit account number inside an ARN
    emails            anything that isn't an example/test domain
    public IPv4       addresses outside the private, loopback, link-local and
                      RFC 5737 documentation ranges

Deliberate values are allowed by adding them to the ALLOW_* sets below with a
reason, or by putting `secrets-ok` in the line (a comment, ideally). Both are
greppable, which is the point: the allowlist should stay short and explainable.
"""

import re
import subprocess
import sys
from pathlib import Path

# --- values that are deliberately fine -------------------------------------

# Fabricated ids used by tests and fixtures. Explicit rather than pattern-based
# so a real id can't be waved through by looking test-ish.
ALLOW_STEAM_IDS = {
    "76561198000000001",  # test fixture
    "76561198000000002",
    "76561198000000003",
    "76561198000000020",
    "76561198000000021",
    "76561198000000022",
    "76561198099999999",
    "76561198012345678",  # the fabricated float64-rounding example in run.py
    "76561198012345680",
    "76561197960287930",  # failure-Lambda test fixture
}

# Non-routable / documentation addresses, plus literals that merely look like an
# address in this repo.
ALLOW_IPS = {
    "1.0.0.0",     # the game exe reports a placeholder version, per refresh_game_data.py
    "1.2.3.4",     # test fixture
}

ALLOW_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
ALLOW_EMAIL_SUFFIXES = (".example", ".invalid", ".test", ".localhost")

# A committed secrets file is always wrong, whatever is in it today.
BLOCKED_PATHS = (
    "infra/cdk.context.json",
    ".env",
    "id_rsa",
    "id_ed25519",
)

PATTERNS = [
    ("Steam ID", re.compile(r"\b7656119\d{10}\b")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS account id in an ARN", re.compile(r"\barn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:\d{12}\b")),
    ("email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # Delimited by something other than a digit or dot, so decimal runs like
    # SVG path data (".82 1.13.16.45.68") don't read as addresses.
    ("public IPv4 address", re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")),
]

SKIP_MARKER = "secrets-ok"


def is_private_ip(value: str) -> bool:
    try:
        a, b, c, _d = (int(part) for part in value.split("."))
    except ValueError:
        return False
    if a in (0, 10, 127) or a >= 224:
        return True
    if (a, b) == (169, 254):
        return True
    if (a, b, c) == (192, 0, 2):
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if (a, b, c) in {(192, 168, 0), (198, 51, 100), (203, 0, 113)}:
        return True
    return False


def allowed(kind: str, value: str) -> bool:
    if kind == "Steam ID":
        return value in ALLOW_STEAM_IDS
    if kind == "public IPv4 address":
        return value in ALLOW_IPS or is_private_ip(value)
    if kind == "email address":
        domain = value.rsplit("@", 1)[1].lower()
        return domain in ALLOW_EMAIL_DOMAINS or domain.endswith(ALLOW_EMAIL_SUFFIXES)
    return False


def scan_text(path: str, text: str) -> list[str]:
    problems = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if SKIP_MARKER in line:
            continue
        for kind, pattern in PATTERNS:
            for match in pattern.finditer(line):
                if allowed(kind, match.group(0)):
                    continue
                problems.append(f"{path}:{lineno}: {kind}: {match.group(0)}")
    return problems


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def staged_files() -> list[str]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
                         capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def read(path: str, staged: bool) -> str | None:
    """The staged blob in --staged mode, else the file on disk. None if binary."""
    if staged:
        got = subprocess.run(["git", "show", f":{path}"], capture_output=True)
        if got.returncode != 0:
            return None
        data = got.stdout
    else:
        data = Path(path).read_bytes()
    if b"\0" in data[:8000]:
        return None
    return data.decode("utf-8", "replace")


def main() -> int:
    staged = "--staged" in sys.argv
    files = staged_files() if staged else tracked_files()

    problems = [f"{f}: blocked path (never commit this)"
                for f in files for p in BLOCKED_PATHS if f == p or f.endswith("/" + p)]
    for f in files:
        text = read(f, staged)
        if text is not None:
            problems += scan_text(f, text)

    if problems:
        print("Refusing to publish private values:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("\nAdd the value to the ALLOW_* sets in tools/check_secrets.py with a reason,"
              f"\nor put `{SKIP_MARKER}` on the line, if it is deliberate.", file=sys.stderr)
        return 1

    scope = "staged files" if staged else "tracked files"
    print(f"check_secrets: {len(files)} {scope} clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
