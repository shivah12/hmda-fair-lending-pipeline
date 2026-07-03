-- Analysis-ready fact table: one row per HMDA application, with the
-- features needed for AIR calculation and the regression model.

with stg as (
    select * from {{ ref('stg_hmda_lar') }}
),

flagged as (
    select
        *,
        -- Reference group for AIR comparisons, per CFPB convention:
        -- White non-Hispanic applicants
        case
            when race = 'White' and ethnicity = 'Not Hispanic or Latino'
                then true
            else false
        end as is_reference_group,

        case
            when ethnicity = 'Hispanic or Latino' then 'Hispanic'
            when race in ('Black or African American') then 'Black'
            when race in ('Asian') then 'Asian'
            when race in ('American Indian or Alaska Native') then 'American Indian or Alaska Native'
            when race in ('Native Hawaiian or Other Pacific Islander') then 'Native Hawaiian or Other Pacific Islander'
            when race = 'White' and ethnicity = 'Not Hispanic or Latino' then 'White (reference)'
            else 'Other / Multiple'
        end as protected_group

    from stg
)

select
    lei,
    activity_year,
    state_code,
    county_code,
    race,
    ethnicity,
    sex,
    protected_group,
    is_reference_group,
    approved,
    loan_amount,
    applicant_income_000s,
    loan_to_value_ratio,
    debt_to_income_pct,
    property_value,
    loan_type_code,
    loan_purpose_code,
    occupancy_type_code,
    dwelling_category
from flagged
