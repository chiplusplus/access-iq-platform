from __future__ import annotations

import importlib
import io
import json
import sys
import types
from datetime import date
from typing import Any, cast

# Safe import if optional deps are missing in local env
if "boto3" not in sys.modules:
    boto3_module = types.ModuleType("boto3")
    cast(Any, boto3_module).Session = None
    sys.modules["boto3"] = boto3_module
if "psycopg2" not in sys.modules:
    psycopg2_module = types.ModuleType("psycopg2")
    cast(Any, psycopg2_module).connect = None
    sys.modules["psycopg2"] = psycopg2_module

pg = importlib.import_module("access_iq.ingestion.postgres")


class FakeCursor:
    def __init__(self):
        self.copy_calls = []

    def copy_expert(self, sql, buffer):
        self.copy_calls.append(sql)
        buffer.write(b"id,name\n1,Ada\n")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def close(self):
        pass


class FakeS3:
    def __init__(self):
        self.uploads = []
        self.puts = []

    def upload_fileobj(self, *, Fileobj, Bucket, Key):
        self.uploads.append({"bucket": Bucket, "key": Key, "body": Fileobj.read().decode("utf-8")})

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


class FakeSession:
    def __init__(self, s3):
        self._s3 = s3

    def client(self, name):
        assert name == "s3"
        return self._s3


def test_copy_stream_writes_and_resets_pointer():
    cursor = FakeCursor()
    stream = pg._copy_stream(cursor, "COPY (SELECT * FROM t) TO STDOUT WITH CSV HEADER")

    assert isinstance(stream, io.BytesIO)
    assert stream.tell() == 0
    assert stream.read().startswith(b"id,name")


def test_ingest_table_to_bronze_uploads_expected_key(monkeypatch):
    cursor = FakeCursor()
    conn = FakeConn(cursor)
    s3 = FakeS3()

    monkeypatch.setattr(pg, "utc_now", lambda: "2026-02-20T00:00:00+00:00")
    monkeypatch.setattr(pg.psycopg2, "connect", lambda dsn: conn)

    # psycopg2.sql.Identifier.as_string() calls extensions.quote_ident(...),
    # which normally requires a real psycopg cursor/connection C type.
    # Patch it so this unit test can run with FakeCursor/FakeConn.
    monkeypatch.setattr(
        pg.psycopg2.extensions,
        "quote_ident",
        lambda ident, _ctx: f'"{ident}"',
    )

    out = pg.ingest_table_to_bronze(
        dsn="postgres://dsn",
        db="ehr",
        table="patients",
        platform_bucket="platform",
        ingest_date=date(2026, 2, 20),
        s3_client=s3,
        run_id="run-1",
    )

    assert out["status"] == "success"
    assert out["db"] == "ehr"
    assert out["table"] == "patients"
    assert (
        "bronze/source=ehr/entity=patients/ingest_date=2026-02-20/run_id=run-1/patients.csv"
        in out["s3_key"]
    )
    assert len(s3.uploads) == 1
    assert s3.uploads[0]["bucket"] == "platform"
    assert "id,name" in s3.uploads[0]["body"]
    assert cursor.copy_calls[0] == 'COPY (SELECT * FROM "patients") TO STDOUT WITH CSV HEADER'


def test_ingest_postgres_source_skips_when_latest_manifest_success(monkeypatch):
    s3 = FakeS3()

    monkeypatch.setattr(pg.uuid, "uuid4", lambda: "run-skip")
    monkeypatch.setattr(pg, "utc_now", lambda: "now")
    monkeypatch.setattr(
        pg.boto3,
        "Session",
        lambda profile_name, region_name: FakeSession(s3),
    )
    monkeypatch.setattr(pg, "should_skip_if_already_successful", lambda **kwargs: True)

    out = pg.ingest_postgres_source_to_bronze(
        db="ehr",
        dsn="postgres://dsn",
        tables=["patients"],
        platform_bucket="platform",
        ingest_date=date(2026, 2, 20),
        env="dev",
        aws_region="us-east-1",
    )

    assert out["status"] == "skipped"
    assert out["reason"] == "latest_manifest_success"
    assert s3.puts == []


