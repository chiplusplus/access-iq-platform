{{
    config(
        materialized='incremental',
        unique_key='diagnosis_id',
        incremental_strategy='merge',
        on_schema_change='sync_all_columns',
        dist='patient_sk',
        sort=['coded_datetime'],
        sort_type='compound'
    )
}}

{#
    Empty-source safe: Bronze diagnoses table currently has zero rows
    (simulator bug, re-ingest pending). First run does a full scan of the
    empty source, returns zero rows, materialises as empty table -- no error.
#}

WITH bronze AS (
    SELECT *
    FROM {{ source('bronze_external', 'diagnoses') }}
    {% if is_incremental() %}
    WHERE ingest_date > (SELECT MAX(_ingest_date) FROM {{ this }})
    {% endif %}
),

deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY diagnosis_id ORDER BY updated_at DESC) AS _rn
    FROM bronze
)

SELECT
    src.diagnosis_id,
    pi.patient_sk,
    src.encounter_id,
    src.diagnosis_code,
    src.diagnosis_desc,
    src.diagnosis_type,
    {{ convert_tz('src.coded_datetime') }}            AS coded_datetime,
    {{ convert_tz('src.clinical_datetime') }}          AS clinical_datetime,
    src.source_system,
    {{ convert_tz('src.created_at') }}                AS created_at,
    src.ingest_date                                   AS _ingest_date,
    SYSDATE                                           AS _loaded_at
FROM deduped src
LEFT JOIN {{ ref('patient_identifiers') }} pi ON pi.patient_id = src.patient_id
WHERE src._rn = 1
