"""
Orchestrates the fair lending analysis at national scale:

- AIR and the two-proportion z-test are computed via DuckDB aggregation
  (SQL pushdown) directly against marts.fct_applications -- these only need
  group-level counts/means, so there's no reason to materialize tens of
  millions of rows in pandas just to compute a mean.

- The logistic regression needs row-level data (statsmodels fits on
  individual observations), so it draws a reproducible random SAMPLE via
  DuckDB's native sampling (pushed down, doesn't scan-then-discard) rather
  than loading the full population into pandas. Default sample size is
  configurable; increase it if you want tighter confidence intervals, at
  the cost of slower model fitting.

Usage:
    python analysis/run_analysis.py
    python analysis/run_analysis.py --db data/hmda.duckdb --year 2023
    python analysis/run_analysis.py --regression-sample-size 1000000
"""
import argparse
from pathlib import Path

import duckdb
import pandas as pd

from fair_lending_metrics import (
    compute_air_sql,
    two_proportion_z_test_from_counts,
    logistic_regression_disparity,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "hmda.duckdb"
REFERENCE_GROUP = "White (reference)"
CONTROL_VARS = ["loan_amount", "applicant_income_000s", "loan_to_value_ratio", "debt_to_income_pct"]


def build_where_clause(year: int | None) -> str:
    return f"activity_year = {year}" if year else "1=1"


def main():
    parser = argparse.ArgumentParser(description="Run HMDA fair lending analysis at scale")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--year", type=int, default=None, help="Restrict to a single activity_year")
    parser.add_argument(
        "--regression-sample-size", type=int, default=500_000,
        help="Row-level sample size for the logistic regression (AIR/z-test always use the full population)"
    )
    parser.add_argument("--seed", type=int, default=42, help="Sampling seed, for reproducibility")
    parser.add_argument("--out", default=str(ROOT / "data" / "fair_lending_results.parquet"))
    args = parser.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    where = build_where_clause(args.year)

    total_n = con.execute(f"SELECT COUNT(*) FROM marts.fct_applications WHERE {where}").fetchone()[0]
    print(f"Population: {total_n:,} applications (full population, no sampling for AIR/z-test)\n")

    # 1. Adverse Impact Ratio -- computed on the FULL population via SQL pushdown
    print("=" * 70)
    print("ADVERSE IMPACT RATIO (AIR) -- full population")
    print("=" * 70)
    air_results = compute_air_sql(
        con, "marts.fct_applications", "protected_group", "approved", REFERENCE_GROUP, where
    )
    air_df = pd.DataFrame([r.__dict__ for r in air_results])
    print(air_df.to_string(index=False))

    # 2. Two-proportion z-tests -- also full population, from the same
    #    group-level counts (no separate row-level query needed)
    print("\n" + "=" * 70)
    print("TWO-PROPORTION Z-TESTS -- full population")
    print("=" * 70)
    counts = con.execute(f"""
        SELECT protected_group, COUNT(*) AS n, SUM(approved) AS x
        FROM marts.fct_applications
        WHERE {where}
        GROUP BY protected_group
    """).fetchdf().set_index("protected_group")

    ref_n, ref_x = int(counts.loc[REFERENCE_GROUP, "n"]), int(counts.loc[REFERENCE_GROUP, "x"])
    z_results = []
    for group in counts.index:
        if group == REFERENCE_GROUP:
            continue
        n, x = int(counts.loc[group, "n"]), int(counts.loc[group, "x"])
        z_results.append(
            two_proportion_z_test_from_counts(group, REFERENCE_GROUP, n, x, ref_n, ref_x)
        )
    z_df = pd.DataFrame([r.__dict__ for r in z_results])
    print(z_df.to_string(index=False))

    # 3. Logistic regression -- needs row-level data, so sample (pushed
    #    down via DuckDB's USING SAMPLE, which reads only what it needs
    #    rather than scanning the full table into pandas and discarding).
    sample_size = min(args.regression_sample_size, total_n)
    print("\n" + "=" * 70)
    print(f"LOGISTIC REGRESSION -- sample of {sample_size:,} rows (seed={args.seed})")
    print("=" * 70)
    reg_input = con.execute(f"""
        SELECT approved, protected_group, {', '.join(CONTROL_VARS)}
        FROM marts.fct_applications
        WHERE {where}
        USING SAMPLE {sample_size} (reservoir, {args.seed})
    """).fetchdf()

    reg_df = logistic_regression_disparity(
        reg_input,
        outcome_col="approved",
        protected_group_col="protected_group",
        reference_group_label=REFERENCE_GROUP,
        control_cols=CONTROL_VARS,
    )
    print(reg_df.to_string(index=False))

    # Persist results for the dashboard. Note: we persist the same
    # regression SAMPLE (not the full population) as the row-level dataset
    # the dashboard filters/drills into, to keep the dashboard responsive.
    # AIR/z-test tables are full-population and don't depend on this.
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    air_df.to_parquet(Path(args.out).with_name("air_results.parquet"))
    z_df.to_parquet(Path(args.out).with_name("z_test_results.parquet"))
    reg_df.to_parquet(Path(args.out).with_name("regression_results.parquet"))

    dashboard_sample = con.execute(f"""
        SELECT *
        FROM marts.fct_applications
        WHERE {where}
        USING SAMPLE {min(sample_size, 200_000)} (reservoir, {args.seed})
    """).fetchdf()
    dashboard_sample.to_parquet(args.out)

    print(f"\nResults written to {Path(args.out).parent}/")
    con.close()


if __name__ == "__main__":
    main()
