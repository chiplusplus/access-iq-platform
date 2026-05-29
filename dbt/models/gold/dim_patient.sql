{{
    config(
        materialized='table',
        dist='patient_sk',
        sort=['valid_from'],
        sort_type='compound'
    )
}}
{#
    Gold dim_patient
    Grain: one row per patient (SCD2 scaffold — single snapshot until simulator produces change streams)
    Source: silver.patients
    Key decisions: D-01 (SCD2 scaffold), D-14 (distkey/sortkey demonstrative)
#}
SELECT
    patient_sk,
    age_band,
    sex,
    ethnicity_ons,
    imd_decile,
    imd_label,
    deprivation_level,
    chronic_conditions_count,
    registered_gp_practice_id,
    registration_start_date                             AS valid_from,
    COALESCE(registration_end_date, '9999-12-31'::date) AS valid_to,
    CASE
        WHEN registration_end_date IS NULL THEN TRUE
        ELSE FALSE
    END                                                 AS is_current
FROM {{ ref('patients') }}
