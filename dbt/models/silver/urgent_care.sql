{{
    config(
        materialized='incremental',
        unique_key='uc_log_id',
        incremental_strategy='merge',
        on_schema_change='sync_all_columns',
        dist='patient_sk',
        sort=['arrival_datetime'],
        sort_type='compound'
    )
}}

{#
    Silver urgent care model
    Source: Urgent care PostgreSQL (bronze_external.urgent_care_logs)
    4 timestamp columns converted to UTC via convert_tz (D-15/D-18)
    Patient identity resolved via patient_identifiers FK join
    urgent_care_logs has bigint patient_id -- no cast needed
#}

WITH bronze AS (
    SELECT
        uc_log_id,
        patient_id,
        provider_id,
        encounter_id,
        arrival_datetime::varchar::timestamp            AS arrival_datetime,
        triage_datetime::varchar::timestamp             AS triage_datetime,
        seen_by_clinician_datetime::varchar::timestamp  AS seen_by_clinician_datetime,
        departure_datetime::varchar::timestamp          AS departure_datetime,
        triage_category,
        presenting_complaint,
        outcome,
        source_system,
        created_at::varchar::timestamp                  AS created_at,
        updated_at::varchar::timestamp                  AS updated_at,
        ingest_date
    FROM {{ source('bronze_external', 'urgent_care_logs') }}
    {% if is_incremental() %}
    WHERE ingest_date > (SELECT MAX(_ingest_date) FROM {{ this }})
    {% endif %}
),

deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY uc_log_id
            ORDER BY updated_at DESC
        ) AS _rn
    FROM bronze
)

SELECT
    src.uc_log_id,
    pi.patient_sk,
    src.provider_id,
    src.encounter_id,
    {{ convert_tz('src.arrival_datetime') }}              AS arrival_datetime,
    {{ convert_tz('src.triage_datetime') }}               AS triage_datetime,
    {{ convert_tz('src.seen_by_clinician_datetime') }}    AS seen_by_clinician_datetime,
    {{ convert_tz('src.departure_datetime') }}            AS departure_datetime,
    src.triage_category,
    src.presenting_complaint,
    src.outcome,
    src.source_system,
    {{ convert_tz('src.created_at') }}                    AS created_at,
    src.ingest_date                                       AS _ingest_date,
    SYSDATE                                               AS _loaded_at
FROM deduped src
LEFT JOIN {{ ref('patient_identifiers') }} pi ON pi.patient_id = src.patient_id
WHERE src._rn = 1
