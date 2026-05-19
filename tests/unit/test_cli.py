"""CLI tests against the Settings-based (12-factor) cli.py."""

from __future__ import annotations

import sys
import types
from datetime import date

import pytest

from access_iq.config import (
    PostgresSourceCfg,
    Settings,
    SftpSourceCfg,
    TrustS3BaseCfg,
    TrustS3Cfg,
    TrustS3EntityCfg,
)
from access_iq.ingestion import cli


def _settings(**overrides: object) -> Settings:
    """Build a Settings instance without going through env vars.

    Uses ``model_construct`` to skip env-var + .env lookup; suitable for tests
    that inject a fully-typed Settings into ``cli`` via monkeypatch.
    """
    defaults: dict[str, object] = {
        "env": "dev",
        "aws_region": "us-east-1",
        "platform_bucket": "bucket",
        "aws_profile": None,
        "pseudonym_key_secret_arn": None,
        "postgres_sources": {},
        "sftp_sources": {},
        "trust_s3": None,
    }
    defaults.update(overrides)
    return Settings.model_construct(**defaults)  # type: ignore[arg-type]


def test_main_ingest_postgres_success(monkeypatch):
    s = _settings(
        postgres_sources={"ehr": PostgresSourceCfg(dsn_env="EHR_DSN", tables=["patients"])},
    )
    monkeypatch.setattr(cli, "Settings", lambda: s)
    monkeypatch.setenv("EHR_DSN", "postgres://dsn")
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "ingest-postgres", "--db", "ehr", "--ingest-date", "2026-02-01"],
    )

    called = {}

    def fake_ingest(**kwargs):
        called.update(kwargs)
        return {"status": "success", "run_id": "r1"}

    monkeypatch.setattr(cli, "ingest_postgres_source_to_bronze", fake_ingest)

    cli.main()

    assert called["db"] == "ehr"
    assert called["dsn"] == "postgres://dsn"
    assert called["ingest_date"] == date(2026, 2, 1)


def test_main_ingest_postgres_unknown_db_raises(monkeypatch):
    s = _settings(
        postgres_sources={"ehr": PostgresSourceCfg(dsn_env="EHR_DSN", tables=["patients"])},
    )
    monkeypatch.setattr(cli, "Settings", lambda: s)
    monkeypatch.setattr(sys, "argv", ["prog", "ingest-postgres", "--db", "missing"])

    with pytest.raises(SystemExit, match="Unknown db"):
        cli.main()


def test_main_ingest_postgres_missing_dsn_env_raises(monkeypatch):
    s = _settings(
        postgres_sources={"ehr": PostgresSourceCfg(dsn_env="EHR_DSN", tables=["patients"])},
    )
    monkeypatch.setattr(cli, "Settings", lambda: s)
    monkeypatch.delenv("EHR_DSN", raising=False)
    monkeypatch.setattr(sys, "argv", ["prog", "ingest-postgres", "--db", "ehr"])

    with pytest.raises(SystemExit, match="Missing required env var for ehr: EHR_DSN"):
        cli.main()


def test_main_ingest_sftp_missing_host_raises(monkeypatch):
    s = _settings(
        sftp_sources={
            "appointments": SftpSourceCfg(
                host_env="SFTP_HOST",
                port_env="SFTP_PORT",
                user_env="SFTP_USER",
                password_env="SFTP_PASSWORD",
                remote_dir="/in",
            )
        },
    )
    monkeypatch.setattr(cli, "Settings", lambda: s)
    monkeypatch.setattr(sys, "argv", ["prog", "ingest-sftp", "--name", "appointments"])
    monkeypatch.delenv("SFTP_HOST", raising=False)

    with pytest.raises(SystemExit, match="Missing required env var: SFTP_HOST"):
        cli.main()


def test_main_ingest_sftp_success(monkeypatch):
    s = _settings(
        sftp_sources={
            "appointments": SftpSourceCfg(
                host_env="SFTP_HOST",
                port_env="SFTP_PORT",
                user_env="SFTP_USER",
                password_env="SFTP_PASSWORD",
                remote_dir="/in",
                source_name="appointments_src",
            )
        },
        aws_profile="profile1",
    )
    monkeypatch.setattr(cli, "Settings", lambda: s)
    monkeypatch.setattr(sys, "argv", ["prog", "ingest-sftp", "--name", "appointments"])
    monkeypatch.setenv("SFTP_HOST", "host")
    monkeypatch.setenv("SFTP_PORT", "2222")
    monkeypatch.setenv("SFTP_USER", "user")
    monkeypatch.setenv("SFTP_PASSWORD", "pass")

    called = {}

    def fake_ingest(**kwargs):
        called.update(kwargs)
        return {"status": "success", "run_id": "r2"}

    monkeypatch.setattr(cli, "ingest_sftp_directory_to_bronze", fake_ingest)

    cli.main()

    assert called["host"] == "host"
    assert called["port"] == 2222
    assert called["username"] == "user"
    assert called["password"] == "pass"
    assert called["source_name"] == "appointments_src"


def test_main_ingest_trust_s3_missing_config_raises(monkeypatch):
    s = _settings(trust_s3=None)
    monkeypatch.setattr(cli, "Settings", lambda: s)
    monkeypatch.setattr(sys, "argv", ["prog", "ingest-trust-s3"])

    with pytest.raises(SystemExit, match="ACCESS_IQ_TRUST_S3"):
        cli.main()


def test_main_ingest_trust_s3_success(monkeypatch):
    s = _settings(
        platform_bucket="platform-bucket",
        trust_s3=TrustS3Cfg(
            base=TrustS3BaseCfg(profile="chi-dev", bucket="trust-bucket"),
            diagnostics=TrustS3EntityCfg(prefix_root="diag/", source_name="trust_s3_diagnostics"),
            provider_ref=TrustS3EntityCfg(
                key="provider_references.json", source_name="trust_s3_provider_ref"
            ),
        ),
    )
    monkeypatch.setattr(cli, "Settings", lambda: s)
    monkeypatch.setattr(sys, "argv", ["prog", "ingest-trust-s3", "--ingest-date", "2026-02-02"])

    class FakeSession:
        def __init__(self, profile_name, region_name):
            assert profile_name == "chi-dev"
            assert region_name == "us-east-1"

        def client(self, name):
            assert name == "s3"
            return object()

    monkeypatch.setattr(cli, "boto3", types.SimpleNamespace(Session=FakeSession), raising=False)

    prov_called = {}
    diag_called = {}

    def fake_provider(**kwargs):
        prov_called.update(kwargs)
        return {"status": "success", "run_id": "p1"}

    def fake_diag(**kwargs):
        diag_called.update(kwargs)
        return {"status": "success", "run_id": "d1"}

    monkeypatch.setattr(cli, "ingest_trust_provider_ref_to_bronze", fake_provider)
    monkeypatch.setattr(cli, "ingest_trust_diagnostics_export_date_to_bronze", fake_diag)

    cli.main()

    assert prov_called["trust_bucket"] == "trust-bucket"
    assert prov_called["trust_key"] == "provider_references.json"
    assert diag_called["prefix_root"] == "diag/"
    assert diag_called["export_date"] == date(2026, 2, 2)
