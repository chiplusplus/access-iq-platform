import json
from datetime import date
from unittest.mock import MagicMock, patch

from access_iq.ingestion.backfill import backfill_postgres_source


def _mock_cursor(columns: list[str], rows: list[tuple]):
    cursor = MagicMock()
    cursor.description = [(col,) for col in columns]
    cursor.fetchall.return_value = rows
    return cursor


class TestBackfillPostgresSource:
    def test_partitions_encounters_by_business_date(self):
        rows = [
            ("E1", "P1", "2026-01-15 10:00:00"),
            ("E2", "P2", "2026-01-15 14:00:00"),
            ("E3", "P3", "2026-02-20 09:00:00"),
        ]
        cursor = _mock_cursor(["encounter_id", "patient_id", "encounter_datetime_start"], rows)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor

        s3 = MagicMock()

        with patch("psycopg2.connect", return_value=mock_conn):
            result = backfill_postgres_source(
                dsn="postgresql://test",
                source="ehr_postgres",
                tables=["encounters"],
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
        assert s3.put_object.call_count == 2  # 2 manifests

    def test_clamps_old_dates_to_pipeline_start(self):
        rows = [
            ("P1", "1990-05-01"),
            ("P2", "2020-03-15"),
            ("P3", "2026-01-10"),
        ]
        cursor = _mock_cursor(["patient_id", "registration_start_date"], rows)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor

        s3 = MagicMock()

        with patch("psycopg2.connect", return_value=mock_conn):
            result = backfill_postgres_source(
                dsn="postgresql://test",
                source="ehr_postgres",
                tables=["patient_demographics"],
                platform_bucket="test-bucket",
                pipeline_start_date=date(2025, 6, 3),
                env="dev",
                s3=s3,
            )

        keys = sorted(result["patient_demographics"])
        # 1990 and 2020 both clamp to 2025-06-03; 2026-01-10 keeps its date
        assert len(keys) == 2
        assert "ingest_date=2025-06-03" in keys[0]
        assert "ingest_date=2026-01-10" in keys[1]

    def test_creates_manifest_per_partition(self):
        rows = [
            ("E1", "P1", "2026-03-01 10:00:00"),
        ]
        cursor = _mock_cursor(["encounter_id", "patient_id", "encounter_datetime_start"], rows)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor

        s3 = MagicMock()

        with patch("psycopg2.connect", return_value=mock_conn):
            backfill_postgres_source(
                dsn="postgresql://test",
                source="ehr_postgres",
                tables=["encounters"],
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
        assert manifest_key.endswith(".json")

        body = json.loads(manifest_calls[0].kwargs["Body"])
        assert body["status"] == "success"
        assert body["inputs"]["backfill"] is True

    def test_empty_table_skipped(self):
        cursor = _mock_cursor(["encounter_id"], [])

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor

        s3 = MagicMock()

        with patch("psycopg2.connect", return_value=mock_conn):
            result = backfill_postgres_source(
                dsn="postgresql://test",
                source="ehr_postgres",
                tables=["encounters"],
                platform_bucket="test-bucket",
                pipeline_start_date=date(2025, 6, 3),
                env="dev",
                s3=s3,
            )

        assert result == {}
        s3.upload_fileobj.assert_not_called()
