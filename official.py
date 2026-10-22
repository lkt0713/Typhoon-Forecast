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
import ssl
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter

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
            issue, shift = _jma_base((title.get("issue") or {}).get("UTC"), [q['h'] for q in pts])
            for q in pts:
                if q['h'] > 0:
                    q['h'] += shift
            out.append({'agency': 'JMA', 'id': tcid, 'number': tc.get("typhoonNumber"), 'name': name,
                        'issue': issue, 'points': sorted(pts, key=lambda q: q['h'])})
    return out


def _jma_base(issue_utc, hours: list[int]):
    """颱風接近日本時 JMA 每小時發一次「推定」更新（例如 13Z），但預報點還是 12Z 那一報的，
    時數卻從 13Z 起算（+11、+23…），跟其他單位的 +12／+24 對不上。

    JMA 24 小時以後的預報點從預報基準時間算都是 12 小時的整數倍，所以用它們推回基準時間
    （13Z 發的 +47 → 差 1 小時 → 12Z）；沒有長期預報點時退回最近的 3 小時整點。
    h=0 仍是最新推定位置，當作「現在」。回傳 (基準時間 ISO, 預報時數要補的小時數)。"""
    if not issue_utc:
        return issue_utc, 0
    try:
        t = datetime.fromisoformat(str(issue_utc).replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        return issue_utc, 0
    t = t.replace(minute=0, second=0, microsecond=0)
    longs = [h for h in hours if h >= 24]
    shift = (-max(longs)) % 12 if longs else t.hour % 3
    return (t - timedelta(hours=shift)).strftime('%Y-%m-%dT%H:%MZ'), shift


class _LenientX509Adapter(HTTPAdapter):
    """照常驗證憑證，只關掉 Python 3.13 起預設開啟的 X509 嚴格檢查（VERIFY_X509_STRICT）。

    氣象署的憑證鏈缺 Subject Key Identifier 擴充欄位，嚴格模式會以
    「Missing Subject Key Identifier」拒絕連線；憑證本身與網域驗證不受影響。"""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~getattr(ssl, 'VERIFY_X509_STRICT', 0)
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)


def fetch_cwa() -> list[dict]:
    """CWA 熱帶氣旋路徑。沒有授權碼回空清單。"""
    key = os.environ.get("CWA_API_KEY", "").strip()
    if not key:
        return []
    with requests.Session() as s:
        s.mount("https://opendata.cwa.gov.tw/", _LenientX509Adapter())
        r = s.get(CWA_URL, params={"Authorization": key, "format": "JSON"}, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    out = parse_cwa(data)
    if not out:
        # 解析不出來時印出結構（只有欄位名稱，沒有授權碼），之後才知道要怎麼對欄位
        print(f"[OFFICIAL] CWA 沒解析出颱風，JSON 結構: {_shape(data)}")
    return out


def _shape(x, depth=0):
    """JSON 的欄位骨架（dict 的鍵、list 的第一個元素），給除錯用。"""
    if depth > 9:
        return '…'
    if isinstance(x, dict):
        return {k: _shape(v, depth + 1) for k, v in list(x.items())[:20]}
    if isinstance(x, list):
        return [_shape(x[0], depth + 1), f'×{len(x)}'] if x else []
    return type(x).__name__


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
