# Data Dictionary - Bronze Layer

**Generated:** 2026-06-03T15:59:21.735436+00:00
**Source:** S3 Bronze Parquet (latest ingest_date partition)

## patient_demographics

**Source:** ehr_postgres | **Rows:** 100,000 | **PK:** patient_id (unique) | **Date range:** 2026-06-03 14:15:01.497765 to 2026-06-03 14:15:27.778169

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| patient_id | int64 | 100.0% | 100000 | 1 | 100000 |  |
| nhs_pseudo_id | object | 100.0% | 100000 |  |  |  |
| date_of_birth | object | 100.0% | 31347 |  |  |  |
| age | int64 | 100.0% | 96 | 0 | 95 |  |
| age_band | object | 100.0% | 6 |  |  |  |
| sex | object | 100.0% | 3 |  |  |  |
| ethnicity_ons | object | 99.4% | 16 |  |  |  |
| imd_decile | int64 | 100.0% | 10 | 1 | 10 |  |
| chronic_conditions_count | int64 | 100.0% | 9 | 0 | 8 |  |
| lsoa_code | object | 100.0% | 82 |  |  |  |
| postcode_sector | object | 100.0% | 82 |  |  |  |
| registered_gp_practice_id | object | 100.0% | 50 |  |  |  |
| registration_start_date | object | 100.0% | 18746 |  |  |  |
| registration_end_date | object | 10.2% | 4863 |  |  |  |
| is_active | bool | 100.0% | 2 |  |  |  |
| updated_at | datetime64[us] | 100.0% | 2 | 2026-06-03 14:15:01.497765 | 2026-06-03 14:15:27.778169 |  |

### Gap Analysis

- High nulls: `registration_end_date` has 89.8% nulls (4863 distinct values)
- Join keys: `patient_id`

## encounters

**Source:** ehr_postgres | **Rows:** 316,212 | **PK:** encounter_id (unique) | **Date range:** 2025-06-03 00:00:00 to 2026-06-14 00:00:00

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| encounter_id | int64 | 100.0% | 316212 | 1 | 317113 |  |
| patient_id | int64 | 100.0% | 83763 | 1 | 100000 |  |
| provider_id | int64 | 100.0% | 125 | 1 | 125 |  |
| encounter_datetime_start | datetime64[us] | 100.0% | 376 | 2025-06-03 00:00:00 | 2026-06-14 00:00:00 |  |
| encounter_datetime_end | datetime64[us] | 100.0% | 376 | 2025-06-03 00:00:00 | 2026-06-14 00:00:00 |  |
| encounter_type | object | 100.0% | 6 |  |  |  |
| source_system | object | 100.0% | 5 |  |  |  |
| clinician_id | int64 | 100.0% | 3250 | 1 | 3250 |  |
| priority | object | 100.0% | 3 |  |  |  |
| was_attended | bool | 100.0% | 2 |  |  |  |
| first_attendance_flag | bool | 100.0% | 2 |  |  |  |
| primary_condition_code | object | 100.0% | 7 |  |  |  |
| wait_time_days | int64 | 100.0% | 86 | 0 | 90 |  |
| created_at | datetime64[us] | 100.0% | 316212 | 2026-06-03 13:59:33.398885 | 2026-06-03 14:00:00.860544 |  |
| updated_at | datetime64[us] | 100.0% | 7 | 2026-06-03 14:15:54.162631 | 2026-06-03 14:18:31.033072 |  |

### Gap Analysis

- Join keys: `patient_id`, `provider_id`, `clinician_id`

## referrals

**Source:** ehr_postgres | **Rows:** 110,694 | **PK:** referral_id (unique) | **Date range:** 2025-05-27 00:00:00 to 2026-06-14 00:00:00

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| referral_id | int64 | 100.0% | 110694 | 1 | 110990 |  |
| patient_id | int64 | 100.0% | 59599 | 1 | 100000 |  |
| source_provider_id | int64 | 100.0% | 125 | 1 | 125 |  |
| target_provider_id | int64 | 100.0% | 40 | 1 | 125 |  |
| referral_datetime | datetime64[us] | 100.0% | 383 | 2025-05-27 00:00:00 | 2026-06-14 00:00:00 |  |
| referral_type | object | 100.0% | 2 |  |  |  |
| referral_specialty | object | 100.0% | 9 |  |  |  |
| status | object | 100.0% | 2 |  |  |  |
| created_at | datetime64[us] | 100.0% | 3 | 2026-06-03 14:18:41.230627 | 2026-06-03 14:19:22.239025 |  |
| updated_at | datetime64[us] | 100.0% | 3 | 2026-06-03 14:18:41.230627 | 2026-06-03 14:19:22.239025 |  |

