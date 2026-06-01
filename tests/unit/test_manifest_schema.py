from __future__ import annotations

import pytest
from pydantic import ValidationError

from access_iq.ingestion.manifests import (
    Manifest,
    build_manifest_key,
    build_manifest_prefix,
)


def _base_fields() -> dict:
    return {
        "source": "ehr",
        "env": "dev",
        "run_id": "r1",
        "ingest_date": "2026-05-12",
        "started_at": "2026-05-12T00:00:00+00:00",
        "status": "success",
    }


def test_manifest_defaults_error_to_empty_list() -> None:
    m = Manifest(**_base_fields())
    assert m.error == []


def test_manifest_rejects_error_as_string() -> None:
    with pytest.raises(ValidationError):
        Manifest(**{**_base_fields(), "error": "oops"})


def test_manifest_accepts_error_as_list() -> None:
    m = Manifest(**{**_base_fields(), "error": ["a", "b"]})
    assert m.error == ["a", "b"]


def test_manifest_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        Manifest(**{**_base_fields(), "status": "weird"})


def test_manifest_accepts_skipped_status() -> None:
    m = Manifest(**{**_base_fields(), "status": "skipped", "reason": "empty_trust_prefix"})
    assert m.status == "skipped"
    assert m.reason == "empty_trust_prefix"


def test_build_manifest_key() -> None:
    key = build_manifest_key(source="ehr", ingest_date="2026-05-12", run_id="r1")
    assert key == "_manifests/source=ehr/ingest_date=2026-05-12/run_id=r1.json"


def test_build_manifest_prefix_trailing_slash() -> None:
    prefix = build_manifest_prefix(source="ehr", ingest_date="2026-05-12")
    assert prefix.endswith("/")
    assert prefix == "_manifests/source=ehr/ingest_date=2026-05-12/"
