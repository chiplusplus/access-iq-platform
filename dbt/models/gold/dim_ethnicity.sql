{{
    config(materialized='table')
}}
{#
    Gold dim_ethnicity
    Grain: one row per ONS 16+1 ethnicity code
    Source: seeds.dim_ethnicity_ons (already deployed)
    Wraps seed with surrogate key for clean fact joins
#}
SELECT
    ROW_NUMBER() OVER (ORDER BY ethnicity_code) AS ethnicity_sk,
    ethnicity_code,
    ethnicity_label,
    ethnicity_group
FROM {{ ref('dim_ethnicity_ons') }}
