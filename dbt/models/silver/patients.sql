{{
    config(
        materialized='incremental',
        unique_key='patient_sk',
        incremental_strategy='merge',
        on_schema_change='sync_all_columns',
        dist='patient_sk',
        sort=['registration_start_date'],
        sort_type='compound'
    )
}}

WITH bronze AS (
    SELECT *
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

valid_only AS (
    SELECT *
    FROM nhs_validated
    WHERE _nhs_validation_failure IS NULL
),

deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY updated_at DESC) AS _rn
    FROM valid_only
),

with_imd AS (
    SELECT
        deduped.*,
        lsoa_imd.imd_decile  AS _lsoa_imd_decile,
        imd.imd_label,
        imd.deprivation_level
    FROM deduped
    LEFT JOIN {{ ref('seed_lsoa_imd_lookup') }} lsoa_imd
        ON lsoa_imd.lsoa_code = deduped.lsoa_code
    LEFT JOIN {{ ref('seed_imd') }} imd
        ON imd.imd_decile = lsoa_imd.imd_decile
)

SELECT
    {{ hmac_pseudonymise('nhs_pseudo_id') }}  AS patient_sk,
    age_band,
    CASE
        WHEN sex IN ('M', 'F', 'I', 'U') THEN sex
        ELSE 'U'
    END                                       AS sex,
    ethnicity_ons,
    _lsoa_imd_decile                          AS imd_decile,
    imd_label,
    deprivation_level,
    chronic_conditions_count::integer         AS chronic_conditions_count,
    registered_gp_practice_id,
    registration_start_date::date             AS registration_start_date,
    registration_end_date::date               AS registration_end_date,
    is_active,
    ingest_date                               AS _ingest_date,
    SYSDATE                                   AS _loaded_at
FROM with_imd
WHERE _rn = 1
