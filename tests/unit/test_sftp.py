from __future__ import annotations

import json
import stat as stat_mod
from datetime import date
from types import SimpleNamespace

from access_iq.ingestion import sftp as mod


class FakeS3:
    def __init__(self):
        self.uploads = []
        self.puts = []

    def upload_fileobj(self, *, Fileobj, Bucket, Key, ExtraArgs=None):
        self.uploads.append({"Bucket": Bucket, "Key": Key, "Body": Fileobj.read()})

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


class FakeSession:
    def __init__(self, s3):
        self._s3 = s3

    def client(self, name: str):
        assert name == "s3"
        return self._s3


class FakeTransport:
    def __init__(self):
        self.connected = False
        self.closed = False

    def connect(self, *, username: str, password: str):
        self.connected = True
        self.username = username
        self.password = password

    def close(self):
        self.closed = True


class FakeRemoteFile:
    def __init__(self, data: bytes, should_fail: bool = False):
        self._data = data
        self._should_fail = should_fail

    def read(self):
        if self._should_fail:
            raise RuntimeError("read failed")
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSFTP:
    def __init__(self, names, files=None, dir_names=None, fail_open_for=None):
        self._names = names
        self._files = files or {}
        self._dir_names = set(dir_names or [])
        self._fail_open_for = set(fail_open_for or [])
        self.closed = False

    def listdir(self, remote_dir):
        return list(self._names)

    def stat(self, remote_path):
        name = remote_path.split("/")[-1]
        if name in self._dir_names:
            return SimpleNamespace(st_mode=stat_mod.S_IFDIR)
        return SimpleNamespace(st_mode=stat_mod.S_IFREG)

    def open(self, remote_path, mode):
        name = remote_path.split("/")[-1]
        if name in self._fail_open_for:
            raise RuntimeError("cannot open")
        return FakeRemoteFile(self._files[name])

    def close(self):
        self.closed = True


def _wire_clients(monkeypatch, s3, transport, sftp_client):
    monkeypatch.setattr(mod.boto3, "Session", lambda profile_name, region_name: FakeSession(s3))
    monkeypatch.setattr(mod.paramiko, "Transport", lambda addr: transport)
    monkeypatch.setattr(mod.paramiko.SFTPClient, "from_transport", lambda t: sftp_client)


def test_sha256_bytes_known_value():
    assert (
        mod.sha256_bytes(b"abc")
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_ingest_sftp_skips_when_idempotent(monkeypatch):
    s3 = FakeS3()
    monkeypatch.setattr(mod, "should_skip_if_already_successful", lambda **kwargs: True)
    monkeypatch.setattr(mod.boto3, "Session", lambda profile_name, region_name: FakeSession(s3))
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "run-skip")

    out = mod.ingest_sftp_directory_to_bronze(
        source_name="appointments",
        host="h",
        port=22,
        username="u",
        password="p",
        remote_dir="/in",
        platform_bucket="bucket",
        ingest_date=date(2026, 2, 20),
        env="dev",
        aws_region="us-east-1",
    )

    assert out["status"] == "skipped"
    assert out["reason"] == "latest_manifest_success"
    assert s3.puts == []


def test_ingest_sftp_success_uploads_files_and_manifest(monkeypatch):
    s3 = FakeS3()
    transport = FakeTransport()
    sftp_client = FakeSFTP(
        names=["b.txt", "subdir", "a.txt"],
        files={"a.txt": b"A", "b.txt": b"BB"},
        dir_names={"subdir"},
    )

    monkeypatch.setattr(mod, "should_skip_if_already_successful", lambda **kwargs: False)
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "run-1")
    monkeypatch.setattr(mod, "utc_now_iso", lambda: "2026-02-20T00:00:00+00:00")
    _wire_clients(monkeypatch, s3, transport, sftp_client)

    out = mod.ingest_sftp_directory_to_bronze(
        source_name="appointments",
        host="host",
        port=2222,
        username="user",
        password="pass",
        remote_dir="/in",
        platform_bucket="bucket",
        ingest_date=date(2026, 2, 20),
        env="dev",
        aws_region="us-east-1",
    )

    assert out["status"] == "success"
    assert out["outputs"]["files_succeeded"] == 2
    assert out["outputs"]["files_failed"] == 0
    assert len(s3.uploads) == 2
    assert transport.connected is True
    assert transport.closed is True
    assert sftp_client.closed is True

    manifest = json.loads(s3.puts[0]["Body"].decode("utf-8"))
    assert manifest["run_id"] == "run-1"
    assert manifest["outputs"]["files_succeeded"] == 2


def test_ingest_sftp_fail_fast_true_stops_on_first_error(monkeypatch):
    s3 = FakeS3()
    transport = FakeTransport()
    sftp_client = FakeSFTP(
        names=["a.txt", "b.txt"],
        files={"b.txt": b"ok"},
        fail_open_for={"a.txt"},
    )

    monkeypatch.setattr(mod, "should_skip_if_already_successful", lambda **kwargs: False)
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "run-ff")
    monkeypatch.setattr(mod, "utc_now_iso", lambda: "now")
    _wire_clients(monkeypatch, s3, transport, sftp_client)

    out = mod.ingest_sftp_directory_to_bronze(
        source_name="appointments",
        host="host",
        port=22,
        username="user",
        password="pass",
        remote_dir="/in",
        platform_bucket="bucket",
        ingest_date=date(2026, 2, 20),
        env="dev",
        aws_region="us-east-1",
        fail_fast=True,
    )

    assert out["status"] == "failed"
    assert isinstance(out["error"], list)
    assert len(out["error"]) == 1
    assert out["outputs"]["files_failed"] == 1
    assert out["outputs"]["files_succeeded"] == 0
    assert len(s3.uploads) == 0


def test_ingest_sftp_fail_fast_false_continues(monkeypatch):
    s3 = FakeS3()
    transport = FakeTransport()
    sftp_client = FakeSFTP(
        names=["a.txt", "b.txt"],
        files={"b.txt": b"ok"},
        fail_open_for={"a.txt"},
    )

    monkeypatch.setattr(mod, "should_skip_if_already_successful", lambda **kwargs: False)
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "run-nff")
    monkeypatch.setattr(mod, "utc_now_iso", lambda: "now")
    _wire_clients(monkeypatch, s3, transport, sftp_client)

    out = mod.ingest_sftp_directory_to_bronze(
        source_name="appointments",
        host="host",
        port=22,
        username="user",
        password="pass",
        remote_dir="/in",
        platform_bucket="bucket",
        ingest_date=date(2026, 2, 20),
        env="dev",
        aws_region="us-east-1",
        fail_fast=False,
    )

    assert out["status"] == "failed"
    assert isinstance(out["error"], list)
    assert len(out["error"]) == 1
    assert out["outputs"]["files_failed"] == 1
    assert out["outputs"]["files_succeeded"] == 1
    assert len(s3.uploads) == 1
