"""Great Expectations validation gate task."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import boto3
import structlog
from prefect import task

log = structlog.get_logger(__name__)

# The GE gate script lives at dbt/scripts/run_ge_gate.py.
# In the container it is at /app/dbt/scripts/run_ge_gate.py.
# Use importlib to load it by path (same pattern as test_ge_gate.py).
_SCRIPT_PATHS = [
    Path("/app/dbt/scripts/run_ge_gate.py"),  # container
    Path(__file__).resolve().parents[2] / "dbt" / "scripts" / "run_ge_gate.py",  # local dev
]


def _load_ge_gate_module():
    """Load run_ge_gate module from known paths."""
    for script_path in _SCRIPT_PATHS:
        if script_path.exists():
            spec = importlib.util.spec_from_file_location("run_ge_gate", script_path)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules["run_ge_gate"] = mod
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError(f"run_ge_gate.py not found at any of: {_SCRIPT_PATHS}")


@task(retries=1, retry_delay_seconds=30, name="ge-gate")
def run_ge_gate() -> None:
    """Run GE validation on Silver tables; raise on failure (not sys.exit).

    Calls run_ge_validation() directly — NOT main() which calls sys.exit(1).
    Writes results to Redshift _dq_results table and S3 _dq/ prefix.
    """
    mod = _load_ge_gate_module()

    results = mod.run_ge_validation()

    if not results:
        raise RuntimeError(
            "GE gate returned empty results — no expectations were evaluated. "
            "Check Silver tables exist and GE suites are configured."
        )

    bucket = os.environ.get("ACCESS_IQ_PLATFORM_BUCKET") or os.environ["PLATFORM_BUCKET"]

    mod.write_results_to_redshift(results)

    s3_client = boto3.client(
        "s3",
        region_name=os.environ.get("AWS_DEFAULT_REGION", "eu-west-2"),
    )
    run_id = results[0].run_id if results else "unknown"
    mod.write_results_to_s3(s3_client, bucket, run_id, results)

    failures = [r for r in results if r.run_status == "FAILED"]
    if failures:
        failed_tables = [f.table_name for f in failures]
        raise RuntimeError(f"GE gate FAILED on tables: {failed_tables}")
    log.info("ge_gate_passed", table_count=len(results))
