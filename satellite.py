"""目前的衛星雲圖：向日葵 9 號（Himawari-9）B13 紅外線亮度溫度，以颱風為中心裁切。

來源是 NOAA 放在 AWS 上的向日葵原始資料（NOAA Open Data Dissemination，s3://noaa-himawari9，
不需帳號），與日本氣象廳、氣象署用的是同一顆衛星：
    AHI-L1b-FLDK/YYYY/MM/DD/HHMM/HS_H09_YYYYMMDD_HHMM_B13_FLDK_R20_S{nn}10.DAT.bz2
全圓盤每 10 分鐘一張，B13（10.4 µm）解析度 2 km、5500×5500，切成 10 段（segment）南北排列，
每段約 4–11 MB。只下載颱風附近用得到的那一兩段。

檔案是 JMA 的 Himawari Standard Data（HSD）格式：一串標頭區塊，接著 uint16 的原始計數值。
這裡只讀用得到的區塊（區塊 2 影像大小、3 投影、5 定標、7 分段資訊），定標公式與
satpy 的 ahi_hsd 讀取器相同：計數 → 輻射 → 普朗克反函數得等效黑體溫度 → 二次式修正成亮度溫度。
經緯度 → 行列號用 CGMS 靜止衛星投影公式（JMA HSD 使用手冊附錄）。

結果重新取樣成經緯度等距網格（PlateCarree），forecast.py 才能用跟其他圖一樣的 Cartopy 底圖
疊海岸線與路徑。觀測結束後檔案要幾分鐘才會全部上傳，所以最新時次缺段時往前一個時次找。
"""
from __future__ import annotations

import bz2
import re
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

BUCKET_URL = "https://noaa-himawari9.s3.amazonaws.com"
PRODUCT = "AHI-L1b-FLDK"
BAND = 13
N_SEG = 10
TIMEOUT = 60
LOOKBACK_SLOTS = 6                       # 最新時次缺段時最多往前找 6 個（1 小時）
H_SAT = 42164.0                          # 衛星到地心距離（km）
R_EQ, R_POL = 6378.1370, 6356.7523       # 地球赤道、極半徑（km）
# B13 全圓盤的投影參數（sub_lon、CFAC、LFAC、COFF、LOFF，即 HSD 區塊 3）與每段行數（5500／10）
DEFAULT_PROJ = (140.7, 20466275.0, 20466275.0, 2750.5, 2750.5)
SEG_LINES = 550

# HSD 標頭區塊（只列出用到的欄位；每個區塊開頭都是 區塊編號 uint8、區塊長度 uint16）
_B2 = np.dtype([('no', 'u1'), ('len', '<u2'), ('bits', '<u2'), ('ncol', '<u2'), ('nline', '<u2'),
                ('comp', 'u1')])
_B3 = np.dtype([('no', 'u1'), ('len', '<u2'), ('sub_lon', '<f8'), ('cfac', '<u4'), ('lfac', '<u4'),
                ('coff', '<f4'), ('loff', '<f4')])
_B5 = np.dtype([('no', 'u1'), ('len', '<u2'), ('band', '<u2'), ('cwl', '<f8'), ('valid_bits', '<u2'),
                ('err_count', '<u2'), ('outside_count', '<u2'), ('gain', '<f8'), ('const', '<f8'),
                ('c0', '<f8'), ('c1', '<f8'), ('c2', '<f8'), ('C0', '<f8'), ('C1', '<f8'), ('C2', '<f8'),
                ('c', '<f8'), ('h', '<f8'), ('k', '<f8')])
_B7 = np.dtype([('no', 'u1'), ('len', '<u2'), ('n_seg', 'u1'), ('seg', 'u1'), ('first_line', '<u2')])

_session = requests.Session()
_seg_cache: dict = {}                     # (時次, 段號) → 解好的段，同一輪多顆颱風共用


