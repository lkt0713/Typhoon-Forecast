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
import matplotlib.patheffects as mpe # type: ignore
from matplotlib.legend_handler import HandlerTuple # type: ignore
import matplotlib.ticker as mticker # type: ignore
import re

try:
    from PIL import Image # type: ignore
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from scipy.interpolate import CubicSpline, PchipInterpolator, interp1d as _scipy_interp1d  # type: ignore
    from scipy.ndimage import gaussian_filter1d as _scipy_gf1d  # type: ignore
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    print("[WARN] scipy 未安裝，無法繪製不確定性圓錐")

try:
    from shapely.geometry import Point as _ShapelyPoint        # type: ignore
    from shapely.ops import unary_union as _shapely_union      # type: ignore
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

# Target timestamp — auto-derived from current UTC time.
# WNC data is available ~6h45m after cycle time, so we subtract that
# and round down to the nearest 6-hour boundary (00/06/12/18Z).
def _latest_cycle() -> datetime:
    adjusted = datetime.now(timezone.utc) - timedelta(hours=6, minutes=45)
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
        "display": "WNC3",
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
        "display": "WNC2-r2",
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
        "display": "WNC2-r1",
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
        "display": "AIFS",
        "ensemble_dir": AIFS_ENSEMBLE_DIR,
        "mean_dir": AIFS_MEAN_DIR,
        "det_dir": AIFS_DET_DIR,
        "det_label": "AIFS-single (deterministic)",
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
        "ensemble_dir": IFS_ENSEMBLE_DIR,
        "mean_dir": IFS_MEAN_DIR,
        "det_dir": IFS_DET_DIR,
        "det_label": "HRES (deterministic)",
        "cyc_dir": IFS_CYCLOGENESIS_DIR,
        "genesis_png": "WP_Genesis_Potential_ECMWF.png",
        "output_prefix": "ECMWF_",
        "required": False,
    },
]

# 舊命名 → 新命名。WNC-R2／WNC-R1 時期產出的下載檔與圖檔仍躺在磁碟上，且不會被
# _cleanup_old_downloads／_cleanup_stale_outputs 掃到（那些正則都綁定現行 prefix），
# 故由 _cleanup_legacy_names() 一次性清除。確認線上已無舊檔後可整段移除。
LEGACY_PREFIXES = ["WNC-R2", "WNC-R1"]

# 每個下載目錄保留的 cycle 數（4 cycle/日，12 期約三天）。
KEEP_CYCLES = 12

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CopilotDownloader/1.0)"}

# 輸出目錄
OUTPUT_DIR = "docs"
os.makedirs(OUTPUT_DIR, exist_ok=True)
open(os.path.join(OUTPUT_DIR, ".nojekyll"), "w").close()


