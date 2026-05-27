"""Markdown data dictionary generator with gap analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


@dataclass
class ColumnStats:
    """Per-column statistics extracted from a Bronze entity DataFrame."""

    name: str
    dtype: str
    non_null_pct: float
    distinct_count: int
    min_val: str
    max_val: str
    notes: str = ""


@dataclass
class EntityStats:
    """Aggregate statistics for a single Bronze entity."""

    entity_name: str
    source: str
    row_count: int
    pk_col: str
    pk_unique: bool
    pk_null_count: int
    date_range_min: str
    date_range_max: str
    columns: list[ColumnStats] = field(default_factory=list)
    gap_analysis: list[str] = field(default_factory=list)


# Entities known to store datetime values as varchar in Bronze
_VARCHAR_DATETIME_ENTITIES = {"appointments", "diagnostics_orders"}

# Columns that are expected to be timestamps but arrive as varchar
_EXPECTED_TIMESTAMP_COLS = {
    "appointments": {
        "appointment_start_datetime",
        "appointment_end_datetime",
        "booking_created_datetime",
        "booking_updated_datetime",
    },
    "diagnostics_orders": {
        "request_date",
        "performed_date",
        "result_date",
    },
}


def _build_gap_analysis(*, stats: EntityStats, entity_cfg: dict) -> list[str]:
    """Build gap analysis entries for a profiled entity.

    Checks:
    (a) type mismatches -- varchar datetime columns flagged
    (b) null concerns -- columns with >10% nulls
    (c) join key notes -- which join keys this entity exposes
    (d) distribution notes -- PK duplicates, zero rows
    """
    gaps: list[str] = []
    entity = stats.entity_name

    # (a) Type mismatches for datetime-as-varchar
    if entity in _VARCHAR_DATETIME_ENTITIES:
        expected_ts = _EXPECTED_TIMESTAMP_COLS.get(entity, set())
        for col in stats.columns:
            if col.name in expected_ts and col.dtype.lower() not in (
                "datetime64[ns]",
                "datetime64[ns, utc]",
            ):
                gaps.append(
                    f"Type mismatch: `{col.name}` is {col.dtype}, "
                    f"expected timestamp -- Silver must cast"
                )

    # (b) Null concerns
    for col in stats.columns:
        if col.non_null_pct < 90.0:
            gaps.append(
                f"High nulls: `{col.name}` has {100.0 - col.non_null_pct:.1f}% nulls "
                f"({col.distinct_count} distinct values)"
            )

    # (c) Join key notes
    join_keys = entity_cfg.get("join_keys", [])
    if join_keys:
        gaps.append(f"Join keys: {', '.join(f'`{k}`' for k in join_keys)}")

    # (d) Distribution notes
    if not stats.pk_unique:
        gaps.append(f"PK `{stats.pk_col}` has duplicates -- deduplication needed in Silver")
    if stats.pk_null_count > 0:
        gaps.append(f"PK `{stats.pk_col}` has {stats.pk_null_count} null values")
    if stats.row_count == 0:
        gaps.append("Entity has 0 rows -- check ingestion pipeline")

    return gaps


def generate_data_dictionary(
    *,
    entity_stats: dict[str, EntityStats],
    output_path: str,
    entity_order: list[str] | None = None,
) -> None:
    """Write a markdown data dictionary to *output_path*.

    Each entity gets a section with a column table and inline gap analysis
    (per D-06).
    """
    from access_iq.profiling.s3_discovery import BRONZE_ENTITIES

    order = entity_order or list(BRONZE_ENTITIES.keys())
    now = datetime.now(tz=UTC).isoformat()

    lines: list[str] = [
        "# Data Dictionary - Bronze Layer",
        "",
        f"**Generated:** {now}",
        "**Source:** S3 Bronze Parquet (latest ingest_date partition)",
        "",
    ]

    for entity_name in order:
        stats = entity_stats.get(entity_name)
        if stats is None:
            lines.append(f"## {entity_name}")
            lines.append("")
            lines.append("*No data available for profiling.*")
            lines.append("")
            continue

        pk_status = "unique" if stats.pk_unique else "has dupes"
        lines.append(f"## {entity_name}")
        lines.append("")
        lines.append(
            f"**Source:** {stats.source} | "
            f"**Rows:** {stats.row_count:,} | "
            f"**PK:** {stats.pk_col} ({pk_status}) | "
            f"**Date range:** {stats.date_range_min} to {stats.date_range_max}"
        )
        lines.append("")

        # Column table
        lines.append("| Column | Type | Non-Null % | Distinct | Min | Max | Notes |")
        lines.append("|--------|------|-----------|----------|-----|-----|-------|")
        for col in stats.columns:
            lines.append(
                f"| {col.name} | {col.dtype} | {col.non_null_pct:.1f}% | "
                f"{col.distinct_count} | {col.min_val} | {col.max_val} | {col.notes} |"
            )
        lines.append("")

        # Gap analysis (inline per D-06)
        lines.append("### Gap Analysis")
        lines.append("")
        if stats.gap_analysis:
            for gap in stats.gap_analysis:
                lines.append(f"- {gap}")
        else:
            lines.append("- No gaps identified.")
        lines.append("")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    log.info("data_dictionary_written", path=str(output), entities=len(entity_stats))
