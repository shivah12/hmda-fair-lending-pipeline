"""
Quick, cheap inspection of a raw HMDA LAR file before committing to a full
load: detects the delimiter, prints the header, column count, and an
estimated row count -- without reading the whole multi-GB file into memory.

Usage:
    python ingestion/inspect_source.py /path/to/2022_public_lar_csv.csv
"""
import argparse
import os
import sys


def sniff_delimiter(sample: str) -> str:
    candidates = ["|", ",", "\t"]
    counts = {d: sample.split("\n")[0].count(d) for d in candidates}
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        raise ValueError("Could not detect a delimiter -- inspect the file manually.")
    return best


def estimate_row_count(path: str, header_bytes: int, sample_lines: int) -> int:
    file_size = os.path.getsize(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        sample = f.read(1_000_000)
    lines_in_sample = sample.count("\n")
    bytes_per_line = len(sample.encode("utf-8")) / max(lines_in_sample, 1)
    return int(file_size / bytes_per_line)


def main():
    parser = argparse.ArgumentParser(description="Inspect a raw HMDA LAR file")
    parser.add_argument("path")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        sys.exit(f"File not found: {args.path}")

    file_size_gb = os.path.getsize(args.path) / (1024 ** 3)

    with open(args.path, "r", encoding="utf-8", errors="replace") as f:
        sample = f.read(1_000_000)

    delim = sniff_delimiter(sample)
    header = sample.split("\n")[0]
    columns = header.split(delim)
    est_rows = estimate_row_count(args.path, len(header), 1000)

    print(f"File:              {args.path}")
    print(f"Size:              {file_size_gb:.2f} GB")
    print(f"Detected delimiter: {repr(delim)}")
    print(f"Column count:      {len(columns)}")
    print(f"Estimated rows:    ~{est_rows:,}")
    print(f"\nFirst 10 columns:")
    for c in columns[:10]:
        print(f"  - {c}")
    print(f"\nFirst data row (truncated):")
    print(sample.split("\n")[1][:300])


if __name__ == "__main__":
    main()
