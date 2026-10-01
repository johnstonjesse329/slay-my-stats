from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_certificatemanager as acm,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_destinations as lambda_destinations,
    aws_logs as logs,
    aws_route53 as route53,
    aws_route53_targets as route53_targets,
    aws_budgets as budgets,
    aws_lambda_event_sources as lambda_event_sources,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sns as sns,
    aws_sqs as sqs,
    aws_ssm as ssm,
)
import shutil
from pathlib import Path

import jsii
from aws_cdk import BundlingOptions, DockerImage, ILocalBundling
from constructs import Construct

INGEST_DIR = Path(__file__).resolve().parents[1] / "lambda" / "ingest"
# The handler parses uploads with the same run.py the local dashboard uses,
# so the two can't drift apart. It lives at the repo root, outside the asset
# folder, and gets copied in at synth time.
RUN_PY = Path(__file__).resolve().parents[2] / "run.py"
# Hand-written site pages: site/pages/<name>.html is served at /<name>.
# tools/deploy.py checks the names (build_site.site_pages()) before cdk
# runs; each page gets its own CloudFront behavior below.
SITE_PAGES = sorted(f.stem for f in (Path(__file__).resolve().parents[2] / "site" / "pages").glob("*.html"))


@jsii.implements(ILocalBundling)
class _CopyIngestSources:
    def try_bundle(self, output_dir: str, *, image=None, **_kwargs) -> bool:
        shutil.copy(INGEST_DIR / "handler.py", output_dir)
        shutil.copy(RUN_PY, output_dir)
        return True


def _ingest_asset_hash() -> str:
    import hashlib
    h = hashlib.sha256()
    for p in (INGEST_DIR / "handler.py", RUN_PY):
        h.update(p.read_bytes())
    return h.hexdigest()


STEAM_API_KEY_PARAM_NAME ="/slay-my-stats/steam-api-key"
DOMAIN_NAME = "slay-my-stats.com"
# The ACM certificate and Route 53 hosted zone are created outside CDK and
# passed in as context ("certificateArn", "hostedZoneId"), which lives in the
# untracked infra/cdk.context.json so account-specific IDs stay out of the repo.
# The certificate must be in us-east-1 -- CloudFront's control plane only looks
# there for certificates, regardless of what region the rest of this stack
# deploys to.
# Everything these services bill is covered by free tier at normal traffic,
# so any actual spend on them means the ingest path is being abused.
KILL_SWITCH_BUDGET_USD = 1
KILL_SWITCH_SERVICES = ["AWS Lambda", "AmazonCloudWatch", "Amazon Simple Storage Service"]

KILL_SWITCH_CODE = """
import os

import boto3

_lambda = boto3.client("lambda")


def lambda_handler(event, context):
    # Any message on the topic is a budget breach; there is nothing to parse.
    for name in os.environ["TARGET_FUNCTION_NAMES"].split(","):
        _lambda.put_function_concurrency(FunctionName=name, ReservedConcurrentExecutions=0)
        print("Throttled", name, "to 0 concurrency")
"""

# The site bucket only has /index.html at the root -- page URLs like
# /u/<slug> and /about have no matching object, so CloudFront needs to
# rewrite the request before it reaches S3. Done at the edge (not with S3
# error-document fallback) so the URL in the address bar stays as typed.
PAGE_URL_REWRITE_CODE = """
function handler(event) {
    var request = event.request;
    request.uri = "/index.html";
    return request;
}
"""


class SlayMyStatsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        def required_context(key: str) -> str:
            value = self.node.try_get_context(key)
            if not value:
                raise ValueError(f'Set "{key}" in infra/cdk.context.json (see README "Deploying").')
            return value

        certificate_arn = required_context("certificateArn")
        hosted_zone_id = required_context("hostedZoneId")

        # users/<slug>.json.gz: one gzip JSON blob per player, plus the public
        # users/_index.json.gz list and users/_uploads/<id>.json.gz, each
        # upload's result for the page to poll. Private (CloudFront only
        # serves users/*): ids/<steamid>.json.gz maps Steam IDs to slugs,
        # limits/ holds the upload rate limits, and raw/<steamid>/ keeps every
        # upload as sent, so profiles can be rebuilt after a parser fix.
        # RETAIN: players' uploads live only here, so tearing the stack down
        # leaves the bucket behind. Standing the stack up again then needs it
        # imported or emptied and deleted by hand first.
        data_bucket = s3.Bucket(
            self, "DataBucket",
            bucket_name="slay-my-stats-data",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            # The upload page POSTs each upload straight here, with a
            # presigned form the ingest function hands out.
            cors=[s3.CorsRule(
                allowed_origins=[f"https://{DOMAIN_NAME}"],
                allowed_methods=[s3.HttpMethods.POST],
                allowed_headers=["*"],
            )],
            # Upload results are only read while the page waits for them.
            # Nothing else here expires: raw/ is kept for good.
            lifecycle_rules=[s3.LifecycleRule(prefix="users/_uploads/", expiration=Duration.days(7))],
        )

        # Built static site (index.html, js/*.js, dashboard.css, game art).
        site_bucket = s3.Bucket(
            self, "SiteBucket",
            bucket_name="slay-my-stats-site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        certificate = acm.Certificate.from_certificate_arn(
            self, "SiteCertificate", certificate_arn,
        )

        # Reused for the default behavior and the page behaviors below (same
        # object, not several calls) so the distribution binds one S3 origin / one OAC
        # for the site bucket instead of standing up a duplicate.
        site_origin = origins.S3BucketOrigin.with_origin_access_control(site_bucket)

        # Rewrites page URLs to /index.html, the SPA shell, which then renders
        # the page client-side (site/boot.js). Associated only on the page
        # behaviors below, not the default one, so it never runs for
        # asset/image requests and doesn't burn function invocations.
        page_url_rewrite_fn = cloudfront.Function(
            self, "ProfileUrlRewriteFunction",
            runtime=cloudfront.FunctionRuntime.JS_2_0,
            code=cloudfront.FunctionCode.from_inline(PAGE_URL_REWRITE_CODE),
        )
        page_behavior = cloudfront.BehaviorOptions(
            origin=site_origin,
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            function_associations=[
                cloudfront.FunctionAssociation(
                    function=page_url_rewrite_fn,
                    event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                ),
            ],
        )

        distribution = cloudfront.Distribution(
            self, "Distribution",
            domain_names=[DOMAIN_NAME],
            certificate=certificate,
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=site_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            additional_behaviors={
                "users/*": cloudfront.BehaviorOptions(
                    origin=origins.S3BucketOrigin.with_origin_access_control(data_bucket),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    # Disabled outright, not just short-TTL: a viewer landing right
                    # after an upload must see that upload, not a cached miss.
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                ),
                "u/*": page_behavior,
                # Exact paths, not "<name>*", so a page can't catch an asset
                # that starts with the same letters; the second is /<name>/.
                **{pattern: page_behavior for name in SITE_PAGES for pattern in (name, f"{name}/")},
            },
        )

        hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "HostedZone",
            hosted_zone_id=hosted_zone_id,
            zone_name=DOMAIN_NAME,
        )
        route53.ARecord(
            self, "SiteAliasRecord",
            zone=hosted_zone,
            target=route53.RecordTarget.from_alias(route53_targets.CloudFrontTarget(distribution)),
        )

        ingest_code = lambda_.Code.from_asset(
            str(INGEST_DIR),
            # Local-only bundling; the image is never pulled because
            # try_bundle always succeeds.
            bundling=BundlingOptions(
                image=DockerImage.from_registry("unused"),
                local=_CopyIngestSources(),
            ),
            # Hash the sources that end up in the bundle, including
            # run.py, so a parser change alone still redeploys.
            asset_hash=_ingest_asset_hash(),
        )

        # Checks the Steam sign-in and the rate limits, then hands out a
        # presigned POST for one new raw/ object. Never sees the upload.
        ingest_log_group = logs.LogGroup(
            self, "IngestLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        ingest_fn = lambda_.Function(
            self, "IngestFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=ingest_code,
            timeout=Duration.seconds(15),
            memory_size=256,
            log_group=ingest_log_group,
            environment={
                "DATA_BUCKET": data_bucket.bucket_name,
                # The OpenID return_to origins sign-ins are accepted from; an
                # assertion Steam issued for any other site is refused.
                "ALLOWED_RETURN_TO": f"https://{DOMAIN_NAME}/",
            },
        )
        # Read/write covers the limits, the slug lookup, and signing the
        # upload form (a presigned POST acts with this role's permissions).
        data_bucket.grant_read_write(ingest_fn)

        # Merges each upload into its player's profile, run by S3 as the
        # upload lands. The whole merged profile is held in memory: measured
        # locally, 667 runs took 1.3 s and ~185 MB, 5,000 runs 10 s and
        # ~790 MB. So 1 GB covers profiles up to roughly 6,000 runs, with time
        # to spare at Lambda's slower CPU for this memory size.
        process_log_group = logs.LogGroup(
            self, "ProcessLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        # Uploads that still failed after Lambda's retries. Their raw/ object
        # is kept, so they can be processed again once whatever broke is fixed.
        # Only ever written to (nothing polls it), so it costs nothing idle.
        process_failures = sqs.Queue(
            self, "ProcessFailures",
            retention_period=Duration.days(14),
        )
        # S3 invokes this directly. No queue in between: Lambda polling one
        # costs SQS requests even while nothing is uploaded. How many copies
        # run at once is capped only by the account's concurrency limit (10);
        # the sign-in and per-IP limits in authorize() gate every upload, and
        # the kill switch below is the backstop.
        process_fn = lambda_.Function(
            self, "ProcessFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.process_handler",
            code=ingest_code,
            timeout=Duration.minutes(2),
            memory_size=1024,
            log_group=process_log_group,
            environment={"DATA_BUCKET": data_bucket.bucket_name},
            retry_attempts=2,
            on_failure=lambda_destinations.SqsDestination(process_failures),
        )
        data_bucket.grant_read_write(process_fn)  # and delete: junk uploads aren't kept
        data_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(process_fn),
            s3.NotificationKeyFilter(prefix="raw/"),
        )

        # CloudFormation can't create a SecureString with a real value baked
        # into the template, so the parameter itself is created out-of-band
        # via the AWS CLI -- CDK only imports it by name to grant read access.
        # Only the process function asks Steam for names.
        steam_api_key_param = ssm.StringParameter.from_secure_string_parameter_attributes(
            self, "SteamApiKeyParam",
            parameter_name=STEAM_API_KEY_PARAM_NAME,
        )
        steam_api_key_param.grant_read(process_fn)
        # kms.Alias.from_alias_name(...).grant_decrypt() is a documented CDK
        # no-op -- it can't resolve the alias to a real key ARN without a live
        # account lookup, so no grant is ever emitted. Build the alias ARN
        # from stack tokens instead (no lookup needed) and grant explicitly.
        process_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt"],
                resources=[self.format_arn(service="kms", resource="alias", resource_name="aws/ssm")],
            )
        )
        process_fn.add_environment("STEAM_API_KEY_PARAM_NAME", STEAM_API_KEY_PARAM_NAME)

        # No API Gateway: OpenID verification happens inside the handler, so
        # a bare public Function URL is enough and one less moving part.
        fn_url = ingest_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["https://slay-my-stats.com"],
                allowed_methods=[lambda_.HttpMethod.POST],
                allowed_headers=["content-type"],
            ),
        )

        # Kill switch: budget breach -> SNS -> small Lambda that sets the ingest
        # and process functions' reserved concurrency to 0, so every further
        # request or upload is throttled before it runs. Budgets only evaluate a few times a day, so
        # this bounds a sustained attack rather than stopping it instantly.
        # Undo manually: aws lambda delete-function-concurrency.
        kill_switch_topic = sns.Topic(self, "KillSwitchTopic")
        kill_switch_topic.add_to_resource_policy(
            iam.PolicyStatement(
                actions=["sns:Publish"],
                principals=[iam.ServicePrincipal("budgets.amazonaws.com")],
                resources=[kill_switch_topic.topic_arn],
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            )
        )

        kill_switch_log_group = logs.LogGroup(
            self, "KillSwitchLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        kill_switch_fn = lambda_.Function(
            self, "KillSwitchFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.lambda_handler",
            code=lambda_.Code.from_inline(KILL_SWITCH_CODE),
            timeout=Duration.seconds(10),
            memory_size=128,
            log_group=kill_switch_log_group,
            environment={"TARGET_FUNCTION_NAMES": f"{ingest_fn.function_name},{process_fn.function_name}"},
        )
        kill_switch_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:PutFunctionConcurrency"],
                resources=[ingest_fn.function_arn, process_fn.function_arn],
            )
        )
        kill_switch_fn.add_event_source(lambda_event_sources.SnsEventSource(kill_switch_topic))

        # Separate from the account-wide budget so Route53's fixed zone fees
        # can't trip it. No budget "actions" are used (just SNS notifications),
        # so this doesn't count toward the paid action-enabled budget tier.
        budgets.CfnBudget(
            self, "KillSwitchBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="slay-my-stats-kill-switch",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=KILL_SWITCH_BUDGET_USD, unit="USD",
                ),
                cost_filters={"Service": KILL_SWITCH_SERVICES},
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="ACTUAL",
                        comparison_operator="GREATER_THAN",
                        threshold=100,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            subscription_type="SNS",
                            address=kill_switch_topic.topic_arn,
                        ),
                    ],
                ),
            ],
        )

        CfnOutput(self, "SiteBucketName", value=site_bucket.bucket_name)
        CfnOutput(self, "DataBucketName", value=data_bucket.bucket_name)
        CfnOutput(self, "DistributionDomainName", value=distribution.distribution_domain_name)
        CfnOutput(self, "IngestFunctionUrl", value=fn_url.url)
        CfnOutput(self, "ProcessFailuresQueueUrl", value=process_failures.queue_url)
