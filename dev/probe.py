"""Temporary probe: CWA dataset structure once CWA_API_KEY exists."""
import os, requests
key = os.environ.get("CWA_API_KEY", "")
print("CWA key present:", bool(key))
if key:
    r = requests.get("https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005",
                     params={"Authorization": key, "format": "JSON"}, timeout=60)
    print(r.status_code); print(r.text[:6000])
