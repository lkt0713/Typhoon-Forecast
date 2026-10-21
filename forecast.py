import os
import io
import shutil
import requests # type: ignore
import pandas as pd # type: ignore
from datetime import datetime, timezone, timedelta
import numpy as np # type: ignore
import matplotlib # type: ignore
matplotlib.use("Agg")  # 排程環境無顯示器，避免載入 GUI 後端
import matplotlib.pyplot as plt # type: ignore
import matplotlib.lines as mlines # type: ignore
import matplotlib.patches as mpatches # type: ignore
import matplotlib.patheffects as mpe # type: ignore
from matplotlib.legend_handler import HandlerTuple # type: ignore
from matplotlib.legend import Legend # type: ignore
from matplotlib.offsetbox import DrawingArea # type: ignore
import matplotlib.ticker as mticker # type: ignore
import re

# Target timestamp — auto-derived from current UTC time.
# 實測 2026-10-16 12Z 上架時間：WN2-C r2／r1（含潛勢）+6h15～6h20、GENC +7h05，
# WN3-C 06Z 在 +6h50～7h20 之間（12Z、18Z 整期沒出）。原本等 6h45 才試，WN2-C 每期
# 白等近半小時；改成 6h15，還沒上架的模式只是那一輪 404、退回前一期，10 分鐘後再試。
def _latest_cycle() -> datetime:
    adjusted = datetime.now(timezone.utc) - timedelta(hours=6, minutes=15)
    cycle_hour = (adjusted.hour // 6) * 6
    return adjusted.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)

# Output directories
ENSEMBLE_DIR = "deepmind_weather_downloads_2026"
MEAN_DIR = "deepmind_weather_ensemble_mean_downloads_2026"
CYCLOGENESIS_DIR = "deepmind_weather_cyclogenesis_2026"

os.makedirs(ENSEMBLE_DIR, exist_ok=True)
os.makedirs(MEAN_DIR, exist_ok=True)
os.makedirs(CYCLOGENESIS_DIR, exist_ok=True)

GENC_ENSEMBLE_DIR = "deepmind_weather_genc_downloads_2026"
GENC_MEAN_DIR = "deepmind_weather_genc_ensemble_mean_downloads_2026"
GENC_CYCLOGENESIS_DIR = "deepmind_weather_genc_cyclogenesis_2026"
os.makedirs(GENC_ENSEMBLE_DIR, exist_ok=True)
os.makedirs(GENC_MEAN_DIR, exist_ok=True)
os.makedirs(GENC_CYCLOGENESIS_DIR, exist_ok=True)

# WNC2-r1 是 WeatherNext 2 的舊版本（現行 WNC2-r2 與新版 WNC3 的命名說明見 MODEL_CONFIGS）
WNC_R1_ENSEMBLE_DIR = "deepmind_weather_wnc_r1_downloads_2026"
WNC_R1_MEAN_DIR = "deepmind_weather_wnc_r1_ensemble_mean_downloads_2026"
WNC_R1_CYCLOGENESIS_DIR = "deepmind_weather_wnc_r1_cyclogenesis_2026"
os.makedirs(WNC_R1_ENSEMBLE_DIR, exist_ok=True)
os.makedirs(WNC_R1_MEAN_DIR, exist_ok=True)
os.makedirs(WNC_R1_CYCLOGENESIS_DIR, exist_ok=True)

# WNC3 = WeatherNext 3（2026-09 推出的新世代模式，集合成員 64 條，前代為 50 條）
WNC3_ENSEMBLE_DIR = "deepmind_weather_wnc3_downloads_2026"
WNC3_MEAN_DIR = "deepmind_weather_wnc3_ensemble_mean_downloads_2026"
WNC3_CYCLOGENESIS_DIR = "deepmind_weather_wnc3_cyclogenesis_2026"
os.makedirs(WNC3_ENSEMBLE_DIR, exist_ok=True)
os.makedirs(WNC3_MEAN_DIR, exist_ok=True)
os.makedirs(WNC3_CYCLOGENESIS_DIR, exist_ok=True)

# ECMWF 兩個模式走 ECMWF Open Data 的 BUFR，不是 Weather Lab 的 CSV：
# IFS  = 傳統物理模式（系集 51 條 + HRES 決定報）
# AIFS = ECMWF 自家的 AI 模式（系集 52 條 + AIFS-single 決定報）
# 對方沒有獨立的 cyclogenesis 產品，但 tf.bufr 本來就把未命名的擾動與現行
# 颱風放在同一份檔案，等價的潛勢 CSV 由 ecmwf_bufr 就地產出（見該模組）。
IFS_ENSEMBLE_DIR = "ecmwf_ifs_downloads_2026"
IFS_MEAN_DIR = "ecmwf_ifs_ensemble_mean_downloads_2026"
IFS_DET_DIR = "ecmwf_ifs_deterministic_2026"
IFS_CYCLOGENESIS_DIR = "ecmwf_ifs_cyclogenesis_2026"
AIFS_ENSEMBLE_DIR = "ecmwf_aifs_downloads_2026"
AIFS_MEAN_DIR = "ecmwf_aifs_ensemble_mean_downloads_2026"
AIFS_DET_DIR = "ecmwf_aifs_deterministic_2026"
AIFS_CYCLOGENESIS_DIR = "ecmwf_aifs_cyclogenesis_2026"
for _d in (IFS_ENSEMBLE_DIR, IFS_MEAN_DIR, IFS_DET_DIR, IFS_CYCLOGENESIS_DIR,
           AIFS_ENSEMBLE_DIR, AIFS_MEAN_DIR, AIFS_DET_DIR, AIFS_CYCLOGENESIS_DIR):
    os.makedirs(_d, exist_ok=True)

# NOAA 兩個模式走 NOMADS 上 NCEP ens_tracker 的 ATCF 路徑檔（見 noaa_atcf）：
# GFS   = 傳統物理模式（GEFS 系集 31 條 + GFS 決定報）
# AIGFS = NOAA 的 AI 模式（AIGEFS 系集 31 條 + AIGFS 決定報）
# 潛勢圖只有 GFS 有：GEFS 另有生成追蹤（只到 120h），AIGEFS 沒有對應產品。
GEFS_ENSEMBLE_DIR = "noaa_gefs_downloads_2026"
GEFS_CYCLOGENESIS_DIR = "noaa_gefs_cyclogenesis_2026"
GEFS_MEAN_DIR = "noaa_gefs_ensemble_mean_downloads_2026"
GFS_DET_DIR = "noaa_gfs_deterministic_2026"
AIGEFS_ENSEMBLE_DIR = "noaa_aigefs_downloads_2026"
AIGEFS_MEAN_DIR = "noaa_aigefs_ensemble_mean_downloads_2026"
AIGFS_DET_DIR = "noaa_aigfs_deterministic_2026"
for _d in (GEFS_ENSEMBLE_DIR, GEFS_MEAN_DIR, GFS_DET_DIR, GEFS_CYCLOGENESIS_DIR,
           AIGEFS_ENSEMBLE_DIR, AIGEFS_MEAN_DIR, AIGFS_DET_DIR):
    os.makedirs(_d, exist_ok=True)

# BUFR 原始檔只是轉檔的中間產物（每 cycle 約 2.6 MB），轉完即刪，
# 不進 KEEP_CYCLES 的保留機制。
ECMWF_SCRATCH_DIR = os.path.join("__pycache__", "ecmwf_bufr_raw")

# Weather Lab 下載端點。
# 注意：URL 上的模型代號與我們的顯示名稱不同步。WeatherNext 2 的兩個版本在對方
# 網址上仍是舊代號 "FNV3P2"（r2，與 "OPER" 別名指向同一份檔案）與 "FNV3P1"（r1）；
# WeatherNext 3 則是 "WNV3"。那是對方網址的路徑片段，不是我們的命名，改掉就抓不到
# 資料，因此 MODEL_CONFIGS 的 "remote" 一律照抄對方；我們自己的檔名與顯示名稱則用
# WNC3（新版）、WNC2-r2、WNC2-r1。
BASE_URL = "https://deepmind.google.com/science/weatherlab/download/cyclones"


def _remote_csv_url(model: str, product: str, stamp: str) -> str:
    """組出 Weather Lab CSV 下載網址。

    product: "ensemble/paired"、"ensemble_mean/paired" 或 "ensemble/cyclogenesis"。
    """
    suffix = "cyclogenesis" if product.endswith("cyclogenesis") else "paired"
    return f"{BASE_URL}/{model}/{product}/csv/{model}_{stamp}_{suffix}.csv"


def _cycle_stamp(cycle: datetime) -> str:
    """cycle → 檔名時間戳，例：2026_07_17T06_00"""
    return cycle.strftime("%Y_%m_%dT%H_00")


# 六種模式共用同一條處理管線（_process_model）；模式間的差異集中在這張設定表。
# 順序即網頁分頁順序，第一個是預設分頁 —— WNC3 排最前面。
MODEL_CONFIGS = [
    {
        "remote": "WNV3",         # Weather Lab URL 上的模型代號
        "local_prefix": "WNC3",   # 本地 CSV 檔名前綴
        "display": "WN3-C",
        "ensemble_dir": WNC3_ENSEMBLE_DIR,
        "mean_dir": WNC3_MEAN_DIR,
        "cyc_dir": WNC3_CYCLOGENESIS_DIR,
        "genesis_png": "WP_Genesis_Potential_WNC3.png",
        "output_prefix": "WNC3_", # 輸出圖檔／動畫檔名前綴
        # 刻意不設 required=True：WNC3 剛上線、發布時程還沒穩定，取不到時應略過
        # 而不是讓整個流程失敗；把關的仍是行之有年的 WNC2-r2。
        "required": False,
    },
    {
        "remote": "FNV3P2",       # 對方未改的舊代號，見上方註解
        "local_prefix": "WNC2-r2",
        "display": "WN2-C r2",
        "ensemble_dir": ENSEMBLE_DIR,
        "mean_dir": MEAN_DIR,
        "cyc_dir": CYCLOGENESIS_DIR,
        "genesis_png": "WP_Genesis_Potential.png",
        # 沿用無前綴的輸出檔名（歷史因素）；改前綴等於把 docs/ 既有檔案全部換名
        "output_prefix": "",
        "required": True,         # True：取不到資料時中止整個流程
    },
    {
        "remote": "FNV3P1",
        "local_prefix": "WNC2-r1",
        "display": "WN2-C r1",
        "ensemble_dir": WNC_R1_ENSEMBLE_DIR,
        "mean_dir": WNC_R1_MEAN_DIR,
        "cyc_dir": WNC_R1_CYCLOGENESIS_DIR,
        "genesis_png": "WP_Genesis_Potential_WNC2-r1.png",
        "output_prefix": "WNC2-r1_",
        "required": False,
    },
    {
        "remote": "GENC",
        "local_prefix": "GENC",
        "display": "GENC",
        "ensemble_dir": GENC_ENSEMBLE_DIR,
        "mean_dir": GENC_MEAN_DIR,
        "cyc_dir": GENC_CYCLOGENESIS_DIR,
        "genesis_png": "WP_Genesis_Potential_GENC.png",
        "output_prefix": "GENC_",
        "required": False,
    },
    {
        # fetcher="ecmwf"：不走 Weather Lab，改由 ecmwf_bufr 下載 BUFR 轉成
        # 同樣格式的 paired CSV，之後的流程完全共用。
        "fetcher": "ecmwf",
        "ecmwf_model": "AIFS",
        "local_prefix": "AIFS",
        "display": "AIFS",             # 系集＋決定報一起出現的地方（路徑圖、動畫、強度、互動地圖）
        "ens_name": "AIFS-ENS",        # 只有系集的產品（侵襲機率、系集平均趨勢、城市表、成績單、潛勢）
        "ensemble_dir": AIFS_ENSEMBLE_DIR,
        "mean_dir": AIFS_MEAN_DIR,
        "det_dir": AIFS_DET_DIR,
        "det_label": "AIFS-single (deterministic)",
        "det_name": "AIFS-single",     # 短名稱：成績單、趨勢、城市表、互動地圖用
        "cyc_dir": AIFS_CYCLOGENESIS_DIR,
        "genesis_png": "WP_Genesis_Potential_AIFS.png",
        "output_prefix": "AIFS_",
        "required": False,
    },
    {
        "fetcher": "ecmwf",
        "ecmwf_model": "IFS",
        "local_prefix": "ECMWF",
        "display": "ECMWF",
        "ens_name": "ECMWF-ENS",
        "ensemble_dir": IFS_ENSEMBLE_DIR,
        "mean_dir": IFS_MEAN_DIR,
        "det_dir": IFS_DET_DIR,
        "det_label": "ECMWF HRES (deterministic)",
        "det_name": "ECMWF HRES",
        "cyc_dir": IFS_CYCLOGENESIS_DIR,
        "genesis_png": "WP_Genesis_Potential_ECMWF.png",
        "output_prefix": "ECMWF_",
        "required": False,
    },
    {
        # fetcher="noaa"：由 noaa_atcf 下載 NCEP 的 ATCF 路徑檔轉成 paired CSV。
        # 編號直接是 JTWC 的，但仍只收 WNC2-r2 判定的颱風（與 ECMWF 一致），
        # 所以同樣要排在 WNC2-r2 之後。
        "fetcher": "noaa",
        "noaa_model": "AIGFS",
        "local_prefix": "AIGFS",
        "display": "AIGFS",
        "ens_name": "AIGEFS",
        "ensemble_dir": AIGEFS_ENSEMBLE_DIR,
        "mean_dir": AIGEFS_MEAN_DIR,
        "det_dir": AIGFS_DET_DIR,
        "det_label": "AIGFS (deterministic)",
        "det_name": "AIGFS",
        "cyc_dir": None,
        "genesis_png": None,
        "output_prefix": "AIGFS_",
        "required": False,
    },
    {
        "fetcher": "noaa",
        "noaa_model": "GFS",
        "local_prefix": "GFS",
        "display": "GFS",
        "ens_name": "GEFS",
        "ensemble_dir": GEFS_ENSEMBLE_DIR,
        "mean_dir": GEFS_MEAN_DIR,
        "det_dir": GFS_DET_DIR,
        "det_label": "GFS (deterministic)",
        "det_name": "GFS",
        "cyc_dir": GEFS_CYCLOGENESIS_DIR,
        "genesis_png": "WP_Genesis_Potential_GFS.png",
        "output_prefix": "GFS_",
        "required": False,
    },
]

# 舊命名 → 新命名。WNC-R2／WNC-R1 時期產出的下載檔與圖檔仍躺在磁碟上，且不會被
# _cleanup_old_downloads／_cleanup_stale_outputs 掃到（那些正則都綁定現行 prefix），
# 故由 _cleanup_legacy_names() 一次性清除。確認線上已無舊檔後可整段移除。
LEGACY_PREFIXES = ["WNC-R2", "WNC-R1"]

# 每個下載目錄保留的 cycle 數（4 cycle/日，12 期約三天）。
KEEP_CYCLES = 12
# 系集路徑圖保留前幾期（不含最新一期），網頁上可切換對照
MAP_HISTORY_RUNS = 4

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CopilotDownloader/1.0)"}

# 輸出目錄
OUTPUT_DIR = "docs"
os.makedirs(OUTPUT_DIR, exist_ok=True)
open(os.path.join(OUTPUT_DIR, ".nojekyll"), "w").close()


# 颱風編號：WP 之外也收 CP/EP（跨換日線進來的颱風沿用原編號）；[0-8] 排除 9X 擾動。
STORM_ID_RE = re.compile(r'^(?:WP|CP|EP)[0-8]\d20\d{2}$')


def _starts_in_wpac(g: pd.DataFrame) -> bool:
    """路徑第一點（起報位置）是否在西北太平洋（赤道以北、100°E–180°）。"""
    g = g.dropna(subset=["lat", "lon"])
    if g.empty:
        return False
    if "lead_time_hours" in g.columns:
        g = g.sort_values("lead_time_hours")
    lat, lon = float(g["lat"].iloc[0]), float(g["lon"].iloc[0]) % 360.0
    return lat >= 0 and 100.0 <= lon <= 180.0


def _auto_detect_track_ids(mean_dir: str, preferred_path: str | None = None, model_prefix: str = "WNC2-r2",
                           known_ids: set[str] | None = None) -> list[str]:
    """從 MEAN_DIR 內最新的 CSV 自動偵測有效颱風 TRACK_ID。
    若提供 preferred_path 且檔案存在，優先使用該檔案（當前 cycle）。
    只保留 WP[0-8]X20XX，排除 WP9X（擾動）；CP/EP 颱風跨換日線進來時編號不變
    （例：2026 NOLO 在西太平洋仍是 EP152026），故 CP/EP 改看起報位置是否已在西太。
    known_ids：已由別的模式判定在西太的 CP/EP，直接收。ECMWF 比 WNC 晚一兩期，
    起報時颱風可能還在換日線以東（NOLO 在 ECMWF 00Z 是 179.2°W、WNC 06Z 已 177.7°E）。
    """
    def _read_ids(path: str) -> list[str]:
        print(f"[AUTO-DETECT] 讀取: {os.path.basename(path)}")
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = ''.join(line for line in f if not line.startswith('#'))
            df = pd.read_csv(io.StringIO(content))
            col = next((c for c in df.columns if c.lower() == 'track_id'), None)
            if col is None:
                print("[AUTO-DETECT] 找不到 track_id 欄位")
                return []
            ids = df[col].dropna().astype(str).unique().tolist()
            valid = sorted(tid for tid in ids
                           if STORM_ID_RE.match(tid)
                           and (tid.startswith("WP") or tid in (known_ids or ())
                                or _starts_in_wpac(df[df[col] == tid])))
            print(f"[AUTO-DETECT] 偵測到颱風: {valid}")
            return valid
        except Exception as e:
            print(f"[AUTO-DETECT] 讀取失敗: {e}")
            return []

    if preferred_path and os.path.exists(preferred_path):
        return _read_ids(preferred_path)

    if not os.path.isdir(mean_dir):
        return []
    csvs = sorted(
        [os.path.join(mean_dir, f) for f in os.listdir(mean_dir)
         if f.startswith(f"{model_prefix}_") and f.endswith(".csv")],
        key=os.path.getmtime,
        reverse=True,
    )
    if not csvs:
        print("[AUTO-DETECT] MEAN_DIR 內無可用 CSV")
        return []
    return _read_ids(csvs[0])


def _jtwc_url_key(track_id: str) -> str:
    """WP062026 → 'wp0626'；EP152026 → 'ep1526'"""
    m = re.match(r'^([A-Z]{2})(\d{2})(\d{4})$', track_id)
    if not m:
        return track_id.lower()
    return f"{m.group(1).lower()}{m.group(2)}{m.group(3)[2:]}"


def _build_jtwc_urls(track_ids: list[str]) -> tuple[dict, dict]:
    base = "https://www.metoc.navy.mil/jtwc/products"
    forecast, text = {}, {}
    for tid in track_ids:
        key = _jtwc_url_key(tid)
        forecast[tid] = f"{base}/{key}.gif"
        text[tid] = f"{base}/{key}web.txt"
    return forecast, text

# 可選底圖：Cartopy
try:
    import cartopy.crs as ccrs # Type: ignore
    import cartopy.feature as cfeature # Type: ignore
    from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER # type: ignore
    HAS_CARTOPY = True
    print("[INFO] Cartopy 已載入")
except ImportError:
    HAS_CARTOPY = False
    print("[WARN] 未安裝 Cartopy，將使用簡易經緯度圖")


def _pick_tick_step(span: float) -> float:
    if span <= 20:
        return 2
    if span <= 40:
        return 5
    if span <= 80:
        return 10
    return 20


def _configure_cartopy_gridlines(gl, extent):
    lon_min, lon_max, lat_min, lat_max = extent
    x_step = _pick_tick_step(abs(lon_max - lon_min))
    y_step = _pick_tick_step(abs(lat_max - lat_min))

    gl.xlocator = mticker.MultipleLocator(x_step)
    gl.ylocator = mticker.MultipleLocator(y_step)
    gl.xformatter = LONGITUDE_FORMATTER
    gl.yformatter = LATITUDE_FORMATTER
    gl.xlabel_style = {'size': 8}
    gl.ylabel_style = {'size': 8}


def _fit_extent_to_aspect(extent, target_ar: float, use_360: bool):
    min_lon, max_lon, min_lat, max_lat = extent
    w, h = max_lon - min_lon, max_lat - min_lat
    if h <= 0:
        h = 1e-6

    if w / h > target_ar:
        extra = (w / target_ar - h) / 2
        min_lat -= extra
        max_lat += extra
    else:
        extra = (target_ar * h - w) / 2
        min_lon -= extra
        max_lon += extra

    # 比例調整後再夾制邊界，避免超出經度範圍造成 Cartopy 版面異常
    if use_360:
        min_lon = max(0.0, min_lon)
        max_lon = min(360.0, max_lon)
    else:
        min_lon = max(-180.0, min_lon)
        max_lon = min(180.0, max_lon)
    min_lat = max(-90.0, min_lat)
    max_lat = min(90.0, max_lat)

    return (min_lon, max_lon, min_lat, max_lat)

# ── 配色系統 ────────────────────────────────────────────────────────────────
# 設計原則（排版與符號參考 Weather Lab 的系集路徑圖）：底圖壓成中性灰藍、只當
# 背景，顏色全部留給資料層。強度色階是單調的色相漸變（灰→藍→綠→琥珀→橘→紅→
# 紫），亮度同時遞減，轉成灰階或色盲視角仍保有順序感；MSLP 色階共用同一組色票
# （壓力越低＝強度越高），兩張圖看起來才像同一套系統。
BASEMAP = {
    'ocean':  '#F2F7FB',   # 極淡藍：海面
    'land':   '#E6E7E3',   # 中性淺灰：陸地
    'coast':  '#5A6672',   # 海岸線
    'border': '#A9B3BE',   # 國界
    'grid':   '#BCC7D3',   # 經緯線
}

# Saffir-Simpson 強度色階
COLOR_MAP = {
    'TD':   '#8A97A6',   # 熱帶低壓：板岩灰
    'TS':   '#2E86C8',   # 熱帶風暴：海洋藍
    'Cat1': '#1FA97E',   # 一級：青綠
    'Cat2': '#E0AC2B',   # 二級：琥珀
    'Cat3': '#EE7A22',   # 三級：橘
    'Cat4': '#DC3A4E',   # 四級：緋紅
    'Cat5': '#A548C8',   # 五級：紫
    'Unknown': '#B7C0CA',
}

# 資料層的其他角色色
TRACK_LINE  = '#9AA6B2'   # 集合成員連線
MEAN_COLOR  = '#16324F'   # 集合平均路徑：深海軍藍（在彩色點群中仍能一眼看出）
# 決定報路徑（ECMWF HRES／AIFS-single）：深琥珀實線，線型與 24h 圓點標記比照
# 平均路徑，只用顏色區分。強度色階裡的橘（Cat3 #EE7A22）只以小圓點出現，這裡
# 是帶白色描邊的粗線，不會與強度點混淆。
DET_COLOR   = '#B45309'
INIT_FACE   = '#FFC24A'   # 初始位置星形
INIT_EDGE   = '#A9670C'
TEXT_DARK   = '#16324F'   # 主要文字
TEXT_MUTED  = '#6B7785'   # 次要文字
BOX_EDGE    = '#C9D3DE'   # 標註方框外框
LEGEND_KW   = dict(frameon=True, framealpha=0.94, facecolor='white', edgecolor=BOX_EDGE)

# MSLP 色彩分級（西太平洋潛勢預報用；與強度色階同色票、方向相反）
MSLP_COLOR_BINS = [
    (935,          '#A548C8', '≤935 hPa'),
    (955,          '#DC3A4E', '936–955 hPa'),
    (978,          '#EE7A22', '956–978 hPa'),
    (988,          '#E0AC2B', '979–988 hPa'),
    (1000,         '#2E86C8', '989–1000 hPa'),
    (float('inf'), '#8A97A6', '>1000 hPa'),
]
MSLP_WEAKEST_COLOR = MSLP_COLOR_BINS[-1][1]



def _mslp_to_color(mslp: float) -> str:
    """依 MSLP_COLOR_BINS 返回對應顏色；NaN 視為最弱一級。"""
    if pd.isna(mslp):
        return MSLP_WEAKEST_COLOR
    for threshold, color, _ in MSLP_COLOR_BINS:
        if mslp <= threshold:
            return color
    return MSLP_WEAKEST_COLOR


def _scatter_members(ax, lons, lats, colors, kw, size=11.0,
                     alpha=0.9, zorder=1.15, lw=0.7):
    """畫集合成員的位置點，一律空心圈。

    早期版本以 34 kt 為界，達到者實心、未達者空心。點放大之後實心點會把密集區
    糊成一整片色塊，反而看不出個別成員，故改為一律空心 —— 圈與圈重疊時邊界
    還在，路徑的疏密一眼可讀。強度仍由顏色表示。
    """
    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)
    if lons.size == 0:
        return
    ax.scatter(lons, lats, s=size, facecolors='none', edgecolors=list(colors),
               marker='o', linewidths=lw, alpha=alpha, zorder=zorder, **kw)


def _draw_member_track(ax, g, use_360: bool, kw, lw: float = 1.0,
                       alpha: float = 0.75, zorder: float = 0.9) -> None:
    """單一成員路徑：依強度逐段著色的細線。

    早期是「灰線 + 每 6h 空心圈」，64 個成員在臺灣附近疊成一整片色塊，連陸地
    與海岸線都被蓋掉。改成細的彩色線段後強度仍讀得出來，線與線之間還留得下
    底圖；每段顏色取起點強度。經度跳超過 180° 的段（換日線）直接略過。
    """
    from matplotlib.collections import LineCollection  # type: ignore
    lons = _normalize_lon_values(g['lon'].to_numpy(), use_360=use_360)
    lats = g['lat'].to_numpy(dtype=float)
    winds = (g['wind'] if 'wind' in g.columns
             else pd.Series(np.nan, index=g.index)).to_numpy()
    valid = ~(np.isnan(lons) | np.isnan(lats))
    lons, lats, winds = lons[valid], lats[valid], winds[valid]
    if lons.size < 2:
        return
    pts = np.column_stack([lons, lats])
    segs = np.stack([pts[:-1], pts[1:]], axis=1)
    keep = np.abs(np.diff(lons)) <= 180.0
    colors = [COLOR_MAP.get(ss_category(w), COLOR_MAP['Unknown']) for w in winds[:-1]]
    colors = [c for c, k in zip(colors, keep) if k]
    ax.add_collection(LineCollection(segs[keep], colors=colors, linewidths=lw,
                                     alpha=alpha, zorder=zorder,
                                     capstyle='round', joinstyle='round', **kw))


def _intensity_legend_handles(ms: float = 7.0, style: str = 'marker') -> list:
    """強度圖例：與地圖一致，只用顏色分強度。

    style='marker' 為空心圈（點狀圖用）；'line' 為短色線（成員改畫彩色線的路徑圖用）。
    """
    cats = ['TD', 'TS', 'Cat1', 'Cat2', 'Cat3', 'Cat4', 'Cat5']
    if style == 'line':
        return [mlines.Line2D([], [], color=COLOR_MAP[cat], lw=2.4, label=cat)
                for cat in cats]
    return [mlines.Line2D([], [], marker='o', ms=ms, ls='', label=cat,
                          markerfacecolor='none', markeredgecolor=COLOR_MAP[cat],
                          markeredgewidth=1.1, color=COLOR_MAP[cat])
            for cat in cats]


