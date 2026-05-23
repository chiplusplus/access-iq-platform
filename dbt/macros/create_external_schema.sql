{% macro create_external_schema() %}
{# Creates the Spectrum external schema if it does not exist.
   Run via: dbt run-operation create_external_schema
   Requires REDSHIFT_SPECTRUM_ROLE_ARN and REDSHIFT_GLUE_DB env vars. #}

{% set spectrum_role_arn = env_var('REDSHIFT_SPECTRUM_ROLE_ARN') %}
{% set glue_db = env_var('REDSHIFT_GLUE_DB', 'access-iq-dev-bronze') %}

{% set sql %}
CREATE EXTERNAL SCHEMA IF NOT EXISTS bronze_external
FROM DATA CATALOG
DATABASE '{{ glue_db }}'
IAM_ROLE '{{ spectrum_role_arn }}'
REGION 'eu-west-2';
{% endset %}

{% do run_query(sql) %}
{{ log("External schema bronze_external created/verified", info=True) }}
{% endmacro %}
