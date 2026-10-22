"""Temporary probes run on the GitHub runner (the dev sandbox cannot reach these hosts)."""
import json, os, sys, requests
sys.path.insert(0, os.getcwd())

H = {"User-Agent": "Mozilla/5.0 (typhoon-forecast dev probe)"}


def show(url, n=1500, **kw):
    try:
        r = requests.get(url, headers=H, timeout=30, **kw)
        print(f"== {url.split('?')[0]} -> {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes")
        print(r.text[:n])
        return r
    except Exception as e:
        print(f"== {url.split('?')[0]} -> ERROR {e}")


print("######## JMA")
r = show("https://www.jma.go.jp/bosai/typhoon/data/targetTc.json")
try:
    tcs = r.json()
    for tc in tcs[:3]:
        tid = tc.get("tropicalCyclone") if isinstance(tc, dict) else tc
        for f in ("specifications.json", "forecast.json"):
            show(f"https://www.jma.go.jp/bosai/typhoon/data/{tid}/{f}", 3000)
except Exception as e:
    print("JMA parse", e)

print("######## CWA")
key = os.environ.get("CWA_API_KEY", "")
print("key present:", bool(key))
if key:
    r = show(f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005?Authorization={key}&format=JSON", 4000)

print("######## ECMWF open data")
try:
    from ecmwf.opendata import Client
    c = Client(source="ecmwf")
    for model in ("ifs", "aifs-single"):
        try:
            res = c.latest(type="fc", step=24, param="gh", levelist=500, model=model)
            print(model, "latest", res)
        except Exception as e:
            print(model, "latest ERROR", e)
    import time
    t = time.time()
    res = c.retrieve(type="fc", step=[0, 24], param=["gh", "u", "v"], levelist=500, target="/tmp/z500.grib2")
    print("retrieved", res.datetime, os.path.getsize("/tmp/z500.grib2"), "bytes in", round(time.time() - t, 1), "s")
    import eccodes
    with open("/tmp/z500.grib2", "rb") as f:
        while True:
            h = eccodes.codes_grib_new_from_file(f)
            if h is None:
                break
            print(" ", eccodes.codes_get(h, "shortName"), eccodes.codes_get(h, "level"), eccodes.codes_get(h, "step"),
                  eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj"))
            eccodes.codes_release(h)
except Exception as e:
    print("ECMWF ERROR", repr(e))

print("######## AOML TCHP")
for u in ["https://erddap.aoml.noaa.gov/hdb/erddap/info/TCHP/index.json",
          "https://cwcgom.aoml.noaa.gov/erddap/info/aomlTCHP/index.json"]:
    r = show(u, 600)
import ohc
try:
    p = ohc.fetch(); d, la, lo, t = ohc.load(p)
    import numpy as np
    print("TCHP", d, la.min(), la.max(), lo.min(), lo.max(), t.shape, np.nanmin(t), np.nanmax(t), os.path.getsize(p))
except Exception as e:
    print("TCHP ERROR", repr(e))
