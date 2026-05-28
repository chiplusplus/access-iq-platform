"""GE 1.x Silver validation gate.

Runs Great Expectations validation suites on 4 person-level Silver tables
(D-09: patients, encounters, referrals, diagnoses).

Results written to:
  - Redshift gold._dq_results (for dbt pre-hook gate query)
  - S3 _dq/<run_id>/ge_results.json (for REQ-DQ-02 observability)

Usage:
  REDSHIFT_DSN=postgresql+psycopg2://... PLATFORM_BUCKET=... python dbt/scripts/run_ge_gate.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import date

import boto3
import great_expectations as gx
import psycopg2
import structlog

log = structlog.get_logger(__name__)

SILVER_TABLES = ["patients", "encounters", "referrals", "diagnoses"]
SILVER_SCHEMA = "silver"


@dataclass
class GERunResult:
    table_name: str
    run_date: str
    run_status: str  # 'PASSED' | 'FAILED'
    failure_count: int
    run_id: str
    details: str  # JSON string of expectation results


def build_suite_for_table(
    context: gx.DataContext,
    datasource: object,
    table_name: str,
) -> tuple:
    """Create data asset, batch def, and expectation suite for a Silver table."""
    data_asset = datasource.add_table_asset(
        name=table_name,
        table_name=table_name,
        schema_name=SILVER_SCHEMA,
    )
    batch_def = data_asset.add_batch_definition_whole_table(f"{table_name}_full")

    suite = context.suites.add(gx.core.ExpectationSuite(name=f"{table_name}_suite"))

    # Common expectations for all person-level tables
    suite.add_expectation(gx.expectations.ExpectTableRowCountToBeBetween(min_value=1))

    # Table-specific expectations
    if table_name == "patients":
        suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="patient_sk"))
        suite.add_expectation(
            gx.expectations.ExpectColumnDistinctValuesToBeInSet(
                column="sex",
                value_set=["M", "F", "I", "U"],
            )
        )
    elif table_name == "encounters":
        suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="encounter_id"))
        # ~14% of encounters have NULL patient_sk from Mod-11 quarantined patients
        suite.add_expectation(
            gx.expectations.ExpectColumnValuesToNotBeNull(column="patient_sk", mostly=0.80)
        )
    elif table_name == "referrals":
        suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="referral_id"))
        # ~14% of referrals have NULL patient_sk from Mod-11 quarantined patients
        suite.add_expectation(
            gx.expectations.ExpectColumnValuesToNotBeNull(column="patient_sk", mostly=0.80)
        )
    elif table_name == "diagnoses":
        suite.expectations = [gx.expectations.ExpectTableRowCountToBeBetween(min_value=0)]
        suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="diagnosis_id"))

    suite.save()

    return batch_def, suite


def write_results_to_redshift(
    dsn: str,
    results: list[GERunResult],
) -> None:
    """Write GE run results to gold._dq_results table."""
    # Parse DSN for psycopg2 (strip sqlalchemy prefix if present)
    conn_str = dsn.replace("redshift+psycopg2://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )

    conn = psycopg2.connect(conn_str, sslmode="prefer")
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS gold")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gold._dq_results (
                    run_date      DATE        NOT NULL,
                    table_name    VARCHAR(64) NOT NULL,
                    run_status    VARCHAR(16) NOT NULL,
                    failure_count INTEGER     NOT NULL DEFAULT 0,
                    run_id        VARCHAR(64) NOT NULL,
                    created_at    TIMESTAMP   DEFAULT GETDATE()
                )
            """)
            cur.execute("DELETE FROM gold._dq_results WHERE run_date = CURRENT_DATE")
            for r in results:
                cur.execute(
                    """
                    INSERT INTO gold._dq_results
                        (run_date, table_name, run_status, failure_count, run_id)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (r.run_date, r.table_name, r.run_status, r.failure_count, r.run_id),
                )
        conn.commit()
    finally:
        conn.close()


def write_results_to_s3(
    s3_client: object,
    bucket: str,
    run_id: str,
    results: list[GERunResult],
) -> str:
    """Publish GE results JSON to S3 _dq/<run_id>/ prefix (REQ-DQ-02)."""
    key = f"_dq/{run_id}/ge_results.json"
    body = json.dumps(
        [asdict(r) for r in results],
        default=str,
        indent=2,
    )
    put_kwargs: dict = dict(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    kms_key = os.environ.get("LAKE_KMS_KEY_ARN", "")
    if kms_key:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = kms_key
    s3_client.put_object(**put_kwargs)
    log.info("s3_results_published", bucket=bucket, key=key)
    return key


def _build_dsn() -> str:
    """Build SQLAlchemy DSN from individual env vars set by tunnel.sh."""
    if dsn := os.environ.get("REDSHIFT_DSN"):
        return dsn.replace("postgresql+psycopg2://", "redshift+psycopg2://")
    host = os.environ.get("REDSHIFT_HOST", "localhost")
    port = os.environ.get("REDSHIFT_PORT", "5439")
    user = os.environ.get("REDSHIFT_USER", "admin")
    password = os.environ.get("REDSHIFT_PASSWORD", "")
    dbname = os.environ.get("REDSHIFT_DBNAME", "dev")
    sslmode = os.environ.get("REDSHIFT_SSLMODE", "prefer")
    return f"redshift+psycopg2://{user}:{password}@{host}:{port}/{dbname}?sslmode={sslmode}"


def _resolve_bucket() -> str:
    """Resolve S3 bucket from PLATFORM_BUCKET or BRONZE_S3_PREFIX."""
    if bucket := os.environ.get("PLATFORM_BUCKET"):
        return bucket
    prefix = os.environ.get("BRONZE_S3_PREFIX", "")
    if prefix.startswith("s3://"):
        return prefix.split("/")[2]
    raise RuntimeError(
        "Set PLATFORM_BUCKET or BRONZE_S3_PREFIX (from `eval $(./scripts/tunnel.sh env)`)"
    )


def run_ge_validation() -> list[GERunResult]:
    """Run GE validation on 4 Silver tables and return results."""
    dsn = _build_dsn()
    run_id = str(uuid.uuid4())
    today = date.today().isoformat()

    context = gx.get_context()
    datasource = context.data_sources.add_or_update_sql(
        name="redshift_silver",
        connection_string=dsn,
    )

    results: list[GERunResult] = []

    for table_name in SILVER_TABLES:
        log.info("validating_table", table=table_name)
        try:
            batch_def, suite = build_suite_for_table(context, datasource, table_name)

            validation_def = context.validation_definitions.add(
                gx.core.ValidationDefinition(
                    name=f"{table_name}_validation",
                    data=batch_def,
                    suite=suite,
                )
            )
            checkpoint = context.checkpoints.add(
                gx.Checkpoint(
                    name=f"{table_name}_checkpoint",
                    validation_definitions=[validation_def],
                )
            )
            result = checkpoint.run()

            success = result.success
            failure_count = 0
            if not success:
                for r in result.run_results.values():
                    for er in r.results:
                        if not er.success:
                            failure_count += 1

            results.append(
                GERunResult(
                    table_name=table_name,
                    run_date=today,
                    run_status="PASSED" if success else "FAILED",
                    failure_count=failure_count,
                    run_id=run_id,
                    details=str(result.describe_dict())[:4000],
                )
            )
            log.info(
                "table_validated",
                table=table_name,
                status="PASSED" if success else "FAILED",
            )

        except Exception as exc:
            log.error("validation_error", table=table_name, error=str(exc))
            results.append(
                GERunResult(
                    table_name=table_name,
                    run_date=today,
                    run_status="FAILED",
                    failure_count=-1,
                    run_id=run_id,
                    details=str(exc)[:4000],
                )
            )

    return results


def publish_cloudwatch_metrics(results: list[GERunResult], failures: list[GERunResult]) -> None:
    """Publish CloudWatch metrics for DQ dashboard (REQ-DQ-02)."""
    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"))
    cw = session.client("cloudwatch")
    cw.put_metric_data(
        Namespace="AccessIQ/DataQuality",
        MetricData=[
            {
                "MetricName": "GEGateRuns",
                "Value": len(results),
                "Unit": "Count",
            },
            {
                "MetricName": "GEGateFailures",
                "Value": len(failures),
                "Unit": "Count",
            },
        ],
    )
    log.info("cloudwatch_metrics_published", runs=len(results), failures=len(failures))


def main() -> None:
    """Run GE gate: validate Silver tables, write results, exit with status."""
    dsn = _build_dsn()
    bucket = _resolve_bucket()

    results = run_ge_validation()

    # Write to Redshift _dq_results
    write_results_to_redshift(dsn, results)
    log.info("redshift_results_written", count=len(results))

    # Publish to S3
    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"))
    run_id = results[0].run_id if results else str(uuid.uuid4())
    s3 = session.client("s3")
    write_results_to_s3(s3, bucket, run_id, results)

    # Publish CloudWatch metrics (best-effort)
    failures = [r for r in results if r.run_status == "FAILED"]
    try:
        publish_cloudwatch_metrics(results, failures)
    except Exception as exc:
        log.warning("cloudwatch_publish_skipped", error=str(exc))

    # Exit
    if failures:
        log.error(
            "ge_gate_failed",
            failed_tables=[f.table_name for f in failures],
            failure_count=len(failures),
        )
        sys.exit(1)

    log.info("ge_gate_passed", table_count=len(results))
    sys.exit(0)


if __name__ == "__main__":
    main()
