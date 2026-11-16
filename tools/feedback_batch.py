"""Work through gamma feedback in batches: pull, triage, then resolve what you approved.

    python tools/feedback_batch.py pull              # open notes -> local_data/feedback/batch.json
    python tools/feedback_batch.py report            # the batch as markdown, grouped by theme
    python tools/feedback_batch.py evidence          # the tl;dr table with screenshots (REPORT.md)
    python tools/feedback_batch.py review            # per-page checklist: where to look, how to answer
    python tools/feedback_batch.py resolve           # dry run: what approved entries would close
    python tools/feedback_batch.py resolve --apply   # write the resolutions to the bucket

Needs AWS credentials. `pull` keeps anything already triaged (group, plan, status, close
fields) and only adds new notes, so it can be rerun as notes arrive.

Each entry carries triage fields to fill in:
    group      theme the note belongs to ("mobile charts", "fool missing", ...)
    plan       one line on what the fix is
    status     new -> planned -> built -> approved   (or declined / duplicate)
    commit     the commit that shipped it (outcome done)
    close_note what changed, or why not -- visible to every gamma reviewer
    duplicate_of  id of the note it repeats (outcome duplicate)

`resolve` closes only entries whose status is approved/declined/duplicate, through the same
validation and _resolve code the Lambda uses, so the notes end up as if closed from the inbox.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra" / "lambda" / "ingest"))
import feedback  # noqa: E402

BUCKET = "slay-my-stats-gamma-data"
BATCH = ROOT / "local_data" / "feedback" / "batch.json"
OWNER = None  # steam id recorded as resolver; read from the notes' own author when unset
STATUS_OUTCOME = {"approved": "done", "declined": "declined", "duplicate": "duplicate"}


def _s3():
    import boto3
    return boto3.client("s3")


def _load():
    return json.loads(BATCH.read_text(encoding="utf-8")) if BATCH.exists() else {"entries": []}


def _save(batch):
    BATCH.parent.mkdir(parents=True, exist_ok=True)
    BATCH.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")


def _target(note):
    t = note.get("target", {})
    return {"kind": t.get("kind"), "selector": t.get("selector", ""), "text": (t.get("text") or "")[:120],
            "viewport": t.get("viewport", {})}


def pull():
    s3, batch = _s3(), _load()
    known = {e["id"] for e in batch["entries"]}
    added, token = 0, None
    while True:
        args = {"Bucket": BUCKET, "Prefix": "feedback/", **({"ContinuationToken": token} if token else {})}
        page = s3.list_objects_v2(**args)
        for obj in page.get("Contents", []):
            if obj["Key"] in known:
                continue
            note = json.loads(s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read())
            if note.get("resolved"):
                continue
            n = len(batch["entries"]) + 1
            batch["entries"].append({
                "n": n, "id": note["id"], "author": note.get("author"), "created": note.get("created"),
                "category": note.get("category", ""), "url": note.get("url", ""),
                "target": _target(note), "comment": note["comment"],
                "group": "", "plan": "", "status": "new", "commit": "", "close_note": "", "duplicate_of": "",
            })
            added += 1
        if not page.get("IsTruncated"):
            break
        token = page["NextContinuationToken"]
    batch["entries"].sort(key=lambda e: e["created"] or 0)
    for i, e in enumerate(batch["entries"], 1):
        e["n"] = i
    _save(batch)
    print(f"{added} new, {len(batch['entries'])} in {BATCH}")


def report():
    groups = {}
    for e in _load()["entries"]:
        groups.setdefault(e["group"] or "(untriaged)", []).append(e)
    for name, entries in sorted(groups.items()):
        print(f"\n## {name} ({len(entries)})")
        for e in entries:
            where = e["target"]["selector"] or "whole page"
            print(f"- #{e['n']} [{e['status']}] {e['category'] or '-'} · {e['url']} · {where}")
            print(f"    {e['comment'][:220]}")
            if e["plan"]:
                print(f"    plan: {e['plan']}")


def _commit_exists(sha):
    return subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=ROOT,
                          capture_output=True).returncode == 0


def resolve(apply):
    s3, batch, closed = _s3(), _load(), 0
    ids = {e["id"]: e["n"] for e in batch["entries"]}
    for e in batch["entries"]:
        outcome = STATUS_OUTCOME.get(e["status"])
        if not outcome:
            continue
        fields = {"outcome": outcome, "close_note": e["close_note"], "resolved_in": e["commit"],
                  "duplicate_of": e["duplicate_of"]}
        try:
            fields = feedback._outcome(fields)
        except ValueError:
            print(f"#{e['n']} skipped: {outcome} needs " + {
                "done": "a commit and a close note", "declined": "a close note",
                "duplicate": "duplicate_of set to a note id"}[outcome])
            continue
        if outcome == "done" and not _commit_exists(fields["resolved_in"]):
            print(f"#{e['n']} skipped: commit {fields['resolved_in']} is not in this repo")
            continue
        if fields["duplicate_of"] and fields["duplicate_of"] not in ids:
            print(f"#{e['n']} skipped: duplicate_of is not a note in this batch")
            continue
        print(f"#{e['n']} -> {outcome}: {fields['close_note'][:90]}")
        if apply:
            note = json.loads(s3.get_object(Bucket=BUCKET, Key=e["id"])["Body"].read())
            feedback._resolve(note, e["author"], True, fields)
            s3.put_object(Bucket=BUCKET, Key=e["id"], Body=json.dumps(note).encode(),
                          ContentType="application/json")
            e["status"] = "closed"
        closed += 1
    if apply:
        _save(batch)
    print(f"{closed} {'closed' if apply else 'would close (rerun with --apply)'}")


def evidence():
    """One row per entry: status, commit, what is now true, and its screenshot, as markdown."""
    print("# Feedback batch evidence (tl;dr)")
    print()
    print("| # | Status | Commit | What is now true | Screenshot |")
    print("|---|---|---|---|---|")
    for e in _load()["entries"]:
        shot = e.get("evidence") or ""
        shot = f"![]({Path(shot).name})" if shot else "-"
        tldr = (e.get("tldr") or e.get("plan") or "").replace("|", "/").replace("\n", " ")
        print(f"| {e['n']} | {e['status']} | {e.get('commit') or '-'} | {tldr} | {shot} |")


PREVIEW = "http://localhost:8095/"
PAGES = [  # (title, hash on the preview, matcher on the note's url hash, what to do there)
    ("Run detail", "#detail", "detail", "Open any run, then check each item below."),
    ("Overview", "#overview", "overview", "Scroll the page; use a phone-width window for the phone items."),
    ("Seeds", "#seeds", "seeds", "Check the rows on a phone-width window."),
    ("Profile header / whole site", "#overview", "", "Look at the header, the ascension cards, and the Feedback button."),
]


def review():
    """A checklist per page: where to click, what to look at, and how to answer each item."""
    entries = _load()["entries"]
    print("# Review checklist")
    print()
    print(f"Start the preview first: `python tools/serve_site.py --port 8095` ({PREVIEW}).")
    print("Answer per item with `ok`, `change: <what>` or `decline`. Items you skip stay unapproved.")
    placed = set()
    for title, hash_, key, todo in PAGES:
        rows = [e for e in entries if e["n"] not in placed and e["status"] in ("built", "blocked", "audited")
                and "/u/" in e["url"] and (key == "" or ("#" + key) in e["url"])]
        if not rows:
            continue
        placed.update(e["n"] for e in rows)
        print(f"\n## {title}\n\n**Open:** {PREVIEW}{hash_}  \n**Do:** {todo}\n")
        for e in rows:
            shot = Path(e["evidence"]).name if e.get("evidence") else "none"
            print(f"- [ ] **#{e['n']}** {e.get('tldr') or e['plan']}  \n"
                  f"  Reply: `ok {e['n']}` / `change {e['n']}: ...`  · screenshot: `{shot}`")
    print("\n## Not a page\n")
    print("- **#24** digest emails: nothing to click until the schedule is deployed. After deploy, "
          "check Tuesday's email: one message, Steam names. Reply `ok 24` to approve the deploy.")
    print("- **#21** performance: Lambda Cache-Control is not deployed; reply `ok 21` to approve the deploy.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pull":
        pull()
    elif cmd == "report":
        report()
    elif cmd == "evidence":
        evidence()
    elif cmd == "review":
        review()
    elif cmd == "resolve":
        resolve("--apply" in sys.argv)
    else:
        sys.exit(__doc__)
