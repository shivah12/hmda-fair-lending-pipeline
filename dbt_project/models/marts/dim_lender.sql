-- One row per lender (LEI) per year, with volume and overall approval rate.
-- Used to let the dashboard drill into specific lenders' disparity metrics.

with stg as (
    select * from {{ ref('stg_hmda_lar') }}
)

select
    lei,
    activity_year,
    count(*)                                   as total_applications,
    sum(approved)                              as total_approved,
    round(avg(approved) * 100, 2)              as approval_rate_pct,
    count(distinct race)                       as distinct_race_categories,
    round(avg(loan_amount), 0)                 as avg_loan_amount
from stg
group by lei, activity_year
