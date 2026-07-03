-- Staging: cast raw (all-varchar) HMDA columns to proper types, decode
-- action_taken into a readable outcome, and filter out rows that are
-- unusable for a fair lending analysis (missing race/ethnicity, missing
-- key underwriting fields, or exempt/NA sentinel values).

with source as (

    select * from raw.hmda_lar

),

typed as (

    select
        s.lei                                                        as lei,
        cast(s.activity_year as integer)                             as activity_year,
        s.state_code                                                 as state_code,
        s.county_code                                                as county_code,
        s.derived_race                                               as race,
        s.derived_ethnicity                                          as ethnicity,
        s.derived_sex                                                as sex,
        cast(s.action_taken as integer)                              as action_taken_code,
        cast(s.loan_amount as double)                                as loan_amount,
        try_cast(s.income as double)                                 as applicant_income_000s,
        try_cast(nullif(s.combined_loan_to_value_ratio, 'NA') as double)      as loan_to_value_ratio,
        s.debt_to_income_ratio                                       as debt_to_income_bucket_raw,
        try_cast(nullif(s.property_value, 'NA') as double)           as property_value,
        s.loan_type                                                  as loan_type_code,
        s.loan_purpose                                               as loan_purpose_code,
        s.occupancy_type                                             as occupancy_type_code,
        s.derived_dwelling_category                                  as dwelling_category

    from source s

),

decoded as (

    select
        *,
        case
            when action_taken_code = 1 then 1
            when action_taken_code = 2 then 1
            when action_taken_code = 3 then 0
            else null
        end as approved,

        case
            when regexp_matches(debt_to_income_bucket_raw, '^[0-9]+\.?[0-9]*$') then
                try_cast(debt_to_income_bucket_raw as double)
            when debt_to_income_bucket_raw = '<20%' then 15.0
            when debt_to_income_bucket_raw = '20%-<30%' then 25.0
            when debt_to_income_bucket_raw = '30%-<36%' then 33.0
            when debt_to_income_bucket_raw = '36%-<40%' then 38.0
            when debt_to_income_bucket_raw = '40%-<50%' then 45.0
            when debt_to_income_bucket_raw = '50%-60%' then 55.0
            when debt_to_income_bucket_raw = '>60%' then 65.0
            else null
        end as debt_to_income_pct

    from typed

)

select
    lei,
    activity_year,
    state_code,
    county_code,
    race,
    ethnicity,
    sex,
    action_taken_code,
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
from decoded
where
    approved is not null
    and race is not null
    and race not in ('Race Not Available', '9')
    and ethnicity is not null
    and ethnicity not in ('Ethnicity Not Available', '9')
    and loan_amount is not null