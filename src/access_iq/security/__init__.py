"""Pseudonymisation + security primitives (D9 HMAC-SHA-256 for NHS numbers)."""

from access_iq.security.pseudonymise import pseudonymise_nhs_number

__all__ = ["pseudonymise_nhs_number"]
