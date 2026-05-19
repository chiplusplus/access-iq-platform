"""HMAC-SHA-256 pseudonymisation of NHS numbers (locked decision D9).

Bare SHA-256 of a 10-digit NHS number is rainbow-trivial (10^10 keyspace).
HMAC with a per-env secret key holds the keyspace problem at bay; the key
lives in AWS Secrets Manager (SecretsStack) and is loaded once per process.
"""

from __future__ import annotations

import hmac
import json
import threading
from hashlib import sha256
from typing import Final

import boto3
import structlog

from access_iq.config import Settings

log: Final = structlog.get_logger(__name__)

_KEY_CACHE: dict[str, bytes] = {}
_CACHE_LOCK = threading.Lock()


def _load_key_from_secrets_manager(*, secret_arn: str, region: str) -> bytes:
    with _CACHE_LOCK:
        cached = _KEY_CACHE.get(secret_arn)
        if cached is not None:
            return cached

    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=secret_arn)

    secret_string = resp.get("SecretString")
    if secret_string is None:
        secret_binary = resp["SecretBinary"]
        key_bytes = secret_binary if isinstance(secret_binary, bytes) else bytes(secret_binary)
    else:
        try:
            payload = json.loads(secret_string)
            if isinstance(payload, dict) and "key" in payload:
                key_bytes = str(payload["key"]).encode("utf-8")
            else:
                key_bytes = secret_string.encode("utf-8")
        except json.JSONDecodeError:
            key_bytes = secret_string.encode("utf-8")

    with _CACHE_LOCK:
        _KEY_CACHE[secret_arn] = key_bytes
    log.info("pseudonym_key_loaded", secret_arn=secret_arn, key_len=len(key_bytes))
    return key_bytes


def pseudonymise_nhs_number(nhs_number: str, *, secret_arn: str | None = None) -> str:
    if not isinstance(nhs_number, str):
        raise TypeError(f"nhs_number must be str, got {type(nhs_number).__name__}")
    if not nhs_number:
        raise ValueError("nhs_number must be non-empty")

    settings = Settings()  # type: ignore[call-arg]
    arn = secret_arn or settings.pseudonym_key_secret_arn
    if not arn:
        raise ValueError(
            "No pseudonymisation key ARN available. Set ACCESS_IQ_PSEUDONYM_KEY_SECRET_ARN "
            "or pass `secret_arn=` explicitly."
        )

    key = _load_key_from_secrets_manager(secret_arn=arn, region=settings.aws_region)
    return hmac.new(key, nhs_number.encode("utf-8"), sha256).hexdigest()


def _clear_cache_for_tests() -> None:
    with _CACHE_LOCK:
        _KEY_CACHE.clear()
