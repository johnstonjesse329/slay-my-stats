from aws_cdk import (
    CfnOutput,
    Fn,
    Duration,
    RemovalPolicy,
    Stack,
    TimeZone,
    aws_certificatemanager as acm,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_actions,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as dynamodb,
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
    aws_scheduler as scheduler,
    aws_scheduler_targets as scheduler_targets,
    aws_sns as sns,
    aws_sns_subscriptions as subscriptions,
    aws_ssm as ssm,
)
import json
import shutil
from pathlib import Path

import jsii
from aws_cdk import BundlingOptions, DockerImage, ILocalBundling
from constructs import Construct

from slay_my_stats.feedback_stack import TABLE_NAME as FEEDBACK_TABLE
from slay_my_stats.edge_alarms_stack import EDGE_ALARM_PREFIX, EDGE_ALARMS

INGEST_DIR = Path(__file__).resolve().parents[1] / "lambda" / "ingest"
# The handler parses uploads with the same run.py the local dashboard uses,
# so the two can't drift apart. It lives at the repo root, outside the asset
# folder, and gets copied in at synth time.
RUN_PY = Path(__file__).resolve().parents[2] / "run.py"
# Likewise the event-log reading the Keeping Up numbers come from, and the card costs
# it prices plays with, cut from the local game data (tools/build_measured_cards.py).
DERIVE_PY = Path(__file__).resolve().parents[2] / "tools" / "power_curve" / "derive_telemetry.py"
FIGHT_DEMAND_PY = DERIVE_PY.with_name("fight_demand.py")
POWER_DATA = Path(__file__).resolve().parents[2] / "power_data.json"
CARDS_PY = Path(__file__).resolve().parents[2] / "tools" / "build_measured_cards.py"
CARD_DATA = Path(__file__).resolve().parents[2] / "card_data.json"
# And which characters, cards and relics are core game content, so runs from mods or a
# newer patch are held back (tools/build_known_ids.py).
IDS_PY = Path(__file__).resolve().parents[2] / "tools" / "build_known_ids.py"
RELIC_DATA = Path(__file__).resolve().parents[2] / "relic_data.json"
RETIRED_IDS = Path(__file__).resolve().parents[2] / "tools" / "retired_ids.json"
# Hand-written site pages: site/pages/<name>.html is served at /<name>.
# tools/deploy.py checks the names (build_site.site_pages()) before cdk
# runs; each page gets its own CloudFront behavior below.
SITE_PAGES = sorted(f.stem for f in (Path(__file__).resolve().parents[2] / "site" / "pages").glob("*.html"))
# Pages with a link per post under them: /whats-new/<post id> (build_site.POSTS_PAGE).
POST_PAGES = [name for name in ("whats-new",) if name in SITE_PAGES]


@jsii.implements(ILocalBundling)
class _CopyIngestSources:
    def try_bundle(self, output_dir: str, *, image=None, **_kwargs) -> bool:
        for name in ("handler.py", "measured.py", "feedback.py", "reactions.py", "session.py", "views.py", "benchmark.py"):
            shutil.copy(INGEST_DIR / name, output_dir)
        shutil.copy(RUN_PY, output_dir)
        shutil.copy(DERIVE_PY, output_dir)
        benchmark_dir = Path(output_dir) / "tools" / "power_curve"
        benchmark_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIGHT_DEMAND_PY, benchmark_dir)
        if POWER_DATA.exists():
            shutil.copy(POWER_DATA, output_dir)
        # Without game data the table is left out and the Lambda reads it as empty:
        # Card cost lines come out flat, nothing else is lost.
        if CARD_DATA.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("build_measured_cards", CARDS_PY)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.write(Path(output_dir) / "measured_cards.json", CARD_DATA)
        # Same for the known IDs: without them nothing is held back.
        if CARD_DATA.exists() and RELIC_DATA.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("build_known_ids", IDS_PY)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.write(Path(output_dir) / "known_ids.json")
        return True


def _ingest_asset_hash() -> str:
    import hashlib
    h = hashlib.sha256()
    for p in (INGEST_DIR / "handler.py", INGEST_DIR / "measured.py", INGEST_DIR / "feedback.py",
              INGEST_DIR / "reactions.py", INGEST_DIR / "session.py", INGEST_DIR / "views.py", RUN_PY, DERIVE_PY, CARDS_PY, CARD_DATA,
              IDS_PY, RELIC_DATA, RETIRED_IDS, INGEST_DIR / "benchmark.py", FIGHT_DEMAND_PY, POWER_DATA):
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()


