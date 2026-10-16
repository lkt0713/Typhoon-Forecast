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

GEFS 另有生成追蹤（genesis/ 目錄，各成員 storms.*.atcf_gen.altg.*），連模式自己
生出來的擾動一起追，只到 120h，用來畫潛勢總覽；AIGEFS 沒有這個產品。

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
    """tctrack 目錄裡的檔名；目錄還不存在時回 None。

    NOMADS 對還沒建立的目錄回 403 而不是 404（實測 2026-10-16 17:00 的 gefs 12Z），
    兩者都當成尚未上架。"""
    resp = _get(_dir_url(system, cycle))
    if resp.status_code in (403, 404):
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

    要等全部成員都在才收：成員檔是陸續寫進目錄的，NCEP 的平均檔不能當完成記號
    （實測 GEFS 的 aemn 05:29 就寫出，ap06 到 05:30 才有）。起報 7 小時後還缺的
    成員視為這期就是沒有（正常 +5h31 前全到），收下現有的。沒有颱風也照樣寫出（空的）CSV，
    檔案在就代表這期處理過，下一輪不會再花 31 次請求重抓。

    known_ids：只留這些編號（WNC2-r2 判定在西太的颱風），與 ECMWF 的配對範圍一致；
    None 表示不篩。
    """
    system, codes = PRODUCTS[model]["ens"]
    names = _list_dir(system, cycle)
    if names is None:
        return FETCH_UNAVAILABLE
    wanted = [c for c in codes if _file_name(c, cycle) in names]
    late = datetime.now(timezone.utc) - cycle > timedelta(hours=7)
    if len(wanted) < len(codes) and not late:
        print(f"[{model}-ENS] {cycle:%Y-%m-%d %HZ} 成員只上架 {len(wanted)}/{len(codes)}，等下一輪")
        return FETCH_UNAVAILABLE
    if not wanted:
        return FETCH_UNAVAILABLE

    print(f"[{model}-ENS] 下載 {cycle:%Y-%m-%d %HZ} 的 {len(wanted)} 個成員")
    parts = []
    for i, code in enumerate(wanted):
        resp = _get(_dir_url(system, cycle) + _file_name(code, cycle))
        if resp.status_code in (403, 404):
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
    if resp.status_code in (403, 404):
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


# ── 生成潛勢（只有 GEFS）─────────────────────────────────────────────────

GENESIS = {"GFS": ("gefs", ["ac00"] + [f"ap{i:02d}" for i in range(1, 31)])}


def parse_atcf_gen(text: str, member: int, year: int) -> pd.DataFrame:
    """生成追蹤的 ATCF 變體 → long format。

    比一般 a-deck 多一欄（第 3 欄是擾動的識別字串），編號欄有兩種：已命名的颱風
    是 'WP, 29W'，模式自己生成的擾動是 'TG, 0018'（每個成員各自編號）。前者對回
    JTWC 編號，後者沿用 TG 編號當 track_id，與 Weather Lab 潛勢檔的做法一致。
    """
    rows, seen = [], set()
    for line in text.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 11:
            continue
        basin, sid = f[0], f[1]
        try:
            tau = int(f[6])
        except ValueError:
            continue
        if basin == "TG":
            tid = f"TG{sid}"
        else:
            num = re.match(r"(\d+)", sid)
            if not num:
                continue
            tid = f"{basin}{int(num.group(1)):02d}{year}"
        if (tid, tau) in seen:
            continue
        seen.add((tid, tau))
        try:
            lat, lon = _latlon(f[7]), _latlon(f[8])
        except (ValueError, IndexError):
            continue
        lon = ((lon + 180.0) % 360.0) - 180.0
        wind = float(f[9]) if f[9].lstrip("-").isdigit() and int(f[9]) > 0 else float("nan")
        mslp = float(f[10]) if f[10].lstrip("-").isdigit() and int(f[10]) > 0 else float("nan")
        rows.append({"track_id": tid, "name": tid, "member": member, "step": tau,
                     "lat": lat, "lon": lon, "mslp_hpa": mslp, "wind_kt": wind})
    return pd.DataFrame(rows, columns=["track_id", "name", "member", "step",
                                       "lat", "lon", "mslp_hpa", "wind_kt"])


def _drop_land_genesis(tracks: pd.DataFrame) -> pd.DataFrame:
    """去掉起點在陸地上的 TG 擾動。

    NCEP 的生成追蹤連陸上的熱低壓也追（實測 2026-10-16 06Z 四川盆地一團 >1000 hPa
    的低壓），那不是熱帶擾動；Weather Lab 的潛勢檔沒有這種東西。已命名的颱風不動。
    """
    if tracks.empty:
        return tracks
    try:
        import cartopy.io.shapereader as shpreader
        from shapely.geometry import Point
        from shapely.ops import unary_union
        from shapely.prepared import prep
        land = prep(unary_union(list(shpreader.Reader(
            shpreader.natural_earth("50m", "physical", "land")).geometries())))
    except Exception as e:
        print(f"[NOAA-GENESIS] 讀不到陸地範圍，不過濾: {e}")
        return tracks
    keys = ["track_id", "member"]
    first = tracks.sort_values("step").groupby(keys).first().reset_index()
    on_land = {(r.track_id, r.member) for r in first.itertuples()
               if r.track_id.startswith("TG") and land.contains(Point(r.lon, r.lat))}
    if not on_land:
        return tracks
    print(f"[NOAA-GENESIS] 去掉 {len(on_land)} 條起點在陸地上的擾動")
    mask = [(t, m) not in on_land for t, m in zip(tracks["track_id"], tracks["member"])]
    return tracks[mask]


def fetch_genesis(model: str, cycle: datetime, cfg: dict) -> bool:
    """下載某 cycle 全部成員的生成追蹤，寫出潛勢 CSV；尚未上架（或不齊）回 False。"""
    if model not in GENESIS or not cfg.get("cyc_dir"):
        return False
    system, codes = GENESIS[model]
    url = f"{BASE_URL}/{system}.{cycle:%Y%m%d}/{cycle:%H}/genesis/"
    resp = _get(url)
    if resp.status_code in (403, 404):
        return False
    resp.raise_for_status()
    names = set(re.findall(r'href="([^"/?]+)"', resp.text))
    fname = lambda c: f"storms.{c}.atcf_gen.altg.{cycle:%Y%m%d%H}"
    wanted = [c for c in codes if fname(c) in names]
    if len(wanted) < len(codes):
        print(f"[{model}-GENESIS] {cycle:%Y-%m-%d %HZ} 只上架 {len(wanted)}/{len(codes)}，等下一輪")
        return False
    parts = []
    for i, code in enumerate(wanted):
        r = _get(url + fname(code))
        if r.status_code in (403, 404):
            continue
        r.raise_for_status()
        parts.append(parse_atcf_gen(r.text, member=i, year=cycle.year))
    tracks = pd.concat(parts, ignore_index=True) if parts else parse_atcf_gen("", 0, cycle.year)
    tracks = _drop_land_genesis(tracks)
    stamp = cycle.strftime("%Y_%m_%dT%H_00")
    _write_csv(_to_paired(tracks, cycle),
               os.path.join(cfg["cyc_dir"], f"{cfg['local_prefix']}_{stamp}_cyclogenesis.csv"),
               f"{model} genesis")
    return True
