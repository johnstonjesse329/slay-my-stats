"""Alarms on prod's CloudFront distribution, in a stack of its own in us-east-1.

CloudFront publishes its metrics (Requests, 4xxErrorRate, 5xxErrorRate) only in us-east-1, and an
alarm, with the SNS topic it notifies, has to live in the region of its metric. The site's stacks
are in us-west-2, so these are kept apart: a normal push never touches this stack, and
`tools/deploy.py --edge-alarms` deploys it. It has no assets, so the legacy synthesizer deploys it
without bootstrapping CDK in us-east-1. Both alarms count toward CloudWatch's free ten.

The distribution is found by its ID in the `prodDistributionId` context, the alert address by
`alertEmail`, the same one the prod stack's AlertTopic uses.
"""
from aws_cdk import Duration, LegacyStackSynthesizer, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from constructs import Construct

# Prod's hourly requests over 2026-11-03..17: median 9, 95th percentile 599, peak 8,069. A spike
# alarm well above the peak only fires on something new: a crawler, a loop, an attack.
REQUESTS_PER_HOUR = 20_000
EDGE_ALARM_PREFIX = "slay-my-stats-edge-"
EDGE_ALARMS = ("Prod5xx", "ProdRequestSpike")


class SlayMyStatsEdgeAlarmsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, synthesizer=LegacyStackSynthesizer(), **kwargs)

        def required_context(key: str) -> str:
            value = self.node.try_get_context(key)
            if not value:
                raise ValueError(f'Set "{key}" in infra/cdk.context.json (see README "Deploying").')
            return value

        distribution_id = required_context("prodDistributionId")
        topic = sns.Topic(self, "EdgeAlertTopic")
        topic.add_subscription(subscriptions.EmailSubscription(required_context("alertEmail")))

        def metric(name: str, statistic: str, period: Duration) -> cloudwatch.Metric:
            return cloudwatch.Metric(
                namespace="AWS/CloudFront", metric_name=name, statistic=statistic, period=period,
                dimensions_map={"DistributionId": distribution_id, "Region": "Global"},
            )

        # (name, metric, threshold, what): any 5xx at all, and traffic far past anything seen.
        # No 4xx alarm: a signed-out /auth/me is a 401, so 4xx sits near 100% on a quiet hour.
        for name, alarm_metric, threshold, what in (
            ("Prod5xx", metric("5xxErrorRate", "Average", Duration.minutes(5)), 0.0001,
             "5xx responses from slay-my-stats.com"),
            ("ProdRequestSpike", metric("Requests", "Sum", Duration.hours(1)), REQUESTS_PER_HOUR,
             f"{REQUESTS_PER_HOUR:,} or more requests in an hour to slay-my-stats.com"),
        ):
            cloudwatch.Alarm(
                self, f"{name}Alarm", metric=alarm_metric, threshold=threshold, evaluation_periods=1,
                # A fixed name, so the prod stack's dashboard can list it by ARN.
                alarm_name=f"{EDGE_ALARM_PREFIX}{name}",
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                # A quiet site sends no datapoints; that is the normal state, not a fault.
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
                alarm_description=f"{what}. Dashboard: slay-my-stats (us-west-2).",
            ).add_alarm_action(cloudwatch_actions.SnsAction(topic))
