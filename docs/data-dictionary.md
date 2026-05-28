# Data Dictionary - Bronze Layer

**Generated:** 2026-05-27T13:19:26.239827+00:00
**Source:** S3 Bronze Parquet (latest ingest_date partition)

## patient_demographics

**Source:** ehr_postgres | **Rows:** 100,000 | **PK:** patient_id (unique) | **Date range:** 2026-05-27 11:33:46.129988 to 2026-05-27 11:34:02.304381

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
| updated_at | datetime64[us] | 100.0% | 2 | 2026-05-27 11:33:46.129988 | 2026-05-27 11:34:02.304381 |  |

### Gap Analysis

- High nulls: `registration_end_date` has 89.8% nulls (4863 distinct values)
- Join keys: `patient_id`

## encounters

**Source:** ehr_postgres | **Rows:** 594,676 | **PK:** encounter_id (unique) | **Date range:** 2023-01-01 00:00:00 to 2026-05-27 11:37:22.541623

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| encounter_id | int64 | 100.0% | 594676 | 1 | 594676 |  |
| patient_id | int64 | 100.0% | 88444 | 1 | 100000 |  |
| provider_id | int64 | 100.0% | 125 | 1 | 125 |  |
| encounter_datetime_start | datetime64[us] | 100.0% | 730 | 2023-01-01 00:00:00 | 2024-12-30 00:00:00 |  |
| encounter_datetime_end | datetime64[us] | 100.0% | 730 | 2023-01-01 00:00:00 | 2024-12-30 00:00:00 |  |
| encounter_type | object | 100.0% | 6 |  |  |  |
| source_system | object | 100.0% | 5 |  |  |  |
| clinician_id | int64 | 100.0% | 3250 | 1 | 3250 |  |
| priority | object | 100.0% | 3 |  |  |  |
| was_attended | bool | 100.0% | 2 |  |  |  |
| first_attendance_flag | bool | 100.0% | 2 |  |  |  |
| primary_condition_code | object | 100.0% | 7 |  |  |  |
| wait_time_days | int64 | 100.0% | 86 | 0 | 90 |  |
| created_at | datetime64[us] | 100.0% | 594676 | 2026-05-27 11:32:01.674935 | 2026-05-27 11:32:52.348040 |  |
| updated_at | datetime64[us] | 100.0% | 12 | 2026-05-27 11:34:18.658382 | 2026-05-27 11:37:22.541623 |  |

### Gap Analysis

- Join keys: `patient_id`, `provider_id`, `clinician_id`

## referrals

**Source:** ehr_postgres | **Rows:** 208,137 | **PK:** referral_id (unique) | **Date range:** 2023-01-01 00:00:00 to 2026-05-27 11:38:22.896178

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| referral_id | int64 | 100.0% | 208137 | 1 | 208137 |  |
| patient_id | int64 | 100.0% | 75031 | 1 | 100000 |  |
| source_provider_id | int64 | 100.0% | 125 | 1 | 125 |  |
| target_provider_id | int64 | 100.0% | 40 | 1 | 125 |  |
| referral_datetime | datetime64[us] | 100.0% | 731 | 2023-01-01 00:00:00 | 2024-12-31 00:00:00 |  |
| referral_type | object | 100.0% | 2 |  |  |  |
| referral_specialty | object | 100.0% | 9 |  |  |  |
| status | object | 100.0% | 2 |  |  |  |
| created_at | datetime64[us] | 100.0% | 5 | 2026-05-27 11:37:38.609376 | 2026-05-27 11:38:22.896178 |  |
| updated_at | datetime64[us] | 100.0% | 5 | 2026-05-27 11:37:38.609376 | 2026-05-27 11:38:22.896178 |  |

### Gap Analysis

- Join keys: `patient_id`, `source_provider_id`, `target_provider_id`

## diagnoses

*No data available for profiling.*

## appointments

