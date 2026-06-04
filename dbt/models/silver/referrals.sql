{{
    config(
        materialized='incremental',
        unique_key='referral_id',
        incremental_strategy='merge',
        on_schema_change='sync_all_columns',
        dist='patient_sk',
        sort=['referral_datetime'],
        sort_type='compound'
    )
}}

WITH bronze AS (
    SELECT
        referral_id,
        patient_id,
        source_provider_id,
        target_provider_id,
        referral_datetime::varchar::timestamp           AS referral_datetime,
        referral_type,
        referral_specialty,
        status,
        created_at::varchar::timestamp                  AS created_at,
        updated_at::varchar::timestamp                  AS updated_at,
        ingest_date
    FROM {{ source('bronze_external', 'referrals') }}
    {% if is_incremental() %}
    WHERE ingest_date > (SELECT MAX(_ingest_date) FROM {{ this }})
    {% endif %}
),

deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY referral_id ORDER BY updated_at DESC) AS _rn
    FROM bronze
)

SELECT
    src.referral_id,
    pi.patient_sk,
    src.source_provider_id,
    src.target_provider_id,
    {{ convert_tz('src.referral_datetime') }}         AS referral_datetime,
    src.referral_type,
    src.referral_specialty,
    src.status,
    {{ convert_tz('src.created_at') }}                AS created_at,
    src.ingest_date                                   AS _ingest_date,
    SYSDATE                                           AS _loaded_at
FROM deduped src
LEFT JOIN {{ ref('patient_identifiers') }} pi ON pi.patient_id = src.patient_id
WHERE src._rn = 1
