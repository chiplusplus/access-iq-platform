"""Bronze-to-Silver readiness gate (D-09).

Validates that Bronze data is structurally sound enough for conformed Silver
models: PKs exist and are unique, join keys connect across entities, types are
consistent, and date ranges overlap.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import pandas as pd
import structlog

from access_iq.config import Settings
from access_iq.logging_config import configure_logging
from access_iq.profiling.s3_discovery import (
    BRONZE_ENTITIES,
    load_all_bronze_entities,
)

log = structlog.get_logger(__name__)


@dataclass
class CheckResult:
    """Outcome of a single readiness check."""

    name: str
    entity: str
    passed: bool
    detail: str


# ---------------------------------------------------------------------------
# Check 1 -- entity completeness
# ---------------------------------------------------------------------------


def check_entity_completeness(*, entity_dfs: dict[str, pd.DataFrame]) -> list[CheckResult]:
    """Every registered Bronze entity must be present with >0 rows."""
    results: list[CheckResult] = []
    for entity_name in BRONZE_ENTITIES:
        df = entity_dfs.get(entity_name)
        if df is None:
            results.append(
                CheckResult(
                    name="entity_completeness",
                    entity=entity_name,
                    passed=False,
                    detail="entity missing from loaded data",
                )
            )
        elif len(df) == 0:
            results.append(
                CheckResult(
                    name="entity_completeness",
                    entity=entity_name,
                    passed=False,
                    detail="entity has 0 rows",
                )
            )
        else:
            results.append(
                CheckResult(
                    name="entity_completeness",
                    entity=entity_name,
                    passed=True,
                    detail=f"rows={len(df)}",
                )
            )
    return results


# ---------------------------------------------------------------------------
# Check 2 -- PK unique & non-null
# ---------------------------------------------------------------------------


def check_pk_unique_nonnull(*, entity_dfs: dict[str, pd.DataFrame]) -> list[CheckResult]:
    """Primary key must be unique and have zero nulls in every entity."""
    results: list[CheckResult] = []
    for entity_name, cfg in BRONZE_ENTITIES.items():
        df = entity_dfs.get(entity_name)
        if df is None or df.empty:
            continue
        pk = cfg["pk"]
        if pk not in df.columns:
            results.append(
                CheckResult(
                    name="pk_unique_nonnull",
                    entity=entity_name,
                    passed=False,
                    detail=f"PK column '{pk}' not found in columns",
                )
            )
            continue
        nulls = int(df[pk].isna().sum())
        duplicates = int(df[pk].duplicated().sum())
        total = len(df)
        passed = nulls == 0 and duplicates == 0
        results.append(
            CheckResult(
                name="pk_unique_nonnull",
                entity=entity_name,
                passed=passed,
                detail=f"nulls={nulls}, duplicates={duplicates}, rows={total}",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Check 3 -- join key existence
# ---------------------------------------------------------------------------

# Maps each join key to the entities that must contain it.
_JOIN_KEY_REQUIREMENTS: dict[str, list[str]] = {
    "patient_id": [
        "patient_demographics",
        "encounters",
        "referrals",
        "diagnoses",
        "appointments",
        "urgent_care_logs",
        "diagnostics_orders",
    ],
    "provider_id": [
        "encounters",
        "urgent_care_logs",
        "diagnostics_orders",
        "provider_site_reference",
    ],
    "encounter_id": [
        "encounters",
        "diagnoses",
        "urgent_care_logs",
        "diagnostics_orders",
    ],
}


def check_join_key_existence(*, entity_dfs: dict[str, pd.DataFrame]) -> list[CheckResult]:
    """Verify that critical join key columns exist in the expected entities."""
    results: list[CheckResult] = []
    for key_col, entities in _JOIN_KEY_REQUIREMENTS.items():
        for entity_name in entities:
            df = entity_dfs.get(entity_name)
            if df is None or df.empty:
                continue
            present = key_col in df.columns
            results.append(
                CheckResult(
                    name="join_key_existence",
                    entity=entity_name,
                    passed=present,
                    detail=f"column='{key_col}' present={present}",
                )
            )
    return results


# ---------------------------------------------------------------------------
# Check 4 -- null rate analysis
# ---------------------------------------------------------------------------


def check_null_rates(*, entity_dfs: dict[str, pd.DataFrame]) -> list[CheckResult]:
    """Flag columns with excessive nulls; PK/join-key nulls are blocking."""
    results: list[CheckResult] = []
    for entity_name, cfg in BRONZE_ENTITIES.items():
        df = entity_dfs.get(entity_name)
        if df is None or df.empty:
            continue
        pk = cfg["pk"]
        join_keys = set(cfg.get("join_keys", []))
        total = len(df)
        for col in df.columns:
            null_count = int(df[col].isna().sum())
            null_pct = (null_count / total * 100.0) if total > 0 else 0.0
            is_critical = col == pk or col in join_keys

            if is_critical and null_count > 0:
                results.append(
                    CheckResult(
                        name="null_rate",
                        entity=entity_name,
                        passed=False,
                        detail=f"column='{col}' (critical) null_pct={null_pct:.1f}% nulls={null_count}",
                    )
                )
            elif null_pct > 50.0:
                # WARN -- non-blocking
                results.append(
                    CheckResult(
                        name="null_rate",
                        entity=entity_name,
                        passed=True,
                        detail=f"WARN column='{col}' null_pct={null_pct:.1f}% nulls={null_count}",
                    )
                )
    return results


# ---------------------------------------------------------------------------
# Check 5 -- type consistency
# ---------------------------------------------------------------------------


def check_type_consistency(*, entity_dfs: dict[str, pd.DataFrame]) -> list[CheckResult]:
    """Cross-entity join key types should be consistent.

    Known varchar/int mismatches (appointments, diagnostics_orders) are flagged
    as WARN (non-blocking per D-07 -- Silver handles casting).
    """
    results: list[CheckResult] = []
    # Known entities where varchar IDs are expected
    _KNOWN_VARCHAR_ENTITIES = {"appointments", "diagnostics_orders"}
    # String-like dtypes that indicate varchar columns
    _STRING_DTYPES = {"object", "string", "str", "string[python]", "string[pyarrow]"}

    def _is_string_dtype(dtype_str: str) -> bool:
        return dtype_str in _STRING_DTYPES or dtype_str.startswith("string")

    for key_col, entities in _JOIN_KEY_REQUIREMENTS.items():
        type_map: dict[str, str] = {}
        for entity_name in entities:
            df = entity_dfs.get(entity_name)
            if df is None or df.empty or key_col not in df.columns:
                continue
            type_map[entity_name] = str(df[key_col].dtype)

        # Normalise: treat all string-like dtypes as equivalent for consistency
        normalised = {e: ("string" if _is_string_dtype(d) else d) for e, d in type_map.items()}
        if len(set(normalised.values())) <= 1:
            # All consistent (or only one entity loaded)
            continue

        # Types differ -- determine if known or unexpected
        for entity_name, dtype in type_map.items():
            is_known = entity_name in _KNOWN_VARCHAR_ENTITIES and _is_string_dtype(dtype)
            results.append(
                CheckResult(
                    name="type_consistency",
                    entity=entity_name,
                    passed=True if is_known else False,
                    detail=(
                        f"WARN column='{key_col}' dtype={dtype} "
                        f"(known varchar entity) types_found={type_map}"
                        if is_known
                        else f"column='{key_col}' dtype={dtype} types_found={type_map}"
                    ),
                )
            )
    return results


# ---------------------------------------------------------------------------
# Check 6 -- referential integrity
# ---------------------------------------------------------------------------

# (child_entity, child_col, parent_entity, parent_col)
_RI_CHECKS: list[tuple[str, str, str, str]] = [
    ("encounters", "patient_id", "patient_demographics", "patient_id"),
    ("referrals", "patient_id", "patient_demographics", "patient_id"),
    ("diagnoses", "patient_id", "patient_demographics", "patient_id"),
    ("diagnoses", "encounter_id", "encounters", "encounter_id"),
    ("urgent_care_logs", "patient_id", "patient_demographics", "patient_id"),
    ("encounters", "provider_id", "provider_site_reference", "provider_id"),
    ("urgent_care_logs", "provider_id", "provider_site_reference", "provider_id"),
]


def check_referential_integrity(*, entity_dfs: dict[str, pd.DataFrame]) -> list[CheckResult]:
    """FK values in child entities must exist in parent entity PKs."""
    results: list[CheckResult] = []
    for child_entity, child_col, parent_entity, parent_col in _RI_CHECKS:
        child_df = entity_dfs.get(child_entity)
        parent_df = entity_dfs.get(parent_entity)
        if child_df is None or parent_df is None:
            continue
        if child_col not in child_df.columns or parent_col not in parent_df.columns:
            results.append(
                CheckResult(
                    name="referential_integrity",
                    entity=child_entity,
                    passed=False,
                    detail=(
                        f"column='{child_col}' -> {parent_entity}.{parent_col}: column missing"
                    ),
                )
            )
            continue

        # Cast to string for comparison when types differ (varchar vs bigint)
        child_vals = set(child_df[child_col].dropna().astype(str))
        parent_vals = set(parent_df[parent_col].dropna().astype(str))
        orphans = child_vals - parent_vals
        orphan_count = len(orphans)
        total = len(child_vals)
        orphan_pct = (orphan_count / total * 100.0) if total > 0 else 0.0
        passed = orphan_count == 0
        results.append(
            CheckResult(
                name="referential_integrity",
                entity=child_entity,
                passed=passed,
                detail=(
                    f"column='{child_col}' -> {parent_entity}.{parent_col}: "
                    f"orphans={orphan_count}/{total} ({orphan_pct:.1f}%)"
                ),
            )
        )
    return results


# ---------------------------------------------------------------------------
# Check 7 -- date range coverage
# ---------------------------------------------------------------------------


def check_date_range_coverage(*, entity_dfs: dict[str, pd.DataFrame]) -> list[CheckResult]:
    """At least 3 entities must have overlapping date ranges."""
    results: list[CheckResult] = []
    entity_ranges: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}

    for entity_name in BRONZE_ENTITIES:
        df = entity_dfs.get(entity_name)
        if df is None or df.empty:
            continue
        for col in df.columns:
            if df[col].dtype.kind == "M":  # datetime
                valid = df[col].dropna()
                if valid.empty:
                    continue
                col_min = valid.min()
                col_max = valid.max()
                if entity_name not in entity_ranges:
                    entity_ranges[entity_name] = (col_min, col_max)
                else:
                    prev_min, prev_max = entity_ranges[entity_name]
                    entity_ranges[entity_name] = (
                        min(prev_min, col_min),
                        max(prev_max, col_max),
                    )

    # Find overlapping range across all entities
    if len(entity_ranges) < 3:
        results.append(
            CheckResult(
                name="date_range_coverage",
                entity="all",
                passed=len(entity_ranges) >= 3,
                detail=f"entities_with_dates={len(entity_ranges)} (need >=3)",
            )
        )
        return results

    # Compute overlap: max of all mins to min of all maxes
    all_mins = [r[0] for r in entity_ranges.values()]
    all_maxes = [r[1] for r in entity_ranges.values()]
    overlap_start = max(all_mins)
    overlap_end = min(all_maxes)

    # Count entities whose range covers the overlap window
    overlapping_count = 0
    for entity_name, (e_min, e_max) in entity_ranges.items():
        if e_min <= overlap_end and e_max >= overlap_start:
            overlapping_count += 1
            results.append(
                CheckResult(
                    name="date_range_coverage",
                    entity=entity_name,
                    passed=True,
                    detail=f"range={e_min.date()} to {e_max.date()}",
                )
            )
        else:
            results.append(
                CheckResult(
                    name="date_range_coverage",
                    entity=entity_name,
                    passed=False,
                    detail=f"range={e_min.date()} to {e_max.date()} (no overlap)",
                )
            )

    # Overall overlap check
    has_overlap = overlap_start <= overlap_end and overlapping_count >= 3
    results.append(
        CheckResult(
            name="date_range_coverage",
            entity="all",
            passed=has_overlap,
            detail=(
                f"overlapping_entities={overlapping_count}, "
                f"overlap={overlap_start.date()} to {overlap_end.date()}"
                if overlap_start <= overlap_end
                else f"overlapping_entities={overlapping_count}, no_common_overlap"
            ),
        )
    )
    return results


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_readiness_checks(*, settings: Settings) -> list[CheckResult]:
    """Execute all 7 readiness checks against live Bronze data."""
    entity_dfs = load_all_bronze_entities(
        aws_profile=settings.aws_profile,
        aws_region=settings.aws_region,
        platform_bucket=settings.platform_bucket,
    )

    all_results: list[CheckResult] = []
    all_results.extend(check_entity_completeness(entity_dfs=entity_dfs))
    all_results.extend(check_pk_unique_nonnull(entity_dfs=entity_dfs))
    all_results.extend(check_join_key_existence(entity_dfs=entity_dfs))
    all_results.extend(check_null_rates(entity_dfs=entity_dfs))
    all_results.extend(check_type_consistency(entity_dfs=entity_dfs))
    all_results.extend(check_referential_integrity(entity_dfs=entity_dfs))
    all_results.extend(check_date_range_coverage(entity_dfs=entity_dfs))

    # Print summary table
    print(f"\n{'Entity':<30} {'Check':<25} {'Result':<6} {'Detail'}")
    print("-" * 100)
    for r in all_results:
        status = "PASS" if r.passed else "FAIL"
        print(f"{r.entity:<30} {r.name:<25} {status:<6} {r.detail}")

    return all_results


def main() -> None:
    """Entry point for ``python -m access_iq.profiling.readiness_gate``."""
    configure_logging()

    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception:
        log.exception("settings_load_failed")
        raise SystemExit(1) from None

    results = run_readiness_checks(settings=settings)
    n_total = len(results)
    n_pass = sum(1 for r in results if r.passed)
    n_fail = n_total - n_pass

    if n_fail == 0:
        print(f"\n=== READINESS GATE: PASS ({n_pass}/{n_total} checks passed) ===")
        sys.exit(0)
    else:
        print(f"\n=== READINESS GATE: FAIL ({n_pass}/{n_total} checks passed) ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
