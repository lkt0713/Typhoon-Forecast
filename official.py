"""各國官方颱風預報：日本氣象廳（JMA）與中央氣象署（CWA），與 JTWC 並列比較。

JMA：氣象廳防災資訊網站的 JSON（www.jma.go.jp/bosai/typhoon/data/），不需金鑰。
    targetTc.json 列出目前發布中的熱帶氣旋，每個再讀 specifications.json：
    各時刻的中心位置、最大風速（10 分鐘平均）、氣壓與 70% 機率圓半徑。
CWA：氣象資料開放平臺 W-C0034-005（熱帶氣旋路徑），需要授權碼，放在環境變數
    CWA_API_KEY（GitHub Actions secret）；沒有就略過。

回傳格式一律是 {'agency', 'name', 'issue'(UTC ISO), 'points': [{'h', 'lat', 'lon', 'kt', 'hpa', 'r70_km'}]}，
h 為預報時數（0 = 實況），缺的欄位給 None。
"""
from __future__ import annotations

import os
import re

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TyphoonForecastSite/1.0)"}
JMA_BASE = "https://www.jma.go.jp/bosai/typhoon/data"
CWA_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005"
TIMEOUT = 30


def _num(x):
    try:
        return None if x in (None, '', '-') else float(x)
    except (TypeError, ValueError):
        return None


def fetch_jma() -> list[dict]:
    r = requests.get(f"{JMA_BASE}/targetTc.json", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for tc in r.json() or []:
        tcid = tc.get("tropicalCyclone") if isinstance(tc, dict) else None
        if not tcid or not re.match(r"^TC\d+$", tcid):
            continue
        try:
            spec = requests.get(f"{JMA_BASE}/{tcid}/specifications.json", headers=HEADERS, timeout=TIMEOUT)
            spec.raise_for_status()
            parts = spec.json()
        except Exception as e:
            print(f"[OFFICIAL] JMA {tcid} 讀取失敗: {e}")
            continue
        title = next((p for p in parts if p.get("part") == "title"), {})
        name = ((title.get("name") or {}).get("en") or "").strip() or None
        pts = []
        for p in parts:
            pos = (p.get("position") or {}).get("deg")
            if not pos or p.get("advancedHours") is None:
                continue
            wind = ((p.get("maximumWind") or {}).get("sustained") or {}).get("kt")
            pts.append({'h': int(p["advancedHours"]), 'lat': float(pos[0]), 'lon': float(pos[1]),
                        'kt': _num(wind), 'hpa': _num(p.get("pressure")),
                        'r70_km': _num((p.get("probabilityCircleRadius") or {}).get("km"))})
        if pts:
            out.append({'agency': 'JMA', 'id': tcid, 'number': tc.get("typhoonNumber"), 'name': name,
                        'issue': (title.get("issue") or {}).get("UTC"),
                        'points': sorted(pts, key=lambda q: q['h'])})
    return out


def fetch_cwa() -> list[dict]:
    """CWA 熱帶氣旋路徑。沒有授權碼回空清單；資料結構確定前只回傳原始 JSON 的解析結果。"""
    key = os.environ.get("CWA_API_KEY", "").strip()
    if not key:
        return []
    r = requests.get(CWA_URL, params={"Authorization": key, "format": "JSON"}, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return parse_cwa(r.json())


def parse_cwa(data: dict) -> list[dict]:
    """W-C0034-005 JSON → 統一格式。欄位依產品說明文件（fix_time／coordinate／max_wind_speed ...），
    結構對不上時回空清單，不讓整個流程失敗。"""
    out = []
    try:
        cyclones = (((data.get("records") or {}).get("tropicalCyclones") or {}).get("tropicalCyclone") or [])
    except AttributeError:
        return out
    for c in cyclones if isinstance(cyclones, list) else [cyclones]:
        name = c.get("typhoonName") or c.get("cwaTyphoonName") or c.get("cwaTdNo")
        pts = []
        an = ((c.get("analysisData") or {}).get("fix") or [])
        an = an if isinstance(an, list) else [an]
        last = an[-1] if an else None
        issue = None
        if last:
            la, lo = _coord(last.get("coordinate"))
            if la is not None:
                pts.append({'h': 0, 'lat': la, 'lon': lo, 'kt': _ms_to_kt(last.get("maxWindSpeed")),
                            'hpa': _num(last.get("pressure")), 'r70_km': None})
                issue = last.get("fixTime")
        fc = ((c.get("forecastData") or {}).get("fix") or [])
        for f in fc if isinstance(fc, list) else [fc]:
            la, lo = _coord(f.get("coordinate"))
            tau = _num(f.get("tau"))
            if la is None or tau is None:
                continue
            pts.append({'h': int(tau), 'lat': la, 'lon': lo, 'kt': _ms_to_kt(f.get("maxWindSpeed")),
                        'hpa': _num(f.get("pressure")),
                        'r70_km': _num(f.get("radiusOf70PercentProbability"))})
        if pts:
            out.append({'agency': 'CWA', 'name': name, 'issue': issue, 'points': sorted(pts, key=lambda q: q['h'])})
    return out


def _coord(txt):
    """'125.4,20.8'（經度,緯度）→ (lat, lon)。"""
    try:
        lo, la = (float(x) for x in str(txt).split(","))
        return la, lo
    except (TypeError, ValueError):
        return None, None


def _ms_to_kt(x):
    v = _num(x)
    return None if v is None else round(v * 1.94384)
