from __future__ import annotations

import json
from typing import Any

import structlog

from access_iq.ingestion.manifests import normalize_manifest_prefix

log = structlog.get_logger(__name__)


def _latest_manifest_key(*, s3: Any, bucket: str, prefix: str) -> str | None:
    paginator = s3.get_paginator("list_objects_v2")

    latest = None
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if latest is None or obj["LastModified"] > latest["LastModified"]:
                latest = obj

    return latest["Key"] if latest else None


def should_skip_if_already_successful(*, s3: Any, bucket: str, manifest_prefix: str) -> bool:
    manifest_prefix = normalize_manifest_prefix(manifest_prefix)
    key = _latest_manifest_key(s3=s3, bucket=bucket, prefix=manifest_prefix)
    if not key:
        return False

    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    try:
        manifest = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        log.warning("manifest_decode_failed", bucket=bucket, key=key)
        return False

    if not isinstance(manifest, dict):
        log.warning("manifest_not_dict", bucket=bucket, key=key)
        return False

    return bool(manifest.get("status") == "success")
