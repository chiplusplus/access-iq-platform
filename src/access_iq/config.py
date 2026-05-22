"""12-factor runtime config for access-iq.

All values come from env vars prefixed with ``ACCESS_IQ_``. Nested fields
(``postgres_sources``, ``sftp_sources``, ``trust_s3``) accept JSON-encoded
strings — see ``.env.example`` at the repo root for the schema.

This module is the single source of runtime truth: no JSON file in CWD, no
filesystem-relative lookup. The CDK config tree at ``infra/config/{env}.json``
is a separate, deploy-time concern (see ADR 0004).
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresSourceCfg(BaseModel):
    dsn_env: str
    tables: list[str]


class SftpSourceCfg(BaseModel):
    host_env: str
    port_env: str
    user_env: str
    password_env: str | None = None
    private_key_env: str | None = None
    remote_dir: str
    source_name: str | None = None


class TrustS3BaseCfg(BaseModel):
    bucket: str
    profile: str | None = None


class TrustS3EntityCfg(BaseModel):
    prefix_root: str | None = None
    key: str | None = None
    source_name: str | None = None


class TrustS3Cfg(BaseModel):
    base: TrustS3BaseCfg
    diagnostics: TrustS3EntityCfg
    provider_ref: TrustS3EntityCfg


class Settings(BaseSettings):
    """12-factor runtime config for access-iq.

    All values come from env vars prefixed with ``ACCESS_IQ_``. Nested fields
    (``postgres_sources``, ``sftp_sources``, ``trust_s3``) accept JSON-encoded
    strings. Local dev may use a ``.env`` file at the repo root; the file is
    gitignored. ``.env.example`` is the committed schema.
    """

    model_config = SettingsConfigDict(
        env_prefix="ACCESS_IQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    env: str = "dev"
    aws_region: str = "eu-west-2"
    platform_bucket: str
    aws_profile: str | None = None

    # Pseudonymisation key ARN (consumed by Plan 05; declared here so Settings
    # is the single source of runtime truth). Optional in Phase 1.
    pseudonym_key_secret_arn: str | None = None

    lake_kms_key_arn: str | None = None

    postgres_sources: dict[str, PostgresSourceCfg] = Field(default_factory=dict)
    sftp_sources: dict[str, SftpSourceCfg] = Field(default_factory=dict)
    trust_s3: TrustS3Cfg | None = None
