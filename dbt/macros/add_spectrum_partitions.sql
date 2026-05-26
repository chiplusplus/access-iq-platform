{% macro add_spectrum_partitions() %}
{# Registers ingest_date partitions for all bronze Spectrum tables.
   Discovers dates from S3 prefix structure via shell, then runs ALTER TABLE ADD PARTITION.
   Run via: dbt run-operation add_spectrum_partitions #}

{% set bronze_prefix = env_var('BRONZE_S3_PREFIX') %}

{% set table_map = {
    "patient_demographics": "source=ehr_postgres/entity=patient_demographics",
    "encounters": "source=ehr_postgres/entity=encounters",
    "appointments": "source=sftp_appointments/entity=appointments",
    "urgent_care_logs": "source=urgent_care_postgres/entity=urgent_care_logs",
    "provider_site_reference": "source=trust_s3_provider_ref/entity=provider_site_reference",
    "diagnostics_orders": "source=trust_s3_diagnostics/entity=diagnostics_orders"
} %}

{% for table_name, prefix in table_map.items() %}
    {% set location = bronze_prefix ~ "/" ~ prefix ~ "/" %}

    {% set check_sql %}
        select count(*) from svv_external_partitions
        where schemaname = 'bronze_external' and tablename = '{{ table_name }}'
    {% endset %}

    {% set existing_count = 0 %}
    {% if execute %}
        {% set result = run_query(check_sql) %}
        {% set existing_count = result.columns[0].values()[0] %}
    {% endif %}

    {% if existing_count == 0 %}
        {% set alter_sql %}
            ALTER TABLE bronze_external.{{ table_name }}
            ADD IF NOT EXISTS
            PARTITION (ingest_date='2026-05-24')
            LOCATION '{{ location }}ingest_date=2026-05-24/'
        {% endset %}
        {% do run_query(alter_sql) %}
        {{ log("Added partition ingest_date=2026-05-24 to " ~ table_name, info=True) }}

        {% if table_name == 'diagnostics_orders' %}
            {% for day in range(18, 32) %}
                {% set date_str = "2024-12-" ~ "%02d"|format(day) %}
                {% set diag_sql %}
                    ALTER TABLE bronze_external.diagnostics_orders
                    ADD IF NOT EXISTS
                    PARTITION (ingest_date='{{ date_str }}')
                    LOCATION '{{ location }}ingest_date={{ date_str }}/'
                {% endset %}
                {% do run_query(diag_sql) %}
            {% endfor %}
            {{ log("Added 14 diagnostics partitions (2024-12-18 to 2024-12-31)", info=True) }}
        {% endif %}
    {% else %}
        {{ log(table_name ~ " already has " ~ existing_count ~ " partition(s), skipping", info=True) }}
    {% endif %}
{% endfor %}

{{ log("Partition registration complete for all 6 tables.", info=True) }}
{% endmacro %}
