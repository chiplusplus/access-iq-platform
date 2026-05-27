"""HMAC-SHA-256 Lambda UDF handler for Redshift CREATE EXTERNAL FUNCTION.

Backs the ``f_hmac_nhs_number`` external function that Silver models call
via the ``{{ hmac_pseudonymise() }}`` dbt macro.  The handler fetches the
HMAC key from Secrets Manager once per warm Lambda instance and caches it
in module-level state (Lambda is single-threaded — no lock needed).

Redshift batch contract
-----------------------
``event["arguments"]`` is a list of single-element lists::

    {"arguments": [["nhs1"], ["nhs2"], [None]]}

Return format::

    {"results": ["hex1", "hex2", null]}

Threat mitigations
------------------
* T-05-01: Input NHS numbers are **never** logged.
* T-05-02: ``None`` inputs produce ``None`` outputs (no crash/leak).
* T-05-03: Only the key ARN is in the env var; the key itself is fetched
  at runtime from Secrets Manager via IAM role.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

import boto3

_KEY_CACHE: bytes | None = None


def _get_key() -> bytes:
    """Fetch HMAC key from Secrets Manager (cached after first call)."""
    global _KEY_CACHE  # noqa: PLW0603
    if _KEY_CACHE is not None:
        return _KEY_CACHE

    arn = os.environ["HMAC_KEY_SECRET_ARN"]
    client = boto3.client("secretsmanager")
    resp = client.get_secret_value(SecretId=arn)
    payload = json.loads(resp["SecretString"])
    _KEY_CACHE = str(payload["key"]).encode("utf-8")
    return _KEY_CACHE


def handler(event: dict, context: object) -> dict:  # noqa: ARG001
    """Redshift Lambda UDF entry point.

    Parameters
    ----------
    event : dict
        ``{"arguments": [["val"], ["val"], [None], ...]}``
    context : object
        Lambda context (unused).

    Returns
    -------
    dict
        ``{"results": ["hex", "hex", null, ...]}``
    """
    key = _get_key()
    results: list[str | None] = []
    for row in event["arguments"]:
        value = row[0]
        if value is None:
            results.append(None)
        else:
            results.append(hmac.new(key, str(value).encode("utf-8"), hashlib.sha256).hexdigest())
    return {"results": results}