STEAM_API_KEY_PARAM_NAME ="/slay-my-stats/steam-api-key"
# Signs prod's sign-in cookies (session.py). A SecureString created once by hand, like the
# Steam API key (README "Deploying"); replacing its value signs everyone out.
SESSION_KEY_PARAM_NAME = "/slay-my-stats/session-key"
DOMAIN_NAME = "slay-my-stats.com"
# The ACM certificate and Route 53 hosted zone are created outside CDK and
# passed in as context ("certificateArn", "hostedZoneId"), which lives in the
# untracked infra/cdk.context.json so account-specific IDs stay out of the repo.
# The gamma stage has its own pair ("gammaCertificateArn", "gammaHostedZoneId"):
# a certificate for gamma.<domain> and the hosted zone that subdomain is
# delegated to.
# The certificate must be in us-east-1 -- CloudFront's control plane only looks
# there for certificates, regardless of what region the rest of this stack
# deploys to.
# Everything these services bill is covered by free tier at normal traffic,
# so any actual spend on them means the ingest path is being abused.
# The game mod's way in (POST /mod on the mod's own function) sends one run
# at a time as each one ends, so a few requests an hour per player is normal.
# Either of these in one window means something is wrong -- a mod stuck
# sending in a loop, or someone poking at it -- and emails the alert topic.
# Refusals are the 401s and 403s: a ticket Steam won't confirm, or (gamma) an
# address that isn't allowed.
MOD_REQUESTS_ALARM = (30, Duration.minutes(5))
MOD_REFUSALS_ALARM = (10, Duration.minutes(15))

KILL_SWITCH_BUDGET_USD = 1
# The data bucket alarm: far past its size (24 MB on 2026-11-17), well under the 5 GB free tier.
DATA_BUCKET_ALARM_BYTES = 2**30
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

# Checked on every request, before CloudFront consults its cache.
STEAM_GATE_CODE = """
var crypto = require('crypto');
var ALLOWED_IDS = %s;
var SESSION_KEY = %s;
function handler(event) {
    var request = event.request;
    var cookie = request.cookies['__Host-gamma'];
    var token = cookie ? cookie.value : '';
    var m = token.match(/^(\\d{17})\\.(\\d{10})\\.([a-f0-9]{64})$/);
    var valid = false;
    if (m && ALLOWED_IDS.indexOf(m[1]) !== -1 && Number(m[2]) > Date.now() / 1000) {
        var signature = crypto.createHmac('sha256', SESSION_KEY).update(m[1] + '.' + m[2]).digest('hex');
        var diff = 0;
        for (var i = 0; i < 64; i++) diff |= signature.charCodeAt(i) ^ m[3].charCodeAt(i);
        valid = diff === 0;
    }
    if (!valid) return {
        statusCode: 302,
        headers: {
            location: { value: '/auth/login' },
            'cache-control': { value: 'no-store' }
        }
    };
%s    return request;
}
"""


def feedback_access(stack, role, read, write=()):
    """Let a function read and write only the feedback items of the given partitions (`env`).

    dynamodb:LeadingKeys holds every key a call names, and the indexes are partitioned on env
    too, so a Query on any index for another env is refused. The Null check closes the gap
    where a call names no key at all (ForAllValues would pass it).
    """
    table = stack.format_arn(service="dynamodb", resource="table", resource_name=FEEDBACK_TABLE)
    def allow(actions, envs, resources):
        role.add_to_principal_policy(iam.PolicyStatement(
            actions=actions, resources=resources,
            conditions={"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": list(envs)},
                        "Null": {"dynamodb:LeadingKeys": "false"}}))
    allow(["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:ConditionCheckItem"],
          read, [table, f"{table}/index/*"])
    if write:
        allow(["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"], write, [table])