def _list(prefix: str) -> tuple[list[str], list[str]]:
    """列出 bucket 裡 prefix 底下的 (子目錄, 檔名)。"""
    r = _session.get(BUCKET_URL, params={'list-type': 2, 'prefix': prefix, 'delimiter': '/'},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return re.findall(r'<Prefix>([^<]+/)</Prefix>', r.text), re.findall(r'<Key>([^<]+)</Key>', r.text)


def _slot_keys(slot: datetime) -> dict[int, str]:
    """這個時次已上傳的 B13 各段：{段號: key}。"""
    _, keys = _list(f"{PRODUCT}/{slot:%Y/%m/%d/%H%M}/")
    out = {}
    for k in keys:
        m = re.search(rf'_B{BAND:02d}_FLDK_R\d+_S(\d\d){N_SEG:02d}\.DAT\.bz2$', k)
        if m:
            out[int(m.group(1))] = k
    return out


def _latest_slots(now: datetime | None = None):
    """由新到舊列出可能有資料的時次（每 10 分鐘一個）。"""
    now = now or datetime.now(timezone.utc)
    t = now.replace(minute=now.minute // 10 * 10, second=0, microsecond=0)
    for i in range(LOOKBACK_SLOTS + 1):
        yield t - timedelta(minutes=10 * i)


def _read_hsd(raw: bytes) -> dict:
    """解一段 HSD 檔：回傳亮度溫度（K，float32，無效值 NaN）與投影參數。"""
    n_blocks = int(np.frombuffer(raw, '<u2', 1, 3)[0])
    hdr_len = int(np.frombuffer(raw, '<u4', 1, 70)[0])
    blocks, off = {}, 0
    for _ in range(n_blocks):
        no, ln = raw[off], int(np.frombuffer(raw, '<u2', 1, off + 1)[0])
        blocks[no] = off
        off += ln
    b2 = np.frombuffer(raw, _B2, 1, blocks[2])[0]
    b3 = np.frombuffer(raw, _B3, 1, blocks[3])[0]
    b5 = np.frombuffer(raw, _B5, 1, blocks[5])[0]
    b7 = np.frombuffer(raw, _B7, 1, blocks[7])[0]
    ncol, nline = int(b2['ncol']), int(b2['nline'])
    counts = np.frombuffer(raw, '<u2', ncol * nline, hdr_len).reshape(nline, ncol)
    bad = (counts == b5['err_count']) | (counts == b5['outside_count'])
    rad = counts * b5['gain'] + b5['const']                   # W/(m²·sr·µm)
    lam = b5['cwl'] * 1e-6
    with np.errstate(invalid='ignore', divide='ignore'):
        te = (b5['h'] * b5['c'] / (b5['k'] * lam)) / np.log(
            2 * b5['h'] * b5['c'] ** 2 / (rad * 1e6 * lam ** 5) + 1)
        tb = b5['c0'] + b5['c1'] * te + b5['c2'] * te ** 2
    tb = np.where(bad | ~np.isfinite(tb) | (rad <= 0), np.nan, tb).astype(np.float32)
    return {'tb': tb, 'first_line': int(b7['first_line']),
            'proj': tuple(float(b3[k]) for k in ('sub_lon', 'cfac', 'lfac', 'coff', 'loff'))}


def _segment(slot: datetime, seg: int, key: str) -> dict:
    ck = (slot, seg)
    if ck not in _seg_cache:
        r = _session.get(f"{BUCKET_URL}/{key}", timeout=TIMEOUT)
        r.raise_for_status()
        _seg_cache[ck] = _read_hsd(bz2.decompress(r.content))
    return _seg_cache[ck]


def _lonlat_to_linecol(lat, lon, sub_lon, cfac, lfac, coff, loff):
    """經緯度（度）→ 全圓盤的 (行號, 列號)，從 1 起算；地球背面為 NaN。"""
    la, dl = np.radians(lat), np.radians(lon - sub_lon)
    c_lat = np.arctan((R_POL / R_EQ) ** 2 * np.tan(la))
    e2 = 1 - (R_POL / R_EQ) ** 2
    rl = R_POL / np.sqrt(1 - e2 * np.cos(c_lat) ** 2)
    r1 = H_SAT - rl * np.cos(c_lat) * np.cos(dl)
    r2 = -rl * np.cos(c_lat) * np.sin(dl)
    r3 = rl * np.sin(c_lat)
    rn = np.sqrt(r1 ** 2 + r2 ** 2 + r3 ** 2)
    x = np.degrees(np.arctan(-r2 / r1))
    y = np.degrees(np.arcsin(-r3 / rn))
    col = coff + x * 2.0 ** -16 * cfac
    line = loff + y * 2.0 ** -16 * lfac
    # 衛星看得到的條件：衛星到該點的向量與該點的地表法向量夾角小於 90°
    hidden = r1 * (H_SAT - r1) - r2 ** 2 - r3 ** 2 * (R_EQ / R_POL) ** 2 < 0
    return np.where(hidden, np.nan, line), np.where(hidden, np.nan, col)


def fetch(lat: float, lon: float, half_lon: float = 12.0, half_lat: float = 9.0,
          step: float = 0.02) -> tuple[np.ndarray, tuple, datetime]:
    """以 (lat, lon) 為中心取最新一張 B13 亮度溫度。

    回傳 (tb, extent, valid)：tb 是 (ny, nx) 的 K 值、北在上的經緯度等距網格（看不到或缺資料為 NaN）；
    extent = (lon0, lon1, lat0, lat1) 是影像外框，經度不折回 180；valid 是觀測開始時間（UTC）。
    """
    lon0, lat0 = lon - half_lon, lat - half_lat
    nx, ny = int(round(2 * half_lon / step)), int(round(2 * half_lat / step))
    lons = lon0 + (np.arange(nx) + 0.5) * step
    lats = lat0 + (ny - np.arange(ny) - 0.5) * step
    glat, glon = np.meshgrid(lats, lons, indexing='ij')

    for slot in _latest_slots():
        keys = _slot_keys(slot)
        if not keys:
            continue
        # 先用預設投影算要哪幾段；讀到的標頭跟預設不同（例如換衛星）就照標頭重算一次
        proj = DEFAULT_PROJ
        for _ in range(2):
            line, col = _lonlat_to_linecol(glat, glon, *proj)
            if not np.isfinite(line).any():
                raise RuntimeError(f"({lat}, {lon}) 不在向日葵的視野內")
            lo, hi = (int((np.nanmin(line) - 1) // SEG_LINES) + 1, int((np.nanmax(line) - 1) // SEG_LINES) + 1)
            need = range(max(lo, 1), min(hi, N_SEG) + 1)
            if any(s not in keys for s in need):
                break                              # 這個時次還沒傳完
            segs = [_segment(slot, s, keys[s]) for s in need]
            if segs[0]['proj'] == proj:
                break
            proj = segs[0]['proj']
        if any(s not in keys for s in need):
            continue
        tb = np.full(glat.shape, np.nan, dtype=np.float32)
        ok = np.isfinite(line) & np.isfinite(col)
        li = np.where(ok, np.round(line), 0).astype(int) - 1
        ci = np.where(ok, np.round(col), 0).astype(int) - 1
        for d in segs:
            r = li - (d['first_line'] - 1)
            m = ok & (r >= 0) & (r < d['tb'].shape[0]) & (ci >= 0) & (ci < d['tb'].shape[1])
            tb[m] = d['tb'][r[m], ci[m]]
        return tb, (lon0, lon0 + nx * step, lat0, lat0 + ny * step), slot
    raise RuntimeError(f"{PRODUCT} 最近 {LOOKBACK_SLOTS + 1} 個時次都沒有完整的 B{BAND:02d} 資料")
