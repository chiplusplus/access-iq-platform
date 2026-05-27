{% macro nhs_mod11_check(col) %}
    CASE
        WHEN LENGTH(REGEXP_REPLACE({{ col }}, '[^0-9]', '')) != 10
            THEN 'invalid_format'
        WHEN 11 - MOD(
                CAST(SUBSTRING({{ col }},1,1) AS INT)*10
              + CAST(SUBSTRING({{ col }},2,1) AS INT)*9
              + CAST(SUBSTRING({{ col }},3,1) AS INT)*8
              + CAST(SUBSTRING({{ col }},4,1) AS INT)*7
              + CAST(SUBSTRING({{ col }},5,1) AS INT)*6
              + CAST(SUBSTRING({{ col }},6,1) AS INT)*5
              + CAST(SUBSTRING({{ col }},7,1) AS INT)*4
              + CAST(SUBSTRING({{ col }},8,1) AS INT)*3
              + CAST(SUBSTRING({{ col }},9,1) AS INT)*2, 11) = 10
            THEN 'mod11_invalid'
        WHEN (CASE
                WHEN 11 - MOD(
                    CAST(SUBSTRING({{ col }},1,1) AS INT)*10
                  + CAST(SUBSTRING({{ col }},2,1) AS INT)*9
                  + CAST(SUBSTRING({{ col }},3,1) AS INT)*8
                  + CAST(SUBSTRING({{ col }},4,1) AS INT)*7
                  + CAST(SUBSTRING({{ col }},5,1) AS INT)*6
                  + CAST(SUBSTRING({{ col }},6,1) AS INT)*5
                  + CAST(SUBSTRING({{ col }},7,1) AS INT)*4
                  + CAST(SUBSTRING({{ col }},8,1) AS INT)*3
                  + CAST(SUBSTRING({{ col }},9,1) AS INT)*2, 11) = 11
                THEN 0
                ELSE 11 - MOD(
                    CAST(SUBSTRING({{ col }},1,1) AS INT)*10
                  + CAST(SUBSTRING({{ col }},2,1) AS INT)*9
                  + CAST(SUBSTRING({{ col }},3,1) AS INT)*8
                  + CAST(SUBSTRING({{ col }},4,1) AS INT)*7
                  + CAST(SUBSTRING({{ col }},5,1) AS INT)*6
                  + CAST(SUBSTRING({{ col }},6,1) AS INT)*5
                  + CAST(SUBSTRING({{ col }},7,1) AS INT)*4
                  + CAST(SUBSTRING({{ col }},8,1) AS INT)*3
                  + CAST(SUBSTRING({{ col }},9,1) AS INT)*2, 11)
              END) != CAST(SUBSTRING({{ col }},10,1) AS INT)
            THEN 'mod11_mismatch'
        ELSE NULL
    END
{% endmacro %}
