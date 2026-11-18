"""ECMWF AIFS 200–850 hPa 垂直風切：沿 AIFS 決定報（AIFS-single）預報路徑的風切時序。

垂直風切＝高層（200 hPa）與低層（850 hPa）風的向量差。風切大時，颱風上下層的環流
被吹得錯開，暖心結構不易維持，通常難以增強；一般以 10 kt 以下為弱、20 kt 以上為強。
這裡照 SHIPS 等統計強度預報的作法，取颱風中心外 200–800 km 環狀範圍的平均風場相減，
避開颱風本身的環流。

資料來自 ECMWF Open Data（CC BY 4.0）的 AIFS-single，用 ecmwf-opendata 套件依索引檔
只抓 u/v 兩層：每個時距 4 個欄位，全球 0.25°。畫圖在 forecast.py（共用圖面樣式）。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import numpy as np

STEPS = list(range(0, 121, 6))
LEVELS = (200, 850)
RING_KM = (200.0, 800.0)          # 環狀平均的內外半徑
# 裁切範圍（經度 0–360）：只留西北太平洋附近，解碼後省記憶體
CROP = (90.0, 200.0, -10.0, 60.0)
KT_PER_MS = 1.94384


def fetch(cycle: datetime, target: str) -> datetime:
    """下載某一期 AIFS-single 的 200/850 hPa u/v，回傳起報時間（UTC）。"""
    from ecmwf.opendata import Client  # 延後匯入：沒裝套件時 forecast.py 其餘部分照常
    client = Client(source="ecmwf", model="aifs-single")
    cycle = cycle.replace(tzinfo=None)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    client.retrieve(date=cycle.strftime("%Y%m%d"), time=cycle.hour, type="fc", step=STEPS,
                    param=["u", "v"], levelist=list(LEVELS), target=target)
    return cycle.replace(tzinfo=timezone.utc)


def decode(path: str) -> dict:
    """GRIB2 → {step: {'lat': 1D 遞增, 'lon': 1D 0–360 遞增, ('u', 200): 2D, ...}}，已裁切。"""
    import eccodes  # type: ignore
    out: dict = {}
    with open(path, "rb") as f:
        while True:
            h = eccodes.codes_grib_new_from_file(f)
            if h is None:
                break
            try:
                name = eccodes.codes_get(h, "shortName")
                level = int(eccodes.codes_get(h, "level"))
                step = int(eccodes.codes_get(h, "step"))
                ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
                lat0 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees")
                lon0 = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees")
                di = eccodes.codes_get(h, "iDirectionIncrementInDegrees")
                dj = eccodes.codes_get(h, "jDirectionIncrementInDegrees")
                jpos = eccodes.codes_get(h, "jScansPositively")
                vals = eccodes.codes_get_values(h).reshape(nj, ni)
            finally:
                eccodes.codes_release(h)
            lat = lat0 + (1 if jpos else -1) * dj * np.arange(nj)
            lon = (lon0 + di * np.arange(ni)) % 360.0
            jo, io = np.argsort(lat), np.argsort(lon)
            lat, lon, vals = lat[jo], lon[io], vals[jo][:, io]
            jm = (lat >= CROP[2]) & (lat <= CROP[3])
            im = (lon >= CROP[0]) & (lon <= CROP[1])
            d = out.setdefault(step, {'lat': lat[jm], 'lon': lon[im]})
            d[(name, level)] = vals[np.ix_(jm, im)].astype(np.float32)
    need = [(p, lv) for p in ("u", "v") for lv in LEVELS]
    return {s: d for s, d in out.items() if all(k in d for k in need)}


def ring_shear(f: dict, lat: float, lon: float) -> tuple[float, float] | None:
    """(風切大小 kt, 風切向量指向的方位角 °，0＝北、90＝東)；颱風在裁切範圍外回 None。"""
    lon = lon % 360.0
    la, lo = f['lat'], f['lon']
    if not (la[0] <= lat <= la[-1] and lo[0] <= lon <= lo[-1]):
        return None
    LA, LO = np.meshgrid(la, lo, indexing='ij')
    dy = (LA - lat) * 111.2
    dx = (LO - lon) * 111.2 * np.cos(np.radians(lat))
    r = np.hypot(dx, dy)
    m = (r >= RING_KM[0]) & (r <= RING_KM[1])
    w = np.cos(np.radians(LA[m]))                 # 高緯網格較小，用 cos(lat) 加權
    du = np.average(f[('u', 200)][m] - f[('u', 850)][m], weights=w)
    dv = np.average(f[('v', 200)][m] - f[('v', 850)][m], weights=w)
    return float(np.hypot(du, dv) * KT_PER_MS), float(np.degrees(np.arctan2(du, dv)) % 360)
