"""Temporary probes run on the GitHub runner (the dev sandbox cannot reach these hosts)."""
import os, sys, requests
H = {"User-Agent": "Mozilla/5.0 (typhoon-forecast dev probe)"}
base = "https://coastwatch.noaa.gov/erddap"
r = requests.get(f"{base}/search/index.json?searchFor=noaacwOHC&itemsPerPage=100", headers=H, timeout=60)
print("search", r.status_code)
ids = []
if r.ok:
    t = r.json()["table"]; ci = t["columnNames"].index("Dataset ID"); ti = t["columnNames"].index("Title")
    for row in t["rows"]:
        print("   ", row[ci], "|", row[ti]); ids.append(row[ci])
for ds in ids or ["noaacwOHCna", "noaacwOHCsp", "noaacwOHCnp", "noaacwOHCwp"]:
    r = requests.get(f"{base}/info/{ds}/index.json", headers=H, timeout=60)
    print("==", ds, r.status_code)
    if r.ok:
        for row in r.json()["table"]["rows"]:
            if row[0] in ("dimension", "variable") or row[2] in ("time_coverage_end", "geospatial_lon_min", "geospatial_lon_max", "geospatial_lat_min", "geospatial_lat_max"):
                print("   ", row[:2], row[2], row[4][:120])
