from __future__ import annotations

import json
from typing import Any


def _latest_manifest_key(*, s3: Any, bucket: str, prefix: str) -> str | None:
    paginator = s3.get_paginator("list_objects_v2")

    latest = None
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if latest is None or obj["LastModified"] > latest["LastModified"]:
                latest = obj

    return latest["Key"] if latest else None


def should_skip_if_already_successful(*, s3: Any, bucket: str, manifest_prefix: str) -> bool:
    """
    Returns True if the most recent manifest under manifest_prefix has status=success.
    """
    key = _latest_manifest_key(s3=s3, bucket=bucket, prefix=manifest_prefix)
    if not key:
        return False

    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    try:
        manifest = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        print(f"Warning: could not decode manifest JSON from s3://{bucket}/{key}. Not skipping.")
        return False

    if not isinstance(manifest, dict):
        print(f"Warning: manifest JSON from s3://{bucket}/{key} is not a dict. Not skipping.")
        return False

    return bool(manifest.get("status") == "success")