def _auto_detect_track_ids(mean_dir: str, preferred_path: str | None = None, model_prefix: str = "WNC2-r2") -> list[str]:
    """從 MEAN_DIR 內最新的 CSV 自動偵測有效颱風 TRACK_ID。
    若提供 preferred_path 且檔案存在，優先使用該檔案（當前 cycle）。
    只保留 WP[0-8]X20XX，排除 WP9X（擾動）。
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
            valid = sorted(tid for tid in ids if re.match(r'^WP[0-8]\d20\d{2}$', tid))
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
    """WP062026 → 'wp0626'"""
    m = re.match(r'^WP(\d{2})(\d{4})$', track_id)
    if not m:
        return track_id.lower()
    return f"wp{m.group(1)}{m.group(2)[2:]}"


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
# 決定報路徑（ECMWF HRES／AIFS-single）：深琥珀＋虛線。強度色階裡的橘（Cat3
# #EE7A22）只以小圓點出現，這裡是帶白色描邊的粗線，加上虛線後不會與平均路徑
# 或強度點混淆。
DET_COLOR   = '#B45309'
DET_DASH    = (0, (5.5, 2.6))
CONE_FILL   = '#8FA8C6'   # 不確定性圓錐填色
# 不確定性圓錐只畫到 +72h：再往後成員發散太大，圓錐會漲成幾乎覆蓋整張圖的巨圓，
# 既遮住路徑也不再有參考價值。平均路徑與成員線不受此限，仍畫到各自的終點。
CONE_MAX_FH = 72.0
CONE_EDGE   = '#3D5A80'   # 圓錐邊界
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

GALE_KT = 34.0   # 暴風強度門檻


def _mslp_to_color(mslp: float) -> str:
    """依 MSLP_COLOR_BINS 返回對應顏色；NaN 視為最弱一級。"""
    if pd.isna(mslp):
        return MSLP_WEAKEST_COLOR
    for threshold, color, _ in MSLP_COLOR_BINS:
        if mslp <= threshold:
            return color
    return MSLP_WEAKEST_COLOR


def _is_gale(wind) -> bool:
    """是否達暴風強度（>=34 kt）。未達者畫空心圈，達到者畫實心點。"""
    try:
        return float(wind) >= GALE_KT
    except (TypeError, ValueError):
        return False


def _scatter_by_strength(ax, lons, lats, winds, colors, kw, size=11.0,
                         alpha=0.9, zorder=1.15, lw=0.7):
    """畫集合成員的強度點：>=34 kt 實心、<34 kt 空心。

    空心／實心的區分讓密集的成員點群不再糊成一片色塊 —— 未成形的部分退成細圈，
    成形之後才是實心，強度的空間分布一眼可讀。
    """
    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)
    colors = list(colors)
    strong = np.array([_is_gale(w) for w in winds], dtype=bool)
    if strong.size == 0:
        return
    if strong.any():
        ax.scatter(lons[strong], lats[strong], s=size,
                   c=[c for c, k in zip(colors, strong) if k], marker='o',
                   edgecolors='none', alpha=alpha, zorder=zorder, **kw)
    weak = ~strong
    if weak.any():
        ax.scatter(lons[weak], lats[weak], s=size, facecolors='none',
                   edgecolors=[c for c, k in zip(colors, weak) if k], marker='o',
                   linewidths=lw, alpha=min(1.0, alpha + 0.05), zorder=zorder - 0.05, **kw)


def _intensity_legend_handles(ms: float = 7.0) -> list:
    """強度圖例：與地圖一致，TD 用空心圈、其餘實心。"""
    handles = []
    for cat in ['TD', 'TS', 'Cat1', 'Cat2', 'Cat3', 'Cat4', 'Cat5']:
        color = COLOR_MAP[cat]
        if cat == 'TD':
            handles.append(mlines.Line2D([], [], marker='o', ms=ms, ls='', label=cat,
                                         markerfacecolor='none', markeredgecolor=color,
                                         markeredgewidth=1.1, color=color))
        else:
            handles.append(mlines.Line2D([], [], marker='o', ms=ms, ls='', label=cat,
                                         color=color, markeredgecolor='none'))
    return handles


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
                         det_label: str | None = None):
    """左上角的 Track Source 圖例（靜態圖與動畫幀共用同一份定義）。

    det_label 有值時多一列決定報（ECMWF HRES／AIFS-single）；WNC 系列沒有
    對應產品，維持原本的四列。
    """
    handles = [
        mlines.Line2D([], [], color=TRACK_LINE, lw=1.4),
        mlines.Line2D([], [], color=MEAN_COLOR, marker='o', ms=ms * 0.55, lw=2.4,
                      markerfacecolor='white', markeredgecolor=MEAN_COLOR,
                      markeredgewidth=1.4),
    ]
    labels = ['Ensemble Members', f'{model_name} Mean']
    if det_label:
        handles.append(mlines.Line2D([], [], color=DET_COLOR, lw=2.2, linestyle=DET_DASH))
        labels.append(det_label)
    handles += [
        mlines.Line2D([], [], color=CONE_FILL, lw=6, alpha=0.5),
        _init_legend_handle(ms),
    ]
    labels += [f'Uncertainty Cone (≤ {int(CONE_MAX_FH)} h)', 'Init Position']
    leg = ax.legend(handles=handles, labels=labels, loc='upper left', title='Track Source',
                    fontsize=fontsize, borderpad=0.7, labelspacing=0.42,
                    handlelength=1.4, handletextpad=0.7,
                    handler_map={tuple: HandlerTuple(ndivide=1, pad=0)}, **LEGEND_KW)
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


def _label_box(alpha: float = 0.92) -> dict:
    """路徑標註用的白底圓角框。"""
    return dict(boxstyle='round,pad=0.28', facecolor='white',
                edgecolor=BOX_EDGE, alpha=alpha, linewidth=0.8)


def _setup_basemap(ax, extent, grid_step: float | None = None, label_size: int = 8):
    """Cartopy 底圖統一樣式。

    海面先加、陸地後加：兩者的預設 zorder 同為 -1，後加入者疊在上面；反過來
    （原本的順序）會讓半透明海面蓋住陸地，整張圖發灰。
    """
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    ax.add_feature(cfeature.OCEAN, facecolor=BASEMAP['ocean'])
    ax.add_feature(cfeature.LAND, facecolor=BASEMAP['land'])
    ax.coastlines(resolution='50m', linewidth=0.7, color=BASEMAP['coast'], zorder=0.6)
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
    """左標題放主資訊、右標題放初始時間與成員數。

    靠左對齊比置中更接近作業型產品的排版，也讓兩段資訊不必擠成一行。
    """
    ax.set_title(main, loc='left', fontsize=main_size, fontweight='bold',
                 color=TEXT_DARK, pad=10)
    if right:
        ax.set_title(right, loc='right', fontsize=right_size, color=TEXT_MUTED, pad=10)


def _watermark(ax, side: str = 'right') -> None:
    """署名。side 決定貼左下或右下 —— 路徑圖右下角被強度圖例佔著，只能放左下。"""
    x, ha = (0.995, 'right') if side == 'right' else (0.005, 'left')
    ax.text(x, 0.008, 'By Pillar', transform=ax.transAxes,
            ha=ha, va='bottom', fontsize=7, style='italic',
            color=TEXT_MUTED, zorder=10)

FIG_AR = 1.40
FIG_H = 8
FIG_W = FIG_AR * FIG_H
FIG_DPI = 300

# 目標颱風 Track ID — 從最新 CSV 自動偵測，無需手動修改
TARGET_TRACK_IDS = _auto_detect_track_ids(MEAN_DIR)
JTWC_FORECAST_URLS, JTWC_TEXT_URLS = _build_jtwc_urls(TARGET_TRACK_IDS)


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
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        
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
    if kt < 34: return 'TD'
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

def _auto_extent(lat_vals, lon_vals, pad_deg=3.0):
    """計算地圖範圍，自動選擇較緊湊的經度表達方式。"""
    lon_vals = np.asarray(lon_vals, dtype=float)
    lat_vals = np.asarray(lat_vals, dtype=float)
    lon_vals = lon_vals[~np.isnan(lon_vals)]
    lat_vals = lat_vals[~np.isnan(lat_vals)]
    
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
    sub = sub.dropna(subset=["valid_time", "lat", "lon"]).sort_values(["sample", "valid_time"]).reset_index(drop=True)
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
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
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

def generate_frame_sequence(df: pd.DataFrame, mean_df: pd.DataFrame, init_time: pd.Timestamp, track_id: str, output_dir: str, max_frames: int = 72, model_name: str = "WNC2-r2", det_df: pd.DataFrame | None = None, det_label: str | None = None) -> list:
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

        # ── 不確定性圓錐（截至 current_time）──────────────────────────────────
        # Pass full df so circle radii are computed from the complete ensemble
        # (consistent across frames), and limit drawing via max_fh.
        fh_now = (pd.to_datetime(current_time) - init_time).total_seconds() / 3600.0
        cone_stop_fh = _compute_cone_stop_fh(df, init_time, max_fh=fh_now)
        _draw_uncertainty_cone(ax, df, mean_df, init_time, use_360, kw, max_fh=fh_now)

        # ── 起始位置星形標記 ──────────────────────────────────────────────────
        _draw_init_marker(ax, init_lon_star, init_lat_star, kw, scale=0.9)

        # ── 集合成員軌跡 ──────────────────────────────────────────────────────
        for sid, g in df.groupby("sample"):
            g = g[g['valid_time'] <= current_time].sort_values('valid_time')
            if not g.empty:
                lons = _normalize_lon_values(g["lon"].to_numpy(), use_360=use_360)
                lats = g["lat"].to_numpy()
                for seg_lon, seg_lat in _split_track_segments(lons, lats):
                    ax.plot(seg_lon, seg_lat, color=TRACK_LINE, linewidth=0.6, alpha=0.55,
                            zorder=0.9, solid_capstyle='round', **kw)
                last_pt = g.iloc[-1]
                wind = last_pt.get('wind', np.nan)
                cat = ss_category(wind)
                last_lon = _normalize_lon_values([last_pt['lon']], use_360=use_360)[0]
                _scatter_by_strength(ax, [last_lon], [last_pt['lat']], [wind],
                                     [COLOR_MAP.get(cat, COLOR_MAP['Unknown'])], kw,
                                     size=17, alpha=0.9, zorder=1.15, lw=0.8)

        # ── 平均軌跡 + 24h 標記 ───────────────────────────────────────────────
        mean_subset = mean_df[mean_df['valid_time'] <= current_time].sort_values('valid_time')
        if cone_stop_fh is not None:
            cone_stop_time = init_time + pd.to_timedelta(cone_stop_fh, unit='h')
            mean_subset = mean_subset[mean_subset['valid_time'] <= cone_stop_time]
        if not mean_subset.empty:
            mean_lons = _normalize_lon_values(mean_subset["lon"].to_numpy(), use_360=use_360)
            mean_lats = mean_subset["lat"].to_numpy()
            for seg_lon, seg_lat in _split_track_segments(mean_lons, mean_lats):
                ax.plot(seg_lon, seg_lat, color='white', lw=4.4, alpha=0.85,
                        solid_capstyle='round', zorder=3.9, **kw)
                ax.plot(seg_lon, seg_lat, color=MEAN_COLOR, lw=2.4,
                        solid_capstyle='round', zorder=4, **kw)
            last_mean_pt = mean_subset.iloc[-1]
            last_mean_lon = _normalize_lon_values([last_mean_pt['lon']], use_360=use_360)[0]
            last_fh = int(round((last_mean_pt['valid_time'] - init_time).total_seconds() / 3600.0))
            last_intensity = _format_intensity_label(last_mean_pt.get('wind', np.nan))
            ax.scatter([last_mean_lon], [last_mean_pt['lat']], marker='o', color=MEAN_COLOR,
                       s=52, ec='white', zorder=5, linewidth=1.4, **kw)
            ax.text(last_mean_lon + LABEL_OFFSET,
                    last_mean_pt['lat'] + LABEL_OFFSET, f'+{last_fh}h\n{last_intensity}',
                    fontsize=6.5, color=TEXT_DARK, fontweight='bold', zorder=6,
                    bbox=_label_box(), clip_on=True, **kw)

            pts_24h_mean = get_24h_markers(mean_subset, init_time)
            if not pts_24h_mean.empty:
                marker_lons = _normalize_lon_values(pts_24h_mean['lon'].to_numpy(), use_360=use_360)
                ax.scatter(marker_lons, pts_24h_mean['lat'], marker='o', s=34, facecolors='white',
                           edgecolors=MEAN_COLOR, linewidths=1.4, zorder=5, **kw)
                # +Nh 時間標籤
                for i, (_, pt) in enumerate(pts_24h_mean.iterrows()):
                    fh = int((pt['valid_time'] - init_time).total_seconds() / 3600)
                    if fh == 0 or fh == last_fh:
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
        _track_source_legend(ax, model_name, fontsize=8, ms=10,
                             det_label=det_label if has_det else None)

        int_leg = ax.legend(handles=_intensity_legend_handles(ms=6), loc='lower right',
                            bbox_to_anchor=(0.995, 0.005), title='Intensity  ·  filled ≥ 34 kt',
                            fontsize=7, ncol=4, borderpad=0.6, labelspacing=0.28,
                            handlelength=0.9, handletextpad=0.35, columnspacing=1.0,
                            markerscale=0.85, borderaxespad=0.5, **LEGEND_KW)
        _style_legend(int_leg)
        ax.add_artist(int_leg)

        # ── 標題 ──────────────────────────────────────────────────────────────
        time_str = pd.to_datetime(current_time).strftime('%Y-%m-%d %H:%M UTC')
        init_str = pd.to_datetime(init_time).strftime('%Y-%m-%d %H:%M UTC')
        _set_map_titles(ax,
                        f"{model_name}  ·  {track_id}  Track Evolution",
                        f"Valid {time_str}\nInit {init_str}",
                        main_size=12.5, right_size=8)
        plt.tight_layout(pad=0.6)
        frame_path = os.path.join(output_dir, f"frame_{frame_idx:04d}.png")
        plt.savefig(frame_path, dpi=150, bbox_inches='tight', facecolor='white', pad_inches=0.12)
        frame_paths.append(frame_path)
        plt.close(fig)

        print(f"[FRAME] 已生成第 {frame_idx + 1}/{len(all_times)} 幀")

    return frame_paths


def create_gif_from_frames(frame_paths: list[str], gif_path: str, duration_ms: int = 180, loop: int = 0) -> str:
    """將幀序列輸出為 GIF 動圖。"""
    if not frame_paths:
        print("[GIF] 無可用幀，略過 GIF 生成")
        return None
    if not HAS_PIL:
        print("[GIF] 未安裝 Pillow，略過 GIF 生成")
        return None

    sorted_paths = sorted(frame_paths)
    images = []
    try:
        for p in sorted_paths:
            with Image.open(p) as im:
                images.append(im.convert("P", palette=Image.ADAPTIVE).copy())

        first, rest = images[0], images[1:]
        first.save(
            gif_path,
            save_all=True,
            append_images=rest,
            duration=duration_ms,
            loop=loop,
            optimize=False,
            disposal=2,
        )
        print(f"[GIF] 已輸出動圖：{gif_path}")
        return gif_path
    except Exception as e:
        print(f"[GIF] 生成失敗: {e}")
        return None


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




def _draw_uncertainty_cone(ax, df: pd.DataFrame, mean_df: pd.DataFrame,
                           init_time: pd.Timestamp, use_360: bool, kw: dict,
                           max_fh: float = None):
    """CWA-style uncertainty cone using the true geometric union of circles.

    Approach: build one circle per 12-h step (90th-pct ensemble spread,
    non-decreasing radius), then take their Shapely unary_union.  The union
    boundary is by construction non-self-intersecting and monotonically grows
    as more circles are added — no analytical envelope needed.

    max_fh : limit drawing to this forecast hour (animation mode); circles are
             always computed from the full df so radii stay consistent across frames.
    """
    if not HAS_SCIPY or df.empty or mean_df.empty or init_time is None:
        return

    cone_stop_fh = _compute_cone_stop_fh(df, init_time, max_fh=max_fh)
    if cone_stop_fh is None:
        return
    # 圓錐最多畫到 CONE_MAX_FH。刻意只夾在這裡、不動 _compute_cone_stop_fh：
    # 那個回傳值同時決定平均路徑要畫到幾小時，一起夾就會把平均路徑也砍到 72h。
    cone_stop_fh = min(cone_stop_fh, CONE_MAX_FH)

    work = df.copy()
    work['fh'] = (work['valid_time'] - init_time).dt.total_seconds() / 3600.0

    mean_s = mean_df.sort_values('valid_time').copy()
    mean_s['fh'] = (mean_s['valid_time'] - init_time).dt.total_seconds() / 3600.0
    mean_s['lon_n'] = _normalize_lon_values(mean_s['lon'].to_numpy(), use_360=use_360)

    # ── 1. Discrete circles at 12-h steps ────────────────────────────────────
    t_kn, cx_kn, cy_kn, r_kn = [], [], [], []
    for t in np.arange(0, cone_stop_fh + 1, 12):
        sub = work[abs(work['fh'] - t) < 3.5]
        if sub.empty:
            continue
        lons = _normalize_lon_values(sub['lon'].to_numpy(), use_360=use_360)
        lats = sub['lat'].to_numpy()
        mt   = mean_s[abs(mean_s['fh'] - t) < 3.5]
        cx   = float(mt.iloc[0]['lon_n']) if not mt.empty else float(np.nanmean(lons))
        cy   = float(mt.iloc[0]['lat'])   if not mt.empty else float(np.nanmean(lats))
        r    = float(np.percentile(np.sqrt((lons - cx)**2 + (lats - cy)**2), 90))
        t_kn.append(t); cx_kn.append(cx); cy_kn.append(cy); r_kn.append(r)

    if len(t_kn) < 2:
        return

    t_arr  = np.array(t_kn,  dtype=float)
    cx_arr = np.array(cx_kn, dtype=float)
    cy_arr = np.array(cy_kn, dtype=float)
    r_arr  = np.array(r_kn,  dtype=float)
    for i in range(1, len(r_arr)):          # enforce non-decreasing radius
        r_arr[i] = max(r_arr[i], r_arr[i - 1])

    # ── 2. Smooth splines for centre and radius ───────────────────────────────
    cs_x = CubicSpline(t_arr, cx_arr, bc_type='not-a-knot')
    cs_y = CubicSpline(t_arr, cy_arr, bc_type='not-a-knot')
    cs_r = PchipInterpolator(t_arr, r_arr)   # monotone → radius stays non-decreasing

    # ── 3. Build cone polygon ─────────────────────────────────────────────────
    if HAS_SHAPELY:
        # Use a FIXED step (np.arange) so the same t values are sampled in every frame.
        # linspace(0, t_arr[-1], N) shifts all intermediate t positions as t_arr[-1]
        # grows, causing the early cone to drift. With arange(0, ..., STEP_H) the
        # circles at t=0, STEP_H, 2*STEP_H, ... are identical across all frames —
        # only new circles at the trailing end are added as max_fh increases.
        STEP_H = 1.0   # hours — fixed step guarantees stability of the early cone

        t_dense  = np.arange(t_arr[0], t_arr[-1] + STEP_H * 0.5, STEP_H)

        # 圓心沿「實際的平均路徑」取樣，而不是在 12h 節點之間拉直線。
        # 平均路徑是 6 小時一筆、而且前期常常大幅轉向；用 12h 節點連線當中心線的話，
        # 中心線會直接切過轉彎的弦，偏離真正的平均路徑，而前 12 小時圓錐半徑又還
        # 接近 0 —— 平均線就整條跑到圓錐外面去。以平均路徑本身內插即可對齊，
        # 圓心就是圖上畫出來的那條線。
        mean_fh = mean_s['fh'].to_numpy(dtype=float)
        mean_x  = mean_s['lon_n'].to_numpy(dtype=float)
        mean_y  = mean_s['lat'].to_numpy(dtype=float)
        # 平均路徑比圓錐短時（末端超出範圍），該段退回節點內插
        use_mean = (t_dense >= mean_fh[0]) & (t_dense <= mean_fh[-1])
        cx_dense = np.where(use_mean, np.interp(t_dense, mean_fh, mean_x),
                            np.interp(t_dense, t_arr, cx_arr))
        cy_dense = np.where(use_mean, np.interp(t_dense, mean_fh, mean_y),
                            np.interp(t_dense, t_arr, cy_arr))

        # 最小半徑：相鄰兩個圓必須重疊，否則 union 會斷成一串珠子。
        # 直接用實際的圓心間距算（2*MIN_R > 間距），比用節點平均速度推更保險。
        step_d = (np.hypot(np.diff(cx_dense), np.diff(cy_dense))
                  if len(cx_dense) > 1 else np.array([0.0]))
        MIN_R = max(0.10, float(step_d.max()) * 0.6)
        r_dense  = np.maximum(np.interp(t_dense, t_arr, r_arr), MIN_R)

        geo_circles = [
            _ShapelyPoint(float(cx), float(cy)).buffer(float(r), resolution=64)
            for cx, cy, r in zip(cx_dense, cy_dense, r_dense)
        ]
        cone = _shapely_union(geo_circles)
        if cone.geom_type == 'MultiPolygon':
            cone = max(cone.geoms, key=lambda g: g.area)
        raw_lons, raw_lats = map(np.array, cone.exterior.xy)

        # Resample to uniform arc-length, then Gaussian-smooth the C0 circle-arc
        # junctions → visually smooth boundary without self-intersection.
        # Shapely exterior.xy already closes the ring (last==first); do NOT append
        # raw_lons[0] again or arc gets a zero-length final segment and interp1d fails.
        pts_cl = np.column_stack([raw_lons, raw_lats])
        seg = np.hypot(np.diff(pts_cl[:, 0]), np.diff(pts_cl[:, 1]))
        arc = np.concatenate([[0.0], np.cumsum(seg)])
        N_s = 600
        t_u = np.linspace(0.0, arc[-1], N_s, endpoint=False)
        xs_u = _scipy_interp1d(arc, pts_cl[:, 0])(t_u)
        ys_u = _scipy_interp1d(arc, pts_cl[:, 1])(t_u)
        # Sigma in PHYSICAL arc-length (degrees), not sample count.
        # A fixed SMOOTH_DEG ensures the same physical smoothing scale in every frame
        # regardless of the total cone perimeter → no drift in the early cone.
        SMOOTH_DEG = 0.20                              # smooth over 0.2° of arc
        sigma = max(2, round(SMOOTH_DEG * N_s / arc[-1]))
        # Roll the array so the Gaussian wrap seam falls at the cone's tail
        # (0h initial position), not on the leading cap arc.  If the Shapely
        # exterior starts mid-cap, mode='wrap' blends opposite sides of the arc
        # across the array boundary → concave dent at the leading edge.
        _roll_idx = int(np.argmin(np.hypot(xs_u - float(cx_dense[0]),
                                           ys_u - float(cy_dense[0]))))
        xs_u = np.roll(xs_u, -_roll_idx)
        ys_u = np.roll(ys_u, -_roll_idx)
        poly_lons = list(_scipy_gf1d(xs_u, sigma=sigma, mode='wrap'))
        poly_lats = list(_scipy_gf1d(ys_u, sigma=sigma, mode='wrap'))

    else:
        # Analytical envelope fallback (may self-intersect on sharply curved tracks)
        N    = 400
        t_f  = np.linspace(t_arr[0], t_arr[-1], N)
        cx_f = cs_x(t_f); cy_f = cs_y(t_f); r_f = np.maximum(cs_r(t_f), 0.0)
        xt_f = cs_x(t_f, 1); yt_f = cs_y(t_f, 1); rt_f = cs_r(t_f, 1)
        v_f  = np.where(np.hypot(xt_f, yt_f) < 1e-9, 1e-9, np.hypot(xt_f, yt_f))
        kappa = np.clip(rt_f / v_f, -1.0, 1.0)
        eta   = np.sqrt(np.maximum(0.0, 1.0 - kappa**2))
        along_x = -r_f * kappa * xt_f / v_f
        along_y = -r_f * kappa * yt_f / v_f
        perp_x  =  r_f * eta   * yt_f / v_f
        perp_y  =  r_f * eta   * xt_f / v_f
        x_L = cx_f + along_x - perp_x
        y_L = cy_f + along_y + perp_y
        x_R = cx_f + along_x + perp_x
        y_R = cy_f + along_y - perp_y

        def _norm_angle(a, phi, side):
            if side == 'L':
                while a <= phi:            a += 2 * np.pi
                while a > phi + 2*np.pi:  a -= 2 * np.pi
            else:
                while a > phi:             a -= 2 * np.pi
                while a <= phi - 2*np.pi: a += 2 * np.pi
            return a

        phi_tail = np.arctan2(yt_f[-1], xt_f[-1])
        aL_tail  = _norm_angle(np.arctan2(y_L[-1]-cy_f[-1], x_L[-1]-cx_f[-1]), phi_tail, 'L')
        aR_tail  = _norm_angle(np.arctan2(y_R[-1]-cy_f[-1], x_R[-1]-cx_f[-1]), phi_tail, 'R')
        tail_a    = np.linspace(aL_tail, aR_tail, 64)
        tail_lons = cx_f[-1] + r_f[-1] * np.cos(tail_a)
        tail_lats = cy_f[-1] + r_f[-1] * np.sin(tail_a)
        poly_lons  = list(x_L) + list(tail_lons) + list(x_R[::-1])
        poly_lats  = list(y_L) + list(tail_lats) + list(y_R[::-1])
        r0 = float(r_f[0])
        if r0 > 0.05:
            phi_start = np.arctan2(yt_f[0], xt_f[0])
            aL_start  = _norm_angle(np.arctan2(y_L[0]-cy_f[0], x_L[0]-cx_f[0]), phi_start, 'L')
            aR_start  = _norm_angle(np.arctan2(y_R[0]-cy_f[0], x_R[0]-cx_f[0]), phi_start, 'R')
            start_a    = np.linspace(aR_start, aL_start - 2*np.pi, 48)
            poly_lons  = list(cx_f[0] + r0*np.cos(start_a)) + poly_lons
            poly_lats  = list(cy_f[0] + r0*np.sin(start_a)) + poly_lats

    # ── 3. Draw ───────────────────────────────────────────────────────────────
    ax.fill(poly_lons, poly_lats, color=CONE_FILL, alpha=0.22, zorder=0.35, **kw)
    ax.plot(np.append(poly_lons, poly_lons[:1]),
            np.append(poly_lats, poly_lats[:1]),
            color=CONE_EDGE, lw=1.3, alpha=0.9, ls=(0, (5, 2.5)), zorder=0.50, **kw)


def _draw_det_track(ax, det_df: pd.DataFrame, init_time: pd.Timestamp, use_360: bool, kw: dict,
                    upto: pd.Timestamp | None = None, label_end: bool = True) -> None:
    """畫決定報路徑（虛線）—— 靜態圖與動畫幀共用。

    刻意不套用平均路徑那套「半數成員」截斷：決定報只有一條，跑到哪就畫到哪，
    截斷反而會讓人以為模式提早結束預報。zorder 介於平均路徑（4）與其標記
    （5）之間，讓平均路徑仍是視覺主角。
    """
    if det_df is None or det_df.empty:
        return
    d = det_df.sort_values('valid_time')
    if upto is not None:
        d = d[d['valid_time'] <= upto]
    if d.empty:
        return

    lons = _normalize_lon_values(d['lon'].to_numpy(), use_360=use_360)
    lats = d['lat'].to_numpy()
    for seg_lon, seg_lat in _split_track_segments(lons, lats):
        ax.plot(seg_lon, seg_lat, color='white', lw=4.0, alpha=0.85,
                solid_capstyle='round', zorder=4.1, **kw)
        ax.plot(seg_lon, seg_lat, color=DET_COLOR, lw=2.2, linestyle=DET_DASH,
                solid_capstyle='round', zorder=4.2, **kw)

    last = d.iloc[-1]
    last_lon = _normalize_lon_values([last['lon']], use_360=use_360)[0]
    ax.scatter([last_lon], [last['lat']], marker='D', color=DET_COLOR, s=34,
               ec='white', zorder=4.6, linewidth=1.2, **kw)
    if label_end and init_time is not None:
        fh = int(round((last['valid_time'] - init_time).total_seconds() / 3600.0))
        ax.text(last_lon + LABEL_OFFSET, last['lat'] - LABEL_OFFSET,
                f'DET +{fh}h', fontsize=6.5, color=DET_COLOR, fontweight='bold',
                zorder=6, bbox=_label_box(), clip_on=True, **kw)


def plot_forecast_map(df: pd.DataFrame, mean_df: pd.DataFrame, init_time: pd.Timestamp, track_id: str, save_path: str, model_name: str = "WNC2-r2", det_df: pd.DataFrame | None = None, det_label: str | None = None):
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

    # 不確定性圓錐（ensemble spread）
    _draw_uncertainty_cone(ax, df, mean_df, init_time, use_360, kw)

    # 每個 member（灰色線）與 6h 強度標記（彩色點）
    for _sid, g in df.groupby("sample"):
        g = g.sort_values('valid_time')
        lons = _normalize_lon_values(g["lon"].to_numpy(), use_360=use_360)
        lats = g["lat"].to_numpy()
        for seg_lon, seg_lat in _split_track_segments(lons, lats):
            ax.plot(seg_lon, seg_lat, color=TRACK_LINE, linewidth=0.45, alpha=0.5,
                    zorder=0.9, solid_capstyle='round', **kw)
        pts_6h = get_6h_markers(g, init_time)
        if not pts_6h.empty:
            marker_lons = _normalize_lon_values(pts_6h['lon'].to_numpy(), use_360=use_360)
            winds = (pts_6h['wind'] if 'wind' in pts_6h.columns
                     else pd.Series(np.nan, index=pts_6h.index)).to_numpy()
            colors = [COLOR_MAP.get(ss_category(w), COLOR_MAP['Unknown']) for w in winds]
            _scatter_by_strength(ax, marker_lons, pts_6h['lat'].to_numpy(), winds, colors, kw,
                                 size=10, alpha=0.85, zorder=1.15, lw=0.55)

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
        ax.plot(seg_lon, seg_lat, color='white', lw=4.4, alpha=0.85,
                solid_capstyle='round', zorder=3.9, **kw)
        ax.plot(seg_lon, seg_lat, color=MEAN_COLOR, lw=2.4,
                solid_capstyle='round', zorder=4, **kw)
    last_mean_pt = mean_plot_df.sort_values('valid_time').iloc[-1]
    last_mean_lon = _normalize_lon_values([last_mean_pt['lon']], use_360=use_360)[0]
    last_fh = int(round((last_mean_pt['valid_time'] - init_time).total_seconds() / 3600.0))
    last_intensity = _format_intensity_label(last_mean_pt.get('wind', np.nan))
    ax.scatter([last_mean_lon], [last_mean_pt['lat']], marker='o', color=MEAN_COLOR, s=54,
               ec='white', zorder=5, linewidth=1.4, **kw)
    ax.text(last_mean_lon + LABEL_OFFSET,
            last_mean_pt['lat'] + LABEL_OFFSET, f'+{last_fh}h\n{last_intensity}',
            fontsize=6.5, color=TEXT_DARK, fontweight='bold', zorder=6,
            bbox=_label_box(), clip_on=True, **kw)
    pts_24h_mean = get_24h_markers(mean_plot_df, init_time)
    if not pts_24h_mean.empty:
        marker_lons = _normalize_lon_values(pts_24h_mean['lon'].to_numpy(), use_360=use_360)
        ax.scatter(marker_lons, pts_24h_mean['lat'], marker='o', s=34, facecolors='white',
                   edgecolors=MEAN_COLOR, linewidths=1.4, zorder=5, **kw)
        # +24h、+48h… 文字標籤（白色描邊，壓在成員點上仍讀得到）
        for i, (_, pt) in enumerate(pts_24h_mean.iterrows()):
            fh = int((pt['valid_time'] - init_time).total_seconds() / 3600)
            if fh == 0 or fh == last_fh:
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
    _track_source_legend(ax, model_name, fontsize=9, ms=11,
                         det_label=det_label if has_det else None)

    int_leg = ax.legend(handles=_intensity_legend_handles(ms=7), loc='lower right',
                        bbox_to_anchor=(0.995, 0.005), title='Intensity  ·  filled ≥ 34 kt',
                        fontsize=8, ncol=4, borderpad=0.6, labelspacing=0.3,
                        handlelength=0.9, handletextpad=0.35, columnspacing=1.0,
                        markerscale=0.85, borderaxespad=0.5, **LEGEND_KW)
    _style_legend(int_leg)
    ax.add_artist(int_leg)

    n_members = int(df['sample'].nunique()) if 'sample' in df.columns else 0
    init_str = pd.to_datetime(init_time).strftime('%Y-%m-%d %H:%M UTC')
    _set_map_titles(ax,
                    f"{model_name}  ·  {track_id}  Ensemble Track Forecast",
                    f"Init {init_str}" + (f"  ·  {n_members} members" if n_members else ""),
                    main_size=15, right_size=9)
    _watermark(ax, side='left')
    plt.tight_layout(pad=0.6)
    plt.savefig(save_path, dpi=FIG_DPI, bbox_inches='tight', facecolor='white', pad_inches=0.12)
    plt.close(fig)
    print(f"[INFO] 已儲存地圖：{save_path}")


# 模式比較圖的線條配色。同一家族用相近色系、決定報用虛線，
# 讓「哪些線來自同一個模式」一眼可辨：
#   WNC 系列與 GENC → 冷色（藍綠）  ECMWF → 暖色（紅橘）  AIFS → 紫紅
# 比較圖一律實線（含決定報）：八條線本來就靠顏色分辨，虛線只會讓
# 短的那幾條看起來斷斷續續。各模式自己的分頁圖上，決定報仍是虛線。
COMPARE_STYLES = {
    'WNC3':      '#16324F',
    'WNC2-r2':   '#1B4F9C',
    'WNC2-r1':   '#5B8DC8',
    'GENC':      '#1FA97E',
    'AIFS':      '#7A3FA8',
    'AIFS-DET':  '#C2569B',
    'ECMWF':     '#B3123F',
    'ECMWF-DET': '#B45309',
}
# 畫線順序：後畫的蓋在先畫的上面，所以主力 WNC2-r2 刻意排在四條 WNC／GENC 的最後。
COMPARE_ORDER = ['WNC3', 'WNC2-r1', 'GENC', 'WNC2-r2',
                 'AIFS', 'AIFS-DET', 'ECMWF', 'ECMWF-DET']
# 圖例順序與畫線順序刻意分開：圖例照模式輩分排（WNC3 → WNC2-r2 → WNC2-r1 →
# GENC → ECMWF → AIFS），疊圖先後則由 COMPARE_ORDER 決定。
COMPARE_LEGEND_ORDER = ['WNC3', 'WNC2-r2', 'WNC2-r1', 'GENC',
                        'AIFS', 'AIFS-DET', 'ECMWF', 'ECMWF-DET']
COMPARE_LABELS = {
    'WNC3': 'WNC3 Mean',
    'WNC2-r2': 'WNC2-r2 Mean',
    'WNC2-r1': 'WNC2-r1 Mean',
    'GENC': 'GENC Mean',
    'AIFS': 'AIFS-ENS Mean',
    'AIFS-DET': 'AIFS-single',
    'ECMWF': 'ECMWF ENS Mean',
    'ECMWF-DET': 'ECMWF HRES',
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
            ax.plot(seg_lon, seg_lat, color='white', lw=4.0, alpha=0.8,
                    solid_capstyle='round', zorder=3.5, **kw)
            ax.plot(seg_lon, seg_lat, color=color, lw=2.2,
                    solid_capstyle='round', zorder=4, **kw)

        # 24h 標記：各模式在同一時間點的位置差距，是這張圖最想讓人看到的東西
        init_time = init_times.get(key)
        if init_time is not None:
            pts = get_24h_markers(d, init_time)
            if not pts.empty:
                mlons = _normalize_lon_values(pts['lon'].to_numpy(), use_360=use_360)
                ax.scatter(mlons, pts['lat'], marker='o', s=22, facecolors='white',
                           edgecolors=color, linewidths=1.3, zorder=5, **kw)

        last = d.iloc[-1]
        last_lon = _normalize_lon_values([last['lon']], use_360=use_360)[0]
        ax.scatter([last_lon], [last['lat']], marker='o', s=30, color=color,
                   ec='white', linewidth=1.1, zorder=5.2, **kw)

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

    leg = ax.legend(handles=handles, labels=labels, loc='upper left', title='Model Mean Tracks',
                    fontsize=8, borderpad=0.7, labelspacing=0.42,
                    handlelength=1.8, handletextpad=0.7, **LEGEND_KW)
    _style_legend(leg)
    ax.add_artist(leg)

    _set_map_titles(ax,
                    f"Multi-Model Comparison  ·  {track_id}",
                    "Mean tracks + deterministic runs  ·  hollow dots = 24 h steps",
                    main_size=15, right_size=9)
    _watermark(ax, side='left')
    plt.tight_layout(pad=0.6)
    plt.savefig(save_path, dpi=FIG_DPI, bbox_inches='tight', facecolor='white', pad_inches=0.12)
    plt.close(fig)
    print(f"[COMPARE] 已儲存模式比較圖：{save_path}")
    return save_path


# 資料來源標註：WNC 系列與 GENC 來自 Weather Lab，ECMWF／AIFS 來自 ECMWF Open Data
# （授權不同，見 ecmwf_bufr 模組說明），圖上不能一律掛 DeepMind。
ECMWF_MODELS = {'ECMWF', 'AIFS'}


def _data_source(model_name: str) -> str:
    return ('ECMWF Open Data' if model_name in ECMWF_MODELS
            else 'Google DeepMind Weather Lab')


def plot_genesis_potential_map(csv_path: str, save_path: str, model_name: str = "WNC2-r2"):
    """繪製西太平洋 Ensemble 潛勢預報總覽圖（以 MSLP 著色）。"""
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
        winds = g['wind'].to_numpy() if 'wind' in g.columns else np.full(len(g), np.nan)

        # 軌跡連線（淡灰）
        ax.plot(lons, lats, color=TRACK_LINE, linewidth=0.45, alpha=0.35,
                zorder=1, solid_capstyle='round', **kw)

        # MSLP 著色圓點：達暴風強度者實心、未達者空心（整條軌跡一次 scatter，
        # 避免逐點繪製拖慢速度）
        colors = [_mslp_to_color(float(m)) for m in mslps]
        _scatter_by_strength(ax, lons, lats, winds, colors, kw,
                             size=11, alpha=0.85, zorder=2, lw=0.6)

    # 圖例（MSLP 色階）
    legend_handles = []
    for _, color, label in MSLP_COLOR_BINS:
        h = mlines.Line2D([], [], marker='o', ms=7.5, ls='',
                          color=color, markeredgecolor='none', label=label)
        legend_handles.append(h)

    leg = ax.legend(handles=legend_handles, loc='upper left',
                    title='min. sea level pressure\nfilled ≥ 34 kt', title_fontsize=8,
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
                    f'{model_name}  ·  Western Pacific Genesis Potential  ·  0–360 h',
                    f'Init {init_time_str}\n{_data_source(model_name)}',
                    main_size=13, right_size=8.5)
    _watermark(ax)
    plt.tight_layout(pad=0.6)
    plt.savefig(save_path, dpi=200, bbox_inches='tight', facecolor='white', pad_inches=0.12)
    plt.close(fig)
    print(f'[GENESIS] 已儲存潛勢預報圖：{save_path}')
    return save_path


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


def _resolve_cycle(cfg: dict) -> tuple[datetime, str] | tuple[None, None]:
    """從最新 cycle 起往回逐 6 小時嘗試（最多 5 個），回傳 (cycle, ensemble CSV 路徑)。"""
    if cfg.get("fetcher") == "ecmwf":
        return _resolve_cycle_ecmwf(cfg)

    latest = _latest_cycle()
    for i in range(5):
        cycle = latest - timedelta(hours=6 * i)
        stamp = _cycle_stamp(cycle)
        path = os.path.join(cfg["ensemble_dir"], f"{cfg['local_prefix']}_{stamp}_paired.csv")
        if os.path.exists(path):
            return cycle, path
        url = _remote_csv_url(cfg["remote"], "ensemble/paired", stamp)
        if _download_file(url, path, f"{cfg['display']}-DL", allow_404=True):
            return cycle, path
    return None, None


def _resolve_cycle_ecmwf(cfg: dict) -> tuple[datetime, str] | tuple[None, None]:
    """ECMWF 版的 cycle 解析：下載 BUFR 並就地轉成 paired CSV。

    ECMWF Open Data 的上架時間與時距都跟 Weather Lab 不同（見 ecmwf_bufr），
    所以起點用 ecmwf_bufr.latest_cycle() 而不是 _latest_cycle()。

    暴風編號的對應要靠 WNC2-r2 的平均路徑當基準（ECMWF 與 JTWC 各自編號，
    對不上），因此 ECMWF 兩個模式必須排在 MODEL_CONFIGS 的 WNC2-r2 之後。
    """
    import ecmwf_bufr

    latest = ecmwf_bufr.latest_cycle()
    for i in range(5):
        cycle = latest - timedelta(hours=6 * i)
        stamp = _cycle_stamp(cycle)
        path = os.path.join(cfg["ensemble_dir"], f"{cfg['local_prefix']}_{stamp}_paired.csv")
        if os.path.exists(path):
            return cycle, path
        try:
            ok = ecmwf_bufr.fetch_cycle(cfg["ecmwf_model"], cycle, cfg,
                                        ref_mean_dir=MEAN_DIR, ref_prefix="WNC2-r2",
                                        scratch_dir=ECMWF_SCRATCH_DIR)
        except Exception as e:
            print(f"[{cfg['display']}-DL] cycle {stamp} 取用失敗: {e}")
            continue
        if ok:
            return cycle, path
    return None, None


def _get_cyclogenesis_csv(cfg: dict, stamp: str) -> str | None:
    """取得潛勢 CSV：優先用當期檔，否則下載；下載失敗才退而用目錄中最新檔。"""
    if not cfg.get("cyc_dir"):
        return None
    display = cfg["display"]
    if cfg.get("fetcher") == "ecmwf":
        # ECMWF 的潛勢檔是解 BUFR 時一併寫出的，沒有可下載的遠端來源
        path = os.path.join(cfg["cyc_dir"], f"{cfg['local_prefix']}_{stamp}_cyclogenesis.csv")
        if os.path.exists(path):
            return path
        print(f"[{display}-GENESIS] 找不到當期潛勢檔: {os.path.basename(path)}")
        return None
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
    file_re = re.compile(rf"^{p}(WP\d{{6}})_Forecast_(?:Map\.png|Animation\.gif)$")
    dir_re = re.compile(rf"^animation_frames_{p}(WP\d{{6}})$")

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

    jtwc_{TID}.gif 與 {TID}_Model_Comparison.png 都與模式無關（同一顆真實
    颱風各模式共用），因此只能在所有模式都跑完、以 track_id 聯集判斷才安全，
    不能放進 _process_model。
    """
    if not os.path.isdir(OUTPUT_DIR):
        return
    jtwc_re = re.compile(r"^jtwc_(WP\d{6})\.gif$|^(WP\d{6})_Model_Comparison\.png$")
    try:
        names = sorted(os.listdir(OUTPUT_DIR))
    except OSError as e:
        print(f"[CLEANUP] 警告: 無法列出 {OUTPUT_DIR}: {e}")
        return
    for name in names:
        m = jtwc_re.match(name)
        # 兩個分支各佔一個群組，命中的那個才有值
        if not m or (m.group(1) or m.group(2)) in keep_ids:
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
    out_re = re.compile(rf"^(?:{p_alt})_WP\d{{6}}_Forecast_(?:Map\.png|Animation\.gif)$"
                        rf"|^WP_Genesis_Potential_(?:{p_alt})\.png$")
    dir_re = re.compile(rf"^animation_frames_(?:{p_alt})_WP\d{{6}}$")
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


