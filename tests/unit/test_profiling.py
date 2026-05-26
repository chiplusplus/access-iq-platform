"""Unit tests for access_iq.profiling module."""

from __future__ import annotations

import io
import json

from access_iq.profiling.s3_discovery import (
    BRONZE_ENTITIES,
    find_latest_partition,
    resolve_latest_run_id,
)

# ---------------------------------------------------------------------------
# Fake S3 helpers (following test_trust_s3.py pattern)
# ---------------------------------------------------------------------------


class FakePaginator:
    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages

    def paginate(self, **kwargs):  # noqa: ANN003, ANN201
        return self._pages


class FakeS3:
    def __init__(
        self,
        pages: list[dict] | None = None,
        objects: dict[str, bytes] | None = None,
    ) -> None:
        self.pages = pages or []
        self._objects = objects or {}

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == "list_objects_v2"
        return FakePaginator(self.pages)

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        data = self._objects.get(Key, b"{}")
        return {"Body": io.BytesIO(data)}


# ---------------------------------------------------------------------------
# Entity registry tests
# ---------------------------------------------------------------------------

EXPECTED_ENTITIES = {
    "patient_demographics",
    "encounters",
    "referrals",
    "diagnoses",
    "appointments",
    "urgent_care_logs",
    "diagnostics_orders",
    "provider_site_reference",
}


def test_entity_registry_has_8_entities() -> None:
    assert len(BRONZE_ENTITIES) == 8


def test_entity_registry_matches_sources_yml() -> None:
    assert set(BRONZE_ENTITIES.keys()) == EXPECTED_ENTITIES


def test_entity_registry_all_have_required_keys() -> None:
    for name, cfg in BRONZE_ENTITIES.items():
        assert "source_prefix" in cfg, f"{name} missing source_prefix"
        assert "pk" in cfg, f"{name} missing pk"
        assert "pk_type" in cfg, f"{name} missing pk_type"
        assert "join_keys" in cfg, f"{name} missing join_keys"
        assert isinstance(cfg["join_keys"], list), f"{name} join_keys not a list"


# ---------------------------------------------------------------------------
# find_latest_partition tests
# ---------------------------------------------------------------------------


def test_find_latest_partition_returns_latest_date() -> None:
    pages = [
        {
            "CommonPrefixes": [
                {"Prefix": "bronze/source=ehr_postgres/entity=encounters/ingest_date=2024-01-01/"},
                {"Prefix": "bronze/source=ehr_postgres/entity=encounters/ingest_date=2024-01-15/"},
                {"Prefix": "bronze/source=ehr_postgres/entity=encounters/ingest_date=2024-01-10/"},
            ]
        }
    ]
    s3 = FakeS3(pages=pages)
    result = find_latest_partition(
        s3=s3,
        bucket="test-bucket",
        entity_prefix="source=ehr_postgres/entity=encounters",
    )
    assert "ingest_date=2024-01-15" in result
    assert result == "bronze/source=ehr_postgres/entity=encounters/ingest_date=2024-01-15/"


def test_find_latest_partition_empty_bucket() -> None:
    s3 = FakeS3(pages=[{"CommonPrefixes": []}])
    result = find_latest_partition(
        s3=s3,
        bucket="test-bucket",
        entity_prefix="source=ehr_postgres/entity=encounters",
    )
    assert result == ""


def test_find_latest_partition_no_pages() -> None:
    s3 = FakeS3(pages=[{}])
    result = find_latest_partition(
        s3=s3,
        bucket="test-bucket",
        entity_prefix="source=ehr_postgres/entity=encounters",
    )
    assert result == ""


# ---------------------------------------------------------------------------
# resolve_latest_run_id tests
# ---------------------------------------------------------------------------


def test_resolve_latest_run_id_picks_successful() -> None:
    manifest_failed = json.dumps(
        {
            "run_id": "failed-run-001",
            "status": "failed",
            "finished_at": "2024-01-15T10:00:00Z",
        }
    ).encode()
    manifest_success = json.dumps(
        {
            "run_id": "success-run-002",
            "status": "success",
            "finished_at": "2024-01-15T11:00:00Z",
        }
    ).encode()

    pages = [
        {
            "Contents": [
                {
                    "Key": "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=failed-run-001.json"
                },
                {
                    "Key": "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=success-run-002.json"
                },
            ]
        }
    ]
    objects = {
        "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=failed-run-001.json": manifest_failed,
        "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=success-run-002.json": manifest_success,
    }

    s3 = FakeS3(pages=pages, objects=objects)
    result = resolve_latest_run_id(
        s3=s3,
        bucket="test-bucket",
        manifest_prefix="_manifests/source=ehr_postgres/ingest_date=2024-01-15/",
    )
    assert result == "success-run-002"


def test_resolve_latest_run_id_no_successful() -> None:
    manifest_failed = json.dumps(
        {"run_id": "failed-run-001", "status": "failed", "finished_at": "2024-01-15T10:00:00Z"}
    ).encode()

    pages = [
        {
            "Contents": [
                {
                    "Key": "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=failed-run-001.json"
                },
            ]
        }
    ]
    objects = {
        "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=failed-run-001.json": manifest_failed,
    }

    s3 = FakeS3(pages=pages, objects=objects)
    result = resolve_latest_run_id(
        s3=s3,
        bucket="test-bucket",
        manifest_prefix="_manifests/source=ehr_postgres/ingest_date=2024-01-15/",
    )
    assert result == ""


def test_resolve_latest_run_id_picks_latest_timestamp() -> None:
    manifest_old = json.dumps(
        {"run_id": "old-run", "status": "success", "finished_at": "2024-01-15T08:00:00Z"}
    ).encode()
    manifest_new = json.dumps(
        {"run_id": "new-run", "status": "success", "finished_at": "2024-01-15T12:00:00Z"}
    ).encode()

    pages = [
        {
            "Contents": [
                {"Key": "_manifests/src/run_id=old-run.json"},
                {"Key": "_manifests/src/run_id=new-run.json"},
            ]
        }
    ]
    objects = {
        "_manifests/src/run_id=old-run.json": manifest_old,
        "_manifests/src/run_id=new-run.json": manifest_new,
    }

    s3 = FakeS3(pages=pages, objects=objects)
    result = resolve_latest_run_id(s3=s3, bucket="b", manifest_prefix="_manifests/src/")
    assert result == "new-run"
