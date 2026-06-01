{% macro backfill_spectrum_partitions(start_date=none, end_date=none) %}
{# Registers ingest_date partitions for all bronze Spectrum tables across a date range.
   Used after the historical backfill repartitions bronze into ~365 per-day partitions.
   ADD IF NOT EXISTS makes this idempotent.
   Run via: dbt run-operation backfill_spectrum_partitions --args '{"start_date": "2025-06-01", "end_date": "2026-06-01"}'
#}

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

{% set s_date = modules.datetime.datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else (modules.datetime.date.today() - modules.datetime.timedelta(days=365)) %}
{% set e_date = modules.datetime.datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else modules.datetime.date.today() %}
{% set day_count = (e_date - s_date).days + 1 %}

{{ log("Registering partitions from " ~ s_date.isoformat() ~ " to " ~ e_date.isoformat() ~ " (" ~ day_count ~ " days) for " ~ tables.keys()|list|length ~ " tables", info=True) }}

{% for table_name, source_path in tables.items() %}
    {% for offset in range(day_count) %}
        {% set d = s_date + modules.datetime.timedelta(days=offset) %}
        {% set alter_sql %}
            ALTER TABLE {{ external_schema }}.{{ table_name }}
            ADD IF NOT EXISTS
            PARTITION (ingest_date='{{ d.isoformat() }}')
            LOCATION '{{ bronze_prefix }}/{{ source_path }}/ingest_date={{ d.isoformat() }}/'
        {% endset %}
        {% do run_query(alter_sql) %}
    {% endfor %}
    {{ log("  " ~ table_name ~ ": " ~ day_count ~ " partitions registered", info=True) }}
{% endfor %}

{{ log("Backfill partition registration complete.", info=True) }}
{% endmacro %}
