select
    client_id,
    plan_tier_at_assignment,
    `group` as experiment_group

from {{ source('saas_raw', 'experiment_assignments') }}