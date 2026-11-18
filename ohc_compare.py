# -*- coding: utf-8 -*-
"""颱風經過前後的海洋熱含量（OHC / TCHP）比較圖。

輸出三張 NRL/CMEMS OHC 產品格式的圖：
  1. 颱風生成當天的 OHC
  2. 颱風消散當天的 OHC（疊颱風路徑）
  3. 兩者差值（疊颱風路徑）

OHC 定義：rho * cp * ∫ (T - 26)+ dz，單位 kJ/cm^2（= 1e7 J/m^2）。

用法：
    python OHC.py                                   # 預設：巴威 Bavi (09W, 2026)
    python OHC.py --day1 2026-07-01 --day2 2026-07-14
    python OHC.py --track tracks/bavi_2026.csv      # 路徑 CSV（需含 lon,lat 欄）
    python OHC.py --no-download                     # 已有 nc 檔，只重畫圖
    python OHC.py --gif                             # 另外輸出每日一張的動畫 GIF
    python OHC.py --dpi 300                         # 提高輸出解析度

首次執行需要 CMEMS 帳號：`copernicusmarine login`（互動式 prompt 在自動化
環境會卡住，可改用 `copernicusmarine login --username X --password Y`）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd
import xarray as xr

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

import cartopy.crs as ccrs
import cartopy.feature as cfeature

import copernicusmarine as cm

# Windows 終端機預設 cp950，直接印中文與 ² 會炸掉
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- 參數設定 --
# 全球 1/12° 日平均 3D 海溫。anfc（分析預報）涵蓋 2022-06 起至今；
# 2022 年以前的個案要改用再分析：cmems_mod_glo_phy_my_0.083deg_P1D-m（1993-01 起）
DATASET = "cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m"
DATASET_REANALYSIS = "cmems_mod_glo_phy_my_0.083deg_P1D-m"

RHO = 1025.0       # 海水密度 kg/m^3
CP = 3850.0        # 海水比熱 J/(kg*K)
T_REF = 26.0       # TCHP 基準溫度 °C
MAX_DEPTH = 300.0  # 積分深度上限 m（26°C 等溫面幾乎不會超過這個深度）

# 預設範圍：與 NRL OHC 產品同範圍的西北太平洋
BBOX = dict(lon_min=100.0, lon_max=180.0, lat_min=0.0, lat_max=50.0)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "ohc_output")
DEFAULT_TRACK = os.path.join(BASE_DIR, "tracks", "bavi_2026.csv")

# cfeature.LAND / COASTLINE 預設是 110m（最粗），小島小灣都畫不出來；
# 改用 10m（Natural Earth 最細的一級），台灣海岸線、沖繩諸島這種小地形
# 才看得出來。第一次執行會另外下載這份 shapefile，之後 cartopy 會快取。
#
# 注意：一定要用 cfeature.LAND.with_scale("10m")，不要自己用
# cfeature.NaturalEarthFeature("physical", "land", "10m") 生一個新的——
# 兩者理論上該一樣，但自建的那個疊在 pcolormesh 上面時，畫面右下（東京、
# 台灣、菲律賓一帶）的陸地會被畫成海洋的顏色，變成一條詭異的斜線分界，
# 跟 pcolormesh 是否 rasterized、加入順序、zorder 都無關（都測過，
# 唯一有差的變數就是 with_scale() vs 自建 NaturalEarthFeature）。
LAND_10M = cfeature.LAND.with_scale("10m")
COASTLINE_10M = cfeature.COASTLINE.with_scale("10m")

# 中文字型（Windows 內建 JhengHei；沒有就退回 DejaVu，只是中文會變方框）
# 注意 JhengHei 沒有 U+2212 減號字符，字串一律用 ASCII 的 "-"
plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Noto Sans TC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# NRL/CMEMS OHC 產品配色：每 10 kJ/cm^2 一階，0~220 共 22 階
OHC_LEVELS = np.arange(0, 230, 10)
OHC_COLORS = [
    "#19c4e0", "#00c9c0", "#00c98a", "#3fce47", "#78d42f", "#a8da28",
    "#cfdd26", "#e3d126", "#ebb527", "#eda528", "#ee9629", "#ef8a2a",
    "#f07d2b", "#f0702c", "#ef5f2e", "#ec4a30", "#e93c33", "#e63237",
    "#e3283d", "#e11f5c", "#e0158a", "#e211a0",
]

# 路徑強度分級色票：與 generate_forecast_website.py 的 CAT_COLOR_MAP／
# ss_category 同一組門檻與顏色（灰→藍→綠→琥珀→橘→紅→紫），刻意複製而不
# import，避免拉進那支模組的下載目錄等副作用。改色時兩邊要一起改。
CAT_COLOR_MAP = {
    "TD": "#8A97A6", "TS": "#2E86C8", "Cat1": "#1FA97E", "Cat2": "#E0AC2B",
    "Cat3": "#EE7A22", "Cat4": "#DC3A4E", "Cat5": "#A548C8", "Unknown": "#B7C0CA",
}
CAT_ORDER = ["TD", "TS", "Cat1", "Cat2", "Cat3", "Cat4", "Cat5"]


def ss_category(kt) -> str:
    if kt is None or (isinstance(kt, float) and np.isnan(kt)):
        return "Unknown"
    kt = float(kt)
    if kt < 35: return "TD"
    if kt < 64: return "TS"
    if kt < 83: return "Cat1"
    if kt < 96: return "Cat2"
    if kt < 113: return "Cat3"
    if kt < 137: return "Cat4"
    return "Cat5"


# 差值用雙色階（藍＝變冷＝颱風帶走熱量，紅＝變暖），0 兩側是幾乎看不出來的淡色。
# 12 階是刻意的：色階要能被 6 整除，刻度才會落在 10 的倍數上。
# 0 兩側的兩階刻意同為中性灰，當成「沒變」的死區：北方海域兩天都是 OHC=0，
# 差值剛好落在 0 的邊界上，不留死區的話整片會被畫成淡紅，看起來像普遍增溫。
DIFF_COLORS = [
    "#08306b", "#1a5da8", "#3282be", "#6baed6", "#a8cfe6", "#f0f0f0",
    "#f0f0f0", "#fcc39f", "#fb8d59", "#ec5d3c", "#c72e21", "#7f0000",
]


# ---------------------------------------------------------------- 資料下載 --
def check_credentials() -> bool:
    """確認本機已有 CMEMS 憑證；沒有就提示登入（互動式輸入在自動化環境會卡住）。"""
    try:
        ok = cm.login(check_credentials_valid=True)
    except Exception as e:
        print(f"[CMEMS] 憑證檢查失敗：{e}")
        ok = False
    if not ok:
        print("[CMEMS] 找不到可用的 CMEMS 憑證。請先在終端機執行：")
        print("            copernicusmarine login")
        print("        （免費註冊：https://data.marine.copernicus.eu/register）")
        print("        登入一次會存在 ~/.copernicusmarine，之後就不用再輸入。")
    return bool(ok)


def download_day(date: str, out_dir: str) -> str:
    """下載單日的 thetao 子集；檔案已存在就直接沿用。"""
    fname = f"thetao_{date}.nc"
    path = os.path.join(out_dir, fname)
    if os.path.exists(path):
        print(f"[CMEMS] 已存在，沿用: {fname}")
        return path

    print(f"[CMEMS] 下載 {date} -> {fname}")
    cm.subset(
        dataset_id=DATASET,
        variables=["thetao"],
        minimum_longitude=BBOX["lon_min"], maximum_longitude=BBOX["lon_max"],
        minimum_latitude=BBOX["lat_min"], maximum_latitude=BBOX["lat_max"],
        minimum_depth=0, maximum_depth=MAX_DEPTH,
        start_datetime=f"{date}T00:00:00", end_datetime=f"{date}T23:59:59",
        output_directory=out_dir,
        output_filename=fname,
        skip_existing=True,
    )
    if not os.path.exists(path):
        raise FileNotFoundError(f"下載後找不到檔案：{path}")
    return path


# ---------------------------------------------------------------- OHC 計算 --
def layer_thickness(depth: xr.DataArray) -> xr.DataArray:
    """由各層深度中心推回層厚 dz（相鄰層取中點當界面，最上界固定為 0 m）。"""
    z = np.asarray(depth.values, dtype=float)
    if z.size == 1:
        dz = np.array([2.0 * z[0]])
    else:
        inner = (z[:-1] + z[1:]) / 2.0
        bottom = min(z[-1] + (z[-1] - z[-2]) / 2.0, MAX_DEPTH)
        edges = np.concatenate([[0.0], inner, [bottom]])
        dz = np.diff(edges)
    return xr.DataArray(dz, coords={depth.name: depth}, dims=depth.name)


def calc_ohc(path: str) -> xr.DataArray:
    """算 26°C 以上熱含量，單位 kJ/cm^2（颱風界慣用單位）。"""
    with xr.open_dataset(path) as ds:
        T = ds["thetao"]
        depth_name = "depth" if "depth" in T.dims else [d for d in T.dims if "dep" in d.lower()][0]
        dz = layer_thickness(T[depth_name])

        ohc = RHO * CP * ((T - T_REF).clip(min=0) * dz).sum(depth_name) / 1e7
        if "time" in ohc.dims:
            ohc = ohc.mean("time")

        # 用最上層的有效值當陸地遮罩（陸地格點會被 sum 填成 0，不遮會誤判成冷區）
        surface = T.isel({depth_name: 0})
        if "time" in surface.dims:
            surface = surface.isel(time=0)
        ohc = ohc.where(surface.notnull())
        return ohc.load()


# ------------------------------------------------------------------- 繪圖 --
def load_track(path: str | None):
    """讀路徑檔（CSV，需含 lon/lat 欄位，大小寫不拘）；沒給或檔案不在就回 None。"""
    if not path:
        return None
    if not os.path.exists(path):
        print(f"[TRACK] 找不到路徑檔，略過疊圖：{path}")
        return None

    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    lon_col = next((cols[k] for k in ("lon", "longitude", "lon_deg") if k in cols), None)
    lat_col = next((cols[k] for k in ("lat", "latitude", "lat_deg") if k in cols), None)
    if lon_col is None or lat_col is None:
        raise ValueError(f"{path} 缺少 lon/lat 欄位，實際欄位：{list(df.columns)}")
    out = df[[lon_col, lat_col]].astype(float)
    out.columns = ["lon", "lat"]
    if "time" in cols:
        out["time"] = pd.to_datetime(df[cols["time"]])
    wind_col = next((cols[k] for k in ("wind_kt", "wind", "vmax", "max_wind") if k in cols), None)
    if wind_col is not None:
        out["wind_kt"] = pd.to_numeric(df[wind_col], errors="coerce")
    return out


def draw_track(ax, track, legend: bool = True) -> None:
    """路徑依強度分級上色（與預報網站同一組色票），白邊確保在彩虹底圖上
    不論深淺都看得見；每日 00Z 標點（不再逐點標日期文字，標題已經有日期，
    每天一個文字反而擠在密集路段——標題的日期字改大一些取代它）。"""
    if track is None:
        return
    proj = ccrs.PlateCarree()
    lon, lat = track.lon.to_numpy(), track.lat.to_numpy()

    # 白邊墊底：整條路徑先畫一次粗白線，彩色線疊上去才不會被底圖顏色吃掉。
    # 線刻意比原本細（上次加粗後蓋掉了底圖的細微變化），只靠白邊維持可讀性。
    ax.plot(lon, lat, color="white", linewidth=3.6,
            solid_capstyle="round", solid_joinstyle="round", transform=proj, zorder=6)

    has_wind = "wind_kt" in track.columns and track.wind_kt.notna().any()
    if has_wind:
        cats = [ss_category(k) for k in track.wind_kt.to_numpy()]
        seg_colors = [CAT_COLOR_MAP[c] for c in cats[:-1]]  # 每段取起點的強度上色
        points = np.column_stack([lon, lat])
        segments = np.stack([points[:-1], points[1:]], axis=1)
        ax.add_collection(LineCollection(segments, colors=seg_colors, linewidths=1.8,
                                         capstyle="round", joinstyle="round",
                                         transform=proj, zorder=7))
        last_color = CAT_COLOR_MAP[cats[-1]]
    else:
        ax.plot(lon, lat, color="black", linewidth=1.2,
                solid_capstyle="round", transform=proj, zorder=7)
        last_color = "black"

    # 路徑最後一點加空心圈（顏色＝當下強度）；動畫裡這就是颱風當下的位置
    last = track.iloc[-1]
    for color, lw, size in (("white", 3.4, 19), (last_color, 1.6, 19)):
        ax.plot([last.lon], [last.lat], linestyle="none", marker="o", markersize=size,
                markerfacecolor="none", markeredgecolor=color, markeredgewidth=lw,
                transform=proj, zorder=9)

    if has_wind and legend:
        used = [c for c in CAT_ORDER if c in set(cats)]
        handles = [Line2D([0], [0], color=CAT_COLOR_MAP[c], lw=3.5, label=c) for c in used]
        leg = ax.legend(handles=handles, loc="upper right", ncols=1, fontsize=12,
                        title="Category (SS)", title_fontsize=13, framealpha=0.88,
                        edgecolor="none", handlelength=1.8, borderpad=0.7,
                        labelspacing=0.45, facecolor="white")
        leg.set_zorder(10)

    if "time" not in track.columns:
        return
    daily = track[track.time.dt.hour == 0]
    daily_colors = ([CAT_COLOR_MAP[ss_category(k)] for k in daily.wind_kt]
                    if has_wind else "black")
    ax.scatter(daily.lon, daily.lat, s=32, c=daily_colors, edgecolors="white",
              linewidths=1.3, transform=proj, zorder=8)


def render_map(field: xr.DataArray, title: str, subtitle: str, out_png: str,
               track=None, kind: str = "ohc", dpi: int = 400) -> None:
    """畫一張 NRL/CMEMS OHC 產品格式的圖：黑色陸地、白色海岸線、離散色階。"""
    proj = ccrs.PlateCarree()
    fig = plt.figure(figsize=(15, 9.6))
    ax = fig.add_axes([0.05, 0.05, 0.80, 0.835], projection=proj)
    ax.set_extent([BBOX["lon_min"], BBOX["lon_max"],
                   BBOX["lat_min"], BBOX["lat_max"]], crs=proj)
    ax.set_facecolor("black")

    if kind == "ohc":
        levels, colors = OHC_LEVELS, OHC_COLORS
        unit = "KJ/cm$^2$"
        under, over = "black", "#f5c2e0"
    else:
        vals = np.abs(field.values[np.isfinite(field.values)])
        p995 = np.percentile(vals, 99.5)
        # 挑一個讓刻度是整數的級距（色階 12 階，一邊 6 格）
        step = next((s for s in (1, 2, 5, 10, 20, 50, 100) if s * 6 >= p995), 100)
        half = step * 6
        levels = np.arange(-half, half + step, step, dtype=float)
        colors = DIFF_COLORS
        unit = "$\\Delta$KJ/cm$^2$"
        under, over = colors[0], colors[-1]

    cmap = ListedColormap(colors)
    cmap.set_under(under)
    cmap.set_over(over)
    # set_bad 一定要留透明：資料右邊界剛好到 180°E，cartopy 會走 pcolormesh
    # 的跨越換日線分支，bad 色不透明時整張圖會被吃掉變全黑。缺值靠底色是黑的來顯示。
    norm = BoundaryNorm(levels, cmap.N)

    m = ax.pcolormesh(field.longitude, field.latitude, field.values,
                      cmap=cmap, norm=norm, transform=proj,
                      shading="auto", zorder=1, rasterized=True)

    ax.add_feature(LAND_10M, facecolor="black", zorder=3)
    ax.add_feature(COASTLINE_10M, edgecolor="white", linewidth=0.6, zorder=4)
    draw_track(ax, track)

    # 只留左側與下方座標標籤，不畫格線（與參考產品一致）
    gl = ax.gridlines(draw_labels=True, linewidth=0)
    gl.top_labels = gl.right_labels = False
    gl.xlabel_style = gl.ylabel_style = {"size": 10, "color": "black"}

    fig.text(0.05, 0.952, title, fontsize=22, ha="left", va="center")
    fig.text(0.05, 0.905, subtitle, fontsize=17, ha="left", va="center", color="#333333")

    cax = fig.add_axes([0.875, 0.05, 0.022, 0.835])
    cb = fig.colorbar(m, cax=cax, extend="both", extendfrac=0.02,
                      ticks=levels, spacing="uniform")
    cb.ax.set_title(unit, fontsize=10, pad=8)
    cb.ax.tick_params(labelsize=9)
    cb.outline.set_linewidth(0.6)

    # Windows 上直接覆寫既有 PNG 偶爾會 OSError(22)（防毒掃描時的檔案鎖），先刪再寫
    if os.path.exists(out_png):
        os.remove(out_png)
    fig.savefig(out_png, dpi=dpi, facecolor="white")
    plt.close(fig)
    print(f"[PLOT] 已輸出: {out_png}")


def date_range(start: str, end: str) -> list[str]:
    """回傳 start 到 end（含頭含尾）的每日日期字串。"""
    d0 = dt.date.fromisoformat(start)
    d1 = dt.date.fromisoformat(end)
    if d1 < d0:
        d0, d1 = d1, d0
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def _build_shared_palette(imgs):
    """建一份所有畫格共用的調色盤：離散色（OHC 色階＋颱風分級色）用色塊
    強制保留，再疊上各畫格縮圖取樣背景漸層，合起來一起量化成 256 色。"""
    from PIL import Image

    swatch_hexes = list(dict.fromkeys(OHC_COLORS + list(CAT_COLOR_MAP.values())
                                      + ["#000000", "#ffffff"]))
    sw = 30
    cols = 16
    rows = (len(swatch_hexes) + cols - 1) // cols
    swatches = Image.new("RGB", (sw * cols, sw * rows), "white")
    for i, hexcolor in enumerate(swatch_hexes):
        block = Image.new("RGB", (sw, sw), hexcolor)
        swatches.paste(block, ((i % cols) * sw, (i // cols) * sw))

    # 縮小取樣以控制合併畫布的大小；用最近鄰避免縮圖把細線的顏色模糊掉
    thumbs = [im.resize((im.width // 3, im.height // 3), Image.Resampling.NEAREST)
             for im in imgs]
    canvas_w = max(swatches.width, thumbs[0].width)
    canvas_h = swatches.height + sum(t.height for t in thumbs)
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    canvas.paste(swatches, (0, 0))
    y = swatches.height
    for t in thumbs:
        canvas.paste(t, (0, y))
        y += t.height

    return canvas.quantize(colors=256, method=Image.Quantize.MEDIANCUT)


def make_gif(dates: list[str], out_dir: str, track, name: str,
             dpi: int, duration: int, allow_download: bool) -> None:
    """每天畫一張，串成動畫。路徑只畫到當天，最後一點就是颱風當下的位置。"""
    from PIL import Image

    frame_dir = os.path.join(out_dir, "frames")
    os.makedirs(frame_dir, exist_ok=True)

    frames = []
    for i, d in enumerate(dates, 1):
        path = os.path.join(out_dir, f"thetao_{d}.nc")
        if not os.path.exists(path):
            if not allow_download:
                print(f"[GIF] 缺 {d} 的資料且指定不下載，略過這一格")
                continue
            path = download_day(d, out_dir)

        sub = None
        if track is not None and "time" in track.columns:
            # 只畫到當天 00Z，跟畫面上的每日圓點對齊。巴威移動快，若畫到
            # 23:59，當天最後一筆（21Z）常常已經逼近隔天 00Z 的位置
            # （例如 07/05 21Z 在 145.6E，07/06 00Z 只有 145.0E，差 0.6 度），
            # 圈會看起來疊到隔天，像是路徑多畫了一天。
            sub = track[track.time <= f"{d} 00:00:00"]
            sub = sub if len(sub) else None

        png = os.path.join(frame_dir, f"frame_{d}.png")
        print(f"[GIF] ({i}/{len(dates)}) {d}")
        render_map(calc_ohc(path), "CMEMS Ocean Heat Content (OHC) Product",
                   f"{d.replace('-', '/')}   {name}", png, track=sub, dpi=dpi)
        frames.append(png)

    if len(frames) < 2:
        print("[GIF] 可用的畫格少於 2 張，不產生動畫")
        return

    imgs = [Image.open(f).convert("RGB") for f in frames]
    # 統一用同一份調色盤，避免每格重新量化造成顏色跳動。
    # 只從第一格取樣會漏色：巴威第一天還是熱帶性低氣壓，路徑只有灰／藍，
    # 調色盤裡根本沒有紫色，後面幾格的 Cat5 紫就會被硬套成最接近的灰色。
    # 做法：把地圖與路徑用到的離散色畫成色塊（大面積、高頻率，量化時一定保留），
    # 再疊上所有畫格的縮圖取樣背景漸層與反鋸齒色，兩者合併後才建調色盤。
    base = _build_shared_palette(imgs)
    quantized = [im.quantize(palette=base, dither=Image.Dither.NONE) for im in imgs]
    durations = [duration] * len(quantized)
    durations[-1] = max(duration * 3, 1800)   # 最後一格停久一點

    out_gif = os.path.join(out_dir, "ohc_animation.gif")
    if os.path.exists(out_gif):
        os.remove(out_gif)
    quantized[0].save(out_gif, save_all=True, append_images=quantized[1:],
                      duration=durations, loop=0, optimize=True)
    for im in imgs:
        im.close()
    size_mb = os.path.getsize(out_gif) / 1e6
    print(f"[GIF] 已輸出: {out_gif}（{len(frames)} 格，{size_mb:.1f} MB）")


def report_stats(f1: xr.DataArray, f2: xr.DataArray, diff: xr.DataArray,
                 day1: str, day2: str, track=None) -> None:
    a = f1.values[np.isfinite(f1.values)]
    b = f2.values[np.isfinite(f2.values)]
    d = diff.values[np.isfinite(diff.values)]
    print("\n===== 全域統計（kJ/cm²）=====")
    print(f"{day1}   平均 {a.mean():6.1f}   最大 {a.max():6.1f}")
    print(f"{day2}   平均 {b.mean():6.1f}   最大 {b.max():6.1f}")
    print(f"差值         平均 {d.mean():+6.1f}   最強降幅 {d.min():+6.1f}")
    print(f"降幅 > 10 kJ/cm² 的海域面積佔比：{(d < -10).mean() * 100:5.1f}%")

    if track is None:
        return
    # 只看路徑兩側 2 度內的格點，把跟颱風無關的渦旋訊號排掉
    lon2d, lat2d = np.meshgrid(diff.longitude.values, diff.latitude.values)
    near = np.zeros(lon2d.shape, dtype=bool)
    for lo, la in zip(track.lon.values, track.lat.values):
        near |= ((lon2d - lo) * np.cos(np.deg2rad(la))) ** 2 + (lat2d - la) ** 2 < 2.0 ** 2
    sel = diff.values[near & np.isfinite(diff.values)]
    if sel.size:
        print("\n----- 沿颱風路徑 2 度內 -----")
        print(f"平均變化 {sel.mean():+6.1f}   最強降幅 {sel.min():+6.1f}   "
              f"降幅 > 10 的佔比 {(sel < -10).mean() * 100:5.1f}%")


# ------------------------------------------------------------------ 主程式 --
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="颱風前後 OHC 比較圖（NRL 產品格式）")
    ap.add_argument("--day1", default="2026-07-01", help="颱風生成日 (YYYY-MM-DD)")
    ap.add_argument("--day2", default="2026-07-14", help="颱風消散日 (YYYY-MM-DD)")
    ap.add_argument("--name", default="Typhoon Bavi (09W, 2026)", help="圖上標註的颱風名稱")
    ap.add_argument("--bbox", nargs=4, type=float,
                    metavar=("LON_MIN", "LON_MAX", "LAT_MIN", "LAT_MAX"),
                    help="下載與繪圖範圍，預設 100 180 0 50")
    ap.add_argument("--track", default=DEFAULT_TRACK, help="颱風路徑 CSV（需含 lon,lat 欄）")
    ap.add_argument("--dataset", default=DATASET,
                    help=f"CMEMS dataset_id，2022 年以前請用 {DATASET_REANALYSIS}")
    ap.add_argument("--out-dir", default=OUT_DIR, help="nc 與圖檔輸出資料夾")
    ap.add_argument("--no-download", action="store_true", help="跳過下載，直接用現有 nc 檔")
    ap.add_argument("--dpi", type=int, default=400, help="靜態圖解析度，預設 400")
    ap.add_argument("--gif", action="store_true", help="另外輸出每日一張的動畫 GIF")
    ap.add_argument("--gif-start", help="GIF 起始日，預設同 --day1")
    ap.add_argument("--gif-end", help="GIF 結束日，預設同 --day2")
    ap.add_argument("--gif-dpi", type=int, default=220, help="GIF 每格解析度，預設 220")
    ap.add_argument("--gif-duration", type=int, default=700, help="GIF 每格毫秒數，預設 700")
    args = ap.parse_args(argv)

    globals()["DATASET"] = args.dataset
    if args.bbox:
        BBOX.update(lon_min=args.bbox[0], lon_max=args.bbox[1],
                    lat_min=args.bbox[2], lat_max=args.bbox[3])

    os.makedirs(args.out_dir, exist_ok=True)
    paths = {d: os.path.join(args.out_dir, f"thetao_{d}.nc") for d in (args.day1, args.day2)}

    if args.no_download:
        for p in paths.values():
            if not os.path.exists(p):
                print(f"[ERROR] --no-download 但找不到 {p}", file=sys.stderr)
                return 1
    else:
        if not check_credentials():
            return 2
        for d in (args.day1, args.day2):
            paths[d] = download_day(d, args.out_dir)

    print("[OHC] 計算中…")
    f1 = calc_ohc(paths[args.day1])
    f2 = calc_ohc(paths[args.day2])
    f1, f2 = xr.align(f1, f2, join="inner")
    diff = f2 - f1

    track = load_track(args.track)
    slash = lambda d: d.replace("-", "/")
    product = "CMEMS Ocean Heat Content (OHC) Product"

    # 生成日只畫到當天為止的路徑，跟 GIF 第一格一樣只有一個定位點；
    # 不能只取當天 00Z（有些颱風生成時間不是 00Z，例如卡努是 06Z，
    # 那樣切會整段是空的），改成含當天全部時刻。
    genesis_track = None
    if track is not None and "time" in track.columns:
        genesis_track = track[track.time <= f"{args.day1} 23:59:59"]
        genesis_track = genesis_track if len(genesis_track) else None

    render_map(f1, product, f"{slash(args.day1)}   {args.name} 生成日",
               os.path.join(args.out_dir, f"ohc_{args.day1}.png"),
               track=genesis_track, dpi=args.dpi)
    render_map(f2, product, f"{slash(args.day2)}   {args.name} 消散日",
               os.path.join(args.out_dir, f"ohc_{args.day2}.png"),
               track=track, dpi=args.dpi)
    render_map(diff, "CMEMS Ocean Heat Content (OHC) Difference",
               f"{slash(args.day2)} - {slash(args.day1)}   {args.name}",
               os.path.join(args.out_dir, f"ohc_diff_{args.day1}_{args.day2}.png"),
               track=track, kind="diff", dpi=args.dpi)

    report_stats(f1, f2, diff, args.day1, args.day2, track)

    if args.gif:
        dates = date_range(args.gif_start or args.day1, args.gif_end or args.day2)
        print("")
        print(f"[GIF] 共 {len(dates)} 天：{dates[0]} ~ {dates[-1]}")
        make_gif(dates, args.out_dir, track, args.name,
                 args.gif_dpi, args.gif_duration, not args.no_download)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
