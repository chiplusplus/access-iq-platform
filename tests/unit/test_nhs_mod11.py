"""NHS Mod-11 checksum validation — Python reference implementation + tests.

The SQL equivalent of ``validate_nhs_mod11`` will be embedded in
``dbt/models/silver/patients.sql`` as a CASE expression.  This Python
version validates the algorithm's correctness against known vectors
before the SQL is written (Plan 03).

Algorithm source: https://www.datadictionary.nhs.uk/attributes/nhs_number.html
"""

from __future__ import annotations

import re

import pytest

# ---------------------------------------------------------------------------
# Reference implementation (mirrors the SQL CASE in patients.sql)
# ---------------------------------------------------------------------------


def validate_nhs_mod11(nhs: str) -> str | None:
    """Return a failure reason string, or ``None`` if valid.

    Failure reasons:
    - ``"invalid_format"`` — not exactly 10 digits
    - ``"mod11_invalid"`` — remainder is 10 (inherently invalid NHS number)
    - ``"mod11_mismatch"`` — computed check digit does not match the 10th digit
    """
    cleaned = re.sub(r"[^0-9]", "", nhs)
    if len(cleaned) != 10:
        return "invalid_format"

    weighted_sum = sum(int(cleaned[i]) * (10 - i) for i in range(9))
    remainder = 11 - (weighted_sum % 11)

    if remainder == 10:
        return "mod11_invalid"

    check_digit = 0 if remainder == 11 else remainder

    if check_digit != int(cleaned[9]):
        return "mod11_mismatch"

    return None


# ---------------------------------------------------------------------------
# Parametrized tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nhs", "expected"),
    [
        # Valid NHS numbers
        ("9434765919", None),
        ("1234567881", None),
        # Invalid: wrong check digit (expected=9, supplied=0)
        ("9434765910", "mod11_mismatch"),
        # Invalid format: non-digit character
        ("123456789A", "invalid_format"),
        # Invalid format: 9 digits
        ("123456789", "invalid_format"),
        # Invalid format: 11 digits
        ("12345678901", "invalid_format"),
        # Invalid format: empty string
        ("", "invalid_format"),
        # Invalid format: spaces and dashes (stripped, then too short)
        ("123 456 78", "invalid_format"),
    ],
    ids=[
        "valid-9434765919",
        "valid-1234567881",
        "invalid-wrong-check-digit",
        "invalid-non-digit",
        "invalid-9-digits",
        "invalid-11-digits",
        "invalid-empty",
        "invalid-with-spaces",
    ],
)
def test_mod11_parametrized(nhs: str, expected: str | None) -> None:
    assert validate_nhs_mod11(nhs) == expected


def test_mod11_remainder_10_is_invalid() -> None:
    """When remainder = 10, the NHS number is inherently invalid.

    Constructed: first 9 digits of ``100000001`` produce weighted_sum=12,
    remainder = 11 - (12 % 11) = 11 - 1 = 10.  Any 10th digit is invalid.
    """
    # 100000001 + any check digit — remainder is 10
    nhs = "1000000010"  # append 0 as check digit
    # Verify weighted sum gives remainder 10
    ws = sum(int(nhs[i]) * (10 - i) for i in range(9))
    assert 11 - (ws % 11) == 10
    assert validate_nhs_mod11(nhs) == "mod11_invalid"


def test_mod11_remainder_11_maps_to_check_digit_0() -> None:
    """When remainder = 11, the expected check digit is 0.

    Constructed: first 9 digits of ``100000006`` produce weighted_sum=33,
    remainder = 11 - (33 % 11) = 11 - 0 = 11, so check digit = 0.
    NHS number ``1000000060`` is valid.
    """
    nhs = "1000000060"
    # Verify weighted sum gives remainder 11
    ws = sum(int(nhs[i]) * (10 - i) for i in range(9))
    assert 11 - (ws % 11) == 11
    assert validate_nhs_mod11(nhs) is None
