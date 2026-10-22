"""Temporary probes run on the GitHub runner (the dev sandbox cannot reach these hosts)."""
import time, requests
H = {"User-Agent": "Mozilla/5.0 (typhoon-forecast dev probe)"}
for u in ["https://tds.hycom.org/thredds/catalog/FMRC_ESPC-D-V02_t3z/catalog.html",
          "https://tds.hycom.org/thredds/dodsC/FMRC_ESPC-D-V02_t3z/FMRC_ESPC-D-V02_t3z_best.ncd.dds",
          "https://tds.hycom.org/thredds/catalog.html"]:
    try:
        r = requests.get(u, headers=H, timeout=60)
        print("==", u, r.status_code, len(r.content)); print(r.text[:1500])
    except Exception as e:
        print("==", u, "ERROR", e)
try:
    import netCDF4, numpy as np
    url = "https://tds.hycom.org/thredds/dodsC/FMRC_ESPC-D-V02_t3z/FMRC_ESPC-D-V02_t3z_best.ncd"
    t0 = time.time()
    ds = netCDF4.Dataset(url)
    print("vars", list(ds.variables)[:20])
    tv = ds.variables["time"]; print("time", tv.units, netCDF4.num2date(tv[-1], tv.units), len(tv))
    dep = ds.variables["depth"][:]; print("depth", dep[:30])
    lat = ds.variables["lat"][:]; lon = ds.variables["lon"][:]; print("grid", lat[0], lat[-1], lon[0], lon[-1], len(lat), len(lon))
    print("opened in", round(time.time() - t0, 1), "s")
except Exception as e:
    print("netCDF4 ERROR", repr(e))
