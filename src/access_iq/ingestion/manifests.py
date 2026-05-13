from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)

ManifestStatus = Literal["success", "failed", "skipped"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ManifestItem(BaseModel):
    status: Literal["success", "failed"]
    error: str | None = None
    model_config = {"extra": "allow"}


class Manifest(BaseModel):
    source: str
    env: str
    run_id: str
    ingest_date: str
    started_at: str
    finished_at: str | None = None
    status: ManifestStatus
    error: list[str] = Field(default_factory=list)
    reason: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


def normalize_manifest_prefix(prefix: str) -> str:
    return prefix if prefix.endswith("/") else prefix + "/"


def build_manifest_prefix(*, source: str, ingest_date: str) -> str:
    return normalize_manifest_prefix(f"_manifests/source={source}/ingest_date={ingest_date}")


def build_manifest_key(*, source: str, ingest_date: str, run_id: str) -> str:
    return f"_manifests/source={source}/ingest_date={ingest_date}/run_id={run_id}.json"


def write_manifest(*, s3: Any, bucket: str, manifest: Manifest) -> str:
    key = build_manifest_key(
        source=manifest.source,
        ingest_date=manifest.ingest_date,
        run_id=manifest.run_id,
    )
    body = json.dumps(manifest.model_dump(), indent=2, default=str).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    log.info(
        "manifest_written",
        key=key,
        status=manifest.status,
        error_count=len(manifest.error),
    )
    return key
