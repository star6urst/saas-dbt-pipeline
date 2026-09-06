select
    client_id,
    cast(event_date as date) as event_date,
    event_type,
    plan_tier,
    mrr_amount

from {{ source('saas_raw', 'subscription_events') }}