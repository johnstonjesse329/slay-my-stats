#!/usr/bin/env python3
import os

import aws_cdk as cdk

from slay_my_stats.edge_alarms_stack import SlayMyStatsEdgeAlarmsStack
from slay_my_stats.feedback_stack import SlayMyStatsFeedbackStack
from slay_my_stats.slay_my_stats_stack import SlayMyStatsStack

app = cdk.App()
SlayMyStatsStack(app, "SlayMyStatsStack")
# Only where the gamma certificate has been set up, so a clone with just the
# production context still synthesizes.
if app.node.try_get_context("gammaCertificateArn"):
    SlayMyStatsStack(app, "SlayMyStatsGammaStack", stage="gamma")
# The feedback table both stages share. Deployed only by `tools/deploy.py --feedback-table`.
SlayMyStatsFeedbackStack(app, "SlayMyStatsFeedbackStack")
# Alarms on prod's CloudFront metrics, which exist only in us-east-1. Deployed only by
# `tools/deploy.py --edge-alarms`, and only once prodDistributionId is set.
if app.node.try_get_context("prodDistributionId"):
    SlayMyStatsEdgeAlarmsStack(app, "SlayMyStatsEdgeAlarmsStack",
                               env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="us-east-1"))
app.synth()
