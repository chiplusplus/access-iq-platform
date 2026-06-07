{{
    config(
        materialized='incremental',
        unique_key='diagnostic_id',
        incremental_strategy='merge',
        on_schema_change='sync_all_columns',
        dist='patient_sk',
        sort=['request_date'],
        sort_type='compound'
    )
}}

{#
    Type conformance: All IDs are varchar(20) and all dates are varchar(10)
    in Bronze (Phase 4.5b finding). Explicit casts fail loudly on malformed
    data rather than silently truncating (T-05-09 mitigation).
    No updated_at column -- dedup uses request_date as tiebreaker.
#}

WITH bronze AS (
    SELECT *
    FROM {{ source('bronze_external', 'diagnostics_orders') }}
    {% if is_incremental() %}
    WHERE ingest_date > (SELECT MAX(_ingest_date) FROM {{ this }})
    {% endif %}
),

deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY diagnostic_id ORDER BY request_date DESC) AS _rn
    FROM bronze
)

SELECT
    NULLIF(REGEXP_REPLACE(src.diagnostic_id, '[^0-9]', ''), '')::bigint AS diagnostic_id,
    pi.patient_sk,
    NULLIF(REGEXP_REPLACE(src.referral_id, '[^0-9]', ''), '')::bigint  AS referral_id,
    NULLIF(REGEXP_REPLACE(src.encounter_id, '[^0-9]', ''), '')::bigint AS encounter_id,
    NULLIF(REGEXP_REPLACE(src.provider_id, '[^0-9]', ''), '')::bigint  AS provider_id,
    src.test_type,
    src.test_panel,
    src.request_date::date                            AS request_date,
    src.performed_date::date                          AS performed_date,
    src.result_date::date                             AS result_date,
    src.result_flag,
    src.ingest_date                                   AS _ingest_date,
    SYSDATE                                           AS _loaded_at
FROM deduped src
LEFT JOIN {{ ref('patient_identifiers') }} pi
    ON pi.patient_id = NULLIF(REGEXP_REPLACE(src.patient_id, '[^0-9]', ''), '')::bigint
WHERE src._rn = 1
