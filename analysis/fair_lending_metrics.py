"""
Fair lending disparity metrics, implemented the way CFPB / DOJ examiners
actually approach it:

1. Adverse Impact Ratio (AIR) -- approval rate for a protected group divided
   by the approval rate for the reference group (typically White,
   non-Hispanic applicants). AIR < 0.80 is the conventional "four-fifths
   rule" screening threshold.

2. Two-proportion z-test -- tests whether an observed approval-rate gap
   between two groups is statistically significant, or plausibly noise
   given sample size.

3. Logistic regression -- models approval as a function of protected-class
   membership *plus* legitimate underwriting variables (income, loan
   amount, LTV, DTI). A statistically significant coefficient on the
   protected-class indicator, after controlling for these factors, is the
   closer analogue to what a regulator would flag as disparate treatment
   risk (note: HMDA data lacks credit score, a known limitation).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats


@dataclass
class AIRResult:
    group: str
    reference_group: str
    group_n: int
    reference_n: int
    group_approval_rate: float
    reference_approval_rate: float
    air: float
    flagged_under_four_fifths_rule: bool


@dataclass
class ZTestResult:
    group: str
    reference_group: str
    approval_rate_gap_pct: float
    z_statistic: float
    p_value: float
    significant_at_05: bool


def compute_air(
    df: pd.DataFrame,
    group_col: str,
    outcome_col: str,
    reference_group_label: str,
) -> list[AIRResult]:
    """
    Compute Adverse Impact Ratio for every group in `group_col` relative to
    `reference_group_label`.
    """
    rates = df.groupby(group_col)[outcome_col].agg(["mean", "count"])
    if reference_group_label not in rates.index:
        raise ValueError(f"Reference group '{reference_group_label}' not found in data")

    ref_rate = rates.loc[reference_group_label, "mean"]
    ref_n = int(rates.loc[reference_group_label, "count"])

    results = []
    for group, row in rates.iterrows():
        if group == reference_group_label:
            continue
        air = row["mean"] / ref_rate if ref_rate > 0 else np.nan
        results.append(
            AIRResult(
                group=group,
                reference_group=reference_group_label,
                group_n=int(row["count"]),
                reference_n=ref_n,
                group_approval_rate=round(row["mean"] * 100, 2),
                reference_approval_rate=round(ref_rate * 100, 2),
                air=round(air, 3) if pd.notna(air) else np.nan,
                flagged_under_four_fifths_rule=bool(air < 0.80) if pd.notna(air) else False,
            )
        )
    return sorted(results, key=lambda r: r.air)


def compute_air_sql(
    con,
    table: str,
    group_col: str,
    outcome_col: str,
    reference_group_label: str,
    where_clause: str = "1=1",
) -> list[AIRResult]:
    """
    Same as compute_air(), but pushes the GROUP BY aggregation down to
    DuckDB instead of materializing the full row-level table in pandas.
    Use this once the fact table is tens of millions of rows -- AIR and the
    z-test only need group-level counts and means, not individual rows.

    `con` is a duckdb connection; `table` is a fully-qualified table name
    (e.g. "marts.fct_applications").
    """
    rates = con.execute(f"""
        SELECT {group_col} AS grp, AVG({outcome_col}) AS rate, COUNT(*) AS n
        FROM {table}
        WHERE {where_clause}
        GROUP BY {group_col}
    """).fetchdf().set_index("grp")

    if reference_group_label not in rates.index:
        raise ValueError(f"Reference group '{reference_group_label}' not found in data")

    ref_rate = rates.loc[reference_group_label, "rate"]
    ref_n = int(rates.loc[reference_group_label, "n"])

    results = []
    for group, row in rates.iterrows():
        if group == reference_group_label:
            continue
        air = row["rate"] / ref_rate if ref_rate > 0 else np.nan
        results.append(
            AIRResult(
                group=group,
                reference_group=reference_group_label,
                group_n=int(row["n"]),
                reference_n=ref_n,
                group_approval_rate=round(row["rate"] * 100, 2),
                reference_approval_rate=round(ref_rate * 100, 2),
                air=round(air, 3) if pd.notna(air) else np.nan,
                flagged_under_four_fifths_rule=bool(air < 0.80) if pd.notna(air) else False,
            )
        )
    return sorted(results, key=lambda r: r.air)


def two_proportion_z_test_from_counts(
    group_label: str,
    reference_group_label: str,
    n1: int, x1: int,
    n2: int, x2: int,
) -> ZTestResult:
    """
    Same test as two_proportion_z_test(), but takes pre-aggregated counts
    (n = sample size, x = number approved) instead of row-level data -- the
    natural pairing with compute_air_sql() when the fact table is too large
    to want to pull row-level data into pandas just for this test.
    """
    p1, p2 = x1 / n1, x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se if se > 0 else np.nan
    p_value = 2 * (1 - stats.norm.cdf(abs(z))) if pd.notna(z) else np.nan

    return ZTestResult(
        group=group_label,
        reference_group=reference_group_label,
        approval_rate_gap_pct=round((p1 - p2) * 100, 2),
        z_statistic=round(z, 4) if pd.notna(z) else np.nan,
        p_value=round(p_value, 6) if pd.notna(p_value) else np.nan,
        significant_at_05=bool(p_value < 0.05) if pd.notna(p_value) else False,
    )


def two_proportion_z_test(
    df: pd.DataFrame,
    group_col: str,
    outcome_col: str,
    group_label: str,
    reference_group_label: str,
) -> ZTestResult:
    """
    Two-proportion z-test comparing approval rate of `group_label` vs
    `reference_group_label`. Uses the standard pooled-proportion z-test.
    """
    g = df[df[group_col] == group_label][outcome_col]
    r = df[df[group_col] == reference_group_label][outcome_col]

    n1, n2 = len(g), len(r)
    p1, p2 = g.mean(), r.mean()
    p_pool = (g.sum() + r.sum()) / (n1 + n2)

    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se if se > 0 else np.nan
    p_value = 2 * (1 - stats.norm.cdf(abs(z))) if pd.notna(z) else np.nan

    return ZTestResult(
        group=group_label,
        reference_group=reference_group_label,
        approval_rate_gap_pct=round((p1 - p2) * 100, 2),
        z_statistic=round(z, 4) if pd.notna(z) else np.nan,
        p_value=round(p_value, 6) if pd.notna(p_value) else np.nan,
        significant_at_05=bool(p_value < 0.05) if pd.notna(p_value) else False,
    )


def logistic_regression_disparity(
    df: pd.DataFrame,
    outcome_col: str,
    protected_group_col: str,
    reference_group_label: str,
    control_cols: list[str],
) -> pd.DataFrame:
    """
    Fit logistic regression: outcome ~ protected_group dummies + controls.
    Returns a coefficient table with odds ratios, p-values, and confidence
    intervals for the protected-group indicators, holding the listed
    controls constant.

    A negative, statistically significant coefficient on a protected group
    (relative to the reference group) means that group is less likely to be
    approved even after controlling for the listed underwriting variables.
    """
    model_df = df[[outcome_col, protected_group_col] + control_cols].dropna().copy()

    # standardize continuous controls so coefficients are comparable
    for col in control_cols:
        std = model_df[col].std()
        if std > 0:
            model_df[col] = (model_df[col] - model_df[col].mean()) / std

    dummies = pd.get_dummies(
        model_df[protected_group_col], prefix="grp", drop_first=False
    )
    ref_col = f"grp_{reference_group_label}"
    if ref_col in dummies.columns:
        dummies = dummies.drop(columns=[ref_col])

    X = pd.concat([dummies, model_df[control_cols]], axis=1).astype(float)
    X = sm.add_constant(X)
    y = model_df[outcome_col].astype(float)

    model = sm.Logit(y, X).fit(disp=0)

    summary = pd.DataFrame({
        "coefficient": model.params,
        "odds_ratio": np.exp(model.params),
        "p_value": model.pvalues,
        "ci_lower_odds": np.exp(model.conf_int()[0]),
        "ci_upper_odds": np.exp(model.conf_int()[1]),
    })
    summary["significant_at_05"] = summary["p_value"] < 0.05
    summary["n_obs"] = int(model.nobs)
    return summary.reset_index().rename(columns={"index": "variable"})
