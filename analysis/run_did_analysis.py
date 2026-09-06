"""
Difference-in-differences (DiD) analysis of the simulated feature-launch
A/B test, run against the fact_experiment_usage dbt model in BigQuery.

Compares:
  1. A naive post-only comparison (treatment vs control, post-period only)
     -- shown to illustrate why this is the wrong approach when the two
     groups may have different baselines.
  2. A naive pre/post comparison within the treatment group only
     -- shown to illustrate why this is wrong when there's an underlying
     time trend (e.g. organic growth) that has nothing to do with treatment.
  3. The correct DiD estimate: treatment_effect = the amount BY WHICH the
     treatment group's own pre-to-post change differs from the control
     group's own pre-to-post change. This nets out both the average
     group-level baseline difference and the common time trend.

The DiD estimate is obtained via OLS regression with an interaction term:
    metric ~ is_treatment + is_post + is_treatment:is_post
The coefficient on the interaction term is the DiD estimate.
Standard errors are clustered by client_id, since each client contributes
many correlated daily observations (not independent rows).
"""

import pandas as pd
import statsmodels.formula.api as smf
from google.cloud import bigquery

PROJECT_ID = "project-256beac9-89c1-4aed-ab4"
DATASET = "saas_dbt"


def load_data():
    client = bigquery.Client(project=PROJECT_ID)
    query = f"""
        select
            client_id,
            usage_date,
            experiment_group,
            period,
            active_users,
            feature_usage_count,
            api_calls
        from `{PROJECT_ID}.{DATASET}.fact_experiment_usage`
    """
    return client.query(query).to_dataframe()


def run_did(df, metric):
    """Run the DiD regression for a given metric column, return the fitted model."""
    data = df.copy()
    data["is_treatment"] = (data["experiment_group"] == "treatment").astype(int)
    data["is_post"] = (data["period"] == "post").astype(int)

    formula = f"{metric} ~ is_treatment * is_post"
    model = smf.ols(formula, data=data).fit(
        cov_type="cluster", cov_kwds={"groups": data["client_id"]}
    )
    return model


def naive_comparisons(df, metric):
    """Show the two naive (wrong) approaches, for contrast."""
    post = df[df["period"] == "post"]
    treat_post_mean = post[post.experiment_group == "treatment"][metric].mean()
    control_post_mean = post[post.experiment_group == "control"][metric].mean()
    naive_post_only = treat_post_mean - control_post_mean

    treat = df[df.experiment_group == "treatment"]
    treat_pre_mean = treat[treat.period == "pre"][metric].mean()
    treat_post_mean2 = treat[treat.period == "post"][metric].mean()
    naive_pre_post = treat_post_mean2 - treat_pre_mean

    return naive_post_only, naive_pre_post


def main():
    print("Querying fact_experiment_usage from BigQuery...")
    df = load_data()
    print(f"Loaded {len(df)} rows, {df.client_id.nunique()} clients "
          f"({df[df.experiment_group=='treatment'].client_id.nunique()} treatment, "
          f"{df[df.experiment_group=='control'].client_id.nunique()} control)\n")

    for metric in ["active_users", "feature_usage_count", "api_calls"]:
        print("=" * 70)
        print(f"METRIC: {metric}")
        print("=" * 70)

        naive_post_only, naive_pre_post = naive_comparisons(df, metric)
        print(f"Naive post-only comparison (treatment - control, post period only): {naive_post_only:+.3f}")
        print(f"  -> wrong if the two groups had different baselines to begin with")
        print(f"Naive pre/post comparison (treatment group only, post - pre):       {naive_pre_post:+.3f}")
        print(f"  -> wrong if there's a time trend unrelated to treatment (e.g. organic growth)")

        model = run_did(df, metric)
        interaction_term = "is_treatment:is_post"
        did_estimate = model.params[interaction_term]
        did_pvalue = model.pvalues[interaction_term]
        ci_low, ci_high = model.conf_int().loc[interaction_term]

        print(f"\nDiD estimate (interaction term):                                    {did_estimate:+.3f}")
        print(f"  95% CI: [{ci_low:+.3f}, {ci_high:+.3f}]   p-value: {did_pvalue:.4f}")
        print()

    print("=" * 70)
    print("Reminder: the true average uplift baked into the generator was ~0.15-0.18")
    print("(printed to console during data generation) on active_users and")
    print("feature_usage_count specifically -- NOT on api_calls. Compare the")
    print("DiD estimates above (as a fraction of each metric's baseline) against that.")
    print("=" * 70)


if __name__ == "__main__":
    main()
