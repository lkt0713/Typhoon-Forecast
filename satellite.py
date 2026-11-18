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
疊海岸線與路徑。觀測結束後檔案要幾分鐘才會全部上傳，所以只算「用得到的段都到齊」的時次；
recent_slots() 列出最近 n 個這樣的時次給動畫用，fetch() 取其中一個時次的影像。
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
LOOKBACK_SLOTS = 6                       # 缺段的時次最多多往前找 6 個（1 小時）
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
_keys_cache: dict = {}                    # 時次 → {段號: key}（已到齊的時次內容不會再變）
_seg_cache: dict = {}                     # (時次, 段號) → 解好的段；只留目前這個時次，免得動畫 18 個時次全塞在記憶體


def _list(prefix: str) -> list[str]:
    """列出 bucket 裡 prefix 底下的檔名。"""
    r = _session.get(BUCKET_URL, params={'list-type': 2, 'prefix': prefix, 'delimiter': '/'},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return re.findall(r'<Key>([^<]+)</Key>', r.text)


def _slot_keys(slot: datetime) -> dict[int, str]:
    """這個時次已上傳的 B13 各段：{段號: key}。"""
    if slot in _keys_cache:
        return _keys_cache[slot]
    out = {}
    for k in _list(f"{PRODUCT}/{slot:%Y/%m/%d/%H%M}/"):
        m = re.search(rf'_B{BAND:02d}_FLDK_R\d+_S(\d\d){N_SEG:02d}\.DAT\.bz2$', k)
        if m:
            out[int(m.group(1))] = k
    if len(out) == N_SEG:
        _keys_cache[slot] = out
    return out


def _read_hsd(raw: bytes) -> dict:
    """解一段 HSD 檔：原始計數值、定標係數與投影參數。"""
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
    return {'counts': np.frombuffer(raw, '<u2', ncol * nline, hdr_len).reshape(nline, ncol),
            'cal': b5, 'first_line': int(b7['first_line']),
            'proj': tuple(float(b3[k]) for k in ('sub_lon', 'cfac', 'lfac', 'coff', 'loff'))}


def _calibrate(counts: np.ndarray, b5) -> np.ndarray:
    """計數值 → 亮度溫度（K），無效值 NaN。"""
    bad = (counts == b5['err_count']) | (counts == b5['outside_count'])
    rad = counts * b5['gain'] + b5['const']                   # W/(m²·sr·µm)
    lam = b5['cwl'] * 1e-6
    with np.errstate(invalid='ignore', divide='ignore'):
        te = (b5['h'] * b5['c'] / (b5['k'] * lam)) / np.log(
            2 * b5['h'] * b5['c'] ** 2 / (rad * 1e6 * lam ** 5) + 1)
        tb = b5['c0'] + b5['c1'] * te + b5['c2'] * te ** 2
    return np.where(bad | ~np.isfinite(tb) | (rad <= 0), np.nan, tb).astype(np.float32)


def _segment(slot: datetime, seg: int, key: str) -> dict:
    ck = (slot, seg)
    if ck not in _seg_cache:
        for old in [k for k in _seg_cache if k[0] != slot]:
            del _seg_cache[old]
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


class _Box:
    """以 (lat, lon) 為中心、間距 step 度的經緯度等距網格，北在上；經度不折回 180。"""

    def __init__(self, lat, lon, half_lon, half_lat, step):
        self.lon0, self.lat0 = lon - half_lon, lat - half_lat
        nx, ny = int(round(2 * half_lon / step)), int(round(2 * half_lat / step))
        lons = self.lon0 + (np.arange(nx) + 0.5) * step
        lats = self.lat0 + (ny - np.arange(ny) - 0.5) * step
        self.glat, self.glon = np.meshgrid(lats, lons, indexing='ij')
        self.extent = (self.lon0, self.lon0 + nx * step, self.lat0, self.lat0 + ny * step)

    def linecol(self, proj):
        line, col = _lonlat_to_linecol(self.glat, self.glon, *proj)
        if not np.isfinite(line).any():
            raise RuntimeError(f"{self.extent} 不在向日葵的視野內")
        return line, col

    def segments(self, proj=DEFAULT_PROJ) -> range:
        """這個範圍用得到的段號。"""
        line, _ = self.linecol(proj)
        lo, hi = int((np.nanmin(line) - 1) // SEG_LINES) + 1, int((np.nanmax(line) - 1) // SEG_LINES) + 1
        return range(max(lo, 1), min(hi, N_SEG) + 1)


def recent_slots(lat: float, lon: float, n: int, half_lon: float = 12.0, half_lat: float = 9.0,
                 step: float = 0.02, now: datetime | None = None) -> list[datetime]:
    """最近 n 個「這個範圍用得到的段都已上傳」的時次（UTC，由舊到新）。

    最新的一兩個時次常常還沒傳完，所以往前多找 LOOKBACK_SLOTS 個；中間偶爾缺的時次直接略過。"""
    need = _Box(lat, lon, half_lon, half_lat, step).segments()
    now = now or datetime.now(timezone.utc)
    t = now.replace(minute=now.minute // 10 * 10, second=0, microsecond=0)
    out = []
    for i in range(n + LOOKBACK_SLOTS):
        slot = t - timedelta(minutes=10 * i)
        keys = _slot_keys(slot)
        if all(s in keys for s in need):
            out.append(slot)
            if len(out) == n:
                break
    return out[::-1]


def fetch(lat: float, lon: float, half_lon: float = 12.0, half_lat: float = 9.0,
          step: float = 0.02, slot: datetime | None = None) -> tuple[np.ndarray, tuple, datetime]:
    """以 (lat, lon) 為中心取一個時次（預設最新）的 B13 亮度溫度。

    回傳 (tb, extent, valid)：tb 是 (ny, nx) 的 K 值、北在上的經緯度等距網格（看不到或缺資料為 NaN）；
    extent = (lon0, lon1, lat0, lat1) 是影像外框，經度不折回 180；valid 是觀測開始時間（UTC）。
    """
    if slot is None:
        slots = recent_slots(lat, lon, 1, half_lon, half_lat, step)
        if not slots:
            raise RuntimeError(f"{PRODUCT} 最近 {LOOKBACK_SLOTS + 1} 個時次都沒有完整的 B{BAND:02d} 資料")
        slot = slots[0]
    box = _Box(lat, lon, half_lon, half_lat, step)
    keys = _slot_keys(slot)
    # 先用預設投影算要哪幾段；讀到的標頭跟預設不同（例如換衛星）就照標頭重算一次
    proj = DEFAULT_PROJ
    for _ in range(2):
        need = box.segments(proj)
        missing = [s for s in need if s not in keys]
        if missing:
            raise RuntimeError(f"{slot:%Y-%m-%d %H:%M} 缺第 {missing} 段")
        segs = [_segment(slot, s, keys[s]) for s in need]
        if segs[0]['proj'] == proj:
            break
        proj = segs[0]['proj']
    line, col = box.linecol(proj)
    tb = np.full(box.glat.shape, np.nan, dtype=np.float32)
    ok = np.isfinite(line) & np.isfinite(col)
    li = np.where(ok, np.round(line), 0).astype(int) - 1
    ci = np.where(ok, np.round(col), 0).astype(int) - 1
    for d in segs:
        r = li - (d['first_line'] - 1)
        m = ok & (r >= 0) & (r < d['counts'].shape[0]) & (ci >= 0) & (ci < d['counts'].shape[1])
        tb[m] = _calibrate(d['counts'][r[m], ci[m]], d['cal'])
    return tb, box.extent, slot
