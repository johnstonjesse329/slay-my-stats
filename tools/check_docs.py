"""
Keeps the docs in step with the code: fails (exit 1) when
  - the AWS stack builds something the architecture diagram doesn't show,
  - the diagram shows something the stack no longer builds, or
  - the README links an image that isn't in the repo.

    python tools/check_docs.py

Each construct id in infra/slay_my_stats/slay_my_stats_stack.py is mapped
below to the words its box in docs/slay-my-stats-architecture.drawio must
contain (or None for plumbing that is deliberately not drawn). Add a new
resource to the stack and this fails until it is drawn and listed here.
"""
import html, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STACK = ROOT / "infra" / "slay_my_stats" / "slay_my_stats_stack.py"
DIAGRAM = ROOT / "docs" / "slay-my-stats-architecture.drawio"
README = ROOT / "README.md"

DRAWN = {
    "DataBucket": "data bucket",
    "SiteBucket": "site bucket",
    "Distribution": "CloudFront",
    "HostedZone": "Route 53",
    "SiteAliasRecord": "Route 53",
    "IngestFunction": "upload URL",
    "ModIngestFunction": "game uploads",
    "ProcessFunction": "merges uploads",
    "ProcessFailureFunction": "on-failure",
    "AlertTopic": "Amazon SNS",
    "KillSwitchTopic": "Amazon SNS",
    "KillSwitchFunction": "stops uploads",
    "KillSwitchBudget": "AWS Budgets",
    "SteamApiKeyParam": "Parameter Store",
    "IngestLogGroup": "CloudWatch",
    "ModIngestLogGroup": "CloudWatch",
    "ProcessLogGroup": "CloudWatch",
    "ProcessFailureLogGroup": "CloudWatch",
    "KillSwitchLogGroup": "CloudWatch",
    "AccessLogBucket": "access logs",
}
NOT_DRAWN = {  # plumbing inside a drawn box, or an output
    "SiteCertificate": "the ACM cert is noted inside the CloudFront box",
    "ProfileUrlRewriteFunction": "the URL rewrite is noted inside the CloudFront box",
    "IpAllowlistFunction": "gamma-only gate",
}
OUTPUT_ID = re.compile(r"(Name|Domain\w*|Url)$")


def stack_ids() -> set[str]:
    src = STACK.read_text(encoding="utf-8")
    ids = set(re.findall(r'\(\s*self,\s*"(\w+)"', src))
    return {i for i in ids if i not in re.findall(r'CfnOutput\(\s*self,\s*"(\w+)"', src)}


def main() -> int:
    problems = []
    ids = stack_ids()
    text = html.unescape(html.unescape(DIAGRAM.read_text(encoding="utf-8"))).lower()
    for i in sorted(ids - DRAWN.keys() - NOT_DRAWN.keys()):
        problems.append(f"stack builds {i}, which the diagram check doesn't know: draw it in "
                        f"{DIAGRAM.name} and add it to DRAWN (or NOT_DRAWN, with a reason) in tools/check_docs.py")
    for i in sorted((DRAWN.keys() | NOT_DRAWN.keys()) - ids):
        problems.append(f"{i} is listed in tools/check_docs.py but the stack no longer builds it: remove it "
                        f"here and from {DIAGRAM.name}")
    for i, words in sorted(DRAWN.items()):
        if i in ids and words.lower() not in text:
            problems.append(f"{i}: the diagram has no box mentioning '{words}'")
    readme = README.read_text(encoding="utf-8")
    for img in re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", readme):
        if not img.startswith("http") and not (ROOT / img).exists():
            problems.append(f"README links {img}, which doesn't exist")
    for p in problems:
        print("check_docs:", p)
    print(f"check_docs: {len(ids)} stack resources, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
