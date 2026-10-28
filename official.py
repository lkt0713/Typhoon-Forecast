"""各國官方颱風預報：日本氣象廳（JMA）與中央氣象署（CWA），與 JTWC 並列比較。

JMA：氣象廳防災資訊網站的 JSON（www.jma.go.jp/bosai/typhoon/data/），不需金鑰。
    targetTc.json 列出目前發布中的熱帶氣旋，每個再讀 specifications.json：
    各時刻的中心位置、最大風速（10 分鐘平均）、氣壓與 70% 機率圓半徑。
    JMA 發報很頻繁（接近日本時每小時），網站只每 6 小時換一次，見 _six_hourly。
CWA：氣象資料開放平臺 W-C0034-005（熱帶氣旋路徑），需要授權碼，放在環境變數
    CWA_API_KEY（GitHub Actions secret）；沒有就略過。回傳偶爾少一顆颱風，見 _keep_recent_cwa。

回傳格式一律是 {'agency', 'name', 'issue'(UTC ISO), 'points': [{'h', 'lat', 'lon', 'kt', 'hpa', 'r70_km'}]}，
h 為預報時數（0 = 實況），缺的欄位給 None。
"""
from __future__ import annotations

import json
import os
import re
import ssl
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TyphoonForecastSite/1.0)"}
JMA_BASE = "https://www.jma.go.jp/bosai/typhoon/data"
CWA_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005"
# 目前採用的 JMA 那一報，跨輪保存才能「每 6 小時換一次」（docs/ 每輪會 commit，Actions 上也留得住）
JMA_STATE = os.path.join("docs", "jma_bulletins.json")
# CWA 的開放資料偶爾整顆颱風不見（2026-10-24 In-Fa：01:16Z 有 00Z 那報，01:25Z、01:38Z 的回傳都沒有），
# 所以存下每顆最近一報，回傳裡少了某顆但那報還不到 CWA_KEEP_H 小時就沿用
CWA_STATE = os.path.join("docs", "cwa_bulletins.json")
CWA_KEEP_H = 12
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
            # JMA 對轉為溫帶氣旋或消散的時刻把最大風速寫成 0，當成沒有資料，網頁顯示「—」而不是「0 kt」
            pts.append({'h': int(p["advancedHours"]), 'lat': float(pos[0]), 'lon': float(pos[1]),
                        'kt': _num(wind) or None, 'hpa': _num(p.get("pressure")),
                        'r70_km': _num((p.get("probabilityCircleRadius") or {}).get("km"))})
        if pts:
            issue, shift = _jma_base((title.get("issue") or {}).get("UTC"), [q['h'] for q in pts])
            for q in pts:
                if q['h'] > 0:
                    q['h'] += shift
            out.append({'agency': 'JMA', 'id': tcid, 'number': tc.get("typhoonNumber"), 'name': name,
                        'issue': issue, 'points': sorted(pts, key=lambda q: q['h'])})
    return _six_hourly(out)


def _floor6(iso):
    """基準時間 ISO → 所屬的 6 小時時段（00/06/12/18Z）；格式不符回 None。"""
    try:
        t = datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
    except ValueError:
        return None
    return t.replace(hour=t.hour - t.hour % 6, minute=0, second=0, microsecond=0)


def _six_hourly(out: list[dict]) -> list[dict]:
    """JMA 接近日本時每小時、平常每 3 小時就發一報，網站只要每 6 小時換一次。

    每顆颱風（JMA 的 TC 編號）沿用 JMA_STATE 裡上次採用的那報，等基準時間進到新的
    00/06/12/18Z 時段才換成新的；沒存過的颱風直接用最新一報。只保留目前還在發報的颱風。"""
    try:
        with open(JMA_STATE, encoding='utf-8') as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    res = []
    for f in out:
        old = state.get(f['id'])
        new_t, old_t = _floor6(f['issue']), _floor6(old['issue']) if old else None
        if old and new_t and old_t and new_t <= old_t:
            res.append(old)
        else:
            res.append(f)
    try:
        with open(JMA_STATE, 'w', encoding='utf-8') as fh:
            json.dump({f['id']: f for f in res}, fh, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"[OFFICIAL] JMA 狀態檔寫入失敗（下一輪改用最新一報）: {e}")
    return res


