"""Unit tests for access_iq.config.Settings (12-factor env-var loader)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError

from access_iq.config import PostgresSourceCfg, Settings


@pytest.fixture(autouse=True)
def _clear_access_iq_env(monkeypatch):
    """Ensure no host env leakage into Settings under test."""
    for key in [
        "ACCESS_IQ_ENV",
        "ACCESS_IQ_AWS_REGION",
        "ACCESS_IQ_PLATFORM_BUCKET",
        "ACCESS_IQ_AWS_PROFILE",
        "ACCESS_IQ_PSEUDONYM_KEY_SECRET_ARN",
        "ACCESS_IQ_POSTGRES_SOURCES",
        "ACCESS_IQ_SFTP_SOURCES",
        "ACCESS_IQ_TRUST_S3",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_missing_required_platform_bucket_raises():
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)
    assert "platform_bucket" in str(excinfo.value).lower()


def test_all_required_set_returns_typed_settings(monkeypatch):
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "bucket-foo")
    monkeypatch.setenv("ACCESS_IQ_AWS_REGION", "eu-west-2")
    monkeypatch.setenv("ACCESS_IQ_ENV", "dev")

    s = Settings(_env_file=None)

    assert s.platform_bucket == "bucket-foo"
    assert s.aws_region == "eu-west-2"
    assert s.env == "dev"
    assert s.aws_profile is None
    assert s.pseudonym_key_secret_arn is None
    assert s.postgres_sources == {}
    assert s.sftp_sources == {}
    assert s.trust_s3 is None


def test_postgres_sources_json_decodes_to_typed_dict(monkeypatch):
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "bucket-foo")
    monkeypatch.setenv(
        "ACCESS_IQ_POSTGRES_SOURCES",
        json.dumps({"ehr": {"dsn_env": "EHR_DSN", "tables": ["patient", "encounter"]}}),
    )

    s = Settings(_env_file=None)

    assert "ehr" in s.postgres_sources
    assert isinstance(s.postgres_sources["ehr"], PostgresSourceCfg)
    assert s.postgres_sources["ehr"].dsn_env == "EHR_DSN"
    assert s.postgres_sources["ehr"].tables == ["patient", "encounter"]


def test_trust_s3_nested_json_validates(monkeypatch):
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "bucket-foo")
    monkeypatch.setenv(
        "ACCESS_IQ_TRUST_S3",
        json.dumps(
            {
                "base": {"bucket": "trust-bucket", "profile": "trust-readonly"},
                "diagnostics": {"prefix_root": "diag", "source_name": "trust_s3_diagnostics"},
                "provider_ref": {
                    "key": "ref/providers.xlsx",
                    "source_name": "trust_s3_provider_ref",
                },
            }
        ),
    )

    s = Settings(_env_file=None)

    assert s.trust_s3 is not None
    assert s.trust_s3.base.bucket == "trust-bucket"
    assert s.trust_s3.base.profile == "trust-readonly"
    assert s.trust_s3.diagnostics.prefix_root == "diag"
    assert s.trust_s3.provider_ref.key == "ref/providers.xlsx"


def test_malformed_json_raises_validation_error(monkeypatch):
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "bucket-foo")
    monkeypatch.setenv("ACCESS_IQ_POSTGRES_SOURCES", "{not valid json")

    with pytest.raises((ValidationError, SettingsError)):
        Settings(_env_file=None)


def test_pseudonym_key_arn_defaults_to_none(monkeypatch):
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "bucket-foo")

    s = Settings(_env_file=None)

    assert s.pseudonym_key_secret_arn is None


def test_pseudonym_key_arn_loads_from_env(monkeypatch):
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "bucket-foo")
    monkeypatch.setenv(
        "ACCESS_IQ_PSEUDONYM_KEY_SECRET_ARN",
        "arn:aws:secretsmanager:eu-west-2:111:secret:access-iq/dev/pseudonym-key",
    )

    s = Settings(_env_file=None)

    assert s.pseudonym_key_secret_arn is not None
    assert "pseudonym-key" in s.pseudonym_key_secret_arn


def test_settings_does_not_read_cwd_config_dir(monkeypatch, tmp_path):
    """Settings must not search Path.cwd() / config / *.json (12-factor)."""
    monkeypatch.chdir(tmp_path)  # no config/ dir present
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "bucket-foo")

    # Must not raise FileNotFoundError or otherwise touch the cwd.
    s = Settings(_env_file=None)

    assert s.platform_bucket == "bucket-foo"
