from __future__ import annotations

import json
from datetime import date

from access_iq.ingestion import manifests as manifests_mod
from access_iq.ingestion import trust_s3 as mod


class FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **kwargs):
        return self._pages


class FakeS3:
    def __init__(self, pages=None):
        self.pages = pages or []
        self.copies = []
        self.puts = []

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return FakePaginator(self.pages)

    def copy_object(self, **kwargs):
        self.copies.append(kwargs)

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


def test_provider_ref_skip_when_idempotent(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(mod, "should_skip_if_already_successful", lambda **kwargs: True)
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "run-skip")

    out = mod.ingest_trust_provider_ref_to_bronze(
        s3=s3,
        trust_bucket="trust",
        trust_key="provider.xlsx",
        platform_bucket="platform",
        ingest_date=date(2026, 2, 20),
        env="dev",
    )

    assert out["status"] == "skipped"
    assert out["reason"] == "latest_manifest_success"
    assert s3.copies == []
    assert s3.puts == []


def test_provider_ref_success_copies_and_writes_manifest(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(mod, "should_skip_if_already_successful", lambda **kwargs: False)
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "run-1")
    monkeypatch.setattr(manifests_mod, "utc_now_iso", lambda: "now")
    monkeypatch.setattr(mod, "utc_now_iso", lambda: "now")

    out = mod.ingest_trust_provider_ref_to_bronze(
        s3=s3,
        trust_bucket="trust",
        trust_key="provider.xlsx",
        platform_bucket="platform",
        ingest_date=date(2026, 2, 20),
        env="dev",
    )

    assert out["status"] == "success"
    assert len(s3.copies) == 1
    assert s3.copies[0]["CopySource"] == {"Bucket": "trust", "Key": "provider.xlsx"}
    assert len(s3.puts) == 1
    manifest = json.loads(s3.puts[0]["Body"].decode("utf-8"))
    assert manifest["run_id"] == "run-1"
    assert manifest["outputs"]["objects_written"] == 1


def test_diagnostics_skip_when_idempotent(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(mod, "should_skip_if_already_successful", lambda **kwargs: True)
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "run-skip")

    out = mod.ingest_trust_diagnostics_export_date_to_bronze(
        s3=s3,
        trust_bucket="trust",
        prefix_root="diag",
        export_date=date(2026, 2, 20),
        platform_bucket="platform",
        env="dev",
    )

    assert out["status"] == "skipped"
    assert s3.copies == []
    assert s3.puts == []


def test_diagnostics_success_multiple_objects(monkeypatch):
    pages = [
        {
            "Contents": [
                {"Key": "diag/export_date=20260220/a.csv", "Size": 10, "ETag": "e1"},
                {"Key": "diag/export_date=20260220/b.csv", "Size": 20, "ETag": "e2"},
            ]
        }
    ]
    s3 = FakeS3(pages=pages)
    monkeypatch.setattr(mod, "should_skip_if_already_successful", lambda **kwargs: False)
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "run-2")
    monkeypatch.setattr(manifests_mod, "utc_now_iso", lambda: "now")
    monkeypatch.setattr(mod, "utc_now_iso", lambda: "now")

    out = mod.ingest_trust_diagnostics_export_date_to_bronze(
        s3=s3,
        trust_bucket="trust",
        prefix_root="diag/",
        export_date=date(2026, 2, 20),
        platform_bucket="platform",
        env="dev",
    )

    assert out["status"] == "success"
    assert out["inputs"]["trust_prefix"] == "diag/export_date=20260220/"
    assert len(s3.copies) == 2
    assert out["outputs"]["objects_written"] == 2
    assert out["outputs"]["objects_failed"] == 0
    assert len(s3.puts) == 1


def test_diagnostics_fail_fast_true_breaks_on_first_error(monkeypatch):
    pages = [{"Contents": [{"Key": "diag/export_date=20260220/a.csv", "Size": 1}]}]
    s3 = FakeS3(pages=pages)

    monkeypatch.setattr(mod, "should_skip_if_already_successful", lambda **kwargs: False)
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "run-3")
    monkeypatch.setattr(manifests_mod, "utc_now_iso", lambda: "now")
    monkeypatch.setattr(mod, "utc_now_iso", lambda: "now")

    def fail_copy(**kwargs):
        raise RuntimeError("copy failed")

    monkeypatch.setattr(s3, "copy_object", fail_copy)

    out = mod.ingest_trust_diagnostics_export_date_to_bronze(
        s3=s3,
        trust_bucket="trust",
        prefix_root="diag",
        export_date=date(2026, 2, 20),
        platform_bucket="platform",
        env="dev",
        fail_fast=True,
    )

    assert out["status"] == "failed"
    assert isinstance(out["error"], list)
    assert len(out["error"]) == 1
    assert out["outputs"]["objects_failed"] == 1
    assert out["outputs"]["objects_written"] == 0
    assert len(s3.puts) == 1


def test_diagnostics_fail_fast_false_continues(monkeypatch):
    pages = [
        {
            "Contents": [
                {"Key": "diag/export_date=20260220/a.csv", "Size": 1},
                {"Key": "diag/export_date=20260220/b.csv", "Size": 2},
            ]
        }
    ]
    s3 = FakeS3(pages=pages)

    monkeypatch.setattr(mod, "should_skip_if_already_successful", lambda **kwargs: False)
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "run-4")
    monkeypatch.setattr(manifests_mod, "utc_now_iso", lambda: "now")
    monkeypatch.setattr(mod, "utc_now_iso", lambda: "now")

    calls = {"n": 0}

    def copy_then_succeed(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first fails")
        return None

    monkeypatch.setattr(s3, "copy_object", copy_then_succeed)

    out = mod.ingest_trust_diagnostics_export_date_to_bronze(
        s3=s3,
        trust_bucket="trust",
        prefix_root="diag",
        export_date=date(2026, 2, 20),
        platform_bucket="platform",
        env="dev",
        fail_fast=False,
    )

    assert out["status"] == "failed"
    assert isinstance(out["error"], list)
    assert len(out["error"]) == 1
    assert out["outputs"]["objects_failed"] == 1
    assert out["outputs"]["objects_written"] == 1
    assert len(s3.puts) == 1
