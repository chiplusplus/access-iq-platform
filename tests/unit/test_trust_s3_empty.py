from __future__ import annotations

from datetime import date

import boto3
from moto import mock_aws

from access_iq.ingestion.idempotency import should_skip_if_already_successful
from access_iq.ingestion.manifests import Manifest
from access_iq.ingestion.trust_s3 import ingest_trust_diagnostics_export_date_to_bronze


@mock_aws
def test_empty_trust_prefix_returns_skipped_not_success() -> None:
    """Bug 2 regression: empty trust prefix must produce status=skipped,
    not status=success, so the next run re-attempts."""
    s3 = boto3.client("s3", region_name="eu-west-2")
    trust_bucket = "northshire-trust-external-exports"
    platform_bucket = "test-platform"

    for b in [trust_bucket, platform_bucket]:
        s3.create_bucket(
            Bucket=b,
            CreateBucketConfiguration={"LocationConstraint": "eu-west-2"},
        )

    result = ingest_trust_diagnostics_export_date_to_bronze(
        s3=s3,
        trust_bucket=trust_bucket,
        prefix_root="diagnostics/orders",
        export_date=date(2026, 5, 12),
        platform_bucket=platform_bucket,
        env="dev",
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "empty_trust_prefix"
    Manifest.model_validate(result)


@mock_aws
def test_skipped_manifest_allows_next_run() -> None:
    """After writing a skipped manifest, should_skip_if_already_successful must return False."""
    s3 = boto3.client("s3", region_name="eu-west-2")
    trust_bucket = "northshire-trust-external-exports"
    platform_bucket = "test-platform"

    for b in [trust_bucket, platform_bucket]:
        s3.create_bucket(
            Bucket=b,
            CreateBucketConfiguration={"LocationConstraint": "eu-west-2"},
        )

    ingest_trust_diagnostics_export_date_to_bronze(
        s3=s3,
        trust_bucket=trust_bucket,
        prefix_root="diagnostics/orders",
        export_date=date(2026, 5, 12),
        platform_bucket=platform_bucket,
        env="dev",
    )

    assert not should_skip_if_already_successful(
        s3=s3,
        bucket=platform_bucket,
        manifest_prefix="_manifests/source=trust_s3_diagnostics/ingest_date=2026-05-12",
    )


@mock_aws
def test_non_empty_trust_prefix_returns_success() -> None:
    """With objects present, ingest should succeed normally."""
    s3 = boto3.client("s3", region_name="eu-west-2")
    trust_bucket = "northshire-trust-external-exports"
    platform_bucket = "test-platform"

    for b in [trust_bucket, platform_bucket]:
        s3.create_bucket(
            Bucket=b,
            CreateBucketConfiguration={"LocationConstraint": "eu-west-2"},
        )

    s3.put_object(
        Bucket=trust_bucket,
        Key="diagnostics/orders/export_date=20260512/orders.csv",
        Body=b"id,value\n1,a\n",
    )

    result = ingest_trust_diagnostics_export_date_to_bronze(
        s3=s3,
        trust_bucket=trust_bucket,
        prefix_root="diagnostics/orders",
        export_date=date(2026, 5, 12),
        platform_bucket=platform_bucket,
        env="dev",
    )

    assert result["status"] == "success"
    assert result["outputs"]["objects_written"] == 1
    Manifest.model_validate(result)
