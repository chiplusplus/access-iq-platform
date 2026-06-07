from __future__ import annotations

import io
import json
from datetime import UTC, datetime

from access_iq.ingestion.idempotency import (
    _latest_manifest_key,
    should_skip_if_already_successful,
)


class FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **kwargs):
        return self._pages


class FakeS3:
    def __init__(self, pages=None, objects=None):
        self._pages = pages or []
        self._objects = objects or {}

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return FakePaginator(self._pages)

    def get_object(self, *, Bucket: str, Key: str):
        body = self._objects[(Bucket, Key)]
        return {"Body": io.BytesIO(body)}


def test_latest_manifest_key_returns_none_when_no_objects():
    s3 = FakeS3(pages=[{}, {"Contents": []}])

    result = _latest_manifest_key(s3=s3, bucket="b", prefix="p/")

    assert result is None


def test_latest_manifest_key_returns_newest_key_across_pages():
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, tzinfo=UTC)
    t3 = datetime(2026, 1, 3, tzinfo=UTC)

    pages = [
        {"Contents": [{"Key": "m1.json", "LastModified": t1}]},
        {"Contents": [{"Key": "m2.json", "LastModified": t3}]},
        {"Contents": [{"Key": "m3.json", "LastModified": t2}]},
    ]
    s3 = FakeS3(pages=pages)

    result = _latest_manifest_key(s3=s3, bucket="b", prefix="p/")

    assert result == "m2.json"


def test_should_skip_returns_false_when_no_manifest():
    s3 = FakeS3(pages=[{"Contents": []}])

    result = should_skip_if_already_successful(
        s3=s3,
        bucket="bucket",
        manifest_prefix="manifests/",
    )

    assert result is False


def test_should_skip_returns_true_when_latest_manifest_success():
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    pages = [{"Contents": [{"Key": "latest.json", "LastModified": t1}]}]
    manifest = {"status": "success"}
    objects = {
        ("bucket", "latest.json"): json.dumps(manifest).encode("utf-8"),
    }
    s3 = FakeS3(pages=pages, objects=objects)

    result = should_skip_if_already_successful(
        s3=s3,
        bucket="bucket",
        manifest_prefix="manifests/",
    )

    assert result is True


def test_should_skip_returns_false_when_latest_manifest_not_success():
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    pages = [{"Contents": [{"Key": "latest.json", "LastModified": t1}]}]
    manifest = {"status": "failed"}
    objects = {
        ("bucket", "latest.json"): json.dumps(manifest).encode("utf-8"),
    }
    s3 = FakeS3(pages=pages, objects=objects)

    result = should_skip_if_already_successful(
        s3=s3,
        bucket="bucket",
        manifest_prefix="manifests/",
    )

    assert result is False