### Gap Analysis

- Join keys: `patient_id`, `source_provider_id`, `target_provider_id`

## diagnoses

**Source:** ehr_postgres | **Rows:** 316,489 | **PK:** diagnosis_id (unique) | **Date range:** 2025-06-03 00:00:00 to 2026-06-21 00:00:00

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| diagnosis_id | int64 | 100.0% | 316489 | 1 | 317352 |  |
| patient_id | int64 | 100.0% | 77562 | 1 | 100000 |  |
| encounter_id | int64 | 100.0% | 221440 | 1 | 317113 |  |
| diagnosis_code | object | 100.0% | 20 |  |  |  |
| diagnosis_desc | object | 100.0% | 20 |  |  |  |
| diagnosis_type | object | 100.0% | 2 |  |  |  |
| coded_datetime | datetime64[us] | 100.0% | 384 | 2025-06-03 00:00:00 | 2026-06-21 00:00:00 |  |
| clinical_datetime | datetime64[us] | 100.0% | 376 | 2025-06-03 00:00:00 | 2026-06-14 00:00:00 |  |
| source_system | object | 100.0% | 1 |  |  |  |
| created_at | datetime64[us] | 100.0% | 7 | 2026-06-03 14:19:27.644808 | 2026-06-03 14:22:03.450221 |  |
| updated_at | datetime64[us] | 100.0% | 7 | 2026-06-03 14:19:27.644808 | 2026-06-03 14:22:03.450221 |  |

### Gap Analysis

- Join keys: `patient_id`, `encounter_id`

## appointments

**Source:** sftp_appointments | **Rows:** 197,328 | **PK:** appointment_id (unique) | **Date range:**  to

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| appointment_id | object | 100.0% | 197328 |  |  |  |
| patient_id | object | 100.0% | 75183 |  |  |  |
| nhs_pseudo_id | object | 100.0% | 75183 |  |  |  |
| registered_gp_practice_id | object | 100.0% | 50 |  |  |  |
| service_location_id | object | 100.0% | 85 |  |  |  |
| clinician_id | object | 100.0% | 3250 |  |  |  |
| appointment_start_datetime | object | 100.0% | 366 |  |  |  |
| appointment_end_datetime | object | 100.0% | 366 |  |  |  |
| appointment_type | object | 100.0% | 2 |  |  |  |
| mode | object | 100.0% | 3 |  |  |  |
| slot_type | object | 100.0% | 2 |  |  |  |
| booking_status | object | 100.0% | 4 |  |  |  |
| booking_created_datetime | object | 100.0% | 442 |  |  |  |
| booking_updated_datetime | object | 100.0% | 444 |  |  |  |
| wait_time_days | object | 100.0% | 84 |  |  |  |
| imd_decile | object | 100.0% | 10 |  |  |  |

### Gap Analysis

- Type mismatch: `appointment_start_datetime` is object, expected timestamp -- Silver must cast
- Type mismatch: `appointment_end_datetime` is object, expected timestamp -- Silver must cast
- Type mismatch: `booking_created_datetime` is object, expected timestamp -- Silver must cast
- Type mismatch: `booking_updated_datetime` is object, expected timestamp -- Silver must cast
- Join keys: `patient_id`, `nhs_pseudo_id`

## urgent_care_logs

