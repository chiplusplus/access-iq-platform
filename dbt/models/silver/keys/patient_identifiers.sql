{{
    config(
        materialized='incremental',
        unique_key='patient_id',
        incremental_strategy='merge',
        on_schema_change='sync_all_columns'
    )
}}

WITH bronze AS (
    SELECT *
    FROM {{ source('bronze_external', 'patient_demographics') }}
    {% if is_incremental() %}
    WHERE ingest_date > (SELECT MAX(_ingest_date) FROM {{ this }})
    {% endif %}
),

deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY updated_at DESC) AS _rn
    FROM bronze
)

SELECT
    {{ hmac_pseudonymise('nhs_pseudo_id') }}  AS patient_sk,
    patient_id::bigint                         AS patient_id,
    date_of_birth::date                        AS date_of_birth,
    postcode_sector,
    lsoa_code,
    ingest_date                                AS _ingest_date,
    SYSDATE                                    AS _loaded_at
FROM deduped
WHERE _rn = 1
