"""Canonical medallion S3 prefix layout for the access-iq lake (REQ-NET-03).

Single source of truth. Ingestion writes Bronze, dbt sources Bronze via
Spectrum (Phase 4), Silver/Gold are dbt-managed (Phase 5/6), _manifests is
written by ingestion, _dq is written by Great Expectations (Phase 6).
"""

from __future__ import annotations

from typing import Final

BRONZE_PREFIX: Final[str] = "bronze/"
SILVER_PREFIX: Final[str] = "silver/"
GOLD_PREFIX: Final[str] = "gold/"
MANIFESTS_PREFIX: Final[str] = "_manifests/"
DQ_PREFIX: Final[str] = "_dq/"

# Order matters for human docs (Bronze -> Silver -> Gold -> ops).
LAKE_PREFIXES: Final[tuple[str, ...]] = (
    BRONZE_PREFIX,
    SILVER_PREFIX,
    GOLD_PREFIX,
    MANIFESTS_PREFIX,
    DQ_PREFIX,
)


def is_lake_prefix(key: str) -> bool:
    """True if `key` starts with one of the canonical lake prefixes."""
    return any(key.startswith(p) for p in LAKE_PREFIXES)
