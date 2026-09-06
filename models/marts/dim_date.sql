with spine as (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2025-01-01' as date)",
        end_date="cast('2026-01-01' as date)"
    ) }}

)

select
    date_day as calendar_date,
    extract(year from date_day) as year,
    extract(month from date_day) as month,
    extract(day from date_day) as day,
    extract(dayofweek from date_day) as day_of_week,
    format_date('%A', date_day) as day_name,
    format_date('%B', date_day) as month_name,
    extract(quarter from date_day) as quarter,
    case
        when extract(dayofweek from date_day) in (1, 7) then true
        else false
    end as is_weekend

from spine