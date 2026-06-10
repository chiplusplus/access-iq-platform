{% macro nhs_mod11_check(col) %}
    {%- set cleaned = "REGEXP_REPLACE(" ~ col ~ ", '[^0-9]', '')" -%}
    CASE
        WHEN LENGTH({{ cleaned }}) != 10
            THEN 'invalid_format'
        WHEN 11 - MOD(
                CAST(SUBSTRING({{ cleaned }},1,1) AS INT)*10
              + CAST(SUBSTRING({{ cleaned }},2,1) AS INT)*9
              + CAST(SUBSTRING({{ cleaned }},3,1) AS INT)*8
              + CAST(SUBSTRING({{ cleaned }},4,1) AS INT)*7
              + CAST(SUBSTRING({{ cleaned }},5,1) AS INT)*6
              + CAST(SUBSTRING({{ cleaned }},6,1) AS INT)*5
              + CAST(SUBSTRING({{ cleaned }},7,1) AS INT)*4
              + CAST(SUBSTRING({{ cleaned }},8,1) AS INT)*3
              + CAST(SUBSTRING({{ cleaned }},9,1) AS INT)*2, 11) = 10
            THEN 'mod11_invalid'
        WHEN (CASE
                WHEN 11 - MOD(
                    CAST(SUBSTRING({{ cleaned }},1,1) AS INT)*10
                  + CAST(SUBSTRING({{ cleaned }},2,1) AS INT)*9
                  + CAST(SUBSTRING({{ cleaned }},3,1) AS INT)*8
                  + CAST(SUBSTRING({{ cleaned }},4,1) AS INT)*7
                  + CAST(SUBSTRING({{ cleaned }},5,1) AS INT)*6
                  + CAST(SUBSTRING({{ cleaned }},6,1) AS INT)*5
                  + CAST(SUBSTRING({{ cleaned }},7,1) AS INT)*4
                  + CAST(SUBSTRING({{ cleaned }},8,1) AS INT)*3
                  + CAST(SUBSTRING({{ cleaned }},9,1) AS INT)*2, 11) = 11
                THEN 0
                ELSE 11 - MOD(
                    CAST(SUBSTRING({{ cleaned }},1,1) AS INT)*10
                  + CAST(SUBSTRING({{ cleaned }},2,1) AS INT)*9
                  + CAST(SUBSTRING({{ cleaned }},3,1) AS INT)*8
                  + CAST(SUBSTRING({{ cleaned }},4,1) AS INT)*7
                  + CAST(SUBSTRING({{ cleaned }},5,1) AS INT)*6
                  + CAST(SUBSTRING({{ cleaned }},6,1) AS INT)*5
                  + CAST(SUBSTRING({{ cleaned }},7,1) AS INT)*4
                  + CAST(SUBSTRING({{ cleaned }},8,1) AS INT)*3
                  + CAST(SUBSTRING({{ cleaned }},9,1) AS INT)*2, 11)
              END) != CAST(SUBSTRING({{ cleaned }},10,1) AS INT)
            THEN 'mod11_mismatch'
        ELSE NULL
    END
{% endmacro %}
