# Synthetic SaaS Analytics Pipeline

An end-to-end analytics engineering project built on a self-generated multi-tenant B2B SaaS dataset: dbt + BigQuery for transformation, automated anomaly detection, and a genuinely embedded, randomized A/B test analyzed with difference-in-differences. CI runs the full build and test suite on every push via GitHub Actions, authenticated with Workload Identity Federation.

This project reuses the same GCP/dbt/CI infrastructure built for [weather-dbt-pipeline](https://github.com/star6urst/weather-dbt-pipeline), applied to a dataset designed specifically to exercise things weather data can't: multiple business entities, revenue over time, anomaly detection, and a real experiment.

## Architecture

```
Python generator (scripts/generate_saas_data.py)
      │
      ▼
BigQuery: saas_raw
   ├── clients
   ├── subscription_events
   ├── daily_usage
   └── experiment_assignments
      │
      ▼
dbt staging models (cleaned, renamed, typed)
      │
      ├──▶ dim_client
      ├──▶ dim_date
      │
      ├──▶ fact_usage_daily
      ├──▶ fact_mrr_monthly        (point-in-time MRR per client, per month)
      ├──▶ fact_usage_anomalies    (rolling z-score anomaly detection)
      └──▶ fact_experiment_usage   (feature-launch A/B test, pre/post)
```

## The data

18 fake client companies on Starter/Pro/Enterprise plans, with a full year (2025) of daily usage data (active users, feature usage, API calls). Built in with deliberate realism:

- Staggered signups — some clients join partway through the year
- ~3 clients churn during the year
- A few clients upgrade or downgrade plans mid-year
- A missing-data window for 2 clients (simulates a broken tracking pipeline)
- An injected usage spike (viral feature adoption) and an injected usage drop (an outage), each on a specific client and date range

Nothing here is real; it's a Python-generated dataset designed to behave like a real SaaS business would.

## Anomaly detection

`fact_usage_anomalies` computes a trailing 14-day rolling average and standard deviation per client, then flags any day where usage deviates by more than 3 standard deviations (a z-score check). This is validated against ground truth: a singular dbt test (`tests/test_known_anomalies_detected.sql`) checks that both injected anomalies are actually caught, rather than just checking that the query runs without error.

## The A/B test

A simulated feature launch (Oct 1, 2025) with a genuine embedded experiment: eligible clients (active, with no confounding plan changes or churn near the launch window) are randomly assigned to treatment or control, stratified by plan tier. Treatment clients receive a real, per-client-variable usage uplift (~15-18% on average) on `active_users` and `feature_usage_count` only — `api_calls` is deliberately left untouched, as a built-in negative control.

The analysis (`analysis/run_did_analysis.py`) compares three approaches per metric:
- A naive post-only comparison
- A naive pre/post comparison (ignoring any underlying time trend)
- The correct difference-in-differences estimate, via OLS regression with an interaction term and standard errors clustered by client

**Results:** `feature_usage_count` showed a statistically significant lift (p = 0.016) matching the true planted effect almost exactly. `active_users` showed a directionally consistent lift that didn't clear conventional significance, most likely due to the small sample (11 eligible clients) rather than a real absence of effect. `api_calls`, the negative control, correctly showed no significant effect (p = 0.39) — evidence the method isn't hallucinating results where nothing was planted.

## Stack

- **Generation**: Python (`pandas`, `numpy`) → BigQuery, via `google-cloud-bigquery`
- **Transformation**: dbt Core, `dbt-bigquery` adapter, `dbt_utils`
- **Warehouse**: Google BigQuery
- **Analysis**: Python (`statsmodels`) for the DiD regression
- **Testing**: dbt schema tests plus a custom singular test validating anomaly detection against ground truth
- **CI/CD**: GitHub Actions, authenticated via Workload Identity Federation (no service account keys)

## Project structure

```
models/
├── staging/
│   ├── sources.yml
│   ├── stg_clients.sql
│   ├── stg_subscription_events.sql
│   ├── stg_daily_usage.sql
│   └── stg_experiment_assignments.sql
└── marts/
    ├── dim_client.sql
    ├── dim_date.sql
    ├── fact_usage_daily.sql
    ├── fact_mrr_monthly.sql
    ├── fact_usage_anomalies.sql
    ├── fact_experiment_usage.sql
    └── dim_client.yml            # tests for all marts models
tests/
└── test_known_anomalies_detected.sql
scripts/
└── generate_saas_data.py         # generates and loads all four raw tables
analysis/
└── run_did_analysis.py           # DiD regression against fact_experiment_usage
.github/workflows/
└── ci.yml
```

## Running it locally

1. Install dependencies:
   ```bash
   pip install dbt-bigquery google-cloud-bigquery pandas numpy statsmodels
   ```
2. Authenticate to Google Cloud (oauth/ADC, no key file):
   ```bash
   gcloud auth application-default login
   ```
3. Generate and load the synthetic data:
   ```bash
   python scripts/generate_saas_data.py
   ```
4. Build and test the dbt project:
   ```bash
   dbt deps
   dbt build
   ```
5. Run the A/B test analysis:
   ```bash
   python analysis/run_did_analysis.py
   ```

## Notes on getting this right

Two real bugs turned up during development, both worth naming rather than hiding:

- The data generator originally let anomaly-target clients get a staggered (late) signup date, which could push a client's signup past its own hardcoded anomaly injection window — meaning the anomaly would never have any data to land on. Caught by the ground-truth anomaly test failing, not by inspection.
- The first version of the embedded experiment didn't account for a client's plan changing (or an anomaly already in their history) during the analysis window itself, which showed up as an unrelated confound distorting individual clients' pre/post usage. Fixed by excluding any client with a disruptive event inside the analysis window, and by excluding the two anomaly-carrying clients from the experiment population entirely.

Both were found by checking assumptions against known ground truth rather than trusting that a clean-looking query result meant a clean-looking analysis.
