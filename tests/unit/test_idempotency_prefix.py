from __future__ import annotations

import json

import boto3
from moto import mock_aws

from access_iq.ingestion.idempotency import should_skip_if_already_successful
from access_iq.ingestion.manifests import normalize_manifest_prefix


def test_normalize_adds_trailing_slash() -> None:
    assert normalize_manifest_prefix("_manifests/source=ehr/ingest_date=2026-05-12") == (
        "_manifests/source=ehr/ingest_date=2026-05-12/"
    )


def test_normalize_idempotent_with_slash() -> None:
    val = "_manifests/source=ehr/ingest_date=2026-05-12/"
    assert normalize_manifest_prefix(val) == val


@mock_aws
def test_prefix_isolation_prevents_cross_source_match() -> None:
    """The trailing-slash fix must prevent source=ehr from matching source=ehr_extra."""
    s3 = boto3.client("s3", region_name="eu-west-2")
    bucket = "test-bucket"
    s3.create_bucket(
        Bucket=bucket,
        CreateBucketConfiguration={"LocationConstraint": "eu-west-2"},
    )

    ehr_manifest = {
        "source": "ehr",
        "status": "success",
        "run_id": "r1",
        "ingest_date": "2026-05-12",
    }
    ehr_extra_manifest = {
        "source": "ehr_extra",
        "status": "success",
        "run_id": "r2",
        "ingest_date": "2026-05-12",
    }

    s3.put_object(
        Bucket=bucket,
        Key="_manifests/source=ehr/ingest_date=2026-05-12/run_id=r1.json",
        Body=json.dumps(ehr_manifest).encode(),
    )
    s3.put_object(
        Bucket=bucket,
        Key="_manifests/source=ehr_extra/ingest_date=2026-05-12/run_id=r2.json",
        Body=json.dumps(ehr_extra_manifest).encode(),
    )

    assert should_skip_if_already_successful(
        s3=s3,
        bucket=bucket,
        manifest_prefix="_manifests/source=ehr/ingest_date=2026-05-12",
    )

    assert should_skip_if_already_successful(
        s3=s3,
        bucket=bucket,
        manifest_prefix="_manifests/source=ehr_extra/ingest_date=2026-05-12",
    )


@mock_aws
def test_no_manifest_returns_false() -> None:
    s3 = boto3.client("s3", region_name="eu-west-2")
    s3.create_bucket(
        Bucket="test-bucket",
        CreateBucketConfiguration={"LocationConstraint": "eu-west-2"},
    )
    assert not should_skip_if_already_successful(
        s3=s3,
        bucket="test-bucket",
        manifest_prefix="_manifests/source=new/ingest_date=2026-05-12",
    )


@mock_aws
def test_skipped_manifest_does_not_skip() -> None:
    """A manifest with status=skipped should NOT cause the next run to skip."""
    s3 = boto3.client("s3", region_name="eu-west-2")
    bucket = "test-bucket"
    s3.create_bucket(
        Bucket=bucket,
        CreateBucketConfiguration={"LocationConstraint": "eu-west-2"},
    )

    skipped_manifest = {
        "source": "trust_s3_diagnostics",
        "status": "skipped",
        "reason": "empty_trust_prefix",
        "run_id": "r1",
        "ingest_date": "2026-05-12",
    }
    s3.put_object(
        Bucket=bucket,
        Key="_manifests/source=trust_s3_diagnostics/ingest_date=2026-05-12/run_id=r1.json",
        Body=json.dumps(skipped_manifest).encode(),
    )

    assert not should_skip_if_already_successful(
        s3=s3,
        bucket=bucket,
        manifest_prefix="_manifests/source=trust_s3_diagnostics/ingest_date=2026-05-12",
    )
