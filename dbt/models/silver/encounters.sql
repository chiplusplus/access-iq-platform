{{
    config(
        materialized='incremental',
        unique_key='encounter_id',
        incremental_strategy='merge',
        on_schema_change='sync_all_columns',
        dist='patient_sk',
        sort=['encounter_datetime_start'],
        sort_type='compound'
    )
}}

WITH bronze AS (
    SELECT *
    FROM {{ source('bronze_external', 'encounters') }}
    {% if is_incremental() %}
    WHERE ingest_date > (SELECT MAX(_ingest_date) FROM {{ this }})
    {% endif %}
),

deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY encounter_id ORDER BY updated_at DESC) AS _rn
    FROM bronze
)

SELECT
    src.encounter_id,
    pi.patient_sk,
    src.provider_id,
    {{ convert_tz('src.encounter_datetime_start') }}  AS encounter_datetime_start,
    {{ convert_tz('src.encounter_datetime_end') }}    AS encounter_datetime_end,
    src.encounter_type,
    src.source_system,
    src.clinician_id,
    src.priority,
    src.was_attended,
    src.first_attendance_flag,
    src.primary_condition_code,
    src.wait_time_days::integer                       AS wait_time_days,
    {{ convert_tz('src.created_at') }}                AS created_at,
    src.ingest_date                                   AS _ingest_date,
    SYSDATE                                           AS _loaded_at
FROM deduped src
LEFT JOIN {{ ref('patient_identifiers') }} pi ON pi.patient_id = src.patient_id
WHERE src._rn = 1
