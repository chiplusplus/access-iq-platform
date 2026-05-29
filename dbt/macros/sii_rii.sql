{%- macro calc_sii(metric_col, population_col, ridit_col) -%}
{#
    SII (Slope Index of Inequality) via weighted OLS.
    Source: PHE/OHID Technical Guide — fingertips.phe.org.uk/static-reports/
            public-health-technical-guidance/Inequality/SII.html

    Expects caller to provide:
      - {{ metric_col }}: the health metric (e.g. median wait days)
      - {{ population_col }}: population count for this stratum
      - {{ ridit_col }}: pre-computed ridit score = (cumsum_pop - 0.5 * pop) / total_pop

    Returns: scalar SII value (slope of weighted regression line)
    Positive SII = metric increases with deprivation rank (worse for deprived)

    Formula (weighted OLS):
      SII = [n * SUM(w * ridit * y) - SUM(w * ridit) * SUM(w * y)]
            / [n * SUM(w * ridit^2) - SUM(w * ridit)^2]
    where w = population_col / total_pop (population share)

    IMPORTANT: D-08 locks full weighted OLS, not decile-gap shortcut.

    Redshift note: SUM(...) OVER () used here is a simple full-frame aggregate window.
    This is NOT a nested window function (prohibited by Redshift). If Redshift rejects
    the window aggregate inside GROUP BY context, fallback: pre-compute total_pop as a
    scalar CTE and replace SUM({{ population_col }}) OVER () with that scalar.
#}
(
    (COUNT(*) * SUM(
        ({{ population_col }} * 1.0 / NULLIF(SUM({{ population_col }}) OVER (), 0))
        * {{ ridit_col }}
        * {{ metric_col }}
    ) - SUM(
        ({{ population_col }} * 1.0 / NULLIF(SUM({{ population_col }}) OVER (), 0))
        * {{ ridit_col }}
    ) * SUM(
        ({{ population_col }} * 1.0 / NULLIF(SUM({{ population_col }}) OVER (), 0))
        * {{ metric_col }}
    ))
    /
    NULLIF(
        COUNT(*) * SUM(
            ({{ population_col }} * 1.0 / NULLIF(SUM({{ population_col }}) OVER (), 0))
            * {{ ridit_col }} * {{ ridit_col }}
        ) - POWER(SUM(
            ({{ population_col }} * 1.0 / NULLIF(SUM({{ population_col }}) OVER (), 0))
            * {{ ridit_col }}
        ), 2),
        0
    )
)
{%- endmacro -%}


{%- macro calc_rii(metric_col, population_col, ridit_col) -%}
{#
    RII (Relative Index of Inequality) = SII / mean(metric)
    Dimensionless ratio: 0 = no inequality, positive = pro-rich inequality.
    Source: PHE/OHID Technical Guide (same reference as calc_sii above)
#}
(
    {{ calc_sii(metric_col, population_col, ridit_col) }}
    / NULLIF(
        SUM({{ population_col }} * {{ metric_col }} * 1.0)
        / NULLIF(SUM({{ population_col }}), 0),
        0
    )
)
{%- endmacro -%}