class SlayMyStatsStack(Stack):
    """
    The whole site. stage="prod" is slay-my-stats.com; stage="gamma" is a
    second, separate copy at gamma.slay-my-stats.com for trying a deploy
    against real CloudFront before production sees it. Gamma has its own
    buckets, upload function and kill switch, and shares only the Steam API
    key. Its data bucket is deleted with the stack: nothing in it is real.
    Gamma answers only accounts in the "gammaAllowedSteamIds" context list.
    """

    def __init__(self, scope: Construct, construct_id: str, *, stage: str = "prod", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        gamma = stage == "gamma"
        domain_name = f"gamma.{DOMAIN_NAME}" if gamma else DOMAIN_NAME
        # Bucket and budget names: slay-my-stats-data, slay-my-stats-gamma-data.
        name_prefix = "slay-my-stats-gamma" if gamma else "slay-my-stats"

        def required_context(key: str) -> str:
            value = self.node.try_get_context(key)
            if not value:
                raise ValueError(f'Set "{key}" in infra/cdk.context.json (see README "Deploying").')
            return value

        certificate_arn = required_context("gammaCertificateArn" if gamma else "certificateArn")
        hosted_zone_id = required_context("gammaHostedZoneId" if gamma else "hostedZoneId")
        # Where failed uploads are emailed. Kept out of the repo with the rest.
        alert_email = required_context("alertEmail")
        # Required, not optional: a gamma deploy without it would be public.
        allowed_ids = required_context("gammaAllowedSteamIds") if gamma else []
        if gamma and not (isinstance(allowed_ids, list) and all(
                isinstance(sid, str) and len(sid) == 17 and sid.isascii() and sid.isdigit() for sid in allowed_ids)):
            raise ValueError('"gammaAllowedSteamIds" must be a nonempty list of SteamID64 strings.')
        session_key = required_context("gammaSessionSecret") if gamma else ""
        if gamma and not (isinstance(session_key, str) and len(session_key) >= 64):
            raise ValueError('"gammaSessionSecret" must be a random secret of at least 64 characters.')
        # CloudFront sends this on every request to the ingest Function URL, so the handler can tell
        # its CloudFront-Viewer-Address from one a direct caller made up (the per-address upload limit).
        origin_secret = required_context("originVerifySecret")
        if not (isinstance(origin_secret, str) and len(origin_secret) >= 32):
            raise ValueError('"originVerifySecret" must be a random secret of at least 32 characters.')
        # Only the owner resolves, reopens or backlogs feedback; other reviewers write and +1.
        owner_id = required_context("ownerSteamId")
        if not (isinstance(owner_id, str) and len(owner_id) == 17 and owner_id.isascii() and owner_id.isdigit()):
            raise ValueError('"ownerSteamId" must be a SteamID64 string.')
        if gamma and owner_id not in allowed_ids:
            raise ValueError('"ownerSteamId" must be one of "gammaAllowedSteamIds".')

        # users/<slug>.json.gz and users/<slug>/<YYYY-MM>.json.gz: each
        # player's profile summary and runs by month, plus the public
        # users/_index.json.gz list and users/_uploads/<id>.json.gz, each
        # upload's result for the page to poll. Private (CloudFront only
        # serves users/*): ids/<steamid>.json.gz maps Steam IDs to slugs,
        # coop/<seed>.json.gz lists co-op copies by party Steam IDs (behind each
        # profile's public users/<slug>/_coop.json.gz links),
        # limits/ holds the upload rate limits, analytics/ a note per upload,
        # and raw/<steamid>/ keeps every upload as sent, so profiles can be
        # rebuilt after a parser fix.
        # RETAIN: players' uploads live only here, so tearing the stack down
        # leaves the bucket behind. Standing the stack up again then needs it
        # imported or emptied and deleted by hand first. Gamma is retained too,
        # for its feedback notes, and is versioned so an overwritten or deleted
        # note can be recovered. Versioning is per bucket, so the rules below
        # expire old versions of everything but feedback/, which keeps them.
        # Prod can take the same by setting `versioned` for both stacks.
        data_bucket = s3.Bucket(
            self, "DataBucket",
            bucket_name=f"{name_prefix}-data",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            versioned=gamma,
            # The upload page POSTs each upload straight here, with a
            # presigned form the ingest function hands out.
            cors=[s3.CorsRule(
                allowed_origins=[f"https://{domain_name}"],
                allowed_methods=[s3.HttpMethods.POST],
                allowed_headers=["*"],
            )],
            # Upload results are only read while the page waits for them.
            # Nothing else here expires: raw/ and analytics/ are kept for good.
            lifecycle_rules=[
                s3.LifecycleRule(prefix="users/_uploads/", expiration=Duration.days(7)),
            ] + ([
                # Gamma is versioned: a month of history for everything that is
                # rewritten often, none expired under feedback/.
                s3.LifecycleRule(
                    prefix=prefix,
                    noncurrent_version_expiration=Duration.days(30),
                    expired_object_delete_marker=True,
                ) for prefix in ("users/", "ids/", "coop/", "limits/", "analytics/", "raw/")
            ] if gamma else []),
        )

        # Built static site (index.html, js/*.js, dashboard.css, game art).
        site_bucket = s3.Bucket(
            self, "SiteBucket",
            bucket_name=f"{name_prefix}-site",
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
            code=cloudfront.FunctionCode.from_inline(
                STEAM_GATE_CODE % (json.dumps(allowed_ids), json.dumps(session_key), '    request.uri = "/index.html";\n')
                if gamma else PAGE_URL_REWRITE_CODE),
        )
        # Everything that isn't a page: assets, art and users/* data.
        gate_associations = [
            cloudfront.FunctionAssociation(
                function=cloudfront.Function(
                    self, "SteamGateFunction",
                    runtime=cloudfront.FunctionRuntime.JS_2_0,
                    code=cloudfront.FunctionCode.from_inline(STEAM_GATE_CODE % (json.dumps(allowed_ids), json.dumps(session_key), "")),
                ),
                event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
            ),
        ] if gamma else None
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

        # CloudFront's standard access logs. CloudFront only writes these with
        # ACLs on, hence BUCKET_OWNER_PREFERRED. A gamma stack's go with it;
        # tools/visit_sources.py summarizes them.
        log_bucket = s3.Bucket(
            self, "AccessLogBucket",
            bucket_name=f"{name_prefix}-access-logs",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
            removal_policy=RemovalPolicy.DESTROY if gamma else RemovalPolicy.RETAIN,
            auto_delete_objects=gamma,
        )

        distribution = cloudfront.Distribution(
            self, "Distribution",
            enable_logging=True,
            log_bucket=log_bucket,
            log_file_prefix="site/",
            domain_names=[domain_name],
            certificate=certificate,
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=site_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                function_associations=gate_associations,
            ),
            additional_behaviors={
                "users/*": cloudfront.BehaviorOptions(
                    origin=origins.S3BucketOrigin.with_origin_access_control(data_bucket),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    # Disabled outright, not just short-TTL: a viewer landing right
                    # after an upload must see that upload, not a cached miss.
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    function_associations=gate_associations,
                ),
                "u/*": page_behavior,
                # Exact paths, not "<name>*", so a page can't catch an asset
                # that starts with the same letters; the second is /<name>/.
                **{pattern: page_behavior for name in SITE_PAGES for pattern in (name, f"{name}/")},
                # Each What's new post's own link; boot.js shows the page at that post.
                **{f"{name}/*": page_behavior for name in POST_PAGES},
            },
        )

        hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "HostedZone",
            hosted_zone_id=hosted_zone_id,
            zone_name=domain_name,
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

        # The site's /auth/* behind CloudFront (session.py): Steam sign-in, then per upload
        # the rate limits and a presigned POST for one new raw/ object (it never sees the
        # upload), and on prod the feedback notes. On gamma, sign-in and feedback are
        # GammaAuthFunction's and only /auth/upload comes here.
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
                # The website's way in only: /mod is the mod function's.
                "ENTRY": "site",
                # Sign-ins return here, and POSTs must come from here.
                "SITE_ORIGIN": f"https://{domain_name}",
                "ORIGIN_VERIFY_SECRET": origin_secret,
                # The Function URL is reachable directly, past CloudFront's
                # gate, so the handler checks the signed-in account itself.
                **({"ALLOWED_STEAM_IDS": ",".join(allowed_ids), "GAMMA_SESSION_SECRET": session_key,
                    "GAMMA_ORIGIN": f"https://{domain_name}"} if gamma else {
                    "SESSION_SECRET_PARAM_NAME": SESSION_KEY_PARAM_NAME,
                    # Feedback: prod writes and reads prod's notes only; only the owner is an admin.
                    "FEEDBACK_TABLE": FEEDBACK_TABLE, "FEEDBACK_ENV": "prod", "FEEDBACK_READ_ENVS": "prod",
                    "ADMIN_STEAM_IDS": owner_id,
                    "STEAM_API_KEY_PARAM_NAME": STEAM_API_KEY_PARAM_NAME}),
            },
        )
        # Read/write covers the limits, the slug lookup, and signing the
        # upload form (a presigned POST acts with this role's permissions).
        data_bucket.grant_read_write(ingest_fn)

        # Merges each upload into its player's profile, run by S3 as the
        # upload lands. It goes a month at a time, so only the months an
        # upload touches are ever in memory: 667 runs took 7.8 s and 155 MB
        # live, and the profile's size doesn't matter.
        process_log_group = logs.LogGroup(
            self, "ProcessLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        # Lambda calls this directly (no queue, so nothing costs anything
        # while uploads work) once an upload has failed every retry, by error
        # or timeout: it tells the uploader's page, logs it, and emails you. The raw/
        # object is kept, so the upload can be processed again once whatever
        # broke is fixed.
        failure_log_group = logs.LogGroup(
            self, "ProcessFailureLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        failure_fn = lambda_.Function(
            self, "ProcessFailureFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.failure_handler",
            code=ingest_code,
            timeout=Duration.seconds(15),
            log_group=failure_log_group,
            environment={"DATA_BUCKET": data_bucket.bucket_name},
        )
        data_bucket.grant_read_write(failure_fn, "users/_uploads/*")
        # Emails you about each one. AWS sends a confirmation email first:
        # nothing arrives until the link in it is clicked.
        alert_topic = sns.Topic(self, "AlertTopic")
        alert_topic.add_subscription(subscriptions.EmailSubscription(alert_email))
        alert_topic.grant_publish(failure_fn)
        failure_fn.add_environment("ALERT_TOPIC_ARN", alert_topic.topic_arn)
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
            # A 20,000-run upload took ~50 s on a desktop; Lambda's CPU at this
            # size is slower. Only an upload that big ever runs this long.
            timeout=Duration.minutes(5),
            memory_size=1024,
            log_group=process_log_group,
            environment={"DATA_BUCKET": data_bucket.bucket_name},
            retry_attempts=2,
            on_failure=lambda_destinations.LambdaDestination(failure_fn),
        )
        data_bucket.grant_read_write(process_fn)  # and delete: junk uploads aren't kept
        # Uploads arrive as form POSTs (presign_post); PUT is kept for writing
        # one by hand. A bucket-to-bucket copy (tools/seed_gamma.py) is neither,
        # so copying uploads that were already processed doesn't run them again.
        for event in (s3.EventType.OBJECT_CREATED_POST, s3.EventType.OBJECT_CREATED_PUT):
            data_bucket.add_event_notification(
                event,
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

        if not gamma:
            # Prod's sign-in key, and feedback's Steam names (looked up with the Web API key).
            ssm.StringParameter.from_secure_string_parameter_attributes(
                self, "SessionKeyParam", parameter_name=SESSION_KEY_PARAM_NAME,
            ).grant_read(ingest_fn)
            steam_api_key_param.grant_read(ingest_fn)
            ingest_fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["kms:Decrypt"],
                    resources=[self.format_arn(service="kms", resource="alias", resource_name="aws/ssm")],
                )
            )
            feedback_access(self, ingest_fn.role, read=("prod", "counter"), write=("prod", "counter"))

        # The game mod's way in: POST /mod and /mod/runs, open to any Steam
        # account. Same code as the ingest function, but a function of its
        # own, so it can be shut off alone without taking the website's
        # uploads with it (README "Mod uploads"):
        #   aws lambda put-function-concurrency --reserved-concurrent-executions 0
        # The kill switch below throttles it too. No standing cap above 0:
        # the account's concurrency limit is 10, and Lambda keeps 10 unreserved.
        # It needs the key, to ask Steam whose ticket it was handed.
        mod_log_group = logs.LogGroup(
            self, "ModIngestLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        mod_fn = lambda_.Function(
            self, "ModIngestFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=ingest_code,
            timeout=Duration.seconds(15),
            memory_size=256,
            log_group=mod_log_group,
            environment={
                "DATA_BUCKET": data_bucket.bucket_name,
                "ENTRY": "mod",
                "STEAM_API_KEY_PARAM_NAME": STEAM_API_KEY_PARAM_NAME,
                **({"ALLOWED_STEAM_IDS": ",".join(allowed_ids)} if gamma else {}),
            },
        )
        data_bucket.grant_read_write(mod_fn)
        steam_api_key_param.grant_read(mod_fn)
        mod_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt"],
                resources=[self.format_arn(service="kms", resource="alias", resource_name="aws/ssm")],
            )
        )
        # The game calls it directly, not a browser: no CORS.
        mod_fn_url = mod_fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

        # The handler logs one JSON line per request, marked "via": "mod" on
        # this path. Count them, and email when there are too many.
        from_mod = logs.FilterPattern.string_value("$.via", "=", "mod")
        mod_alarms = {
            "ModRequests": (from_mod, MOD_REQUESTS_ALARM, "Mod upload requests are coming in fast"),
            "ModRefusals": (
                logs.FilterPattern.all(from_mod, logs.FilterPattern.any(
                    logs.FilterPattern.number_value("$.status", "=", 401),
                    logs.FilterPattern.number_value("$.status", "=", 403))),
                MOD_REFUSALS_ALARM, "Mod upload requests are being refused",
            ),
        }
        # Prod only: gamma's mod traffic is testing.
        for name, (pattern, (threshold, period), what) in (mod_alarms.items() if not gamma else ()):
            metric = logs.MetricFilter(
                self, f"{name}Filter",
                log_group=mod_log_group,
                filter_pattern=pattern,
                metric_namespace=name_prefix,
                metric_name=name,
            ).metric(statistic="Sum", period=period)
            cloudwatch.Alarm(
                self, f"{name}Alarm",
                metric=metric,
                threshold=threshold,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                # No requests at all is the normal state, not missing data.
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
                alarm_description=f"{what} on {domain_name}: {threshold} or more in "
                                  f"{period.to_minutes()} minutes. Details are in ModIngestLogGroup.",
            ).add_alarm_action(cloudwatch_actions.SnsAction(alert_topic))

        # Every morning at 8 AM Central, an email of the day's uploads: who
        # added how many runs, new players, failures, the site's totals. It
        # reads the upload results the bucket already keeps for a week, so
        # nothing new is recorded. Prod only: gamma's uploads are testing.
        # Below them, the new feedback on prod and on gamma (Mondays: the open,
        # incoming and resolved counts), so feedback never sends an email of its own.
        # It also keeps the day's adoption numbers (players, by site and mod): a row
        # in the adoption table, kept for good, and the same as metrics for the dashboard.
        # Last, the page views: it counts the day's view pings in the access logs
        # (site/boot.js, views.py) and keeps the counts in analytics/views/.
        if not gamma:
            # One small row a day. Provisioned at 1/1, inside DynamoDB's always-free 25,
            # and kept if the stack is ever deleted.
            adoption_table = dynamodb.Table(
                self, "AdoptionTable",
                table_name="slay-my-stats-adoption",
                partition_key=dynamodb.Attribute(name="day", type=dynamodb.AttributeType.STRING),
                billing_mode=dynamodb.BillingMode.PROVISIONED,
                read_capacity=1, write_capacity=1,
                deletion_protection=True,
                removal_policy=RemovalPolicy.RETAIN,
            )
            digest_log_group = logs.LogGroup(
                self, "DigestLogGroup",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=RemovalPolicy.DESTROY,
            )
            digest_fn = lambda_.Function(
                self, "DigestFunction",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="handler.digest_handler",
                code=ingest_code,
                timeout=Duration.seconds(60),
                memory_size=256,
                log_group=digest_log_group,
                environment={"DATA_BUCKET": data_bucket.bucket_name, "SITE_DOMAIN": domain_name,
                             "ALERT_TOPIC_ARN": alert_topic.topic_arn, "FEEDBACK_TABLE": FEEDBACK_TABLE,
                             "FEEDBACK_DIGEST_SITES": f"prod=https://{DOMAIN_NAME},gamma=https://gamma.{DOMAIN_NAME}",
                             "ADOPTION_TABLE": adoption_table.table_name,
                             # Page views (views.py): the site's access logs, one day's at a time.
                             "ACCESS_LOG_BUCKET": log_bucket.bucket_name,
                             "ACCESS_LOG_PREFIX": f"site/{distribution.distribution_id}."},
            )
            adoption_table.grant(digest_fn, "dynamodb:PutItem")
            digest_fn.add_to_role_policy(iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"], resources=["*"],  # it takes no resource
                conditions={"StringEquals": {"cloudwatch:namespace": name_prefix}},
            ))
            feedback_access(self, digest_fn.role, read=("prod", "gamma"))
            data_bucket.grant_read(digest_fn, "users/*")
            data_bucket.grant_read(digest_fn, "analytics/*")
            data_bucket.grant_put(digest_fn, "analytics/views/*")
            log_bucket.grant_read(digest_fn, "site/*")
            alert_topic.grant_publish(digest_fn)
            scheduler.Schedule(
                self, "DigestSchedule",
                schedule=scheduler.ScheduleExpression.cron(
                    minute="0", hour="8", time_zone=TimeZone.AMERICA_CHICAGO),
                target=scheduler_targets.LambdaInvoke(digest_fn),
                description=f"Daily upload digest for {domain_name}",
            )
            benchmark_fn = lambda_.Function(
                self, "BenchmarkFunction",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="benchmark.refresh",
                code=ingest_code,
                timeout=Duration.minutes(5),
                memory_size=512,
                environment={"DATA_BUCKET": data_bucket.bucket_name},
            )
            benchmark_fn.add_to_role_policy(iam.PolicyStatement(
                actions=["s3:ListBucket"], resources=[data_bucket.bucket_arn],
            ))
            data_bucket.grant_read(benchmark_fn, "raw/*")
            data_bucket.grant_read(benchmark_fn, "ids/*")
            data_bucket.grant_read(benchmark_fn, "users/*")
            data_bucket.grant_read_write(benchmark_fn, "users/_fight-demand.json.gz")
            scheduler.Schedule(
                self, "BenchmarkSchedule",
                schedule=scheduler.ScheduleExpression.cron(
                    minute="30", hour="4", time_zone=TimeZone.AMERICA_CHICAGO),
                target=scheduler_targets.LambdaInvoke(benchmark_fn),
                description="Refresh the fight benchmark from production uploads",
            )

        if gamma:
            # Nightly copy of prod's run data into this bucket (seed.py): gamma
            # shows real players' data without anyone running tools/seed_gamma.py.
            seed_fn = lambda_.Function(
                self, "SeedFunction",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="seed.copy_prod",
                code=ingest_code,
                timeout=Duration.minutes(15),
                memory_size=512,
                environment={"DATA_BUCKET": data_bucket.bucket_name},
            )
            data_bucket.grant_read_write(seed_fn)
            prod_bucket_arn = "arn:aws:s3:::slay-my-stats-data"
            seed_fn.add_to_role_policy(iam.PolicyStatement(
                actions=["s3:ListBucket"], resources=[prod_bucket_arn]))
            seed_fn.add_to_role_policy(iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"{prod_bucket_arn}/{p}/*" for p in ("users", "ids", "coop", "raw", "telemetry")]))
            scheduler.Schedule(
                self, "SeedSchedule",
                schedule=scheduler.ScheduleExpression.cron(
                    minute="0", hour="3", time_zone=TimeZone.AMERICA_CHICAGO),
                target=scheduler_targets.LambdaInvoke(seed_fn),
                description="Copy production's run data into gamma",
            )

        # No API Gateway: the handler checks the session itself, so a bare
        # public Function URL is enough and one less moving part. Pages reach
        # it through CloudFront's auth/ behaviors below, on the site's own
        # origin, so it needs no CORS.
        fn_url = ingest_fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)
        # CloudFront-Viewer-Address (the rate limit's address) is among the viewer headers this
        # policy forwards; the Host header isn't, since the Function URL answers only its own.
        # x-origin-verify vouches for that address (see viewer_ip in the handler).
        # Behaviors match in the order they're added, so gamma's auth/upload goes before auth/*.
        def auth_behavior(path, url):
            distribution.add_behavior(
                path, origins.HttpOrigin(Fn.select(2, Fn.split("/", url)),
                                         custom_headers={"x-origin-verify": origin_secret}),
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            )
        auth_behavior("auth/upload" if gamma else "auth/*", fn_url.url)

        if gamma:
            auth_fn = lambda_.Function(
                self, "GammaAuthFunction",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="handler.gamma_auth_handler",
                code=ingest_code,
                timeout=Duration.seconds(15),
                memory_size=256,
                environment={
                    "ALLOWED_STEAM_IDS": ",".join(allowed_ids),
                    "GAMMA_SESSION_SECRET": session_key,
                    "GAMMA_ORIGIN": f"https://{domain_name}",
                    "DATA_BUCKET": data_bucket.bucket_name,
                    "STEAM_API_KEY_PARAM_NAME": STEAM_API_KEY_PARAM_NAME,
                    # Feedback: gamma writes gamma notes and reads prod's too; only the
                    # owner is an admin.
                    "FEEDBACK_TABLE": FEEDBACK_TABLE,
                    "FEEDBACK_ENV": "gamma",
                    "FEEDBACK_READ_ENVS": "gamma,prod",
                    "ADMIN_STEAM_IDS": owner_id,
                },
            )
            auth_url = auth_fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)
            feedback_access(self, auth_fn.role, read=("gamma", "prod", "counter"), write=("gamma", "counter"))
            # Feedback shows authors and resolvers by Steam name, looked up with the Web API key
            # (Steam's public profile page is unreliable from AWS addresses).
            steam_api_key_param.grant_read(auth_fn)
            auth_fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["kms:Decrypt"],
                    resources=[self.format_arn(service="kms", resource="alias", resource_name="aws/ssm")],
                )
            )

            auth_behavior("auth/*", auth_url.url)

        # Kill switch: budget breach -> SNS -> small Lambda that sets the ingest,
        # mod and process functions' reserved concurrency to 0, so every further
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
            environment={"TARGET_FUNCTION_NAMES": ",".join(
                f.function_name for f in ((ingest_fn, mod_fn, process_fn, auth_fn) if gamma else (ingest_fn, mod_fn, process_fn)))},
        )
        kill_switch_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:PutFunctionConcurrency"],
                resources=[f.function_arn for f in ((ingest_fn, mod_fn, process_fn, auth_fn) if gamma else (ingest_fn, mod_fn, process_fn))],
            )
        )
        kill_switch_fn.add_event_source(lambda_event_sources.SnsEventSource(kill_switch_topic))

        # Prod only. CloudWatch's free tier is 10 alarm metrics per account, and an alarm on
        # metric math pays for every metric inside it, so each alarm here watches one metric:
        # the two mod alarms above, the two CloudFront ones (edge_alarms_stack), and these five,
        # leaving one spare. Lambda's region-wide Errors and Throttles cover every function, both
        # stages', in one metric each: an uncaught error anywhere (sign-in, uploads, feedback,
        # processing, the digest, the kill switch) or a throttle (the kill switch fired, or the
        # account's concurrency ran out).
        if not gamma:
            five = Duration.minutes(5)
            def lambda_total(name):
                return cloudwatch.Metric(namespace="AWS/Lambda", metric_name=name,
                                         statistic="Sum", period=five)
            def feedback_metric(name):
                return cloudwatch.Metric(namespace="AWS/DynamoDB", metric_name=name, statistic="Sum",
                                         period=five, dimensions_map={"TableName": FEEDBACK_TABLE})
            bucket_size = cloudwatch.Metric(
                namespace="AWS/S3", metric_name="BucketSizeBytes", statistic="Maximum",
                period=Duration.days(1),
                dimensions_map={"BucketName": data_bucket.bucket_name, "StorageType": "StandardStorage"})
            # (name, metric, threshold, what)
            alarms = (
                ("LambdaErrors", lambda_total("Errors"), 1,
                 "A function (prod or gamma) is failing"),
                ("LambdaThrottles", lambda_total("Throttles"), 1,
                 "Functions are being turned away (kill switch or concurrency limit)"),
                ("FeedbackWriteThrottles", feedback_metric("WriteThrottleEvents"), 1,
                 "Feedback can't be saved (table write capacity)"),
                ("FeedbackReadThrottles", feedback_metric("ReadThrottleEvents"), 1,
                 "Feedback can't be read (table read capacity)"),
                # S3 reports its size once a day. 24 MB on 2026-11-17; the free tier is 5 GB.
                ("DataBucketSize", bucket_size, DATA_BUCKET_ALARM_BYTES,
                 f"The data bucket is past {DATA_BUCKET_ALARM_BYTES // 2**30} GB"),
            )
            for name, metric, threshold, what in alarms:
                cloudwatch.Alarm(
                    self, f"{name}Alarm", metric=metric, threshold=threshold, evaluation_periods=1,
                    comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                    treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
                    alarm_description=f"{what} on {domain_name}. Dashboard: {name_prefix}.",
                ).add_alarm_action(cloudwatch_actions.SnsAction(alert_topic))

            # The dashboard: adoption and page views (from the morning digest), usage, and every alarm.
            day = Duration.days(1)
            def ours(name):
                return cloudwatch.Metric(namespace=name_prefix, metric_name=name,
                                         statistic="Maximum", period=day)
            all_alarms = [a for a in self.node.find_all() if isinstance(a, cloudwatch.Alarm)]
            all_alarms += [cloudwatch.Alarm.from_alarm_arn(
                self, f"Edge{n}", f"arn:aws:cloudwatch:us-east-1:{self.account}:alarm:{EDGE_ALARM_PREFIX}{n}")
                for n in EDGE_ALARMS]
            # Every graph is a time series: CloudWatch's bar view sums the whole range into one bar.
            graph = dict(width=6, height=6)
            hour = Duration.hours(1)
            def table_use(table, name):
                return cloudwatch.Metric(namespace="AWS/DynamoDB", metric_name=name, statistic="Sum",
                                         period=hour, dimensions_map={"TableName": table},
                                         label=f"{table} {name.replace('Consumed', '').replace('CapacityUnits', '')}")
            cloudwatch.Dashboard(
                self, "Dashboard", dashboard_name=name_prefix,
                start="-P14D",
                widgets=[
                    [cloudwatch.AlarmStatusWidget(title="Alarms", alarms=all_alarms, width=24, height=4)],
                    [cloudwatch.GraphWidget(title="Production CloudFront requests (per hour)", left=[
                        cloudwatch.Metric(namespace="AWS/CloudFront", metric_name="Requests",
                                          statistic="Sum", period=hour, region="us-east-1",
                                          dimensions_map={"DistributionId": distribution.distribution_id,
                                                          "Region": "Global"})], **graph)],
                    [cloudwatch.GraphWidget(title="Players (per day)", left=[
                        ours("ActivePlayersSite"), ours("ActivePlayersMod"), ours("NewPlayers")], **graph),
                     cloudwatch.GraphWidget(title="Total players", left=[ours("TotalPlayers")], **graph),
                     cloudwatch.GraphWidget(title="Runs added (per day)", left=[ours("RunsAdded")], **graph),
                     cloudwatch.GraphWidget(title="Feedback filed (per day)", left=[ours("FeedbackFiled")], **graph)],
                    [cloudwatch.GraphWidget(title="Page views and visitors (per day)", left=[
                        ours("PageViews"), ours("Visitors")], **graph),
                     cloudwatch.GraphWidget(title="What's New reactions (daily snapshot)", left=[
                         ours("WhatsNewReactions")], **graph)],
                    [cloudwatch.GraphWidget(title="Lambda invocations, all functions (per hour)", left=[
                        cloudwatch.Metric(namespace="AWS/Lambda", metric_name="Invocations",
                                          statistic="Sum", period=hour)], **graph),
                     cloudwatch.GraphWidget(title="DynamoDB capacity used (per hour)", left=[
                         table_use(t, m) for t in (FEEDBACK_TABLE, "slay-my-stats-adoption")
                         for m in ("ConsumedReadCapacityUnits", "ConsumedWriteCapacityUnits")], **graph),
                     cloudwatch.GraphWidget(title="Data bucket size", left=[bucket_size], **graph),
                     cloudwatch.GraphWidget(title="Data bucket objects", left=[cloudwatch.Metric(
                         namespace="AWS/S3", metric_name="NumberOfObjects", statistic="Maximum", period=day,
                         dimensions_map={"BucketName": data_bucket.bucket_name,
                                         "StorageType": "AllStorageTypes"})], **graph)],
                ],
            )

        # Separate from the account-wide budget so Route53's fixed zone fees
        # can't trip it. The filter is by service across the whole account, so
        # each stage's budget sees the same spend and they trip together, each
        # shutting off its own ingest function. No budget "actions" are used (just SNS notifications),
        # so this doesn't count toward the paid action-enabled budget tier.
        budgets.CfnBudget(
            self, "KillSwitchBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=f"{name_prefix}-kill-switch",
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
        CfnOutput(self, "ModIngestFunctionUrl", value=mod_fn_url.url)
