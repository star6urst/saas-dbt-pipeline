with usage_with_baseline as (

    select
        client_id,
        usage_date,
        active_users,

        avg(active_users) over (
            partition by client_id
            order by usage_date
            rows between 14 preceding and 1 preceding
        ) as avg_active_users_14d,

        stddev(active_users) over (
            partition by client_id
            order by usage_date
            rows between 14 preceding and 1 preceding
        ) as stddev_active_users_14d

    from {{ ref('fact_usage_daily') }}

)

select
    client_id,
    usage_date,
    active_users,
    avg_active_users_14d,
    stddev_active_users_14d,
    safe_divide(active_users - avg_active_users_14d, stddev_active_users_14d) as active_users_zscore,

    case
        when abs(safe_divide(active_users - avg_active_users_14d, stddev_active_users_14d)) >= 3
        then true
        else false
    end as is_anomaly

from usage_with_baseline

where avg_active_users_14d is not null
  and stddev_active_users_14d is not null
  and stddev_active_users_14d > 0