def _cyclone_marker_path(turns: float = 0.62, r_core: float = 0.30,
                         r_end: float = 1.0, w_start: float = 0.30,
                         w_end: float = 0.035, n: int = 56):
    """颱風符號（中心圓 + 兩條旋臂）的 marker Path。

    matplotlib 沒有現成的颱風符號，Unicode 的 🌀 只存在於 emoji 字型 —— 排程是在
    沒有 emoji 字型的環境跑的，直接用字元會變成豆腐框，所以這裡自己描出形狀：
    每條旋臂沿一條「半徑漸增、寬度漸縮」的螺旋中心線取外緣與內緣後閉合。

    北半球颱風逆時針旋轉，旋臂要往逆時針方向甩出去；螺旋是先以 +θ 描出來的，
    最後整條路徑沿 x 軸鏡射一次來翻轉旋向 —— 鏡射比改角度符號安全，因為它把
    三個子路徑（中心圓 + 兩臂）的環繞方向一起翻，繞向仍然一致。Agg 用 nonzero
    填色規則，繞向一致時重疊處會併成一體而不是挖洞；也因此不要對它描邊，否則
    子路徑的交界會露出接縫。
    """
    from matplotlib.path import Path as _MplPath

    verts: list = []
    codes: list = []

    def _add_polygon(pts):
        verts.extend(pts.tolist() + [pts[0].tolist()])
        codes.extend([_MplPath.MOVETO] + [_MplPath.LINETO] * (len(pts) - 1)
                     + [_MplPath.CLOSEPOLY])

    ang = np.linspace(0.0, 2 * np.pi, 40, endpoint=False)
    _add_polygon(np.column_stack([r_core * np.cos(ang), r_core * np.sin(ang)]))

    u = np.linspace(0.0, 1.0, n)
    rad = r_core * 0.5 + (r_end - r_core * 0.5) * u
    half_w = w_start * (1.0 - u) ** 1.2 + w_end * u
    for k in range(2):
        th = np.pi * k + 2 * np.pi * turns * u
        outer = np.column_stack([(rad + half_w) * np.cos(th), (rad + half_w) * np.sin(th)])
        inner = np.column_stack([(rad - half_w) * np.cos(th), (rad - half_w) * np.sin(th)])
        _add_polygon(np.vstack([outer, inner[::-1]]))

    xy = np.asarray(verts, dtype=float)
    xy[:, 1] = -xy[:, 1]          # 沿 x 軸鏡射：旋臂由順時針翻成逆時針
    return _MplPath(xy, np.asarray(codes, dtype=np.uint8))


CYCLONE_MARKER = _cyclone_marker_path()


def _draw_init_marker(ax, lon, lat, kw, scale: float = 1.0):
    """初始位置：颱風符號。

    白色圓底先把它從底下密集的成員點裡挖出來，再疊深琥珀（外框）與琥珀（本體）
    兩層符號 —— 用兩層疊而不是描邊，是因為描邊會把旋臂與中心圓的接縫畫出來。
    """
    ax.scatter([lon], [lat], s=250 * scale, marker='o', color='white',
               edgecolors='none', alpha=0.85, zorder=7, **kw)
    ax.scatter([lon], [lat], s=235 * scale, marker=CYCLONE_MARKER, color=INIT_EDGE,
               edgecolors='none', zorder=7.1, **kw)
    ax.scatter([lon], [lat], s=165 * scale, marker=CYCLONE_MARKER, color=INIT_FACE,
               edgecolors='none', zorder=7.2, **kw)


def _init_legend_handle(ms: float = 11.0):
    """圖例裡的初始位置標記：兩個 Line2D 疊出跟地圖上一樣的雙層颱風符號。

    回傳 tuple，legend 需搭配 handler_map={tuple: HandlerTuple(ndivide=1)}
    —— ndivide=1 才是「全部疊在同一格」，None 會把格子平分成並排的兩個；
    因為 tuple 沒有 get_label()，呼叫端必須另外傳 labels。
    """
    return (
        mlines.Line2D([], [], marker=CYCLONE_MARKER, ms=ms, ls='',
                      color=INIT_EDGE, markeredgecolor='none'),
        mlines.Line2D([], [], marker=CYCLONE_MARKER, ms=ms * 0.84, ls='',
                      color=INIT_FACE, markeredgecolor='none'),
    )


def _track_source_legend(ax, model_name: str, fontsize: float = 9, ms: float = 11.0,
                         det_label: str | None = None, intensity_style: str = 'line'):
    """左上角的合併圖例：上半路徑／符號（不加標題，各列自己就說得清楚）、
    下半 Intensity 色票（靜態圖與動畫幀共用）。

    det_label 有值時多一列決定報（ECMWF HRES／AIFS-single）。intensity_style
    'line' 給成員畫彩色線的路徑圖、'marker' 給成員當前位置畫圈的動畫幀。

    一個 Legend 只能有一種欄數，路徑區一欄、強度四欄排不進同一個；所以
    強度另建一個不掛到軸上的 Legend 只拿來排版，把它的方塊（標題＋色票）接到
    主圖例的 _legend_box 底下 —— 外框、底色只有一個，看起來是同一個圖例。
    """
    # 成員線依強度著色，圖例用三段彩色短線並排暗示「顏色＝強度」
    member_handle = tuple(mlines.Line2D([], [], color=COLOR_MAP[c], lw=2.0)
                          for c in ('TS', 'Cat2', 'Cat4'))
    handles = [
        member_handle,
        mlines.Line2D([], [], color=MEAN_COLOR, marker='o', ms=ms * 0.55, lw=2.8,
                      markerfacecolor='white', markeredgecolor=MEAN_COLOR,
                      markeredgewidth=1.4),
    ]
    labels = ['Ensemble Members', f'{model_name} Mean']
    if det_label:
        handles.append(mlines.Line2D([], [], color=DET_COLOR, marker='o', ms=ms * 0.55,
                                     lw=2.6, markerfacecolor='white',
                                     markeredgecolor=DET_COLOR, markeredgewidth=1.4))
        labels.append(det_label)
    handles.append(_init_legend_handle(ms))
    labels.append('Init Position')
    leg = ax.legend(handles=handles, labels=labels, loc='upper left',
                    fontsize=fontsize, borderpad=0.7, labelspacing=0.42,
                    handlelength=1.4, handletextpad=0.7,
                    handler_map={tuple: HandlerTuple(ndivide=1, pad=0),
                                 member_handle: HandlerTuple(ndivide=None, pad=0)},
                    alignment='left', **LEGEND_KW)

    int_handles = _intensity_legend_handles(ms=ms * 0.6, style=intensity_style)
    int_leg = Legend(ax, int_handles, [h.get_label() for h in int_handles],
                     title='Intensity', fontsize=fontsize * 0.92, ncol=4,
                     title_fontsize=fontsize, labelspacing=0.3, columnspacing=1.0,
                     handlelength=1.4 if intensity_style == 'line' else 0.9,
                     handletextpad=0.4, borderpad=0, alignment='left')
    _style_legend(int_leg)

    # 兩段之間的虛線分隔：寬度要等於圖例內容寬，但 VPacker 不會把子方塊撐滿，
    # 只能先量兩段的實際寬度（像素）再換成 DrawingArea 用的點數
    fig = ax.figure
    renderer = fig.canvas.get_renderer()
    width_px = max(leg._legend_box.get_bbox(renderer).width,
                   int_leg._legend_box.get_bbox(renderer).width)
    width_pt = width_px * 72.0 / fig.dpi
    sep = DrawingArea(width_pt, 6)
    sep.add_artist(mlines.Line2D([0, width_pt], [3, 3], color=TEXT_MUTED, alpha=0.6,
                                 lw=0.8, ls=(0, (3, 2.5))))
    leg._legend_box._children += [sep, int_leg._legend_box]

    _style_legend(leg)
    ax.add_artist(leg)
    return leg


def _style_legend(leg) -> None:
    """圖例標題置中並統一字色。"""
    title = leg.get_title()
    title.set_multialignment('center')
    title.set_ha('center')
    title.set_color(TEXT_DARK)
    for text in leg.get_texts():
        text.set_color(TEXT_DARK)


# 領先點標註（+Nh／強度）離標記中心的經緯度偏移。+0h 時這個標註就落在颱風
# 符號旁邊，偏移太小會被符號的旋臂壓到，所以留得比 24h 小標籤寬一些。
LABEL_OFFSET = 0.95
# 平均路徑終點有「+Nh／強度」標註框；離終點這麼近（度）的 24 h 時間標籤不畫，
# 不然路徑最後往回勾時（如 ECMWF 偶爾的鉤狀尾巴）兩個標籤會疊在一起
END_LABEL_CLEAR_DEG = 2.5


def _label_box(alpha: float = 0.92) -> dict:
    """路徑標註用的白底圓角框。"""
    return dict(boxstyle='round,pad=0.28', facecolor='white',
                edgecolor=BOX_EDGE, alpha=alpha, linewidth=0.8)


def _setup_basemap(ax, extent, grid_step: float | None = None, label_size: int = 8):
    """Cartopy 底圖統一樣式。

    海面先加、陸地後加：兩者的預設 zorder 同為 -1，後加入者疊在上面；反過來
    （原本的順序）會讓半透明海面蓋住陸地，整張圖發灰。

    海岸線 zorder 2.5：壓在所有成員線與成員圈（路徑圖 0.9～1.15、潛勢圖 1～2）
    之上，連平均路徑／決定報（2.0～2.4）也壓在底下，成員與平均線再密集，
    臺灣等島嶼的輪廓也不會消失；24h 圓點與標籤（5 以上）仍在海岸線之上。
    """
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    ax.add_feature(cfeature.OCEAN, facecolor=BASEMAP['ocean'])
    ax.add_feature(cfeature.LAND, facecolor=BASEMAP['land'])
    ax.coastlines(resolution='50m', linewidth=0.7, color=BASEMAP['coast'], zorder=2.5)
    ax.add_feature(cfeature.BORDERS, linewidth=0.5, edgecolor=BASEMAP['border'], zorder=0.6)
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color=BASEMAP['grid'],
                      alpha=0.8, linestyle=(0, (2, 3)))
    gl.right_labels = False
    gl.top_labels = False
    if grid_step is not None:
        gl.xlocator = mticker.MultipleLocator(grid_step)
        gl.ylocator = mticker.MultipleLocator(grid_step)
        gl.xformatter = LONGITUDE_FORMATTER
        gl.yformatter = LATITUDE_FORMATTER
        gl.xlabel_style = {'size': label_size, 'color': TEXT_MUTED}
        gl.ylabel_style = {'size': label_size, 'color': TEXT_MUTED}
    else:
        _configure_cartopy_gridlines(gl, extent)
        gl.xlabel_style = {'size': label_size, 'color': TEXT_MUTED}
        gl.ylabel_style = {'size': label_size, 'color': TEXT_MUTED}
    return gl


def _setup_plain_axes(ax, extent, label_size: int = 9):
    """無 Cartopy 時的退化底圖 —— 與 _setup_basemap 共用同一套顏色。"""
    ax.set_facecolor(BASEMAP['ocean'])
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.grid(True, linewidth=0.5, alpha=0.8, linestyle=(0, (2, 3)), color=BASEMAP['grid'])
    ax.set_xlabel("Longitude", fontsize=label_size, color=TEXT_MUTED)
    ax.set_ylabel("Latitude", fontsize=label_size, color=TEXT_MUTED)
    ax.tick_params(colors=TEXT_MUTED, labelsize=label_size - 1)
    for spine in ax.spines.values():
        spine.set_edgecolor(BASEMAP['grid'])


def _set_map_titles(ax, main: str, right: str = '', main_size: int = 14, right_size: int = 9):
    """主標題（粗體）＋副標（灰色），兩行都靠左，副標貼在軸框正上方。

    原本副標放右上角，模式名稱一長（如 ECMWF-ENS）就跟主標題撞在一起；改成兩行後
    與侵襲機率、強度、趨勢圖同一套排版。right 裡的換行與「·」一律接成一行副標。
    """
    ax.set_title(main, loc='left', fontsize=main_size, fontweight='bold',
                 color=TEXT_DARK, pad=10 + right_size * 1.9 if right else 10)
    if right:
        parts = [p.strip() for p in re.split(r'\n|·', right) if p.strip()]
        ax.text(0, 1.012, '  ·  '.join(parts), transform=ax.transAxes, ha='left', va='bottom',
                fontsize=right_size + 0.5, color=TEXT_MUTED)


def _watermark(ax, side: str = 'right') -> None:
    """署名，side 決定貼左下或右下。"""
    x, ha = (0.995, 'right') if side == 'right' else (0.005, 'left')
    ax.text(x, 0.008, 'By Pillar', transform=ax.transAxes,
            ha=ha, va='bottom', fontsize=7, style='italic',
            color=TEXT_MUTED, zorder=10)

FIG_AR = 1.40
FIG_H = 8
FIG_W = FIG_AR * FIG_H
FIG_DPI = 300
# 潛勢總覽／路徑聚類圖與動畫幀的輸出解析度（幀數多，比 FIG_DPI 低一些以控制 docs 大小）
OVERVIEW_DPI = 300
FRAME_DPI = 220
FRAME_WEBP_QUALITY = 82

# 目標颱風 Track ID — 從最新 CSV 自動偵測，無需手動修改
TARGET_TRACK_IDS = _auto_detect_track_ids(MEAN_DIR)
JTWC_FORECAST_URLS, JTWC_TEXT_URLS = _build_jtwc_urls(TARGET_TRACK_IDS)


# 本次執行中已確認不存在的 JTWC 產品 URL。JTWC 對某顆颱風停止發布後，該產品在
# 這次執行內不會突然冒出來，每個模式各問一次只是白費好幾個 request。
_JTWC_ABSENT: set[str] = set()


def _jtwc_fetch(url: str, label: str):
    """抓一份 JTWC 產品；產品不存在時回 None，其餘錯誤照拋。

    metoc.navy.mil 的 /jtwc/products/ 是 S3 靜態託管，而且沒開 ListBucket，
    所以物件不存在時回的是 403 AccessDenied 而不是 404（實測 2026-09-10：
    已停發的 wp2226web.txt 回 403 + 111 bytes 的 AccessDenied XML，仍在發布的
    wp9926web.txt 回 200）。照著字面把這個 403 當錯誤，log 裡就會刷出一排
    「403 Client Error: Forbidden」，看起來像被擋或壞掉，實際上只是這顆颱風
    已經沒有公報可抓。

    只認 body 帶 AccessDenied 的 403：真的被 WAF 擋下時回的是 HTML，
    那種情況仍然要拋出來，不能默默當成「沒有這顆颱風」。
    """
    if url in _JTWC_ABSENT:
        print(f"[JTWC] {label}: 本次執行已確認 JTWC 無此產品，略過")
        return None
    resp = requests.get(url, headers=HEADERS, timeout=30)
    if resp.status_code == 404 or (resp.status_code == 403
                                   and b"AccessDenied" in resp.content[:512]):
        _JTWC_ABSENT.add(url)
        print(f"[JTWC] {label}: JTWC 已停止發布此產品（HTTP {resp.status_code}），略過")
        return None
    resp.raise_for_status()
    return resp


def download_jtwc_image(track_id: str, output_dir: str = OUTPUT_DIR, jtwc_forecast_urls: dict | None = None) -> str | None:
    """下載 JTWC 預報圖

    Args:
        track_id: 風暴追蹤 ID
        output_dir: 輸出目錄
        jtwc_forecast_urls: 自訂 URL 字典（None 時使用全域 JTWC_FORECAST_URLS）

    Returns:
        下載的圖片檔案路徑，如果失敗則返回 None
    """
    urls = jtwc_forecast_urls if jtwc_forecast_urls is not None else JTWC_FORECAST_URLS
    if track_id not in urls:
        print(f"[JTWC] 無對應的 JTWC URL: {track_id}")
        return None

    url = urls[track_id]
    output_path = os.path.join(output_dir, f"jtwc_{track_id}.gif")
    
    try:
        print(f"[JTWC] 正在下載: {url}")
        response = _jtwc_fetch(url, track_id)
        if response is None:
            return None

        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        print(f"[JTWC] 下載完成: {output_path}")
        return output_path
    except Exception as e:
        print(f"[JTWC] 下載失敗: {e}")
        return None


def ss_category(kt):
    if pd.isna(kt):
        return 'Unknown'
    try:
        kt = float(kt)
    except Exception:
        return 'Unknown'
    if kt < 35: return 'TD'
    elif kt < 64: return 'TS'
    elif kt < 83: return 'Cat1'
    elif kt < 96: return 'Cat2'
    elif kt < 113: return 'Cat3'
    elif kt < 137: return 'Cat4'
    else: return 'Cat5'


def _get_interval_markers(df, init_time, step_h: float, tol_h: float, max_hour: float) -> pd.DataFrame:
    """每 step_h 小時取一筆最接近整點的資料列（時間誤差需 < tol_h 小時）。"""
    if df.empty or init_time is None:
        return pd.DataFrame()
    df = df.copy()
    df['fh'] = (df['valid_time'] - init_time).dt.total_seconds() / 3600.0
    rows = []
    for t in np.arange(0, max_hour + 1, step_h):
        match = df[abs(df['fh'] - t) < tol_h]
        if not match.empty:
            rows.append(match.loc[abs(match['fh'] - t).idxmin()])
    return pd.DataFrame(rows)


def get_24h_markers(df, init_time, max_hour=360):
    return _get_interval_markers(df, init_time, step_h=24, tol_h=1.5, max_hour=max_hour)


def get_6h_markers(df, init_time, max_hour=360):
    return _get_interval_markers(df, init_time, step_h=6, tol_h=1.0, max_hour=max_hour)


def build_24h_summary(pts: pd.DataFrame, init_time: pd.Timestamp) -> str:
    """組合 24 小時標記的摘要字串，顯示在右下角。
    內容格式：+24h: 80kt (Cat1)
    """
    if pts is None or pts.empty:
        return ""
    lines = []
    for _, pt in pts.iterrows():
        wind = pt.get('wind', np.nan)
        cat = ss_category(wind)
        fh = (pt['valid_time'] - init_time).total_seconds() / 3600.0
        wind_str = f"{int(wind)}kt" if not pd.isna(wind) else "N/A"
        lines.append(f"+{int(fh)}h: {wind_str} ({cat})")
    return "\n".join(lines)


def _format_intensity_label(wind) -> str:
    """Format wind intensity for compact point annotations."""
    if pd.isna(wind):
        return "N/A"
    try:
        w = float(wind)
    except Exception:
        return "N/A"
    return f"{int(round(w))}kt ({ss_category(w)})"


def _detect_dateline_crossing(lon_vals):
    """檢測是否跨越國際換日線"""
    lon_vals = np.array(lon_vals)
    lon_vals = lon_vals[~np.isnan(lon_vals)]
    if len(lon_vals) < 2:
        return False
    lon_sorted = np.sort(lon_vals)
    lon_diffs = np.diff(lon_sorted)
    return np.max(lon_diffs) > 180


def _normalize_lon_values(lon_vals, use_360: bool):
    """將經度正規化到 [-180, 180) 或 [0, 360) 以利跨換日線繪圖。"""
    lons = np.asarray(lon_vals, dtype=float)
    lons = ((lons + 180.0) % 360.0) - 180.0
    if use_360:
        lons = lons % 360.0
    return lons


def _split_track_segments(lons, lats, jump_threshold: float = 180.0):
    """在經度跳躍過大處切段，避免軌跡跨整張圖連線。"""
    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)
    valid = (~np.isnan(lons)) & (~np.isnan(lats))
    lons = lons[valid]
    lats = lats[valid]
    if len(lons) == 0:
        return []

    split_idx = np.where(np.abs(np.diff(lons)) > jump_threshold)[0] + 1
    lon_segments = np.split(lons, split_idx)
    lat_segments = np.split(lats, split_idx)
    return [(seg_lon, seg_lat) for seg_lon, seg_lat in zip(lon_segments, lat_segments) if len(seg_lon) > 0]

# AIGFS／GFS 的成員轉溫帶後會一路追到極區，地圖範圍只算這個緯度以南的點（線照畫，超出部分裁掉）
EXTENT_LAT_CAP = 45.0


def _auto_extent(lat_vals, lon_vals, pad_deg=3.0):
    """計算地圖範圍，自動選擇較緊湊的經度表達方式。"""
    lon_vals = np.asarray(lon_vals, dtype=float)
    lat_vals = np.asarray(lat_vals, dtype=float)
    ok = ~np.isnan(lon_vals) & ~np.isnan(lat_vals)
    lon_vals, lat_vals = lon_vals[ok], lat_vals[ok]
    if len(lat_vals):
        # 颱風本身就在高緯時把上限往北放，避免整條路徑都被濾掉
        cap = max(EXTENT_LAT_CAP, np.min(lat_vals) + 10)
        keep = lat_vals <= cap
        lon_vals, lat_vals = lon_vals[keep], lat_vals[keep]

    if len(lon_vals) == 0 or len(lat_vals) == 0:
        return (-180, 180, -90, 90), False
    
    lat_min, lat_max = np.min(lat_vals), np.max(lat_vals)

    lons_180 = _normalize_lon_values(lon_vals, use_360=False)
    span_180 = np.max(lons_180) - np.min(lons_180)

    lons_360 = _normalize_lon_values(lon_vals, use_360=True)
    span_360 = np.max(lons_360) - np.min(lons_360)

    use_360 = span_360 < span_180
    if use_360:
        lon_min = np.min(lons_360) - pad_deg
        lon_max = np.max(lons_360) + pad_deg
        lon_min = max(lon_min, 0)
        lon_max = min(lon_max, 360)
    else:
        lon_min = np.min(lons_180) - pad_deg
        lon_max = np.max(lons_180) + pad_deg
        lon_min = max(lon_min, -180)
        lon_max = min(lon_max, 180)

    return (lon_min, lon_max, lat_min - pad_deg, lat_max + pad_deg), use_360


# 轉溫帶後不再追蹤：路徑一過這個緯度就截斷，之後的點全部丟掉（所有模式同一規則）。
# 各家資料都沒有冷暖心欄位可判斷，以緯度近似；西北太平洋颱風多在 35～40N 完成轉化。
# AIGFS／GFS 的追蹤器轉溫帶後仍一路追到極區，不截斷時會把地圖撐到北緯 80 度。
ET_CUTOFF_LAT = 40.0


def _cut_extratropical(df: pd.DataFrame, by, order: str) -> pd.DataFrame:
    """每條路徑（依 by 分組、order 排序）從第一個緯度絕對值超過 ET_CUTOFF_LAT 的點起全部截掉。

    起報時本來就在截斷緯度以北的（極少見），門檻改為起點以北 5 度，免得整條被丟。"""
    if df.empty:
        return df
    df = df.sort_values([*by, order]) if by else df.sort_values(order)
    alat = df['lat'].abs()                  # 南半球同理，往南過 40S 截斷
    lat0 = alat.groupby([df[c] for c in by]).transform('first') if by else alat.iloc[0]
    over = (alat > np.maximum(ET_CUTOFF_LAT, lat0 + 5)).astype(int)
    passed = over.groupby([df[c] for c in by]).cumsum() if by else over.cumsum()
    return df[passed == 0]


