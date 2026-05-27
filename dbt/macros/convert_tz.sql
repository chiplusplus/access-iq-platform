{% macro convert_tz(col) %}
    CONVERT_TIMEZONE('Europe/London', 'UTC', {{ col }})
{% endmacro %}