def test_ingest_postgres_source_success_writes_manifest(monkeypatch):
    s3 = FakeS3()

    monkeypatch.setattr(pg.uuid, "uuid4", lambda: "run-ok")
    monkeypatch.setattr(pg, "utc_now", lambda: "now")
    monkeypatch.setattr(
        pg.boto3,
        "Session",
        lambda profile_name, region_name: FakeSession(s3),
    )
    monkeypatch.setattr(pg, "should_skip_if_already_successful", lambda **kwargs: False)
    monkeypatch.setattr(
        pg,
        "ingest_table_to_bronze",
        lambda **kwargs: {
            "db": kwargs["db"],
            "table": kwargs["table"],
            "status": "success",
            "s3_key": f"k/{kwargs['table']}.csv",
        },
    )

    out = pg.ingest_postgres_source_to_bronze(
        db="ehr",
        dsn="postgres://dsn",
        tables=["patients", "visits"],
        platform_bucket="platform",
        ingest_date=date(2026, 2, 20),
        env="dev",
        aws_region="us-east-1",
    )

    assert out["status"] == "success"
    assert out["outputs"]["tables_succeeded"] == 2
    assert out["outputs"]["tables_failed"] == 0
    assert len(s3.puts) == 1

    body = json.loads(s3.puts[0]["Body"].decode("utf-8"))
    assert body["run_id"] == "run-ok"
    assert body["status"] == "success"


def test_ingest_postgres_source_fail_fast_true_stops_on_first_error(monkeypatch):
    s3 = FakeS3()

    monkeypatch.setattr(pg.uuid, "uuid4", lambda: "run-fail-fast")
    monkeypatch.setattr(pg, "utc_now", lambda: "now")
    monkeypatch.setattr(
        pg.boto3,
        "Session",
        lambda profile_name, region_name: FakeSession(s3),
    )
    monkeypatch.setattr(pg, "should_skip_if_already_successful", lambda **kwargs: False)

    calls = {"n": 0}

    def fake_ingest_table(**kwargs):
        calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(pg, "ingest_table_to_bronze", fake_ingest_table)

    out = pg.ingest_postgres_source_to_bronze(
        db="ehr",
        dsn="postgres://dsn",
        tables=["patients", "visits"],
        platform_bucket="platform",
        ingest_date=date(2026, 2, 20),
        env="dev",
        aws_region="us-east-1",
        fail_fast=True,
    )

    assert calls["n"] == 1
    assert out["status"] == "failed"
    assert out["outputs"]["tables_failed"] == 1


def test_ingest_postgres_source_fail_fast_false_continues(monkeypatch):
    s3 = FakeS3()

    monkeypatch.setattr(pg.uuid, "uuid4", lambda: "run-no-fast")
    monkeypatch.setattr(pg, "utc_now", lambda: "now")
    monkeypatch.setattr(
        pg.boto3,
        "Session",
        lambda profile_name, region_name: FakeSession(s3),
    )
    monkeypatch.setattr(pg, "should_skip_if_already_successful", lambda **kwargs: False)

    state = {"n": 0}

    def fake_ingest_table(**kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("first fails")
        return {"db": "ehr", "table": kwargs["table"], "status": "success"}

    monkeypatch.setattr(pg, "ingest_table_to_bronze", fake_ingest_table)

    out = pg.ingest_postgres_source_to_bronze(
        db="ehr",
        dsn="postgres://dsn",
        tables=["patients", "visits"],
        platform_bucket="platform",
        ingest_date=date(2026, 2, 20),
        env="dev",
        aws_region="us-east-1",
        fail_fast=False,
    )

    assert state["n"] == 2
    assert out["status"] == "failed"
    assert out["outputs"]["tables_succeeded"] == 1
    assert out["outputs"]["tables_failed"] == 1
