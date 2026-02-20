from __future__ import annotations

import json
import sys
import types
from datetime import date

import pytest

from access_iq.ingestion import cli


def test_load_config_reads_env_config(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "dev.json").write_text(
        json.dumps(
            {
                "aws_region": "us-east-1",
                "platform_bucket": "platform-bucket",
                "sources": {
                    "postgres": {"ehr": {"dsn_env": "EHR_DSN", "tables": ["patients"]}},
                    "sftp": {"appointments": {"host_env": "SFTP_HOST"}},
                    "trust_s3": {"base": {}, "diagnostics": {}, "provider_ref": {}},
                },
            }
        )
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("AWS_PROFILE", "dev-profile")

    cfg = cli.load_config()

    assert cfg.env == "dev"
    assert cfg.aws_region == "us-east-1"
    assert cfg.platform_bucket == "platform-bucket"
    assert cfg.postgres_sources["ehr"].dsn_env == "EHR_DSN"
    assert cfg.aws_profile == "dev-profile"


def test_main_ingest_postgres_success(monkeypatch, capsys):
    cfg = cli.Config(
        env="dev",
        aws_region="us-east-1",
        platform_bucket="bucket",
        postgres_sources={"ehr": cli.PostgresSource(dsn_env="EHR_DSN", tables=["patients"])},
        sftp_sources={},
        trust_s3={},
        aws_profile=None,
    )
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
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
    out = capsys.readouterr().out
    assert "success" in out


def test_main_ingest_postgres_unknown_db_raises(monkeypatch):
    cfg = cli.Config(
        env="dev",
        aws_region="us-east-1",
        platform_bucket="bucket",
        postgres_sources={"ehr": cli.PostgresSource(dsn_env="EHR_DSN", tables=["patients"])},
        sftp_sources={},
        trust_s3={},
        aws_profile=None,
    )
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(sys, "argv", ["prog", "ingest-postgres", "--db", "missing"])

    with pytest.raises(SystemExit, match="Unknown db"):
        cli.main()


def test_main_ingest_sftp_missing_host_raises(monkeypatch):
    cfg = cli.Config(
        env="dev",
        aws_region="us-east-1",
        platform_bucket="bucket",
        postgres_sources={},
        sftp_sources={
            "appointments": {
                "host_env": "SFTP_HOST",
                "port_env": "SFTP_PORT",
                "user_env": "SFTP_USER",
                "password_env": "SFTP_PASSWORD",
                "remote_dir": "/in",
            }
        },
        trust_s3={},
        aws_profile=None,
    )
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(sys, "argv", ["prog", "ingest-sftp", "--name", "appointments"])
    monkeypatch.delenv("SFTP_HOST", raising=False)

    with pytest.raises(SystemExit, match="Missing required env var: SFTP_HOST"):
        cli.main()


def test_main_ingest_sftp_success(monkeypatch):
    cfg = cli.Config(
        env="dev",
        aws_region="us-east-1",
        platform_bucket="bucket",
        postgres_sources={},
        sftp_sources={
            "appointments": {
                "host_env": "SFTP_HOST",
                "port_env": "SFTP_PORT",
                "user_env": "SFTP_USER",
                "password_env": "SFTP_PASSWORD",
                "remote_dir": "/in",
                "source_name": "appointments_src",
            }
        },
        trust_s3={},
        aws_profile="profile1",
    )
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
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


def test_main_ingest_trust_s3_success(monkeypatch):
    cfg = cli.Config(
        env="dev",
        aws_region="us-east-1",
        platform_bucket="platform-bucket",
        postgres_sources={},
        sftp_sources={},
        trust_s3={
            "base": {"profile": "chi-dev", "bucket": "trust-bucket"},
            "diagnostics": {"prefix_root": "diag/"},
            "provider_ref": {"key": "provider_references.json"},
        },
        aws_profile=None,
    )
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(sys, "argv", ["prog", "ingest-trust-s3", "--ingest-date", "2026-02-02"])

    class FakeSession:
        def __init__(self, profile_name, region_name):
            assert profile_name == "chi-dev"
            assert region_name == "us-east-1"

        def client(self, name):
            assert name == "s3"
            return object()

    # Patch symbols used by cli directly (not sys.modules["boto3"])
    monkeypatch.setattr(cli, "boto3", types.SimpleNamespace(Session=FakeSession), raising=False)
    monkeypatch.setattr(cli, "Session", FakeSession, raising=False)

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
