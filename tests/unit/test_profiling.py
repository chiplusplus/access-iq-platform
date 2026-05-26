"""Unit tests for access_iq.profiling module."""

from __future__ import annotations

import io
import json
import tempfile

import pandas as pd

from access_iq.profiling.data_dictionary import (
    ColumnStats,
    EntityStats,
    _build_gap_analysis,
    generate_data_dictionary,
)
from access_iq.profiling.profile_bronze import _extract_entity_stats
from access_iq.profiling.readiness_gate import (
    CheckResult,
    check_date_range_coverage,
    check_entity_completeness,
    check_join_key_existence,
    check_null_rates,
    check_pk_unique_nonnull,
    check_referential_integrity,
    check_type_consistency,
)
from access_iq.profiling.s3_discovery import (
    BRONZE_ENTITIES,
    find_latest_partition,
    resolve_latest_run_id,
)

# ---------------------------------------------------------------------------
# Fake S3 helpers (following test_trust_s3.py pattern)
# ---------------------------------------------------------------------------


class FakePaginator:
    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages

    def paginate(self, **kwargs):  # noqa: ANN003, ANN201
        return self._pages


class FakeS3:
    def __init__(
        self,
        pages: list[dict] | None = None,
        objects: dict[str, bytes] | None = None,
    ) -> None:
        self.pages = pages or []
        self._objects = objects or {}

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == "list_objects_v2"
        return FakePaginator(self.pages)

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        data = self._objects.get(Key, b"{}")
        return {"Body": io.BytesIO(data)}


# ---------------------------------------------------------------------------
# Entity registry tests
# ---------------------------------------------------------------------------

EXPECTED_ENTITIES = {
    "patient_demographics",
    "encounters",
    "referrals",
    "diagnoses",
    "appointments",
    "urgent_care_logs",
    "diagnostics_orders",
    "provider_site_reference",
}


def test_entity_registry_has_8_entities() -> None:
    assert len(BRONZE_ENTITIES) == 8


def test_entity_registry_matches_sources_yml() -> None:
    assert set(BRONZE_ENTITIES.keys()) == EXPECTED_ENTITIES


def test_entity_registry_all_have_required_keys() -> None:
    for name, cfg in BRONZE_ENTITIES.items():
        assert "source_prefix" in cfg, f"{name} missing source_prefix"
        assert "pk" in cfg, f"{name} missing pk"
        assert "pk_type" in cfg, f"{name} missing pk_type"
        assert "join_keys" in cfg, f"{name} missing join_keys"
        assert isinstance(cfg["join_keys"], list), f"{name} join_keys not a list"


# ---------------------------------------------------------------------------
# find_latest_partition tests
# ---------------------------------------------------------------------------


def test_find_latest_partition_returns_latest_date() -> None:
    pages = [
        {
            "CommonPrefixes": [
                {"Prefix": "bronze/source=ehr_postgres/entity=encounters/ingest_date=2024-01-01/"},
                {"Prefix": "bronze/source=ehr_postgres/entity=encounters/ingest_date=2024-01-15/"},
                {"Prefix": "bronze/source=ehr_postgres/entity=encounters/ingest_date=2024-01-10/"},
            ]
        }
    ]
    s3 = FakeS3(pages=pages)
    result = find_latest_partition(
        s3=s3,
        bucket="test-bucket",
        entity_prefix="source=ehr_postgres/entity=encounters",
    )
    assert "ingest_date=2024-01-15" in result
    assert result == "bronze/source=ehr_postgres/entity=encounters/ingest_date=2024-01-15/"


def test_find_latest_partition_empty_bucket() -> None:
    s3 = FakeS3(pages=[{"CommonPrefixes": []}])
    result = find_latest_partition(
        s3=s3,
        bucket="test-bucket",
        entity_prefix="source=ehr_postgres/entity=encounters",
    )
    assert result == ""


def test_find_latest_partition_no_pages() -> None:
    s3 = FakeS3(pages=[{}])
    result = find_latest_partition(
        s3=s3,
        bucket="test-bucket",
        entity_prefix="source=ehr_postgres/entity=encounters",
    )
    assert result == ""


# ---------------------------------------------------------------------------
# resolve_latest_run_id tests
# ---------------------------------------------------------------------------


