"""Work through site feedback in batches: pull, triage, then resolve approved Gamma notes.

    python tools/feedback_batch.py pull --env both   # open Gamma and production notes -> batch.json
    python tools/feedback_batch.py queue             # active counts and group checkpoints
    python tools/feedback_batch.py queue --group charts  # IDs and status for one group
    python tools/feedback_batch.py queue --env prod --ids  # scoped IDs without report text
    python tools/feedback_batch.py detail --id FB-42      # selected report details as JSON lines
    python tools/feedback_batch.py record-candidate --help
    python tools/feedback_batch.py record-review --help
    python tools/feedback_batch.py report            # the batch as markdown, grouped by theme
    python tools/feedback_batch.py evidence          # the tl;dr table with screenshots (REPORT.md)
    python tools/feedback_batch.py review            # per-page checklist: where to look, how to answer
    python tools/feedback_batch.py resolve           # dry run: what approved entries would close
    python tools/feedback_batch.py resolve --apply   # write the resolutions to the feedback table
    python tools/feedback_batch.py backlog --id FB-42 --reason "..."  # dry run: put a note in the backlog
    python tools/feedback_batch.py backlog --id FB-42 --off --apply   # take it back out

Needs AWS credentials for intake and resolution. Pull defaults to Gamma for
existing callers. It keeps triage fields when rerun and records each note's
source. Resolution through this tool is limited to Gamma. Backlog works on both,
like the inbox's Backlog button, since it ships nothing.

Each entry carries triage fields to fill in:
    group      theme the note belongs to ("mobile charts", "fool missing", ...)
    plan       one line on what the fix is
    status     new -> planned -> built -> approved   (or declined / duplicate)
    commit     the commit that shipped it (outcome done, optional)
    close_note what changed, or why not -- visible to every gamma reviewer
    duplicate_of  id of the note it repeats (outcome duplicate)

`resolve` closes only entries whose status is approved/declined/duplicate, through the same
validation, _resolve and conditional write the Lambda uses, so the notes end up as if closed
from the inbox, and a note someone changed meanwhile is skipped, not overwritten.
"""
import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra" / "lambda" / "ingest"))
import feedback  # noqa: E402

TABLE = "slay-my-stats-feedback"
ENV = "gamma"
BATCH = ROOT / "local_data" / "feedback" / "batch.json"
STATUS_OUTCOME = {"approved": "done", "declined": "declined", "duplicate": "duplicate"}
DETAIL_FIELDS = ("comment", "url", "target", "group", "status", "plan", "acceptance")
VALIDATION_FAILURE_LIMIT = 2


def _db():
    import boto3
    return boto3.client("dynamodb")


def _load():
    return json.loads(BATCH.read_text(encoding="utf-8")) if BATCH.exists() else {"entries": []}


def _save(batch):
    BATCH.parent.mkdir(parents=True, exist_ok=True)
    pending = BATCH.with_suffix(".tmp")
    pending.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")
    pending.replace(BATCH)


def _target(note):
    t = note.get("target", {})
    return {"kind": t.get("kind"), "selector": t.get("selector", ""), "text": (t.get("text") or "")[:120],
            "viewport": t.get("viewport", {})}


def tag(e):
    """The note's stable id (FB-n, assigned by the feedback Lambda) or, before it had one, the batch's own #n."""
    return f"FB-{e['seq']}" if e.get("seq") else f"#{e['n']}"


def _source(entry):
    # Batch files created before production intake only contained Gamma notes.
    return entry.get("env", ENV)


