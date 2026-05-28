{{
    config(
        materialized='table',
        sort=['provider_code'],
        sort_type='compound'
    )
}}
{#
    Gold dim_site
    Grain: one row per provider site
    Source: silver.providers (active sites only)
#}
SELECT
    ROW_NUMBER() OVER (ORDER BY provider_code) AS site_sk,
    provider_id,
    provider_code,
    site_name,
    provider_type,
    ics_region,
    has_ed,
    has_inpatient_beds,
    size_band
FROM {{ ref('providers') }}
WHERE site_status = 'active'
