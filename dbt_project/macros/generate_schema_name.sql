{#
    By default dbt prefixes custom schemas with the connection's default
    schema (e.g. "staging" becomes "main_staging"). That's a reasonable
    default for warehouses with many teams sharing a database, but for this
    single-database DuckDB project it just adds noise -- every downstream
    query (analysis scripts, the dashboard) would need to know about a
    "main_" prefix that has no meaning here. This macro makes schema names
    exactly what's declared in dbt_project.yml / model configs.
#}

{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