def pull(source=ENV):
    batch = _load()
    known = {(_source(e), e["id"]): e for e in batch["entries"]}
    next_number = max((e["n"] for e in batch["entries"]), default=0) + 1
    added = 0
    db = _db()
    sources = (ENV, "prod") if source == "both" else (source,)
    for env in sources:
        for note in feedback.all_notes(db, TABLE, env):
            inbox_status = "resolved" if note.get("resolved") else "backlog" if note.get("backlog") else "open"
            entry = known.get((env, note["id"]))
            if entry is not None:
                entry["env"] = env
                entry["inbox_status"] = inbox_status
                if note.get("seq"):
                    entry["seq"] = note["seq"]
                continue
            if inbox_status != "open":
                continue
            batch["entries"].append({
                "n": next_number, "seq": note.get("seq"), "id": note["id"], "author": note.get("author"),
                "env": env, "inbox_status": inbox_status, "created": note.get("created"),
                "category": note.get("category", ""),
                "url": note.get("url", ""), "target": _target(note), "comment": note["comment"],
                "group": "", "plan": "", "status": "new", "commit": "", "close_note": "", "duplicate_of": "",
            })
            next_number += 1
            added += 1
    batch["entries"].sort(key=lambda e: e["created"] or 0)
    _save(batch)
    print(f"{added} new, {len(batch['entries'])} in {BATCH}")


def _queue_checkpoint(entry):
    status = entry.get("status")
    if status == "blocked":
        return "blocked"
    if _source(entry) == ENV and status in STATUS_OUTCOME:
        return "ready to close"
    decision = entry.get("owner_decision")
    # Older batch records may contain an informal owner decision.
    decision = decision if isinstance(decision, dict) else {}
    deployed = entry.get("gamma_commit")
    if deployed and decision.get("gamma_commit") == deployed:
        if decision.get("action") == "change":
            return "reopened"
        if _source(entry) == "prod" and decision.get("action") == "ok":
            return "waiting for production"
    if deployed:
        return "waiting for owner"
    if entry.get("integration_commit"):
        return "integration"
    if entry.get("commit"):
        verdict = entry.get("agent_review")
        if verdict == "pass":
            return "candidate"
        if verdict in ("changes-requested", "inconclusive"):
            return "validation failed"
        return "verification pending"
    if decision.get("action") == "change":
        return "reopened"
    if entry.get("branch") or entry.get("worktree"):
        return "assigned"
    return "queued"


def queue(group=None, source="both", show_ids=False):
    """Summarize active work from the local batch without printing report contents."""
    entries = [
        e for e in _load()["entries"]
        if _is_open(e) and (source == "both" or _source(e) == source)
    ]
    if group is not None:
        entries = [e for e in entries if (e.get("group") or "") == group]

    sources = Counter(_source(e) for e in entries)
    source_counts = ", ".join(f"{source} {count}" for source, count in sorted(sources.items()))
    print(f"{len(entries)} active" + (f" ({source_counts})" if sources else ""))

    if group is not None:
        for e in entries:
            print(f"- {tag(e)} [{_source(e)}] {e.get('status') or 'new'} ({_queue_checkpoint(e)})")
        return

    groups = {}
    for e in entries:
        groups.setdefault(e.get("group") or "", []).append(e)
    for name, group_entries in sorted(groups.items()):
        checkpoints = Counter(map(_queue_checkpoint, group_entries))
        counts = ", ".join(f"{count} {stage}" for stage, count in sorted(checkpoints.items()))
        print(f"- {name or '(untriaged)'}: {counts}")
        if show_ids:
            for stage in sorted(checkpoints):
                ids = ", ".join(f"{tag(e)} [{_source(e)}]" for e in group_entries if _queue_checkpoint(e) == stage)
                print(f"  {stage}: {ids}")


def _is_open(entry):
    return entry.get("status") != "closed" and entry.get("inbox_status", "open") == "open"


def _select_entries(batch, tags):
    entries = {tag(e): e for e in batch["entries"]}
    missing = [report_id for report_id in tags if report_id not in entries]
    if missing:
        sys.exit(f"Unknown report IDs: {', '.join(missing)}")
    return [entries[report_id] for report_id in dict.fromkeys(tags)]


