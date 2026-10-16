"""NOAA NCEP 颱風路徑（ATCF）→ 專案既有的 paired CSV。

NCEP 的 ens_tracker 在 NOMADS 上發佈各模式追到的熱帶氣旋路徑，格式是 ATCF
a-deck（一行一個 (暴風, 時距, 風圈)），暴風編號直接沿用 JTWC／NHC 的 tcvitals，
所以 WP29 就是 WP292026，不必像 ECMWF 那樣靠位置配對。

兩個模式、四個產品：
    GFS    ens  gefs    ac00 + ap01..ap30   31 成員（GEFS）
    GFS    det  gfs     avno                1 條（GFS 決定報）
    AIGFS  ens  aigefs  a000..a030          31 成員（AIGEFS）
    AIGFS  det  aigfs   agfs                1 條（AIGFS 決定報）

上架時間（實測 2026-10-16 00Z）：AIGFS +4h03、AIGEFS +4h39、GFS +4h45、
GEFS +5h31，都比 WeatherNext（+6h45）與 ECMWF（+6～8h）早。

NOAA 的資料屬美國政府公有領域，網頁仍標示來源。
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from ecmwf_bufr import (FETCH_NO_STORMS, FETCH_OK, FETCH_UNAVAILABLE,
                        _ensemble_mean, _to_paired)

BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/ens_tracker/prod"

# (目錄名稱, 成員檔代號清單) 與 (目錄名稱, 決定報檔代號)
PRODUCTS = {
    "GFS": {"ens": ("gefs", ["ac00"] + [f"ap{i:02d}" for i in range(1, 31)]),
            "det": ("gfs", "avno")},
    "AIGFS": {"ens": ("aigefs", [f"a{i:03d}" for i in range(31)]),
              "det": ("aigfs", "agfs")},
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CopilotDownloader/1.0)"}

# NOMADS 對同一 IP 每分鐘超過約 120 次請求會暫時封鎖。一期系集 31 個檔，
# 第一次執行還要補抓前幾期（forecast._backfill_noaa），間隔 0.6 秒＝每分鐘最多 100 次
REQUEST_GAP_S = 0.6
DOWNLOAD_RETRIES = 3

# 只收這幾個海盆；9x（擾動）與 8x（測試）不是正式編號
_BASINS = {"WP", "CP", "EP"}

_last_request = 0.0


def latest_cycle(now: datetime | None = None) -> datetime:
    """NOAA 可用的最新 cycle：上架最早的 AIGFS 約 +4h，取 4 小時往下取整。

    猜早了只是那期 404、退回前一期，代價是一次目錄列表。
    """
    now = now or datetime.now(timezone.utc)
    adjusted = now - timedelta(hours=4)
    return adjusted.replace(hour=(adjusted.hour // 6) * 6, minute=0, second=0, microsecond=0)


def _dir_url(system: str, cycle: datetime) -> str:
    return f"{BASE_URL}/{system}.{cycle:%Y%m%d}/{cycle:%H}/tctrack/"


def _file_name(code: str, cycle: datetime) -> str:
    return f"{code}.t{cycle:%H}z.cyclone.trackatcfunix"


def _get(url: str) -> requests.Response:
    """GET，請求之間保持間隔；429／5xx 退避重試，其餘照原樣回傳。"""
    global _last_request
    for attempt in range(DOWNLOAD_RETRIES + 1):
        wait = REQUEST_GAP_S - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        resp = requests.get(url, headers=HEADERS, timeout=60)
        if resp.status_code != 429 and resp.status_code < 500:
            return resp
        if attempt < DOWNLOAD_RETRIES:
            print(f"[NOAA] HTTP {resp.status_code}，{10 * (attempt + 1)} 秒後重試: {url}")
            time.sleep(10 * (attempt + 1))
    return resp


def _list_dir(system: str, cycle: datetime) -> set[str] | None:
    """tctrack 目錄裡的檔名；目錄還不存在時回 None。"""
    resp = _get(_dir_url(system, cycle))
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return set(re.findall(r'href="([^"/?]+)"', resp.text))


# ── ATCF 解析 ──────────────────────────────────────────────────────────────

def _latlon(s: str) -> float:
    """'115N' → 11.5、'1531E' → 153.1、'1084W' → -108.4。"""
    s = s.strip()
    v = int(s[:-1]) / 10.0
    return -v if s[-1] in "SW" else v


def parse_atcf(text: str, member: int, year: int) -> pd.DataFrame:
    """ATCF a-deck → long format（track_id, member, step, lat, lon, mslp_hpa, wind_kt）。

    同一時距會因 34／50／64 kt 風圈重複出現好幾列，位置與強度都一樣，取第一列。
    """
    rows, seen = [], set()
    for line in text.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 10 or f[0] not in _BASINS:
            continue
        try:
            num, tau = int(f[1]), int(f[5])
        except ValueError:
            continue
        if num >= 80:
            continue
        tid = f"{f[0]}{num:02d}{year}"
        if (tid, tau) in seen:
            continue
        seen.add((tid, tau))
        try:
            lat, lon = _latlon(f[6]), _latlon(f[7])
        except (ValueError, IndexError):
            continue
        lon = ((lon + 180.0) % 360.0) - 180.0
        wind = float(f[8]) if f[8].lstrip("-").isdigit() and int(f[8]) > 0 else float("nan")
        mslp = float(f[9]) if f[9].lstrip("-").isdigit() and int(f[9]) > 0 else float("nan")
        rows.append({"track_id": tid, "name": tid, "member": member, "step": tau,
                     "lat": lat, "lon": lon, "mslp_hpa": mslp, "wind_kt": wind})
    return pd.DataFrame(rows, columns=["track_id", "name", "member", "step",
                                       "lat", "lon", "mslp_hpa", "wind_kt"])


def _write_csv(df: pd.DataFrame, path: str, source: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(f"# Source: NOAA NCEP ens_tracker ({source})\n")
        f.write("# Licence: U.S. Government work, public domain\n")
        df.to_csv(f, index=False)
    os.replace(tmp, path)
    print(f"[NOAA] 已寫出 {os.path.basename(path)}（{len(df)} 列）")


# ── 對外入口 ───────────────────────────────────────────────────────────────

def fetch_ensemble(model: str, cycle: datetime, cfg: dict,
                   known_ids: set[str] | None = None) -> str:
    """下載某 cycle 的全部成員，寫出系集與平均 CSV。

    以「平均檔（aemn／aimn）已上架」或「全部成員都在」當作這期跑完的記號：成員
    檔是陸續寫進目錄的，太早來會只抓到一半。沒有颱風也照樣寫出（空的）CSV，
    檔案在就代表這期處理過，下一輪不會再花 31 次請求重抓。

    known_ids：只留這些編號（WNC2-r2 判定在西太的颱風），與 ECMWF 的配對範圍一致；
    None 表示不篩。
    """
    system, codes = PRODUCTS[model]["ens"]
    names = _list_dir(system, cycle)
    if names is None:
        return FETCH_UNAVAILABLE
    wanted = [c for c in codes if _file_name(c, cycle) in names]
    mean_code = "aemn" if system == "gefs" else "aimn"
    if len(wanted) < len(codes) and _file_name(mean_code, cycle) not in names:
        print(f"[{model}-ENS] {cycle:%Y-%m-%d %HZ} 成員只上架 {len(wanted)}/{len(codes)}，等下一輪")
        return FETCH_UNAVAILABLE
    if not wanted:
        return FETCH_UNAVAILABLE

    print(f"[{model}-ENS] 下載 {cycle:%Y-%m-%d %HZ} 的 {len(wanted)} 個成員")
    parts = []
    for i, code in enumerate(wanted):
        resp = _get(_dir_url(system, cycle) + _file_name(code, cycle))
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        parts.append(parse_atcf(resp.text, member=i, year=cycle.year))
    tracks = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if not tracks.empty and known_ids is not None:
        tracks = tracks[tracks["track_id"].isin(known_ids)]

    stamp = cycle.strftime("%Y_%m_%dT%H_00")
    prefix = cfg["local_prefix"]
    if tracks.empty:
        tracks = parse_atcf("", 0, cycle.year)
    # 平均自己算（與 ECMWF 同一套「半數成員」截斷），不用 NCEP 的 aemn／aimn，
    # 各模式的平均路徑才是同一個定義
    _write_csv(_to_paired(_ensemble_mean(tracks), cycle),
               os.path.join(cfg["mean_dir"], f"{prefix}_{stamp}_paired.csv"), f"{model} ensemble mean")
    # 平均檔先寫、系集檔後寫：系集檔在才算這期完成（_resolve_cycle 只看它）
    _write_csv(_to_paired(tracks, cycle),
               os.path.join(cfg["ensemble_dir"], f"{prefix}_{stamp}_paired.csv"), f"{model} ensemble")
    return FETCH_OK if not tracks.empty else FETCH_NO_STORMS


def fetch_deterministic(model: str, cycle: datetime, cfg: dict,
                        known_ids: set[str] | None = None) -> bool:
    """下載決定報並寫出 CSV；尚未上架回 False。沒有颱風也寫空檔（代表處理過）。"""
    system, code = PRODUCTS[model]["det"]
    resp = _get(_dir_url(system, cycle) + _file_name(code, cycle))
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    det = parse_atcf(resp.text, member=0, year=cycle.year)
    if known_ids is not None:
        det = det[det["track_id"].isin(known_ids)]
    stamp = cycle.strftime("%Y_%m_%dT%H_00")
    _write_csv(_to_paired(det, cycle),
               os.path.join(cfg["det_dir"], f"{cfg['local_prefix']}_{stamp}_deterministic.csv"),
               f"{model} deterministic")
    return True
