from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from access_iq.security.pseudonymise import (
    _clear_cache_for_tests,
    pseudonymise_nhs_number,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    _clear_cache_for_tests()
    yield
    _clear_cache_for_tests()


def _mock_sm(secret_string: str) -> MagicMock:
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": secret_string}
    return client


def test_pseudonymise_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "test-bucket")
    monkeypatch.setenv(
        "ACCESS_IQ_PSEUDONYM_KEY_SECRET_ARN",
        "arn:aws:secretsmanager:eu-west-2:111:secret:k1",
    )

    with patch(
        "access_iq.security.pseudonymise.boto3.client", return_value=_mock_sm("super-secret")
    ):
        a = pseudonymise_nhs_number("1234567881")
        b = pseudonymise_nhs_number("1234567881")
    assert a == b
    assert len(a) == 64
    assert all(c in "0123456789abcdef" for c in a)


def test_pseudonymise_different_keys_different_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "test-bucket")
    arn1 = "arn:aws:secretsmanager:eu-west-2:111:secret:k1"
    arn2 = "arn:aws:secretsmanager:eu-west-2:111:secret:k2"

    with patch("access_iq.security.pseudonymise.boto3.client", return_value=_mock_sm("key-aaa")):
        a = pseudonymise_nhs_number("1234567881", secret_arn=arn1)
    _clear_cache_for_tests()
    with patch("access_iq.security.pseudonymise.boto3.client", return_value=_mock_sm("key-bbb")):
        b = pseudonymise_nhs_number("1234567881", secret_arn=arn2)

    assert a != b


def test_pseudonymise_different_inputs_different_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "test-bucket")
    monkeypatch.setenv(
        "ACCESS_IQ_PSEUDONYM_KEY_SECRET_ARN",
        "arn:aws:secretsmanager:eu-west-2:111:secret:k1",
    )

    with patch("access_iq.security.pseudonymise.boto3.client", return_value=_mock_sm("shared-key")):
        a = pseudonymise_nhs_number("1234567881")
        b = pseudonymise_nhs_number("9876543210")
    assert a != b


def test_pseudonymise_type_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "test-bucket")
    monkeypatch.setenv(
        "ACCESS_IQ_PSEUDONYM_KEY_SECRET_ARN",
        "arn:aws:secretsmanager:eu-west-2:111:secret:k1",
    )
    with pytest.raises(TypeError):
        pseudonymise_nhs_number(1234567881)  # type: ignore[arg-type]


def test_pseudonymise_empty_string_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "test-bucket")
    monkeypatch.setenv(
        "ACCESS_IQ_PSEUDONYM_KEY_SECRET_ARN",
        "arn:aws:secretsmanager:eu-west-2:111:secret:k1",
    )
    with pytest.raises(ValueError):
        pseudonymise_nhs_number("")


def test_pseudonymise_missing_arn_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "test-bucket")
    monkeypatch.delenv("ACCESS_IQ_PSEUDONYM_KEY_SECRET_ARN", raising=False)
    with pytest.raises(ValueError, match="No pseudonymisation key ARN"):
        pseudonymise_nhs_number("1234567881")


def test_pseudonymise_caches_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_IQ_PLATFORM_BUCKET", "test-bucket")
    monkeypatch.setenv(
        "ACCESS_IQ_PSEUDONYM_KEY_SECRET_ARN",
        "arn:aws:secretsmanager:eu-west-2:111:secret:k1",
    )

    sm = _mock_sm("cached-key")
    with patch("access_iq.security.pseudonymise.boto3.client", return_value=sm):
        pseudonymise_nhs_number("1234567881")
        pseudonymise_nhs_number("9876543210")
    assert sm.get_secret_value.call_count == 1
