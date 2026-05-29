{{
    config(
        materialized='table',
        dist='patient_sk',
        sort=['appointment_start_datetime'],
        sort_type='compound'
    )
}}
{#
    Gold fct_utilisation
    Grain: one row per appointment_id
    DNA flag: booking_status = 'DNA'
    imd_decile: re-derived via dim_patient join — intentionally excluded from Silver
                appointments by design (D-04/T-05-12, Pitfall 5)
    Provider capacity not available from simulator — scope to volume + DNA rate
    dim_site joined via service_location_id::varchar = provider_code (LEFT JOIN — preserve all appts)
    Key decisions: D-14 (distkey patient_sk, sortkey appointment_start_datetime), D-17 (appointment_month)
    Source: silver.appointments + gold.dim_patient + gold.dim_site
#}

WITH appts AS (
    SELECT * FROM {{ ref('appointments') }}
),

dim_p AS (
    SELECT patient_sk, imd_decile, age_band, sex, ethnicity_ons
    FROM {{ ref('dim_patient') }}
    WHERE is_current
),

dim_s AS (
    SELECT site_sk, provider_id, provider_code
    FROM {{ ref('dim_site') }}
)

SELECT
    a.appointment_id,
    a.patient_sk,
    ds.site_sk,
    a.appointment_start_datetime,
    a.appointment_end_datetime,
    a.appointment_type,
    a.mode,
    a.slot_type,
    a.booking_status,
    -- Flags
    CASE WHEN a.booking_status = 'DNA'         THEN TRUE ELSE FALSE END AS dna_flag,
    CASE WHEN a.booking_status = 'attended'    THEN TRUE ELSE FALSE END AS attended_flag,
    CASE WHEN a.booking_status LIKE '%cancel%' THEN TRUE ELSE FALSE END AS cancelled_flag,
    -- Pass-through metrics
    a.wait_time_days,
    -- Re-derived demographics from dim_patient (Pitfall 5: imd_decile not in Silver appointments)
    dp.imd_decile,
    dp.age_band,
    dp.sex,
    dp.ethnicity_ons,
    -- Time-series (D-17)
    DATE_TRUNC('month', a.appointment_start_datetime)::date             AS appointment_month
FROM appts a
LEFT JOIN dim_p dp ON dp.patient_sk = a.patient_sk
LEFT JOIN dim_s ds ON ds.provider_code = a.service_location_id::varchar
