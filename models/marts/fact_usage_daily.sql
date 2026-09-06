select
    du.usage_date,
    dc.client_id,
    dc.client_name,
    dc.current_plan,
    du.active_users,
    du.feature_usage_count,
    du.api_calls

from {{ ref('stg_daily_usage') }} as du

left join {{ ref('dim_client') }} as dc
    on du.client_id = dc.client_id

left join {{ ref('dim_date') }} as dd
    on du.usage_date = dd.calendar_date