def test_resolve_latest_run_id_picks_successful() -> None:
    manifest_failed = json.dumps(
        {
            "run_id": "failed-run-001",
            "status": "failed",
            "finished_at": "2024-01-15T10:00:00Z",
        }
    ).encode()
    manifest_success = json.dumps(
        {
            "run_id": "success-run-002",
            "status": "success",
            "finished_at": "2024-01-15T11:00:00Z",
        }
    ).encode()

    pages = [
        {
            "Contents": [
                {
                    "Key": "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=failed-run-001.json"
                },
                {
                    "Key": "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=success-run-002.json"
                },
            ]
        }
    ]
    objects = {
        "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=failed-run-001.json": manifest_failed,
        "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=success-run-002.json": manifest_success,
    }

    s3 = FakeS3(pages=pages, objects=objects)
    result = resolve_latest_run_id(
        s3=s3,
        bucket="test-bucket",
        manifest_prefix="_manifests/source=ehr_postgres/ingest_date=2024-01-15/",
    )
    assert result == "success-run-002"


def test_resolve_latest_run_id_no_successful() -> None:
    manifest_failed = json.dumps(
        {"run_id": "failed-run-001", "status": "failed", "finished_at": "2024-01-15T10:00:00Z"}
    ).encode()

    pages = [
        {
            "Contents": [
                {
                    "Key": "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=failed-run-001.json"
                },
            ]
        }
    ]
    objects = {
        "_manifests/source=ehr_postgres/ingest_date=2024-01-15/run_id=failed-run-001.json": manifest_failed,
    }

    s3 = FakeS3(pages=pages, objects=objects)
    result = resolve_latest_run_id(
        s3=s3,
        bucket="test-bucket",
        manifest_prefix="_manifests/source=ehr_postgres/ingest_date=2024-01-15/",
    )
    assert result == ""


def test_resolve_latest_run_id_picks_latest_timestamp() -> None:
    manifest_old = json.dumps(
        {"run_id": "old-run", "status": "success", "finished_at": "2024-01-15T08:00:00Z"}
    ).encode()
    manifest_new = json.dumps(
        {"run_id": "new-run", "status": "success", "finished_at": "2024-01-15T12:00:00Z"}
    ).encode()

    pages = [
        {
            "Contents": [
                {"Key": "_manifests/src/run_id=old-run.json"},
                {"Key": "_manifests/src/run_id=new-run.json"},
            ]
        }
    ]
    objects = {
        "_manifests/src/run_id=old-run.json": manifest_old,
        "_manifests/src/run_id=new-run.json": manifest_new,
    }

    s3 = FakeS3(pages=pages, objects=objects)
    result = resolve_latest_run_id(s3=s3, bucket="b", manifest_prefix="_manifests/src/")
    assert result == "new-run"


# ---------------------------------------------------------------------------
# data_dictionary tests
# ---------------------------------------------------------------------------


def _make_entity_stats(name: str, **overrides: object) -> EntityStats:
    """Helper to build minimal EntityStats for testing."""
    defaults: dict[str, object] = {
        "entity_name": name,
        "source": "ehr_postgres",
        "row_count": 100,
        "pk_col": "id",
        "pk_unique": True,
        "pk_null_count": 0,
        "date_range_min": "2024-01-01",
        "date_range_max": "2024-06-30",
        "columns": [
            ColumnStats(
                name="id",
                dtype="int64",
                non_null_pct=100.0,
                distinct_count=100,
                min_val="1",
                max_val="100",
            ),
        ],
        "gap_analysis": [],
    }
    defaults.update(overrides)
    return EntityStats(**defaults)  # type: ignore[arg-type]


def test_data_dictionary_has_all_entity_sections(tmp_path: object) -> None:
    """All 8 entities appear as ## sections in the generated dictionary."""
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="r") as f:
        out_path = f.name

    stats = {name: _make_entity_stats(name) for name in EXPECTED_ENTITIES}
    generate_data_dictionary(entity_stats=stats, output_path=out_path)

    from pathlib import Path

    content = Path(out_path).read_text()
    for entity in EXPECTED_ENTITIES:
        assert f"## {entity}" in content, f"Missing section for {entity}"