def _jma_base(issue_utc, hours: list[int]):
    """JMA 的 issue 時間不一定是預報基準時間，時數的起算點也有兩種：

    - 颱風接近日本時每小時發一次「推定」更新（例如 13Z），預報點還是 12Z 那一報的，時數卻從
      13Z 起算（+11、+23、+47…）。24 小時以後的預報點從基準時間算都是 12 小時的整數倍，
      所以用最長的那點推回基準時間（+47 → 差 1 小時 → 12Z），時數也補回去。
    - 遠洋的颱風照常每 3／6 小時發報，issue 是發布時間（18Z 那報在 19Z 發），時數已經從
      基準時間起算（+48、+72…都是 12 的倍數）。這時基準時間是 issue 往前取 3 小時整點，時數不動。
      2026-10 In-Fa 就是這種，原本被當成 19Z 起算，預報點全部晚了 1 小時。

    沒有 24 小時以後的預報點時無從分辨，退回最近的 3 小時整點、時數照第一種補。
    h=0 仍是最新推定位置，當作「現在」。回傳 (基準時間 ISO, 預報時數要補的小時數)。"""
    if not issue_utc:
        return issue_utc, 0
    try:
        t = datetime.fromisoformat(str(issue_utc).replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        return issue_utc, 0
    t = t.replace(minute=0, second=0, microsecond=0)
    longs = [h for h in hours if h >= 24]
    if longs and max(longs) % 12 == 0:
        return (t - timedelta(hours=t.hour % 3)).strftime('%Y-%m-%dT%H:%MZ'), 0
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
    print("[OFFICIAL] CWA 回傳：" + ("、".join(
        f"{f['name']} {f['issue'] or '?'} {f['points'][0]['lat']:.1f}°N {f['points'][0]['lon'] % 360:.1f}°E"
        f"（{len(f['points'])} 點）" for f in out) or "無"))
    return _keep_recent_cwa(out)


def _keep_recent_cwa(out: list[dict]) -> list[dict]:
    """回傳裡沒有、但存檔裡那報還不到 CWA_KEEP_H 小時的颱風，沿用存檔那報；存檔只留這次用到的。"""
    try:
        with open(CWA_STATE, encoding='utf-8') as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    names = {str(f['name']).upper() for f in out}
    now = datetime.now(timezone.utc)
    res = list(out)
    for key, f in state.items():
        if key in names:
            continue
        try:
            age = now - datetime.fromisoformat(str(f.get('issue')).replace('Z', '+00:00'))
        except ValueError:
            continue
        if age <= timedelta(hours=CWA_KEEP_H):
            print(f"[OFFICIAL] CWA 這次沒有 {f['name']}，沿用 {f['issue']} 那報")
            res.append(f)
    try:
        with open(CWA_STATE, 'w', encoding='utf-8') as fh:
            json.dump({str(f['name']).upper(): f for f in res}, fh, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"[OFFICIAL] CWA 狀態檔寫入失敗: {e}")
    return res


def _shape(x, depth=0):
    """JSON 的欄位骨架（dict 的鍵、list 的第一個元素），給除錯用。"""
    if depth > 9:
        return '…'
    if isinstance(x, dict):
        return {k: _shape(v, depth + 1) for k, v in list(x.items())[:20]}
    if isinstance(x, list):
        return [_shape(x[0], depth + 1), f'×{len(x)}'] if x else []
    return type(x).__name__


def _ci(d, key):
    """不分大小寫取 dict 欄位（CWA 的欄位名稱是 PascalCase，例如 TropicalCyclones）。"""
    if not isinstance(d, dict):
        return None
    if key in d:
        return d[key]
    lk = key.lower()
    return next((v for k, v in d.items() if k.lower() == lk), None)


def _as_list(x):
    return x if isinstance(x, list) else ([x] if x else [])


def _utc(txt):
    """CWA 的時間（帶 +08:00）→ datetime（UTC）；格式不符回 None。"""
    try:
        t = datetime.fromisoformat(str(txt).replace('Z', '+00:00'))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone(timedelta(hours=8)))
    return t.astimezone(timezone.utc)


