"""ECMWF Open Data 500 hPa 高度場與風場：駛流場圖的資料來源。

颱風大致順著周圍的中層氣流走，500 hPa 上 5880 gpm 等高線常被用來描述太平洋
高壓的範圍：颱風多沿著它的外緣移動，高壓西伸時偏西走、東退時容易轉北。
這裡只負責下載與解碼（畫圖在 forecast.py，才能共用底圖樣式）。

資料來自 ECMWF Open Data（CC BY 4.0）的 AIFS-single（ECMWF 的 AI 模式決定報），用
ecmwf-opendata 套件依索引檔只抓需要的欄位：每個時距的 gh/u/v 三個 500 hPa 欄位，
全球 0.25° 約 0.5 MB 一個。AIFS 每天四期都跑到 360 小時，所以每期都有 0–120 h。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import numpy as np

STEPS = [0, 24, 48, 72, 96, 120]
# 裁切範圍（經度 0–360）：比畫圖範圍大一點，流線在邊緣才不會斷得太突然
CROP = (90.0, 190.0, -10.0, 60.0)


def steps_for(cycle: datetime) -> list[int]:
    return STEPS


def fetch(cycle: datetime | None, target: str) -> datetime:
    """下載某一期（None＝最新一期）AIFS-single 的 500 hPa gh/u/v，回傳實際的起報時間（UTC）。"""
    from ecmwf.opendata import Client  # 延後匯入：沒裝套件時 forecast.py 其餘部分照常
    client = Client(source="ecmwf", model="aifs-single")
    kw = dict(type="fc", param=["gh", "u", "v"], levelist=500)
    if cycle is None:
        cycle = client.latest(step=0, **kw)
    cycle = cycle.replace(tzinfo=None)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    client.retrieve(date=cycle.strftime("%Y%m%d"), time=cycle.hour, step=steps_for(cycle),
                    target=target, **kw)
    return cycle.replace(tzinfo=timezone.utc)


def decode(path: str) -> dict:
    """GRIB2 → {step: {'gh': 2D, 'u': 2D, 'v': 2D, 'lat': 1D（遞增）, 'lon': 1D（0–360 遞增）}}，已裁切。"""
    import eccodes  # type: ignore
    out: dict = {}
    with open(path, "rb") as f:
        while True:
            h = eccodes.codes_grib_new_from_file(f)
            if h is None:
                break
            try:
                name = eccodes.codes_get(h, "shortName")
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
            d[name] = vals[np.ix_(jm, im)]
    return {s: d for s, d in out.items() if all(k in d for k in ("gh", "u", "v"))}
