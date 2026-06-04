{{
    config(
        materialized='incremental',
        unique_key='provider_code',
        incremental_strategy='merge',
        on_schema_change='sync_all_columns',
        sort=['provider_code'],
        sort_type='compound'
    )
}}

{#
    Silver providers reference model
    Source: Trust S3 provider reference export (bronze_external.provider_site_reference)
    No patient linkage -- no patient_sk, no dist='patient_sk'
    Dual-key: provider_id (bigint) + provider_code (varchar) for cross-direction joins
    Caldicott exclusion: site_manager_name and site_manager_email removed (T-05-11)
    Dedup on provider_code by ingest_date DESC (no updated_at column)
#}

WITH bronze AS (
    SELECT
        provider_id,
        provider_code,
        site_name,
        provider_type,
        parent_trust_name,
        ics_region,
        address_line_1,
        city,
        postcode,
        postcode_sector,
        lsoa_code,
        is_main_site,
        site_status,
        has_ed,
        has_inpatient_beds,
        size_band,
        opening_hours,
        service_lines,
        ingest_date::varchar::date                      AS ingest_date
    FROM {{ source('bronze_external', 'provider_site_reference') }}
    {% if is_incremental() %}
    WHERE ingest_date > (SELECT MAX(_ingest_date) FROM {{ this }})
    {% endif %}
),

deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY provider_code
            ORDER BY ingest_date DESC
        ) AS _rn
    FROM bronze
)

SELECT
    src.provider_id::bigint                            AS provider_id,
    src.provider_code,
    src.site_name,
    src.provider_type,
    src.parent_trust_name,
    src.ics_region,
    src.address_line_1,
    src.city,
    src.postcode,
    src.postcode_sector,
    src.lsoa_code,
    src.is_main_site,
    src.site_status,
    src.has_ed,
    src.has_inpatient_beds,
    src.size_band,
    src.opening_hours,
    src.service_lines,
    src.ingest_date                                    AS _ingest_date,
    SYSDATE                                            AS _loaded_at
FROM deduped src
WHERE src._rn = 1
