"""Temporary probes run on the GitHub runner (the dev sandbox cannot reach these hosts)."""
import json, os, sys, re, requests
sys.path.insert(0, os.getcwd())
H = {"User-Agent": "Mozilla/5.0 (typhoon-forecast dev probe)"}

def get(url, **kw):
    try:
        r = requests.get(url, headers=H, timeout=60, **kw)
        print(f"== {url} -> {r.status_code} {len(r.content)} bytes")
        return r
    except Exception as e:
        print(f"== {url} -> ERROR {e}")

for base, ds in [("https://erddap.aoml.noaa.gov/hdb/erddap", "TCHP"), ("https://cwcgom.aoml.noaa.gov/erddap", "aomlTCHP")]:
    r = get(f"{base}/info/{ds}/index.json")
    if r is not None and r.ok:
        for row in r.json()["table"]["rows"]:
            if row[2] in ("time_coverage_end", "time_coverage_start", "units", "actual_range") or row[1] == "time":
                print("   ", row)
    r = get(f"{base}/search/index.json?searchFor=heat%20potential&itemsPerPage=50")
    if r is not None and r.ok:
        t = r.json()["table"]; ci = t["columnNames"].index("Dataset ID"); ti = t["columnNames"].index("Title")
        for row in t["rows"]:
            print("   dataset:", row[ci], "|", row[ti])
r = get("https://erddap.aoml.noaa.gov/hdb/erddap/files/TCHP/2026/")
if r is not None and r.ok:
    names = re.findall(r'href="([^"?/][^"]*)"', r.text)
    print("   files:", len(names), names[:3], names[-6:])
for u in ["https://www.aoml.noaa.gov/phod/cyclone/data/", "https://cwcgom.aoml.noaa.gov/erddap/files/aomlTCHP/"]:
    r = get(u)
    if r is not None and r.ok:
        names = re.findall(r'href="([^"?/][^"]*)"', r.text)
        print("   links:", names[:10], names[-10:])
# CoastWatch / NESDIS ocean heat content
r = get("https://coastwatch.noaa.gov/erddap/search/index.json?searchFor=ocean%20heat%20content&itemsPerPage=50")
if r is not None and r.ok:
    t = r.json()["table"]; ci = t["columnNames"].index("Dataset ID"); ti = t["columnNames"].index("Title")
    for row in t["rows"]:
        print("   coastwatch:", row[ci], "|", row[ti])
r = get("https://coastwatch.pfeg.noaa.gov/erddap/search/index.json?searchFor=heat%20potential&itemsPerPage=50")
if r is not None and r.ok:
    t = r.json()["table"]; ci = t["columnNames"].index("Dataset ID"); ti = t["columnNames"].index("Title")
    for row in t["rows"]:
        print("   pfeg:", row[ci], "|", row[ti])
