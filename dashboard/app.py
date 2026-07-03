"""
Streamlit dashboard for the HMDA Fair Lending Data Pipeline.

Run with:
    streamlit run dashboard/app.py
"""
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REFERENCE_GROUP = "White (reference)"

st.set_page_config(page_title="HMDA Fair Lending Dashboard", layout="wide")


@st.cache_data
def load_results():
    apps = pd.read_parquet(DATA_DIR / "fair_lending_results.parquet")
    air = pd.read_parquet(DATA_DIR / "air_results.parquet")
    z = pd.read_parquet(DATA_DIR / "z_test_results.parquet")
    reg = pd.read_parquet(DATA_DIR / "regression_results.parquet")
    return apps, air, z, reg


try:
    apps, air_df, z_df, reg_df = load_results()
except FileNotFoundError:
    st.error(
        "No results found. Run the pipeline first:\n\n"
        "1. python ingestion/download_hmda.py --states CA --years 2023\n"
        "2. python ingestion/load_to_duckdb.py\n"
        "3. cd dbt_project && dbt run\n"
        "4. python analysis/run_analysis.py"
    )
    st.stop()

st.title("HMDA Fair Lending Disparity Dashboard")
st.caption(
    "Adverse Impact Ratio, statistical significance, and controlled regression "
    "results for mortgage approval disparities by race/ethnicity."
)

# ---- Sidebar filters ----
st.sidebar.header("Filters")
years = sorted(apps["activity_year"].unique())
selected_years = st.sidebar.multiselect("Activity year", years, default=years)

lenders = sorted(apps["lei"].dropna().unique())
selected_lender = st.sidebar.selectbox("Lender (LEI)", ["All lenders"] + list(lenders))

filtered = apps[apps["activity_year"].isin(selected_years)]
if selected_lender != "All lenders":
    filtered = filtered[filtered["lei"] == selected_lender]

st.sidebar.metric("Applications in view", f"{len(filtered):,}")

# ---- Top-line metrics ----
col1, col2, col3 = st.columns(3)
overall_rate = filtered["approved"].mean() * 100
col1.metric("Overall approval rate", f"{overall_rate:.1f}%")
n_flagged = int(air_df["flagged_under_four_fifths_rule"].sum())
col2.metric("Groups flagged (AIR < 0.80)", n_flagged)
n_sig = int(z_df["significant_at_05"].sum())
col3.metric("Statistically significant gaps (p<0.05)", n_sig)

st.divider()

# ---- AIR chart ----
st.subheader("Adverse Impact Ratio by Group")
st.caption(
    "AIR = group approval rate ÷ reference group (White, non-Hispanic) approval rate. "
    "The dashed line marks the conventional four-fifths (0.80) screening threshold."
)
fig_air = px.bar(
    air_df.sort_values("air"),
    x="group",
    y="air",
    color="flagged_under_four_fifths_rule",
    color_discrete_map={True: "#d62728", False: "#2ca02c"},
    labels={"air": "Adverse Impact Ratio", "group": "Group", "flagged_under_four_fifths_rule": "Flagged"},
    text="air",
)
fig_air.add_hline(y=0.80, line_dash="dash", line_color="gray", annotation_text="0.80 threshold")
fig_air.update_traces(texttemplate="%{text:.2f}", textposition="outside")
st.plotly_chart(fig_air, use_container_width=True)

st.dataframe(air_df, use_container_width=True)

st.divider()

# ---- Z-test results ----
st.subheader("Statistical Significance of Approval Rate Gaps")
st.caption("Two-proportion z-test: is the raw approval-rate gap distinguishable from chance?")
fig_z = px.bar(
    z_df.sort_values("approval_rate_gap_pct"),
    x="group",
    y="approval_rate_gap_pct",
    color="significant_at_05",
    color_discrete_map={True: "#d62728", False: "#7f7f7f"},
    labels={"approval_rate_gap_pct": "Approval rate gap (pp)", "group": "Group", "significant_at_05": "p < 0.05"},
)
st.plotly_chart(fig_z, use_container_width=True)
st.dataframe(z_df, use_container_width=True)

st.divider()

# ---- Regression results ----
st.subheader("Logistic Regression: Approval ~ Protected Group + Underwriting Controls")
st.caption(
    "Controls for loan amount, income, LTV, and DTI. Odds ratio < 1 with p < 0.05 means "
    "that group is significantly less likely to be approved than the reference group, "
    "even after accounting for these underwriting factors."
)
group_rows = reg_df[reg_df["variable"].str.startswith("grp_")].copy()
group_rows["group"] = group_rows["variable"].str.replace("grp_", "", regex=False)
fig_reg = px.scatter(
    group_rows,
    x="odds_ratio",
    y="group",
    color="significant_at_05",
    color_discrete_map={True: "#d62728", False: "#7f7f7f"},
    error_x=group_rows["ci_upper_odds"] - group_rows["odds_ratio"],
    error_x_minus=group_rows["odds_ratio"] - group_rows["ci_lower_odds"],
    labels={"odds_ratio": "Odds Ratio (95% CI)", "group": "Group"},
)
fig_reg.add_vline(x=1.0, line_dash="dash", line_color="gray", annotation_text="No effect (OR=1)")
st.plotly_chart(fig_reg, use_container_width=True)
st.dataframe(reg_df, use_container_width=True)

st.divider()
st.caption(
    "Methodology note: HMDA public data does not include credit score, which is a known "
    "limitation of any HMDA-only fair lending analysis. Results here should be read as "
    "screening indicators consistent with CFPB's public methodology, not as legal findings."
)
