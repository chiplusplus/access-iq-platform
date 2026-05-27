"""Unit tests for the HMAC Lambda UDF handler.

Validates:
- Single-value and batch invocation
- None/null handling per Redshift contract
- Output parity with ``pseudonymise.py`` (D-01 critical requirement)
- Key caching across warm invocations
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

# ``lambda`` is a Python keyword, so normal ``from access_iq.lambda...``
# import syntax is a SyntaxError.  Use importlib instead.
handler_module = importlib.import_module("access_iq.lambda.hmac_udf.handler")
handler = handler_module.handler  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_KEY = "test-key-123"
TEST_SECRET_ARN = "arn:aws:secretsmanager:eu-west-2:111:secret:hmac-key-abc"


def _mock_sm(secret_string: str) -> MagicMock:
    """Return a mock Secrets Manager client that returns *secret_string*."""
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": secret_string}
    return client


@pytest.fixture(autouse=True)
def _reset_key_cache(monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[misc]
    """Clear the module-level key cache before and after each test."""
    handler_module._KEY_CACHE = None  # noqa: SLF001
    monkeypatch.setenv("HMAC_KEY_SECRET_ARN", TEST_SECRET_ARN)
    yield
    handler_module._KEY_CACHE = None  # noqa: SLF001


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _expected_hex(key: str, value: str) -> str:
    """Compute the expected HMAC-SHA-256 hex digest (reference implementation)."""
    return hmac_mod.new(key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def _parse(result: str) -> dict:
    """Parse the JSON-string response from the handler."""
    return json.loads(result)


def test_handler_single_value() -> None:
    """Single NHS number returns correct HMAC hex."""
    nhs = "9434765919"
    expected = _expected_hex(TEST_KEY, nhs)

    sm = _mock_sm(json.dumps({"key": TEST_KEY}))
    with patch("access_iq.lambda.hmac_udf.handler.boto3.client", return_value=sm):
        result = _parse(handler({"arguments": [[nhs]]}, None))

    assert result == {"success": True, "results": [expected]}


def test_handler_batch() -> None:
    """Batch of 3 NHS numbers all return correct hex digests."""
    numbers = ["9434765919", "1234567881", "5555555555"]
    expected = [_expected_hex(TEST_KEY, n) for n in numbers]

    sm = _mock_sm(json.dumps({"key": TEST_KEY}))
    with patch("access_iq.lambda.hmac_udf.handler.boto3.client", return_value=sm):
        result = _parse(handler({"arguments": [[n] for n in numbers]}, None))

    assert result == {"success": True, "results": expected}


def test_handler_null_value() -> None:
    """None input produces None output (Redshift contract)."""
    sm = _mock_sm(json.dumps({"key": TEST_KEY}))
    with patch("access_iq.lambda.hmac_udf.handler.boto3.client", return_value=sm):
        result = _parse(handler({"arguments": [[None]]}, None))

    assert result == {"success": True, "results": [None]}


def test_handler_mixed_null_and_values() -> None:
    """Batch with mixed None and real values handles both correctly."""
    nhs = "9434765919"
    expected_hex = _expected_hex(TEST_KEY, nhs)

    sm = _mock_sm(json.dumps({"key": TEST_KEY}))
    with patch("access_iq.lambda.hmac_udf.handler.boto3.client", return_value=sm):
        result = _parse(handler({"arguments": [[nhs], [None], [nhs]]}, None))

    assert result == {"success": True, "results": [expected_hex, None, expected_hex]}


def test_handler_parity_with_pseudonymise() -> None:
    """Lambda handler output is byte-for-byte identical to pseudonymise.py.

    This is the critical D-01 parity test.  Both implementations must use
    ``hmac.new(key_bytes, value.encode('utf-8'), sha256).hexdigest()``.
    """
    nhs = "9434765919"
    key = "parity-check-key"

    # Reference: same computation as pseudonymise.py line 71
    reference = hmac_mod.new(key.encode("utf-8"), nhs.encode("utf-8"), hashlib.sha256).hexdigest()

    sm = _mock_sm(json.dumps({"key": key}))
    with patch("access_iq.lambda.hmac_udf.handler.boto3.client", return_value=sm):
        result = _parse(handler({"arguments": [[nhs]]}, None))

    assert result["results"][0] == reference


def test_key_caching() -> None:
    """Key is fetched from Secrets Manager only once (cached on warm Lambda)."""
    sm = _mock_sm(json.dumps({"key": TEST_KEY}))
    with patch("access_iq.lambda.hmac_udf.handler.boto3.client", return_value=sm) as mock_client:
        handler({"arguments": [["1111111111"]]}, None)
        handler({"arguments": [["2222222222"]]}, None)

    # boto3.client("secretsmanager") called once; second invocation uses cache
    mock_client.assert_called_once_with("secretsmanager")