def parse_cwa(data: dict) -> list[dict]:
    """W-C0034-005 JSON → 統一格式。結構（2026-10 實際回傳）：
    records.TropicalCyclones.TropicalCyclone[]：TyphoonName、CwaTyphoonName、
      AnalysisData.Fix[]：DateTime、CoordinateLatitude／Longitude、MaxWindSpeed（m/s）、Pressure
      ForecastData.Fix[]：InitialTime、ForecastHour、座標、MaxWindSpeed、Pressure、Radius70PercentProbability（km）
    「現在」用時間等於預報起始時間的那筆分析，沒有就用時間最新的分析；剛生成的颱風可能還沒有分析資料，
    這時改用預報時數 0 的那一點。都沒有就略過這顆並印出原因。結構對不上回空清單。"""
    out = []
    tcs = _ci(_ci(_ci(data, 'records'), 'TropicalCyclones'), 'TropicalCyclone')
    for c in _as_list(tcs):
        name = _ci(c, 'TyphoonName') or _ci(c, 'CwaTyphoonName') or _ci(c, 'CwaTdNo')
        an = _as_list(_ci(_ci(c, 'AnalysisData'), 'Fix'))
        fc = _as_list(_ci(_ci(c, 'ForecastData'), 'Fix'))
        init = _utc(_ci(fc[0], 'InitialTime')) if fc else None
        now = None
        if an:
            latest = max(an, key=lambda a: _utc(_ci(a, 'DateTime')) or datetime.min.replace(tzinfo=timezone.utc))
            now = next((a for a in an if init and _utc(_ci(a, 'DateTime')) == init), latest)
        else:
            now = next((f for f in fc if _num(_ci(f, 'ForecastHour')) == 0), None)
        base = init or (_utc(_ci(now, 'DateTime')) if now else None)
        pts = []
        if now:
            la, lo = _num(_ci(now, 'CoordinateLatitude')), _num(_ci(now, 'CoordinateLongitude'))
            if la is not None and lo is not None:
                pts.append({'h': 0, 'lat': la, 'lon': lo, 'kt': _ms_to_kt(_ci(now, 'MaxWindSpeed')),
                            'hpa': _num(_ci(now, 'Pressure')), 'r70_km': None})
        for f in fc:
            la, lo = _num(_ci(f, 'CoordinateLatitude')), _num(_ci(f, 'CoordinateLongitude'))
            tau = _num(_ci(f, 'ForecastHour'))
            if la is None or lo is None or not tau:
                continue
            pts.append({'h': int(tau), 'lat': la, 'lon': lo, 'kt': _ms_to_kt(_ci(f, 'MaxWindSpeed')),
                        'hpa': _num(_ci(f, 'Pressure')), 'r70_km': _num(_ci(f, 'Radius70PercentProbability'))})
        if pts and pts[0]['h'] == 0:
            out.append({'agency': 'CWA', 'name': name,
                        'issue': base.strftime('%Y-%m-%dT%H:%MZ') if base else None,
                        'points': sorted(pts, key=lambda q: q['h'])})
        else:
            print(f"[OFFICIAL] CWA {name} 沒有目前位置，略過（分析 {len(an)} 筆、預報 {len(fc)} 筆）")
    return out


def _ms_to_kt(x):
    v = _num(x)
    return None if v is None else round(v * 1.94384)
