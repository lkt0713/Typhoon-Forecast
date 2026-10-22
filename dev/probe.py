"""Temporary probes run on the GitHub runner (the dev sandbox cannot reach these hosts)."""
import os, sys, requests
sys.path.insert(0, os.getcwd())
H = {"User-Agent": "Mozilla/5.0 (typhoon-forecast dev probe)"}
base = "https://erddap.aoml.noaa.gov/hdb/erddap"
r = requests.get(f"{base}/info/UOHC_2026/index.json", headers=H, timeout=60)
print(r.status_code)
for row in r.json()["table"]["rows"]:
    if row[0] in ("dimension", "variable") or row[2] in ("time_coverage_end", "time_coverage_start", "units", "actual_range", "long_name", "summary", "title", "_FillValue", "missing_value"):
        print("   ", row)
