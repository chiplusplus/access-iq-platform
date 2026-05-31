{% macro add_spectrum_partitions() %}
{# Registers ingest_date partitions for all bronze Spectrum tables.
   Uses today's date (from run_started_at) so partitions match the current ingestion.
   ADD IF NOT EXISTS makes this idempotent - safe to rerun.
   Run via: dbt run-operation add_spectrum_partitions #}

{% set bronze_prefix = env_var('BRONZE_S3_PREFIX') %}
{% set today = run_started_at.strftime('%Y-%m-%d') %}

{% set table_map = {
    "patient_demographics": "source=ehr_postgres/entity=patient_demographics",
    "encounters": "source=ehr_postgres/entity=encounters",
    "referrals": "source=ehr_postgres/entity=referrals",
    "diagnoses": "source=ehr_postgres/entity=diagnoses",
    "appointments": "source=sftp_appointments/entity=appointments",
    "urgent_care_logs": "source=urgent_care_postgres/entity=urgent_care_logs",
    "provider_site_reference": "source=trust_s3_provider_ref/entity=provider_site_reference",
    "diagnostics_orders": "source=trust_s3_diagnostics/entity=diagnostics_orders"
} %}

{% for table_name, prefix in table_map.items() %}
    {% set location = bronze_prefix ~ "/" ~ prefix ~ "/" %}

    {% set alter_sql %}
        ALTER TABLE bronze_external.{{ table_name }}
        ADD IF NOT EXISTS
        PARTITION (ingest_date='{{ today }}')
        LOCATION '{{ location }}ingest_date={{ today }}/'
    {% endset %}
    {% do run_query(alter_sql) %}
    {{ log("Registered partition ingest_date=" ~ today ~ " for " ~ table_name, info=True) }}

    {# diagnostics_orders has historical Trust export dates #}
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
        {{ log("Registered 14 diagnostics partitions (2024-12-18 to 2024-12-31)", info=True) }}
    {% endif %}
{% endfor %}

{{ log("Partition registration complete for all 8 tables.", info=True) }}
{% endmacro %}
