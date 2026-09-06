select
    u.usage_date,
    u.client_id,
    a.plan_tier_at_assignment,
    a.experiment_group,
    u.active_users,
    u.feature_usage_count,
    u.api_calls,

    case
        when u.usage_date < date('2025-10-01') then 'pre'
        else 'post'
    end as period

from {{ ref('fact_usage_daily') }} as u

inner join {{ ref('stg_experiment_assignments') }} as a
    on u.client_id = a.client_id

where u.usage_date between date('2025-09-01') and date('2025-10-31')