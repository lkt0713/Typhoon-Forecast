"""海洋熱含量：NOAA AOML 每日的熱帶氣旋熱潛能（Tropical Cyclone Heat Potential, TCHP）。

TCHP 是海面到 26°C 等溫線深度之間、比 26°C 多出來的熱量（kJ/cm²）。颱風底下的
暖水層越厚，颱風攪動海水時越不容易把冷水翻上來，越有利增強；一般以約 50 kJ/cm²
當作有利增強的門檻。資料由衛星海溫與海面高度推算，0.25° 網格，每天一筆。

從 AOML 的 ERDDAP 用 griddap 只抓西北太平洋、最新一天的資料（NetCDF3，scipy 就能讀）。
下載檔存在 OHC_DIR（檔名含 noaa_ 開頭，會跟著 GitHub Actions 的下載快取保留），
OHC_MAX_AGE_H 小時內不重抓。
"""
from __future__ import annotations

import os
import time

import numpy as np
import requests

SERVERS = [
    ("https://erddap.aoml.noaa.gov/hdb/erddap", "TCHP"),
    ("https://cwcgom.aoml.noaa.gov/erddap", "aomlTCHP"),
]
VAR = "Tropical_Cyclone_Heat_Potential"
REGION = (100.0, 180.0, 0.0, 50.0)      # lon0, lon1, lat0, lat1
OHC_DIR = "noaa_ohc_2026"
OHC_FILE = os.path.join(OHC_DIR, "tchp_latest.nc")
OHC_MAX_AGE_H = 6
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TyphoonForecastSite/1.0)"}


def _urls():
    lo0, lo1, la0, la1 = REGION
    for base, ds in SERVERS:
        # 緯度在資料集裡可能是遞減排列，兩種順序都試
        for la in (f"({la0}):({la1})", f"({la1}):({la0})"):
            yield f"{base}/griddap/{ds}.nc?{VAR}[(last)][{la}][({lo0}):({lo1})]"


def fetch() -> str:
    """下載（或沿用）最新一天的 TCHP，回傳檔案路徑。"""
    if os.path.exists(OHC_FILE) and time.time() - os.path.getmtime(OHC_FILE) < OHC_MAX_AGE_H * 3600:
        return OHC_FILE
    os.makedirs(OHC_DIR, exist_ok=True)
    errors = []
    for url in _urls():
        try:
            r = requests.get(url, headers=HEADERS, timeout=90)
            if r.status_code != 200 or not r.content.startswith(b"CDF"):
                errors.append(f"{r.status_code} {url.split('?')[0]}")
                continue
            tmp = OHC_FILE + ".part"
            with open(tmp, "wb") as f:
                f.write(r.content)
            os.replace(tmp, OHC_FILE)
            return OHC_FILE
        except Exception as e:
            errors.append(f"{type(e).__name__} {url.split('?')[0]}")
    if os.path.exists(OHC_FILE):          # 抓不到新的就沿用舊檔
        return OHC_FILE
    raise RuntimeError("TCHP 下載失敗: " + "; ".join(errors))


def load(path: str):
    """→ (date: datetime64, lat 1D 遞增, lon 1D 0–360 遞增, tchp 2D；陸地與缺值為 NaN)。"""
    from scipy.io import netcdf_file
    with netcdf_file(path, "r", mmap=False) as nc:
        v = nc.variables[VAR]
        data = np.array(v[:], dtype=float)
        fill = [getattr(v, a) for a in ("_FillValue", "missing_value") if hasattr(v, a)]
        lat = np.array(nc.variables["latitude"][:], dtype=float)
        lon = np.array(nc.variables["longitude"][:], dtype=float)
        t = np.array(nc.variables["time"][:], dtype=float)
    data = data.reshape(data.shape[-2:]) if data.ndim > 2 else data
    for fv in fill:
        data[data == fv] = np.nan
    data[(data < 0) | (data > 1000)] = np.nan
    lon = lon % 360.0
    jo, io = np.argsort(lat), np.argsort(lon)
    date = np.datetime64(int(t[-1]), "s")          # ERDDAP 的 time 是 1970 起算的秒數
    return date, lat[jo], lon[io], data[jo][:, io]