def load_forecast_dataframe(csv_path: str, track_id: str) -> tuple[pd.DataFrame, pd.Timestamp]:
    """讀取 paired CSV 並過濾指定 track_id，僅保留必要欄位。"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"找不到資料檔：{csv_path}")
    df = pd.read_csv(csv_path, comment="#")
    # 標準欄位存在性
    for col in ["track_id", "sample", "valid_time", "lat", "lon"]:
        if col not in df.columns:
            raise ValueError(f"CSV 缺少必要欄位：{col}")
    # 欄位修正: 一致使用 wind 欄位（若存在）
    if 'maximum_sustained_wind_speed_knots' in df.columns:
        df = df.rename(columns={'maximum_sustained_wind_speed_knots': 'wind'})

    sub = df[df["track_id"].astype(str) == str(track_id)].copy()
    if sub.empty:
        raise ValueError(f"CSV 中未找到 track_id={track_id} 的資料")
    # 轉型與排序
    sub["valid_time"] = pd.to_datetime(sub["valid_time"], errors="coerce", utc=True)
    # 取初始化時間（欄位存在時）
    init_time = None
    if 'init_time' in sub.columns:
        try:
            init_time = pd.to_datetime(sub['init_time'].iloc[0], utc=True)
        except Exception:
            init_time = None
    sub["sample"] = sub["sample"].astype(float)
    sub = sub.dropna(subset=["valid_time", "lat", "lon"])
    sub = _cut_extratropical(sub, ["sample"], "valid_time").reset_index(drop=True)
    # 若沒有 init_time 欄位則以第一筆 valid_time 當作初始（近似）
    if init_time is None and not sub.empty:
        init_time = sub['valid_time'].min()
    return sub, init_time

def scrape_jtwc_text_product(track_id: str, jtwc_text_urls: dict | None = None) -> dict:
    """從 JTWC web.txt 文字公報解析颱風名稱、時間、位置與風速；失敗回傳空字典。"""
    urls = jtwc_text_urls if jtwc_text_urls is not None else JTWC_TEXT_URLS
    url = urls.get(track_id)
    if not url:
        print(f"[JTWC] 無對應 web.txt URL: {track_id}")
        return {}
    try:
        print(f"[JTWC] 下載 web.txt: {url}")
        resp = _jtwc_fetch(url, track_id)
        if resp is None:
            return {}
        text = resp.text

        info: dict[str, object] = {}

        # 名稱（支援 SUBJ/TYPHOON、1. TYPHOON、TROPICAL STORM/CYCLONE 等格式）
        name_patterns = [
            r"SUBJ/\s*(?:SUPER\s+)?(?:TROPICAL\s+)?(?:DEPRESSION|STORM|CYCLONE|TYPHOON)\s+\d+[A-Z]?\s*\(([A-Z\-]+)\)",
            r"\b(?:SUPER\s+)?(?:TROPICAL\s+)?(?:DEPRESSION|STORM|CYCLONE|TYPHOON)\s+\d+[A-Z]?\s*\(([A-Z\-]+)\)",
        ]
        for pat in name_patterns:
            m_name = re.search(pat, text, re.IGNORECASE)
            if m_name:
                info['name'] = m_name.group(1).upper()
                break

        # 時間，抓 Z 時戳
        m_time = re.search(r"\b(\d{6})Z\b", text)
        if m_time:
            info['update_time'] = m_time.group(1) + " Z"

        # 位置（支援 "POSITION NEAR ..."、"--- NEAR ..." 等格式）
        m_pos = re.search(
            r"(?:POSITION\s+NEAR|---\s+NEAR|NEAR)\s+([0-9.]+)([NS])\s+([0-9.]+)([EW])",
            text,
            re.IGNORECASE,
        )
        if m_pos:
            lat_val = float(m_pos.group(1))
            lat_hem = m_pos.group(2).upper()
            lon_val = float(m_pos.group(3))
            lon_hem = m_pos.group(4).upper()
            info['latitude'] = f"{lat_val:.1f}°{lat_hem}"
            info['longitude'] = f"{lon_val:.1f}°{lon_hem}"

        # 最大風速
        m_wind = re.search(r"MAX\s+SUSTAINED\s+WINDS\s*[:\-]?\s*(\d+)\s*KT", text, re.IGNORECASE)
        if m_wind:
            info['max_winds_kt'] = int(m_wind.group(1))

        # Gusts
        m_gusts = re.search(r"GUSTS\s+(?:TO\s+)?(\d+)\s*KT", text, re.IGNORECASE)
        if m_gusts:
            info['gusts'] = int(m_gusts.group(1))

        # 最低中心氣壓：警報的 REMARKS 段落寫成
        # "MINIMUM CENTRAL PRESSURE AT 231200Z IS 932 MB"；沒寫就不給，網頁不顯示這張卡
        m_pres = re.search(r"MINIMUM\s+CENTRAL\s+PRESSURE\s+(?:AT\s+\d{6}Z\s+)?IS\s+(\d{3,4})\s*MB",
                           text, re.IGNORECASE)
        if m_pres:
            info['pressure_mb'] = int(m_pres.group(1))

        # 官方預報路徑：每段 "12 HRS, VALID AT:\n 281200Z --- 27.5N 132.6E\n MAX SUSTAINED WINDS - 100 KT"
        # 延伸展望（48～120 小時）格式相同；消散的時段可能沒寫風速，給 None。每點為 [lat, lon, kt, 預報時數]
        track = []
        parts = re.split(r"\b(\d+)\s+HRS,\s+VALID\s+AT:", text)
        for tau, blk in zip(parts[1::2], parts[2::2]):
            m_p = re.search(r"\d{6}Z\s*---\s*(?:NEAR\s+)?([0-9.]+)([NS])\s+([0-9.]+)([EW])", blk)
            if not m_p:
                continue
            la = float(m_p.group(1)) * (-1 if m_p.group(2).upper() == 'S' else 1)
            lo = float(m_p.group(3)) * (-1 if m_p.group(4).upper() == 'W' else 1)
            m_w = re.search(r"MAX\s+SUSTAINED\s+WINDS\s*-\s*(\d+)\s*KT", blk)
            track.append([la, lo, int(m_w.group(1)) if m_w else None, int(tau)])
        if track:
            info['forecast_track'] = track

        if info:
            print(f"[JTWC] 解析成功: {info}")
        else:
            print("[JTWC] 警告: 未能從 web.txt 解析資料")
        return info

    except Exception as e:
        print(f"[JTWC] 錯誤: {e}")
        return {}

def extract_current_info(df: pd.DataFrame) -> dict:
    """Extract current condition from first (earliest) forecast row."""
    if df.empty:
        return {}
    df = df.copy().sort_values('valid_time').reset_index(drop=True)
    row = df.iloc[0]
    wind = row.get('wind', np.nan)
    pressure = row.get('minimum_sea_level_pressure_hpa', np.nan)
    rmw = row.get('radius_of_maximum_winds_km', np.nan)
    r34_ne = row.get('radius_34_knot_winds_ne_km', np.nan)
    r34_se = row.get('radius_34_knot_winds_se_km', np.nan)
    r34_sw = row.get('radius_34_knot_winds_sw_km', np.nan)
    r34_nw = row.get('radius_34_knot_winds_nw_km', np.nan)
    
    return {
        'valid_time': row.get('valid_time'),
        'lat': row.get('lat', np.nan),
        'lon': row.get('lon', np.nan),
        'wind': wind,
        'category': ss_category(wind),
        'pressure': pressure,
        'rmw': rmw,
        'r34_ne': r34_ne,
        'r34_se': r34_se,
        'r34_sw': r34_sw,
        'r34_nw': r34_nw,
    }

def generate_frame_sequence(df: pd.DataFrame, mean_df: pd.DataFrame, init_time: pd.Timestamp, track_id: str, output_dir: str, max_frames: int = 72, model_name: str = "WN2-C r2", det_df: pd.DataFrame | None = None, det_label: str | None = None, mean_name: str | None = None) -> list:
    """生成預報軌跡演變的幀序列，用於網頁動畫生成。與靜態地圖保持一致的風格。

    det_df／det_label 的意義與 plot_forecast_map 相同。

    Returns:
        包含所有生成幀的文件路徑列表
    """
    has_det = det_df is not None and not det_df.empty
    # 計算時間步
    all_times = sorted(pd.concat([df, mean_df])['valid_time'].unique())
    if len(all_times) > max_frames:
        step = len(all_times) // max_frames
        all_times = all_times[::step]

    print(f"[FRAME] 正在生成 {len(all_times)} 幀序列...")

    # 計算地圖範圍（處理國際換日線），並套用與靜態圖一致的比例
    all_lons = list(df['lon']) + list(mean_df['lon'])
    all_lats = list(df['lat']) + list(mean_df['lat'])
    if has_det:
        all_lons += list(det_df['lon'])
        all_lats += list(det_df['lat'])
    extent, use_360 = _auto_extent(all_lats, all_lons, pad_deg=3)
    min_lon, max_lon, min_lat, max_lat = extent
    if min_lat == max_lat:
        min_lat -= 2
        max_lat += 2
    if min_lon == max_lon:
        min_lon -= 2
        max_lon += 2

    target_ar = 1.40
    extent = _fit_extent_to_aspect((min_lon, max_lon, min_lat, max_lat), target_ar, use_360)

    frame_paths = []
    os.makedirs(output_dir, exist_ok=True)

    # 起始位置（全序列共用）
    init_pt = mean_df.sort_values('valid_time').iloc[0]
    init_lon_star = _normalize_lon_values([init_pt['lon']], use_360=use_360)[0]
    init_lat_star = float(init_pt['lat'])

    for frame_idx, current_time in enumerate(all_times):
        # ── 建立畫布 ──────────────────────────────────────────────────────────
        if HAS_CARTOPY:
            fig = plt.figure(figsize=(10, 7), facecolor='white')
            if use_360:
                ax = plt.axes(projection=ccrs.PlateCarree(central_longitude=180))
            else:
                ax = plt.axes(projection=ccrs.PlateCarree())
            _setup_basemap(ax, extent)
            kw = dict(transform=ccrs.PlateCarree())
        else:
            fig = plt.figure(figsize=(10, 7), dpi=100, facecolor='white')
            ax = fig.add_subplot(111)
            _setup_plain_axes(ax, extent, label_size=10)
            kw = {}

        # 平均路徑的截止時間（成員過少就不再畫平均）；圓錐已移除，但截止邏輯沿用
        fh_now = (pd.to_datetime(current_time) - init_time).total_seconds() / 3600.0
        cone_stop_fh = _compute_cone_stop_fh(df, init_time, max_fh=fh_now)

        # ── 起始位置星形標記 ──────────────────────────────────────────────────
        _draw_init_marker(ax, init_lon_star, init_lat_star, kw, scale=0.9)

        # ── 集合成員軌跡 ──────────────────────────────────────────────────────
        for sid, g in df.groupby("sample"):
            g = g[g['valid_time'] <= current_time].sort_values('valid_time')
            if not g.empty:
                _draw_member_track(ax, g, use_360, kw, lw=0.9, alpha=0.75)
                last_pt = g.iloc[-1]
                wind = last_pt.get('wind', np.nan)
                cat = ss_category(wind)
                last_lon = _normalize_lon_values([last_pt['lon']], use_360=use_360)[0]
                _scatter_members(ax, [last_lon], [last_pt['lat']],
                                 [COLOR_MAP.get(cat, COLOR_MAP['Unknown'])], kw,
                                 size=22, alpha=0.9, zorder=1.15, lw=1.0)

        # ── 平均軌跡 + 24h 標記 ───────────────────────────────────────────────
        mean_subset = mean_df[mean_df['valid_time'] <= current_time].sort_values('valid_time')
        if cone_stop_fh is not None:
            cone_stop_time = init_time + pd.to_timedelta(cone_stop_fh, unit='h')
            mean_subset = mean_subset[mean_subset['valid_time'] <= cone_stop_time]
        if not mean_subset.empty:
            mean_lons = _normalize_lon_values(mean_subset["lon"].to_numpy(), use_360=use_360)
            mean_lats = mean_subset["lat"].to_numpy()
            for seg_lon, seg_lat in _split_track_segments(mean_lons, mean_lats):
                ax.plot(seg_lon, seg_lat, color='white', lw=4.6, alpha=0.7,
                        solid_capstyle='round', zorder=2.0, **kw)
                ax.plot(seg_lon, seg_lat, color=MEAN_COLOR, lw=2.8,
                        solid_capstyle='round', zorder=2.2, **kw)
            last_mean_pt = mean_subset.iloc[-1]
            last_mean_lon = _normalize_lon_values([last_mean_pt['lon']], use_360=use_360)[0]
            last_fh = int(round((last_mean_pt['valid_time'] - init_time).total_seconds() / 3600.0))
            last_intensity = _format_intensity_label(last_mean_pt.get('wind', np.nan))
            ax.scatter([last_mean_lon], [last_mean_pt['lat']], marker='o', color=MEAN_COLOR,
                       s=64, ec='white', zorder=5, linewidth=1.4, **kw)
            ax.text(last_mean_lon + LABEL_OFFSET,
                    last_mean_pt['lat'] + LABEL_OFFSET, f'+{last_fh}h\n{last_intensity}',
                    fontsize=6.5, color=TEXT_DARK, fontweight='bold', zorder=6,
                    bbox=_label_box(), clip_on=True, **kw)

            pts_24h_mean = get_24h_markers(mean_subset, init_time)
            if not pts_24h_mean.empty:
                marker_lons = _normalize_lon_values(pts_24h_mean['lon'].to_numpy(), use_360=use_360)
                ax.scatter(marker_lons, pts_24h_mean['lat'], marker='o', s=42, facecolors='white',
                           edgecolors=MEAN_COLOR, linewidths=1.4, zorder=5, **kw)
                # +Nh 時間標籤
                for i, (_, pt) in enumerate(pts_24h_mean.iterrows()):
                    fh = int((pt['valid_time'] - init_time).total_seconds() / 3600)
                    if (fh == 0 or last_fh - fh < 24
                            or np.hypot(marker_lons[i] - last_mean_lon, pt['lat'] - last_mean_pt['lat'])
                            < END_LABEL_CLEAR_DEG):
                        continue
                    ax.text(marker_lons[i] + 0.4, pt['lat'] + 0.4, f'+{fh}h',
                            fontsize=6.5, color=TEXT_DARK, fontweight='bold', zorder=6,
                            path_effects=[mpe.withStroke(linewidth=2.2, foreground='white')],
                            clip_on=True, **kw)
                summary = build_24h_summary(pts_24h_mean, init_time)
                if summary:
                    n_lines = len(summary.splitlines())
                    y_anchor = 0.27 + min(n_lines, 8) * 0.015
                    ax.text(0.985, y_anchor, summary, transform=ax.transAxes, fontsize=6.5,
                            ha='right', va='bottom', color=TEXT_DARK, linespacing=1.35,
                            bbox=_label_box(0.94), zorder=6)

        # ── 決定報軌跡（截至 current_time）────────────────────────────────────
        if has_det:
            _draw_det_track(ax, det_df, init_time, use_360, kw,
                            upto=pd.to_datetime(current_time), label_end=False)

        # ── 圖例 ──────────────────────────────────────────────────────────────
        _track_source_legend(ax, mean_name or model_name, fontsize=8, ms=10,
                             det_label=det_label if has_det else None,
                             intensity_style='marker')


        # ── 標題 ──────────────────────────────────────────────────────────────
        time_str = pd.to_datetime(current_time).strftime('%Y-%m-%d %H:%M UTC')
        init_str = pd.to_datetime(init_time).strftime('%Y-%m-%d %H:%M UTC')
        _set_map_titles(ax,
                        f"{model_name}  ·  {track_id}  Track Evolution",
                        f"Valid {time_str}\nInit {init_str}",
                        main_size=12.5, right_size=8)
        plt.tight_layout(pad=0.6)
        # 幀存 WebP：網頁播放器逐張載入，PNG 一幀 300–800 KB，WebP 約小 3–5 倍、肉眼看不出差別
        frame_path = os.path.join(output_dir, f"frame_{frame_idx:04d}.webp")
        plt.savefig(frame_path, dpi=FRAME_DPI, bbox_inches='tight', facecolor='white', pad_inches=0.12,
                    pil_kwargs={'quality': FRAME_WEBP_QUALITY, 'method': 6})
        frame_paths.append(frame_path)
        plt.close(fig)

        print(f"[FRAME] 已生成第 {frame_idx + 1}/{len(all_times)} 幀")

    return frame_paths


def _compute_cone_stop_fh(df: pd.DataFrame, init_time: pd.Timestamp, max_fh: float = None) -> float | None:
    """Compute the effective cone stop hour used by both cone and mean-track display."""
    if df.empty or init_time is None:
        return None

    work = df.copy()
    work['fh'] = (work['valid_time'] - init_time).dt.total_seconds() / 3600.0
    data_max_fh = float(work['fh'].max())
    if data_max_fh < 12:
        return None

    if max_fh is None:
        max_fh = data_max_fh
    else:
        max_fh = min(float(max_fh), data_max_fh)
    if max_fh < 12:
        return None

    # If max_fh lands on 12h but not 24h, move back to the previous 24h boundary.
    # Example: 36h -> 24h, so cone ending aligns with 24h cadence.
    cone_end_fh = float(max_fh)
    rem12 = np.mod(cone_end_fh, 12.0)
    rem24 = np.mod(cone_end_fh, 24.0)
    if np.isclose(rem12, 0.0, atol=1e-6) and (not np.isclose(rem24, 0.0, atol=1e-6)):
        cone_end_fh = max(0.0, cone_end_fh - 12.0)

    # 門檻取「總成員數的一半」而非固定值：WNC2 是 50 條、WNC3 是 64 條，
    # 寫死 25 會讓兩個模式的鬆緊不一致（50% vs 39%）。
    n_members = int(work['sample'].nunique()) if 'sample' in work.columns else 0
    min_members = max(5, int(np.ceil(n_members * 0.5))) if n_members else 25

    last_ok_t = None
    for t in np.arange(0, cone_end_fh + 1, 12):
        sub = work[abs(work['fh'] - t) < 3.5]
        if len(sub) < min_members:   # 存活成員數不足，視為圓錐終點
            break
        last_ok_t = float(t)

    return last_ok_t




def _draw_det_track(ax, det_df: pd.DataFrame, init_time: pd.Timestamp, use_360: bool, kw: dict,
                    upto: pd.Timestamp | None = None, label_end: bool = True) -> None:
    """畫決定報路徑（實線）—— 靜態圖與動畫幀共用。

    線型與 24 小時圓點標記比照平均路徑，只用顏色區分；刻意不套用平均路徑那套
    「半數成員」截斷：決定報只有一條，跑到哪就畫到哪，截斷反而會讓人以為模式
    提早結束預報。zorder 介於平均路徑（4）與其標記（5）之間，讓平均路徑仍是
    視覺主角。
    """
    if det_df is None or det_df.empty:
        return
    d = det_df.sort_values('valid_time')
    if upto is not None:
        d = d[d['valid_time'] <= upto]
    if d.empty:
        return

    # 決定報可能比系集新一期：24h 圓點與「DET +Nh」照它自己的起報時間算
    if init_time is not None and 'init_time' in d.columns:
        own = pd.to_datetime(d['init_time'].iloc[0], errors='coerce', utc=True)
        if pd.notna(own):
            init_time = own

    lons = _normalize_lon_values(d['lon'].to_numpy(), use_360=use_360)
    lats = d['lat'].to_numpy()
    for seg_lon, seg_lat in _split_track_segments(lons, lats):
        ax.plot(seg_lon, seg_lat, color='white', lw=4.4, alpha=0.7,
                solid_capstyle='round', zorder=2.25, **kw)
        ax.plot(seg_lon, seg_lat, color=DET_COLOR, lw=2.6,
                solid_capstyle='round', zorder=2.35, **kw)

    # 每 24 小時的空心圓點（與平均路徑同款，僅顏色不同）
    if init_time is not None:
        pts_24h_det = get_24h_markers(d, init_time)
        if not pts_24h_det.empty:
            det_marker_lons = _normalize_lon_values(pts_24h_det['lon'].to_numpy(), use_360=use_360)
            ax.scatter(det_marker_lons, pts_24h_det['lat'].to_numpy(), marker='o', s=42,
                       facecolors='white', edgecolors=DET_COLOR, linewidths=1.4,
                       zorder=4.5, **kw)

    last = d.iloc[-1]
    last_lon = _normalize_lon_values([last['lon']], use_360=use_360)[0]
    ax.scatter([last_lon], [last['lat']], marker='D', color=DET_COLOR, s=42,
               ec='white', zorder=4.6, linewidth=1.2, **kw)
    if label_end and init_time is not None:
        fh = int(round((last['valid_time'] - init_time).total_seconds() / 3600.0))
        ax.text(last_lon + LABEL_OFFSET, last['lat'] - LABEL_OFFSET,
                f'DET +{fh}h', fontsize=6.5, color=DET_COLOR, fontweight='bold',
                zorder=6, bbox=_label_box(), clip_on=True, **kw)


# ── 侵襲機率（strike probability）─────────────────────────────────────────
# 每個 0.1° 格點：路徑曾通過其 1° 內的成員比例。距離用經緯度度數算（與常見的
# 「1° track buffer」產品一致），高緯經度方向會略窄於 111 km。
STRIKE_RES = 0.1
STRIKE_RADIUS_DEG = 1.0
STRIKE_LEVELS = [1, 10, 20, 30, 40, 50, 60, 70, 80, 90]
STRIKE_COLORS = ['#A9D6F5', '#5E9DDB', '#3B6DB3', '#3F9C55', '#9CC64E',
                 '#EFD35A', '#EBA03E', '#D9463A', '#9E2A22']
STRIKE_OVER = '#C451D3'    # > 90 %
STRIKE_FIG_AR = 1.25


def _densify_track(lons, lats, hours=None, step: float = STRIKE_RES / 2):
    """把路徑加密到每步 < step 度；有 hours 時一併線性內插時間。NaN 點先剔除。"""
    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)
    ok = ~(np.isnan(lons) | np.isnan(lats))
    hrs = None if hours is None else np.asarray(hours, dtype=float)[ok]
    lons, lats = lons[ok], lats[ok]
    if lons.size < 2:
        return lons, lats, hrs
    seg = np.hypot(np.diff(lons), np.diff(lats))
    n = np.maximum(1, np.ceil(seg / step).astype(int))

    def _fill(v):
        return np.concatenate([np.linspace(v[i], v[i + 1], n[i], endpoint=False)
                               for i in range(len(n))] + [v[-1:]])
    return _fill(lons), _fill(lats), (None if hrs is None else _fill(hrs))


def compute_strike_probability(tracks: list, extent: tuple, n_total: int | None = None):
    """tracks 為 [(lons, lats), ...]（經度須已依 use_360 正規化），回傳 (glon, glat, prob%)。

    每條路徑先加密到每步 < 半格，在成員自己的外框內做距離轉換（≤ 半徑格數即命中），
    一個成員對同一格最多算一次。只算外框是為了 1000 成員也能在十秒內跑完。
    """
    from scipy.ndimage import distance_transform_edt  # type: ignore
    lon0, lon1, lat0, lat1 = extent
    r = int(round(STRIKE_RADIUS_DEG / STRIKE_RES))
    # 網格外圍多留 r 格：範圍外的路徑點也能把 1° 影響圈帶進來
    gx0, gy0 = lon0 - r * STRIKE_RES, lat0 - r * STRIKE_RES
    nx = int(round((lon1 - lon0) / STRIKE_RES)) + 1 + 2 * r
    ny = int(round((lat1 - lat0) / STRIKE_RES)) + 1 + 2 * r
    count = np.zeros((ny, nx), dtype=np.int32)
    for lons, lats, *_ in tracks:
        xs, ys, _ = _densify_track(lons, lats)
        if xs.size == 0:
            continue
        ix = np.round((xs - gx0) / STRIKE_RES).astype(int)
        iy = np.round((ys - gy0) / STRIKE_RES).astype(int)
        inside = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny)
        if not inside.any():
            continue
        ix, iy = ix[inside], iy[inside]
        x0, x1 = max(ix.min() - r - 1, 0), min(ix.max() + r + 2, nx)
        y0, y1 = max(iy.min() - r - 1, 0), min(iy.max() + r + 2, ny)
        mask = np.ones((y1 - y0, x1 - x0), dtype=bool)
        mask[iy - y0, ix - x0] = False
        count[y0:y1, x0:x1] += distance_transform_edt(mask) <= r
    prob = count[r:-r, r:-r] * 100.0 / max(n_total or len(tracks), 1)
    glon = lon0 + np.arange(prob.shape[1]) * STRIKE_RES
    glat = lat0 + np.arange(prob.shape[0]) * STRIKE_RES
    return glon, glat, prob


# 分時段侵襲機率的時段（h）；None 表示到預報結束
STRIKE_WINDOWS = [(0, 72), (72, 120), (120, None)]
WIND34_COLS = ['radius_34_knot_winds_ne_km', 'radius_34_knot_winds_se_km',
               'radius_34_knot_winds_sw_km', 'radius_34_knot_winds_nw_km']


def window_tracks(tracks: list, t0: float, t1: float | None) -> list:
    """只留 [t0, t1) 時段內的路徑片段（先加密再切，切點落在時段邊界附近）。"""
    out = []
    for x, y, h in tracks:
        xs, ys, hs = _densify_track(x, y, h)
        if xs.size == 0:
            out.append((xs, ys))
            continue
        m = (hs >= t0) & ((hs < t1) if t1 is not None else True)
        out.append((xs[m], ys[m]))
    return out


def compute_wind34_probability(members: list, extent: tuple, n_total: int) -> tuple:
    """34 kt 暴風圈侵襲機率：格點曾落在成員 34 kt 暴風半徑（四象限）內的成員比例。

    members = [(lons, lats, hours, r_ne, r_se, r_sw, r_nw), ...]，半徑單位 km、NaN／0
    表示未達 34 kt。每 3 h 內插一點，每點只在半徑涵蓋的小窗內計算，1000 成員也跑得動。
    """
    lon0, lon1, lat0, lat1 = extent
    nx = int(round((lon1 - lon0) / STRIKE_RES)) + 1
    ny = int(round((lat1 - lat0) / STRIKE_RES)) + 1
    glon = lon0 + np.arange(nx) * STRIKE_RES
    glat = lat0 + np.arange(ny) * STRIKE_RES
    count = np.zeros((ny, nx), dtype=np.int32)
    for x, y, h, *radii in members:
        x = np.asarray(x, dtype=float)
        h = np.asarray(h, dtype=float)
        ok = ~(np.isnan(x) | np.isnan(np.asarray(y, dtype=float)) | np.isnan(h))
        if ok.sum() < 1:
            continue
        hh = np.arange(h[ok][0], h[ok][-1] + 1e-6, 3.0)
        xi = np.interp(hh, h[ok], x[ok])
        yi = np.interp(hh, h[ok], np.asarray(y, dtype=float)[ok])
        ri = [np.interp(hh, h[ok], np.nan_to_num(np.asarray(r, dtype=float)[ok], nan=0.0))
              for r in radii]
        hit = np.zeros((ny, nx), dtype=bool)
        for k in range(hh.size):
            rmax = max(r[k] for r in ri)
            if rmax <= 0:
                continue
            coslat = max(np.cos(np.radians(yi[k])), 0.2)
            dlon = rmax / (111.0 * coslat)
            dlat = rmax / 111.0
            ix0 = max(int((xi[k] - dlon - lon0) / STRIKE_RES), 0)
            ix1 = min(int((xi[k] + dlon - lon0) / STRIKE_RES) + 2, nx)
            iy0 = max(int((yi[k] - dlat - lat0) / STRIKE_RES), 0)
            iy1 = min(int((yi[k] + dlat - lat0) / STRIKE_RES) + 2, ny)
            if ix0 >= ix1 or iy0 >= iy1:
                continue
            dx = (glon[ix0:ix1][None, :] - xi[k]) * 111.0 * coslat
            dy = (glat[iy0:iy1][:, None] - yi[k]) * 111.0
            # 象限：NE(dx≥0,dy≥0)、SE(dx≥0,dy<0)、SW(dx<0,dy<0)、NW(dx<0,dy≥0)
            r = np.where(dx >= 0, np.where(dy >= 0, ri[0][k], ri[1][k]),
                         np.where(dy < 0, ri[2][k], ri[3][k]))
            hit[iy0:iy1, ix0:ix1] |= np.hypot(dx, dy) <= r
        count += hit
    return glon, glat, count * 100.0 / max(n_total, 1)


def load_large_ensemble_radii(csv_path: str, track_id: str) -> list:
    """1000 成員某颱風的 34 kt 暴風半徑序列：[(lon360, lat, hours, r_ne, r_se, r_sw, r_nw), ...]。"""
    df = pd.read_csv(csv_path, comment='#').dropna(subset=['lat', 'lon', 'lead_time_hours'])
    if not all(c in df.columns for c in WIND34_COLS):
        return []
    df['track_id'] = df['track_id'].astype(str)
    df['lon360'] = df['lon'] % 360.0
    df = df.sort_values(['track_id', 'sample', 'lead_time_hours'])
    _relink_lost_tracks(df, [t for t in df['track_id'].unique() if not t.isdigit()])
    g = _cut_extratropical(df[df['track_id'] == track_id], ['sample'], 'lead_time_hours')
    return [(t['lon360'].to_numpy(), t['lat'].to_numpy(), t['lead_time_hours'].to_numpy(),
             *(t[c].to_numpy() for c in WIND34_COLS)) for _, t in g.groupby('sample')]


def plot_strike_probability(tracks: list, init_time, track_id: str, save_path: str,
                            model_name: str, n_members: int | None = None,
                            title: str = 'Strike Probability', subtitle: str | None = None,
                            field=None, extent_tracks: list | None = None) -> str | None:
    """畫侵襲機率圖。tracks 為 [(lons, lats[, lead_hours]), ...]（原始經度即可）；回傳存檔路徑或 None。"""
    if not HAS_CARTOPY or not tracks:
        return None
    # 範圍依 extent_tracks（預設 tracks）決定；分時段圖用完整路徑定範圍，三張才對得齊
    ext_src = extent_tracks or tracks
    all_lon = np.concatenate([np.asarray(t[0], dtype=float) for t in ext_src if len(t[0])])
    all_lat = np.concatenate([np.asarray(t[1], dtype=float) for t in ext_src if len(t[1])])
    big, use_360 = _auto_extent(all_lat, all_lon, pad_deg=2)
    big = tuple(float(np.round(v, 1)) for v in big)
    tracks = [(_normalize_lon_values(t[0], use_360=use_360), np.asarray(t[1], dtype=float))
              for t in tracks]
    if field is not None:
        glon, glat, prob = field(big, use_360)
    else:
        glon, glat, prob = compute_strike_probability(tracks, big, n_total=n_members)
    # 顯示範圍用完整路徑的侵襲範圍，分時段、暴風圈各圖才會對齊
    if extent_tracks is not None:
        _, _, ref = compute_strike_probability(
            [(_normalize_lon_values(t[0], use_360=use_360), t[1]) for t in extent_tracks],
            big, n_total=n_members)
        iy, ix = np.nonzero(ref >= STRIKE_LEVELS[0])
    else:
        iy, ix = np.nonzero(prob >= STRIKE_LEVELS[0])
    if iy.size == 0:
        return None
    # 顯示範圍＝機率 ≥1% 區域外擴 4°：零星跑到高緯的成員不會把地圖撐大
    extent = (glon[ix.min()] - 4, glon[ix.max()] + 4, glat[iy.min()] - 4, glat[iy.max()] + 4)
    extent = _fit_extent_to_aspect(extent, STRIKE_FIG_AR, use_360)

    fig = plt.figure(figsize=(10, 7.6), facecolor='white')
    proj = ccrs.PlateCarree(central_longitude=180) if use_360 else ccrs.PlateCarree()
    ax = plt.axes(projection=proj)
    _setup_basemap(ax, extent)
    kw = dict(transform=ccrs.PlateCarree())
    from matplotlib.colors import ListedColormap, BoundaryNorm  # type: ignore
    cmap = ListedColormap(STRIKE_COLORS)
    cmap.set_over(STRIKE_OVER)
    # 色塊半透明、壓在國界（0.6）與海岸線（2.5）底下：陸地灰底與輪廓都透得出來
    cf = ax.contourf(glon, glat, prob, levels=STRIKE_LEVELS, cmap=cmap,
                     norm=BoundaryNorm(STRIKE_LEVELS, cmap.N), extend='max',
                     zorder=0.5, alpha=0.72, **kw)
    # 初始位置取各成員起點的中位數
    starts = np.array([(x[0], y[0]) for x, y in tracks if len(x)]) if extent_tracks is None else \
        np.array([(_normalize_lon_values([t[0][0]], use_360=use_360)[0], t[1][0])
                  for t in extent_tracks if len(t[0])])
    _draw_init_marker(ax, float(np.median(starts[:, 0])), float(np.median(starts[:, 1])),
                      kw, scale=0.9)

    cb = fig.colorbar(cf, ax=ax, orientation='horizontal', pad=0.06, fraction=0.045,
                      aspect=40, shrink=0.8, ticks=[1, 20, 40, 60, 80, 90])
    cb.set_label(f"{title.split('  ')[0]} (%)", color=TEXT_MUTED, fontsize=9)
    cb.ax.tick_params(labelsize=8, colors=TEXT_DARK)
    cb.outline.set_edgecolor(BOX_EDGE)

    n = n_members if n_members is not None else len(tracks)
    init_str = pd.to_datetime(init_time).strftime('%Y-%m-%d %H:%M UTC')
    # 主標題＋灰色副標，兩行都靠左；副標貼在軸框正上方，主標題用 pad 讓出一行
    ax.set_title(f"{model_name}  ·  {track_id}  {title}", loc='left',
                 fontsize=15, fontweight='bold', color=TEXT_DARK, pad=24)
    ax.text(0, 1.012, f"Init {init_str}  ·  {n} members  ·  " + (subtitle or
            f"{STRIKE_RADIUS_DEG:g}° track buffer  ·  {STRIKE_RES:g}° grid"),
            transform=ax.transAxes, ha='left', va='bottom', fontsize=9.5, color=TEXT_MUTED)
    _watermark(ax, side='right')
    plt.savefig(save_path, dpi=FIG_DPI, bbox_inches='tight', facecolor='white', pad_inches=0.12)
    plt.close(fig)
    print(f"[STRIKE] 已儲存侵襲機率圖：{save_path}")
    return save_path


# 城市侵襲機率表的城市：(key, 緯度, 經度, 是否一律列出)。臺灣城市一律列出，
# 其餘只在任一模式 ≥ 1% 時列出（由網頁端判斷）。中英文名稱在網頁的 i18n 表。
STRIKE_CITIES = [
    ('taipei', 25.04, 121.56, True), ('taichung', 24.15, 120.67, True),
    ('kaohsiung', 22.62, 120.30, True), ('hualien', 23.98, 121.60, True),
    ('hengchun', 22.00, 120.74, True),
    ('naha', 26.21, 127.68, False), ('manila', 14.60, 120.98, False),
    ('hongkong', 22.30, 114.17, False), ('xiamen', 24.48, 118.09, False),
    ('shanghai', 31.23, 121.47, False), ('seoul', 37.57, 126.98, False),
    ('tokyo', 35.68, 139.69, False), ('guam', 13.44, 144.79, False),
]


# 臺灣本島簡化輪廓（經度, 緯度）：data/taiwan_main_island.json 讀不到時的備援
# （與實際海岸線最大偏差約 12 km）。離島（澎湖、金馬、蘭嶼）不算本島登陸。
TAIWAN_OUTLINE = [
    (121.54, 25.30), (121.93, 25.02), (121.87, 24.60), (121.60, 24.00), (121.50, 23.50),
    (121.15, 22.75), (120.89, 22.30), (120.85, 21.90), (120.70, 21.95), (120.62, 22.30),
    (120.28, 22.55), (120.10, 23.00), (120.10, 23.40), (120.20, 23.80), (120.40, 24.30),
    (120.75, 24.75), (121.00, 25.05), (121.40, 25.20),
]


_TAIWAN_PATH = None


def _taiwan_path():
    """臺灣本島輪廓的 matplotlib Path。

    優先讀 data/taiwan_main_island.json（Natural Earth 1:10m 本島，簡化到 0.01°，
    與原始海岸線最大偏差約 1 km）；檔案讀不到才退回上面的 18 點簡化輪廓（偏差約 12 km）。
    """
    global _TAIWAN_PATH
    if _TAIWAN_PATH is None:
        import json
        from matplotlib.path import Path as _MplPath  # type: ignore
        pts = TAIWAN_OUTLINE
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'taiwan_main_island.json')
            with open(p, encoding='utf-8') as fh:
                pts = [tuple(xy) for xy in json.load(fh)['lonlat']]
        except Exception as e:
            print(f"[LANDFALL] 讀不到臺灣輪廓檔，改用簡化輪廓: {e}")
        _TAIWAN_PATH = _MplPath(pts)
    return _TAIWAN_PATH


def taiwan_landfall_stats(tracks: list, init_time, n_total: int | None = None) -> dict:
    """路徑中心進入臺灣本島的成員比例與首次登陸時間中位數（格式同 city_strike_stats）。"""
    poly = _taiwan_path()
    first = []
    for x, y, h in tracks:
        xs, ys, hs = _densify_track(np.asarray(x, dtype=float) % 360.0, y, h)
        if xs.size == 0:
            continue
        inside = poly.contains_points(np.column_stack([xs, ys]))
        if inside.any():
            first.append(float(hs[np.argmax(inside)]))
    p = len(first) * 100.0 / max(n_total or len(tracks), 1)
    eta = None
    if first:
        eta = (pd.to_datetime(init_time) + pd.to_timedelta(float(np.median(first)), unit='h')
               ).strftime('%Y-%m-%dT%H:%MZ')
    return {'p': round(p, 1), 'eta': eta}


def city_strike_stats(tracks: list, init_time, n_total: int | None = None) -> dict:
    """各城市的侵襲機率與預估影響時間。

    tracks 為 [(lons, lats, lead_hours), ...]。侵襲的定義與侵襲機率圖相同（路徑通過
    城市 STRIKE_RADIUS_DEG 內）；影響時間取各侵襲成員「第一次進入範圍」時間的中位數。
    n_total 為分母（預設 len(tracks)）；大系集裡沒有這顆颱風的成員也要算進去。
    回傳 {key: {'p': 百分比, 'eta': 'YYYY-MM-DDTHH:MMZ' 或 None}}。
    """
    init = pd.to_datetime(init_time)
    dense = [_densify_track(x, y, h) for x, y, h in tracks]
    # 第一列放「登陸臺灣」（網頁依 dict 順序排列）
    out = {'tw_landfall': taiwan_landfall_stats(tracks, init_time, n_total=n_total)}
    for key, clat, clon, _ in STRIKE_CITIES:
        first = []
        for xs, ys, hs in dense:
            if xs.size == 0:
                continue
            # 經度差折回 ±180，跨換日線或 0–360／±180 混用都算得對
            dx = (xs - clon + 180.0) % 360.0 - 180.0
            hit = np.hypot(dx, ys - clat) <= STRIKE_RADIUS_DEG
            if hit.any():
                first.append(float(hs[np.argmax(hit)]))
        p = len(first) * 100.0 / max(n_total or len(tracks), 1)
        eta = None
        if first:
            eta = (init + pd.to_timedelta(float(np.median(first)), unit='h')).strftime('%Y-%m-%dT%H:%MZ')
        out[key] = {'p': round(p, 1), 'eta': eta}
    # 預報長度：IFS 06Z／18Z 只跑 144 h，颱風還沒到就結束時 <1% 不代表「不會來」，
    # 網頁在表頭標出來
    hs = [float(np.nanmax(h)) for _, _, h in tracks if len(h)]
    out['_max_h'] = int(round(max(hs))) if hs else None
    out['_init'] = init.strftime('%m/%d %HZ')   # 表頭顯示起報時間，各模式不一定同一期
    return out


def _member_tracks(df: pd.DataFrame, init_time=None) -> list:
    """paired 系集 DataFrame → [(lons, lats), ...]，每個成員一條、依時間排序。

    給 init_time 時多回傳預報時數：[(lons, lats, lead_hours), ...]。
    """
    out = []
    for _, g in df.sort_values('valid_time').groupby('sample'):
        if init_time is None:
            out.append((g['lon'].to_numpy(), g['lat'].to_numpy()))
        else:
            hrs = (pd.to_datetime(g['valid_time']) - pd.to_datetime(init_time)).dt.total_seconds() / 3600.0
            out.append((g['lon'].to_numpy(), g['lat'].to_numpy(), hrs.to_numpy()))
    return out


def load_large_ensemble_tracks(csv_path: str) -> tuple[dict, pd.Timestamp, int, dict]:
    """讀 1000 成員 cyclogenesis CSV，回傳 (路徑, init_time, 成員總數, 強度序列)。

    路徑為 {track_id: [(lons, lats, lead_hours), ...]}，強度序列為
    {track_id: [(hours, wind, mslp), ...]}（給強度羽狀圖）。

    已命名系統先用 _relink_lost_tracks 接回追蹤器跟丟後重新編號的路徑，與路徑聚類圖
    的成員認定一致。分母用全部成員數：沒有這顆颱風的成員就是「沒侵襲」。
    """
    df = pd.read_csv(csv_path, comment='#').dropna(subset=['lat', 'lon', 'lead_time_hours'])
    df['track_id'] = df['track_id'].astype(str)
    df['lon360'] = df['lon'] % 360.0
    df = df.sort_values(['track_id', 'sample', 'lead_time_hours'])
    named = [t for t in df['track_id'].unique() if not t.isdigit()]
    _relink_lost_tracks(df, named)
    df = df.sort_values(['track_id', 'sample', 'lead_time_hours'])
    named_df = _cut_extratropical(df[df['track_id'].isin(named)], ['track_id', 'sample'], 'lead_time_hours')
    out = {tid: [(t['lon360'].to_numpy(), t['lat'].to_numpy(), t['lead_time_hours'].to_numpy())
                 for _, t in g.groupby('sample')]
           for tid, g in named_df.groupby('track_id')}
    d = named_df.rename(columns={'maximum_sustained_wind_speed_knots': 'wind',
                                 'lead_time_hours': '_h'})
    series = {tid: _member_series([t for _, t in g.groupby('sample')])
              for tid, g in d.groupby('track_id')}
    return out, pd.to_datetime(df['init_time'].iloc[0], utc=True), int(df['sample'].nunique()), series


# ── 強度羽狀圖 ───────────────────────────────────────────────────────────
RI_KT = 30.0          # 快速增強門檻：24 h 內增強 ≥ 30 kt（JTWC／NHC 常用定義）
RI_WINDOW_H = 24.0
PLUME_MEMBER_COLOR = '#5B7A99'
PLUME_BAND_COLOR = '#3B6DB3'
# 強度區間（kt）：與 ss_category 的門檻一致，畫成背景色帶
INTENSITY_BANDS = [('TD', 0, 35), ('TS', 35, 64), ('Cat1', 64, 83), ('Cat2', 83, 96),
                   ('Cat3', 96, 113), ('Cat4', 113, 137), ('Cat5', 137, 200)]


def _member_series(groups: list) -> list:
    """[(hours, wind, mslp), ...]：每個成員一組 numpy 陣列（mslp 可能全為 NaN）。"""
    out = []
    for g in groups:
        h = g['_h'].to_numpy(dtype=float)
        w = (g['wind'] if 'wind' in g.columns else pd.Series(np.nan, index=g.index)).to_numpy(dtype=float)
        p = (g['minimum_sea_level_pressure_hpa'] if 'minimum_sea_level_pressure_hpa' in g.columns
             else pd.Series(np.nan, index=g.index)).to_numpy(dtype=float)
        out.append((h, w, p))
    return out


def rapid_intensification_prob(series: list, n_total: int | None = None) -> float | None:
    """成員中「任一 24 h 內增強 ≥ RI_KT」的比例（%）；沒有風速資料時回 None。"""
    n_ri, n_valid = 0, 0
    for h, w, _ in series:
        ok = ~np.isnan(w)
        h, w = h[ok], w[ok]
        if h.size < 2:
            continue
        n_valid += 1
        grid = np.arange(h[0], h[-1] + 1e-6, 6.0)
        wi = np.interp(grid, h, w)
        k = int(round(RI_WINDOW_H / 6.0))
        if wi.size > k and np.max(wi[k:] - wi[:-k]) >= RI_KT:
            n_ri += 1
    if n_valid == 0:
        return None
    return n_ri * 100.0 / max(n_total or len(series), 1)


def _plume_panel(ax, series, idx, init, n_members, ylabel, alpha):
    """畫一個羽狀圖面板（idx=1 風速、2 氣壓）；回傳是否有資料。"""
    has = False
    grid = None
    for s_ in series:
        h, v = s_[0], s_[idx]
        ok = ~np.isnan(v)
        if ok.sum() < 2:
            continue
        has = True
        t = init + pd.to_timedelta(h[ok], unit='h')
        ax.plot(t, v[ok], color=PLUME_MEMBER_COLOR, lw=0.6, alpha=alpha, zorder=2)
        grid = h[ok][-1] if grid is None else max(grid, h[ok][-1])
    if not has:
        return False
    # 百分位只在還有足夠成員存活的時段計算，免得尾端剩幾條時亂跳
    hh = np.arange(0, grid + 1e-6, 6.0)
    vals = np.full((len(series), hh.size), np.nan)
    for i, s_ in enumerate(series):
        h, v = s_[0], s_[idx]
        ok = ~np.isnan(v)
        if ok.sum() < 2:
            continue
        inside = (hh >= h[ok][0]) & (hh <= h[ok][-1])
        vals[i, inside] = np.interp(hh[inside], h[ok], v[ok])
    alive = np.sum(~np.isnan(vals), axis=0)
    keep = alive >= max(5, 0.2 * n_members)
    if keep.any():
        with np.errstate(all='ignore'):
            p10 = np.nanpercentile(vals[:, keep], 10, axis=0)
            p50 = np.nanpercentile(vals[:, keep], 50, axis=0)
            p90 = np.nanpercentile(vals[:, keep], 90, axis=0)
        t = init + pd.to_timedelta(hh[keep], unit='h')
        ax.fill_between(t, p10, p90, color=PLUME_BAND_COLOR, alpha=0.22, lw=0, zorder=3)
        ax.plot(t, p50, color=MEAN_COLOR, lw=2.4, zorder=4)
    ax.set_ylabel(ylabel, color=TEXT_MUTED, fontsize=9)
    ax.grid(True, color=BASEMAP['grid'], lw=0.5, ls=(0, (2, 3)))
    ax.tick_params(colors=TEXT_MUTED, labelsize=8)
    for sp in ax.spines.values():
        sp.set_edgecolor(BOX_EDGE)
    return True


def plot_intensity_plume(series: list, init_time, track_id: str, save_path: str,
                         model_name: str, n_members: int | None = None,
                         det: tuple | None = None, det_name: str | None = None
                         ) -> tuple[str | None, float | None]:
    """強度羽狀圖（上：最大風速、下：中心氣壓）。回傳 (存檔路徑, RI 機率%)。

    det = (hours, wind, mslp) 時另疊一條決定報（琥珀色），RI 機率仍只算系集成員。
    """
    import matplotlib.dates as mdates  # type: ignore
    if not series:
        return None, None
    n = n_members or len(series)
    init = pd.to_datetime(init_time)
    alpha = float(np.clip(12.0 / max(len(series), 1), 0.04, 0.35))
    fig, (ax_w, ax_p) = plt.subplots(2, 1, figsize=(10, 7.2), sharex=True,
                                     gridspec_kw={'height_ratios': [2.2, 1]}, facecolor='white')
    if not _plume_panel(ax_w, series, 1, init, n, 'Max sustained wind (kt)', alpha):
        plt.close(fig)
        return None, None
    ymax = ax_w.get_ylim()[1]
    # 決定報可能比所有成員都強（實測 AIGFS 決定報 >100 kt、成員最高 75 kt），
    # 上限要把它算進去，否則線會衝出圖框
    if det is not None and np.isfinite(det[1]).any():
        ymax = max(ymax, float(np.nanmax(det[1])) * 1.15)   # 多留一截給右上角的圖例
    for cat, lo, hi in INTENSITY_BANDS:
        if lo >= ymax:
            break
        ax_w.axhspan(lo, hi, color=COLOR_MAP[cat], alpha=0.09, lw=0, zorder=1)
        ax_w.text(1.005, (lo + min(hi, ymax)) / 2, cat, transform=ax_w.get_yaxis_transform(),
                  ha='left', va='center', fontsize=7.5, color=COLOR_MAP[cat], fontweight='bold')
    ax_w.set_ylim(0, ymax)
    has_p = _plume_panel(ax_p, series, 2, init, n, 'Min. pressure (hPa)', alpha)
    if not has_p:
        ax_p.text(0.5, 0.5, 'No pressure data', transform=ax_p.transAxes, ha='center',
                  va='center', color=TEXT_MUTED, fontsize=9)

    has_det = det is not None and np.isfinite(det[1]).sum() >= 2
    if has_det:
        for ax_, v in ((ax_w, det[1]), (ax_p, det[2])):
            ok = np.isfinite(v)
            if ok.sum() >= 2:
                ax_.plot(init + pd.to_timedelta(det[0][ok], unit='h'), v[ok], color='white',
                         lw=4.2, alpha=0.9, zorder=4.9)
                ax_.plot(init + pd.to_timedelta(det[0][ok], unit='h'), v[ok], color=DET_COLOR,
                         lw=2.2, zorder=5)
        p = det[2][np.isfinite(det[2])]
        if has_p and p.size:
            lo, hi = ax_p.get_ylim()
            ax_p.set_ylim(min(lo, float(p.min()) - 3), max(hi, float(p.max()) + 3))
    ri = rapid_intensification_prob(series, n_total=n)
    peaks = np.array([np.nanmax(w) for _, w, _ in series if np.isfinite(w).any()])
    info = []
    if ri is not None:
        info.append(f"RI probability (≥{RI_KT:.0f} kt / {RI_WINDOW_H:.0f} h): {ri:.0f}%")
    if peaks.size:
        info.append(f"Peak wind median {np.median(peaks):.0f} kt "
                    f"(10–90%: {np.percentile(peaks, 10):.0f}–{np.percentile(peaks, 90):.0f})")
    if info:
        # 放在標題列右側（軸框外）：不擋到峰值附近的成員線
        ax_w.text(1, 1.015, '\n'.join(info), transform=ax_w.transAxes, ha='right', va='bottom',
                  multialignment='right', fontsize=9, color=TEXT_DARK, linespacing=1.45)
    handles = [mlines.Line2D([], [], color=PLUME_MEMBER_COLOR, lw=1, alpha=0.6),
               mlines.Line2D([], [], color=MEAN_COLOR, lw=2.4),
               mpatches.Patch(color=PLUME_BAND_COLOR, alpha=0.22)]
    labels = ['Members', 'Median', '10–90%']
    if has_det:
        handles.append(mlines.Line2D([], [], color=DET_COLOR, lw=2.2))
        labels.append(det_name or 'Deterministic')
    leg = ax_w.legend(handles, labels, loc='upper right',
                      fontsize=8, ncol=len(labels), handlelength=1.4, columnspacing=1.0, **LEGEND_KW)
    _style_legend(leg)

    ax_p.xaxis.set_major_locator(mdates.DayLocator(interval=1 if len(series) else 1))
    ax_p.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    days = (ax_p.get_xlim()[1] - ax_p.get_xlim()[0])
    if days > 9:
        ax_p.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax_p.set_xlabel('Valid date (UTC)', color=TEXT_MUTED, fontsize=9)

    init_str = init.strftime('%Y-%m-%d %H:%M UTC')
    ax_w.set_title(f"{model_name}  ·  {track_id}  Intensity Forecast", loc='left',
                   fontsize=15, fontweight='bold', color=TEXT_DARK, pad=24)
    ax_w.text(0, 1.015, f"Init {init_str}  ·  {n} members", transform=ax_w.transAxes,
              ha='left', va='bottom', fontsize=9.5, color=TEXT_MUTED)
    ax_p.text(0.995, 0.03, 'By Pillar', transform=ax_p.transAxes, ha='right', va='bottom',
              fontsize=7, style='italic', color=TEXT_MUTED, zorder=10)
    fig.tight_layout(pad=0.6)
    plt.savefig(save_path, dpi=200, bbox_inches='tight', facecolor='white', pad_inches=0.12)
    plt.close(fig)
    print(f"[PLUME] 已儲存強度羽狀圖：{save_path}")
    return save_path, ri


def paired_member_series(df: pd.DataFrame, init_time) -> list:
    """paired 系集 DataFrame → 強度羽狀圖用的 [(hours, wind, mslp), ...]。"""
    d = df.copy()
    d['_h'] = (pd.to_datetime(d['valid_time']) - pd.to_datetime(init_time)).dt.total_seconds() / 3600.0
    return _member_series([g.sort_values('_h') for _, g in d.groupby('sample')])


# ── 預報趨勢（從第一報到最新一報）──────────────────────────────────────
# 這顆颱風所有期數的系集平均路徑疊在一起，看預報一路往哪邊修正。來源合併兩處：
# 下載目錄（只留最近 KEEP_CYCLES 期）與路徑校驗存檔（每期一份、留 VERIF_KEEP_DAYS 天），
# 後者讓颱風壽命超過三天時也能畫到第一報。舊 → 新由淺灰漸深到深海軍藍。
TREND_CMAP_COLORS = ['#7EC4E8', '#4A8FD6', '#5B5BC2', '#3B2F8F']   # 天藍 → 紫藍；最新一報另用深海軍藍
TREND_DET_COLORS = ['#F4C46A', '#E8963A', '#D0622A', '#9C3B12']   # 決定報：金黃 → 赭紅


def _ens_name(cfg: dict) -> str:
    """只有系集的產品用的名稱（AIFS-ENS／ECMWF-ENS）；WN 系列與 GENC 就是 display。"""
    return cfg.get('ens_name') or cfg['display']


def load_trend_means(cfg: dict, cycle, track_id: str, det: bool = False) -> list:
    """這顆颱風在此模式下所有期數的系集平均（det=True 為決定報）：[(init_time, df), ...]，舊 → 新。"""
    src_dir = cfg.get("det_dir") if det else cfg["mean_dir"]
    suffix = "deterministic" if det else "paired"
    if det and not (src_dir and cfg.get("det_name")):
        return []
    found = {}
    # ① 路徑校驗存檔：lead_h → valid_time
    name = cfg['det_name'] if det else _ens_name(cfg)
    slugs = [str(n).replace(' ', '~') for n in
             [name] + [old for old, new in VERIF_LEGACY_NAMES.items() if new == name]]
    fdir = os.path.join(VERIF_DIR, 'fcst')
    if os.path.isdir(fdir):
        for fname in os.listdir(fdir):
            m = re.match(rf"(?:{'|'.join(map(re.escape, slugs))})_{re.escape(track_id)}_(\d{{10}})\.csv$", fname)
            if not m:
                continue
            it = pd.Timestamp(datetime.strptime(m.group(1), '%Y%m%d%H'), tz='UTC')
            try:
                f = pd.read_csv(os.path.join(fdir, fname)).dropna()
            except Exception:
                continue
            f = _cut_extratropical(f, [], 'lead_h')
            if f.empty:
                continue
            found[it] = pd.DataFrame({'valid_time': it + pd.to_timedelta(f['lead_h'], unit='h'),
                                      'lat': f['lat'], 'lon': f['lon']})
    # ② 下載目錄（含本期；同一期以下載檔為準，資料較完整）
    name_re = re.compile(rf"^{re.escape(cfg['local_prefix'])}_\d{{4}}_\d{{2}}_\d{{2}}T\d{{2}}_00_{suffix}\.csv$")
    for name in sorted(os.listdir(src_dir)) if os.path.isdir(src_dir) else []:
        if not name_re.match(name):
            continue
        try:
            mdf, it = load_forecast_dataframe(os.path.join(src_dir, name), track_id)
        except Exception:
            continue    # 該期沒有這顆颱風（還沒生成或已消散）
        if not mdf.empty and it is not None:
            found[pd.to_datetime(it)] = mdf
    cyc = pd.Timestamp(cycle).tz_convert('UTC') if pd.Timestamp(cycle).tzinfo else pd.Timestamp(cycle, tz='UTC')
    return [(it, found[it]) for it in sorted(found) if it <= cyc]


def plot_track_trend(entries: list, track_id: str, save_path: str, model_name: str,
                     colors: list = TREND_CMAP_COLORS, latest_color: str = MEAN_COLOR,
                     track_kind: str = 'Ensemble mean') -> str | None:
    """所有期數的路徑疊圖（系集平均或決定報）；少於兩期時不畫（回 None）。"""
    import matplotlib.dates as mdates  # type: ignore
    from matplotlib.colors import LinearSegmentedColormap, Normalize  # type: ignore
    if len(entries) < 2:
        return None
    all_lons = np.concatenate([e[1]['lon'].to_numpy() for e in entries])
    all_lats = np.concatenate([e[1]['lat'].to_numpy() for e in entries])
    extent, use_360 = _auto_extent(all_lats, all_lons, pad_deg=3)
    extent = _fit_extent_to_aspect(extent, FIG_AR, use_360)
    if HAS_CARTOPY:
        fig = plt.figure(figsize=(10, 7.6), facecolor='white')
        proj = ccrs.PlateCarree(central_longitude=180) if use_360 else ccrs.PlateCarree()
        ax = plt.axes(projection=proj)
        _setup_basemap(ax, extent)
        kw = dict(transform=ccrs.PlateCarree())
    else:
        fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=FIG_DPI, facecolor='white')
        ax = fig.add_subplot(111)
        _setup_plain_axes(ax, extent)
        kw = {}

    cmap = LinearSegmentedColormap.from_list('trend', colors)
    tnum = [mdates.date2num(pd.to_datetime(it)) for it, _ in entries]
    norm = Normalize(tnum[0], tnum[-1])
    for k, ((it, mdf), tn) in enumerate(zip(entries, tnum)):
        mdf = mdf.sort_values('valid_time')
        lons = _normalize_lon_values(mdf['lon'].to_numpy(), use_360=use_360)
        lats = mdf['lat'].to_numpy()
        newest = k == len(entries) - 1
        color = latest_color if newest else cmap(norm(tn))
        for seg_lon, seg_lat in _split_track_segments(lons, lats):
            if newest:
                ax.plot(seg_lon, seg_lat, color='white', lw=4.4, alpha=0.7,
                        solid_capstyle='round', zorder=2.2, **kw)
            ax.plot(seg_lon, seg_lat, color=color, lw=2.6 if newest else 1.6,
                    alpha=1.0, solid_capstyle='round',
                    zorder=2.3 if newest else 2.1, **kw)
        if newest:
            pts = get_24h_markers(mdf, it)
            if not pts.empty:
                ax.scatter(_normalize_lon_values(pts['lon'].to_numpy(), use_360=use_360), pts['lat'],
                           marker='o', s=34, facecolors='white', edgecolors=latest_color,
                           linewidths=1.4, zorder=5, **kw)

    first_s = pd.to_datetime(entries[0][0]).strftime('%m/%d %HZ')
    last_s = pd.to_datetime(entries[-1][0]).strftime('%m/%d %HZ')
    handles = [mlines.Line2D([], [], color=latest_color, lw=2.6, marker='o', ms=5,
                             markerfacecolor='white', markeredgecolor=latest_color),
               mlines.Line2D([], [], color=cmap(0.5), lw=1.6)]
    leg = ax.legend(handles, [f'Latest  {last_s}', f'Earlier cycles (from {first_s})'],
                    loc='upper left', fontsize=9, borderpad=0.7, labelspacing=0.42,
                    handlelength=2.0, **LEGEND_KW)
    _style_legend(leg)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = fig.colorbar(sm, ax=ax, orientation='horizontal', pad=0.06, fraction=0.04,
                      aspect=45, shrink=0.8)
    # 刻度只標真的有資料的起報時間：期數多時等距挑（最多約 8 個，頭尾一定標），
    # 每一期另畫小刻度。最後兩個標籤太近時拿掉倒數第二個，免得字疊在一起
    step = max(1, int(np.ceil((len(tnum) - 1) / 7)))
    idx = list(range(0, len(tnum), step))
    if idx[-1] != len(tnum) - 1:
        if len(idx) > 1:
            idx.pop()
        idx.append(len(tnum) - 1)
    cb.set_ticks([tnum[i] for i in idx])
    cb.ax.xaxis.set_ticks(tnum, minor=True)
    cb.ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %HZ'))
    cb.set_label('Init time (older → newer)', color=TEXT_MUTED, fontsize=9)
    cb.ax.tick_params(labelsize=8, colors=TEXT_DARK)
    cb.outline.set_edgecolor(BOX_EDGE)

    ax.set_title(f"{model_name}  ·  {track_id}  Track Trend", loc='left',
                 fontsize=15, fontweight='bold', color=TEXT_DARK, pad=24)
    ax.text(0, 1.012, f"{track_kind} tracks of all {len(entries)} cycles  ·  {first_s} → {last_s}  ·  "
            "Hollow dots = 24-hr steps of the latest", transform=ax.transAxes,
            ha='left', va='bottom', fontsize=9.5, color=TEXT_MUTED)
    _watermark(ax, side='right')
    plt.savefig(save_path, dpi=200, bbox_inches='tight', facecolor='white', pad_inches=0.12)
    plt.close(fig)
    print(f"[TREND] 已儲存趨勢圖：{save_path}（{len(entries)} 期）")
    return save_path


# ── 路徑校驗（模式成績單）──────────────────────────────────────────────
# 每輪把各模式系集平均與 JTWC 警報位置（當作實況）存成小 CSV（JTWC 官方預報不比），
# 預報時間到了再比對路徑誤差。放在 docs/ 底下，雲端 commit docs/ 時一併保存。
VERIF_DIR = os.path.join(OUTPUT_DIR, 'verification')
VERIF_LEADS = [24, 48, 72, 96, 120]
VERIF_MATCH_H = 1.5       # 實況時間與預報時間最多差多少小時算對得上
VERIF_KEEP_DAYS = 90
# 改名前存下的校驗檔用舊顯示名稱；讀回時對應到新名稱，成績與趨勢才不會斷成兩段
VERIF_LEGACY_NAMES = {'AIFS': 'AIFS-ENS', 'ECMWF': 'ECMWF-ENS'}


def _jtwc_warning_time(jtwc: dict, now: datetime | None = None) -> pd.Timestamp | None:
    """JTWC 'DDHHMM Z' → 完整 UTC 時間；月份取不晚於現在、最接近的那個月。"""
    m = re.match(r"(\d{2})(\d{2})(\d{2})", str(jtwc.get('update_time', '')))
    if not m:
        return None
    day, hh, mm = (int(x) for x in m.groups())
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    for back in range(0, 2):
        y, mo = now.year, now.month - back
        if mo < 1:
            y, mo = y - 1, 12
        try:
            t = pd.Timestamp(year=y, month=mo, day=day, hour=hh, minute=mm, tz='UTC')
        except ValueError:
            continue
        if t <= now + pd.Timedelta(hours=6):
            return t
    return None


def _parse_latlon(txt: str) -> float | None:
    m = re.match(r"([0-9.]+)°?([NSEW])", str(txt))
    if not m:
        return None
    v = float(m.group(1))
    return -v if m.group(2) in 'SW' else v


def archive_verification(storms: list) -> None:
    """存本輪的預報與 JTWC 實況；已存在的檔案不覆寫（同一期只留第一份）。"""
    fdir, odir = os.path.join(VERIF_DIR, 'fcst'), os.path.join(VERIF_DIR, 'obs')
    os.makedirs(fdir, exist_ok=True)
    os.makedirs(odir, exist_ok=True)
    seen_jtwc = set()
    for s in storms:
        tid, mdf, it = s['track_id'], s.get('mean_df'), s.get('init_time')
        model = s.get('ens_name') or s.get('model')     # 存的是系集平均
        if mdf is not None and not mdf.empty and it is not None:
            slug = str(model).replace(' ', '~')   # 檔名不放空格
            p = os.path.join(fdir, f"{slug}_{tid}_{pd.to_datetime(it):%Y%m%d%H}.csv")
            if not os.path.exists(p):
                lead = (pd.to_datetime(mdf['valid_time']) - pd.to_datetime(it)).dt.total_seconds() / 3600.0
                pd.DataFrame({'lead_h': lead.round(2), 'lat': mdf['lat'].round(3),
                              'lon': mdf['lon'].round(3)}).to_csv(p, index=False)
        # 決定報可能比系集新一期，存檔與時距都照它自己的起報時間
        ddf, dname, dit = s.get('det_df'), s.get('det_name'), s.get('det_init_time') or it
        if ddf is not None and not ddf.empty and dname and dit is not None:
            p = os.path.join(fdir, f"{str(dname).replace(' ', '~')}_{tid}_{pd.to_datetime(dit):%Y%m%d%H}.csv")
            if not os.path.exists(p):
                lead = (pd.to_datetime(ddf['valid_time']) - pd.to_datetime(dit)).dt.total_seconds() / 3600.0
                pd.DataFrame({'lead_h': lead.round(2), 'lat': ddf['lat'].round(3),
                              'lon': ddf['lon'].round(3)}).to_csv(p, index=False)
        jt = (s.get('current_info') or {}).get('jtwc') or {}
        if not jt or tid in seen_jtwc:
            continue
        seen_jtwc.add(tid)
        wt = _jtwc_warning_time(jt)
        lat, lon = _parse_latlon(jt.get('latitude')), _parse_latlon(jt.get('longitude'))
        if wt is None or lat is None or lon is None:
            continue
        # 實況：同一時間只留一筆
        op = os.path.join(odir, f"{tid}.csv")
        obs = pd.read_csv(op) if os.path.exists(op) else pd.DataFrame(columns=['time', 'lat', 'lon', 'wind'])
        key = wt.strftime('%Y-%m-%dT%H:%MZ')
        if key not in set(obs['time'].astype(str)):
            obs.loc[len(obs)] = [key, lat, lon, jt.get('max_winds_kt')]
            obs.sort_values('time').to_csv(op, index=False)
    # 太舊的檔清掉，目錄不會無限長大
    cutoff = datetime.now(timezone.utc) - timedelta(days=VERIF_KEEP_DAYS)
    for d in (fdir, odir):
        for name in os.listdir(d):
            fp = os.path.join(d, name)
            try:
                if datetime.fromtimestamp(os.path.getmtime(fp), timezone.utc) < cutoff:
                    os.remove(fp)
            except OSError:
                pass


def archive_noaa_backfill(storms: list) -> None:
    """把 NOAA 補抓到的前幾期也存進校驗檔（已存在的不覆寫）。

    同質樣本要求「這顆颱風出現過的模式全到」，新加入的模式若只從加入那期開始存，
    之前每一期都會因為缺它而整期被踢出同質樣本（JTWC 當初就是這樣被拿掉的）。
    NOMADS 留兩天，補抓的那幾期存進來，缺口就只剩更早、NOMADS 已刪掉的期數。
    """
    fdir = os.path.join(VERIF_DIR, 'fcst')
    os.makedirs(fdir, exist_ok=True)
    tids = {s['track_id'] for s in storms}
    for cfg in MODEL_CONFIGS:
        if cfg.get("fetcher") != "noaa":
            continue
        for src_dir, suffix, name in ((cfg["mean_dir"], "paired", _ens_name(cfg)),
                                      (cfg.get("det_dir"), "deterministic", cfg.get("det_name"))):
            if not (src_dir and name and os.path.isdir(src_dir)):
                continue
            for fn in os.listdir(src_dir):
                if not (fn.startswith(f"{cfg['local_prefix']}_") and fn.endswith(f"_{suffix}.csv")):
                    continue
                init = _cycle_from_stamp(fn)
                if init is None:
                    continue
                try:
                    df = pd.read_csv(os.path.join(src_dir, fn), comment='#')
                except Exception:
                    continue
                for tid in tids & set(df['track_id'].astype(str)):
                    p = os.path.join(fdir, f"{str(name).replace(' ', '~')}_{tid}_{init:%Y%m%d%H}.csv")
                    if os.path.exists(p):
                        continue
                    g = df[df['track_id'].astype(str) == tid].sort_values('lead_time_hours')
                    pd.DataFrame({'lead_h': g['lead_time_hours'].astype(float).round(2),
                                  'lat': g['lat'].round(3), 'lon': g['lon'].round(3)}).to_csv(p, index=False)


def compute_scorecard() -> dict:
    """路徑誤差成績單：{範圍: {'all': {model: {lead: [平均 km, n]}}, 'homog': {...}}}。

    範圍為 track_id，或 '_all'（所有颱風合計）。'all' 用各模式全部校驗得到的預報；
    'homog' 是同質樣本：同一颱風、同一起報時間、同一預報時數上，這顆颱風有出現的
    模式全部都有預報才算進來。各模式碰到的情境相同，平均誤差才能直接比較。
    """
    fdir, odir = os.path.join(VERIF_DIR, 'fcst'), os.path.join(VERIF_DIR, 'obs')
    if not os.path.isdir(fdir) or not os.path.isdir(odir):
        return {}
    obs = {}
    for name in os.listdir(odir):
        if name.endswith('.csv'):
            o = pd.read_csv(os.path.join(odir, name))
            o['t'] = pd.to_datetime(o['time'], utc=True)
            obs[name[:-4]] = o
    recs = []      # (track_id, model, 起報 YYYYmmddHH, 預報時數, 誤差 km)
    seen: set = set()
    for name in sorted(os.listdir(fdir)):
        m = re.match(r"(.+)_((?:WP|CP|EP)\d{6})_(\d{10})\.csv$", name)
        if not m or m.group(2) not in obs:
            continue
        model, tid = m.group(1).replace('~', ' '), m.group(2)
        model = VERIF_LEGACY_NAMES.get(model, model)
        # JTWC 預報不比：存檔起點比模式晚一期，樣本數永遠少一筆，還會把同質樣本擋掉
        if model == 'JTWC':
            continue
        # 改名那一期新舊名稱各存了一份，同一模式／颱風／期數只算一次
        if (model, tid, m.group(3)) in seen:
            continue
        seen.add((model, tid, m.group(3)))
        init = pd.Timestamp(datetime.strptime(m.group(3), '%Y%m%d%H'), tz='UTC')
        f = pd.read_csv(os.path.join(fdir, name)).dropna()
        if len(f) < 2:
            continue
        o = obs[tid]
        for lead in VERIF_LEADS:
            if lead > f['lead_h'].max():
                continue
            target = init + pd.Timedelta(hours=lead)
            dt = (o['t'] - target).abs()
            if dt.empty or dt.min() > pd.Timedelta(hours=VERIF_MATCH_H):
                continue
            ob = o.loc[dt.idxmin()]
            flat = float(np.interp(lead, f['lead_h'], f['lat']))
            # 經度內插前先展開，跨換日線也不會內插到地球另一邊
            flon = float(np.interp(lead, f['lead_h'], np.unwrap(np.radians(f['lon'])) * 180 / np.pi))
            e = float(_haversine_km(ob['lat'], ob['lon'] % 360, flat, flon % 360))
            recs.append((tid, model, m.group(3), lead, e))

    def _agg(rs):
        out: dict = {}
        for _, mdl, _, ld, e in rs:
            out.setdefault(mdl, {}).setdefault(ld, []).append(e)
        return {mdl: {ld: [round(float(np.mean(v)), 0), len(v)] for ld, v in d.items()}
                for mdl, d in out.items()}

    def _homog(rs):
        # 每顆颱風、每個時數各自要求「該颱風出現過的模式全到」：只在某些颱風才有的模式
        # （例如 GENC）不會把其他颱風的樣本整個擋掉。
        # 中途才加入的模式（2026-10-16 加入的 AIGFS／GFS，NOMADS 只補得到兩天）在它
        # 第一期之前不算缺席，否則較早的期數會整期被踢出同質樣本
        present: dict = {}
        cases: dict = {}
        first: dict = {}
        for t, mdl, ini, ld, _ in rs:
            present.setdefault((t, ld), set()).add(mdl)
            cases.setdefault((t, ini, ld), set()).add(mdl)
            first[(t, mdl)] = min(first.get((t, mdl), ini), ini)
        ok = {k for k, ms in cases.items()
              if ms >= {m for m in present[(k[0], k[2])] if first[(k[0], m)] <= k[1]}}
        return [r for r in rs if (r[0], r[2], r[3]) in ok]

    card = {}
    for scope in sorted({r[0] for r in recs}) + (['_all'] if recs else []):
        rs = recs if scope == '_all' else [r for r in recs if r[0] == scope]
        card[scope] = {'all': _agg(rs), 'homog': _agg(_homog(rs))}
    return card


# ── 互動式地圖資料 ───────────────────────────────────────────────────────
# 每顆颱風一個 JSON：各模式成員路徑（每 6 h 一點）與系集平均，給網頁的 Leaflet 地圖。
# 每點為 [lat, lon, 風速 kt 或 null, 預報時數]；座標取到 0.01°，檔案才不會太大。
def _track_points(g: pd.DataFrame, init_time, step_h: float = 6.0) -> list:
    g = g.sort_values('valid_time')
    lead = (pd.to_datetime(g['valid_time']) - pd.to_datetime(init_time)).dt.total_seconds() / 3600.0
    keep = (np.abs(lead / step_h - np.round(lead / step_h)) < 1e-3).to_numpy()
    wind = (g['wind'] if 'wind' in g.columns else pd.Series(np.nan, index=g.index)).to_numpy()
    out = []
    for la, lo, w, h in zip(g['lat'].to_numpy()[keep], g['lon'].to_numpy()[keep],
                            wind[keep], lead.to_numpy()[keep]):
        out.append([round(float(la), 2), round(float(lo), 2),
                    None if pd.isna(w) else int(round(float(w))), int(round(float(h)))])
    return out


def _run_stamp(t) -> str:
    return pd.Timestamp(t).strftime('%Y%m%d%H')


def _archive_tracks(tid: str, init, model: str, fields: dict) -> None:
    """把某模式某一期的路徑點併進 {tid}_Tracks_{YYYYMMDDHH}.json（同一期各模式共用一個檔）。

    只更新給的欄位：決定報比系集早一期上架時，先只寫決定報，系集到了再補成員與平均。
    """
    import json
    path = os.path.join(OUTPUT_DIR, f"{tid}_Tracks_{_run_stamp(init)}.json")
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {'track_id': tid, 'init': pd.Timestamp(init).strftime('%Y-%m-%dT%H:00:00Z'), 'models': {}}
    data['models'].setdefault(model, {}).update(fields)
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, separators=(',', ':'))
    except OSError as e:
        print(f"[HISTORY] 警告: 寫入 {path} 失敗: {e}")


def write_tracks_json(storms: list) -> None:
    """依颱風合併各模式資料寫成 {tid}_Tracks.json，路徑掛在該颱風第一個 storm dict。

    另把各模式這一期的路徑點存進每期一個的 {tid}_Tracks_{YYYYMMDDHH}.json，留最新
    MAP_HISTORY_RUNS + 1 期，期數清單寫在 runs，互動地圖可整排模式一起切到同一期。
    """
    import json
    for tid in dict.fromkeys(s['track_id'] for s in storms):
        group = [s for s in storms if s['track_id'] == tid and s.get('track_points')]
        if not group:
            continue
        for s in group:
            tp = s['track_points']
            fields = {'members': tp['members'], 'mean': tp['mean']}
            if tp.get('det'):
                det_fields = {'det': tp['det'], 'det_name': tp.get('det_name')}
                if _run_stamp(tp['det_init']) == _run_stamp(s['init_time']):
                    fields.update(det_fields)
                else:
                    _archive_tracks(tid, tp['det_init'], s['model'], det_fields)
            _archive_tracks(tid, s['init_time'], s['model'], fields)
        run_re = re.compile(rf"^{tid}_Tracks_(\d{{10}})\.json$")
        stamps = sorted((m.group(1) for m in map(run_re.match, os.listdir(OUTPUT_DIR)) if m), reverse=True)
        for old in stamps[MAP_HISTORY_RUNS + 1:]:
            try:
                os.remove(os.path.join(OUTPUT_DIR, f"{tid}_Tracks_{old}.json"))
            except OSError as e:
                print(f"[HISTORY] 警告: 移除 {tid}_Tracks_{old}.json 失敗: {e}")
        data = {'track_id': tid,
                'init': pd.to_datetime(group[0]['init_time']).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'models': {s['model']: s['track_points'] for s in group},
                'inits': {s['model']: pd.to_datetime(s['init_time']).strftime('%Y-%m-%dT%H:%M:%SZ')
                          for s in group},
                'runs': [datetime.strptime(x, '%Y%m%d%H').strftime('%Y-%m-%dT%H:00:00Z')
                         for x in stamps[:MAP_HISTORY_RUNS + 1]]}
        path = os.path.join(OUTPUT_DIR, f"{tid}_Tracks.json")
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, separators=(',', ':'))
        next(s for s in storms if s['track_id'] == tid)['tracks_json'] = path


def plot_forecast_map(df: pd.DataFrame, mean_df: pd.DataFrame, init_time: pd.Timestamp, track_id: str, save_path: str, model_name: str = "WN2-C r2", det_df: pd.DataFrame | None = None, det_label: str | None = None, mean_name: str | None = None):
    """將各 Ensemble member 的預報路徑畫在地圖上，並標示 Ensemble 平均路徑。

    det_df 有值時（ECMWF／AIFS）再疊一條決定報路徑；det_label 是圖例文字。
    """
    has_det = det_df is not None and not det_df.empty
    # 計算範圍（處理國際換日線）；決定報可能比系集跑得更遠，一併納入
    all_lons = list(df['lon']) + list(mean_df['lon'])
    all_lats = list(df['lat']) + list(mean_df['lat'])
    if has_det:
        all_lons += list(det_df['lon'])
        all_lats += list(det_df['lat'])
    extent, use_360 = _auto_extent(all_lats, all_lons, pad_deg=3)
    min_lon, max_lon, min_lat, max_lat = extent
    if min_lat == max_lat:
        min_lat -= 2; max_lat += 2
    if min_lon == max_lon:
        min_lon -= 2; max_lon += 2
    extent = _fit_extent_to_aspect((min_lon, max_lon, min_lat, max_lat), FIG_AR, use_360)

    cone_stop_fh = _compute_cone_stop_fh(df, init_time)
    if cone_stop_fh is not None:
        cone_stop_time = init_time + pd.to_timedelta(cone_stop_fh, unit='h')
        mean_plot_df = mean_df[mean_df['valid_time'] <= cone_stop_time].copy()
    else:
        mean_plot_df = mean_df.copy()

    # 建立畫布：有 Cartopy 用地圖投影，否則退回簡易經緯度圖；
    # 之後的繪圖程式碼透過 kw（transform）共用同一份。
    if HAS_CARTOPY:
        fig = plt.figure(figsize=(10, 7), facecolor='white')
        # 跨越換日線時，使用中心在 180° 的投影
        proj = ccrs.PlateCarree(central_longitude=180) if use_360 else ccrs.PlateCarree()
        ax = plt.axes(projection=proj)
        _setup_basemap(ax, extent)
        kw = dict(transform=ccrs.PlateCarree())
    else:
        fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=FIG_DPI, facecolor='white')
        ax = fig.add_subplot(111)
        _setup_plain_axes(ax, extent)
        kw = {}

    # 每個 member：依強度著色的細線
    for _sid, g in df.groupby("sample"):
        _draw_member_track(ax, g.sort_values('valid_time'), use_360, kw,
                           lw=0.9, alpha=0.75)

    # 起始位置星形標記
    if not mean_df.empty:
        init_pt = mean_df.sort_values('valid_time').iloc[0]
        init_lon_star = _normalize_lon_values([init_pt['lon']], use_360=use_360)[0]
        _draw_init_marker(ax, init_lon_star, init_pt['lat'], kw, scale=1.0)

    # 平均路徑（紅線）與 24h 標記（紅色方塊）及標註
    mean_lons = _normalize_lon_values(mean_plot_df["lon"].to_numpy(), use_360=use_360)
    mean_lats = mean_plot_df["lat"].to_numpy()
    for seg_lon, seg_lat in _split_track_segments(mean_lons, mean_lats):
        # 先鋪一層白色描邊：平均路徑穿過密集的成員點時才不會被淹沒
        ax.plot(seg_lon, seg_lat, color='white', lw=4.6, alpha=0.7,
                solid_capstyle='round', zorder=2.0, **kw)
        ax.plot(seg_lon, seg_lat, color=MEAN_COLOR, lw=2.8,
                solid_capstyle='round', zorder=2.2, **kw)
    last_mean_pt = mean_plot_df.sort_values('valid_time').iloc[-1]
    last_mean_lon = _normalize_lon_values([last_mean_pt['lon']], use_360=use_360)[0]
    last_fh = int(round((last_mean_pt['valid_time'] - init_time).total_seconds() / 3600.0))
    last_intensity = _format_intensity_label(last_mean_pt.get('wind', np.nan))
    ax.scatter([last_mean_lon], [last_mean_pt['lat']], marker='o', color=MEAN_COLOR, s=66,
               ec='white', zorder=5, linewidth=1.4, **kw)
    ax.text(last_mean_lon + LABEL_OFFSET,
            last_mean_pt['lat'] + LABEL_OFFSET, f'+{last_fh}h\n{last_intensity}',
            fontsize=6.5, color=TEXT_DARK, fontweight='bold', zorder=6,
            bbox=_label_box(), clip_on=True, **kw)
    pts_24h_mean = get_24h_markers(mean_plot_df, init_time)
    if not pts_24h_mean.empty:
        marker_lons = _normalize_lon_values(pts_24h_mean['lon'].to_numpy(), use_360=use_360)
        ax.scatter(marker_lons, pts_24h_mean['lat'], marker='o', s=42, facecolors='white',
                   edgecolors=MEAN_COLOR, linewidths=1.4, zorder=5, **kw)
        # +24h、+48h… 文字標籤（白色描邊，壓在成員點上仍讀得到）
        for i, (_, pt) in enumerate(pts_24h_mean.iterrows()):
            fh = int((pt['valid_time'] - init_time).total_seconds() / 3600)
            if (fh == 0 or last_fh - fh < 24
                    or np.hypot(marker_lons[i] - last_mean_lon, pt['lat'] - last_mean_pt['lat'])
                    < END_LABEL_CLEAR_DEG):
                continue
            ax.text(marker_lons[i] + 0.4, pt['lat'] + 0.4, f'+{fh}h',
                    fontsize=6.5, color=TEXT_DARK, fontweight='bold', zorder=6,
                    path_effects=[mpe.withStroke(linewidth=2.2, foreground='white')],
                    clip_on=True, **kw)
        # 右下角摘要框
        summary = build_24h_summary(pts_24h_mean, init_time)
        if summary:
            n_lines = len(summary.splitlines())
            y_anchor = 0.27 + min(n_lines, 8) * 0.015
            ax.text(0.985, y_anchor, summary, transform=ax.transAxes, fontsize=7,
                    ha='right', va='bottom', color=TEXT_DARK, linespacing=1.35,
                    bbox=_label_box(0.94), zorder=6)

    # 決定報路徑（畫在平均路徑之後，才不會被平均路徑的白色描邊蓋掉）
    if has_det:
        _draw_det_track(ax, det_df, init_time, use_360, kw)

    # 圖例
    _track_source_legend(ax, mean_name or model_name, fontsize=9, ms=11,
                         det_label=det_label if has_det else None)


    n_members = int(df['sample'].nunique()) if 'sample' in df.columns else 0
    init_str = pd.to_datetime(init_time).strftime('%Y-%m-%d %H:%M UTC')
    _set_map_titles(ax,
                    f"{model_name}  ·  {track_id}  Ensemble Track Forecast",
                    f"Init {init_str}" + (f"  ·  {n_members} members" if n_members else ""),
                    main_size=15, right_size=9)
    _watermark(ax, side='right')
    plt.tight_layout(pad=0.6)
    plt.savefig(save_path, dpi=FIG_DPI, bbox_inches='tight', facecolor='white', pad_inches=0.12)
    plt.close(fig)
    print(f"[INFO] 已儲存地圖：{save_path}")


# 模式比較圖的線條配色。同一家族用相近色系、決定報用虛線，
# 讓「哪些線來自同一個模式」一眼可辨：
#   WNC 系列與 GENC → 冷色（藍綠）  ECMWF → 暖色（紅橘）  AIFS → 紫紅
#   AIGFS → 青  GFS → 橄欖
# 比較圖一律實線（含決定報）：八條線本來就靠顏色分辨，虛線只會讓
# 短的那幾條看起來斷斷續續。各模式自己的分頁圖上，決定報仍是虛線。
COMPARE_STYLES = {
    'WN3-C':      '#16324F',
    'WN2-C r2':   '#1B4F9C',
    'WN2-C r1':   '#5B8DC8',
    'GENC':      '#1FA97E',
    'AIFS':      '#7A3FA8',
    'AIFS-DET':  '#C2569B',
    'ECMWF':     '#B3123F',
    'ECMWF-DET': '#B45309',
    'AIGFS':     '#0E7490',
    'AIGFS-DET': '#38B2D0',
    'GFS':       '#5A6B12',
    'GFS-DET':   '#9AA82E',
}
# 畫線順序：後畫的蓋在先畫的上面，所以主力 WNC2-r2 刻意排在四條 WNC／GENC 的最後。
COMPARE_ORDER = ['AIGFS', 'AIGFS-DET', 'GFS', 'GFS-DET',
                 'WN3-C', 'WN2-C r1', 'GENC', 'WN2-C r2',
                 'AIFS', 'AIFS-DET', 'ECMWF', 'ECMWF-DET']
# 圖例順序與畫線順序刻意分開：圖例照模式輩分排（WNC3 → WNC2-r2 → WNC2-r1 →
# GENC → ECMWF → AIFS），疊圖先後則由 COMPARE_ORDER 決定。
COMPARE_LEGEND_ORDER = ['WN3-C', 'WN2-C r2', 'WN2-C r1', 'GENC',
                        'AIFS', 'AIFS-DET', 'ECMWF', 'ECMWF-DET',
                        'AIGFS', 'AIGFS-DET', 'GFS', 'GFS-DET']
COMPARE_LABELS = {
    'WN3-C': 'WN3-C Mean',
    'WN2-C r2': 'WN2-C r2 Mean',
    'WN2-C r1': 'WN2-C r1 Mean',
    'GENC': 'GENC Mean',
    'AIFS': 'AIFS-ENS Mean',
    'AIFS-DET': 'AIFS-single',
    'ECMWF': 'ECMWF-ENS Mean',
    'ECMWF-DET': 'ECMWF HRES',
    'AIGFS': 'AIGEFS Mean',
    'AIGFS-DET': 'AIGFS',
    'GFS': 'GEFS Mean',
    'GFS-DET': 'GFS',
}


def plot_model_comparison_map(track_id: str, entries: dict, save_path: str,
                              init_times: dict | None = None):
    """把各模式的平均路徑（與 ECMWF／AIFS 的決定報）畫在同一張圖上。

    entries: {圖例鍵: DataFrame}，鍵取自 COMPARE_STYLES。各模式的 cycle 不一定
    相同（ECMWF 比 WNC 晚上架），所以圖例會逐條標出各自的初始時間，不在標題上
    寫一個會誤導人的共同 init。

    刻意不畫成員線、不畫圓錐、不標強度點：這張圖的用途是「各模式指向哪裡」，
    細節留給各模式自己的分頁。
    """
    usable = {k: v for k, v in entries.items()
              if isinstance(v, pd.DataFrame) and not v.empty and k in COMPARE_STYLES}
    if len(usable) < 2:
        print(f"[COMPARE] {track_id} 可比較的模式不足兩個，略過")
        return None

    all_lons = [x for v in usable.values() for x in v['lon']]
    all_lats = [x for v in usable.values() for x in v['lat']]
    extent, use_360 = _auto_extent(all_lats, all_lons, pad_deg=3)
    min_lon, max_lon, min_lat, max_lat = extent
    if min_lat == max_lat:
        min_lat -= 2; max_lat += 2
    if min_lon == max_lon:
        min_lon -= 2; max_lon += 2
    extent = _fit_extent_to_aspect((min_lon, max_lon, min_lat, max_lat), FIG_AR, use_360)

    if HAS_CARTOPY:
        fig = plt.figure(figsize=(10, 7), facecolor='white')
        proj = ccrs.PlateCarree(central_longitude=180) if use_360 else ccrs.PlateCarree()
        ax = plt.axes(projection=proj)
        _setup_basemap(ax, extent)
        kw = dict(transform=ccrs.PlateCarree())
    else:
        fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=FIG_DPI, facecolor='white')
        ax = fig.add_subplot(111)
        _setup_plain_axes(ax, extent)
        kw = {}

    init_times = init_times or {}
    drawn: dict[str, str] = {}          # key → 圖例文字，畫成功的才進圖例
    for key in COMPARE_ORDER:
        d = usable.get(key)
        if d is None:
            continue
        color = COMPARE_STYLES[key]
        d = d.sort_values('valid_time')
        lons = _normalize_lon_values(d['lon'].to_numpy(), use_360=use_360)
        lats = d['lat'].to_numpy()
        for seg_lon, seg_lat in _split_track_segments(lons, lats):
            # 線細一點、壓在海岸線（zorder 2.5）底下：十幾條線疊在臺灣附近時陸地輪廓仍看得到
            ax.plot(seg_lon, seg_lat, color='white', lw=3.6, alpha=0.6,
                    solid_capstyle='round', zorder=2.0, **kw)
            ax.plot(seg_lon, seg_lat, color=color, lw=2.2, alpha=0.9,
                    solid_capstyle='round', zorder=2.2, **kw)

        # 24h 標記：各模式在同一時間點的位置差距，是這張圖最想讓人看到的東西
        init_time = init_times.get(key)
        if init_time is not None:
            pts = get_24h_markers(d, init_time)
            if not pts.empty:
                mlons = _normalize_lon_values(pts['lon'].to_numpy(), use_360=use_360)
                ax.scatter(mlons, pts['lat'], marker='o', s=20, facecolors='white',
                           edgecolors=color, linewidths=1.1, zorder=2.3, **kw)

        last = d.iloc[-1]
        last_lon = _normalize_lon_values([last['lon']], use_360=use_360)[0]
        ax.scatter([last_lon], [last['lat']], marker='o', s=28, color=color,
                   ec='white', linewidth=1.0, zorder=2.4, **kw)

        suffix = ''
        if init_time is not None:
            suffix = f"  ({pd.to_datetime(init_time).strftime('%d/%HZ')})"
        drawn[key] = COMPARE_LABELS.get(key, key) + suffix

    handles, labels = [], []
    for key in COMPARE_LEGEND_ORDER:
        if key not in drawn:
            continue
        handles.append(mlines.Line2D([], [], color=COMPARE_STYLES[key],
                                     lw=2.4, solid_capstyle='butt'))
        labels.append(drawn[key])

    leg = ax.legend(handles=handles, labels=labels, loc='upper left', title='Mean Tracks & Deterministic Runs',
                    fontsize=6.3, title_fontsize=7.2, borderpad=0.5, labelspacing=0.3,
                    handlelength=1.4, handletextpad=0.5, **LEGEND_KW)
    _style_legend(leg)
    ax.add_artist(leg)

    _set_map_titles(ax,
                    f"Multi-Model Comparison  ·  {track_id}",
                    "Mean tracks + deterministic runs  ·  hollow dots = 24 h steps",
                    main_size=15, right_size=9)
    _watermark(ax, side='right')
    plt.tight_layout(pad=0.6)
    plt.savefig(save_path, dpi=FIG_DPI, bbox_inches='tight', facecolor='white', pad_inches=0.12)
    plt.close(fig)
    print(f"[COMPARE] 已儲存模式比較圖：{save_path}")
    return save_path


# 資料來源標註：WNC 系列與 GENC 來自 Weather Lab，ECMWF／AIFS 來自 ECMWF Open Data
# （授權不同，見 ecmwf_bufr 模組說明），圖上不能一律掛 DeepMind。
ECMWF_MODELS = {'ECMWF', 'AIFS', 'ECMWF-ENS', 'AIFS-ENS'}
NOAA_MODELS = {'GFS', 'AIGFS', 'GEFS', 'AIGEFS'}


def _data_source(model_name: str) -> str:
    if model_name in ECMWF_MODELS:
        return 'ECMWF Open Data'
    if model_name in NOAA_MODELS:
        return 'NOAA NCEP'
    return 'Google DeepMind Weather Lab'


def plot_genesis_potential_map(csv_path: str, save_path: str, model_name: str = "WN2-C r2",
                               range_hours: int = 360):
    """繪製西太平洋 Ensemble 潛勢預報總覽圖（以 MSLP 著色）。

    range_hours 是該次預報的名目時距，只用在標題。不能寫死 360：
    ECMWF 的 06Z／18Z 只跑到 144h（AIFS 與 WNC 系列則四個 cycle 都是 360h）。
    """
    if not os.path.exists(csv_path):
        print(f"[GENESIS] 找不到潛勢 CSV：{csv_path}")
        return None

    df = pd.read_csv(csv_path, comment='#')
    if df.empty:
        print("[GENESIS] 潛勢 CSV 無資料")
        return None

    if 'maximum_sustained_wind_speed_knots' in df.columns:
        df = df.rename(columns={'maximum_sustained_wind_speed_knots': 'wind'})
    df['valid_time'] = pd.to_datetime(df['valid_time'], errors='coerce', utc=True)

    # 從最小 lead_time 反推初始化時間，格式化為 YYYY-MM-DD-HHZ
    if 'lead_time_hours' in df.columns:
        first = df.sort_values('lead_time_hours').iloc[0]
        init_dt = pd.to_datetime(first['valid_time'], utc=True) - pd.to_timedelta(float(first['lead_time_hours']), unit='h')
        init_time_str = init_dt.strftime('%Y-%m-%d-%HZ')
    elif 'init_time' in df.columns:
        try:
            _idt = pd.to_datetime(df['init_time'].iloc[0], utc=True)
            init_time_str = _idt.strftime('%Y-%m-%d-%HZ')
        except Exception:
            init_time_str = str(df['init_time'].iloc[0])
    else:
        init_time_str = ''

    # 只保留西太平洋範圍
    WP_LON_MIN, WP_LON_MAX = 95.0, 170.0
    WP_LAT_MIN, WP_LAT_MAX = 3.0, 53.0
    df_wp = df[(df['lon'] >= WP_LON_MIN) & (df['lon'] <= WP_LON_MAX) &
               (df['lat'] >= WP_LAT_MIN) & (df['lat'] <= WP_LAT_MAX)].copy()

    if df_wp.empty:
        print("[GENESIS] 西太平洋範圍內無潛勢資料")
        return None

    EXTENT = (98, 162, 3, 52)
    global_min_mslp = float(df_wp['minimum_sea_level_pressure_hpa'].min())

    if HAS_CARTOPY:
        fig = plt.figure(figsize=(13, 8), facecolor='white')
        ax = plt.axes(projection=ccrs.PlateCarree())
        _setup_basemap(ax, EXTENT, grid_step=10)
        kw = dict(transform=ccrs.PlateCarree())
    else:
        fig = plt.figure(figsize=(13, 8), dpi=150, facecolor='white')
        ax = fig.add_subplot(111)
        _setup_plain_axes(ax, EXTENT)
        kw = {}

    # 繪製各 track_id + sample 的 ensemble 軌跡
    for (tid, sid), g in df_wp.groupby(['track_id', 'sample']):
        g = g.sort_values('valid_time')
        lons = g['lon'].to_numpy()
        lats = g['lat'].to_numpy()
        mslps = g['minimum_sea_level_pressure_hpa'].to_numpy()

        # 軌跡連線（淡灰）
        ax.plot(lons, lats, color=TRACK_LINE, linewidth=1.0, alpha=0.35,
                zorder=1, solid_capstyle='round', **kw)

        # MSLP 著色圓點：達暴風強度者實心、未達者空心（整條軌跡一次 scatter，
        # 避免逐點繪製拖慢速度）
        colors = [_mslp_to_color(float(m)) for m in mslps]
        _scatter_members(ax, lons, lats, colors, kw,
                         size=14, alpha=0.75, zorder=2, lw=0.8)

    # 圖例（MSLP 色階）
    legend_handles = []
    for _, color, label in MSLP_COLOR_BINS:
        h = mlines.Line2D([], [], marker='o', ms=6, ls='',
                          markerfacecolor='none', markeredgecolor=color,
                          markeredgewidth=1.4, color=color, label=label)
        legend_handles.append(h)

    leg = ax.legend(handles=legend_handles, loc='upper left',
                    title='min. sea level pressure', title_fontsize=8,
                    fontsize=8, borderpad=0.7, labelspacing=0.34, handletextpad=0.6,
                    **LEGEND_KW)
    _style_legend(leg)

    # 右上角顯示全域最低 MSLP
    ax.text(0.99, 0.99, f'min. MSLP  {global_min_mslp:.1f} hPa',
            transform=ax.transAxes, fontsize=8.5, ha='right', va='top',
            color=MSLP_COLOR_BINS[1][1], fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.34', facecolor='white',
                      edgecolor=BOX_EDGE, alpha=0.94, linewidth=0.8))

    _set_map_titles(ax,
                    f'{model_name}  ·  Western Pacific Tropical Cyclone Genesis Potential  ·  0–{int(range_hours)} h',
                    f'Init {init_time_str}\n{_data_source(model_name)}',
                    main_size=13, right_size=8.5)
    _watermark(ax)
    plt.tight_layout(pad=0.6)
    plt.savefig(save_path, dpi=OVERVIEW_DPI, bbox_inches='tight', facecolor='white', pad_inches=0.12)
    plt.close(fig)
    print(f'[GENESIS] 已儲存潛勢預報圖：{save_path}')
    return save_path


# ── WNC2 1000 成員大系集：路徑聚類圖 ─────────────────────────────────────────
# Weather Lab 的 FNV3_LARGE_ENSEMBLE 是 WNC2 的 1000 成員版本，只有 cyclogenesis
# 產品（單檔約 40 MB）。檔內已命名的系統（WP272026、WP962026(4)…）每個成員都
# 帶同一個 track_id，直接各成一群；尚未生成的系統 track_id 只是各成員自己的流水號
# （同一個數字在不同成員代表不同系統），必須自己分群。
WNC2_LE_CONFIG = {
    "remote": "FNV3_LARGE_ENSEMBLE",
    "local_prefix": "WNC2-1000",
    "display": "WN2-C 1000",
    "cyc_dir": "deepmind_weather_wnc2_le_cyclogenesis_2026",
    "cluster_png": "WP_Track_Clusters_WNC2-1000.png",
}
os.makedirs(WNC2_LE_CONFIG["cyc_dir"], exist_ok=True)
# 單檔 40 MB，不比照 KEEP_CYCLES 留 12 期；留兩期給「當期取不到時退回上一期」用
WNC2_LE_KEEP_CYCLES = 2

CLUSTER_EXTENT = (100, 172, 3, 47)
# 分群只收在西北太平洋生成的未命名路徑（生成點 lon%360 100–180、lat 0–45）
CLUSTER_GEN_BOX = (100.0, 180.0, 0.0, 45.0)
CLUSTER_EPS_KM = 400.0      # DBSCAN 鄰域半徑
CLUSTER_MIN_PTS = 15        # 核心點門檻（1.5% 成員）
CLUSTER_MIN_MEMBERS = 20    # 成群後至少要 2% 的成員，否則當成雜訊
CLUSTER_MIN_DURATION_H = 12 # 圖例的成員數只算路徑延續 ≥12 h 者
CLUSTER_RELINK_MAX_GAP_H = 24   # 命名系統斷掉後多久內冒出的新路徑可接回
CLUSTER_RELINK_MAX_KM = 300.0   # 且距其最後位置多近
# 兩條路徑生成時間不同時，生成點距離每差 1 小時加多少 km（約颱風移速）
CLUSTER_KM_PER_HOUR = 15.0
CLUSTER_PALETTE = ['#D63FC4', '#E8803A', '#2BB5A0', '#4C5BE0', '#6DBE2F',
                   '#D9A31C', '#1F8FD6', '#C0392B', '#8E44AD', '#8B5A2B']
CLUSTER_NOISE_COLOR = '#8A8F96'


def _short_storm_label(tid: str) -> str:
    """WP272026 → 27W；WP962026(4) → 96W；EP152026 → 15E；CP012026 → 01C。"""
    m = re.match(r'^(WP|EP|CP)(\d{2})\d{4}', tid)
    if not m:
        return tid
    return f"{m.group(2)}{ {'WP': 'W', 'EP': 'E', 'CP': 'C'}[m.group(1)] }"


def _haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(a, dtype=np.float64)) for a in (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _dbscan(dist: np.ndarray, eps: float, min_pts: int) -> np.ndarray:
    """以預先算好的距離矩陣跑 DBSCAN；回傳 labels（-1 為雜訊）。

    CI 沒裝 scikit-learn，n 只有幾千，自己寫一個就夠了。
    """
    n = dist.shape[0]
    nbrs = [np.flatnonzero(dist[i] <= eps) for i in range(n)]
    core = np.array([len(x) >= min_pts for x in nbrs])
    labels = np.full(n, -1, dtype=int)
    cid = 0
    for i in range(n):
        if labels[i] != -1 or not core[i]:
            continue
        labels[i] = cid
        stack = [i]
        while stack:
            j = stack.pop()
            if not core[j]:
                continue
            for k in nbrs[j]:
                if labels[k] == -1:
                    labels[k] = cid
                    stack.append(k)
        cid += 1
    return labels


def _relink_lost_tracks(df: pd.DataFrame, named_ids: list[str]) -> None:
    """把「追蹤器跟丟已命名系統後重新編號」的路徑接回原系統（就地改 df 的 track_id）。

    例：10/13 18Z 有 32 個成員的 96W 在 0–12h 就斷，12h 後在原處 100 km 左右冒出
    一條新編號路徑，之後與其他成員的 96W 幾乎重疊。條件：同一成員內、命名系統已
    結束、新路徑在其結束後 CLUSTER_RELINK_MAX_GAP_H 內開始、距其最後位置
    CLUSTER_RELINK_MAX_KM 內；多個候選取最近者。依開始時間處理，接回後更新
    「最後位置」，所以斷了又斷的也能一路接上。
    """
    if not named_ids:
        return
    is_num = df['track_id'].str.fullmatch(r'\d+')
    last = {(tid, s): (g['lead_time_hours'].iloc[-1], g['lat'].iloc[-1], g['lon360'].iloc[-1])
            for (tid, s), g in df[df['track_id'].isin(named_ids)].groupby(['track_id', 'sample'])}
    starts = (df[is_num].groupby(['track_id', 'sample'], sort=False)
              .agg(t0=('lead_time_hours', 'first'), lat=('lat', 'first'), lon=('lon360', 'first'),
                   t1=('lead_time_hours', 'last'), lat1=('lat', 'last'), lon1=('lon360', 'last'))
              .reset_index().sort_values('t0'))
    n_linked = 0
    for r in starts.itertuples(index=False):
        best, best_d = None, CLUSTER_RELINK_MAX_KM
        for tid in named_ids:
            prev = last.get((tid, r.sample))
            if prev is None or not (0 < r.t0 - prev[0] <= CLUSTER_RELINK_MAX_GAP_H):
                continue
            d = float(_haversine_km(prev[1], prev[2], r.lat, r.lon))
            if d <= best_d:
                best, best_d = tid, d
        if best is None:
            continue
        df.loc[(df['track_id'] == r.track_id) & (df['sample'] == r.sample), 'track_id'] = best
        last[(best, r.sample)] = (r.t1, r.lat1, r.lon1)
        n_linked += 1
    if n_linked:
        print(f"[CLUSTER] {n_linked} 條路徑接回已命名系統（追蹤器跟丟後重新編號）")


def cluster_large_ensemble_tracks(df: pd.DataFrame) -> tuple[list[dict], list[tuple]]:
    """把大系集 cyclogenesis 的路徑分群。

    回傳 (clusters, noise)。clusters 每項含 label、named、members（不重複成員數）、
    tracks（[(lons, lats), ...]）、gen_lat/gen_lon/gen_time（中位生成點與時間）；
    noise 是沒歸進任何群的 (lons, lats)。

    未命名路徑的距離：A 的生成點與「B 在 A 生成那一刻的位置」的距離（反之亦然），
    兩者都不存在時才退回生成點距離＋生成時間差懲罰。同一個擾動在不同成員裡生成
    時間可差上一兩天、位置也已往西北移了好幾百公里，單比生成點會把它拆成好幾群。
    """
    df = df.dropna(subset=['lat', 'lon', 'lead_time_hours']).copy()
    df['track_id'] = df['track_id'].astype(str)
    df['lon360'] = df['lon'] % 360.0
    df = df.sort_values(['track_id', 'sample', 'lead_time_hours'])

    clusters: list[dict] = []
    noise: list[tuple] = []

    def _count_members(g):
        # 路徑至少延續 CLUSTER_MIN_DURATION_H 才算這個成員有這個系統：只有起報點、
        # 6 小時就斷掉的多半是追蹤器在初始場抓到又立刻跟丟，不代表系統存在
        dur = g.groupby('sample')['lead_time_hours'].agg(lambda x: x.max() - x.min())
        return int((dur >= CLUSTER_MIN_DURATION_H).sum())

    def _track_xy(g):
        return g['lon360'].to_numpy(), g['lat'].to_numpy()

    # ① 已命名系統：track_id 本身就是分群結果。只收起報在西太者
    is_num = df['track_id'].str.fullmatch(r'\d+')
    named_ids = []
    for tid, g in df[~is_num].groupby('track_id', sort=False):
        first = g.groupby('sample').first()
        if first['lat'].median() >= 0 and 100.0 <= first['lon360'].median() <= 180.0:
            named_ids.append(tid)
    _relink_lost_tracks(df, named_ids)
    # 接回的列原本排在數字編號那一段，重排才能讓 groupby 拿到依時間排序的完整路徑
    df = df.sort_values(['track_id', 'sample', 'lead_time_hours'])

    named = df[df['track_id'].isin(named_ids)]
    for tid, g in named.groupby('track_id', sort=False):
        first = g.groupby('sample').first()
        lat0, lon0 = float(first['lat'].median()), float(first['lon360'].median())
        clusters.append({
            'label': _short_storm_label(tid), 'named': True,
            'members': _count_members(g),
            'tracks': [_track_xy(t) for _, t in g.groupby('sample')],
            'gen_lat': lat0, 'gen_lon': lon0,
            'gen_time': float(first['lead_time_hours'].median()),
        })

    # ② 未命名路徑：在西太生成者才分群
    unnamed = df[df['track_id'].str.fullmatch(r'\d+')]
    tracks = [g for _, g in unnamed.groupby(['track_id', 'sample'], sort=False)]
    lo0, lo1, la0, la1 = CLUSTER_GEN_BOX
    tracks = [g for g in tracks
              if lo0 <= g['lon360'].iloc[0] <= lo1 and la0 <= g['lat'].iloc[0] <= la1]
    if tracks:
        steps = int(df['lead_time_hours'].max() // 6) + 1
        n = len(tracks)
        plat = np.full((n, steps), np.nan)
        plon = np.full((n, steps), np.nan)
        t0 = np.empty(n, dtype=int)
        for i, g in enumerate(tracks):
            idx = (g['lead_time_hours'].to_numpy() // 6).astype(int)
            plat[i, idx] = g['lat'].to_numpy()
            plon[i, idx] = g['lon360'].to_numpy()
            t0[i] = idx[0]
        glat, glon = plat[np.arange(n), t0], plon[np.arange(n), t0]
        # d_ab[a, b]：A 的生成點 vs. B 在 A 生成時刻的位置（B 那時不存在則 NaN）
        d_ab = _haversine_km(glat[:, None], glon[:, None], plat[:, t0].T, plon[:, t0].T)
        d_gg = (_haversine_km(glat[:, None], glon[:, None], glat[None, :], glon[None, :])
                + CLUSTER_KM_PER_HOUR * 6 * np.abs(t0[:, None] - t0[None, :]))
        dist = np.fmin(np.fmin(d_ab, d_ab.T), d_gg)
        labels = _dbscan(dist, CLUSTER_EPS_KM, CLUSTER_MIN_PTS)

        unnamed_clusters = []
        for c in sorted(set(labels) - {-1}):
            members = [tracks[i] for i in np.flatnonzero(labels == c)]
            samples = {int(g['sample'].iloc[0]) for g in members}
            if len(samples) < CLUSTER_MIN_MEMBERS:
                labels[labels == c] = -1
                continue
            sel = labels == c
            unnamed_clusters.append({
                'named': False, 'members': _count_members(pd.concat(members)),
                'tracks': [_track_xy(g) for g in members],
                'gen_lat': float(np.median(glat[sel])), 'gen_lon': float(np.median(glon[sel])),
                'gen_time': float(np.median(t0[sel]) * 6),
            })
        # 依中位生成時間編號 C1、C2…
        unnamed_clusters.sort(key=lambda c: c['gen_time'])
        for k, c in enumerate(unnamed_clusters, start=1):
            c['label'] = f'C{k}'
        clusters.extend(unnamed_clusters)
        noise = [_track_xy(tracks[i]) for i in np.flatnonzero(labels == -1)]

    for i, c in enumerate(clusters):
        c['color'] = CLUSTER_PALETTE[i % len(CLUSTER_PALETTE)]
    return clusters, noise


def plot_large_ensemble_clusters(csv_path: str, save_path: str, model_name: str = "WN2-C"):
    """繪製 WNC2 1000 成員大系集的路徑聚類圖。"""
    from matplotlib.collections import LineCollection  # type: ignore

    df = pd.read_csv(csv_path, comment='#')
    if df.empty:
        print("[CLUSTER] 大系集 CSV 無資料")
        return None
    df = _cut_extratropical(df.dropna(subset=['lat', 'lon', 'lead_time_hours']),
                            ['track_id', 'sample'], 'lead_time_hours')
    n_total = int(df['sample'].nunique())
    init_dt = pd.to_datetime(df['init_time'].iloc[0], utc=True)
    max_h = int(df['lead_time_hours'].max())
    clusters, noise = cluster_large_ensemble_tracks(df)
    print(f"[CLUSTER] {len(clusters)} 群（{sum(c['named'] for c in clusters)} 個已命名），"
          f"雜訊 {len(noise)} 條")

    if HAS_CARTOPY:
        fig = plt.figure(figsize=(13, 8.6), facecolor='white')
        ax = plt.axes(projection=ccrs.PlateCarree())
        _setup_basemap(ax, CLUSTER_EXTENT, grid_step=10)
        kw = dict(transform=ccrs.PlateCarree())
    else:
        fig = plt.figure(figsize=(13, 8.6), dpi=150, facecolor='white')
        ax = fig.add_subplot(111)
        _setup_plain_axes(ax, CLUSTER_EXTENT)
        kw = {}

    def _segments(tracks):
        # lon 已轉 0–360；跨換日線的路徑在 180 以東直接畫出圖框外，不必切段
        return [np.column_stack(t) for t in tracks if len(t[0]) >= 2]

    def _alpha(c):
        # 成員比例越高越深：機率高的系統一眼就要比零星的小群醒目
        return 0.10 + 0.18 * c['members'] / n_total

    ax.add_collection(LineCollection(_segments(noise), colors=CLUSTER_NOISE_COLOR,
                                     linewidths=0.6, alpha=0.5, zorder=1, **kw))
    # 成員多的先畫；小群疊在上面但本身很淡，只在大群上留一層色調，不會搶過大群
    for c in sorted(clusters, key=lambda c: -c['members']):
        ax.add_collection(LineCollection(_segments(c['tracks']), colors=c['color'],
                                         linewidths=0.6, alpha=_alpha(c), zorder=2, **kw))

    # 每群在中位生成點標名稱與生成日期。系集裡常有「雙胞胎」擾動（例：96W 與緊跟
    # 在後的 C1）生成點幾乎重疊，標籤撞到就往上下錯開；貼邊的往內收，免得被圖框切掉
    lon_min, lon_max, lat_min, lat_max = CLUSTER_EXTENT
    placed: list[tuple[float, float]] = []
    for c in clusters:
        if not (lon_min <= c['gen_lon'] <= lon_max + 5 and lat_min <= c['gen_lat'] <= lat_max):
            continue
        gen_dt = init_dt + pd.Timedelta(hours=c['gen_time'])
        text = c['label'] if c['named'] else f"{c['label']}  {gen_dt:%m/%d}"
        x = float(np.clip(c['gen_lon'], lon_min + 3, lon_max - 3))
        y0 = float(np.clip(c['gen_lat'], lat_min + 1, lat_max - 1))
        y = next((y0 + dy for dy in (0, -1.6, 1.6, -3.2, 3.2, -4.8, 4.8)
                  if all(abs(x - px) > 5 or abs(y0 + dy - py) > 1.4 for px, py in placed)), y0)
        placed.append((x, y))
        ax.text(x, y, text, fontsize=9, fontweight='bold',
                color=c['color'], ha='center', va='center', zorder=6,
                bbox=dict(boxstyle='round,pad=0.25', facecolor='white',
                          edgecolor=c['color'], alpha=0.9, linewidth=1.0),
                **kw)

    handles = [mlines.Line2D([], [], color=c['color'], lw=4,
                             label=f"{c['label']}  {c['members']}/{n_total} "
                                   f"({c['members'] / n_total:.0%})")
               for c in clusters]
    handles.append(mlines.Line2D([], [], color=CLUSTER_NOISE_COLOR, lw=4,
                                 label='Sparse / noise'))
    leg = ax.legend(handles=handles, loc='upper left', fontsize=9, borderpad=0.7,
                    labelspacing=0.4, handlelength=1.6, handletextpad=0.6, **LEGEND_KW)
    _style_legend(leg)

    ax.text(0.005, 0.008,
            'Named storms grouped by track ID (tracks re-detected after a tracker loss are '
            'rejoined); unnamed tracks clustered by genesis time & position (DBSCAN). '
            'Counts = members lasting ≥12 h.',
            transform=ax.transAxes, ha='left', va='bottom', fontsize=7.5,
            color=TEXT_MUTED, zorder=10,
            bbox=dict(boxstyle='round,pad=0.25', facecolor='white', edgecolor='none', alpha=0.8))

    valid_dt = init_dt + pd.Timedelta(hours=max_h)
    _set_map_titles(ax,
                    f'{model_name}  ·  {n_total}-Member TC Track Clusters  ·  0–{max_h} h',
                    f'Init {init_dt:%Y-%m-%d-%HZ} → {valid_dt:%m/%d %HZ}  ·  Systems: {len(clusters)}\n'
                    f'{_data_source(model_name)}',
                    main_size=13, right_size=8.5)
    _watermark(ax)
    plt.tight_layout(pad=0.6)
    plt.savefig(save_path, dpi=OVERVIEW_DPI, bbox_inches='tight', facecolor='white', pad_inches=0.12)
    plt.close(fig)
    print(f'[CLUSTER] 已儲存路徑聚類圖：{save_path}')
    return save_path


def _process_large_ensemble() -> tuple[str | None, str | None]:
    """下載最新一期 WNC2 1000 成員 cyclogenesis CSV 並畫聚類圖。

    回傳 (聚類圖路徑, CSV 路徑)；取不到資料時兩者皆 None。CSV 留給 main() 畫各颱風的
    1000 成員侵襲機率圖。
    """
    cfg = WNC2_LE_CONFIG
    d, prefix = cfg["cyc_dir"], cfg["local_prefix"]
    path = None
    latest = _latest_cycle()
    for i in range(5):
        stamp = _cycle_stamp(latest - timedelta(hours=6 * i))
        p = os.path.join(d, f"{prefix}_{stamp}_cyclogenesis.csv")
        if os.path.exists(p) or _download_file(
                _remote_csv_url(cfg["remote"], "ensemble/cyclogenesis", stamp),
                p, f"{cfg['display']}-DL", allow_404=True):
            path = p
            break
    if path is None:
        print(f"[{cfg['display']}] 最近 5 期都取不到大系集 CSV")
        return None, None

    names = sorted(n for n in os.listdir(d)
                   if n.startswith(f"{prefix}_") and n.endswith("_cyclogenesis.csv"))
    for name in names[:-WNC2_LE_KEEP_CYCLES]:
        if os.path.join(d, name) != path:
            try:
                os.remove(os.path.join(d, name))
            except OSError as e:
                print(f"[{cfg['display']}-CLEANUP] 警告: 移除 {name} 失敗: {e}")

    try:
        cluster = plot_large_ensemble_clusters(path, os.path.join(OUTPUT_DIR, cfg["cluster_png"]),
                                               model_name="WN2-C")
    except Exception as e:
        print(f"[{cfg['display']}-ERROR] 路徑聚類圖失敗，略過: {e}")
        cluster = None
    return cluster, path


def _download_file(url: str, out_path: str, label: str, allow_404: bool = False) -> bool:
    """下載檔案至 out_path。allow_404=True 時遇 404 回傳 False 而不拋錯。

    先寫入 .part 再 os.replace 換名。中途失敗或被 Ctrl+C 中斷時，out_path
    要嘛不存在、要嘛還是完整的舊檔，不會留下截斷的半成品 —— 這點很重要，
    因為 _resolve_cycle 與 mean/cyclogenesis 三處都只用 os.path.exists
    判斷檔案可用，截斷檔一旦落地，之後每一次執行都會沉默地重用它。
    """
    print(f"[{label}] GET {url}")
    resp = requests.get(url, headers=HEADERS, stream=True, timeout=60)
    if allow_404 and resp.status_code == 404:
        return False
    resp.raise_for_status()
    tmp_path = out_path + ".part"
    try:
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        os.replace(tmp_path, out_path)
    except BaseException:
        # 攔 BaseException 而非 Exception：KeyboardInterrupt 正是要防的情況
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    print(f"[{label}] saved to {out_path}")
    return True


def _resolve_cycle(cfg: dict) -> tuple[datetime, str | None] | tuple[None, None]:
    """從最新 cycle 起往回逐 6 小時嘗試（最多 5 個），回傳 (cycle, ensemble CSV 路徑)。"""
    if cfg.get("fetcher") == "ecmwf":
        cycle, path = _resolve_cycle_ecmwf(cfg)
        _fetch_newer_det(cfg, cycle)
        return cycle, path
    if cfg.get("fetcher") == "noaa":
        cycle, path = _resolve_cycle_noaa(cfg)
        _fetch_newer_det(cfg, cycle)
        return cycle, path

    latest = _latest_cycle()
    for i in range(5):
        cycle = latest - timedelta(hours=6 * i)
        stamp = _cycle_stamp(cycle)
        path = os.path.join(cfg["ensemble_dir"], f"{cfg['local_prefix']}_{stamp}_paired.csv")
        mean_path = os.path.join(cfg["mean_dir"], f"{cfg['local_prefix']}_{stamp}_paired.csv")
        if os.path.exists(path) and os.path.exists(mean_path):
            return cycle, path
        url = _remote_csv_url(cfg["remote"], "ensemble/paired", stamp)
        if not (os.path.exists(path) or _download_file(url, path, f"{cfg['display']}-DL", allow_404=True)):
            continue
        # 平均檔與系集檔不一定同時上架：上架時間抓得很緊（_latest_cycle），剛好卡在中間
        # 時平均檔是 404，以前會直接拋錯（WN2-C r2 是必要模式，整輪失敗）。這期先不用，
        # 系集檔留著，下一輪平均檔到了就直接用
        if os.path.exists(mean_path) or _download_file(
                _remote_csv_url(cfg["remote"], "ensemble_mean/paired", stamp), mean_path,
                f"{cfg['display']}-MEAN", allow_404=True):
            return cycle, path
        print(f"[{cfg['display']}-DL] {stamp} 平均檔尚未上架，先用前一期")
    return None, None


def _resolve_cycle_ecmwf(cfg: dict) -> tuple[datetime, str | None] | tuple[None, None]:
    """ECMWF 版的 cycle 解析：下載 BUFR 並就地轉成 paired CSV。

    ECMWF Open Data 的上架時間與時距都跟 Weather Lab 不同（見 ecmwf_bufr），
    所以起點用 ecmwf_bufr.latest_cycle() 而不是 _latest_cycle()。

    暴風編號的對應要靠 WNC2-r2 的平均路徑當基準（ECMWF 與 JTWC 各自編號，
    對不上），因此 ECMWF 兩個模式必須排在 MODEL_CONFIGS 的 WNC2-r2 之後。

    回傳的 CSV 路徑可能是 None，代表最新一期解得開、但模式已經不追任何颱風。
    這種情況**不可以**往前找還有颱風的舊 cycle：那等於把早就結束的路徑當成
    最新預報掛在網頁上。只有「尚未上架」才回退，判斷依據是 fetch_cycle 的
    三態回傳值。
    """
    import ecmwf_bufr

    latest = ecmwf_bufr.latest_cycle()
    for i in range(5):
        cycle = latest - timedelta(hours=6 * i)
        stamp = _cycle_stamp(cycle)
        path = os.path.join(cfg["ensemble_dir"], f"{cfg['local_prefix']}_{stamp}_paired.csv")
        if os.path.exists(path):
            if ecmwf_bufr.has_unmatched_reference(path, cycle, MEAN_DIR, "WNC2-r2"):
                try:
                    ecmwf_bufr.fetch_cycle(cfg["ecmwf_model"], cycle, cfg,
                                           ref_mean_dir=MEAN_DIR, ref_prefix="WNC2-r2",
                                           scratch_dir=ECMWF_SCRATCH_DIR)
                except Exception as e:
                    # 失敗就沿用舊檔；檔頭沒更新，下一輪會再試
                    print(f"[{cfg['display']}-DL] cycle {stamp} 重抓失敗，沿用舊檔: {e}")
            ecmwf_bufr.retry_missing_deterministic(cfg["ecmwf_model"], cycle, cfg, path,
                                                   ECMWF_SCRATCH_DIR)
            return cycle, path
        # 潛勢檔在、系集檔不在 ⇒ 這期先前解過且沒有颱風。BUFR 是靜態的，重下
        # 也是同樣結果，直接認定「目前無颱風」，不必再花一次 1 MB 下載。
        if os.path.exists(os.path.join(
                cfg["cyc_dir"], f"{cfg['local_prefix']}_{stamp}_cyclogenesis.csv")):
            return cycle, None
        try:
            status = ecmwf_bufr.fetch_cycle(cfg["ecmwf_model"], cycle, cfg,
                                            ref_mean_dir=MEAN_DIR, ref_prefix="WNC2-r2",
                                            scratch_dir=ECMWF_SCRATCH_DIR)
        except Exception as e:
            print(f"[{cfg['display']}-DL] cycle {stamp} 取用失敗: {e}")
            continue
        if status == ecmwf_bufr.FETCH_OK:
            return cycle, path
        if status == ecmwf_bufr.FETCH_NO_STORMS:
            return cycle, None
    return None, None


def _resolve_cycle_noaa(cfg: dict) -> tuple[datetime, str | None] | tuple[None, None]:
    """NOAA 版的 cycle 解析：下載 NCEP 的 ATCF 成員檔並就地轉成 paired CSV。

    與 ECMWF 相同，「這期沒有颱風」照實回報、不往前找舊期；只有「尚未上架」才
    回退。沒有颱風時 noaa_atcf 也會寫出空的系集檔，所以檔案在就代表這期處理過，
    空檔則回 (cycle, None)。檔案收下全部 WP／CP／EP 颱風，只收 WNC2-r2 有的那幾顆
    是 _process_model 的事：WNC 比 NOAA 晚上架，寫檔時就篩，新颱風會整期漏掉。
    """
    import noaa_atcf

    latest = noaa_atcf.latest_cycle()
    for i in range(5):
        cycle = latest - timedelta(hours=6 * i)
        path = os.path.join(cfg["ensemble_dir"],
                            f"{cfg['local_prefix']}_{_cycle_stamp(cycle)}_paired.csv")
        if not os.path.exists(path):
            try:
                status = noaa_atcf.fetch_ensemble(cfg["noaa_model"], cycle, cfg)
            except Exception as e:
                print(f"[{cfg['display']}-DL] cycle {_cycle_stamp(cycle)} 取用失敗: {e}")
                continue
            if status == noaa_atcf.FETCH_UNAVAILABLE:
                continue
        try:
            empty = pd.read_csv(path, comment="#").empty
        except Exception:
            empty = True
        _backfill_noaa(cfg, cycle)
        if cfg.get("cyc_dir") and not os.path.exists(os.path.join(
                cfg["cyc_dir"], f"{cfg['local_prefix']}_{_cycle_stamp(cycle)}_cyclogenesis.csv")):
            try:
                noaa_atcf.fetch_genesis(cfg["noaa_model"], cycle, cfg)
            except Exception as e:
                print(f"[{cfg['display']}-GENESIS] 生成追蹤取用失敗，沿用舊檔: {e}")
        return cycle, (None if empty else path)
    return None, None


# 補抓往前幾期（NOMADS 留兩天）：趨勢圖要有前幾期的平均路徑才畫得出來，
# 不補的話新加入的模式要等一兩天才有趨勢圖。檔案在就略過，所以只有第一次會真的下載。
NOAA_BACKFILL_CYCLES = 6


def _backfill_noaa(cfg: dict, latest: datetime) -> None:
    import noaa_atcf
    for i in range(1, NOAA_BACKFILL_CYCLES + 1):
        cycle = latest - timedelta(hours=6 * i)
        stamp = _cycle_stamp(cycle)
        try:
            if not os.path.exists(os.path.join(cfg["ensemble_dir"],
                                               f"{cfg['local_prefix']}_{stamp}_paired.csv")):
                noaa_atcf.fetch_ensemble(cfg["noaa_model"], cycle, cfg)
            if not os.path.exists(os.path.join(cfg["det_dir"],
                                               f"{cfg['local_prefix']}_{stamp}_deterministic.csv")):
                noaa_atcf.fetch_deterministic(cfg["noaa_model"], cycle, cfg)
        except Exception as e:
            print(f"[{cfg['display']}-BACKFILL] {stamp} 補抓失敗，略過: {e}")


def _fetch_newer_det(cfg: dict, ens_cycle: datetime | None) -> None:
    """抓比系集更新的決定報：決定報比系集早上架（ECMWF 早 30～60 分、NOAA 早
    約 50 分），等系集到齊才一起抓，等於白白晚一截。

    從最新一期往回找到系集那期為止，碰到已有的檔或抓到一期就停（更舊的不需要）。
    檔名照決定報自己的 cycle，_process_model 再逐颱風挑最新的一份。
    """
    if ens_cycle is None or not cfg.get("det_dir"):
        return
    fetcher = cfg.get("fetcher")
    if fetcher == "ecmwf":
        import ecmwf_bufr
        latest = ecmwf_bufr.latest_cycle()
    else:
        import noaa_atcf
        latest = noaa_atcf.latest_cycle()
    cycle = latest
    while cycle > ens_cycle:
        det_path = os.path.join(cfg["det_dir"],
                                f"{cfg['local_prefix']}_{_cycle_stamp(cycle)}_deterministic.csv")
        if os.path.exists(det_path):
            break
        try:
            if fetcher == "ecmwf":
                ok = ecmwf_bufr.fetch_deterministic_only(
                    cfg["ecmwf_model"], cycle, cfg, ref_mean_dir=MEAN_DIR, ref_prefix="WNC2-r2",
                    scratch_dir=ECMWF_SCRATCH_DIR)
            else:
                ok = noaa_atcf.fetch_deterministic(cfg["noaa_model"], cycle, cfg)
        except Exception as e:
            print(f"[{cfg['display']}-DET] {_cycle_stamp(cycle)} 決定報取用失敗: {e}")
            ok = False
        if ok:
            print(f"[{cfg['display']}-DET] 決定報 {_cycle_stamp(cycle)} 比系集新，先上")
            break
        cycle -= timedelta(hours=6)
    # 系集那期的決定報（NOAA 系集與決定報分開抓，這裡補；ECMWF 由 fetch_cycle 處理）。
    # 不能因為上面抓到更新的就跳過：快取重建時系集那期會缺，趨勢圖與校驗少一期
    if fetcher == "noaa":
        det_path = os.path.join(cfg["det_dir"],
                                f"{cfg['local_prefix']}_{_cycle_stamp(ens_cycle)}_deterministic.csv")
        if not os.path.exists(det_path):
            try:
                noaa_atcf.fetch_deterministic(cfg["noaa_model"], ens_cycle, cfg)
            except Exception as e:
                print(f"[{cfg['display']}-DET] {_cycle_stamp(ens_cycle)} 決定報取用失敗: {e}")


def _det_files(cfg: dict, ens_cycle: datetime) -> list[str]:
    """不早於系集那期的決定報檔，新 → 舊。"""
    d = cfg.get("det_dir")
    if not d or not os.path.isdir(d):
        return []
    out = []
    for name in os.listdir(d):
        if not (name.startswith(f"{cfg['local_prefix']}_") and name.endswith("_deterministic.csv")):
            continue
        c = _cycle_from_stamp(name)
        if c is not None and c >= ens_cycle:
            out.append((c, os.path.join(d, name)))
    return [p for _, p in sorted(out, reverse=True)]


def _cycle_from_stamp(name: str) -> datetime | None:
    """檔名（或時間戳）→ cycle，與 _cycle_stamp 互為反向；解不出來回 None。"""
    m = re.search(r"(\d{4})_(\d{2})_(\d{2})T(\d{2})_00", os.path.basename(name))
    if not m:
        return None
    y, mo, d, h = (int(g) for g in m.groups())
    return datetime(y, mo, d, h, tzinfo=timezone.utc)


def _latest_local_cyclogenesis(cfg: dict) -> tuple[datetime, str] | tuple[None, None]:
    """cyc_dir 內最新一期潛勢檔的 (cycle, 路徑)；檔名字典序即時間序。

    ECMWF 專用。潛勢總覽與系集檔的 cycle 會脫鉤：西北太平洋淨空時 ecmwf_bufr
    對不到颱風編號、不寫系集檔，但潛勢檔照樣逐期寫出。潛勢圖要跟著自己這份
    檔案的時間走，綁系集檔的 cycle 會讓它一起卡在最後一顆颱風消散的那期。
    """
    d = cfg.get("cyc_dir")
    if not d or not os.path.isdir(d):
        return None, None
    names = sorted(n for n in os.listdir(d)
                   if n.startswith(f"{cfg['local_prefix']}_")
                   and n.endswith("_cyclogenesis.csv"))
    if not names:
        return None, None
    return _cycle_from_stamp(names[-1]), os.path.join(d, names[-1])


def _get_cyclogenesis_csv(cfg: dict, stamp: str) -> str | None:
    """取得潛勢 CSV：優先用當期檔，否則下載；下載失敗才退而用目錄中最新檔。"""
    if not cfg.get("cyc_dir"):
        return None
    display = cfg["display"]
    if cfg.get("fetcher") in ("ecmwf", "noaa"):
        # ECMWF／NOAA 的潛勢檔是轉檔時一併寫出的，沒有可下載的遠端來源；
        # 也不綁當期 stamp，理由見 _latest_local_cyclogenesis
        _, path = _latest_local_cyclogenesis(cfg)
        if path is None:
            print(f"[{display}-GENESIS] {cfg['cyc_dir']} 內無可用潛勢檔")
            return None
        print(f"[{display}-GENESIS] 使用潛勢檔: {os.path.basename(path)}")
        return path
    path = os.path.join(cfg["cyc_dir"], f"{cfg['local_prefix']}_{stamp}_cyclogenesis.csv")
    if os.path.exists(path):
        print(f"[{display}-GENESIS] 使用當期潛勢檔: {path}")
        return path
    url = _remote_csv_url(cfg["remote"], "ensemble/cyclogenesis", stamp)
    try:
        _download_file(url, path, f"{display}-GENESIS")
        return path
    except Exception as e:
        print(f"[{display}-GENESIS] 下載失敗: {e}，嘗試使用目錄中最新檔")
        fallback = sorted(f for f in os.listdir(cfg["cyc_dir"]) if f.endswith('_cyclogenesis.csv'))
        if fallback:
            fb_path = os.path.join(cfg["cyc_dir"], fallback[-1])
            print(f"[{display}-GENESIS] 退而使用: {fb_path}")
            return fb_path
        return None


def _cleanup_old_downloads(cfg: dict) -> None:
    """刪除下載目錄中過舊的 cycle 檔，只保留最近 KEEP_CYCLES 期。

    這三個目錄原本只增不減（約 +20 MB/日）。舊檔也確實用不到：
    _resolve_cycle 最多只回溯 5 個 cycle，_get_cyclogenesis_csv 的退路
    也只取目錄中最新一檔。

    檔名為 {local_prefix}_YYYY_MM_DDTHH_00_*.csv，字典序即時間序，
    故直接依檔名排序後砍掉尾端以外的部分。
    """
    display = cfg["display"]
    name_re = re.compile(
        rf"^{re.escape(cfg['local_prefix'])}_\d{{4}}_\d{{2}}_\d{{2}}T\d{{2}}_00_\w+\.csv$")

    # 清理是輔助性的：排程無人值守，任何失敗都只警告，不可中斷預報產出
    # cyc_dir／det_dir 不是每個模式都有（ECMWF 無潛勢、WNC 無決定報），略過 None
    for d in (cfg["ensemble_dir"], cfg["mean_dir"], cfg.get("cyc_dir"), cfg.get("det_dir")):
        if not d:
            continue
        try:
            names = sorted(n for n in os.listdir(d) if name_re.match(n))
        except OSError as e:
            print(f"[{display}-CLEANUP] 警告: 無法列出 {d}: {e}")
            continue
        for name in names[:-KEEP_CYCLES]:
            try:
                os.remove(os.path.join(d, name))
                print(f"[{display}-CLEANUP] 已移除過舊下載檔: {name}")
            except OSError as e:
                print(f"[{display}-CLEANUP] 警告: 移除 {name} 失敗: {e}")


def _archive_forecast_map(save_path: str, init_time) -> list[tuple[str, str]]:
    """把剛畫好的系集路徑圖另存一份 {原檔名}_{YYYYMMDDHH}.png，留最新的 MAP_HISTORY_RUNS + 1 期。

    回傳比這期舊的前幾期 [(init ISO, 路徑), ...]，新到舊。同一期每輪重畫就覆蓋同一份，
    所以歷史圖是那一期最後一次的樣子（含後來才補上的決定報）。失敗只警告，不中斷預報。
    """
    base, ext = os.path.splitext(save_path)
    stamp = pd.Timestamp(init_time).strftime('%Y%m%d%H')
    try:
        shutil.copyfile(save_path, f"{base}_{stamp}{ext}")
    except OSError as e:
        print(f"[HISTORY] 警告: 另存 {save_path} 失敗: {e}")
    d, name = os.path.split(base)
    hist_re = re.compile(rf"^{re.escape(name)}_(\d{{10}}){re.escape(ext)}$")
    try:
        stamps = sorted((m.group(1) for m in map(hist_re.match, os.listdir(d)) if m), reverse=True)
    except OSError as e:
        print(f"[HISTORY] 警告: 無法列出 {d}: {e}")
        return []
    for old in stamps[MAP_HISTORY_RUNS + 1:]:
        try:
            os.remove(f"{base}_{old}{ext}")
        except OSError as e:
            print(f"[HISTORY] 警告: 移除 {base}_{old}{ext} 失敗: {e}")
    return [(datetime.strptime(x, '%Y%m%d%H').strftime('%Y-%m-%dT%H:00:00Z'), f"{base}_{x}{ext}")
            for x in stamps[:MAP_HISTORY_RUNS + 1] if x < stamp][:MAP_HISTORY_RUNS]


def _backfill_history(cfg: dict, tid: str, save_path: str, init_time) -> None:
    """功能上線前沒存到的前幾期：下載目錄還留著那期 CSV 就補畫路徑圖、補存互動地圖路徑點。

    只補缺的，補過檔案就在了，之後每輪都會直接略過。只往前找 MAP_HISTORY_RUNS 個
    6 小時（不跨過中間缺很多天的舊檔），補的圖不含決定報。
    """
    import json
    display = cfg['display']
    base, ext = os.path.splitext(save_path)
    for k in range(1, MAP_HISTORY_RUNS + 1):
        t = pd.Timestamp(init_time) - pd.Timedelta(hours=6 * k)
        png = f"{base}_{_run_stamp(t)}{ext}"
        jpath = os.path.join(OUTPUT_DIR, f"{tid}_Tracks_{_run_stamp(t)}.json")
        try:
            with open(jpath, encoding='utf-8') as fh:
                need_json = display not in json.load(fh).get('models', {})
        except (OSError, ValueError):
            need_json = True
        need_png = not os.path.exists(png)
        if not (need_png or need_json):
            continue
        name = f"{cfg['local_prefix']}_{_cycle_stamp(t)}_paired.csv"
        ens, mean = os.path.join(cfg['ensemble_dir'], name), os.path.join(cfg['mean_dir'], name)
        if not (os.path.exists(ens) and os.path.exists(mean)):
            continue
        try:
            df, t_init = load_forecast_dataframe(ens, tid)
            mdf, _ = load_forecast_dataframe(mean, tid)
            if df is None or df.empty:
                continue
            if need_png:
                plot_forecast_map(df, mdf, t_init, tid, png, model_name=display, mean_name=_ens_name(cfg))
            if need_json:
                _archive_tracks(tid, t_init, display, {
                    'members': [_track_points(g, t_init) for _, g in df.groupby('sample')],
                    'mean': _track_points(mdf, t_init)})
            print(f"[{display}-HISTORY] 補存 {tid} {t:%m/%d %HZ}")
        except Exception as e:
            print(f"[{display}-HISTORY] 補存 {tid} {t:%m/%d %HZ} 失敗，略過: {e}")


def _cleanup_stale_outputs(prefix: str, keep_ids: list[str], display: str) -> None:
    """移除本次未偵測到的颱風在此模式下的殘留產物。

    颱風從某模式的偵測結果消失時（例如某 cycle 的 GENC 不再追蹤某顆），
    舊的路徑圖、動畫 GIF 與幀目錄會永遠留在 OUTPUT_DIR，既佔空間也會被
    commit 進 repo，且 index.html 不會再引用它們。

    前綴以 ^ 錨定，確保無前綴的 WNC2-r2（output_prefix=""）不會誤刪
    WNC3_ / WNC2-r1_ / GENC_ 開頭的檔案。
    """
    if not os.path.isdir(OUTPUT_DIR):
        return
    keep = set(keep_ids)
    p = re.escape(prefix)
    file_re = re.compile(rf"^{p}((?:WP|CP|EP)\d{{6}})_"
                         rf"(?:Forecast_(?:Map(?:_\d{{10}})?\.png|Animation\.gif)|Strike_Probability\.png|Intensity_Plume\.png|Track_Trend\.png|Det_Track_Trend\.png)$")
    dir_re = re.compile(rf"^animation_frames_{p}((?:WP|CP|EP)\d{{6}})$")

    # 清理是輔助性的：排程無人值守，任何失敗都只警告，不可中斷預報產出
    try:
        names = sorted(os.listdir(OUTPUT_DIR))
    except OSError as e:
        print(f"[{display}-CLEANUP] 警告: 無法列出 {OUTPUT_DIR}: {e}")
        return

    for name in names:
        path = os.path.join(OUTPUT_DIR, name)
        is_dir = os.path.isdir(path)
        m = dir_re.match(name) if is_dir else file_re.match(name)
        if not m or m.group(1) in keep:
            continue
        try:
            shutil.rmtree(path) if is_dir else os.remove(path)
            print(f"[{display}-CLEANUP] 已移除殘留產物: {name}")
        except OSError as e:
            print(f"[{display}-CLEANUP] 警告: 移除 {name} 失敗: {e}")


def _cleanup_stale_jtwc(keep_ids: set[str]) -> None:
    """移除已無任何模式追蹤的颱風其「每顆一份」的產物。

    jtwc_{TID}.gif、{TID}_Model_Comparison.png 與 1000 成員侵襲機率圖都不屬於單一
    paired 模式（同一顆真實颱風各模式共用），因此只能在所有模式都跑完、以 track_id 聯集判斷才安全，
    不能放進 _process_model。
    """
    if not os.path.isdir(OUTPUT_DIR):
        return
    jtwc_re = re.compile(r"^jtwc_((?:WP|CP|EP)\d{6})\.gif$|^((?:WP|CP|EP)\d{6})_Model_Comparison\.png$"
                         r"|^((?:WP|CP|EP)\d{6})_Tracks(?:_\d{10})?\.json$"
                         rf"|^{re.escape(WNC2_LE_CONFIG['local_prefix'])}_((?:WP|CP|EP)\d{{6}})_(?:Strike_Probability|Intensity_Plume|Strike_\d+_\w+h|Wind34_Probability)\.png$")
    try:
        names = sorted(os.listdir(OUTPUT_DIR))
    except OSError as e:
        print(f"[CLEANUP] 警告: 無法列出 {OUTPUT_DIR}: {e}")
        return
    for name in names:
        m = jtwc_re.match(name)
        # 兩個分支各佔一個群組，命中的那個才有值
        if not m or (m.group(1) or m.group(2) or m.group(3) or m.group(4)) in keep_ids:
            continue
        try:
            os.remove(os.path.join(OUTPUT_DIR, name))
            print(f"[CLEANUP] 已移除殘留的每顆颱風共用圖: {name}")
        except OSError as e:
            print(f"[CLEANUP] 警告: 移除 {name} 失敗: {e}")


def _cleanup_legacy_names() -> None:
    """清除改名前（WNC-R2／WNC-R1）留在磁碟上的下載檔與輸出產物。

    現行的清理函式都以 MODEL_CONFIGS 目前的 prefix 建正則，掃不到舊檔名，
    舊檔會就這樣一直留著（下載檔約 20 MB/日，圖檔還會被 commit 進 repo）。
    這裡按舊 prefix 精確比對後刪除；比對用 ^ 錨定並要求完整的時間戳／檔名格式，
    不做寬鬆的 startswith，以免誤刪其他東西。
    """
    if not LEGACY_PREFIXES:
        return

    # 下載目錄：{legacy}_YYYY_MM_DDTHH_00_*.csv
    dirs = {d for cfg in MODEL_CONFIGS
            for d in (cfg["ensemble_dir"], cfg["mean_dir"], cfg.get("cyc_dir"), cfg.get("det_dir"))
            if d}
    csv_re = re.compile(
        r"^(?:%s)_\d{4}_\d{2}_\d{2}T\d{2}_00_\w+\.csv$"
        % "|".join(re.escape(x) for x in LEGACY_PREFIXES))
    for d in sorted(dirs):
        try:
            names = [n for n in os.listdir(d) if csv_re.match(n)]
        except OSError as e:
            print(f"[LEGACY-CLEANUP] 警告: 無法列出 {d}: {e}")
            continue
        for name in names:
            try:
                os.remove(os.path.join(d, name))
                print(f"[LEGACY-CLEANUP] 已移除舊命名下載檔: {d}/{name}")
            except OSError as e:
                print(f"[LEGACY-CLEANUP] 警告: 移除 {name} 失敗: {e}")

    # 輸出目錄：舊 prefix 的路徑圖／動畫／幀目錄／潛勢圖
    if not os.path.isdir(OUTPUT_DIR):
        return
    p_alt = "|".join(re.escape(x) for x in LEGACY_PREFIXES)
    out_re = re.compile(rf"^(?:{p_alt})_(?:WP|CP|EP)\d{{6}}_Forecast_(?:Map\.png|Animation\.gif)$"
                        rf"|^WP_Genesis_Potential_(?:{p_alt})\.png$")
    dir_re = re.compile(rf"^animation_frames_(?:{p_alt})_(?:WP|CP|EP)\d{{6}}$")
    try:
        names = sorted(os.listdir(OUTPUT_DIR))
    except OSError as e:
        print(f"[LEGACY-CLEANUP] 警告: 無法列出 {OUTPUT_DIR}: {e}")
        return
    for name in names:
        path = os.path.join(OUTPUT_DIR, name)
        is_dir = os.path.isdir(path)
        if not (dir_re.match(name) if is_dir else out_re.match(name)):
            continue
        try:
            shutil.rmtree(path) if is_dir else os.remove(path)
            print(f"[LEGACY-CLEANUP] 已移除舊命名產物: {name}")
        except OSError as e:
            print(f"[LEGACY-CLEANUP] 警告: 移除 {name} 失敗: {e}")


def _genesis_range_hours(cfg: dict, cycle: datetime) -> int:
    """該模式此次 cycle 的名目預報時距（潛勢圖標題用）。

    Weather Lab 的四個模式一律 360h；ECMWF 的 IFS 在 06Z／18Z 只跑 144h，
    標題寫死 360 會與圖上實際內容不符。
    """
    if cfg.get("fetcher") == "noaa":
        return 120      # NCEP 的生成追蹤只跑到 120h
    if cfg.get("fetcher") != "ecmwf":
        return 360
    import ecmwf_bufr
    return ecmwf_bufr.forecast_range_hours(cfg["ecmwf_model"], cycle)


def _process_model(cfg: dict, get_jtwc_text, download_jtwc_img) -> tuple[str | None, list[dict]]:
    """執行單一模式的完整流程：解析 cycle、下載 CSV、繪製潛勢圖與各颱風產品。

    get_jtwc_text / download_jtwc_img 由 main() 傳入，帶跨模式快取
    （同一顆颱風的 JTWC 官方資料與模式無關，不必重複下載）。
    回傳 (潛勢圖路徑或 None, storms 清單)。
    """
    display = cfg["display"]
    print(f"\n[{display}] === 開始處理 {display} 模式 ===")

    cycle, csv_path = _resolve_cycle(cfg)
    if cycle is None and cfg.get("fetcher") == "ecmwf":
        # 五期全都還沒上架時連 cycle 都定不出來，改拿最新潛勢檔的 cycle 頂替，
        # 至少讓潛勢總覽跟著更新（早期版本在這裡直接拋錯，整個模式從網頁消失）。
        cycle, _ = _latest_local_cyclogenesis(cfg)
    if cycle is None:
        raise RuntimeError(f"無法取得最近 5 個 cycle 的 {display} ensemble CSV")
    if csv_path is None:
        # 模式已經不追任何颱風。照實走完流程：track_ids 會是空的，
        # _cleanup_stale_outputs 把殘留的路徑圖與動畫清掉，網頁上這個模式
        # 就跟 WNC 一樣只剩潛勢總覽，不會掛著早就結束的舊路徑。
        print(f"[{display}] 本期無追蹤中的颱風，僅更新潛勢總覽")
    if cycle != _latest_cycle():
        print(f"[{display}] 回退至 cycle: {cycle.strftime('%Y-%m-%d %HZ')}")
    stamp = _cycle_stamp(cycle)

    # 下載 Ensemble Mean 檔（ECMWF／NOAA 的平均是轉檔時一併算出的，沒有遠端來源）
    mean_csv_path = os.path.join(cfg["mean_dir"], f"{cfg['local_prefix']}_{stamp}_paired.csv")
    if not os.path.exists(mean_csv_path) and cfg.get("remote"):
        _download_file(_remote_csv_url(cfg["remote"], "ensemble_mean/paired", stamp),
                       mean_csv_path, f"{display}-MEAN")

    # 用當前 cycle 的 mean CSV 偵測颱風，確保不會抓到舊資料。
    # csv_path 是 None 代表這期根本沒有系集檔，此時不能讓 _auto_detect_track_ids
    # 退去讀目錄裡的舊檔，否則會拿早就消散的颱風重畫一次路徑圖。
    # ECMWF／NOAA 的 CP/EP 颱風以 WNC2-r2（配對基準，排在前面已下載）判定的為準
    known_ids = (set(_auto_detect_track_ids(MEAN_DIR)) if cfg.get("fetcher") and csv_path
                 else None)
    track_ids = (_auto_detect_track_ids(cfg["mean_dir"], preferred_path=mean_csv_path,
                                        model_prefix=cfg["local_prefix"], known_ids=known_ids)
                 if csv_path else [])
    if cfg.get("fetcher") == "noaa":
        # NOAA 檔案收下了所有 JTWC 有編號的颱風；WNC 沒有的不另外開颱風頁
        track_ids = [t for t in track_ids if t in (known_ids or set())]
    jtwc_forecast_urls, jtwc_text_urls = _build_jtwc_urls(track_ids)

    # 先清掉本模式已不再追蹤的颱風產物，再產生本次結果
    _cleanup_stale_outputs(cfg["output_prefix"], track_ids, display)

    # 決定報（ECMWF／NOAA 才有）：可能比系集新一兩期（見 _fetch_newer_det），
    # 逐颱風挑最新一份有這顆的
    det_paths = _det_files(cfg, cycle) if cfg.get("det_dir") else []

    # 西太平洋潛勢預報圖
    genesis_map_path = None
    cyc_csv_path = _get_cyclogenesis_csv(cfg, stamp)
    if cfg.get("genesis_png") and cyc_csv_path and os.path.exists(cyc_csv_path):
        print(f"[{display}-GENESIS] 正在繪製西太平洋潛勢預報圖...")
        # 時距用潛勢檔自己的 cycle 推：ECMWF 兩邊的 cycle 會脫鉤，而 IFS 的
        # 06Z／18Z 只跑 144h，拿系集檔的 cycle 去算會在標題寫錯時距
        genesis_map_path = plot_genesis_potential_map(
            cyc_csv_path, os.path.join(OUTPUT_DIR, cfg["genesis_png"]), model_name=_ens_name(cfg),
            range_hours=_genesis_range_hours(cfg, _cycle_from_stamp(cyc_csv_path) or cycle))

    # 逐颱風產出：路徑圖、JTWC 官方圖、動畫幀序列與 GIF
    storms = []
    prefix = cfg["output_prefix"]
    for tid in track_ids:
        print(f"\n[{display}] === 處理颱風 {tid} ===")
        try:
            df, init_time = load_forecast_dataframe(csv_path, tid)
            mean_df, _ = load_forecast_dataframe(mean_csv_path, tid)
            current_info = extract_current_info(mean_df)

            # 決定報是加分項：這顆颱風在決定報裡追不到（或整份檔沒下載到）時
            # 就少畫一條線，不影響系集本身的產出
            det_df, det_init, det_label = None, None, cfg.get("det_label")
            for det_path in det_paths:
                try:
                    det_df, det_init = load_forecast_dataframe(det_path, tid)
                except Exception:
                    det_df = None
                    continue
                if det_df is not None and not det_df.empty:
                    break
            if det_df is None:
                print(f"[{display}-DET] {tid} 無決定報路徑")
            elif det_label and pd.Timestamp(det_init) != pd.Timestamp(init_time):
                # 比系集新的決定報：圖例標出它自己的起報時間，免得被當成同一期
                det_label = f"{det_label} · {pd.Timestamp(det_init):%d/%HZ}"

            if tid in jtwc_text_urls:
                print(f"[JTWC] 嘗試從 JTWC web.txt 抓取 {tid} 資料...")
                jtwc_data = get_jtwc_text(tid, jtwc_text_urls)
                if jtwc_data:
                    current_info['jtwc'] = jtwc_data
                    # 目前強度優先採用 JTWC web.txt 的最大持續風速
                    max_wind = jtwc_data.get('max_winds_kt')
                    if max_wind is not None:
                        try:
                            current_info['wind'] = float(max_wind)
                            current_info['category'] = ss_category(current_info['wind'])
                            print(f"[JTWC] 目前強度已更新為 web.txt: {int(float(max_wind))} kt")
                        except Exception:
                            print("[JTWC] 警告: max_winds_kt 格式異常，保留原始強度")

            save_path = os.path.join(OUTPUT_DIR, f"{prefix}{tid}_Forecast_Map.png")
            plot_forecast_map(df, mean_df, init_time, tid, save_path, model_name=display,
                              det_df=det_df, det_label=det_label, mean_name=_ens_name(cfg))
            _backfill_history(cfg, tid, save_path, init_time)
            map_history = _archive_forecast_map(save_path, init_time)

            # 侵襲機率圖：加分項，失敗只略過這張
            strike_path, city_strike = None, None
            try:
                member_tracks = _member_tracks(df, init_time)
                city_strike = city_strike_stats(member_tracks, init_time)
                strike_path = plot_strike_probability(
                    member_tracks, init_time, tid,
                    os.path.join(OUTPUT_DIR, f"{prefix}{tid}_Strike_Probability.png"),
                    model_name=_ens_name(cfg))
            except Exception as e:
                print(f"[{display}-STRIKE] 侵襲機率圖失敗，略過: {e}")

            det_name = cfg.get('det_name')
            has_det = det_df is not None and not det_df.empty and bool(det_name)
            city_strike_det = None
            if has_det:
                try:
                    city_strike_det = city_strike_stats(_member_tracks(det_df, det_init), det_init)
                except Exception as e:
                    print(f"[{display}-DET] 決定報城市表失敗，略過: {e}")

            plume_path, ri_prob = None, None
            try:
                plume_path, ri_prob = plot_intensity_plume(
                    paired_member_series(df, init_time), init_time, tid,
                    os.path.join(OUTPUT_DIR, f"{prefix}{tid}_Intensity_Plume.png"),
                    model_name=display,
                    det=paired_member_series(det_df, init_time)[0] if has_det else None,
                    det_name=(f"{det_name} · {pd.Timestamp(det_init):%d/%HZ}"
                              if has_det and pd.Timestamp(det_init) != pd.Timestamp(init_time) else det_name))
            except Exception as e:
                print(f"[{display}-PLUME] 強度羽狀圖失敗，略過: {e}")

            trend_path = None
            try:
                trend_path = plot_track_trend(
                    load_trend_means(cfg, cycle, tid), tid,
                    os.path.join(OUTPUT_DIR, f"{prefix}{tid}_Track_Trend.png"), model_name=_ens_name(cfg))
            except Exception as e:
                print(f"[{display}-TREND] 趨勢圖失敗，略過: {e}")
            det_trend_path = None
            if det_name and cfg.get('det_dir'):
                try:
                    det_trend_path = plot_track_trend(
                        load_trend_means(cfg, max(pd.Timestamp(cycle), pd.Timestamp(det_init)) if has_det else cycle,
                                     tid, det=True), tid,
                        os.path.join(OUTPUT_DIR, f"{prefix}{tid}_Det_Track_Trend.png"),
                        model_name=det_name, colors=TREND_DET_COLORS, latest_color=DET_COLOR,
                        track_kind='Deterministic')
                except Exception as e:
                    print(f"[{display}-DET] 決定報趨勢圖失敗，略過: {e}")

            download_jtwc_img(tid, OUTPUT_DIR, jtwc_forecast_urls)

            print("[ANIMATION] 正在生成幀序列...")
            frames_dir = os.path.join(OUTPUT_DIR, f"animation_frames_{prefix}{tid}")
            # 清除舊幀，避免幀數減少時殘留上次多餘的圖
            if os.path.isdir(frames_dir):
                for _old in os.listdir(frames_dir):
                    # .png 是改存 WebP 前的舊幀，一併清掉
                    if _old.startswith("frame_") and _old.endswith((".png", ".webp")):
                        os.remove(os.path.join(frames_dir, _old))
            # 幀存成 WebP 給網頁播放器；GIF 已停產，不需要回傳的路徑清單
            generate_frame_sequence(df, mean_df, init_time, tid, frames_dir,
                                    max_frames=72, model_name=display,
                                    det_df=det_df, det_label=det_label,
                                    mean_name=_ens_name(cfg))

            # 預報 GIF 已停產：網頁播放器用的是幀，GIF 沒有地方引用，每輪卻佔 ~57 MB。
            # 停產前留下的舊檔在這裡順手刪掉
            old_gif = os.path.join(OUTPUT_DIR, f"{prefix}{tid}_Forecast_Animation.gif")
            if os.path.exists(old_gif):
                try:
                    os.remove(old_gif)
                except OSError as e:
                    print(f"[{display}-CLEANUP] 警告: 移除 {old_gif} 失敗: {e}")

            storms.append({
                'track_id': tid,
                'model': display,
                'ens_name': _ens_name(cfg),
                'forecast_map_path': save_path,
                'forecast_map_init': pd.Timestamp(init_time).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'forecast_map_history': map_history,
                'strike_map_path': strike_path,
                'city_strike': city_strike,
                'plume_path': plume_path,
                'trend_path': trend_path,
                'det_name': det_name if has_det else None,
                'city_strike_det': city_strike_det,
                'det_trend_path': det_trend_path,
                'track_points': {
                    'members': [_track_points(g, init_time) for _, g in df.groupby('sample')],
                    'mean': _track_points(mean_df, init_time),
                    'det': _track_points(det_df, det_init) if has_det else [],
                    'det_init': (pd.Timestamp(det_init).strftime('%Y-%m-%dT%H:%M:%SZ')
                                 if has_det else None),
                    'det_name': det_name if has_det else None},
                'ri_prob': ri_prob,
                'current_info': current_info,
                'frames_dir': frames_dir,
                # 供 main() 組模式比較圖用；不會進到網頁 HTML
                'mean_df': mean_df,
                'det_df': det_df,
                'det_init_time': det_init if has_det else None,
                'init_time': init_time,
            })
            print(f"[{display}-DONE] 完成颱風 {tid} 的處理")
        except Exception as e:
            print(f"[{display}-ERROR] 處理 {tid} 時發生錯誤: {e}")
            continue

    # 放在最後：本次要用的下載檔都已讀取完畢，不會刪到正在使用的檔
    _cleanup_old_downloads(cfg)

    return genesis_map_path, storms


def main():
    # 先清掉改名前殘留的舊檔，避免與本次產出的新命名檔案並存
    _cleanup_legacy_names()

    # 同一顆颱風的各模式 track_id 相同時，JTWC 官方資料（web.txt、預報圖）
    # 只跟真實颱風有關、與模式無關，故在本次執行內快取，避免重複下載。
    jtwc_text_cache: dict = {}
    jtwc_image_downloaded: set = set()

    def get_jtwc_text_cached(track_id: str, urls: dict) -> dict:
        if track_id in jtwc_text_cache:
            print(f"[JTWC] 使用本次執行已抓取的 web.txt 快取: {track_id}")
            return jtwc_text_cache[track_id]
        data = scrape_jtwc_text_product(track_id, jtwc_text_urls=urls)
        # 只快取成功結果；失敗（空字典）不快取，讓下一個模式的迴圈有機會重試
        if data:
            jtwc_text_cache[track_id] = data
        return data

    def download_jtwc_image_cached(track_id: str, output_dir: str, forecast_urls: dict) -> None:
        if track_id in jtwc_image_downloaded:
            print(f"[JTWC] 預報圖本次執行已下載過，略過重複下載: {track_id}")
            return
        # 只有下載成功才標記，失敗（回傳 None）時讓下一個模式的迴圈重試
        if download_jtwc_image(track_id, output_dir, jtwc_forecast_urls=forecast_urls):
            jtwc_image_downloaded.add(track_id)

    storms: list[dict] = []
    genesis_maps: list[tuple[str, str]] = []
    for cfg in MODEL_CONFIGS:
        try:
            genesis_map_path, model_storms = _process_model(
                cfg, get_jtwc_text_cached, download_jtwc_image_cached)
        except Exception as e:
            # 主模式（required）失敗時中止；其餘模式失敗僅略過，不拖垮整體流程
            if cfg["required"]:
                raise
            print(f"[{cfg['display']}-ERROR] 模式處理失敗，略過: {e}")
            continue
        if genesis_map_path:
            # 帶上 display 名稱：網頁端要用它當分頁標籤，從檔名反猜既脆弱又容易撞名
            genesis_maps.append((_ens_name(cfg), genesis_map_path))
        storms.extend(model_storms)

    # WNC2 1000 成員路徑聚類圖：放在潛勢頁當一個分頁。加分項，失敗不影響其他產品
    try:
        cluster_path, le_csv = _process_large_ensemble()
    except Exception as e:
        print(f"[{WNC2_LE_CONFIG['display']}-ERROR] 大系集處理失敗，略過: {e}")
        cluster_path, le_csv = None, None
    if cluster_path:
        genesis_maps.append((WNC2_LE_CONFIG["display"], cluster_path))

    # 1000 成員侵襲機率圖：每顆颱風一張，掛在該颱風第一個模式的 storm dict 上
    # （與模式比較圖同樣是「每顆一份」）。加分項，失敗不影響其他產品
    if le_csv:
        le_name = WNC2_LE_CONFIG["display"]
        le_file = WNC2_LE_CONFIG["local_prefix"]   # 檔名用；顯示名稱有空格
        try:
            le_tracks, le_init, le_n, le_series = load_large_ensemble_tracks(le_csv)
            for tid in dict.fromkeys(s['track_id'] for s in storms):
                if tid not in le_tracks:
                    continue
                path = plot_strike_probability(
                    le_tracks[tid], le_init, tid,
                    os.path.join(OUTPUT_DIR, f"{le_file}_{tid}_Strike_Probability.png"),
                    model_name=le_name, n_members=le_n)
                head = next(s for s in storms if s['track_id'] == tid)
                head['city_strike_1000'] = city_strike_stats(le_tracks[tid], le_init, n_total=le_n)
                try:
                    plume, ri = plot_intensity_plume(
                        le_series.get(tid, []), le_init, tid,
                        os.path.join(OUTPUT_DIR, f"{le_file}_{tid}_Intensity_Plume.png"),
                        model_name=le_name, n_members=le_n)
                    if plume:
                        head['plume_1000_path'], head['ri_1000'] = plume, ri
                except Exception as e:
                    print(f"[{le_name}-PLUME] 1000 成員強度羽狀圖失敗，略過: {e}")
                if path:
                    head['strike_1000_path'] = path
                extra = []
                for t0, t1 in STRIKE_WINDOWS:
                    lbl = f"{t0}–{t1} h" if t1 is not None else f"{t0} h+"
                    fn = f"{le_file}_{tid}_Strike_{t0}_{t1 if t1 is not None else 'end'}h.png"
                    try:
                        p_ = plot_strike_probability(
                            window_tracks(le_tracks[tid], t0, t1), le_init, tid,
                            os.path.join(OUTPUT_DIR, fn), model_name=le_name, n_members=le_n,
                            title=f"Strike Probability  {lbl}",
                            subtitle=f"track within {STRIKE_RADIUS_DEG:g}° during {lbl}",
                            extent_tracks=le_tracks[tid])
                        if p_:
                            extra.append((lbl, p_))
                    except Exception as e:
                        print(f"[{le_name}-STRIKE] {lbl} 失敗，略過: {e}")
                try:
                    radii = load_large_ensemble_radii(le_csv, tid)
                    if radii:
                        p_ = plot_strike_probability(
                            le_tracks[tid], le_init, tid,
                            os.path.join(OUTPUT_DIR, f"{le_file}_{tid}_Wind34_Probability.png"),
                            model_name=le_name, n_members=le_n,
                            title='34-kt Wind Probability',
                            subtitle='inside the 34-kt wind radii (4 quadrants) at any time',
                            field=lambda ext, u360, _r=radii: compute_wind34_probability(
                                [(_normalize_lon_values(m[0], use_360=u360), *m[1:]) for m in _r],
                                ext, le_n),
                            extent_tracks=le_tracks[tid])
                        if p_:
                            extra.append(('34 kt', p_))
                except Exception as e:
                    print(f"[{le_name}-WIND34] 暴風圈機率失敗，略過: {e}")
                if extra:
                    head['strike_1000_extra'] = extra
        except Exception as e:
            print(f"[{le_name}-STRIKE] 1000 成員侵襲機率圖失敗，略過: {e}")

    # 模式比較圖：所有模式跑完才有完整素材，故放在迴圈之後統一產生。
    # 一顆颱風一張，掛在該颱風第一個模式的 storm dict 上，網頁端就能當成
    # 這顆颱風的共用圖（與 JTWC 官方圖同樣是「每顆一份」而非「每模式一份」）。
    for tid in dict.fromkeys(s['track_id'] for s in storms):
        group = [s for s in storms if s['track_id'] == tid]
        entries, init_times = {}, {}
        for s in group:
            model = s['model']
            if s.get('mean_df') is not None:
                entries[model] = s['mean_df']
                init_times[model] = s.get('init_time')
            if s.get('det_df') is not None and not s['det_df'].empty:
                entries[f'{model}-DET'] = s['det_df']
                init_times[f'{model}-DET'] = s.get('det_init_time') or s.get('init_time')
        path = plot_model_comparison_map(
            tid, entries, os.path.join(OUTPUT_DIR, f"{tid}_Model_Comparison.png"),
            init_times=init_times)
        if path:
            group[0]['comparison_map_path'] = path

    try:
        write_tracks_json(storms)
    except Exception as e:
        print(f"[TRACKMAP] 互動地圖資料失敗，略過: {e}")

    # 路徑校驗：存本輪預報與實況、算成績單，掛在各颱風第一個 storm dict 上。
    # 加分項，失敗不影響其他產品
    try:
        archive_verification(storms)
        archive_noaa_backfill(storms)
        card = compute_scorecard()
        for tid in dict.fromkeys(s['track_id'] for s in storms):
            head = next(s for s in storms if s['track_id'] == tid)
            head['scorecard'] = card.get(tid, {})
            head['scorecard_all'] = card.get('_all', {})
    except Exception as e:
        print(f"[VERIF] 路徑校驗失敗，略過: {e}")

    # 只留下本次仍在追蹤的颱風產物（JTWC 官方圖與模式比較圖都是每顆颱風一份，
    # 跨模式共用，須等所有模式跑完才知道哪些颱風已完全消失）
    _cleanup_stale_jtwc({s['track_id'] for s in storms})

    # 生成預報網站 HTML（支援多顆颱風；storms 順序決定卡片與分頁排序）
    print("\n[HTML] 正在生成預報網站...")
    from generate_forecast_website import generate_forecast_html
    generate_forecast_html(storms, os.path.join(OUTPUT_DIR, "index.html"),
                           genesis_map_paths=genesis_maps)

    print("\n[DONE] 所有颱風處理完成")


if __name__ == "__main__":
    main()
