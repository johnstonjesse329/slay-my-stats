#!/usr/bin/env python3
import aws_cdk as cdk

from slay_my_stats.slay_my_stats_stack import SlayMyStatsStack

app = cdk.App()
SlayMyStatsStack(app, "SlayMyStatsStack")
app.synth()
