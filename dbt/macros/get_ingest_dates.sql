{% macro get_ingest_dates(source_prefix) %}
{# Discovers ingest_date partition values by listing S3 prefixes via Redshift SVV_EXTERNAL_PARTITIONS
   or by querying the Glue catalog. Falls back to a manual list if the table doesn't exist yet.

   For initial table creation, we provide an empty list so CREATE TABLE succeeds
   without attempting to add partitions. After creation, re-run stage_external_sources
   to pick up partitions via ALTER TABLE ADD PARTITION.

   Usage in sources.yml:
     vals:
       macro: get_ingest_dates
       args:
         source_prefix: "source=ehr_postgres/entity=patient_demographics"
#}

{# Check if the external table already exists by querying information_schema #}
{% set check_sql %}
    select 1 from svv_external_tables
    where schemaname = 'bronze_external'
    and tablename = '{{ source_prefix.split("/entity=")[1] }}'
    limit 1
{% endset %}

{% set table_exists = false %}
{% if execute %}
    {% set result = run_query(check_sql) %}
    {% if result|length > 0 %}
        {% set table_exists = true %}
    {% endif %}
{% endif %}

{% if table_exists %}
    {# Table exists — discover partitions from Glue catalog via Spectrum metadata #}
    {% set discover_sql %}
        select distinct "values" from svv_external_partitions
        where schemaname = 'bronze_external'
        and tablename = '{{ source_prefix.split("/entity=")[1] }}'
        order by 1
    {% endset %}

    {% if execute %}
        {% set results = run_query(discover_sql) %}
        {% set dates = [] %}
        {% for row in results %}
            {% do dates.append(row[0] | replace('[\"', '') | replace('\"]', '')) %}
        {% endfor %}
        {{ return(dates) }}
    {% else %}
        {{ return([]) }}
    {% endif %}
{% else %}
    {# Table doesn't exist yet — return empty list so CREATE TABLE proceeds without refresh #}
    {{ return([]) }}
{% endif %}

{% endmacro %}
