"""ECMWF Open Data 熱帶氣旋路徑 BUFR → 專案既有的 paired CSV。

Weather Lab 的下載端點只提供 DeepMind 自家的模式（實測 ENS／ECMWF／IFS／EPS
一律 404），所以 ECMWF 與 AIFS 得走另一條管道：ECMWF Open Data 在每個 cycle
的 `enfo`／`oper` 目錄下發佈 `-tf.bufr`，內含該次預報追到的所有熱帶氣旋路徑。

本模組把那份 BUFR 轉成 forecast.py 既有的 paired CSV 欄位，讓下游
（load_forecast_dataframe、繪圖、動畫、網頁）完全不必知道資料來自哪裡。

四個產品：
    IFS  ens  ifs/0p25/enfo         51 成員（傳統 IFS 系集）
    IFS  det  ifs/0p25/oper         1 條（HRES 決定報）
    AIFS ens  aifs-ens/0p25/enfo    52 成員
    AIFS det  aifs-single/0p25/oper 1 條

資料授權為 ECMWF general licence（CC-BY 性質），與 WeatherNext 的 terms-of-use
不同，網頁端須另外標示來源。
"""

from __future__ import annotations

import os
import re
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

BASE_URL = "https://data.ecmwf.int/forecasts"

# 每個模式的 (系集, 決定報) 路徑片段。第二個元素是檔名裡的 stream 代號。
PRODUCTS = {
    "IFS":  {"ens": ("ifs/0p25/enfo", "enfo"),      "det": ("ifs/0p25/oper", "oper")},
    "AIFS": {"ens": ("aifs-ens/0p25/enfo", "enfo"), "det": ("aifs-single/0p25/oper", "oper")},
}

# ECMWF 的暴風編號與 JTWC 不同調 —— 實測 2026-09-05 00Z，JTWC 的
# 「TROPICAL DEPRESSION 22W (KROVANH)」在 ECMWF 是 28W，但同一份檔案裡的
# 23W 又剛好對上 WP232026。編號不可信，只能用位置對應（見 _match_track_ids）。
MATCH_RADIUS_KM = 250.0

# 平均路徑截止門檻：與 forecast.py 的 _compute_cone_stop_fh 同樣取「半數成員」。
# 成員掉到一半以下後的平均會被少數殘存路徑拉走，DeepMind 自家的 mean 檔也是
# 提早結束（實測 WP222026 成員到 120h、mean 只到 102h），這裡跟上同樣的行為。
MEAN_MIN_MEMBER_FRACTION = 0.5

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CopilotDownloader/1.0)"}


# ── cycle 與網址 ────────────────────────────────────────────────────────────

