{{
    config(
        materialized='table',
        dist='even',
        sort=['period', 'stratifier'],
        sort_type='compound'
    )
}}
{#
    Gold fct_inequality
    Grain: metric x period x stratifier x stratum (NHS OHID Fingertips long-form — D-06)
    Stratifiers: imd_decile, age_band, ethnicity_ons, sex (REQ-GOLD-INEQ-01)
    Metrics: wait_time_median, four_hour_breach_rate, dna_rate
    Small-cell suppression D-07: counts < 5 replaced with NULL (NHS Digital standard)
    SII/RII D-08: weighted OLS via calc_sii/calc_rii macros (IMD decile stratifier only)
    dist='even': no patient_sk in this table (aggregated to stratum level)
    Key decisions: D-06, D-07, D-08, D-16 (traces to DEI & Patient Advocacy personas), D-17
#}

WITH dim_p AS (
    SELECT patient_sk, imd_decile, age_band, sex, ethnicity_ons
    FROM {{ ref('dim_patient') }}
    WHERE is_current
),

-- ── Wait time metrics by 4 stratifiers ──────────────────────────────────────

wt_by_imd AS (
    SELECT
        'wait_time_median'      AS metric_name,
        fw.referral_month       AS period,
        'imd_decile'            AS stratifier,
        dp.imd_decile::varchar  AS stratum,
        COUNT(*)                AS population_count,
        MEDIAN(fw.wait_days)    AS metric_value
    FROM {{ ref('fct_wait_times') }} fw
    JOIN dim_p dp ON dp.patient_sk = fw.patient_sk
    WHERE fw.wait_days IS NOT NULL
    GROUP BY 1,2,3,4
),

wt_by_age AS (
    SELECT
        'wait_time_median'  AS metric_name,
        fw.referral_month   AS period,
        'age_band'          AS stratifier,
        dp.age_band         AS stratum,
        COUNT(*)            AS population_count,
        MEDIAN(fw.wait_days) AS metric_value
    FROM {{ ref('fct_wait_times') }} fw
    JOIN dim_p dp ON dp.patient_sk = fw.patient_sk
    WHERE fw.wait_days IS NOT NULL
    GROUP BY 1,2,3,4
),

wt_by_ethnicity AS (
    SELECT
        'wait_time_median'  AS metric_name,
        fw.referral_month   AS period,
        'ethnicity_ons'     AS stratifier,
        dp.ethnicity_ons    AS stratum,
        COUNT(*)            AS population_count,
        MEDIAN(fw.wait_days) AS metric_value
    FROM {{ ref('fct_wait_times') }} fw
    JOIN dim_p dp ON dp.patient_sk = fw.patient_sk
    WHERE fw.wait_days IS NOT NULL
    GROUP BY 1,2,3,4
),

wt_by_sex AS (
    SELECT
        'wait_time_median'  AS metric_name,
        fw.referral_month   AS period,
        'sex'               AS stratifier,
        dp.sex              AS stratum,
        COUNT(*)            AS population_count,
        MEDIAN(fw.wait_days) AS metric_value
    FROM {{ ref('fct_wait_times') }} fw
    JOIN dim_p dp ON dp.patient_sk = fw.patient_sk
    WHERE fw.wait_days IS NOT NULL
    GROUP BY 1,2,3,4
),

-- ── 4-hour breach rate by 4 stratifiers ─────────────────────────────────────

breach_by_imd AS (
    SELECT
        'four_hour_breach_rate' AS metric_name,
        fc.arrival_month        AS period,
        'imd_decile'            AS stratifier,
        dp.imd_decile::varchar  AS stratum,
        COUNT(*)                AS population_count,
        AVG(CASE WHEN fc.four_hour_breach_flag THEN 1.0 ELSE 0.0 END) AS metric_value
    FROM {{ ref('fct_urgent_care') }} fc
    JOIN dim_p dp ON dp.patient_sk = fc.patient_sk
    GROUP BY 1,2,3,4
),

breach_by_age AS (
    SELECT
        'four_hour_breach_rate' AS metric_name,
        fc.arrival_month        AS period,
        'age_band'              AS stratifier,
        dp.age_band             AS stratum,
        COUNT(*)                AS population_count,
        AVG(CASE WHEN fc.four_hour_breach_flag THEN 1.0 ELSE 0.0 END) AS metric_value
    FROM {{ ref('fct_urgent_care') }} fc
    JOIN dim_p dp ON dp.patient_sk = fc.patient_sk
    GROUP BY 1,2,3,4
),

breach_by_ethnicity AS (
    SELECT
        'four_hour_breach_rate' AS metric_name,
        fc.arrival_month        AS period,
        'ethnicity_ons'         AS stratifier,
        dp.ethnicity_ons        AS stratum,
        COUNT(*)                AS population_count,
        AVG(CASE WHEN fc.four_hour_breach_flag THEN 1.0 ELSE 0.0 END) AS metric_value
    FROM {{ ref('fct_urgent_care') }} fc
    JOIN dim_p dp ON dp.patient_sk = fc.patient_sk
    GROUP BY 1,2,3,4
),

breach_by_sex AS (
    SELECT
        'four_hour_breach_rate' AS metric_name,
        fc.arrival_month        AS period,
        'sex'                   AS stratifier,
        dp.sex                  AS stratum,
        COUNT(*)                AS population_count,
        AVG(CASE WHEN fc.four_hour_breach_flag THEN 1.0 ELSE 0.0 END) AS metric_value
    FROM {{ ref('fct_urgent_care') }} fc
    JOIN dim_p dp ON dp.patient_sk = fc.patient_sk
    GROUP BY 1,2,3,4
),

-- ── DNA rate by 4 stratifiers ────────────────────────────────────────────────

dna_by_imd AS (
    SELECT
        'dna_rate'                                                          AS metric_name,
        DATE_TRUNC('month', a.appointment_start_datetime)::date             AS period,
        'imd_decile'                                                        AS stratifier,
        dp.imd_decile::varchar                                              AS stratum,
        COUNT(*)                                                            AS population_count,
        AVG(CASE WHEN a.booking_status = 'DNA' THEN 1.0 ELSE 0.0 END)      AS metric_value
    FROM {{ ref('appointments') }} a
    JOIN dim_p dp ON dp.patient_sk = a.patient_sk
    GROUP BY 1,2,3,4
),

dna_by_age AS (
    SELECT
        'dna_rate'                                                          AS metric_name,
        DATE_TRUNC('month', a.appointment_start_datetime)::date             AS period,
        'age_band'                                                          AS stratifier,
        dp.age_band                                                         AS stratum,
        COUNT(*)                                                            AS population_count,
        AVG(CASE WHEN a.booking_status = 'DNA' THEN 1.0 ELSE 0.0 END)      AS metric_value
    FROM {{ ref('appointments') }} a
    JOIN dim_p dp ON dp.patient_sk = a.patient_sk
    GROUP BY 1,2,3,4
),

dna_by_ethnicity AS (
    SELECT
        'dna_rate'                                                          AS metric_name,
        DATE_TRUNC('month', a.appointment_start_datetime)::date             AS period,
        'ethnicity_ons'                                                     AS stratifier,
        dp.ethnicity_ons                                                    AS stratum,
        COUNT(*)                                                            AS population_count,
        AVG(CASE WHEN a.booking_status = 'DNA' THEN 1.0 ELSE 0.0 END)      AS metric_value
    FROM {{ ref('appointments') }} a
    JOIN dim_p dp ON dp.patient_sk = a.patient_sk
    GROUP BY 1,2,3,4
),

dna_by_sex AS (
    SELECT
        'dna_rate'                                                          AS metric_name,
        DATE_TRUNC('month', a.appointment_start_datetime)::date             AS period,
        'sex'                                                               AS stratifier,
        dp.sex                                                              AS stratum,
        COUNT(*)                                                            AS population_count,
        AVG(CASE WHEN a.booking_status = 'DNA' THEN 1.0 ELSE 0.0 END)      AS metric_value
    FROM {{ ref('appointments') }} a
    JOIN dim_p dp ON dp.patient_sk = a.patient_sk
    GROUP BY 1,2,3,4
),

-- ── UNION ALL 12 branches (3 metrics x 4 stratifiers) ───────────────────────

base AS (
    SELECT * FROM wt_by_imd
    UNION ALL SELECT * FROM wt_by_age
    UNION ALL SELECT * FROM wt_by_ethnicity
    UNION ALL SELECT * FROM wt_by_sex
    UNION ALL SELECT * FROM breach_by_imd
    UNION ALL SELECT * FROM breach_by_age
    UNION ALL SELECT * FROM breach_by_ethnicity
    UNION ALL SELECT * FROM breach_by_sex
    UNION ALL SELECT * FROM dna_by_imd
    UNION ALL SELECT * FROM dna_by_age
    UNION ALL SELECT * FROM dna_by_ethnicity
    UNION ALL SELECT * FROM dna_by_sex
),

-- ── Ridit scores for SII/RII (IMD decile stratifier only) ───────────────────
-- ridit_i = (cumulative_pop_up_to_i - 0.5 * pop_i) / total_pop
-- IMD decile ordered ascending (1 = most deprived)

with_ridit AS (
    SELECT
        b.*,
        CASE
            WHEN b.stratifier = 'imd_decile' THEN
                (SUM(b.population_count) OVER (
                    PARTITION BY b.metric_name, b.period, b.stratifier
                    ORDER BY b.stratum::integer
                    ROWS UNBOUNDED PRECEDING
                ) - 0.5 * b.population_count)
                * 1.0
                / NULLIF(SUM(b.population_count) OVER (
                    PARTITION BY b.metric_name, b.period, b.stratifier
                ), 0)
            ELSE NULL
        END AS ridit_score
    FROM base b
)

-- ── Final SELECT with small-cell suppression (D-07) ─────────────────────────

SELECT
    metric_name,
    period,
    stratifier,
    stratum,
    -- Small-cell suppression: counts < 5 replaced with NULL (NHS Digital standard D-07)
    CASE WHEN population_count < 5 THEN NULL ELSE population_count END AS population_count,
    CASE WHEN population_count < 5 THEN NULL ELSE metric_value    END  AS metric_value,
    ridit_score,
    -- SII/RII only computed for imd_decile stratifier (ordinal rank required for OLS)
    CASE
        WHEN stratifier = 'imd_decile' AND ridit_score IS NOT NULL
        THEN {{ calc_sii('metric_value', 'population_count', 'ridit_score') }}
        ELSE NULL
    END AS sii_value,
    CASE
        WHEN stratifier = 'imd_decile' AND ridit_score IS NOT NULL
        THEN {{ calc_rii('metric_value', 'population_count', 'ridit_score') }}
        ELSE NULL
    END AS rii_value
FROM with_ridit