def test_data_dictionary_gap_analysis_inline(tmp_path: object) -> None:
    """Gap analysis appears inline under the entity section."""
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="r") as f:
        out_path = f.name

    stats = {
        "patient_demographics": _make_entity_stats(
            "patient_demographics",
            gap_analysis=["High nulls: `postcode` has 15.0% nulls (50 distinct values)"],
        ),
    }
    generate_data_dictionary(
        entity_stats=stats,
        output_path=out_path,
        entity_order=["patient_demographics"],
    )

    from pathlib import Path

    content = Path(out_path).read_text()
    assert "### Gap Analysis" in content
    assert "High nulls: `postcode`" in content


def test_extract_entity_stats_captures_nulls() -> None:
    """_extract_entity_stats correctly reports null percentages."""
    df = pd.DataFrame(
        {
            "patient_id": [1, 2, 3, 4, 5],
            "name": ["A", None, "C", None, "E"],
            "age": [30, 40, None, 50, 60],
        }
    )
    entity_cfg = {
        "source_prefix": "source=ehr_postgres/entity=patient_demographics",
        "pk": "patient_id",
        "pk_type": "bigint",
        "join_keys": ["patient_id"],
    }

    stats = _extract_entity_stats(df=df, entity_name="patient_demographics", entity_cfg=entity_cfg)

    assert stats.row_count == 5
    assert stats.pk_unique is True
    assert stats.pk_null_count == 0

    # Find name column stats
    name_col = next(c for c in stats.columns if c.name == "name")
    assert name_col.non_null_pct == 60.0  # 3/5 non-null
    assert name_col.distinct_count == 3

    # Find age column stats
    age_col = next(c for c in stats.columns if c.name == "age")
    assert age_col.non_null_pct == 80.0  # 4/5 non-null


def test_build_gap_analysis_flags_high_nulls() -> None:
    """Columns with >10% nulls get flagged in gap analysis."""
    stats = _make_entity_stats(
        "test_entity",
        columns=[
            ColumnStats(
                name="ok_col",
                dtype="int64",
                non_null_pct=95.0,
                distinct_count=50,
                min_val="",
                max_val="",
            ),
            ColumnStats(
                name="bad_col",
                dtype="object",
                non_null_pct=80.0,
                distinct_count=10,
                min_val="",
                max_val="",
            ),
        ],
    )
    entity_cfg = {"pk": "id", "pk_type": "bigint", "join_keys": ["id"]}
    gaps = _build_gap_analysis(stats=stats, entity_cfg=entity_cfg)

    # bad_col should be flagged (80% non-null = 20% nulls)
    assert any("bad_col" in g for g in gaps)
    # ok_col should NOT be flagged (95% non-null = 5% nulls)
    assert not any("ok_col" in g and "nulls" in g.lower() for g in gaps)


# ---------------------------------------------------------------------------
# Readiness gate tests
# ---------------------------------------------------------------------------


def _make_minimal_entity_dfs() -> dict[str, pd.DataFrame]:
    """Build a minimal dict of all 8 entity DataFrames for gate tests."""
    return {
        "patient_demographics": pd.DataFrame(
            {
                "patient_id": [1, 2, 3],
                "nhs_pseudo_id": ["A", "B", "C"],
                "date_of_birth": pd.to_datetime(["2000-01-01"] * 3),
                "registration_date": pd.to_datetime(["2024-02-01", "2024-03-01", "2024-04-01"]),
            }
        ),
        "encounters": pd.DataFrame(
            {
                "encounter_id": [10, 20],
                "patient_id": [1, 2],
                "provider_id": [100, 200],
                "encounter_datetime": pd.to_datetime(["2024-03-01", "2024-03-15"]),
            }
        ),
        "referrals": pd.DataFrame(
            {
                "referral_id": [30, 40],
                "patient_id": [1, 3],
                "source_provider_id": [100, 200],
                "target_provider_id": [200, 100],
            }
        ),
        "diagnoses": pd.DataFrame(
            {
                "diagnosis_id": [50, 60],
                "patient_id": [1, 2],
                "encounter_id": [10, 20],
            }
        ),
        "appointments": pd.DataFrame(
            {
                "appointment_id": ["APT1", "APT2"],
                "patient_id": ["1", "2"],  # varchar
                "nhs_pseudo_id": ["A", "B"],
                "appointment_start_datetime": ["2024-03-01T10:00", "2024-03-02T11:00"],
            }
        ),
        "urgent_care_logs": pd.DataFrame(
            {
                "uc_log_id": [70, 80],
                "patient_id": [1, 2],
                "provider_id": [100, 200],
                "encounter_id": [10, 20],
                "arrival_datetime": pd.to_datetime(["2024-03-01", "2024-03-10"]),
            }
        ),
        "diagnostics_orders": pd.DataFrame(
            {
                "diagnostic_id": ["D1", "D2"],
                "patient_id": ["1", "2"],  # varchar
                "referral_id": ["30", "40"],
                "encounter_id": ["10", "20"],
                "provider_id": ["100", "200"],
            }
        ),
        "provider_site_reference": pd.DataFrame(
            {
                "provider_id": [100, 200],
                "provider_code": ["P100", "P200"],
                "provider_name": ["Site A", "Site B"],
            }
        ),
    }


