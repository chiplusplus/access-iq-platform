{{
    config(
        materialized='table',
        dist='patient_sk',
        sort=['referral_datetime'],
        sort_type='compound'
    )
}}
{#
    Gold fct_wait_times
    Grain: one row per referral_id
    RTT breach: >18 weeks = 126 days (NHS 18-week RTT rule)
    DM01 breach: >6 weeks = 42 days (NHS diagnostics waiting time standard)
    Treatment date: first attended outpatient encounter after referral_date for same patient
    WARN: referral-to-encounter join is approximated via patient_sk + time window (no FK in Silver)
    NOTE: diagnoses Silver table is empty (simulator bug) — do NOT join to diagnoses
    Key decisions: D-05 (per-referral grain), D-14 (distkey/sortkey), D-17 (referral_month)
#}

WITH referrals AS (
    SELECT * FROM {{ ref('referrals') }}
),

-- DM01: diagnostic orders linked via referral_id (LEFT JOIN — patient_sk nullable in diagnostics_orders)
diagnostics AS (
    SELECT
        referral_id,
        MIN(request_date)  AS earliest_request_date,
        MIN(result_date)   AS earliest_result_date
    FROM {{ ref('diagnostics_orders') }}
    WHERE request_date IS NOT NULL
    GROUP BY referral_id
),

-- First attended encounter per patient after each referral (approximate — no FK between referrals and encounters)
first_treatment AS (
    SELECT
        r.referral_id,
        MIN(e.encounter_datetime_start)::date AS treatment_date
    FROM referrals r
    LEFT JOIN {{ ref('encounters') }} e
        ON  e.patient_sk = r.patient_sk
        AND e.encounter_datetime_start > r.referral_datetime
        AND e.was_attended = TRUE
    GROUP BY r.referral_id
)

SELECT
    r.referral_id,
    r.patient_sk,
    ds.specialty_sk,
    dsite.site_sk,
    r.referral_datetime,
    r.referral_datetime::date                                           AS referral_date,
    -- RTT: first attended encounter after referral for this patient
    ft.treatment_date,
    DATEDIFF('day', r.referral_datetime::date, ft.treatment_date)       AS wait_days,
    CASE
        WHEN DATEDIFF('day', r.referral_datetime::date, ft.treatment_date) > 126
        THEN TRUE ELSE FALSE
    END                                                                 AS rtt_breach_flag,
    -- DM01: diagnostics wait
    dx.earliest_request_date                                            AS dm01_request_date,
    dx.earliest_result_date                                             AS dm01_result_date,
    DATEDIFF('day', dx.earliest_request_date, dx.earliest_result_date)  AS dm01_wait_days,
    CASE
        WHEN DATEDIFF('day', dx.earliest_request_date, dx.earliest_result_date) > 42
        THEN TRUE ELSE FALSE
    END                                                                 AS dm01_breach_flag,
    -- Time-series (D-17)
    DATE_TRUNC('month', r.referral_datetime)::date                      AS referral_month,
    r.referral_specialty,
    r.status
FROM referrals r
LEFT JOIN first_treatment ft
    ON ft.referral_id = r.referral_id
LEFT JOIN {{ ref('dim_specialty') }} ds
    ON ds.specialty_code = r.referral_specialty
LEFT JOIN {{ ref('dim_site') }} dsite
    ON dsite.provider_id = r.target_provider_id
LEFT JOIN diagnostics dx
    ON dx.referral_id = r.referral_id