def _process_model(cfg: dict, get_jtwc_text, download_jtwc_img) -> tuple[str | None, list[dict]]:
    """執行單一模式的完整流程：解析 cycle、下載 CSV、繪製潛勢圖與各颱風產品。

    get_jtwc_text / download_jtwc_img 由 main() 傳入，帶跨模式快取
    （同一顆颱風的 JTWC 官方資料與模式無關，不必重複下載）。
    回傳 (潛勢圖路徑或 None, storms 清單)。
    """
    display = cfg["display"]
    print(f"\n[{display}] === 開始處理 {display} 模式 ===")

    cycle, csv_path = _resolve_cycle(cfg)
    if cycle is None:
        raise RuntimeError(f"無法取得最近 5 個 cycle 的 {display} ensemble CSV")
    if cycle != _latest_cycle():
        print(f"[{display}] 回退至 cycle: {cycle.strftime('%Y-%m-%d %HZ')}")
    stamp = _cycle_stamp(cycle)

    # 下載 Ensemble Mean 檔
    mean_csv_path = os.path.join(cfg["mean_dir"], f"{cfg['local_prefix']}_{stamp}_paired.csv")
    if not os.path.exists(mean_csv_path):
        _download_file(_remote_csv_url(cfg["remote"], "ensemble_mean/paired", stamp),
                       mean_csv_path, f"{display}-MEAN")

    # 用當前 cycle 的 mean CSV 偵測颱風，確保不會抓到舊資料
    track_ids = _auto_detect_track_ids(cfg["mean_dir"], preferred_path=mean_csv_path,
                                       model_prefix=cfg["local_prefix"])
    jtwc_forecast_urls, jtwc_text_urls = _build_jtwc_urls(track_ids)

    # 先清掉本模式已不再追蹤的颱風產物，再產生本次結果
    _cleanup_stale_outputs(cfg["output_prefix"], track_ids, display)

    # 決定報（僅 ECMWF／AIFS 有）：整份讀進來，逐颱風再過濾
    det_csv_path = (os.path.join(cfg["det_dir"], f"{cfg['local_prefix']}_{stamp}_deterministic.csv")
                    if cfg.get("det_dir") else None)
    det_label = cfg.get("det_label")

    # 西太平洋潛勢預報圖
    genesis_map_path = None
    cyc_csv_path = _get_cyclogenesis_csv(cfg, stamp)
    if cfg.get("genesis_png") and cyc_csv_path and os.path.exists(cyc_csv_path):
        print(f"[{display}-GENESIS] 正在繪製西太平洋潛勢預報圖...")
        genesis_map_path = plot_genesis_potential_map(
            cyc_csv_path, os.path.join(OUTPUT_DIR, cfg["genesis_png"]), model_name=display)

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
            det_df = None
            if det_csv_path and os.path.exists(det_csv_path):
                try:
                    det_df, _ = load_forecast_dataframe(det_csv_path, tid)
                except Exception as e:
                    print(f"[{display}-DET] {tid} 無決定報路徑: {e}")

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
                              det_df=det_df, det_label=det_label)

            download_jtwc_img(tid, OUTPUT_DIR, jtwc_forecast_urls)

            print("[ANIMATION] 正在生成幀序列...")
            frames_dir = os.path.join(OUTPUT_DIR, f"animation_frames_{prefix}{tid}")
            # 清除舊幀，避免幀數減少時殘留上次多餘的圖
            if os.path.isdir(frames_dir):
                for _old in os.listdir(frames_dir):
                    if _old.startswith("frame_") and _old.endswith(".png"):
                        os.remove(os.path.join(frames_dir, _old))
            frame_paths = generate_frame_sequence(df, mean_df, init_time, tid, frames_dir,
                                                  max_frames=72, model_name=display,
                                                  det_df=det_df, det_label=det_label)

            gif_path = os.path.join(OUTPUT_DIR, f"{prefix}{tid}_Forecast_Animation.gif")
            gif_output = create_gif_from_frames(frame_paths, gif_path, duration_ms=180, loop=0)

            storms.append({
                'track_id': tid,
                'model': display,
                'forecast_map_path': save_path,
                'current_info': current_info,
                'frames_dir': frames_dir,
                'forecast_gif_path': gif_output,
                # 供 main() 組模式比較圖用；不會進到網頁 HTML
                'mean_df': mean_df,
                'det_df': det_df,
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
            genesis_maps.append((cfg["display"], genesis_map_path))
        storms.extend(model_storms)

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
                init_times[f'{model}-DET'] = s.get('init_time')
        path = plot_model_comparison_map(
            tid, entries, os.path.join(OUTPUT_DIR, f"{tid}_Model_Comparison.png"),
            init_times=init_times)
        if path:
            group[0]['comparison_map_path'] = path

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
