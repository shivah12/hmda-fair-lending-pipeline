"""
Streams large national HMDA LAR CSVs into year-partitioned Parquet using
DuckDB's out-of-core engine -- handles multi-GB files without loading them
fully into memory, and produces a compressed, columnar raw layer that's
fast to re-read on every subsequent dbt/analysis run (instead of re-parsing
multi-GB CSV text every time).

Handles the well-known CFPB gotcha where national LAR exports are
pipe-delimited despite a .csv extension -- delimiter is auto-detected.

Usage:
    python ingestion/build_raw.py --input-dir /path/to/hmda_csvs --db data/hmda.duckdb

Expects filenames containing a 4-digit year, e.g. 2022_public_lar_csv.csv,
hmda_2023_lar.csv, etc. -- the year is extracted via regex, not position.
"""
import argparse
import re
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "hmda.duckdb"
DEFAULT_PARQUET_DIR = ROOT / "data" / "parquet"

YEAR_RE = re.compile(r"(20\d{2})")


def sniff_delimiter(path: Path) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        first_line = f.readline()
    counts = {d: first_line.count(d) for d in ["|", ",", "\t"]}
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        raise ValueError(f"Could not detect delimiter for {path}")
    return best


def extract_year(path: Path) -> str:
    match = YEAR_RE.search(path.name)
    if not match:
        raise ValueError(
            f"Could not find a 4-digit year in filename: {path.name}. "
            "Rename the file to include the activity year, e.g. 2022_public_lar.csv"
        )
    return match.group(1)


def convert_file(con: duckdb.DuckDBPyConnection, csv_path: Path, parquet_dir: Path) -> Path:
    year = extract_year(csv_path)
    delim = sniff_delimiter(csv_path)
    out_dir = parquet_dir / f"year={year}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "data.parquet"

    print(f"  [{csv_path.name}] year={year} delimiter={repr(delim)}")
    print(f"    streaming CSV -> Parquet (out-of-core, this can take a few minutes)...")

    # all_varchar=true keeps this step lossless -- dbt staging does the typing.
    # COPY streams row groups to disk rather than materializing the full
    # result in memory, so this scales regardless of available RAM (DuckDB
    # will spill to the configured temp_directory if needed).
    con.execute(f"""
        COPY (
            SELECT *
            FROM read_csv(
                '{csv_path.as_posix()}',
                delim = '{delim}',
                header = true,
                all_varchar = true,
                sample_size = -1,
                ignore_errors = false
            )
        ) TO '{out_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    row_count = con.execute(f"SELECT COUNT(*) FROM read_parquet('{out_path.as_posix()}')").fetchone()[0]
    size_gb = out_path.stat().st_size / (1024 ** 3)
    print(f"    -> {row_count:,} rows written, {size_gb:.2f} GB Parquet ({out_path})")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Convert raw HMDA CSVs to partitioned Parquet")
    parser.add_argument("--input-dir", required=True, help="Directory containing the raw HMDA CSV files")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--parquet-dir", default=str(DEFAULT_PARQUET_DIR))
    parser.add_argument("--memory-limit", default="4GB", help="DuckDB memory_limit pragma")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    csv_files = sorted(input_dir.glob("*.csv"))
    if not csv_files:
        raise SystemExit(f"No .csv files found in {input_dir}")

    print(f"Found {len(csv_files)} file(s) in {input_dir}:")
    for f in csv_files:
        print(f"  - {f.name} ({f.stat().st_size / (1024**3):.2f} GB)")

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(args.db).parent / "duckdb_tmp"
    tmp_dir.mkdir(exist_ok=True)

    con = duckdb.connect(args.db)
    # Bound memory usage and let DuckDB spill to disk for anything larger --
    # this is what makes multi-GB CSVs safe to process on a laptop.
    con.execute(f"SET memory_limit = '{args.memory_limit}'")
    con.execute(f"SET threads = {args.threads}")
    con.execute(f"SET temp_directory = '{tmp_dir.as_posix()}'")

    print()
    for csv_path in csv_files:
        convert_file(con, csv_path, Path(args.parquet_dir))

    # raw.hmda_lar becomes a view over the partitioned Parquet dataset --
    # hive_partitioning picks up `year=YYYY` from the directory structure
    # automatically as an `activity_year_partition` style column.
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute(f"""
        CREATE OR REPLACE VIEW raw.hmda_lar AS
        SELECT *
        FROM read_parquet('{Path(args.parquet_dir).as_posix()}/year=*/data.parquet', hive_partitioning = true)
    """)

    total_rows = con.execute("SELECT COUNT(*) FROM raw.hmda_lar").fetchone()[0]
    print(f"\nraw.hmda_lar view created over partitioned Parquet: {total_rows:,} total rows")
    print(f"Database: {args.db}")
    con.close()


if __name__ == "__main__":
    main()
