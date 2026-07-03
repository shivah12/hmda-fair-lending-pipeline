-- One row per state/county/year, for geographic drill-down of disparity
-- metrics in the dashboard.

with stg as (
    select * from {{ ref('stg_hmda_lar') }}
)

select
    state_code,
    county_code,
    activity_year,
    count(*)                        as total_applications,
    sum(approved)                   as total_approved,
    round(avg(approved) * 100, 2)   as approval_rate_pct
from stg
group by state_code, county_code, activity_year
