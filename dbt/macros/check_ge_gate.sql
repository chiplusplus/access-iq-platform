{% macro check_ge_gate() %}
{#
    GE gate pre-hook -- blocks Gold promotion on Silver DQ failures.
    Queries gold._dq_results for today's GE validation results.
    Aborts if: (a) any FAILED runs, or (b) zero runs found (GE not yet run today).

    D-11: self-contained in dbt, no Prefect dependency.
    Pitfall 6: prevents silent pass on missing GE execution.

    Table schema (created by dbt/scripts/run_ge_gate.py):
      run_date DATE, table_name VARCHAR, run_status VARCHAR, failure_count INT, run_id VARCHAR
#}
{%- if execute -%}
  {%- set gate_query %}
    SELECT
        COALESCE(SUM(CASE WHEN run_status = 'FAILED' THEN 1 ELSE 0 END), 0) AS failures,
        COUNT(*) AS total_runs
    FROM gold._dq_results
    WHERE run_date = CURRENT_DATE
  {%- endset %}

  {%- set results = run_query(gate_query) -%}
  {%- set failures = results.columns[0].values()[0] -%}
  {%- set total    = results.columns[1].values()[0] -%}

  {%- if total == 0 -%}
    {{ exceptions.raise_compiler_error(
       "GE gate: No GE validation runs found for today (" ~ modules.datetime.date.today().isoformat() ~ "). "
       ~ "Run `make dq-gate` or `python dbt/scripts/run_ge_gate.py` before `dbt build --select gold`."
    ) }}
  {%- elif failures > 0 -%}
    {{ exceptions.raise_compiler_error(
       "GE gate FAILED: " ~ failures ~ " Silver table(s) have DQ failures. "
       ~ "Gold promotion blocked. Check gold._dq_results for details."
    ) }}
  {%- endif -%}
{%- endif -%}
{% endmacro %}