def detail(tags, fields):
    """Print one JSON line per requested report with only the requested fields."""
    for entry in _select_entries(_load(), tags):
        row = {"tag": tag(entry), "env": _source(entry)}
        row.update((field, entry[field]) for field in fields if field in entry and field not in row)
        print(json.dumps(row, ensure_ascii=False, separators=(",", ":")))


def _commit_sha(ref):
    result = subprocess.run(["git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        sys.exit(f"Unknown commit: {ref}")
    return result.stdout.strip()


def _handoff_path(path):
    handoff = (ROOT / path).resolve()
    directory = ROOT / "local_data" / "feedback" / "handoffs"
    if not handoff.is_relative_to(directory.resolve()) or not handoff.is_relative_to(ROOT) or not handoff.is_file():
        sys.exit("Use an existing handoff under local_data/feedback/handoffs.")
    return handoff.relative_to(ROOT).as_posix()


def _pending_entries(batch, tags):
    entries = _select_entries(batch, tags)
    for entry in entries:
        if (not _is_open(entry) or entry.get("status") in (*STATUS_OUTCOME, "blocked")
                or entry.get("gamma_commit") or entry.get("integration_commit")):
            sys.exit(f"{tag(entry)} has a later checkpoint or is outside the active fix scope.")
    return entries


def _matches_commit(entry, commit):
    recorded = entry.get("commit")
    return bool(recorded and commit.startswith(recorded))


def record_candidate(tags, base_ref, commit_ref, checks, handoff_path):
    batch = _load()
    entries = _pending_entries(batch, tags)
    base, commit = _commit_sha(base_ref), _commit_sha(commit_ref)
    handoff = _handoff_path(handoff_path)
    ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", base, commit], cwd=ROOT, capture_output=True)
    if base == commit or ancestry.returncode:
        sys.exit("Candidate must add work on top of its recorded base.")
    for entry in entries:
        roles = entry.setdefault("handoffs", {})
        if not _matches_commit(entry, commit):
            entry.pop("agent_review", None)
            roles.pop("review", None)
        entry.update(status="built", base_commit=base, commit=commit, checks=checks)
        roles["implementation"] = handoff
    _save(batch)
    print(f"Candidate {commit[:12]} recorded for {', '.join(map(tag, entries))}")


def record_review(tags, commit_ref, verdict, handoff_path, reason=None):
    if verdict != "pass" and not (reason or "").strip():
        sys.exit("Give a one-line --reason for failed or inconclusive verification.")
    batch = _load()
    entries = _pending_entries(batch, tags)
    commit = _commit_sha(commit_ref)
    handoff = _handoff_path(handoff_path)
    for entry in entries:
        if not _matches_commit(entry, commit):
            sys.exit(f"{tag(entry)} does not have candidate {commit[:12]} recorded.")
        for attempt in entry.get("validation_failures", []):
            if attempt["handoff"] == handoff and (attempt["commit"], attempt["verdict"]) != (commit, verdict):
                sys.exit(f"Use a new handoff for the new verification of {tag(entry)}.")
    for entry in entries:
        entry["agent_review"] = verdict
        entry.setdefault("handoffs", {})["review"] = handoff
        if verdict == "pass":
            continue
        failures = entry.setdefault("validation_failures", [])
        if not any(attempt["handoff"] == handoff for attempt in failures):
            failures.append({"commit": commit, "handoff": handoff, "verdict": verdict, "reason": reason})
        if len(failures) >= VALIDATION_FAILURE_LIMIT:
            entry.update(status="blocked", blocker=reason)
    _save(batch)
    print(f"Review {verdict} for {commit[:12]} recorded for {', '.join(map(tag, entries))}")
    blocked = [tag(e) for e in entries if e.get("status") == "blocked"]
    if blocked:
        print(f"Human decision required after {VALIDATION_FAILURE_LIMIT} failed attempts: {', '.join(blocked)}")


def report():
    groups = {}
    for e in _load()["entries"]:
        groups.setdefault(e["group"] or "(untriaged)", []).append(e)
    for name, entries in sorted(groups.items()):
        print(f"\n## {name} ({len(entries)})")
        for e in entries:
            where = e["target"]["selector"] or "whole page"
            print(f"- {tag(e)} [{_source(e)}, {e['status']}] {e['category'] or '-'} · {e['url']} · {where}")
            print(f"    {e['comment'][:220]}")
            if e["plan"]:
                print(f"    plan: {e['plan']}")


def _commit_exists(sha):
    return subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=ROOT,
                          capture_output=True).returncode == 0


def resolve(apply, tags=()):
    db, batch, closed = _db() if apply else None, _load(), 0
    ids = {e["id"] for e in batch["entries"] if _source(e) == ENV}
    for e in batch["entries"]:
        if tags and tag(e) not in tags:
            continue
        outcome = STATUS_OUTCOME.get(e["status"])
        if not outcome:
            continue
        if _source(e) != ENV:
            print(f"{tag(e)} skipped: production feedback uses the production release workflow")
            continue
        fields = {"outcome": outcome, "close_note": e["close_note"], "resolved_in": e["commit"],
                  "duplicate_of": e["duplicate_of"]}
        try:
            fields = feedback._outcome(fields)
        except feedback.Refused as refused:
            print(f"{tag(e)} skipped: {refused.message}")
            continue
        except ValueError:
            print(f"{tag(e)} skipped: invalid close fields")
            continue
        if fields["resolved_in"] and not _commit_exists(fields["resolved_in"]):
            print(f"{tag(e)} skipped: commit {fields['resolved_in']} is not in this repo")
            continue
        if fields["duplicate_of"] and fields["duplicate_of"] not in ids:
            print(f"{tag(e)} skipped: duplicate_of is not a Gamma note in this batch")
            continue
        print(f"{tag(e)} -> {outcome}: {fields['close_note'][:90]}")
        if apply:
            try:
                feedback._change(db, TABLE, ENV, e["id"], e["author"],
                                 lambda note: feedback._changed(note, lambda n: feedback._resolve(n, e["author"], True, fields)))
            except feedback.Refused as refused:
                print(f"{tag(e)} skipped: {refused.message}")
                continue
            e["status"] = "closed"
        closed += 1
    if apply:
        _save(batch)
    print(f"{closed} {'closed' if apply else 'would close (rerun with --apply)'}")


def backlog(tags, reason="", on=True, apply=False):
    """Put open notes in the backlog (or take them out), as the inbox's Backlog button does.

    Uses the Lambda's own _backlog and conditional write, on Gamma or production. The reason is
    optional and shown publicly on the note, like the inbox's. A resolved note is left alone.
    """
    reason = (reason or "").strip()
    if len(reason) > 500:
        sys.exit("Keep the backlog reason to 500 characters.")
    batch = _load()
    entries = _select_entries(batch, tags)
    db, changed = _db() if apply else None, 0
    for e in entries:
        if e.get("status") == "closed" or e.get("inbox_status") == "resolved":
            print(f"{tag(e)} skipped: already resolved")
            continue
        if (e.get("inbox_status", "open") == "backlog") == on:
            print(f"{tag(e)} skipped: already {'in' if on else 'out of'} the backlog")
            continue
        print(f"{tag(e)} [{_source(e)}] -> {'backlog' if on else 'open'}" + (f": {reason[:90]}" if on and reason else ""))
        if apply:
            try:
                feedback._change(db, TABLE, _source(e), e["id"], e["author"],
                                 lambda note: feedback._backlog(note, e["author"], on, reason))
            except feedback.Refused as refused:
                print(f"{tag(e)} skipped: {refused.message}")
                continue
            e["inbox_status"] = "backlog" if on else "open"
        changed += 1
    if apply:
        _save(batch)
    print(f"{changed} {'changed' if apply else 'would change (rerun with --apply)'}")


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
        print(f"| {tag(e)} | {e['status']} | {e.get('commit') or '-'} | {tldr} | {shot} |")


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
            print(f"- [ ] **{tag(e)}** {e.get('tldr') or e['plan']}  \n"
                  f"  Reply: `ok {tag(e)}` / `change {tag(e)}: ...`  · screenshot: `{shot}`")
    print("\n## Not a page\n")
    print("- **#24** digest emails: nothing to click until the schedule is deployed. After deploy, "
          "check Tuesday's email: one message, Steam names. Reply `ok 24` to approve the deploy.")
    print("- **#21** performance: Lambda Cache-Control is not deployed; reply `ok 21` to approve the deploy.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pull":
        parser = argparse.ArgumentParser(prog="feedback_batch.py pull")
        parser.add_argument("--env", choices=(ENV, "prod", "both"), default=ENV)
        pull(parser.parse_args(sys.argv[2:]).env)
    elif cmd == "queue":
        parser = argparse.ArgumentParser(prog="feedback_batch.py queue")
        parser.add_argument("--group", help="Show report IDs for this group. Use --group= for untriaged.")
        parser.add_argument("--env", choices=(ENV, "prod", "both"), default="both")
        parser.add_argument("--ids", action="store_true", help="Include report IDs in the grouped summary.")
        options = parser.parse_args(sys.argv[2:])
        queue(options.group, options.env, options.ids)
    elif cmd == "detail":
        parser = argparse.ArgumentParser(prog="feedback_batch.py detail")
        parser.add_argument("--id", action="append", required=True, help="Report ID. Repeat to select more reports.")
        parser.add_argument("--field", action="append", help="Batch field to include. Repeat to select more fields.")
        options = parser.parse_args(sys.argv[2:])
        detail(options.id, options.field or DETAIL_FIELDS)
    elif cmd in ("record-candidate", "record-review"):
        parser = argparse.ArgumentParser(prog=f"feedback_batch.py {cmd}")
        parser.add_argument("--id", action="append", required=True, help="Report ID. Repeat for a shared candidate.")
        parser.add_argument("--commit", required=True, help="Candidate commit SHA.")
        parser.add_argument("--handoff", required=True, help="Existing handoff under local_data/feedback/handoffs.")
        if cmd == "record-candidate":
            parser.add_argument("--base", required=True, help="Base commit SHA.")
            parser.add_argument("--checks", required=True, help="One-line summary of the checks and limitations.")
            options = parser.parse_args(sys.argv[2:])
            record_candidate(options.id, options.base, options.commit, options.checks, options.handoff)
        else:
            parser.add_argument("--verdict", choices=("pass", "changes-requested", "inconclusive"), required=True)
            parser.add_argument("--reason", help="One-line reason for a failed or inconclusive attempt.")
            options = parser.parse_args(sys.argv[2:])
            record_review(options.id, options.commit, options.verdict, options.handoff, options.reason)
    elif cmd == "report":
        report()
    elif cmd == "evidence":
        evidence()
    elif cmd == "review":
        review()
    elif cmd == "resolve":
        parser = argparse.ArgumentParser(prog="feedback_batch.py resolve")
        parser.add_argument("--id", action="append", default=[], help="Limit resolution to this FB-n. Repeat as needed.")
        parser.add_argument("--apply", action="store_true")
        options = parser.parse_args(sys.argv[2:])
        resolve(options.apply, options.id)
    elif cmd == "backlog":
        parser = argparse.ArgumentParser(prog="feedback_batch.py backlog")
        parser.add_argument("--id", action="append", required=True, help="Report ID. Repeat to select more reports.")
        parser.add_argument("--reason", default="", help="Why later (optional, shown publicly on the note).")
        parser.add_argument("--off", action="store_true", help="Take the notes back out of the backlog.")
        parser.add_argument("--apply", action="store_true")
        options = parser.parse_args(sys.argv[2:])
        backlog(options.id, options.reason, not options.off, options.apply)
    else:
        sys.exit(__doc__)
