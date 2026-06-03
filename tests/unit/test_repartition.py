import io
from datetime import date
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq

from access_iq.ingestion.repartition import (
    extract_business_dates,
    repartition_bronze_key,
)


def _parquet_bytes(data: dict) -> bytes:
    table = pa.Table.from_pydict(data)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


class TestExtractBusinessDates:
    def test_extracts_dates_from_encounters(self):
        data = {
            "encounter_id": ["E1", "E2", "E3"],
            "encounter_datetime_start": [
                "2026-05-01 10:00:00",
                "2026-05-01 14:00:00",
                "2026-05-02 09:00:00",
            ],
        }
        dates = extract_business_dates(
            parquet_bytes=_parquet_bytes(data),
            entity="encounters",
        )
        assert sorted(dates) == [date(2026, 5, 1), date(2026, 5, 2)]

    def test_static_entity_returns_none(self):
        data = {"provider_id": ["P1"]}
        dates = extract_business_dates(
            parquet_bytes=_parquet_bytes(data),
            entity="provider_site_reference",
        )
        assert dates is None


class TestRepartitionBronzeKey:
    def test_splits_parquet_by_date_within_window(self):
        """Dates within the pipeline window get their own partitions."""
        data = {
            "encounter_id": ["E1", "E2", "E3"],
            "encounter_datetime_start": [
                "2026-05-01 10:00:00",
                "2026-05-01 14:00:00",
                "2026-05-02 09:00:00",
            ],
            "patient_id": ["P1", "P2", "P3"],
        }

        s3 = MagicMock()
        s3.get_object.return_value = {"Body": io.BytesIO(_parquet_bytes(data))}

        keys = repartition_bronze_key(
            s3=s3,
            bucket="platform-bucket",
            source_key="bronze/source=ehr_postgres/entity=encounters/ingest_date=2026-06-02/encounters.parquet",
            source="ehr_postgres",
            entity="encounters",
            pipeline_start_date=date(2025, 6, 2),
        )

        assert s3.upload_fileobj.call_count == 2
        assert len(keys) == 2

        uploaded_keys = sorted(keys)
        assert "ingest_date=2026-05-01" in uploaded_keys[0]
        assert "ingest_date=2026-05-02" in uploaded_keys[1]
        s3.delete_object.assert_called_once()

    def test_clamps_old_dates_to_pipeline_start(self):
        """Dates before pipeline_start_date are clamped to pipeline_start."""
        data = {
            "referral_id": ["R1", "R2", "R3"],
            "referral_datetime": [
                "2023-03-15 10:00:00",
                "2024-06-01 14:00:00",
                "2026-01-15 09:00:00",
            ],
        }

        s3 = MagicMock()
        s3.get_object.return_value = {"Body": io.BytesIO(_parquet_bytes(data))}

        pipeline_start = date(2025, 6, 2)
        keys = repartition_bronze_key(
            s3=s3,
            bucket="platform-bucket",
            source_key="bronze/source=ehr_postgres/entity=referrals/ingest_date=2026-06-02/referrals.parquet",
            source="ehr_postgres",
            entity="referrals",
            pipeline_start_date=pipeline_start,
        )

        # 2023 and 2024 dates both clamp to 2025-06-02; 2026-01-15 stays
        assert s3.upload_fileobj.call_count == 2
        uploaded_keys = sorted(keys)
        assert "ingest_date=2025-06-02" in uploaded_keys[0]
        assert "ingest_date=2026-01-15" in uploaded_keys[1]

    def test_all_old_dates_produce_single_partition(self):
        """When ALL data is before pipeline start, everything goes to day-1 partition."""
        data = {
            "patient_id": ["P1", "P2"],
            "registration_start_date": ["2005-03-01", "2018-11-22"],
        }

        s3 = MagicMock()
        s3.get_object.return_value = {"Body": io.BytesIO(_parquet_bytes(data))}

        pipeline_start = date(2025, 6, 2)
        keys = repartition_bronze_key(
            s3=s3,
            bucket="platform-bucket",
            source_key="bronze/source=ehr_postgres/entity=patient_demographics/ingest_date=2026-06-02/patient_demographics.parquet",
            source="ehr_postgres",
            entity="patient_demographics",
            pipeline_start_date=pipeline_start,
        )

        assert s3.upload_fileobj.call_count == 1
        assert len(keys) == 1
        assert "ingest_date=2025-06-02" in keys[0]

    def test_static_entity_returns_source_key(self):
        s3 = MagicMock()
        keys = repartition_bronze_key(
            s3=s3,
            bucket="platform-bucket",
            source_key="bronze/source=trust_s3_provider_ref/entity=provider_site_reference/ingest_date=2026-06-02/provider_site_reference.parquet",
            source="trust_s3_provider_ref",
            entity="provider_site_reference",
            pipeline_start_date=date(2025, 6, 2),
        )
        assert keys == [
            "bronze/source=trust_s3_provider_ref/entity=provider_site_reference/ingest_date=2026-06-02/provider_site_reference.parquet"
        ]
        s3.get_object.assert_not_called()
