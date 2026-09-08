"""Ingest Lambda: receives an upload and merges it into the user's stored blob.

Stubbed for now. The real flow (see the slay-my-stats cloud project memory):
verify the Steam OpenID assertion, check the per-key upload cooldown against
the existing blob's Last-Modified, dedupe incoming runs by `ts`, merge and
recompute rollups, PutObject, and return the fresh DATA JSON to the caller.
"""
import json
import os

import boto3

DATA_BUCKET = os.environ["DATA_BUCKET"]
STEAM_API_KEY_PARAM_NAME = os.environ["STEAM_API_KEY_PARAM_NAME"]

_ssm = boto3.client("ssm")
_steam_api_key = None


def _get_steam_api_key():
    # Cached on the warm container so a steady stream of invocations doesn't
    # re-fetch it from SSM every time.
    global _steam_api_key
    if _steam_api_key is None:
        _steam_api_key = _ssm.get_parameter(
            Name=STEAM_API_KEY_PARAM_NAME, WithDecryption=True
        )["Parameter"]["Value"]
    return _steam_api_key


def lambda_handler(event, context):
    return {
        "statusCode": 501,
        "body": json.dumps({"error": "not implemented"}),
    }
