{{
    config(
        materialized='incremental',
        unique_key='patient_id',
        incremental_strategy='merge',
        on_schema_change='sync_all_columns'
    )
}}

WITH bronze AS (
    SELECT
        patient_id,
        nhs_pseudo_id,
        age_band,
        sex,
        ethnicity_ons,
        date_of_birth::varchar::date                    AS date_of_birth,
        postcode_sector,
        lsoa_code,
        chronic_conditions_count,
        registered_gp_practice_id,
        registration_start_date::varchar::date          AS registration_start_date,
        registration_end_date::varchar::date            AS registration_end_date,
        is_active,
        updated_at::varchar::timestamp                  AS updated_at,
        ingest_date
    FROM {{ source('bronze_external', 'patient_demographics') }}
    {% if is_incremental() %}
    WHERE ingest_date > (SELECT MAX(_ingest_date) FROM {{ this }})
    {% endif %}
),

nhs_validated AS (
    SELECT *,
        {{ nhs_mod11_check('nhs_pseudo_id') }} AS _nhs_validation_failure
    FROM bronze
),

deduped_validated AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY updated_at DESC) AS _rn
    FROM nhs_validated
)

SELECT
    patient_id::bigint                         AS patient_id,
    nhs_pseudo_id,
    age_band,
    sex,
    ethnicity_ons,
    date_of_birth::date                        AS date_of_birth,
    postcode_sector,
    lsoa_code,
    chronic_conditions_count::integer          AS chronic_conditions_count,
    registered_gp_practice_id,
    registration_start_date::date              AS registration_start_date,
    registration_end_date::date                AS registration_end_date,
    is_active,
    _nhs_validation_failure                    AS rejection_reason,
    SYSDATE                                    AS rejected_at,
    ingest_date                                AS _ingest_date,
    SYSDATE                                    AS _loaded_at
FROM deduped_validated
WHERE _rn = 1
  AND _nhs_validation_failure IS NOT NULL
