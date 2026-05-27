"""Bronze profiling orchestrator: iterate entities, profile, generate dictionary."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import structlog

from access_iq.config import Settings
from access_iq.logging_config import configure_logging
from access_iq.profiling.data_dictionary import (
    ColumnStats,
    EntityStats,
    _build_gap_analysis,
    generate_data_dictionary,
)
from access_iq.profiling.s3_discovery import (
    BRONZE_ENTITIES,
    find_latest_partition,
    read_bronze_entity,
    resolve_latest_run_id,
)

try:
    from data_profiling import ProfileReport  # type: ignore[import-untyped]
except ImportError:
    ProfileReport = None  # type: ignore[assignment,misc]

log = structlog.get_logger(__name__)

DEFAULT_OUTPUT_DIR = "docs/profiling"
DEFAULT_DICT_PATH = "docs/data-dictionary.md"


def profile_entity(*, df: pd.DataFrame, entity_name: str, output_dir: str) -> Any | None:
    """Generate an HTML profiling report for a single entity.

    Returns the ProfileReport object, or None if fg-data-profiling is not
    installed.
    """
    if ProfileReport is None:
        log.warning("data_profiling_not_installed", entity=entity_name)
        return None

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    profile = ProfileReport(
        df,
        title=f"Bronze Profile: {entity_name}",
        minimal=True,
        explorative=True,
    )
    out_path = f"{output_dir}/{entity_name}.html"
    profile.to_file(out_path)
    log.info("profile_written", entity=entity_name, path=out_path)
    return profile


def _extract_entity_stats(*, df: pd.DataFrame, entity_name: str, entity_cfg: dict) -> EntityStats:
    """Extract statistics from a DataFrame for data dictionary generation."""
    pk_col = entity_cfg["pk"]
    row_count = len(df)

    # PK analysis
    pk_unique = False
    pk_null_count = 0
    if pk_col in df.columns:
        pk_null_count = int(df[pk_col].isna().sum())
        pk_unique = bool(df[pk_col].nunique(dropna=True) == (row_count - pk_null_count))

    # Date range from timestamp/date columns
    date_range_min = ""
    date_range_max = ""
    for col_name in df.columns:
        if df[col_name].dtype.kind in ("M",):  # datetime
            valid = df[col_name].dropna()
            if not valid.empty:
                col_min = str(valid.min())
                col_max = str(valid.max())
                if not date_range_min or col_min < date_range_min:
                    date_range_min = col_min
                if not date_range_max or col_max > date_range_max:
                    date_range_max = col_max

    # Column stats
    columns: list[ColumnStats] = []
    for col_name in df.columns:
        series = df[col_name]
        total = len(series)
        non_null = int(series.notna().sum())
        non_null_pct = (non_null / total * 100.0) if total > 0 else 0.0
        distinct = int(series.nunique(dropna=True))

        # Min/max for numeric and date columns
        min_val = ""
        max_val = ""
        if series.dtype.kind in ("i", "f", "u", "M"):  # numeric or datetime
            valid = series.dropna()
            if not valid.empty:
                min_val = str(valid.min())
                max_val = str(valid.max())

        columns.append(
            ColumnStats(
                name=col_name,
                dtype=str(series.dtype),
                non_null_pct=non_null_pct,
                distinct_count=distinct,
                min_val=min_val,
                max_val=max_val,
            )
        )

    # Source from entity prefix
    source = entity_cfg.get("source_prefix", "").split("/")[0].replace("source=", "")

    stats = EntityStats(
        entity_name=entity_name,
        source=source,
        row_count=row_count,
        pk_col=pk_col,
        pk_unique=pk_unique,
        pk_null_count=pk_null_count,
        date_range_min=date_range_min,
        date_range_max=date_range_max,
        columns=columns,
    )
    stats.gap_analysis = _build_gap_analysis(stats=stats, entity_cfg=entity_cfg)
    return stats


def _run(settings: Settings) -> None:
    """Run profiling across all Bronze entities."""
    import boto3

    session = boto3.Session(
        profile_name=settings.aws_profile,
        region_name=settings.aws_region,
    )
    s3 = session.client("s3")
    bucket = settings.platform_bucket

    output_dir = os.environ.get("PROFILING_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
    dict_path = os.environ.get("PROFILING_DICT_PATH", DEFAULT_DICT_PATH)

    all_stats: dict[str, EntityStats] = {}

    for entity_name, entity_cfg in BRONZE_ENTITIES.items():
        bound = log.bind(entity=entity_name)

        # Discover latest partition
        partition = find_latest_partition(
            s3=s3,
            bucket=bucket,
            entity_prefix=entity_cfg["source_prefix"],
        )
        if not partition:
            bound.warning("no_partition", entity=entity_name)
            continue

        # Extract source_prefix parts for manifest lookup
        source_part = entity_cfg["source_prefix"].split("/")[0]  # e.g. source=ehr_postgres
        # Get ingest_date from partition
        date_part = partition.rstrip("/").split("/")[-1]  # e.g. ingest_date=2024-01-15
        manifest_prefix = f"_manifests/{source_part}/{date_part}/"

        run_id = resolve_latest_run_id(s3=s3, bucket=bucket, manifest_prefix=manifest_prefix)

        # Build read prefix
        if run_id:
            read_prefix = f"{partition}run_id={run_id}/"
        else:
            read_prefix = partition
            bound.info("no_successful_run_id", msg="reading all files under partition")

        # Read entity data
        df = read_bronze_entity(
            s3_session=session,
            bucket=bucket,
            prefix=read_prefix,
            region=settings.aws_region,
        )
        if df.empty:
            bound.warning("empty_dataframe", entity=entity_name)
            continue

        # Profile
        profile_entity(df=df, entity_name=entity_name, output_dir=output_dir)

        # Extract stats
        stats = _extract_entity_stats(df=df, entity_name=entity_name, entity_cfg=entity_cfg)
        all_stats[entity_name] = stats
        bound.info("entity_profiled", rows=stats.row_count, columns=len(stats.columns))

    # Generate data dictionary
    generate_data_dictionary(entity_stats=all_stats, output_path=dict_path)
    log.info("profiling_complete", entities_profiled=len(all_stats))


def main() -> None:
    """Entry point for ``python -m access_iq.profiling.profile_bronze``."""
    configure_logging()

    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception:
        log.exception("settings_load_failed")
        raise SystemExit(1) from None

    try:
        _run(settings)
    except Exception:
        log.exception("profiling_crash")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
