with latest_status as (

    select
        client_id,
        plan_tier as current_plan,
        event_type as latest_event_type,
        event_date as latest_event_date,
        row_number() over (partition by client_id order by event_date desc) as rn

    from {{ ref('stg_subscription_events') }}

)

select
    c.client_id,
    c.client_name,
    c.signup_date,
    c.initial_plan,
    ls.current_plan,
    case when ls.latest_event_type = 'churn' then true else false end as is_churned,
    ls.latest_event_date as status_as_of_date

from {{ ref('stg_clients') }} as c

left join latest_status as ls
    on c.client_id = ls.client_id
    and ls.rn = 1