**Source:** urgent_care_postgres | **Rows:** 32,372 | **PK:** uc_log_id (unique) | **Date range:** 2025-06-03 00:00:00 to 2026-06-14 05:00:00

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| uc_log_id | int64 | 100.0% | 32372 | 1 | 32458 |  |
| patient_id | int64 | 100.0% | 26332 | 2 | 99999 |  |
| provider_id | int64 | 100.0% | 10 | 106 | 115 |  |
| encounter_id | int64 | 100.0% | 32372 | 8 | 317106 |  |
| arrival_datetime | datetime64[us] | 100.0% | 376 | 2025-06-03 00:00:00 | 2026-06-14 00:00:00 |  |
| triage_datetime | datetime64[us] | 100.0% | 10901 | 2025-06-03 00:00:00 | 2026-06-14 00:30:00 |  |
| seen_by_clinician_datetime | datetime64[us] | 100.0% | 24659 | 2025-06-03 00:12:00 | 2026-06-14 02:59:00 |  |
| departure_datetime | datetime64[us] | 100.0% | 1880 | 2025-06-03 01:00:00 | 2026-06-14 05:00:00 |  |
| triage_category | object | 100.0% | 5 |  |  |  |
| presenting_complaint | object | 100.0% | 8 |  |  |  |
| outcome | object | 100.0% | 4 |  |  |  |
| source_system | object | 100.0% | 1 |  |  |  |
| created_at | datetime64[us] | 100.0% | 1 | 2026-06-03 14:34:30.950493 | 2026-06-03 14:34:30.950493 |  |
| updated_at | datetime64[us] | 100.0% | 1 | 2026-06-03 14:34:30.950493 | 2026-06-03 14:34:30.950493 |  |

### Gap Analysis

- Join keys: `patient_id`, `provider_id`, `encounter_id`

## diagnostics_orders

**Source:** trust_s3_diagnostics | **Rows:** 964 | **PK:** diagnostic_id (unique) | **Date range:**  to

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| diagnostic_id | object | 100.0% | 964 |  |  |  |
| patient_id | object | 100.0% | 888 |  |  |  |
| referral_id | object | 100.0% | 474 |  |  |  |
| encounter_id | object | 100.0% | 439 |  |  |  |
| provider_id | object | 100.0% | 121 |  |  |  |
| test_type | object | 100.0% | 6 |  |  |  |
| test_panel | object | 100.0% | 19 |  |  |  |
| request_date | object | 100.0% | 1 |  |  |  |
| performed_date | object | 100.0% | 21 |  |  |  |
| result_date | object | 100.0% | 27 |  |  |  |
| result_flag | object | 100.0% | 4 |  |  |  |

### Gap Analysis

- Type mismatch: `request_date` is object, expected timestamp -- Silver must cast
- Type mismatch: `performed_date` is object, expected timestamp -- Silver must cast
- Type mismatch: `result_date` is object, expected timestamp -- Silver must cast
- Join keys: `patient_id`, `referral_id`, `encounter_id`, `provider_id`

## provider_site_reference

**Source:** trust_s3_provider_ref | **Rows:** 125 | **PK:** provider_id (unique) | **Date range:**  to

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| provider_id | object | 100.0% | 125 |  |  |  |
| provider_code | object | 100.0% | 125 |  |  |  |
| site_name | object | 100.0% | 70 |  |  |  |
| provider_type | object | 100.0% | 5 |  |  |  |
| parent_trust_name | object | 100.0% | 1 |  |  |  |
| ics_region | object | 100.0% | 1 |  |  |  |
| address_line_1 | object | 100.0% | 120 |  |  |  |
| city | object | 100.0% | 6 |  |  |  |
| postcode | object | 100.0% | 125 |  |  |  |
| postcode_sector | object | 100.0% | 65 |  |  |  |
| lsoa_code | object | 100.0% | 65 |  |  |  |
| is_main_site | object | 100.0% | 2 |  |  |  |
| site_status | object | 100.0% | 5 |  |  |  |
| has_ed | object | 100.0% | 2 |  |  |  |
| has_inpatient_beds | object | 100.0% | 2 |  |  |  |
| size_band | object | 100.0% | 3 |  |  |  |
| opening_hours | object | 100.0% | 3 |  |  |  |
| service_lines | object | 100.0% | 5 |  |  |  |
| site_manager_name | object | 100.0% | 125 |  |  |  |
| site_manager_email | object | 100.0% | 125 |  |  |  |

### Gap Analysis

- Join keys: `provider_id`, `provider_code`
