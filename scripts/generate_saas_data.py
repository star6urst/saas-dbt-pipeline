"""
Generate a synthetic multi-tenant B2B SaaS dataset and load it into BigQuery.

Produces three raw tables in the `saas_raw` dataset:
  - clients               one row per client (tenant)
  - subscription_events   plan signup/upgrade/downgrade/churn history
  - daily_usage           daily usage metrics per client

Designed to include realistic messiness: staggered signups, churn,
plan changes, a missing-data window, and injected usage anomalies
(a spike and a drop) so downstream dbt models have something real
to detect.
"""

import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
from google.cloud import bigquery

# ---- Config ----

PROJECT_ID = "project-256beac9-89c1-4aed-ab4"
DATASET = "saas_raw"

RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

START_DATE = date(2025, 1, 1)
END_DATE = date(2025, 12, 31)
ALL_DATES = pd.date_range(START_DATE, END_DATE, freq="D")

NUM_CLIENTS = 18

PLAN_TIERS = {
    "Starter": {"price": 49, "base_users": 5, "base_features": 20, "base_api": 500},
    "Pro": {"price": 199, "base_users": 25, "base_features": 80, "base_api": 3000},
    "Enterprise": {"price": 499, "base_users": 100, "base_features": 250, "base_api": 15000},
}
PLAN_WEIGHTS = {"Starter": 0.5, "Pro": 0.35, "Enterprise": 0.15}

NAME_PREFIXES = [
    "Nimbus", "Cascade", "Vertex", "Solstice", "Orbital", "Brightline",
    "Anchor", "Northgate", "Bluepeak", "Ironclad", "Lucid", "Meridian",
    "Fernwood", "Redshift", "Silverline", "Crestpoint", "Harbor", "Aster",
]
NAME_SUFFIXES = ["Analytics", "Systems", "Labs", "Solutions", "Group", "Technologies"]

# clients chosen for special treatment (fixed indices for reproducibility)
CHURN_CLIENT_IDXS = [2, 9, 15]          # will cancel partway through the year
PLAN_CHANGE_CLIENT_IDXS = [1, 4, 7, 12] # will upgrade/downgrade mid-year
MISSING_DATA_CLIENT_IDXS = [5, 11]      # will have a broken-tracking window
SPIKE_CLIENT_IDX = 3                    # viral usage spike
DROP_CLIENT_IDX = 8                     # outage-driven usage drop


def random_signup_date(idx):
    """Most clients start on day one; a handful join partway through the year.

    The two anomaly-target clients (SPIKE_CLIENT_IDX, DROP_CLIENT_IDX) are
    forced to sign up on day one, so the hardcoded anomaly injection windows
    always land on a date where that client actually has usage data.
    """
    if idx in (SPIKE_CLIENT_IDX, DROP_CLIENT_IDX):
        return START_DATE
    if idx % 4 == 0 and idx != 0:
        offset_days = random.randint(30, 300)
        return START_DATE + timedelta(days=offset_days)
    return START_DATE


def build_clients():
    rows = []
    for i in range(NUM_CLIENTS):
        client_id = f"C{i+1:03d}"
        name = f"{random.choice(NAME_PREFIXES)} {random.choice(NAME_SUFFIXES)}"
        plan = random.choices(
            list(PLAN_WEIGHTS.keys()), weights=list(PLAN_WEIGHTS.values())
        )[0]
        signup = random_signup_date(i)
        rows.append(
            {
                "client_id": client_id,
                "client_name": name,
                "signup_date": signup,
                "initial_plan": plan,
            }
        )
    return pd.DataFrame(rows)


def build_subscription_events(clients_df):
    events = []
    for idx, row in clients_df.iterrows():
        client_id = row["client_id"]
        signup = row["signup_date"]
        plan = row["initial_plan"]

        events.append(
            {
                "client_id": client_id,
                "event_date": signup,
                "event_type": "signup",
                "plan_tier": plan,
                "mrr_amount": PLAN_TIERS[plan]["price"],
            }
        )

        if idx in PLAN_CHANGE_CLIENT_IDXS:
            change_date = signup + timedelta(days=random.randint(60, 250))
            if change_date <= END_DATE:
                tiers = list(PLAN_TIERS.keys())
                current_rank = tiers.index(plan)
                # upgrade if not already Enterprise, else downgrade
                if current_rank < len(tiers) - 1:
                    new_plan = tiers[current_rank + 1]
                    event_type = "upgrade"
                else:
                    new_plan = tiers[current_rank - 1]
                    event_type = "downgrade"
                events.append(
                    {
                        "client_id": client_id,
                        "event_date": change_date,
                        "event_type": event_type,
                        "plan_tier": new_plan,
                        "mrr_amount": PLAN_TIERS[new_plan]["price"],
                    }
                )
                plan = new_plan  # so churn (if any) reflects the latest plan

        if idx in CHURN_CLIENT_IDXS:
            churn_date = signup + timedelta(days=random.randint(150, 320))
            if churn_date <= END_DATE:
                events.append(
                    {
                        "client_id": client_id,
                        "event_date": churn_date,
                        "event_type": "churn",
                        "plan_tier": None,
                        "mrr_amount": 0,
                    }
                )

    return pd.DataFrame(events).sort_values(["client_id", "event_date"]).reset_index(drop=True)


