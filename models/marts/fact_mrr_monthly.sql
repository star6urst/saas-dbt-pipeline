with months as (

    select distinct
        date_trunc(calendar_date, month) as month_start

    from {{ ref('dim_date') }}

),

client_months as (

    select
        c.client_id,
        m.month_start

    from {{ ref('dim_client') }} as c
    cross join months as m

    where m.month_start >= date_trunc(c.signup_date, month)

),

events_before_month_end as (

    select
        cm.client_id,
        cm.month_start,
        se.mrr_amount,
        se.event_date,
        row_number() over (
            partition by cm.client_id, cm.month_start
            order by se.event_date desc
        ) as rn

    from client_months as cm

    inner join {{ ref('stg_subscription_events') }} as se
        on se.client_id = cm.client_id
        and se.event_date <= last_day(cm.month_start, month)

)

select
    client_id,
    month_start,
    mrr_amount

from events_before_month_end

where rn = 1

order by client_id, month_start