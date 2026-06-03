import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from access_iq.ingestion.backfill import backfill_from_staging


class TestBackfillFromStaging:
    def test_partitions_encounters_by_business_date(self, tmp_path: Path):
        core = tmp_path / "core"
        core.mkdir()
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
        ).to_csv(core / "encounters.csv", index=False)

        s3 = MagicMock()

        result = backfill_from_staging(
            staging_core_dir=core,
            platform_bucket="test-bucket",
            pipeline_start_date=date(2025, 6, 3),
            env="dev",
            s3=s3,
        )

        assert len(result["encounters"]) == 2
        keys = sorted(result["encounters"])
        assert "ingest_date=2026-01-15" in keys[0]
        assert "ingest_date=2026-02-20" in keys[1]

        assert s3.upload_fileobj.call_count == 2
        assert s3.put_object.call_count == 2

    def test_clamps_old_dates_to_pipeline_start(self, tmp_path: Path):
        core = tmp_path / "core"
        core.mkdir()
        pd.DataFrame(
            {
                "patient_id": ["P1", "P2", "P3"],
                "registration_start_date": ["1990-05-01", "2020-03-15", "2026-01-10"],
            }
        ).to_csv(core / "patients.csv", index=False)

        s3 = MagicMock()

        result = backfill_from_staging(
            staging_core_dir=core,
            platform_bucket="test-bucket",
            pipeline_start_date=date(2025, 6, 3),
            env="dev",
            s3=s3,
        )

        keys = sorted(result["patient_demographics"])
        assert len(keys) == 2
        assert "ingest_date=2025-06-03" in keys[0]
        assert "ingest_date=2026-01-10" in keys[1]

    def test_creates_manifest_per_partition(self, tmp_path: Path):
        core = tmp_path / "core"
        core.mkdir()
        pd.DataFrame(
            {
                "encounter_id": ["E1"],
                "patient_id": ["P1"],
                "encounter_datetime_start": ["2026-03-01 10:00:00"],
            }
        ).to_csv(core / "encounters.csv", index=False)

        s3 = MagicMock()

        backfill_from_staging(
            staging_core_dir=core,
            platform_bucket="test-bucket",
            pipeline_start_date=date(2025, 6, 3),
            env="dev",
            s3=s3,
        )

        manifest_calls = [
            c for c in s3.put_object.call_args_list if "_manifests/" in c.kwargs.get("Key", "")
        ]
        assert len(manifest_calls) == 1
        manifest_key = manifest_calls[0].kwargs["Key"]
        assert "ingest_date=2026-03-01" in manifest_key

        body = json.loads(manifest_calls[0].kwargs["Body"])
        assert body["status"] == "success"
        assert body["inputs"]["backfill"] is True

    def test_missing_csv_skipped(self, tmp_path: Path):
        core = tmp_path / "core"
        core.mkdir()

        s3 = MagicMock()

        result = backfill_from_staging(
            staging_core_dir=core,
            platform_bucket="test-bucket",
            pipeline_start_date=date(2025, 6, 3),
            env="dev",
            s3=s3,
        )

        assert result == {}
        s3.upload_fileobj.assert_not_called()
