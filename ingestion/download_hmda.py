"""
Download HMDA Loan/Application Register (LAR) data from the CFPB
Data Browser API (public, no API key required).

Docs: https://ffiec.cfpb.gov/documentation/api/data-browser-api/

Usage:
    python ingestion/download_hmda.py --states CA,TX --years 2022,2023
    python ingestion/download_hmda.py --states CA --years 2023 --actions 1,3
"""
import argparse
import os
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://ffiec.cfpb.gov/v2/data-browser-api/view/csv"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

# action_taken codes we care about by default:
# 1 = Loan originated, 3 = Application denied
# (2, 4, 5, 6, 7, 8 = approved-not-accepted, withdrawn, closed-incomplete,
#  purchased loan, preapproval-denied, preapproval-approved-not-accepted)
DEFAULT_ACTIONS = "1,3"


def download_state_year(state: str, year: str, actions: str, timeout: int = 300) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"hmda_{state}_{year}.csv"

    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  [skip] {out_path.name} already exists")
        return out_path

    params = {
        "states": state,
        "years": year,
        "actions_taken": actions,
    }
    print(f"  [fetch] state={state} year={year} actions={actions} ...")
    with requests.get(BASE_URL, params=params, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"  [done] wrote {out_path.name} ({size_mb:.1f} MB)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Download HMDA LAR data from CFPB")
    parser.add_argument("--states", required=True, help="Comma-separated state codes, e.g. CA,TX")
    parser.add_argument("--years", required=True, help="Comma-separated years, e.g. 2022,2023")
    parser.add_argument("--actions", default=DEFAULT_ACTIONS,
                         help="Comma-separated action_taken codes (default: 1,3 = originated/denied)")
    args = parser.parse_args()

    states = [s.strip().upper() for s in args.states.split(",")]
    years = [y.strip() for y in args.years.split(",")]

    downloaded = []
    for year in years:
        for state in states:
            try:
                path = download_state_year(state, year, args.actions)
                downloaded.append(path)
            except requests.HTTPError as e:
                print(f"  [error] {state} {year}: {e}", file=sys.stderr)
            time.sleep(1)  # be polite to the API

    print(f"\nDownloaded {len(downloaded)} file(s) to {RAW_DIR}")


if __name__ == "__main__":
    main()
