{{
    config(
        materialized='table',
        sort=['specialty_code'],
        sort_type='compound'
    )
}}
{#
    Gold dim_specialty
    Grain: one row per distinct referral_specialty code
    Source: silver.referrals (distinct values)
    specialty_name = specialty_code until NHS specialty mapping seed is available
#}
WITH specialties AS (
    SELECT DISTINCT referral_specialty AS specialty_code
    FROM {{ ref('referrals') }}
    WHERE referral_specialty IS NOT NULL
)
SELECT
    ROW_NUMBER() OVER (ORDER BY specialty_code) AS specialty_sk,
    specialty_code,
    specialty_code                              AS specialty_name
FROM specialties
