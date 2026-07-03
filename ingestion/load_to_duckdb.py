"""
Load raw HMDA CSVs (data/raw/*.csv) into a DuckDB database as a single
raw.hmda_lar table. Uses DuckDB's native CSV reader with union_by_name so
files from different years/states with slightly different column sets
still combine cleanly.

Usage:
    python ingestion/load_to_duckdb.py
    python ingestion/load_to_duckdb.py --db data/hmda.duckdb
"""
import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DEFAULT_DB = ROOT / "data" / "hmda.duckdb"


def main():
    parser = argparse.ArgumentParser(description="Load raw HMDA CSVs into DuckDB")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to DuckDB database file")
    parser.add_argument("--glob", default=str(RAW_DIR / "*.csv"), help="Glob pattern for input CSVs")
    args = parser.parse_args()

    csv_files = sorted(Path(".").glob(args.glob)) if not Path(args.glob).is_absolute() else \
        sorted(Path(args.glob).parent.glob(Path(args.glob).name))

    if not csv_files:
        raise SystemExit(
            f"No CSV files found matching {args.glob}. "
            "Run ingestion/download_hmda.py first."
        )

    print(f"Found {len(csv_files)} CSV file(s):")
    for f in csv_files:
        print(f"  - {f.name}")

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(args.db)
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")

    # union_by_name=True handles schema drift across HMDA vintages;
    # all_varchar keeps ingestion lossless -- staging models do the typing/casting.
    con.execute(f"""
        CREATE OR REPLACE TABLE raw.hmda_lar AS
        SELECT *
        FROM read_csv(
            '{args.glob}',
            union_by_name = true,
            all_varchar = true,
            filename = true,
            sample_size = -1
        )
    """)

    row_count = con.execute("SELECT COUNT(*) FROM raw.hmda_lar").fetchone()[0]
    col_count = len(con.execute("DESCRIBE raw.hmda_lar").fetchall())
    print(f"\nLoaded raw.hmda_lar: {row_count:,} rows, {col_count} columns")
    print(f"Database written to: {args.db}")
    con.close()


if __name__ == "__main__":
    main()
