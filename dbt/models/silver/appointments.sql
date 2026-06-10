{{
    config(
        materialized='incremental',
        unique_key='appointment_id',
        incremental_strategy='merge',
        on_schema_change='sync_all_columns',
        dist='patient_sk',
        sort=['appointment_start_datetime'],
        sort_type='compound'
    )
}}

{#
    Silver appointments model
    Source: SFTP appointment drops (bronze_external.appointments)
    Heavy type casting: all datetimes are varchar(30) in Bronze
    Patient identity resolved via patient_identifiers FK join (D-07)
    Intentional exclusions: nhs_pseudo_id (D-04/D-07), imd_decile (re-derived at Gold from LSOA)
    Threat mitigations: T-05-12 (nhs_pseudo_id + imd_decile excluded)
#}

WITH bronze AS (
    SELECT *
    FROM {{ source('bronze_external', 'appointments') }}
    {% if is_incremental() %}
    WHERE ingest_date > (SELECT MAX(_ingest_date) FROM {{ this }})
    {% endif %}
),

deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY appointment_id
            ORDER BY booking_updated_datetime DESC
        ) AS _rn
    FROM bronze
)

SELECT
    src.appointment_id,
    pi.patient_sk,
    src.registered_gp_practice_id,
    src.service_location_id,
    src.clinician_id,
    {{ convert_tz('src.appointment_start_datetime::timestamp') }}  AS appointment_start_datetime,
    {{ convert_tz('src.appointment_end_datetime::timestamp') }}    AS appointment_end_datetime,
    src.appointment_type,
    src.mode,
    src.slot_type,
    src.booking_status,
    {{ convert_tz('src.booking_created_datetime::timestamp') }}    AS booking_created_datetime,
    {{ convert_tz('src.booking_updated_datetime::timestamp') }}    AS booking_updated_datetime,
    src.wait_time_days::integer                                    AS wait_time_days,
    src.ingest_date                                                AS _ingest_date,
    SYSDATE                                                        AS _loaded_at
FROM deduped src
LEFT JOIN {{ ref('patient_identifiers') }} pi ON pi.patient_id = src.patient_id::bigint
WHERE src._rn = 1
