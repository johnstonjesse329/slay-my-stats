"""Copy gamma's S3 feedback notes into the feedback table as env=gamma (docs/prod-feedback-plan.md).

    infra\\.venv\\Scripts\\python.exe tools/feedback_migrate.py           # dry run: what would be copied
    infra\\.venv\\Scripts\\python.exe tools/feedback_migrate.py --apply   # write it

Each note keeps its id, seq, outcome, backlog and history. Its `plus` list of Steam IDs becomes
one vote item per player and `plus_count`, and leaves the note, so the inbox never sends who
voted. A note and its votes go in one transaction, each put only if absent, so a rerun only
adds notes sent since the last one. A note already in the table is left alone; one that
differs from S3 (changed on gamma between runs) is listed for a look, never overwritten.
The FB-n counter is raised to the highest seq, never lowered. S3 is only read.

Needs AWS credentials that may read the gamma data bucket and write the table.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra" / "lambda" / "ingest"))
import feedback  # noqa: E402

BUCKET = "slay-my-stats-gamma-data"
TABLE = "slay-my-stats-feedback"
ENV = "gamma"


def s3_notes(s3, bucket):
    """Every note in the bucket's feedback/ prefix, newest first."""
    notes, token = [], None
    while True:
        page = s3.list_objects_v2(Bucket=bucket, Prefix="feedback/", **({"ContinuationToken": token} if token else {}))
        for obj in page.get("Contents", []):
            if feedback.NOTE_ID.fullmatch(obj["Key"]):
                notes.append(json.loads(s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()))
        if not page.get("IsTruncated"):
            return notes
        token = page["NextContinuationToken"]


def split(note):
    """The note as stored (without `plus`) and the distinct Steam IDs that gave it a +1."""
    body = {k: v for k, v in note.items() if k != "plus"}
    voters = list(dict.fromkeys(p for p in note.get("plus", []) if isinstance(p, str) and p))
    return body, voters


def migrate(s3, db, apply, bucket=BUCKET, table=TABLE, env=ENV, out=print):
    notes = s3_notes(s3, bucket)
    copied, kept, differs = 0, 0, []
    for note in notes:
        body, voters = split(note)
        tag = f"FB-{body.get('seq', '?')}"
        got = db.get_item(TableName=table, Key={"env": {"S": env}, "sk": {"S": body["id"]}}, ConsistentRead=True).get("Item")
        if got:
            kept += 1
            if json.loads(got["body"]["S"]) != body or int(got["plus_count"]["N"]) != len(voters):
                differs.append(tag)
            continue
        out(f"{tag} {feedback._state(body)}, {len(voters)} +1: {body.get('comment', '')[:70]!r}")
        copied += 1
        if apply:
            items = [{"Put": {"TableName": table, "Item": feedback.note_item(env, body, len(voters)),
                              "ConditionExpression": "attribute_not_exists(sk)"}}]
            items += [{"Put": {"TableName": table, "Item": feedback.vote_item(env, body["id"], v, body.get("created", 0)),
                               "ConditionExpression": "attribute_not_exists(sk)"}} for v in voters]
            db.transact_write_items(TransactItems=items)
    top = max((n["seq"] for n in notes if isinstance(n.get("seq"), int)), default=0)
    if apply and top:
        try:
            db.update_item(TableName=table, Key={"env": {"S": "counter"}, "sk": {"S": "seq"}},
                           UpdateExpression="SET #v = :top", ConditionExpression="attribute_not_exists(#v) OR #v < :top",
                           ExpressionAttributeNames={"#v": "value"}, ExpressionAttributeValues={":top": {"N": str(top)}})
        except Exception as error:
            if feedback._code(error) != "ConditionalCheckFailedException":
                raise
    out(f"{len(notes)} notes in S3: {copied} {'copied' if apply else 'to copy (rerun with --apply)'}, "
        f"{kept} already in the table; counter {'raised to at least' if apply else 'would be at least'} {top}.")
    if differs:
        out("Already in the table but different from S3 (left alone, look at these): " + ", ".join(differs))
    return copied, kept, differs


if __name__ == "__main__":
    import boto3
    migrate(boto3.client("s3"), boto3.client("dynamodb"), "--apply" in sys.argv)