def latest_cycle(now: datetime | None = None) -> datetime:
    """ECMWF 可用的最新 cycle。

    Open Data 的路徑檔大約在 cycle+8 小時才上架（實測 2026-09-06 03:51 UTC 時
    當天 00Z 的 tf.bufr 仍是 404），比 WNC 的 6h45m 晚，因此這裡用 9 小時的
    保守值，再往下取整到 6 小時邊界。
    """
    now = now or datetime.now(timezone.utc)
    adjusted = now - timedelta(hours=9)
    return adjusted.replace(hour=(adjusted.hour // 6) * 6, minute=0, second=0, microsecond=0)


def forecast_range_hours(model: str, cycle: datetime) -> int:
    """檔名帶著預報時距，猜錯就 404，而且兩個模式的規則不一樣（實測 2026-09-05）：

        IFS   00Z／12Z → 360h，06Z／18Z → 144h
        AIFS  四個 cycle 一律 360h

    早期版本把 IFS 的規則套到 AIFS，導致 AIFS 的 06Z／18Z 一律 404、
    每次都退回 12Z，看起來像「AIFS 沒有 18Z」，其實是檔名要錯了。
    """
    if model == "AIFS":
        return 360
    return 360 if cycle.hour in (0, 12) else 144


def _url(model: str, cycle: datetime, path: str, stream: str) -> str:
    return (f"{BASE_URL}/{cycle:%Y%m%d}/{cycle:%H}z/{path}/"
            f"{cycle:%Y%m%d%H%M%S}-{forecast_range_hours(model, cycle)}h-{stream}-tf.bufr")


# ── BUFR 解碼 ──────────────────────────────────────────────────────────────

def _decode(bufr_path: str) -> pd.DataFrame:
    """把一份 tf.bufr 攤平成 long format：一列一個 (暴風, 成員, 時距) 的路徑點。

    這個 BUFR 模板 pdbufr 的階層式讀法會回空表，只有 flat=True 讀得到；出來是
    一列一個 (暴風, 成員)、欄位以 `#N#key` 帶序號的寬表，得自己還原時間軸：

      meteorologicalAttributeSignificance  1 = 暴風中心、3 = 最大風位置、
                                           4 = 分析時刻的附屬點
      lat/lon      分析中心在 #1#，第 k 個時距的中心在 #{2k+2}#
                   （#2#、#3# 是分析的 sig 4／sig 3，之後每個時距各佔 2 個序號）
      mslp/wind    只在各自的顯著點上報，所以自成一條序號：第 k 個時距是 #{k+1}#
      timePeriod   第 k 個序號即 6k 小時
    """
    import pdbufr  # 延後匯入：沒裝 pdbufr 的環境仍能載入 forecast.py 的其餘部分

    with warnings.catch_warnings():
        # 同一檔內不同暴風的欄位數不一致，pdbufr 會就欄位順序示警；我們一律
        # 以 `#N#key` 具名取值，不依賴欄位順序，故靜音。
        warnings.simplefilter("ignore")
        flat = pdbufr.read_bufr(bufr_path, flat=True)

    if flat.empty:
        return pd.DataFrame()

    step_cols = sorted((c for c in flat.columns if c.endswith("#timePeriod")),
                       key=lambda c: int(re.match(r"#(\d+)#", c).group(1)))

    rows: list[dict] = []
    for _, r in flat.iterrows():
        storm = str(r.get("#1#stormIdentifier", "")).strip()
        if not storm or storm == "nan":
            continue
        name = str(r.get("#1#longStormName", "")).strip() or storm
        member = r.get("#1#ensembleMemberNumber")

        # (時距, 中心 lat/lon 序號, mslp/wind 序號)：分析點 + 逐 6 小時
        points = [(0, 1, 1)]
        points += [(int(r[c]), 2 * k + 2, k + 1)
                   for k, c in enumerate(step_cols, start=1) if pd.notna(r.get(c))]

        for step, pos_i, val_i in points:
            lat, lon = r.get(f"#{pos_i}#latitude"), r.get(f"#{pos_i}#longitude")
            if pd.isna(lat) or pd.isna(lon):
                continue
            mslp = r.get(f"#{val_i}#pressureReducedToMeanSeaLevel")
            wind = r.get(f"#{val_i}#windSpeedAt10M")
            rows.append({
                "storm_id": storm,
                "name": name,
                # ECMWF 成員從 1 起算，DeepMind 從 0 起算，這裡對齊後者
                "member": int(member) - 1 if pd.notna(member) else 0,
                "step": step,
                "lat": float(lat),
                "lon": float(lon),
                # BUFR 的 MSLP 是 Pa、風速是 m/s，專案內一律 hPa 與 kt
                "mslp_hpa": np.nan if pd.isna(mslp) else float(mslp) / 100.0,
                "wind_kt": np.nan if pd.isna(wind) else float(wind) * 1.9438444924406,
            })

    return pd.DataFrame(rows)


# ── 暴風編號對應 ────────────────────────────────────────────────────────────

def _as_utc(dt: datetime) -> datetime:
    """統一成帶 UTC 時區的 datetime，讓 naive／aware 的 cycle 都能相減。"""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r1, r2 = np.radians(lat1), np.radians(lat2)
    dlat, dlon = r2 - r1, np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(r1) * np.cos(r2) * np.sin(dlon / 2) ** 2
    return float(6371.0 * 2 * np.arcsin(np.sqrt(a)))


def _reference_positions(ref_mean_dir: str, ref_prefix: str,
                         cycle: datetime) -> dict[str, tuple[float, float]]:
    """從 DeepMind mean CSV 取各 WP 颱風在 ECMWF cycle 時刻的位置。

    ECMWF 上架得比 WNC 晚，兩邊的 cycle 常常不同期，所以不比對「分析點對分析點」，
    而是把 WNC 的平均路徑內插到 ECMWF 的 cycle 時刻再比 —— 這樣即使差了一兩期
    也還是同一個時刻的位置對位置。

    參考檔取「cycle 最接近」的一份而非最新的一份：最新的那期起始時間可能晚於
    ECMWF 的 cycle，內插會夾到路徑起點，等於拿六小時後的位置來比，實測會把
    誤差從 20 km 拉大到 370 km 而配對失敗。
    """
    if not os.path.isdir(ref_mean_dir):
        return {}

    stamp_re = re.compile(rf"^{re.escape(ref_prefix)}_(\d{{4}}_\d{{2}}_\d{{2}}T\d{{2}})_00_.*\.csv$")
    candidates = []
    for name in os.listdir(ref_mean_dir):
        m = stamp_re.match(name)
        if not m:
            continue
        ref_cycle = datetime.strptime(m.group(1), "%Y_%m_%dT%H").replace(tzinfo=timezone.utc)
        candidates.append((abs((ref_cycle - _as_utc(cycle)).total_seconds()),
                           os.path.join(ref_mean_dir, name)))
    if not candidates:
        return {}
    _, ref_path = min(candidates)

    df = pd.read_csv(ref_path, comment="#")
    df["valid_time"] = pd.to_datetime(df["valid_time"], errors="coerce", utc=True)
    target = pd.Timestamp(_as_utc(cycle))

    out: dict[str, tuple[float, float]] = {}
    for tid, g in df.groupby("track_id"):
        tid = str(tid)
        if not re.match(r"^WP[0-8]\d20\d{2}$", tid):
            continue
        g = g.dropna(subset=["valid_time", "lat", "lon"]).sort_values("valid_time")
        if g.empty:
            continue
        t = g["valid_time"].astype("int64").to_numpy()
        # 目標時刻落在路徑之外時 np.interp 會夾到端點，正是我們要的行為
        lat = float(np.interp(target.value, t, g["lat"].to_numpy()))
        lon = float(np.interp(target.value, t, g["lon"].to_numpy()))
        out[tid] = (lat, lon)
    return out


def _match_track_ids(ec_df: pd.DataFrame,
                     ref_pos: dict[str, tuple[float, float]]) -> dict[str, str]:
    """ECMWF storm_id → 專案的 WP track_id，以分析位置最近者配對。

    不能用編號：ECMWF 與 JTWC 各自編號，實測同一份檔案裡 28W 是 JTWC 的 22W，
    23W 卻又真的是 WP23。位置則是兩邊都吃同一批官方定位報，實測誤差 0.2 度。
    """
    if ec_df.empty or not ref_pos:
        return {}

    analysis = (ec_df[ec_df["step"] == 0]
                .groupby("storm_id")[["lat", "lon"]].first().to_dict("index"))

    pairs = sorted(
        ((_haversine_km(p["lat"], p["lon"], rl, ro), sid, tid)
         for sid, p in analysis.items()
         for tid, (rl, ro) in ref_pos.items()),
        key=lambda x: x[0])

    mapping: dict[str, str] = {}
    used: set[str] = set()
    for dist, sid, tid in pairs:
        if dist > MATCH_RADIUS_KM or sid in mapping or tid in used:
            continue
        mapping[sid] = tid
        used.add(tid)
        print(f"[ECMWF-MATCH] {sid} → {tid}（距離 {dist:.0f} km）")
    return mapping


# ── 輸出 CSV ───────────────────────────────────────────────────────────────

_CSV_COLUMNS = ["init_time", "track_id", "sample", "valid_time", "lead_time",
                "lead_time_hours", "lat", "lon", "minimum_sea_level_pressure_hpa",
                "maximum_sustained_wind_speed_knots"]


def _to_paired(tracks: pd.DataFrame, cycle: datetime) -> pd.DataFrame:
    """long format → 專案的 paired CSV 欄位。"""
    if tracks.empty:
        return pd.DataFrame(columns=_CSV_COLUMNS)
    init = pd.Timestamp(cycle)
    init = init.tz_localize(None) if init.tzinfo else init
    out = pd.DataFrame({
        "init_time": init,
        "track_id": tracks["track_id"].to_numpy(),
        "sample": tracks["member"].astype(int).to_numpy(),
        "valid_time": init + pd.to_timedelta(tracks["step"].to_numpy(), unit="h"),
        "lead_time": pd.to_timedelta(tracks["step"].to_numpy(), unit="h"),
        "lead_time_hours": tracks["step"].astype(int).to_numpy(),
        "lat": tracks["lat"].to_numpy(),
        "lon": tracks["lon"].to_numpy(),
        "minimum_sea_level_pressure_hpa": tracks["mslp_hpa"].to_numpy(),
        "maximum_sustained_wind_speed_knots": tracks["wind_kt"].to_numpy(),
    })
    return out[_CSV_COLUMNS].sort_values(["track_id", "sample", "lead_time_hours"])


def _ensemble_mean(tracks: pd.DataFrame) -> pd.DataFrame:
    """自行計算系集平均 —— ECMWF 的 BUFR 只有成員，沒有現成的平均路徑。

    經度取平均前先解繞：西北太平洋的路徑會跨換日線，直接對 -179 與 179 取
    算術平均會得到 0 度（大西洋中央）。以第一個成員的經度為基準把其餘成員
    拉到同一圈內，平均完再折回 -180..180。
    """
    if tracks.empty:
        return tracks

    rows = []
    for tid, g in tracks.groupby("track_id"):
        n_members = g["member"].nunique()
        min_members = max(2, int(np.ceil(n_members * MEAN_MIN_MEMBER_FRACTION)))
        for step, s in g.groupby("step"):
            if len(s) < min_members:
                continue
            lon0 = s["lon"].iloc[0]
            lon_unwrapped = lon0 + ((s["lon"] - lon0 + 180.0) % 360.0) - 180.0
            rows.append({
                "track_id": tid,
                "name": s["name"].iloc[0],
                "member": -1,
                "step": step,
                "lat": s["lat"].mean(),
                "lon": ((lon_unwrapped.mean() + 180.0) % 360.0) - 180.0,
                "mslp_hpa": s["mslp_hpa"].mean(),
                "wind_kt": s["wind_kt"].mean(),
            })

    mean = pd.DataFrame(rows)
    if mean.empty:
        return mean
    # 平均路徑在成員掉到半數以下後就中斷，中斷後零星復活的時距要一併截掉，
    # 否則畫出來會是一條斷開又重新出現的線
    keep = []
    for _tid, g in mean.groupby("track_id"):
        steps = sorted(g["step"])
        cut = len(steps)
        for i in range(1, len(steps)):
            if steps[i] - steps[i - 1] > 6:
                cut = i
                break
        keep.append(g[g["step"].isin(steps[:cut])])
    return pd.concat(keep, ignore_index=True)


def _write_csv(df: pd.DataFrame, path: str, source: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(f"# Source: ECMWF Open Data ({source})\n")
        f.write("# Licence: https://apps.ecmwf.int/datasets/licences/general (CC BY 4.0)\n")
        df.to_csv(f, index=False)
    os.replace(tmp, path)
    print(f"[ECMWF] 已寫出 {os.path.basename(path)}（{len(df)} 列）")


# ── 對外入口 ───────────────────────────────────────────────────────────────

def _download_bufr(url: str, dest: str, label: str) -> bool:
    """下載 BUFR；404 回傳 False（該 cycle 尚未上架），其餘錯誤照拋。"""
    print(f"[{label}] GET {url}")
    resp = requests.get(url, headers=HEADERS, stream=True, timeout=120)
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    tmp = dest + ".part"
    try:
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                f.write(chunk)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return True


def fetch_cycle(model: str, cycle: datetime, cfg: dict,
                ref_mean_dir: str, ref_prefix: str, scratch_dir: str) -> bool:
    """下載並轉出某個 cycle 的四份 CSV（系集／平均／決定報／潛勢總覽）。

    回傳 False 表示該 cycle 尚未上架或對不到追蹤中的颱風，呼叫端應往前一個
    cycle 再試。系集檔缺就整期跳過；決定報缺只是少一條線，不影響其餘產出。
    """
    stamp = cycle.strftime("%Y_%m_%dT%H_00")
    prefix = cfg["local_prefix"]
    ens_path = os.path.join(cfg["ensemble_dir"], f"{prefix}_{stamp}_paired.csv")
    mean_path = os.path.join(cfg["mean_dir"], f"{prefix}_{stamp}_paired.csv")
    det_path = os.path.join(cfg["det_dir"], f"{prefix}_{stamp}_deterministic.csv")
    cyc_path = os.path.join(cfg["cyc_dir"], f"{prefix}_{stamp}_cyclogenesis.csv")

    os.makedirs(scratch_dir, exist_ok=True)
    ens_src, ens_stream = PRODUCTS[model]["ens"]
    raw_ens = os.path.join(scratch_dir, f"{prefix}_{stamp}_ens.bufr")

    if not _download_bufr(_url(model, cycle, ens_src, ens_stream), raw_ens, f"{model}-ENS"):
        return False

    try:
        tracks = _decode(raw_ens)
    finally:
        if os.path.exists(raw_ens):
            os.remove(raw_ens)

    if tracks.empty:
        print(f"[{model}] BUFR 內無路徑資料")
        return False

    ref_pos = _reference_positions(ref_mean_dir, ref_prefix, cycle)
    mapping = _match_track_ids(tracks, ref_pos)
    if not mapping:
        print(f"[{model}] 無法對應到任何追蹤中的颱風，跳過此 cycle")
        return False

    # 潛勢總覽（Ensemble Overview）：ECMWF Open Data 沒有對應 DeepMind
    # cyclogenesis 的獨立產品，但 tf.bufr 本來就把模式自己生出來的擾動
    # （70W、82W 這類尚未命名的系統）連同現行颱風一起放在同一份檔案裡，
    # 內容與 genesis CSV 等價。DeepMind 的 genesis 檔也是「現行颱風 + 生成
    # 候選」並存（實測 WP222026 與編號 1、2、3… 同在一檔），故這裡照樣全收，
    # 對不到現行颱風的就沿用 ECMWF 自己的暴風代號當 track_id。
    # 西太平洋範圍的篩選交給 plot_genesis_potential_map，這裡不預先裁切。
    genesis = tracks.copy()
    genesis["track_id"] = genesis["storm_id"].map(lambda s: mapping.get(s, s))
    _write_csv(_to_paired(genesis, cycle), cyc_path, f"{model} cyclogenesis")

    tracks["track_id"] = tracks["storm_id"].map(mapping)
    tracks = tracks.dropna(subset=["track_id"]).copy()

    _write_csv(_to_paired(tracks, cycle), ens_path, f"{model} ensemble")
    _write_csv(_to_paired(_ensemble_mean(tracks), cycle), mean_path, f"{model} ensemble mean")

    # 決定報：同一 cycle 的 oper 檔，沿用系集算出的編號對應
    det_src, det_stream = PRODUCTS[model]["det"]
    raw_det = os.path.join(scratch_dir, f"{prefix}_{stamp}_det.bufr")
    try:
        if _download_bufr(_url(model, cycle, det_src, det_stream), raw_det, f"{model}-DET"):
            det = _decode(raw_det)
            if not det.empty:
                det["track_id"] = det["storm_id"].map(mapping)
                det = det.dropna(subset=["track_id"]).copy()
                det["member"] = 0        # 決定報只有一條，成員編號無意義
                _write_csv(_to_paired(det, cycle), det_path, f"{model} deterministic")
        else:
            print(f"[{model}-DET] 決定報尚未上架，僅輸出系集")
    except Exception as e:
        print(f"[{model}-DET] 決定報處理失敗（不影響系集）: {e}")
    finally:
        if os.path.exists(raw_det):
            os.remove(raw_det)

    return True
