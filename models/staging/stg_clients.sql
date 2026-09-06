select
    client_id,
    client_name,
    cast(signup_date as date) as signup_date,
    initial_plan

from {{ source('saas_raw', 'clients') }}