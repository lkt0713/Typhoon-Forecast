"""Temporary probes run on the GitHub runner (the dev sandbox cannot reach these hosts)."""
import re, requests
H = {"User-Agent": "Mozilla/5.0 (typhoon-forecast dev probe)"}
base = "https://coastwatch.noaa.gov/erddap"
for ds in ["noaacwOHC14np", "noaacwOHCnp", "noaacwOHC14na"]:
    for ext in ("info/{}/index.json",):
        r = requests.get(f"{base}/" + ext.format(ds), headers=H, timeout=60)
        print("==", ds, r.status_code, r.text[:200].replace("\n", " ") if not r.ok else "")
        if r.ok:
            for row in r.json()["table"]["rows"]:
                if row[0] in ("dimension", "variable") or row[2] in ("time_coverage_end", "geospatial_lon_min", "geospatial_lon_max", "geospatial_lat_min", "geospatial_lat_max", "units"):
                    print("   ", row[1], row[2], row[4][:100])
r = requests.get(f"{base}/griddap/index.json?page=1&itemsPerPage=1000", headers=H, timeout=60)
print("griddap list", r.status_code)
if r.ok:
    t = r.json()["table"]; ci = t["columnNames"].index("Dataset ID"); ti = t["columnNames"].index("Title")
    for row in t["rows"]:
        if "OHC" in row[ci].upper() or "heat" in row[ti].lower():
            print("   ", row[ci], "|", row[ti])
for u in ["https://coastwatch.noaa.gov/thredds/socd/coastwatch/catalog_coastwatch_ohc.html",
          "https://coastwatch.noaa.gov/thredds/catalog/socd/coastwatch/catalog_coastwatch_ohc.xml"]:
    r = requests.get(u, headers=H, timeout=60)
    print("==", u, r.status_code)
    if r.ok:
        print("   ", sorted(set(re.findall(r'(?:href|xlink:href)="([^"]+)"', r.text)))[:40])
