select
    client_id,
    cast(usage_date as date) as usage_date,
    active_users,
    feature_usage_count,
    api_calls

from {{ source('saas_raw', 'daily_usage') }}