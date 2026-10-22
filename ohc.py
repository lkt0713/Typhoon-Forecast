"""海洋熱含量（熱帶氣旋熱潛能，TCHP）：用海洋模式的水溫剖面自己算。

來源優先用 CMEMS（Copernicus Marine，歐盟哥白尼海洋服務）全球 1/12° 每日分析
GLOBAL_ANALYSISFORECAST_PHY_001_024，需要免費帳號，帳密放在環境變數
COPERNICUSMARINE_SERVICE_USERNAME／COPERNICUSMARINE_SERVICE_PASSWORD（GitHub secrets）；
沒有帳密或抓取失敗時改用 HYCOM（不需帳號）。

TCHP 是海面到 26°C 等溫線之間、比 26°C 多出來的熱量：
    TCHP = ρ · cp · ∫ (T − 26°C) dz       （只積 T > 26°C 的部分，單位 kJ/cm²）
颱風底下的暖水層越厚，颱風攪動海水時越不容易把冷水翻上來，越有利增強；一般以約
50 kJ/cm² 當作有利增強的門檻。NOAA 的衛星 TCHP 產品（AOML／CoastWatch）2026 年起
停在 1 月或 9 月，所以改用 HYCOM 自己算，定義與 NOAA 的產品相同。

資料：HYCOM ESPC-D-V02 全球分析（美國海軍，tds.hycom.org，OPeNDAP），1/12° 網格、
40 層深度。只抓西北太平洋、250 m 以淺、每 3 格取 1 格（約 0.24°），一次約 10 MB。
算好的結果存在 OHC_DIR（noaa_ 開頭是為了跟著 GitHub Actions 的下載快取保留），
OHC_MAX_AGE_H 小時內不重算；HYCOM 一天出一次分析。
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import numpy as np

HYCOM_URL = "https://tds.hycom.org/thredds/dodsC/FMRC_ESPC-D-V02_t3z/FMRC_ESPC-D-V02_t3z_best.ncd"
REGION = (100.0, 180.0, 0.0, 50.0)      # lon0, lon1, lat0, lat1
MAX_DEPTH_M = 250.0
STRIDE = 3
OHC_DIR = "noaa_ohc_2026"
OHC_FILE = os.path.join(OHC_DIR, "hycom_tchp.npz")
OHC_MAX_AGE_H = 12
RHO, CP = 1025.0, 3985.0                # 海水密度 kg/m³、比熱 J/(kg·K)
T26 = 26.0


def tchp_from_profiles(temp: np.ndarray, depth: np.ndarray) -> np.ndarray:
    """temp[深度, ...]（°C，陸地／海底以下為 NaN）→ TCHP（kJ/cm²），海面就是 NaN 的格子為 NaN。

    每一層用梯形積分；跨過 26°C 的那一層只積到內插出的 26°C 深度。"""
    a = temp - T26
    heat = np.zeros(temp.shape[1:])
    for k in range(len(depth) - 1):
        a1, a2 = a[k], a[k + 1]
        dz = float(depth[k + 1] - depth[k])
        ok = ~np.isnan(a1) & ~np.isnan(a2)                # 下一層是海底以下（NaN）就不再往下積
        both = ok & (a1 > 0) & (a2 >= 0)
        cross = ok & (a1 > 0) & (a2 < 0)
        with np.errstate(invalid='ignore', divide='ignore'):
            frac = np.where(cross, a1 / (a1 - a2), 0.0)
        heat += np.where(both, (a1 + a2) / 2 * dz, 0.0)
        heat += np.where(cross, a1 * frac * dz / 2, 0.0)
    out = heat * RHO * CP / 1e7                           # J/m² → kJ/cm²
    return np.where(np.isnan(temp[0]), np.nan, out)


CMEMS_DATASET = "cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m"


def _save(when, lat, lon, tchp, source):
    os.makedirs(OHC_DIR, exist_ok=True)
    tmp = OHC_FILE + '.part.npz'
    np.savez_compressed(tmp, time=when, lat=lat, lon=lon, tchp=tchp.astype(np.float32), source=source)
    os.replace(tmp, OHC_FILE)
    return when, lat, lon, tchp, source


def fetch() -> tuple:
    """→ (分析時間 datetime64, lat 1D, lon 1D 0–360, tchp 2D, 來源名稱)；
    沿用 OHC_MAX_AGE_H 小時內算好、且來源相同的結果。"""
    want = 'CMEMS' if os.environ.get('COPERNICUSMARINE_SERVICE_USERNAME') else 'HYCOM'
    if os.path.exists(OHC_FILE) and time.time() - os.path.getmtime(OHC_FILE) < OHC_MAX_AGE_H * 3600:
        d = np.load(OHC_FILE)
        src = str(d['source']) if 'source' in d.files else 'HYCOM'
        if src == want:
            return d['time'], d['lat'], d['lon'], d['tchp'], src
    if want == 'CMEMS':
        try:
            return _save(*_fetch_cmems(), 'CMEMS')
        except Exception as e:
            print(f"[OHC] CMEMS 失敗，改用 HYCOM: {e}")
    return _save(*_fetch_hycom(), 'HYCOM')


def _fetch_cmems() -> tuple:
    """CMEMS 前一天的日平均水溫（最新的分析日）→ TCHP。"""
    import copernicusmarine  # type: ignore
    day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT00:00:00')
    ds = copernicusmarine.open_dataset(
        dataset_id=CMEMS_DATASET, variables=['thetao'],
        minimum_longitude=REGION[0], maximum_longitude=REGION[1],
        minimum_latitude=REGION[2], maximum_latitude=REGION[3],
        minimum_depth=0, maximum_depth=MAX_DEPTH_M, start_datetime=day, end_datetime=day)
    da = ds['thetao'].isel(time=-1).load()
    depth = np.asarray(da['depth'].values, dtype=float)
    temp = np.asarray(da.values, dtype=float)
    # 最淺一層在 0.5 m，補一層 0 m（同溫）讓積分從海面開始
    depth = np.concatenate([[0.0], depth])
    temp = np.concatenate([temp[:1], temp], axis=0)
    lat = np.asarray(da['latitude'].values, dtype=float)
    lon = np.asarray(da['longitude'].values, dtype=float) % 360.0
    when = np.datetime64(str(da['time'].values)[:19], 's')
    return when, lat, lon, tchp_from_profiles(temp, depth)


def _fetch_hycom() -> tuple:
    import netCDF4  # type: ignore
    ds = netCDF4.Dataset(HYCOM_URL)
    try:
        tv = ds.variables['time']
        times = netCDF4.num2date(tv[:], tv.units, only_use_cftime_datetimes=False,
                                 only_use_python_datetimes=True)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        past = [i for i, t in enumerate(times) if t <= now]
        ti = past[-1] if past else 0                       # 不晚於現在的最後一筆＝最新分析
        depth = np.asarray(ds.variables['depth'][:], dtype=float)
        nk = int(np.searchsorted(depth, MAX_DEPTH_M, side='right'))
        lat = np.asarray(ds.variables['lat'][:], dtype=float)
        lon = np.asarray(ds.variables['lon'][:], dtype=float) % 360.0
        j = np.where((lat >= REGION[2]) & (lat <= REGION[3]))[0]
        i = np.where((lon >= REGION[0]) & (lon <= REGION[1]))[0]
        temp = ds.variables['water_temp'][ti, 0:nk, j[0]:j[-1] + 1:STRIDE, i[0]:i[-1] + 1:STRIDE]
        temp = np.ma.filled(np.ma.asarray(temp, dtype=float), np.nan)
        lat_s, lon_s = lat[j[0]:j[-1] + 1:STRIDE], lon[i[0]:i[-1] + 1:STRIDE]
        when = np.datetime64(times[ti].replace(tzinfo=None), 's')
    finally:
        ds.close()
    return when, lat_s, lon_s, tchp_from_profiles(temp, depth[:nk])