**Source:** sftp_appointments | **Rows:** 7,363 | **PK:** appointment_id (unique) | **Date range:**  to

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| appointment_id | object | 100.0% | 7363 |  |  |  |
| patient_id | object | 100.0% | 7038 |  |  |  |
| nhs_pseudo_id | object | 100.0% | 7038 |  |  |  |
| registered_gp_practice_id | object | 100.0% | 50 |  |  |  |
| service_location_id | object | 100.0% | 85 |  |  |  |
| clinician_id | object | 100.0% | 2883 |  |  |  |
| appointment_start_datetime | object | 100.0% | 13 |  |  |  |
| appointment_end_datetime | object | 100.0% | 13 |  |  |  |
| appointment_type | object | 100.0% | 2 |  |  |  |
| mode | object | 100.0% | 3 |  |  |  |
| slot_type | object | 100.0% | 2 |  |  |  |
| booking_status | object | 100.0% | 4 |  |  |  |
| booking_created_datetime | object | 100.0% | 89 |  |  |  |
| booking_updated_datetime | object | 100.0% | 94 |  |  |  |
| wait_time_days | object | 100.0% | 81 |  |  |  |
| imd_decile | object | 100.0% | 10 |  |  |  |

### Gap Analysis

- Type mismatch: `appointment_start_datetime` is object, expected timestamp -- Silver must cast
- Type mismatch: `appointment_end_datetime` is object, expected timestamp -- Silver must cast
- Type mismatch: `booking_created_datetime` is object, expected timestamp -- Silver must cast
- Type mismatch: `booking_updated_datetime` is object, expected timestamp -- Silver must cast
- Join keys: `patient_id`, `nhs_pseudo_id`

## urgent_care_logs

**Source:** urgent_care_postgres | **Rows:** 61,029 | **PK:** uc_log_id (unique) | **Date range:** 2023-01-01 00:00:00 to 2026-05-27 11:48:04.317901

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| uc_log_id | int64 | 100.0% | 61029 | 1 | 61029 |  |
| patient_id | int64 | 100.0% | 41911 | 4 | 100000 |  |
| provider_id | int64 | 100.0% | 10 | 106 | 115 |  |
| encounter_id | int64 | 100.0% | 61029 | 27 | 594676 |  |
| arrival_datetime | datetime64[us] | 100.0% | 730 | 2023-01-01 00:00:00 | 2024-12-30 00:00:00 |  |
| triage_datetime | datetime64[us] | 100.0% | 21118 | 2023-01-01 00:00:00 | 2024-12-30 00:30:00 |  |
| seen_by_clinician_datetime | datetime64[us] | 100.0% | 46718 | 2023-01-01 00:10:00 | 2024-12-30 03:00:00 |  |
| departure_datetime | datetime64[us] | 100.0% | 3650 | 2023-01-01 01:00:00 | 2024-12-30 05:00:00 |  |
| triage_category | object | 100.0% | 5 |  |  |  |
| presenting_complaint | object | 100.0% | 8 |  |  |  |
| outcome | object | 100.0% | 4 |  |  |  |
| source_system | object | 100.0% | 1 |  |  |  |
| created_at | datetime64[us] | 100.0% | 2 | 2026-05-27 11:47:48.514863 | 2026-05-27 11:48:04.317901 |  |
| updated_at | datetime64[us] | 100.0% | 2 | 2026-05-27 11:47:48.514863 | 2026-05-27 11:48:04.317901 |  |

### Gap Analysis

- Join keys: `patient_id`, `provider_id`, `encounter_id`

## diagnostics_orders

**Source:** trust_s3_diagnostics | **Rows:** 629 | **PK:** diagnostic_id (unique) | **Date range:**  to

| Column | Type | Non-Null % | Distinct | Min | Max | Notes |
|--------|------|-----------|----------|-----|-----|-------|
| diagnostic_id | object | 100.0% | 629 |  |  |  |
| patient_id | object | 100.0% | 608 |  |  |  |
| referral_id | object | 100.0% | 460 |  |  |  |
| encounter_id | object | 100.0% | 150 |  |  |  |
| provider_id | object | 100.0% | 93 |  |  |  |
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
