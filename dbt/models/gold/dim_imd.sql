{{
    config(materialized='table')
}}
{#
    Gold dim_imd
    Grain: one row per IMD decile (1-10)
    Source: seeds.dim_imd (already deployed)
    Wraps seed with surrogate key for clean fact joins
#}
SELECT
    ROW_NUMBER() OVER (ORDER BY imd_decile) AS imd_sk,
    imd_decile,
    imd_label,
    deprivation_level
FROM {{ ref('dim_imd') }}
