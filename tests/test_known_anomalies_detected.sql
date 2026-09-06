-- Fails (returns rows) if any known injected anomaly was NOT detected in its expected window.

with expected_anomalies as (
    select 'C004' as client_id, date('2025-09-01') as start_date, date('2025-09-07') as end_date
    union all
    select 'C009' as client_id, date('2025-04-10') as start_date, date('2025-04-12') as end_date
),

detected as (
    select client_id, usage_date
    from {{ ref('fact_usage_anomalies') }}
    where is_anomaly = true
)

select ea.client_id, ea.start_date, ea.end_date
from expected_anomalies as ea
where not exists (
    select 1
    from detected as d
    where d.client_id = ea.client_id
      and d.usage_date between ea.start_date and ea.end_date
)