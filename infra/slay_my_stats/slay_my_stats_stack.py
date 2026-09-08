from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_ssm as ssm,
)
from constructs import Construct

STEAM_API_KEY_PARAM_NAME = "/slay-my-stats/steam-api-key"


class SlayMyStatsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # One gzip JSON blob per user at users/steam-<steamid64>.json.gz.
        # DESTROY/auto-delete is fine while no real user data lives here --
        # switch to RETAIN before this bucket holds anything worth protecting.
        data_bucket = s3.Bucket(
            self, "DataBucket",
            bucket_name="slay-my-stats-data",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Built static site (index.html, js/*.js, dashboard.css, game art).
        site_bucket = s3.Bucket(
            self, "SiteBucket",
            bucket_name="slay-my-stats-site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        distribution = cloudfront.Distribution(
            self, "Distribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
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
            },
        )

        ingest_log_group = logs.LogGroup(
            self, "IngestLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        ingest_fn = lambda_.Function(
            self, "IngestFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda/ingest"),
            timeout=Duration.seconds(10),
            memory_size=256,
            # Low ceiling on purpose: an ingest spike should degrade to
            # throttling, not scale unbounded and drive up cost.
            reserved_concurrent_executions=5,
            log_group=ingest_log_group,
            environment={
                "DATA_BUCKET": data_bucket.bucket_name,
            },
        )
        data_bucket.grant_read_write(ingest_fn)

        # CloudFormation can't create a SecureString with a real value baked
        # into the template, so the parameter itself is created out-of-band
        # via the AWS CLI -- CDK only imports it by name to grant read access.
        steam_api_key_param = ssm.StringParameter.from_secure_string_parameter_attributes(
            self, "SteamApiKeyParam",
            parameter_name=STEAM_API_KEY_PARAM_NAME,
        )
        steam_api_key_param.grant_read(ingest_fn)
        # kms.Alias.from_alias_name(...).grant_decrypt() is a documented CDK
        # no-op -- it can't resolve the alias to a real key ARN without a live
        # account lookup, so no grant is ever emitted. Build the alias ARN
        # from stack tokens instead (no lookup needed) and grant explicitly.
        ingest_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt"],
                resources=[self.format_arn(service="kms", resource="alias", resource_name="aws/ssm")],
            )
        )
        ingest_fn.add_environment("STEAM_API_KEY_PARAM_NAME", STEAM_API_KEY_PARAM_NAME)

        # No API Gateway: OpenID verification happens inside the handler, so
        # a bare public Function URL is enough and one less moving part.
        fn_url = ingest_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["https://slay-my-stats.com"],
                allowed_methods=[lambda_.HttpMethod.POST],
            ),
        )

        CfnOutput(self, "SiteBucketName", value=site_bucket.bucket_name)
        CfnOutput(self, "DataBucketName", value=data_bucket.bucket_name)
        CfnOutput(self, "DistributionDomainName", value=distribution.distribution_domain_name)
        CfnOutput(self, "IngestFunctionUrl", value=fn_url.url)