# -- check_pk_unique_nonnull ------------------------------------------------


def test_check_pk_unique_nonnull_passes() -> None:
    dfs = _make_minimal_entity_dfs()
    results = check_pk_unique_nonnull(entity_dfs=dfs)
    assert all(r.passed for r in results), [r for r in results if not r.passed]


def test_check_pk_unique_nonnull_fails_on_duplicates() -> None:
    dfs = _make_minimal_entity_dfs()
    dfs["encounters"] = pd.DataFrame(
        {"encounter_id": [10, 10], "patient_id": [1, 2], "provider_id": [100, 200]}
    )
    results = check_pk_unique_nonnull(entity_dfs=dfs)
    enc_result = next(r for r in results if r.entity == "encounters")
    assert enc_result.passed is False
    assert "duplicates=" in enc_result.detail


def test_check_pk_unique_nonnull_fails_on_nulls() -> None:
    dfs = _make_minimal_entity_dfs()
    dfs["encounters"] = pd.DataFrame(
        {
            "encounter_id": pd.array([10, None], dtype=pd.Int64Dtype()),
            "patient_id": [1, 2],
            "provider_id": [100, 200],
        }
    )
    results = check_pk_unique_nonnull(entity_dfs=dfs)
    enc_result = next(r for r in results if r.entity == "encounters")
    assert enc_result.passed is False
    assert "nulls=" in enc_result.detail


# -- check_entity_completeness ---------------------------------------------


def test_check_entity_completeness_passes() -> None:
    dfs = _make_minimal_entity_dfs()
    results = check_entity_completeness(entity_dfs=dfs)
    assert len(results) == 8
    assert all(r.passed for r in results)


def test_check_entity_completeness_fails_empty() -> None:
    dfs = _make_minimal_entity_dfs()
    dfs["encounters"] = pd.DataFrame()
    results = check_entity_completeness(entity_dfs=dfs)
    enc_result = next(r for r in results if r.entity == "encounters")
    assert enc_result.passed is False


def test_check_entity_completeness_fails_missing() -> None:
    dfs = _make_minimal_entity_dfs()
    del dfs["encounters"]
    results = check_entity_completeness(entity_dfs=dfs)
    enc_result = next(r for r in results if r.entity == "encounters")
    assert enc_result.passed is False
    assert "missing" in enc_result.detail


# -- check_join_key_existence -----------------------------------------------


def test_check_join_key_existence_passes() -> None:
    dfs = _make_minimal_entity_dfs()
    results = check_join_key_existence(entity_dfs=dfs)
    assert all(r.passed for r in results), [r for r in results if not r.passed]


# -- check_referential_integrity --------------------------------------------


def test_check_referential_integrity_passes() -> None:
    dfs = _make_minimal_entity_dfs()
    results = check_referential_integrity(entity_dfs=dfs)
    assert all(r.passed for r in results), [r for r in results if not r.passed]


def test_check_referential_integrity_fails_orphans() -> None:
    dfs = _make_minimal_entity_dfs()
    dfs["encounters"] = pd.DataFrame(
        {
            "encounter_id": [10, 20],
            "patient_id": [1, 999],  # 999 not in patients
            "provider_id": [100, 200],
        }
    )
    results = check_referential_integrity(entity_dfs=dfs)
    patient_ri = [r for r in results if r.entity == "encounters" and "patient_id" in r.detail]
    assert any(not r.passed for r in patient_ri)
    fail = next(r for r in patient_ri if not r.passed)
    assert "orphans=" in fail.detail


