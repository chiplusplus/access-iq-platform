import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from access_iq.ingestion.backfill import backfill_from_staging


def _write_core_csv(core_dir: Path, filename: str, df: pd.DataFrame) -> None:
    df.to_csv(core_dir / filename, index=False)


def _write_export_csv(exports_dir: Path, subfolder: str, filename: str, df: pd.DataFrame) -> None:
    d = exports_dir / subfolder
    d.mkdir(parents=True, exist_ok=True)
    df.to_csv(d / filename, index=False)


class TestBackfillFromStaging:
    def test_partitions_encounters_by_business_date(self, tmp_path: Path):
        core = tmp_path / "core"
        core.mkdir()
        exports = tmp_path / "exports"
        exports.mkdir()
        _write_core_csv(
            core,
            "encounters.csv",
            pd.DataFrame(
                {
                    "encounter_id": ["E1", "E2", "E3"],
                    "patient_id": ["P1", "P2", "P3"],
                    "encounter_datetime_start": [
                        "2026-01-15 10:00:00",
                        "2026-01-15 14:00:00",
                        "2026-02-20 09:00:00",
                    ],
                }
            ),
        )

        s3 = MagicMock()

        result = backfill_from_staging(
            staging_core_dir=core,
            staging_exports_dir=exports,
            platform_bucket="test-bucket",
            pipeline_start_date=date(2025, 6, 3),
            env="dev",
            s3=s3,
        )

        assert len(result["encounters"]) == 2
        keys = sorted(result["encounters"])
        assert "ingest_date=2026-01-15" in keys[0]
        assert "ingest_date=2026-02-20" in keys[1]

    def test_clamps_old_dates_to_pipeline_start(self, tmp_path: Path):
        core = tmp_path / "core"
        core.mkdir()
        exports = tmp_path / "exports"
        exports.mkdir()
        _write_core_csv(
            core,
            "patients.csv",
            pd.DataFrame(
                {
                    "patient_id": ["P1", "P2", "P3"],
                    "registration_start_date": ["1990-05-01", "2020-03-15", "2026-01-10"],
                }
            ),
        )

        s3 = MagicMock()

        result = backfill_from_staging(
            staging_core_dir=core,
            staging_exports_dir=exports,
            platform_bucket="test-bucket",
            pipeline_start_date=date(2025, 6, 3),
            env="dev",
            s3=s3,
        )

        keys = sorted(result["patient_demographics"])
        assert len(keys) == 2
        assert "ingest_date=2025-06-03" in keys[0]
        assert "ingest_date=2026-01-10" in keys[1]

    def test_backfills_appointment_exports(self, tmp_path: Path):
        core = tmp_path / "core"
        core.mkdir()
        exports = tmp_path / "exports"
        _write_export_csv(
            exports,
            "appointments",
            "20260115_appointments.csv",
            pd.DataFrame({"appointment_id": ["A1"], "patient_id": ["P1"]}),
        )
        _write_export_csv(
            exports,
            "appointments",
            "20260220_appointments.csv",
            pd.DataFrame({"appointment_id": ["A2"], "patient_id": ["P2"]}),
        )

        s3 = MagicMock()

        result = backfill_from_staging(
            staging_core_dir=core,
            staging_exports_dir=exports,
            platform_bucket="test-bucket",
            pipeline_start_date=date(2025, 6, 3),
            env="dev",
            s3=s3,
        )

        assert len(result["appointments"]) == 2
        keys = sorted(result["appointments"])
        assert "source=sftp_appointments" in keys[0]
        assert "ingest_date=2026-01-15" in keys[0]
        assert "ingest_date=2026-02-20" in keys[1]

    def test_backfills_diagnostics_exports(self, tmp_path: Path):
        core = tmp_path / "core"
        core.mkdir()
        exports = tmp_path / "exports"
        _write_export_csv(
            exports,
            "diagnostics",
            "20260301_diagnostic_orders.csv",
            pd.DataFrame({"diagnostic_id": ["D1"], "patient_id": ["P1"]}),
        )

        s3 = MagicMock()

        result = backfill_from_staging(
            staging_core_dir=core,
            staging_exports_dir=exports,
            platform_bucket="test-bucket",
            pipeline_start_date=date(2025, 6, 3),
            env="dev",
            s3=s3,
        )

        assert len(result["diagnostics_orders"]) == 1
        assert "source=trust_s3_diagnostics" in result["diagnostics_orders"][0]
        assert "ingest_date=2026-03-01" in result["diagnostics_orders"][0]

    def test_creates_manifest_per_partition(self, tmp_path: Path):
        core = tmp_path / "core"
        core.mkdir()
        exports = tmp_path / "exports"
        exports.mkdir()
        _write_core_csv(
            core,
            "encounters.csv",
            pd.DataFrame(
                {
                    "encounter_id": ["E1"],
                    "patient_id": ["P1"],
                    "encounter_datetime_start": ["2026-03-01 10:00:00"],
                }
            ),
        )

        s3 = MagicMock()

        backfill_from_staging(
            staging_core_dir=core,
            staging_exports_dir=exports,
            platform_bucket="test-bucket",
            pipeline_start_date=date(2025, 6, 3),
            env="dev",
            s3=s3,
        )

        manifest_calls = [
            c for c in s3.put_object.call_args_list if "_manifests/" in c.kwargs.get("Key", "")
        ]
        assert len(manifest_calls) == 1
        body = json.loads(manifest_calls[0].kwargs["Body"])
        assert body["status"] == "success"
        assert body["inputs"]["backfill"] is True

    def test_missing_csv_skipped(self, tmp_path: Path):
        core = tmp_path / "core"
        core.mkdir()
        exports = tmp_path / "exports"
        exports.mkdir()

        s3 = MagicMock()

        result = backfill_from_staging(
            staging_core_dir=core,
            staging_exports_dir=exports,
            platform_bucket="test-bucket",
            pipeline_start_date=date(2025, 6, 3),
            env="dev",
            s3=s3,
        )

        assert result.get("appointments") == []
        assert result.get("diagnostics_orders") == []
        s3.upload_fileobj.assert_not_called()