def get_active_plan(sub_events, client_id, as_of_date):
    """Look up which plan a client was on for a given date."""
    client_events = sub_events[
        (sub_events["client_id"] == client_id) & (sub_events["event_date"] <= as_of_date)
    ]
    if client_events.empty:
        return None
    latest = client_events.sort_values("event_date").iloc[-1]
    return None if latest["event_type"] == "churn" else latest["plan_tier"]


def build_daily_usage(clients_df, sub_events):
    rows = []

    for idx, client in clients_df.iterrows():
        client_id = client["client_id"]
        signup = pd.Timestamp(client["signup_date"])

        # find churn date, if any, for this client
        churn_rows = sub_events[
            (sub_events["client_id"] == client_id) & (sub_events["event_type"] == "churn")
        ]
        churn_date = pd.Timestamp(churn_rows.iloc[0]["event_date"]) if not churn_rows.empty else None

        for day in ALL_DATES:
            if day < signup:
                continue
            if churn_date is not None and day >= churn_date:
                continue

            plan = get_active_plan(sub_events, client_id, day.date())
            if plan is None:
                continue
            plan_cfg = PLAN_TIERS[plan]

            # --- missing data window (broken tracking) ---
            if idx in MISSING_DATA_CLIENT_IDXS:
                if date(2025, 6, 1) <= day.date() <= date(2025, 6, 14):
                    continue  # skip this row entirely

            # --- base usage with weekly seasonality + growth trend + noise ---
            days_since_signup = (day - signup).days
            growth_factor = 1 + min(days_since_signup / 365, 1) * 0.4  # up to +40% over the year
            weekend_factor = 0.5 if day.weekday() >= 5 else 1.0
            seasonal_factor = 0.85 if day.month in (8, 12) else 1.0  # summer/holiday dip
            noise = np.random.normal(1.0, 0.08)

            multiplier = growth_factor * weekend_factor * seasonal_factor * noise

            # --- injected anomalies ---
            if idx == SPIKE_CLIENT_IDX and date(2025, 9, 1) <= day.date() <= date(2025, 9, 7):
                multiplier *= 4.0  # viral spike week
            if idx == DROP_CLIENT_IDX and date(2025, 4, 10) <= day.date() <= date(2025, 4, 12):
                multiplier *= 0.1  # outage

            active_users = max(0, int(plan_cfg["base_users"] * multiplier))
            feature_usage = max(0, int(plan_cfg["base_features"] * multiplier))
            api_calls = max(0, int(plan_cfg["base_api"] * multiplier))

            rows.append(
                {
                    "client_id": client_id,
                    "usage_date": day.date(),
                    "active_users": active_users,
                    "feature_usage_count": feature_usage,
                    "api_calls": api_calls,
                }
            )

    return pd.DataFrame(rows)


def load_table(client, df, table_name):
    table_ref = f"{PROJECT_ID}.{DATASET}.{table_name}"
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", autodetect=True)
    print(f"Loading {len(df)} rows into {table_ref} ...")
    job = client.load_table_from_dataframe(df, table_ref, job_config=job_config)
    job.result()
    print(f"  done: {client.get_table(table_ref).num_rows} rows now in {table_ref}")


def main():
    print("Generating clients...")
    clients_df = build_clients()

    print("Generating subscription events...")
    sub_events_df = build_subscription_events(clients_df)

    print("Generating daily usage (this is the slow part)...")
    usage_df = build_daily_usage(clients_df, sub_events_df)

    print(f"\nclients: {len(clients_df)} rows")
    print(f"subscription_events: {len(sub_events_df)} rows")
    print(f"daily_usage: {len(usage_df)} rows")

    bq_client = bigquery.Client(project=PROJECT_ID)
    load_table(bq_client, clients_df, "clients")
    load_table(bq_client, sub_events_df, "subscription_events")
    load_table(bq_client, usage_df, "daily_usage")


if __name__ == "__main__":
    main()
