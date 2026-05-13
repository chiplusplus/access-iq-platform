from __future__ import annotations

from access_iq_infra.lake_layout import (
    BRONZE_PREFIX,
    DQ_PREFIX,
    GOLD_PREFIX,
    LAKE_PREFIXES,
    MANIFESTS_PREFIX,
    SILVER_PREFIX,
    is_lake_prefix,
)


def test_bronze_prefix_canonical() -> None:
    assert BRONZE_PREFIX == "bronze/"


def test_all_prefixes_trailing_slash() -> None:
    assert all(p.endswith("/") for p in LAKE_PREFIXES)


def test_all_five_prefixes_present() -> None:
    assert set(LAKE_PREFIXES) == {
        BRONZE_PREFIX,
        SILVER_PREFIX,
        GOLD_PREFIX,
        MANIFESTS_PREFIX,
        DQ_PREFIX,
    }
    assert len(LAKE_PREFIXES) == 5


def test_is_lake_prefix_matches_bronze_key() -> None:
    assert is_lake_prefix("bronze/source=ehr/entity=patients/ingest_date=2026-05-12/x.csv")


def test_is_lake_prefix_matches_manifests_key() -> None:
    assert is_lake_prefix("_manifests/source=ehr/ingest_date=2026-05-12/run-abc.json")


def test_is_lake_prefix_rejects_unknown_key() -> None:
    assert not is_lake_prefix("random/key")
    assert not is_lake_prefix("")
