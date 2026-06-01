{% macro add_spectrum_partitions() %}
{# Registers ingest_date partitions for all bronze Spectrum tables.
   Adds today's date partition as a minimum/fallback.
   Historical partitions are discovered automatically via svv_external_partitions
   (see get_ingest_dates macro) or MSCK REPAIR TABLE.
   ADD IF NOT EXISTS makes this idempotent - safe to rerun.
   Run via: dbt run-operation add_spectrum_partitions #}

{% set bronze_prefix = env_var('BRONZE_S3_PREFIX') %}
{% set external_schema = 'bronze_external' %}

{% set tables = {
    'patient_demographics':    'source=ehr_postgres/entity=patient_demographics',
    'encounters':              'source=ehr_postgres/entity=encounters',
    'referrals':               'source=ehr_postgres/entity=referrals',
    'diagnoses':               'source=ehr_postgres/entity=diagnoses',
    'appointments':            'source=sftp_appointments/entity=appointments',
    'diagnostics_orders':      'source=trust_s3_diagnostics/entity=diagnostics_orders',
    'provider_site_reference': 'source=trust_s3_provider_ref/entity=provider_site_reference',
    'urgent_care_logs':        'source=urgent_care_postgres/entity=urgent_care_logs',
} %}

{% set today = modules.datetime.date.today().isoformat() %}

{% for table_name, source_path in tables.items() %}
    {% set alter_sql %}
        ALTER TABLE {{ external_schema }}.{{ table_name }}
        ADD IF NOT EXISTS
        PARTITION (ingest_date='{{ today }}')
        LOCATION '{{ bronze_prefix }}/{{ source_path }}/ingest_date={{ today }}/'
    {% endset %}
    {% do run_query(alter_sql) %}
    {{ log("Registered partition ingest_date=" ~ today ~ " for " ~ table_name, info=True) }}
{% endfor %}

{{ log("Partition registration complete for all 8 tables.", info=True) }}
{% endmacro %}
