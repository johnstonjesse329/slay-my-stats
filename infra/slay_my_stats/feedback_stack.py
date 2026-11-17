"""The feedback table, in a stack of its own (docs/prod-feedback-plan.md).

Both stages read and write it, each held by IAM to its own `env`, so it lives apart from the
stage stacks: a normal push never touches it, and `tools/deploy.py --feedback-table` deploys it
only when this file changes. The stage stacks refer to it by name, not by a CloudFormation
export, so neither stack locks the other. Indexes are only ever added, never removed or renamed
while a Lambda reads them.
"""
from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct

TABLE_NAME = "slay-my-stats-feedback"
# Index name -> its sort key; all are partitioned on env, like the table.
INDEXES = {"ByState": "st", "ByStateCategory": "stcat", "ByCategory": "cat", "ByPage": "pg"}


class SlayMyStatsFeedbackStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        string = dynamodb.AttributeType.STRING
        table = dynamodb.TableV2(
            self, "FeedbackTable",
            table_name=TABLE_NAME,
            partition_key=dynamodb.Attribute(name="env", type=string),
            sort_key=dynamodb.Attribute(name="sk", type=string),
            billing=dynamodb.Billing.on_demand(),
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True),
            deletion_protection=True,
            removal_policy=RemovalPolicy.RETAIN,
            time_to_live_attribute="expires",  # throttle counters only
        )
        for name, sort_key in INDEXES.items():
            table.add_global_secondary_index(
                index_name=name,
                partition_key=dynamodb.Attribute(name="env", type=string),
                sort_key=dynamodb.Attribute(name=sort_key, type=string),
            )
