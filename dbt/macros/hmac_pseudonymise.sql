{% macro hmac_pseudonymise(col) %}
    f_hmac_nhs_number({{ col }}::varchar)
{% endmacro %}
