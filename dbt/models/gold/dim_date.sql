{{
    config(materialized='table')
}}
{#
    Gold dim_date
    Grain: one row per calendar date (2020-01-01 to 2030-12-31)
    Source: self-generated via integer series (Redshift does not support generate_series on dates)
    Key decisions: D-02 (SQL generate_series, no seed CSV)
#}
WITH int_series AS (
    SELECT (ROW_NUMBER() OVER ()) - 1 AS n
    FROM stl_scan
    LIMIT 4018  -- 2020-01-01 to 2030-12-31 = 4018 days
),
dates AS (
    SELECT DATEADD(day, n, '2020-01-01'::date) AS calendar_date
    FROM int_series
)
SELECT
    (TO_CHAR(calendar_date, 'YYYYMMDD'))::integer   AS date_sk,
    calendar_date,
    EXTRACT(year FROM calendar_date)::integer        AS year,
    EXTRACT(month FROM calendar_date)::integer       AS month,
    EXTRACT(quarter FROM calendar_date)::integer     AS quarter,
    TO_CHAR(calendar_date, 'YYYY-MM')                AS year_month,
    TO_CHAR(calendar_date, 'Mon YYYY')               AS month_label,
    EXTRACT(dow FROM calendar_date)::integer         AS day_of_week,
    CASE
        WHEN EXTRACT(dow FROM calendar_date) IN (0, 6) THEN TRUE
        ELSE FALSE
    END                                              AS is_weekend
FROM dates
ORDER BY calendar_date