# -- check_type_consistency -------------------------------------------------


def test_check_type_consistency_flags_varchar_vs_int() -> None:
    dfs = _make_minimal_entity_dfs()
    # appointments has object patient_id, patient_demographics has int64
    results = check_type_consistency(entity_dfs=dfs)
    # Should flag appointments as WARN (known varchar entity)
    apt_results = [r for r in results if r.entity == "appointments"]
    if apt_results:
        assert any("WARN" in r.detail for r in apt_results)


# -- check_null_rates -------------------------------------------------------


def test_check_null_rates_flags_critical_nulls() -> None:
    dfs = _make_minimal_entity_dfs()
    dfs["encounters"] = pd.DataFrame(
        {
            "encounter_id": pd.array([10, None], dtype=pd.Int64Dtype()),
            "patient_id": [1, 2],
            "provider_id": [100, 200],
        }
    )
    results = check_null_rates(entity_dfs=dfs)
    enc_results = [r for r in results if r.entity == "encounters"]
    assert any(not r.passed for r in enc_results)


# -- check_date_range_coverage ----------------------------------------------


def test_check_date_range_coverage_overlapping() -> None:
    dfs = _make_minimal_entity_dfs()
    # encounters, urgent_care_logs, and patient_demographics all have datetime cols
    results = check_date_range_coverage(entity_dfs=dfs)
    overall = next(r for r in results if r.entity == "all")
    # At least encounters + urgent_care_logs + patient_demographics have dates
    assert overall.passed is True


def test_check_date_range_coverage_no_dates() -> None:
    # Entities with no datetime columns
    dfs = {
        "patient_demographics": pd.DataFrame({"patient_id": [1]}),
        "encounters": pd.DataFrame({"encounter_id": [10]}),
    }
    results = check_date_range_coverage(entity_dfs=dfs)
    overall = next(r for r in results if r.entity == "all")
    assert overall.passed is False


# -- main exit codes --------------------------------------------------------


def test_gate_exit_code_zero_on_all_pass(monkeypatch: object) -> None:
    from unittest.mock import MagicMock, patch

    mock_settings = MagicMock()
    all_pass = [CheckResult(name="test", entity="e", passed=True, detail="ok")]

    with (
        patch("access_iq.profiling.readiness_gate.Settings", return_value=mock_settings),
        patch("access_iq.profiling.readiness_gate.configure_logging"),
        patch(
            "access_iq.profiling.readiness_gate.run_readiness_checks",
            return_value=all_pass,
        ),
    ):
        from access_iq.profiling.readiness_gate import main

        try:
            main()
        except SystemExit as e:
            assert e.code == 0


def test_gate_exit_code_one_on_failure(monkeypatch: object) -> None:
    from unittest.mock import MagicMock, patch

    mock_settings = MagicMock()
    results = [
        CheckResult(name="test", entity="e", passed=True, detail="ok"),
        CheckResult(name="test2", entity="e2", passed=False, detail="fail"),
    ]

    with (
        patch("access_iq.profiling.readiness_gate.Settings", return_value=mock_settings),
        patch("access_iq.profiling.readiness_gate.configure_logging"),
        patch(
            "access_iq.profiling.readiness_gate.run_readiness_checks",
            return_value=results,
        ),
    ):
        from access_iq.profiling.readiness_gate import main

        try:
            main()
            assert False, "Expected SystemExit"  # noqa: B011
        except SystemExit as e:
            assert e.code == 1


def test_build_gap_analysis_flags_varchar_datetime() -> None:
    """Appointments varchar datetime columns get flagged."""
    stats = _make_entity_stats(
        "appointments",
        columns=[
            ColumnStats(
                name="appointment_start_datetime",
                dtype="object",
                non_null_pct=100.0,
                distinct_count=50,
                min_val="",
                max_val="",
            ),
        ],
    )
    entity_cfg = {"pk": "appointment_id", "pk_type": "varchar", "join_keys": []}
    gaps = _build_gap_analysis(stats=stats, entity_cfg=entity_cfg)

    assert any("Type mismatch" in g and "appointment_start_datetime" in g for g in gaps)
