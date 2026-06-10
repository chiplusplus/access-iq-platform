{{
    config(
        materialized='table',
        dist='patient_sk',
        sort=['arrival_datetime'],
        sort_type='compound'
    )
}}
{#
    Gold fct_urgent_care
    Grain: one row per uc_log_id (A&E attendance)
    Breach flags: 4h (240 min) and 12h (720 min) from arrival to departure
    admitted_flag: derived from outcome column (LOWER + IN for case tolerance)
    Key decisions: D-14 (distkey/sortkey), D-17 (arrival_month for trend analysis)
    Source: silver.urgent_care
#}

WITH uc AS (
    SELECT * FROM {{ ref('urgent_care') }}
)

SELECT
    uc.uc_log_id,
    uc.patient_sk,
    uc.provider_id,
    dsite.site_sk,
    uc.arrival_datetime,
    uc.triage_datetime,
    uc.seen_by_clinician_datetime,
    uc.departure_datetime,
    -- Computed time intervals
    DATEDIFF('minute', uc.arrival_datetime, uc.triage_datetime)          AS arrival_to_triage_mins,
    DATEDIFF('minute', uc.arrival_datetime, uc.seen_by_clinician_datetime) AS arrival_to_seen_mins,
    DATEDIFF('minute', uc.arrival_datetime, uc.departure_datetime)       AS arrival_to_discharge_mins,
    -- Breach flags
    CASE
        WHEN DATEDIFF('minute', uc.arrival_datetime, uc.departure_datetime) > 240
        THEN TRUE ELSE FALSE
    END                                                                   AS four_hour_breach_flag,
    CASE
        WHEN DATEDIFF('minute', uc.arrival_datetime, uc.departure_datetime) > 720
        THEN TRUE ELSE FALSE
    END                                                                   AS twelve_hour_breach_flag,
    -- Conversion to admission (LOWER handles case variation in simulator outcome values)
    CASE
        WHEN LOWER(uc.outcome) IN ('admitted', 'admission')
        THEN TRUE ELSE FALSE
    END                                                                   AS admitted_flag,
    -- Pass-through categorical
    uc.triage_category,
    uc.presenting_complaint,
    uc.outcome,
    -- Time-series (D-17)
    DATE_TRUNC('month', uc.arrival_datetime)::date                        AS arrival_month
FROM uc
LEFT JOIN {{ ref('dim_site') }} dsite
    ON dsite.provider_id = uc.provider_id
