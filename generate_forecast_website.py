import os
import json
import html
import re
import math
import pandas as pd  # type: ignore
from datetime import datetime, timedelta, timezone

# 網站版號，顯示在頁首語言切換鈕右邊。改版時只動這裡 —— HTML 由 f-string 取值。
SITE_VERSION = "7.1.0"

# 與 forecast.py 的 COLOR_MAP 同一組色票（灰→藍→綠→琥珀→橘→紅→紫），
# 網頁上的字卡顏色才會跟地圖上的點對得起來。改色時兩邊要一起改。
CAT_COLOR_MAP = {
    'TD': '#8A97A6',
    'TS': '#2E86C8',
    'Cat1': '#1FA97E',
    'Cat2': '#E0AC2B',
    'Cat3': '#EE7A22',
    'Cat4': '#DC3A4E',
    'Cat5': '#A548C8',
    'Unknown': '#B7C0CA',
}

# 徽章上的文字色：淺底配深字、深底配白字（逐色挑過，不用亮度公式硬套）
CAT_TEXT_MAP = {
    'TD': '#0D2033',
    'TS': '#FFFFFF',
    'Cat1': '#08281E',
    'Cat2': '#3A2A02',
    'Cat3': '#3A1B02',
    'Cat4': '#FFFFFF',
    'Cat5': '#FFFFFF',
    'Unknown': '#0D2033',
}

# 各級距的風速區間（kt），與 ss_category 的門檻一致；網頁的強度色帶、
# 儀表與說明頁的分級表都從這裡取值。最後一格的上限 170 只是色帶畫到哪裡為止。
CAT_RANGES = [
    ('TD', 0, 35), ('TS', 35, 64), ('Cat1', 64, 83), ('Cat2', 83, 96),
    ('Cat3', 96, 113), ('Cat4', 113, 137), ('Cat5', 137, 170),
]
SCALE_MAX_KT = 170

# 頂部導覽列：颱風超過這個數量就把各颱風連結收進「颱風 ▾」下拉選單
NAV_COLLAPSE_AT = 3

# 總覽頁「預報模式」一欄的清單（顯示順序即此順序）
KNOWN_MODELS = [
    ('WN3-C', 'Google DeepMind', 'WeatherNext · Ensemble'),
    ('WN2-C r2', 'Google DeepMind', 'WeatherNext · Ensemble'),
    ('WN2-C r1', 'Google DeepMind', 'WeatherNext · Ensemble'),
    ('WN2-C 1000', 'Google DeepMind', 'WeatherNext · 1000 members'),
    ('GENC', 'Google DeepMind', 'WeatherNext · Ensemble'),
    ('AIFS', 'ECMWF', 'AIFS-ENS + AIFS-single'),
    ('ECMWF', 'ECMWF', 'IFS ENS + HRES'),
    ('AIGFS', 'NOAA', 'AIGEFS + AIGFS'),
    ('GFS', 'NOAA', 'GEFS + GFS'),
]


# 與 forecast.py 的 ss_category 相同；刻意重複而不匯入，
# 避免匯入 forecast 模組時觸發其模組層級的下載目錄建立等副作用。
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


# ECMWF／AIFS 來自 ECMWF Open Data（CC-BY，授權與 WeatherNext 不同），
# 其餘模式來自 Weather Lab；圖說的來源字串不能寫死成 DeepMind。
ECMWF_MODELS = {'ECMWF', 'AIFS', 'ECMWF-ENS', 'AIFS-ENS'}
NOAA_MODELS = {'GFS', 'AIGFS', 'GEFS', 'AIGEFS'}
# 只有系集的產品（如生成潛勢）用 -ENS 名稱；首頁模式卡是 AIFS／ECMWF，亮燈時對回去
ENS_SYSTEM = {'AIFS-ENS': 'AIFS', 'ECMWF-ENS': 'ECMWF', 'AIGEFS': 'AIGFS', 'GEFS': 'GFS'}

# 潛勢頁上的 WN2-C 1000 成員路徑聚類圖：算進潛勢頁的「N 個模式」（8 個；NOAA 只有 GEFS 有潛勢產品），
# 但圖說不同，也不放進左右拖曳的比較器（聚類圖與其他潛勢圖畫法不同，對不齊）
CLUSTER_LABEL = 'WN2-C 1000'


def _genesis_source(model_label: str) -> str:
    if model_label in ECMWF_MODELS:
        return 'ECMWF Open Data'
    if model_label in NOAA_MODELS:
        return 'NOAA NCEP'
    return f'Google DeepMind {model_label}'


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _num(v):
    """轉成 float；NaN、None 或無法轉換時回傳 None。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _hex_rgb(hex_color: str, mix_white: float = 0.0) -> str:
    """'#RRGGBB' → 'r,g,b'，可選擇往白色混合（給深色主視覺上的流線用）。"""
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (round(c + (255 - c) * mix_white) for c in (r, g, b))
    return f"{r},{g},{b}"


def _coord(s):
    """JTWC 的 '18.2°N' / '131.5E' → 帶正負號的度數（S、W 為負）；解析不了回傳 None。"""
    m = re.match(r'\s*([0-9.]+)\s*°?\s*([NSEW])', str(s or ''), re.IGNORECASE)
    if not m:
        return None
    v = float(m.group(1))
    return -v if m.group(2).upper() in 'SW' else v


def _snap_track(pts: list, lat, lon, kt) -> list:
    """模式起報時間通常比 JTWC 定位早，路徑起點會跟颱風中心錯開。
    把 JTWC 位置投影到路徑前幾段上，丟掉投影點之前的點，改從 JTWC 位置畫起。"""
    if lat is None or lon is None or len(pts) < 2:
        return pts
    cos = math.cos(math.radians(lat))
    best = (float('inf'), 0)
    for k in range(min(len(pts) - 1, 8)):
        (ay, ax), (by, bx) = pts[k][:2], pts[k + 1][:2]
        dx, dy = ((bx - ax + 180) % 360 - 180) * cos, by - ay    # 跨換日線時經度差取短邊
        px, py = ((lon - ax + 180) % 360 - 180) * cos, lat - ay
        L = dx * dx + dy * dy
        f = max(0.0, min(1.0, (px * dx + py * dy) / L)) if L else 0.0
        d = (px - f * dx) ** 2 + (py - f * dy) ** 2
        if d < best[0]:
            best = (d, k + 1 if f > 0 else k)
    k = best[1]
    if k < len(pts) and abs(pts[k][0] - lat) < 1e-3 and abs(pts[k][1] - lon) < 1e-3:
        k += 1
    start_kt = round(kt) if kt is not None else pts[max(k - 1, 0)][2]
    return [[round(lat, 2), round(lon, 2), start_kt]] + pts[k:]


def _jtwc_track(jtwc_data: dict, wind) -> list:
    """JTWC 官方預報路徑：現在位置 + 公報各時段預報點，回傳 [[lat, lon, kt, 時數], ...]；沒有預報點回傳 []。
    第 4 欄時數讓地球只在整 24 小時畫點（JTWC 前 72 小時 12 小時一筆，之後 24 小時一筆）。"""
    lat, lon = _coord(jtwc_data.get('latitude')), _coord(jtwc_data.get('longitude'))
    fc = jtwc_data.get('forecast_track') or []
    if lat is None or lon is None or not fc:
        return []
    pts = [[round(lat, 2), round(lon, 2), round(wind) if wind is not None else None, 0]]
    pts += [[round(la, 2), round((lo + 180) % 360 - 180, 2), kt, tau] for la, lo, kt, tau in fc]
    return pts


def _globe_track(models: list[dict]) -> list:
    """給 3D 地球畫預報路徑：取第一個有系集平均的模式，回傳 [[lat, lon, kt], ...]。"""
    for m in models:
        df = m.get('mean_df') if isinstance(m, dict) else None
        if not isinstance(df, pd.DataFrame) or df.empty or not {'lat', 'lon'} <= set(df.columns):
            continue
        df = df.sort_values('valid_time') if 'valid_time' in df.columns else df
        pts = []
        for _, row in df.iterrows():
            la, lo, kt = _num(row.get('lat')), _num(row.get('lon')), _num(row.get('wind'))
            if la is None or lo is None:
                continue
            pts.append([round(la, 2), round((lo + 180) % 360 - 180, 2), round(kt) if kt is not None else None])
        if len(pts) >= 2:
            return pts[:80]
    return []


def _fmt_obs_time(raw: str) -> str:
    """JTWC 的 'DDHHMM Z' → 'DD / HH:MM UTC'；格式不符就原樣回傳。"""
    s = str(raw).replace('Z', '').strip()
    if len(s) == 6 and s.isdigit():
        return f"{s[:2]} / {s[2:4]}:{s[4:]} UTC"
    return str(raw)


def _tz(iso, text: str, fmt: str = 'mdh') -> str:
    """UTC 時間包成 <time class="tz">（只用在頁首更新時間）：前端依「UTC／臺灣時間」設定重排文字；沒有 ISO 就原樣輸出。
    fmt：mdh＝月/日 時、dhm＝日 / 時:分（JTWC 觀測時間）、ymd／hm／s＝頁首更新時間的三段。"""
    if not iso:
        return text
    return f'<time class="tz" data-utc="{_esc(str(iso))}" data-fmt="{fmt}">{text}</time>'


def _figure(src: str, alt: str, onerror_extra: str = "", cls: str = "") -> str:
    """可點擊放大的圖：載入前顯示骨架閃光，載入後淡入；壞圖時標記 broken。

    onload／onerror 寫成自給自足的行內程式，不呼叫頁尾腳本的函式 ——
    圖片可能在腳本解析完之前就載好。
    """
    onerr = "this.parentNode.classList.add('loaded','broken');" + onerror_extra
    extra = f" {cls}" if cls else ""
    return (f'<figure class="zoomable skel{extra}" data-caption="{_esc(alt)}">'
            f'<img src="{_esc(src)}" alt="{_esc(alt)}" loading="lazy" decoding="async" '
            f'onload="this.parentNode.classList.add(\'loaded\')" onerror="{onerr}">'
            '<span class="zoom-hint" data-i18n="zoom.hint">🔍 Click to enlarge</span></figure>')


def _model_tabs(track: str, labels: list[str], extra_cls: str = "") -> str:
    buttons = "".join(
        f'<button class="model-tab-btn{" active" if i == 0 else ""}" role="tab" aria-selected="{"true" if i == 0 else "false"}" '
        f'data-track="{_esc(track)}" data-model="{_esc(lbl)}">{_esc(lbl)}</button>'
        for i, lbl in enumerate(labels))
    return f'<div class="seg model-tabs {extra_cls}" role="tablist"><span class="seg-ind"></span>{buttons}</div>'


# 城市侵襲機率表：臺灣城市一律列出，其餘只在任一模式 ≥ 1% 時列出。
# 色階與 forecast.py 的 STRIKE_LEVELS／STRIKE_COLORS 一致（同一份侵襲機率的配色）。
CITY_ALWAYS = {'tw_landfall', 'taipei', 'taichung', 'kaohsiung', 'hualien', 'hengchun'}
CITY_LEVELS = [1, 10, 20, 30, 40, 50, 60, 70, 80, 90]
CITY_COLORS = ['#A9D6F5', '#5E9DDB', '#3B6DB3', '#3F9C55', '#9CC64E',
               '#EFD35A', '#EBA03E', '#D9463A', '#9E2A22', '#C451D3']
CITY_DARK_TEXT = {0, 4, 5, 6}   # 淺色底用深字，其餘用白字


def _player(key: str, frames_dir: str, frame_files: list[str], caption: str, alt: str,
            start: int = 0) -> str:
    """逐幀動畫播放器（頁尾腳本的 initPlayer 接手）。key 在整頁要唯一；start 是一開始顯示的幀。"""
    folder = os.path.basename(frames_dir)
    n = len(frame_files)
    return f"""<div class="player" data-anim-key="{_esc(key)}" data-frames-dir="{_esc(folder)}"
                         data-frames='{_esc(json.dumps(frame_files))}' data-start="{start}">
                        <figure class="zoomable skel frame-stage" data-caption="{_esc(caption)}">
                            <img class="frame is-front" src="{_esc(folder)}/{_esc(frame_files[start])}" alt="{_esc(alt)}"
                                 loading="lazy" decoding="async" onload="this.parentNode.classList.add('loaded')"
                                 onerror="this.parentNode.classList.add('loaded','broken')">
                            <img class="frame" alt="" decoding="async">
                            <span class="zoom-hint" data-i18n="zoom.hint">🔍 Click to enlarge</span>
                            <span class="buffer"><span></span></span>
                        </figure>
                        <div class="player-controls">
                            <button class="pc-btn pc-main" data-act="toggle" title="Play">
                                <span class="ic-play">{ICONS['play']}</span><span class="ic-pause">{ICONS['pause']}</span>
                            </button>
                            <button class="pc-btn" data-act="prev" data-i18n="pl.prev" data-i18n-attr="title" title="Previous frame">{ICONS['prev']}</button>
                            <button class="pc-btn" data-act="next" data-i18n="pl.next" data-i18n-attr="title" title="Next frame">{ICONS['next']}</button>
                            <div class="timeline-wrap">
                                <input type="range" class="timeline" min="0" max="{n - 1}" value="{start}" aria-label="Frame">
                            </div>
                            <span class="frame-counter mono">{start + 1}/{n}</span>
                            <div class="speed-seg" role="group">
                                <button class="speed-btn" data-speed="1">1×</button><button class="speed-btn active" data-speed="2">2×</button><button class="speed-btn" data-speed="4">4×</button><button class="speed-btn" data-speed="8">8×</button>
                            </div>
                        </div>
                    </div>"""


# 面板標題旁的小標籤：目前顯示哪個模式（由颱風頁上方的模式選單控制，腳本填字）
MT_SHOWN = '<span class="mt-shown" aria-live="polite"></span>'


def _model_group(name: str) -> str:
    """同一個模式的不同寫法算一組（與頁尾腳本的 modelGroup 相同）：AIFS-ENS／AIFS-single／AIFS → AIFS。"""
    n = re.sub(r'-ENS$|-SINGLE$| HRES$', '', str(name).upper())
    return {'AIGEFS': 'AIGFS', 'GEFS': 'GFS'}.get(n, n)


def _tabbed_image_panel(sec_id: str, track_key: str, icon: str, title_key: str, title: str,
                        items: list[tuple[str, str]], note_key: str, note: str, alt: str) -> str:
    """一個 panel：上方模式分頁（只有一個時改成標籤）＋每模式一張圖＋說明。

    track_key 要與其他區塊不同，分頁才會獨立切換（多出的 WN2-C 1000 分頁不牽動
    路徑圖與動畫的分頁）。items = [(模式名, 圖檔路徑), ...]。
    """
    panels = "".join(f"""
                <div class="model-panel" data-track="{_esc(track_key)}" data-model="{_esc(lbl)}"{'' if i == 0 else ' style="display:none;"'}>
                    {_figure(os.path.basename(p), f"{alt} · {lbl}")}
                </div>""" for i, (lbl, p) in enumerate(items))
    tabs = (_model_tabs(track_key, [lbl for lbl, _ in items]) if len(items) > 1
            else f'<div class="model-label">{_esc(items[0][0])}</div>')
    return f"""
            <div class="panel reveal" id="{sec_id}">
                <div class="panel-header">
                    <span class="panel-icon">{icon}</span>
                    <span data-i18n="{title_key}">{title}</span>{MT_SHOWN if len(items) > 1 else ''}
                </div>
                {tabs}
                {panels}
                <p class="map-note" data-i18n="{note_key}">{note}</p>
            </div>"""


def _place_1000(items: list, label=lambda x: x) -> list:
    """WN2-C 1000 一律排在 WN2-C r1 之後；該颱風沒有 r1 時接在最後一個 WN 系列之後。

    1000 成員版沒有自己的 storm dict，各清單都是最後才補上，順序要另外排。
    items 可以是名稱或 tuple，label 取出名稱。
    """
    rest = [x for x in items if label(x) != CLUSTER_LABEL]
    k1000 = [x for x in items if label(x) == CLUSTER_LABEL]
    if not k1000:
        return list(items)
    names = [label(x) for x in rest]
    if 'WN2-C r1' in names:
        pos = names.index('WN2-C r1') + 1
    else:
        wn = [i for i, n in enumerate(names) if str(n).startswith('WN')]
        pos = wn[-1] + 1 if wn else len(rest)
    return rest[:pos] + k1000 + rest[pos:]


def _model_images(models: list, key: str, key_1000: str, label_key: str = 'model') -> list[tuple[str, str]]:
    """各模式 storm dict 的 key 圖檔，再加上掛在第一個 dict 的 1000 成員圖（存在者）。

    label_key='ens_name' 用在只有系集的產品（侵襲機率），分頁顯示 AIFS-ENS／ECMWF-ENS。
    """
    items = [(m.get(label_key) or m.get('model', 'WN2-C r2'), m.get(key)) for m in models if isinstance(m, dict)]
    items += [(CLUSTER_LABEL, m.get(key_1000)) for m in models
              if isinstance(m, dict) and m.get(key_1000)][:1]
    return _place_1000([(lbl, p) for lbl, p in items if p and os.path.exists(p)], label=lambda x: x[0])


SCORE_LEADS = [24, 48, 72, 96, 120]
SCORE_MIN_N = 3          # 少於這個樣本數不參與排名、淡化顯示
# 折線圖各模式顏色：深淺主題都看得清楚；決定報虛線、JTWC 點線
SCORE_COLORS = {
    'WN3-C': '#4C9BE8', 'WN2-C r2': '#2DB7A3', 'WN2-C r1': '#7FB5D9', 'GENC': '#63C26B',
    'AIFS-ENS': '#A06CD5', 'AIFS-single': '#C98BD9', 'ECMWF-ENS': '#E0465E',
    'ECMWF HRES': '#F08A3C', 'AIGEFS': '#22A3C4', 'AIGFS': '#7FD3E6',
    'GEFS': '#8A9A1E', 'GFS': '#C2B44A', 'JTWC': '#9AA6B2',
}


def _score_get(card: dict, m: str, ld: int):
    d = card.get(m) or {}
    return d.get(ld) or d.get(str(ld))       # 來自 JSON 時鍵是字串


def _score_heat(rel: float) -> str:
    """0（最好）→ 1（最差）：綠 → 黃 → 紅。"""
    stops = [(0.0, (46, 158, 91)), (0.5, (224, 180, 58)), (1.0, (217, 70, 58))]
    rel = min(max(rel, 0.0), 1.0)
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if rel <= b:
            t = (rel - a) / (b - a)
            return '#%02x%02x%02x' % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))
    return '#d9463a'


def _score_groups(models: list, det_names: set) -> list:
    """(群組鍵, 預設標題, 副標鍵, 預設副標, [模式]) —— 系集平均／決定報／官方預報。"""
    ens = [m for m in models if m not in det_names and m != 'JTWC']
    det = [m for m in models if m in det_names]
    off = [m for m in models if m == 'JTWC']
    return [g for g in (
        ('score.grp.ens', 'Ensemble mean', None, '', ens),
        ('score.grp.det', 'Deterministic', 'score.grp.det.sub',
         'single run — usually less accurate than an ensemble mean', det),
        ('score.grp.jtwc', 'Official (JTWC)', 'score.grp.jtwc.sub',
         'verified against its own warning positions, which flatters JTWC — not ranked', off)) if g[4]]


# 成績單的四種指標：(鍵, 分頁 i18n 鍵, 預設分頁名, 單位, 是否有正負號)
#   track 路徑誤差、at 沿路徑誤差、ct 跨路徑誤差、int 強度誤差（後三者看正負＝系統性偏差）
SCORE_METRICS = [
    ('track', 'score.m.track', 'Track', 'km', False),
    ('at', 'score.m.at', 'Along-track', 'km', True),
    ('ct', 'score.m.ct', 'Cross-track', 'km', True),
    ('int', 'score.m.int', 'Intensity', 'kt', True),
]
SCORE_METRIC_TEXT = {
    'track': ('score.chart.y', 'Mean track error (km)', None, ''),
    'at': ('score.chart.at', 'Mean along-track error (km) · + too fast, − too slow', 'score.note.at',
           'Along-track error: measured along the storm\'s real direction of motion, is the forecast '
           'position ahead of (+) or behind (−) the real storm? A steady + means the model moves the storm '
           'too fast, − too slow. The small |e| is the average size ignoring the sign. Only counted while the '
           'storm moves at least 5 km/h; when it stalls or loops its direction is unreliable.'),
    'ct': ('score.chart.ct', 'Mean cross-track error (km) · + right of track, − left', 'score.note.ct',
           'Cross-track error: at right angles to the real motion, is the forecast to the right (+) or left (−) '
           'of the real track? A model that stays on one side usually has a systematic steering bias, for '
           'example in how far west the subtropical high reaches. The small |e| is the average size ignoring the sign.'),
    'int': ('score.chart.int', 'Mean intensity error (kt) · + too strong, − too weak', 'score.note.int',
            'Intensity error: forecast maximum wind minus the JTWC maximum wind (kt): + = forecast too strong, '
            '− = too weak. The small |e| is the average size ignoring the sign. Ensemble means smooth out the '
            'members and usually run weak, and coarser models often underestimate strong typhoons. Wind speeds '
            'were only archived from late October 2026 on, so older forecasts have no intensity to compare.'),
}


def _score_table(card: dict, order: list[str], det_names: set, metric: str = 'track') -> str:
    """模式誤差表：card = {model: {lead: [值, n, (副值)]}}。

    每個預報時數各自比較：n ≥ SCORE_MIN_N 的格子依誤差由綠（最好）到紅（最差）上色。
    路徑誤差最小的標 ★、其餘標比最好多幾 %；沿／跨路徑與強度誤差有正負號，依絕對值上色
    （越接近 0 越綠），小字附不分正負的平均大小 |e|。樣本不足的格子淡化、不參與排名。
    """
    unit, signed = next((u, sg) for k, _, _, u, sg in SCORE_METRICS if k == metric)
    models = [m for m in order if m in card] + sorted(m for m in card if m not in order)
    if not models:
        return ''
    mag = (lambda v: abs(v[0])) if signed else (lambda v: v[0])
    rank = {}
    for ld in SCORE_LEADS:
        # JTWC 用自己的警報位置當實況、數字偏有利，不跟模式一起排名
        vals = [mag(v) for m in models if m != 'JTWC' and (v := _score_get(card, m, ld)) and v[1] >= SCORE_MIN_N]
        rank[ld] = (min(vals), max(vals)) if vals else None
    fmt = (lambda x: f'{x:+.0f}'.replace('-', '−')) if signed else (lambda x: f'{x:.0f}')

    def extra(v):
        if len(v) < 3:
            return ''
        return f' · |e| {v[2]:.0f}' if signed else ''

    span = len(SCORE_LEADS) + 1
    rows = []
    for gk, gtxt, sk, stxt, ms in _score_groups(models, det_names):
        sub = f'<small data-i18n="{sk}">{stxt}</small>' if sk else ''
        rows.append(f'<tr class="grp"><td colspan="{span}"><span data-i18n="{gk}">{gtxt}</span>{sub}</td></tr>')
        for m in ms:
            cells = []
            for ld in SCORE_LEADS:
                v = _score_get(card, m, ld)
                if not v:
                    cells.append('<td class="c-nil">—</td>')
                    continue
                n = v[1]
                if m == 'JTWC' and n >= SCORE_MIN_N:
                    cells.append(f'<td class="c-ref">{fmt(v[0])}<span class="eta">n={n}{extra(v)}</span></td>')
                    continue
                if n < SCORE_MIN_N or rank[ld] is None:
                    cells.append(f'<td class="c-low" title="n &lt; {SCORE_MIN_N}">{fmt(v[0])}'
                                 f'<span class="eta">n={n}{extra(v)}</span></td>')
                    continue
                lo, hi = rank[ld]
                rel = (mag(v) - lo) / (hi - lo) if hi > lo else 0.0
                if signed:
                    tag = ''
                else:
                    tag = ' · ★' if mag(v) == lo else (f' · +{(mag(v) - lo) / lo * 100:.0f}%' if lo > 0 else '')
                bg = _score_heat(rel)
                r_, g_, b_ = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
                fg = '#16324F' if 0.299 * r_ + 0.587 * g_ + 0.114 * b_ > 150 else '#fff'
                cells.append(f'<td style="background:{bg};color:{fg};">{fmt(v[0])}'
                             f'<span class="eta">n={n}{extra(v)}{tag}</span></td>')
            name_cls = 'c-name c-detname' if m in det_names else 'c-name'
            rows.append(f'<tr><td class="{name_cls}">{_esc(m)}</td>{"".join(cells)}</tr>')
    head = ''.join(f'<th>{ld} h<span class="eta">{unit}</span></th>' for ld in SCORE_LEADS)
    return (f'<div class="city-table-wrap"><table class="city-table score-table">'
            f'<caption class="sr-only" data-i18n="cap.score">Mean forecast error by lead time for each model</caption>'
            f'<thead><tr><th data-i18n="score.model">Model</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _score_chart(card: dict, order: list[str], det_names: set, metric: str = 'track') -> str:
    """平均誤差隨預報時數的折線圖（inline SVG，跟著網站深淺主題變色）。

    沿／跨路徑誤差有正負號，y 軸上下對稱並畫出 0 線。"""
    unit, signed = next((u, sg) for k, _, _, u, sg in SCORE_METRICS if k == metric)
    ykey, ytxt = SCORE_METRIC_TEXT[metric][:2]
    models = [m for m in order if m in card] + sorted(m for m in card if m not in order)
    pts = {m: [(ld, v[0], v[1]) for ld in SCORE_LEADS if (v := _score_get(card, m, ld))] for m in models}
    pts = {m: p for m, p in pts.items() if p}
    if not pts:
        return ''
    W, H, L, R, T, B = 900, 300, 52, 16, 12, 34
    top = max(abs(e) for p in pts.values() for _, e, _ in p) * 1.1 or 1.0
    step = next(st for st in (5, 10, 20, 25, 50, 100, 200, 500) if top / st <= 8)
    ymax = (int(top // step) + 1) * step
    ymin = -ymax if signed else 0
    x = lambda ld: L + (ld - SCORE_LEADS[0]) / (SCORE_LEADS[-1] - SCORE_LEADS[0]) * (W - L - R)
    y = lambda e: T + (ymax - e) / (ymax - ymin) * (H - T - B)
    g = []
    for k in range(ymin, ymax + 1, step):
        lbl = f'{k:+d}'.replace('-', '−') if signed and k else f'{k}'
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{y(k):.1f}" y2="{y(k):.1f}" style="stroke:var(--border)" '
                 f'stroke-width="{2 if signed and k == 0 else 1}"/>'
                 f'<text x="{L - 6}" y="{y(k) + 4:.1f}" text-anchor="end" font-size="11" style="fill:var(--text-2)">{lbl}</text>')
    for ld in SCORE_LEADS:
        g.append(f'<text x="{x(ld):.1f}" y="{H - 12}" text-anchor="middle" font-size="11" style="fill:var(--text-2)">{ld} h</text>')
    for m, p in pts.items():
        c = SCORE_COLORS.get(m, '#9AA6B2')
        dash = ' stroke-dasharray="6 4"' if m in det_names else (' stroke-dasharray="2 4"' if m == 'JTWC' else '')
        path = ' '.join(f'{x(ld):.1f},{y(e):.1f}' for ld, e, _ in p)
        g.append(f'<polyline points="{path}" fill="none" stroke="{c}" stroke-width="2.2"{dash}/>')
        for ld, e, n in p:
            fill = c if n >= SCORE_MIN_N else 'none'
            val = f'{e:+.0f}' if signed else f'{e:.0f}'
            g.append(f'<circle cx="{x(ld):.1f}" cy="{y(e):.1f}" r="3.6" fill="{fill}" stroke="{c}" stroke-width="1.6">'
                     f'<title>{_esc(m)} · {ld} h · {val} {unit} · n={n}</title></circle>')
    legend = ''.join(
        f'<span><i style="background:{SCORE_COLORS.get(m, "#9AA6B2")}'
        f'{";opacity:.55" if m in det_names or m == "JTWC" else ""}"></i>{_esc(m)}</span>' for m in pts)
    return (f'<div class="score-chart"><div class="sc-axis" data-i18n="{ykey}">{ytxt}</div>'
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_esc(ytxt)}">{"".join(g)}</svg>'
            f'<div class="sc-legend">{legend}</div></div>')


def _score_metric_cards(card: dict, sample: str) -> dict:
    """某個樣本（homog／all）下四種指標各自的 {model: {lead: [...]}}。

    強度存成 [平均絕對誤差, n, 平均偏差]，這裡換成跟沿／跨路徑一樣的 [偏差, n, |e|]，主數字顯示正負。"""
    card = card or {}
    out = {'track': card.get(sample) or {},
           **{k: (card.get(k) or {}).get(sample) or {} for k in ('at', 'ct', 'int')}}
    out['int'] = {m: {ld: ([v[2], v[1], v[0]] if len(v) >= 3 and v[2] is not None else v) for ld, v in leads.items()}
                  for m, leads in out['int'].items()}
    return out


def _score_metric_panels(key: str, cards: dict, order: list[str], det_names: set) -> str:
    """一個分頁（範圍 × 樣本）的內容：路徑誤差照原本的圖表放最前面，
    下面再接「其他指標」分頁：沿路徑／跨路徑／強度。"""
    track = cards.get('track') or {}
    html = _score_chart(track, order, det_names, 'track') + _score_table(track, order, det_names, 'track')
    tabs, panels = [], []
    for i, (mk, lkey, ltxt, _, _) in enumerate(m for m in SCORE_METRICS if m[0] != 'track'):
        c = cards.get(mk) or {}
        tabs.append(f'<button class="model-tab-btn{" active" if i == 0 else ""}" role="tab" aria-selected="{"true" if i == 0 else "false"}" '
                    f'data-track="{_esc(key)}-m" data-model="{mk}"><span data-i18n="{lkey}">{ltxt}</span></button>')
        nkey, ntxt = SCORE_METRIC_TEXT[mk][2:]
        note = f'<p class="map-note" style="margin:0 0 10px;" data-i18n="{nkey}">{ntxt}</p>' if nkey else ''
        body = (_score_chart(c, order, det_names, mk) + _score_table(c, order, det_names, mk)) if c else (
            '<p class="map-note" data-i18n="score.m.pending">Not enough data for this measure yet.</p>')
        hide = '' if i == 0 else ' style="display:none;"'
        panels.append(f'<div class="model-panel" data-track="{_esc(key)}-m" data-model="{mk}"{hide}>'
                      f'{note}{body}</div>')
    html += (f'<h4 class="score-more" data-i18n="score.more">More measures</h4>'
             f'<div class="seg model-tabs score-metrics" role="tablist"><span class="seg-ind"></span>'
             f'{"".join(tabs)}</div>' + ''.join(panels))
    return html


def _score_block(track_key: str, scope_cards: list, order: list[str], det_names: set) -> str:
    """成績區塊：分頁（範圍 × 樣本），每頁再分指標（路徑／沿路徑／跨路徑／強度）。

    scope_cards = [(範圍鍵, card), ...]。內容完全相同的分頁合併成一個，免得點來點去都一樣：
    同質＝全部（每期各模式都到齊）時只留一個；只有一顆颱風有資料時「這顆颱風」與「所有颱風」也相同。
    """
    items, notes = [], []
    for scope, card in scope_cards:
        h, a = _score_metric_cards(card, 'homog'), _score_metric_cards(card, 'all')
        cands = ([('same', h)] if h['track'] and h == a else
                 [(smp, c) for smp, c in (('homog', h), ('all', a)) if c['track']])
        for sample, c in cands:
            if any(c == prev for _, _, prev in items):
                if scope == 'allst' and 'score.onestorm' not in notes:   # 只有這顆有資料：「所有颱風」與「這個颱風」相同
                    notes.append('score.onestorm')
                continue
            if sample == 'same' and 'score.same' not in notes:
                notes.append('score.same')
            items.append((scope, sample, c))
    if not items:
        return ''
    note_txt = {'score.same': 'Every model has every forecast so far, so the homogeneous and full samples are identical and shown once.',
                'score.onestorm': 'Only this storm has verified forecasts so far, so it matches the all-storms total.',
                'score.official': 'JTWC / JMA / CWA rows are the official forecasts, verified the same way; they appear only in the all-forecasts sample because their archive starts later than the models’ and does not enter the homogeneous sample.'}
    if any(m in (c.get('track') or {}) for _, _, c in items for m in ('JTWC', 'JMA', 'CWA')) and 'score.official' not in notes:
        notes.append('score.official')
    tabs, panels = [], []
    for i, (scope, sample, c) in enumerate(items):
        key = f'{scope}-{sample}'
        tabs.append(f'<button class="model-tab-btn{" active" if i == 0 else ""}" role="tab" aria-selected="{"true" if i == 0 else "false"}" '
                    f'data-track="{_esc(track_key)}" data-model="{key}">'
                    f'<span data-i18n="score.tab.{scope}.{sample}">{key}</span></button>')
        hide = '' if i == 0 else ' style="display:none;"'
        panels.append(f'<div class="model-panel" data-track="{_esc(track_key)}" data-model="{key}"{hide}>'
                      f'{_score_metric_panels(f"{track_key}-{key}", c, order, det_names)}</div>')
    head = (f'<div class="seg model-tabs" role="tablist"><span class="seg-ind"></span>{"".join(tabs)}</div>'
            if len(tabs) > 1 else
            f'<div class="model-label" data-i18n="score.tab.{items[0][0]}.{items[0][1]}">{items[0][0]}</div>')
    head += ''.join(f'<p class="map-note" style="margin:0 0 10px;" data-i18n="{k}">{note_txt[k]}</p>' for k in notes)
    return head + ''.join(panels)


# 16 方位：(英文, 中文)；颱風頁摘要的移動方向用
COMPASS16 = [('north', '北'), ('north-northeast', '北北東'), ('northeast', '東北'), ('east-northeast', '東北東'),
             ('east', '東'), ('east-southeast', '東南東'), ('southeast', '東南'), ('south-southeast', '南南東'),
             ('south', '南'), ('south-southwest', '南南西'), ('southwest', '西南'), ('west-southwest', '西南西'),
             ('west', '西'), ('west-northwest', '西北西'), ('northwest', '西北'), ('north-northwest', '北北西')]


def _bi(en: str, zh: str) -> str:
    """中英各一份，CSS 依 <html lang> 只顯示其中一份（句子結構不同，套不進 data-i18n 的參數）。"""
    return f'<span class="i-en">{en}</span><span class="i-zh">{zh}</span>'


def _storm_summary(info: dict, city_cols: list) -> str:
    """颱風頁頂端的白話摘要：往哪走、會變強還是變弱、臺灣有沒有威脅。缺資料的那句就不寫。"""
    import math
    lines = []
    lat, lon, wind = info.get('lat'), info.get('lon'), info.get('wind')
    fc = [p for p in (info.get('jtwc_fc') or []) if p and p[3] and p[3] > 0]
    if lat is not None and lon is not None and fc:
        la2, lo2, _, tau = min(fc, key=lambda p: abs(p[3] - 12))
        p1, p2, dl = math.radians(lat), math.radians(la2), math.radians(lo2 - lon)
        brg = math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                      math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360
        dist = 6371 * math.acos(min(1, max(-1, math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl))))
        spd = dist / tau
        if spd < 5:
            lines.append(_bi('Nearly stationary.', '幾乎停滯。'))
        else:
            en, zh = COMPASS16[int((brg + 11.25) // 22.5) % 16]
            lines.append(_bi(f'Moving {en} at about {spd:.0f} km/h.', f'向{zh}移動，時速約 {spd:.0f} 公里。'))
    near24 = [p for p in fc if 12 <= p[3] <= 36 and p[2] is not None]
    if wind is not None and near24:
        _, _, kt24, tau24 = min(near24, key=lambda p: abs(p[3] - 24))
        cat = ss_category(kt24)
        catname = f'<span data-i18n="catname.{cat}">{cat}</span>'
        if kt24 >= wind + 5:
            lines.append(_bi(f'Strengthening to {kt24:.0f} kt ({catname}) in {tau24:.0f} h.',
                             f'{tau24:.0f} 小時後增強至 {kt24:.0f} kt（{catname}）。'))
        elif kt24 <= wind - 5:
            lines.append(_bi(f'Weakening to {kt24:.0f} kt ({catname}) in {tau24:.0f} h.',
                             f'{tau24:.0f} 小時後減弱至 {kt24:.0f} kt（{catname}）。'))
        else:
            lines.append(_bi(f'Holding near {kt24:.0f} kt over the next {tau24:.0f} h.',
                             f'未來 {tau24:.0f} 小時維持約 {kt24:.0f} kt。'))
    land = [(c[0], (c[1].get('tw_landfall') or {}).get('p') or 0) for c in city_cols
            if not (len(c) > 2 and c[2]) and 'tw_landfall' in c[1]]
    if land:
        name, top = max(land, key=lambda t: t[1])
        if top < 1:
            lines.append(_bi('Taiwan landfall: under 1% in every model.', '登陸臺灣：各模式機率都低於 1%。'))
        else:
            lines.append(_bi(f'Taiwan landfall: up to {top:.0f}% ({_esc(name)}).',
                             f'登陸臺灣：機率最高 {top:.0f}%（{_esc(name)}）。'))
    if not lines:
        return ''
    return '<div class="storm-summary">' + ''.join(f'<p>{l}</p>' for l in lines) + '</div>'


def _city_table(cols: list[tuple]) -> str:
    """cols = [(模式名, {city: {'p': %, 'eta': iso}}[, 是否決定報]), ...] → 城市侵襲機率表 HTML。

    決定報只有一條路徑，機率不是 0 就是 100，改顯示 ✓（附抵達時間）或 —。
    """
    keys = list(dict.fromkeys(k for c in cols for k in c[1] if not k.startswith('_')))
    # 整欄都 <1%（決定報：沒有 ✓）的模式預設收起，表格才不會十幾欄全是 <1%；按鈕可展開
    def _col_has(c):
        det = len(c) > 2 and c[2]
        return any(((c[1].get(k) or {}).get('p') or 0) >= (50 if det else CITY_LEVELS[0]) for k in keys)
    dim = [not _col_has(c) for c in cols]
    if all(dim):
        dim = [False] * len(cols)                  # 全部都 <1% 時沒有可留的欄，就全列出
    cls = lambda i: ' class="col-dim"' if dim[i] else ''
    rows = []
    quiet = []          # 臺灣城市裡每個模式都 <1% 的：不逐列列出一整排 <1%，合成一行
    for key in keys:
        vals = [c[1].get(key) or {} for c in cols]
        hit = any((v.get('p') or 0) >= CITY_LEVELS[0] for v in vals)
        if key not in CITY_ALWAYS and not hit:
            continue
        if key != 'tw_landfall' and not hit:
            quiet.append(key)
            continue
        cells = []
        for i, (c, v) in enumerate(zip(cols, vals)):
            p = v.get('p')
            dc = ' col-dim' if dim[i] else ''
            if len(c) > 2 and c[2]:
                eta = v.get('eta') or ''
                cells.append((f'<td class="c-det{dc}" title="{_esc(eta)}">✓<span class="eta">'
                              f'{_esc(eta[5:7] + "/" + eta[8:10] + " " + eta[11:13] + "Z") if eta else ""}</span></td>')
                             if (p or 0) >= 50 else f'<td class="c-nil{dc}">—</td>')
                continue
            if p is None or p < CITY_LEVELS[0]:
                cells.append(f'<td class="c-nil{dc}">&lt;1%</td>')
                continue
            idx = sum(p >= lv for lv in CITY_LEVELS) - 1
            fg = '#16324F' if idx in CITY_DARK_TEXT else '#fff'
            eta = v.get('eta') or ''
            eta_txt = (f'{eta[5:7]}/{eta[8:10]} {eta[11:13]}Z') if eta else ''
            cells.append(f'<td{cls(i)} style="background:{CITY_COLORS[idx]};color:{fg};" title="{_esc(eta)}">'
                         f'{p:.0f}%<span class="eta">{_esc(eta_txt)}</span></td>')
        rows.append((key, f'<tr><td class="c-name" data-i18n="city.{key}">{key}</td>{"".join(cells)}</tr>'))
    if not rows and not quiet:
        return ''
    # 登陸臺灣與城市侵襲定義不同（中心上岸 vs. 通過 1° 內），分兩區並各加小標題列
    span = len(cols) + 1

    def _grp(k, txt, sub_k, sub):
        return (f'<tr class="grp"><td colspan="{span}"><span data-i18n="{k}">{txt}</span>'
                f'<small data-i18n="{sub_k}">{sub}</small></td></tr>')
    land = [r for k, r in rows if k == 'tw_landfall']
    city = [r for k, r in rows if k != 'tw_landfall']
    body = ''
    if land:
        body += _grp('cities.grp.land', 'Taiwan landfall', 'cities.grp.land.sub',
                     'storm centre moves onto Taiwan\'s main island (outlying islands excluded)') + ''.join(land)
    if city or quiet:
        body += _grp('cities.grp.city', 'City strike', 'cities.grp.city.sub',
                     'track passes within 1° (~111 km) of the city') + ''.join(city)
    if quiet:
        names = '、'.join(f'<span data-i18n="city.{k}">{k}</span>' for k in quiet)
        names_en = ', '.join(f'<span data-i18n="city.{k}">{k}</span>' for k in quiet)
        body += (f'<tr class="c-quiet"><td colspan="{span}">'
                 + _bi(f'{names_en}: under 1% in every model', f'{names}：各模式都低於 1%') + '</td></tr>')
    # 表頭附上預報長度：太短的模式（如 IFS 06Z／18Z 的 144 h）<1% 不代表不會來
    def _th_sub(d):
        parts = [d.get('_init')] + ([f'≤{d["_max_h"]} h'] if d.get('_max_h') else [])
        parts = [p for p in parts if p]
        return f'<span class="eta">{_esc(" · ".join(parts))}</span>' if parts else ''
    head = ''.join(f'<th{cls(i)}>{_esc(m)}{_th_sub(d)}</th>' for i, (m, d, *_) in enumerate(cols))
    n_dim = sum(dim)
    toggle = ''
    if n_dim:
        toggle = (f'<button type="button" class="city-toggle" aria-expanded="false">'
                  f'<span class="ct-more">{_bi(f"Show all {len(cols)} models ({n_dim} under 1% everywhere)", f"顯示全部 {len(cols)} 個模式（{n_dim} 個各地都低於 1%）")}</span>'
                  f'<span class="ct-less">{_bi(f"Hide the {n_dim} models under 1% everywhere", f"收起 {n_dim} 個各地都低於 1% 的模式")}</span></button>')
    return (f'<div class="city-table-wrap{" compact" if n_dim else ""}"><table class="city-table">'
            f'<caption class="sr-only" data-i18n="cap.cities">Taiwan landfall and city strike probability by model</caption>'
            f'<thead><tr><th data-i18n="cities.city">Model</th>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>{toggle}')


# 線條圖示（導覽列與行動版底部分頁列共用）
_ICON_ATTR = ('viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
              'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"')
ICONS = {
    'overview': f'<svg {_ICON_ATTR}><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/></svg>',
    'storm': (f'<svg {_ICON_ATTR}><circle cx="12" cy="12" r="2.4"/>'
              '<path d="M19.5 7.5C17.6 4.3 13.4 3 10 4.2M4.5 16.5C6.4 19.7 10.6 21 14 19.8'
              'M7.2 4.9C4.2 6.9 3.1 10.5 4 13.6M16.8 19.1c3-2 4.1-5.6 3.2-8.7"/></svg>'),
    'genesis': (f'<svg {_ICON_ATTR}><circle cx="12" cy="12" r="9"/>'
                '<path d="M3 12h18M12 3c3.2 3.6 3.2 14.4 0 18M12 3c-3.2 3.6-3.2 14.4 0 18"/></svg>'),
    'about': f'<svg {_ICON_ATTR}><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.6v.2"/></svg>',
    'archive': f'<svg {_ICON_ATTR}><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/></svg>',
    'play': '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M8 5.5v13a1 1 0 0 0 1.5.86l10.2-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>',
    'pause': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect fill="currentColor" x="6.5" y="5" width="4" height="14" rx="1.2"/><rect fill="currentColor" x="13.5" y="5" width="4" height="14" rx="1.2"/></svg>',
    'prev': f'<svg {_ICON_ATTR}><path d="M15 6l-6 6 6 6"/></svg>',
    'next': f'<svg {_ICON_ATTR}><path d="M9 6l6 6-6 6"/></svg>',
    'compare': f'<svg {_ICON_ATTR}><path d="M12 3v18M7 8l-4 4 4 4M17 8l4 4-4 4"/></svg>',
}


OFFICIAL_COLORS = {'JTWC': '#DC2626', 'JMA': '#2563EB', 'CWA': '#059669'}
OFFICIAL_TABLE_H = [0, 12, 24, 48, 72, 96, 120]

# 颱風歷史存檔（forecast.update_storm_archive 寫的 docs/archive/{tid}.json）
ARCHIVE_MODEL_ORDER = ['WN3-C', 'WN2-C r2', 'WN2-C r1', 'WN2-C 1000', 'GENC', 'AIFS-ENS', 'AIFS-single',
                       'ECMWF-ENS', 'ECMWF HRES', 'AIGEFS', 'AIGFS', 'GEFS', 'GFS']


def _load_archive(docs_dir: str) -> list[dict]:
    """讀歷史存檔，順便把每顆颱風的成績單寫成 archive/{tid}_score.html 片段（網頁點開時才載入）。

    只列有模式預報的颱風（只有一兩筆實況、沒有任何預報可看的不列），最近結束的排前面。
    """
    adir = os.path.join(docs_dir, 'archive')
    out = []
    if not os.path.isdir(adir):
        return out
    for fn in sorted(os.listdir(adir)):
        if not fn.endswith('.json'):
            continue
        try:
            with open(os.path.join(adir, fn), encoding='utf-8') as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        fc = d.get('fcst') or {}
        if not fc or not d.get('obs'):
            continue
        tid = d.get('id') or fn[:-5]
        card = d.get('card') or {}
        score = ''
        if card:
            score = _score_block(f'arch-{tid}-score', [('storm', card)], ARCHIVE_MODEL_ORDER, set(d.get('det') or []))
        try:
            with open(os.path.join(adir, f'{tid}_score.html'), 'w', encoding='utf-8') as fh:
                fh.write(score or '<p class="map-note" data-i18n="arch.noscore">No verified forecasts for this storm yet.</p>')
        except OSError:
            pass
        # 預報趨勢圖（颱風消散前最後一版的複本）：每模式一個分頁，網頁點開時才載入
        trends = [(lbl, rel) for lbl, rel in (d.get('trends') or []) if os.path.exists(os.path.join(adir, rel))]
        tpath = os.path.join(adir, f'{tid}_trend.html')
        if trends:
            track = f'arch-{tid}-trend'
            panels = "".join(
                f'<div class="model-panel" data-track="{_esc(track)}" data-model="{_esc(lbl)}"'
                f'{"" if i == 0 else " style=\"display:none;\""}>'
                f'{_figure("archive/" + rel, f"{tid} {lbl} Track Trend")}</div>'
                for i, (lbl, rel) in enumerate(trends))
            tabs = (_model_tabs(track, [lbl for lbl, _ in trends]) if len(trends) > 1
                    else f'<div class="model-label">{_esc(trends[0][0])}</div>')
            frag = (f'<h4 class="arch-sub" data-i18n="panel.trend">Track Trend</h4>{tabs}{panels}'
                    '<p class="map-note" data-i18n="note.arch.trend">The last version drawn before the storm '
                    'ended: ensemble-mean (or deterministic) tracks from every run, older = lighter</p>')
            try:
                with open(tpath, 'w', encoding='utf-8') as fh:
                    fh.write(frag)
            except OSError:
                pass
        elif os.path.exists(tpath):
            os.remove(tpath)
        out.append({'id': tid, 'name': d.get('name'), 'first': d.get('first'), 'last': d.get('last'),
                    'peak': d.get('peak'), 'active': bool(d.get('active')),
                    'n': sum(len(v) for v in fc.values()), 'models': len(fc)})
    out.sort(key=lambda e: e['last'] or '', reverse=True)
    return out


# ── 分享預覽（LINE／Facebook 的 Open Graph 卡片）與加到主畫面（Web App Manifest）──
# 預覽圖與圖示的網址必須是絕對網址；在 GitHub Actions 裡由 GITHUB_REPOSITORY 推出 Pages 網址，
# 也可用環境變數 SITE_URL 覆寫（例如改用自訂網域時）
SITE_NAME = "Pillar's Tropical Cyclone Forecast"
SITE_SHORT_NAME = "颱風預報"
APP_BG = '#071320'          # 深色主題的底色，也是主畫面啟動畫面的底色
SHARE_IMAGE = 'share.png'   # 1200×630，Open Graph 建議尺寸
APP_ICONS = (('icon-192.png', 192), ('icon-512.png', 512), ('apple-touch-icon.png', 180))


def _site_url() -> str:
    url = os.environ.get('SITE_URL', '').strip()
    if not url:
        owner, _, repo = os.environ.get('GITHUB_REPOSITORY', 'lkt0713/Typhoon-Forecast').partition('/')
        url = f"https://{owner.lower()}.github.io/{repo}/"
    return url if url.endswith('/') else url + '/'


def _font(size: int, bold: bool = True):
    from PIL import ImageFont  # type: ignore
    from matplotlib import font_manager  # type: ignore
    path = font_manager.findfont(font_manager.FontProperties(family='DejaVu Sans', weight='bold' if bold else 'normal'))
    return ImageFont.truetype(path, size)


def _app_icon(size: int):
    """主畫面圖示：網站主色漸層底＋白色熱帶氣旋符號。整張滿版（不自己切圓角），
    符號留在中間 60% 內，Android 的圓形／圓角遮罩（maskable）切掉邊緣也不會切到符號。"""
    import numpy as np  # type: ignore
    from PIL import Image, ImageDraw  # type: ignore
    S = size * 4                                      # 先畫 4 倍大再縮小，邊緣比較平滑
    y = np.linspace(0, 1, S)[:, None]
    x = np.linspace(0, 1, S)[None, :]
    t = np.clip((x + y) / 2, 0, 1)[..., None]
    a, b = np.array([58, 160, 255]), np.array([10, 95, 196])    # 與頁首 logo 同一組漸層（#3aa0ff → #0a5fc4）
    img = Image.fromarray((a + (b - a) * t).astype('uint8'), 'RGB')
    d = ImageDraw.Draw(img)
    c, r, R, w = S / 2, S * 0.1, S * 0.2, int(S * 0.045)
    d.ellipse([c - r, c - r, c + r, c + r], outline='white', width=w)
    # 兩條旋臂（天氣圖上的北半球颱風符號）：氣流逆時針往內旋，所以旋臂往外是順時針彎——
    # 從圓的左緣往上再彎向右（東）、從右緣往下再彎向左（西）
    for cx, a0, a1 in ((c - r + R, 180, 330), (c + r - R, 0, 150)):
        d.arc([cx - R, c - R, cx + R, c + R], a0, a1, fill='white', width=w)
    return img.resize((size, size), Image.LANCZOS)


def _write_app_assets(docs_dir: str) -> None:
    """圖示與 manifest 每次都重寫：畫法固定，輸出的位元組相同，git 不會出現變動；改了畫法也會自動換新。"""
    for fn, size in APP_ICONS:
        _app_icon(size).save(os.path.join(docs_dir, fn), optimize=True)
    manifest = {
        'name': SITE_NAME, 'short_name': SITE_SHORT_NAME,
        'description': 'AI and physics-based ensemble forecasts for Western Pacific tropical cyclones',
        'lang': 'zh-TW', 'start_url': './', 'scope': './', 'display': 'standalone',
        'background_color': APP_BG, 'theme_color': APP_BG,
        'icons': [{'src': fn, 'sizes': f'{n}x{n}', 'type': 'image/png', 'purpose': 'any maskable'}
                  for fn, n in APP_ICONS if fn.startswith('icon-')],
    }
    with open(os.path.join(docs_dir, 'manifest.webmanifest'), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    # 搜尋引擎：robots.txt／sitemap.xml（單頁站，分頁都是 #/ 路由，只有一個網址）；
    # 404.html：GitHub Pages 找不到路徑時（舊連結、打錯）導回首頁，#/ 後面的分頁保留
    site = _site_url()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    with open(os.path.join(docs_dir, 'robots.txt'), 'w', encoding='utf-8') as fh:
        fh.write(f'User-agent: *\nAllow: /\nDisallow: /verification/\n\nSitemap: {site}sitemap.xml\n')
    with open(os.path.join(docs_dir, 'sitemap.xml'), 'w', encoding='utf-8') as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                 f'  <url><loc>{_esc(site)}</loc><lastmod>{today}</lastmod><changefreq>hourly</changefreq></url>\n'
                 '</urlset>\n')
    with open(os.path.join(docs_dir, '404.html'), 'w', encoding='utf-8') as fh:
        fh.write(f'''<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{_esc(SITE_NAME)}</title>
<script>location.replace({json.dumps(site)} + location.hash);</script>
<noscript><meta http-equiv="refresh" content="0;url={_esc(site)}"></noscript>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;font:16px/1.6 system-ui,-apple-system,"Noto Sans TC",sans-serif;background:{APP_BG};color:#eaf0f5;text-align:center;padding:24px}}a{{color:#8ec5ff}}</style>
</head><body><p>找不到這個頁面，正在帶你回到首頁… <a href="{_esc(site)}">回到颱風預報網站</a><br>
Page not found, taking you back to the <a href="{_esc(site)}">forecast site</a>.</p></body></html>
''')


def _write_static_assets(docs_dir: str) -> str:
    """寫出 site.css／site.js，回傳內容雜湊（8 碼）當網址的版本參數。"""
    import hashlib
    h = hashlib.sha1()
    for fn, body in (('site.css', _CSS), ('site.js', _JS)):
        data = body.encode('utf-8')
        h.update(data)
        path = os.path.join(docs_dir, fn)
        if not (os.path.exists(path) and open(path, 'rb').read() == data):   # 沒變就不重寫，git 不會有多餘變動
            with open(path, 'wb') as fh:
                fh.write(data)
    return h.hexdigest()[:8]


NOTE_OHCTRACK = "Ocean heat content under the forecast centre, sampled every 6 h along the latest JTWC forecast track (mean within ±0.5° of the centre) &nbsp;·&nbsp; Dashed line = 50 kJ/cm², a common threshold for intensification: above it the warm layer is thick enough that the storm’s own mixing does not cool the surface much &nbsp;·&nbsp; Grey squares = land or water colder than 26 °C &nbsp;·&nbsp; The ocean analysis is one daily snapshot, so this is the ocean the storm will meet if it follows the JTWC track, not a forecast of how the ocean changes"
CAVEAT_INTENSITY = "Read the intensities here as a trend, not as a forecast of peak winds. The AI models (WN3-C, WN2-C, GENC, AIFS, AIGFS) run at about 0.25° and cannot resolve the eyewall, so strong typhoons usually come out tens of knots too weak; the ECMWF and GFS ensembles also run weak. For how strong the storm will get, use the official forecasts (JTWC / JMA / CWA) in Summary; use these curves for whether it strengthens or weakens, and when. The Verification tab shows each model’s actual intensity bias for this storm."

TEASER_THUMB = 'genesis_teaser.jpg'


def _write_teaser_thumb(docs_dir: str, src: str, width: int = 960) -> str | None:
    """總覽封面用的生成潛勢縮圖（JPEG，寬 960px）。來源圖沒變就不重寫；失敗回 None，封面退回用原圖。"""
    try:
        from PIL import Image  # type: ignore
        path = os.path.join(docs_dir, TEASER_THUMB)
        if not os.path.exists(src):                      # 清單裡存的是給網頁用的檔名，不含 docs/
            src = os.path.join(docs_dir, os.path.basename(src))
        if os.path.exists(path) and os.path.getmtime(path) >= os.path.getmtime(src):
            return TEASER_THUMB
        im = Image.open(src).convert('RGB')
        im.thumbnail((width, width * 4), Image.LANCZOS)
        im.save(path, 'JPEG', quality=82, optimize=True, progressive=True)
        return TEASER_THUMB
    except Exception as e:
        print(f"[HTML] 警告: 生成潛勢縮圖失敗，封面改用原圖: {e}")
        return None


def _write_share_image(docs_dir: str, lead: dict | None, updated: str, genesis_png: str | None) -> bool:
    """分享卡片圖：左邊文字（站名、颱風名、強度、更新時間），右邊最新的模式比較圖；
    沒有颱風時改放生成潛勢圖。兩者都沒有就不產生（網頁也不放 og:image）。"""
    from PIL import Image, ImageDraw  # type: ignore
    src = os.path.join(docs_dir, f"{lead['id']}_Model_Comparison.png") if lead else None
    if not (src and os.path.exists(src)):
        src = genesis_png if genesis_png and os.path.exists(genesis_png) else None
    if not src:
        return False
    W, H, LW = 1200, 630, 400
    card = Image.new('RGB', (W, H), 'white')
    card.paste(APP_BG, (0, 0, LW, H))
    m = Image.open(src).convert('RGB')
    scale = min((W - LW) / m.width, H / m.height)    # 整張圖放進右側，不裁切
    m = m.resize((round(m.width * scale), round(m.height * scale)), Image.LANCZOS)
    card.paste(m, (LW + (W - LW - m.width) // 2, (H - m.height) // 2))
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, 8, H], fill='#58b0e8')
    d.text((44, 48), "Pillar's\nTropical Cyclone\nForecast", font=_font(28), fill='#c9dbea', spacing=8)
    if lead:
        name = (lead['name'] or lead['id']).upper()
        size = 60 if len(name) <= 9 else 44
        d.text((44, 210), name, font=_font(size), fill='white')
        sub = lead['id'] + (f"  ·  {lead['wind']:.0f} kt" if lead.get('wind') is not None else '')
        d.text((44, 210 + size + 22), sub, font=_font(30, bold=False), fill='white')
        d.rounded_rectangle([44, 210 + size + 76, 44 + 150, 210 + size + 84], 4, fill=lead['color'])
    else:
        d.text((44, 210), 'Genesis\nOutlook', font=_font(56), fill='white', spacing=10)
    d.text((44, H - 84), 'Updated', font=_font(22, bold=False), fill='#8fa6ba')
    d.text((44, H - 56), updated, font=_font(26), fill='white')
    card.save(os.path.join(docs_dir, SHARE_IMAGE), optimize=True)
    return True


def _share_meta(lead: dict | None, track_ids: list, updated: str, has_image: bool, stamp: str) -> str:
    url = _site_url()
    if lead:
        name = (lead['name'] or lead['id']).upper()
        wind = f" {lead['wind']:.0f} kt" if lead.get('wind') is not None else ''
        others = f"（另有 {len(track_ids) - 1} 個系統）" if len(track_ids) > 1 else ''
        desc = f"{name}{wind}{others} · 更新 {updated} · AI 與物理模式系集路徑、侵襲機率、登陸臺灣機率"
    else:
        desc = f"目前沒有活躍颱風 · 西太平洋生成潛勢 · 更新 {updated}"
    title = f"{SITE_NAME} | {' / '.join(track_ids) or 'Forecast'}"
    tags = [
        f'<meta name="description" content="{_esc(desc)}">',
        f'<meta name="theme-color" content="{APP_BG}">',
        '<link rel="manifest" href="manifest.webmanifest">',
        '<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">',
        '<link rel="apple-touch-icon" href="apple-touch-icon.png">',
        '<meta name="apple-mobile-web-app-capable" content="yes">',
        '<meta name="mobile-web-app-capable" content="yes">',
        f'<meta name="apple-mobile-web-app-title" content="{_esc(SITE_SHORT_NAME)}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{_esc(SITE_NAME)}">',
        f'<meta property="og:title" content="{_esc(title)}">',
        f'<meta property="og:description" content="{_esc(desc)}">',
        f'<meta property="og:url" content="{_esc(url)}">',
        '<meta property="og:locale" content="zh_TW">',
    ]
    if has_image:
        # 每次更新換查詢字串，LINE／Facebook 才會重抓新圖，不沿用舊快取
        img = f"{url}{SHARE_IMAGE}?v={stamp}"
        tags += [f'<meta property="og:image" content="{_esc(img)}">',
                 '<meta property="og:image:width" content="1200">',
                 '<meta property="og:image:height" content="630">',
                 '<meta name="twitter:card" content="summary_large_image">',
                 f'<meta name="twitter:image" content="{_esc(img)}">']
    return '\n    '.join(tags)


def generate_forecast_html(storms: list[dict], output_path: str,
                           genesis_map_paths: list | None = None):
    """生成預報網站（多頁式：總覽／各颱風／生成潛勢／說明，以 hash 路由切換）。

    同一顆颱風若同時有 WN3-C / WN2-C r2 / WN2-C r1 / GENC 多種模式的預報，會合併成
    單一颱風頁：颱風字卡與 JTWC 官方預報圖僅顯示一次，Ensemble 路徑圖與動畫則
    透過分頁切換，避免同一顆颱風重複出現多張幾乎相同的卡片。

    genesis_map_paths 收 (模式名稱, 圖檔路徑) 的序列；為相容舊呼叫方式，也接受
    純路徑字串，此時退回以檔名判斷模式。
    """

    now_local = datetime.now().astimezone()
    update_time = now_local.strftime('%Y-%m-%d %H:%M:%S')
    updated_iso = now_local.isoformat(timespec='seconds')

    # 依 track_id 分組（保留原始出現順序），同一顆颱風的 WNC/GENC 併入同一組
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for storm in storms:
        if not isinstance(storm, dict):
            continue
        tid = storm.get('track_id', 'Unknown')
        if tid not in groups:
            groups[tid] = []
            order.append(tid)
        groups[tid].append(storm)
    track_ids = order

    # ── 整理每顆颱風的摘要資訊 ─────────────────────────────────────────
    infos: dict[str, dict] = {}
    for track_id in order:
        models = groups[track_id]
        # 摘要資訊優先採用有 JTWC 實時資料的那筆，否則採用第一筆
        rep = next(
            (m for m in models if isinstance(m.get('current_info'), dict) and m['current_info'].get('jtwc')),
            models[0]
        )
        current_info = rep.get('current_info', {}) if isinstance(rep, dict) else {}
        if not isinstance(current_info, dict):
            current_info = {}

        # 字卡、強度分級、儀表一律只用 JTWC 實際資料；JTWC 沒給的欄位顯示 N/A，
        # 不拿模式的初始值頂替（模式初始場不是觀測，放在「現況」欄位會誤導）
        jtwc_data = current_info.get('jtwc', {}) or {}
        wind = _num(jtwc_data.get('max_winds_kt'))
        curr_cat = ss_category(wind) if wind is not None else 'Unknown'
        if curr_cat not in CAT_COLOR_MAP:
            curr_cat = 'Unknown'

        jtwc_update = jtwc_data.get('update_time', '')
        infos[track_id] = {
            'id': track_id,
            'name': jtwc_data.get('name', '') or '',
            'cat': curr_cat,
            'color': CAT_COLOR_MAP[curr_cat],
            'text': CAT_TEXT_MAP.get(curr_cat, '#0D2033'),
            'wind': wind,
            'pressure': _num(jtwc_data.get('pressure_mb')),
            'pos': (f"{jtwc_data['latitude']}, {jtwc_data['longitude']}"
                    if jtwc_data.get('latitude') and jtwc_data.get('longitude') else 'N/A'),
            'time': _fmt_obs_time(jtwc_update) if jtwc_update else 'N/A',
            'models': [m.get('model', 'WN2-C r2') for m in models if isinstance(m, dict)],
            # 首頁颱風卡片列的模式：多算 1000 成員版（它沒有自己的動畫／路徑圖分頁，
            # 不能放進上面的 models，那份清單颱風頁拿去產生模式分頁）
            'tile_models': _place_1000(
                [m.get('model', 'WN2-C r2') for m in models if isinstance(m, dict)]
                + ([CLUSTER_LABEL] if any(isinstance(m, dict) and m.get('strike_1000_path')
                                          for m in models) else [])),
            # 3D 地球用：颱風位置只用 JTWC；路徑優先用 JTWC 官方預報，沒有才退回模式系集平均
            'lat': _coord(jtwc_data.get('latitude')),
            'lon': _coord(jtwc_data.get('longitude')),
            'jtwc_fc': jtwc_data.get('forecast_track') or [],
            'track': _jtwc_track(jtwc_data, wind) or _snap_track(
                _globe_track(models), _coord(jtwc_data.get('latitude')),
                _coord(jtwc_data.get('longitude')), wind),
        }

    def _title(info):
        return info['name'] or info['id']

    # 主視覺以最強的一顆為主角（風速未知的排最後）
    lead = max(infos.values(), key=lambda i: i['wind'] if i['wind'] is not None else -1) if infos else None

    # ── 西太平洋潛勢預報圖清單 ─────────────────────────────────────────
    _genesis_entries = []
    for _entry in list(genesis_map_paths or []):
        if isinstance(_entry, (tuple, list)) and len(_entry) == 2:
            _model_label, _gpath = _entry
        else:
            # 舊呼叫方式：只給路徑，退回用檔名判斷（WP_Genesis_Potential.png 無後綴
            # 者即現行主力模式 WN2-C r2）
            _gpath = _entry
            _stem = os.path.basename(str(_gpath)).upper()
            _model_label = next(
                (lbl for key, lbl in (("GENC", "GENC"), ("WNC3", "WN3-C"),
                                      ("WNC2-R1", "WN2-C r1"), ("WNC-R1", "WN2-C r1"))
                 if key in _stem),
                "WN2-C r2")
        if not (_gpath and os.path.exists(_gpath)):
            continue
        _genesis_entries.append((_model_label, os.path.basename(_gpath)))

    _genesis_entries = _place_1000(_genesis_entries, label=lambda e: e[0])

    # 路由順序同時決定導覽列排列與換頁動畫的方向（往右的頁面從右邊滑入）
    _archive = _load_archive(os.path.dirname(output_path) or '.')
    routes = ['overview'] + [f'storm/{tid}' for tid in order]
    if _genesis_entries:
        routes.append('genesis')
    if _archive:
        routes.append('archive')
    routes.append('about')

    active_models = set()
    for info in infos.values():
        active_models.update(info['models'])
    active_models.update(ENS_SYSTEM.get(lbl, lbl) for lbl, _ in _genesis_entries if lbl != CLUSTER_LABEL)
    # 1000 成員版沒有自己的 storm dict（產品掛在各颱風第一個模式上），另外判斷：
    # 有任一颱風的 1000 成員侵襲機率圖、或潛勢頁有路徑聚類圖，首頁就算它一個模式
    if (any(lbl == CLUSTER_LABEL for lbl, _ in _genesis_entries)
            or any(isinstance(s, dict) and s.get('strike_1000_path') for s in storms)):
        active_models.add(CLUSTER_LABEL)

    # ═════════════════════════════════════════════════════════════════
    #  總覽頁
    # ═════════════════════════════════════════════════════════════════
    if lead:
        hero_rgb = _hex_rgb(lead['color'], 0.35)
        hero_strength = min(1.0, max(0.15, ((lead['wind'] or 30) - 20) / 120))
        _wind = lambda i: f"{i['wind']:.0f} kt" if i['wind'] is not None else "— kt"
        hero_sub = (f'<p class="hero-sub" data-i18n="hero.live.sub" data-i18n-count="{len(infos)}"\n'
                    f'                   data-i18n-models="{len(active_models)}">{len(infos)} active system(s) · '
                    f'ensemble guidance from {len(active_models)} models, refreshed every 10–15 minutes.</p>')
        genesis_btn = ('<a class="btn-ghost" href="#/genesis" data-i18n="hero.cta.genesis">Genesis outlook</a>'
                       if _genesis_entries else '')
        if len(infos) == 1:
            hero_inner = f"""
                <div class="eyebrow"><span class="live-dot"></span><span data-i18n="hero.eyebrow.live">Now tracking</span></div>
                <h2 class="hero-title storm-name split" style="--glow:{lead['color']}">{_esc(_title(lead))}</h2>
                <p class="hero-lead">
                    <span class="cat-pill" style="background:{lead['color']};color:{lead['text']}">{lead['cat']}</span>
                    <span data-i18n="catname.{lead['cat']}">{lead['cat']}</span>
                    <span class="sep">·</span><span class="mono">{_wind(lead)}</span>
                    <span class="sep">·</span><span class="mono">{_esc(lead['pos'])}</span>
                </p>
                {hero_sub}
                <div class="hero-cta">
                    <a class="btn-primary" href="#/storm/{_esc(lead['id'])}"><span data-i18n="hero.cta.storm">Open forecast</span> <span aria-hidden="true">→</span></a>
                    {genesis_btn}
                </div>"""
        else:
            # 同時有好幾顆：標題放所有颱風的名字，底下每顆一列（強度、風速、位置），整列連到該颱風頁。
            # 依強度排，最強的在前（與 lead 相同）
            ranked = sorted(infos.values(), key=lambda i: i['wind'] if i['wind'] is not None else -1, reverse=True)
            rows = "".join(f"""
                    <li><a href="#/storm/{_esc(i['id'])}">
                        <span class="hs-name storm-name">{_esc(_title(i))}</span>
                        <span class="cat-pill" style="background:{i['color']};color:{i['text']}">{i['cat']}</span>
                        <span data-i18n="catname.{i['cat']}">{i['cat']}</span>
                        <span class="sep">·</span><span class="mono">{_wind(i)}</span>
                        <span class="sep">·</span><span class="mono">{_esc(i['pos'])}</span>
                        <span class="hs-go" aria-hidden="true">→</span>
                    </a></li>""" for i in ranked)
            hero_inner = f"""
                <div class="eyebrow"><span class="live-dot"></span><span data-i18n="hero.eyebrow.multi" data-i18n-count="{len(infos)}">Now tracking {len(infos)} storms</span></div>
                <h2 class="hero-title storm-name split" style="--glow:{lead['color']}">{' · '.join(_esc(_title(i)) for i in ranked)}</h2>
                <ul class="hero-storms">{rows}
                </ul>
                {hero_sub}
                {f'<div class="hero-cta">{genesis_btn}</div>' if genesis_btn else ''}"""
    else:
        hero_rgb = '143,211,255'
        hero_strength = 0.04
        hero_inner = f"""
                <div class="eyebrow"><span class="calm-dot"></span><span data-i18n="hero.eyebrow.quiet">Western Pacific · Monitoring</span></div>
                <h2 class="hero-title split" data-i18n="hero.quiet.title">All quiet in the Western Pacific</h2>
                <p class="hero-sub" data-i18n="hero.quiet.sub">No active tropical cyclones right now. The genesis outlook shows where ensemble members hint at something forming next.</p>
                <div class="hero-cta">
                    {'<a class="btn-primary" href="#/genesis"><span data-i18n="hero.cta.genesis">Genesis outlook</span> <span aria-hidden="true">→</span></a>' if _genesis_entries else ''}
                    <a class="btn-ghost" href="#/about" data-i18n="nav.about">About</a>
                </div>"""

    hero_html = f"""
        <div class="hero" style="--flow-rgb:{hero_rgb}">
            <canvas class="hero-canvas" id="hero-canvas" aria-hidden="true"></canvas>
            <div class="hero-eye" aria-hidden="true"></div>
            <div class="hero-inner">
                {hero_inner}
            </div>
            <div class="scroll-cue" aria-hidden="true"><span></span></div>
        </div>"""

    genesis_teaser = ""
    _n_genesis_models = len(_genesis_entries)      # 含 WN2-C 1000，與首頁的模式數一致
    if _genesis_entries:
        chips = "".join(f'<span class="mini-chip">{_esc(lbl)}</span>' for lbl, _ in _genesis_entries)
        # 總覽的封面只是縮圖：另存一張小的 JPEG（約 1/15 大小），不用載整張 2 MB 的潛勢圖
        _teaser_src = _write_teaser_thumb(os.path.dirname(output_path) or '.', _genesis_entries[0][1]) or _genesis_entries[0][1]
        genesis_teaser = f"""
            <div class="section-head reveal">
                <div><div class="kicker" data-i18n="sec.genesis.kicker">Outlook</div>
                <h3 data-i18n="sec.genesis">Genesis potential</h3></div>
            </div>
            <a class="genesis-teaser reveal" href="#/genesis">
                <div class="teaser-img"><img src="{_esc(_teaser_src)}" alt="" loading="lazy" decoding="async"></div>
                <div class="teaser-body">
                    <p data-i18n="genesis.teaser" data-i18n-n="{_n_genesis_models}">Where might the next storm form? Explore ensemble genesis signals from {_n_genesis_models} models.</p>
                    <div class="mini-chips">{chips}</div>
                    <span class="tile-cta" data-i18n="genesis.open">Explore outlook →</span>
                </div>
            </a>"""

    model_cards = "".join(f"""
                <div class="model-card reveal{' on' if name in active_models else ''}">
                    <div class="model-name">{_esc(name)}<span class="model-state" title=""></span></div>
                    <div class="model-org">{_esc(org)}</div>
                    <div class="model-desc">{_esc(desc)}</div>
                </div>""" for name, org, desc in KNOWN_MODELS)

    # 首頁只放主視覺（每顆颱風一列，整列連到颱風頁）與生成潛勢；以前的跑馬燈、標語與颱風卡片
    # 跟主視覺講的是同一件事，拿掉。沒有颱風時主視覺已經寫了「風平浪靜」，下面不再放空白卡
    overview_view = f"""
    <section class="view" data-view="overview" data-title-key="nav.overview">
        {hero_html}
        <div class="page">
            {genesis_teaser}
        </div>
    </section>"""

    # ═════════════════════════════════════════════════════════════════
    #  各颱風頁
    # ═════════════════════════════════════════════════════════════════
    storm_views = []
    for track_id in order:
        models = groups[track_id]
        info = infos[track_id]
        model_names = info['models']
        multi_model = len(models) > 1
        key_prefix = _esc(track_id)

        # 其他颱風的切換列（兩顆以上才顯示）
        switcher = ""
        if len(infos) > 1:
            links = "".join(
                f'<a class="switch-chip{" active" if o["id"] == track_id else ""}" href="#/storm/{_esc(o["id"])}">'
                f'<span class="nav-dot" style="--c:{o["color"]}"></span><span class="storm-name">{_esc(_title(o))}</span></a>'
                for o in infos.values())
            switcher = f'<div class="storm-switch reveal">{links}</div>'

        kt_txt = f"{info['wind']:.0f}" if info['wind'] is not None else ''
        stats = [
            ('stat.time', '⏱', 'Obs time', f'<span class="mono">{_esc(info["time"])}</span>'),
            ('stat.pos', '📍', 'Position', f'<span class="mono">{_esc(info["pos"])}</span>'),
        ]
        if info['pressure'] is not None:
            stats.append(('stat.pres', '🧭', 'Min pressure',
                          f'<span data-count="{info["pressure"]:.0f}">{info["pressure"]:.0f}</span><small>hPa</small>'))
        stats_html = "".join(f"""
                <div class="stat reveal">
                    <div class="stat-label"><span aria-hidden="true">{icon}</span> <span data-i18n="{key}">{label}</span></div>
                    <div class="stat-value">{val}</div>
                </div>""" for key, icon, label, val in stats)

        sections = []   # (目標 id, i18n key, 預設文字)

        # ── 模式比較圖（與模式無關，不參與分頁切換）
        cmp_html = ""
        _cmp = next((m.get('comparison_map_path') for m in models
                     if isinstance(m, dict) and m.get('comparison_map_path')), '')
        if _cmp and os.path.exists(_cmp):
            sec_id = f"sec-{key_prefix}-cmp"
            sections.append((sec_id, 'sub.cmp', 'Comparison'))
            cmp_html = f"""
            <div class="panel reveal" id="{sec_id}">
                <div class="panel-header">
                    <span class="panel-icon">📊</span>
                    <span data-i18n="panel.comparison">Multi-Model Comparison</span>
                </div>
                {_figure(os.path.basename(_cmp), f"{track_id} Multi-Model Comparison",
                         "this.closest('.panel').style.display='none';")}
                <p class="map-note" data-i18n="note.comparison">
                    Ensemble mean tracks and deterministic runs from every model on one map
                    &nbsp;·&nbsp; Hollow dots = 24-hr steps &nbsp;·&nbsp;
                    Parentheses in the legend give each model's initialization time (day/hour Z)
                </p>
            </div>"""

        # ── 動畫（依模式分頁切換；僅在該模式有幀資料時輸出）
        anim_panels = []
        for i, m in enumerate(models):
            model_name = m.get('model', 'WN2-C r2')
            storm_frames_dir = m.get('frames_dir', '')
            if not (storm_frames_dir and os.path.exists(storm_frames_dir)):
                continue
            frame_files = sorted([f for f in os.listdir(storm_frames_dir) if f.endswith(('.webp', '.png'))])
            if not frame_files:
                continue
            hide_attr = '' if i == 0 else ' style="display:none;"'
            anim_panels.append(f"""
                <div class="model-panel" data-track="{key_prefix}" data-model="{_esc(model_name)}"{hide_attr}>
                    {_player(f"{track_id}-{model_name}", storm_frames_dir, frame_files,
                             f"{model_name} · {track_id}", f"{model_name} animation frame")}
                </div>""")

        anim_html = ""
        if anim_panels:
            sec_id = f"sec-{key_prefix}-anim"
            sections.append((sec_id, 'sub.anim', 'Animation'))
            first_anim_model = next(
                (m.get('model', 'WN2-C r2') for m in models
                 if m.get('frames_dir') and os.path.exists(m.get('frames_dir'))), model_names[0])
            anim_html = f"""
            <div class="panel reveal" id="{sec_id}">
                <div class="panel-header">
                    <span class="panel-icon">🎬</span>
                    <span data-i18n="panel.anim.generic">Track Evolution Animation</span>{MT_SHOWN if multi_model else ''}
                    <span class="panel-aside kbd-hint" data-i18n="kbd.hint"><kbd>Space</kbd> play/pause &nbsp;<kbd>←</kbd><kbd>→</kbd> seek</span>
                </div>
                {_model_tabs(track_id, model_names) if multi_model else f'<div class="model-label">{_esc(first_anim_model)}</div>'}
                {"".join(anim_panels)}
            </div>"""

        # ── Ensemble 路徑圖（依模式分頁切換）+ JTWC 官方預報（每顆颱風僅一份）
        map_panels = []
        for i, m in enumerate(models):
            model_name = m.get('model', 'WN2-C r2')
            forecast_map_path = m.get('forecast_map_path', '') if isinstance(m, dict) else ''
            map_src = os.path.basename(forecast_map_path) if forecast_map_path else ''
            hide_attr = '' if i == 0 else ' style="display:none;"'
            # 前幾期的歷史圖：一排起報時間按鈕，點了換圖，方便和最新一期對照
            history = (m.get('forecast_map_history') or []) if isinstance(m, dict) else []
            run_row = ""
            if history and map_src and m.get('forecast_map_init'):
                def _run_lbl(iso):
                    return pd.Timestamp(iso).strftime('%m/%d %HZ')
                run_row = ('<div class="run-picks" role="group" aria-label="Init">'
                           f'<button type="button" class="run-btn active" data-src="{_esc(map_src)}">'
                           f'<span data-i18n="run.latest">Latest</span> {_run_lbl(m["forecast_map_init"])}</button>'
                           + "".join(f'<button type="button" class="run-btn" data-src="{_esc(os.path.basename(hp))}">'
                                     f'{_run_lbl(iso)}</button>' for iso, hp in history)
                           + '</div>')
            map_panels.append(f"""
                <div class="model-panel" data-track="{key_prefix}" data-model="{_esc(model_name)}"{hide_attr}>
                    {run_row}
                    {_figure(map_src, f"{track_id} {model_name} Forecast Map")}
                    <p class="map-note" data-i18n="note.ensemble" data-i18n-model="{_esc(model_name)}">
                        {_esc(model_name)} &nbsp;·&nbsp; Colored lines = ensemble members (color = intensity) &nbsp;·&nbsp;
                        Navy line = ensemble mean &nbsp;·&nbsp; Cyclone symbol = initial position
                    </p>
                </div>""")

        sec_id = f"sec-{key_prefix}-maps"
        sections.append((sec_id, 'sub.maps', 'Ensemble & JTWC'))
        maps_html = f"""
            <div class="panel reveal" id="{sec_id}">
                    <div class="panel-header">
                        <span class="panel-icon">🗺</span>
                        <span data-i18n="panel.ensemble">Ensemble Track Forecast</span>{MT_SHOWN if multi_model else ''}
                    </div>
                    {_model_tabs(track_id, model_names) if multi_model else ''}
                    {"".join(map_panels)}
            </div>"""
        jtwc_html = f"""
            <div class="panel reveal" id="sec-{key_prefix}-jtwc">
                    <div class="panel-header">
                        <span class="panel-icon">🛰</span>
                        <span data-i18n="panel.jtwc">JTWC Official Forecast</span>
                    </div>
                    {_figure(f"jtwc_{track_id}.gif", "JTWC Forecast", "this.closest('.panel').style.display='none';")}
                    <p class="jtwc-src" data-i18n="note.jtwc">Source: Joint Typhoon Warning Center (JTWC) — U.S. Navy &amp; Air Force</p>
            </div>"""

        # ── 侵襲機率、強度預報（每模式一張，另加 1000 成員）
        strike_html = plume_html = ""
        strike_items = _model_images(models, 'strike_map_path', 'strike_1000_path', label_key='ens_name')
        if strike_items:
            sec_id = f"sec-{key_prefix}-strike"
            sections.append((sec_id, 'sub.strike', 'Strike Prob.'))
            strike_html = _tabbed_image_panel(
                sec_id, f"{key_prefix}-strike", '🎯', 'panel.strike', 'Strike Probability',
                strike_items, 'note.strike',
                'Share of ensemble members whose track passes within 1° (~111 km) of each 0.1° grid point '
                'at any time in the forecast &nbsp;·&nbsp; Intensity is not considered',
                f"{track_id} Strike Probability")
        extra_html = ""
        extra_items = next((m['strike_1000_extra'] for m in models
                            if isinstance(m, dict) and m.get('strike_1000_extra')), [])
        extra_items = [(lbl, p) for lbl, p in extra_items if p and os.path.exists(p)]
        if extra_items:
            sec_id = f"sec-{key_prefix}-strikex"
            sections.append((sec_id, 'sub.strikex', 'By Period'))
            extra_html = _tabbed_image_panel(
                sec_id, f"{key_prefix}-strikex", '⏱', 'panel.strikex',
                f'{CLUSTER_LABEL} Strike Probability by Period &amp; 34-kt Wind',
                extra_items, 'note.strikex',
                'Same 1° rule split into forecast periods &nbsp;·&nbsp; 34 kt = inside the '
                'forecast 34-kt wind radii at any time &nbsp;·&nbsp; 1000 members',
                f"{track_id} {CLUSTER_LABEL} Strike Probability")
        official_html = ""
        _off = next((m.get('official') for m in models if isinstance(m, dict) and m.get('official')), None)
        if _off and os.path.exists(_off['path']):
            sec_id = f"sec-{key_prefix}-official"
            sections.append((sec_id, 'sub.official', 'Official'))
            fcs = _off['forecasts']
            hours = [h for h in OFFICIAL_TABLE_H if any(p['h'] == h for f in fcs for p in f['points'])]
            def _cell(f, h):
                p = next((q for q in f['points'] if q['h'] == h), None)
                if not p:
                    return '<td class="c-nil">—</td>'
                kt = f"{p['kt']:.0f} kt" if p.get('kt') else '–'
                return (f'<td class="c-off">{abs(p["lat"]):.1f}°{"N" if p["lat"] >= 0 else "S"} '
                        f'{p["lon"] % 360:.1f}°E<span class="eta">{kt}</span></td>')
            head = ''.join(f'<th style="color:{OFFICIAL_COLORS.get(f["agency"], "inherit")}">{f["agency"]}'
                           f'<span class="eta">{_esc(f["issue"][5:13].replace("-", "/").replace("T", " ")) + ":00" if f.get("issue") else ""}</span></th>'
                           for f in fcs)
            rows = ''.join(f'<tr><td class="c-name">{"<span data-i18n=\"off.now\">Now</span>" if h == 0 else f"+{h} h"}</td>'
                           f'{"".join(_cell(f, h) for f in fcs)}</tr>' for h in hours)
            official_html = f"""
            <div class="panel reveal" id="{sec_id}">
                <div class="panel-header">
                    <span class="panel-icon">🏛️</span>
                    <span data-i18n="panel.official">Official Forecasts Compared</span>
                </div>
                {_figure(os.path.basename(_off['path']), f"{track_id} Official Forecasts")}
                <div class="city-table-wrap"><table class="city-table off-table">
                    <caption class="sr-only" data-i18n="cap.official">Official forecasts by agency and forecast hour</caption>
                    <thead><tr><th data-i18n="off.hour">Hour</th>{head}</tr></thead><tbody>{rows}</tbody>
                </table></div>
                <p class="map-note" data-i18n="note.official">JTWC (US), JMA (Japan) and CWA (Taiwan) official tracks &nbsp;·&nbsp; JTWC reports 1-minute winds, JMA and CWA 10-minute winds, so JTWC numbers run higher for the same storm &nbsp;·&nbsp; Time under each agency = forecast base time (UTC) &nbsp;·&nbsp; Map labels = valid time, day/hour UTC (e.g. 23/12Z = 23rd 12:00 UTC = 20:00 Taiwan time)</p>
            </div>"""

        sat_html = ""
        _sat = next((m.get('satellite_maps') for m in models
                     if isinstance(m, dict) and m.get('satellite_maps')), None)
        sat_panels = []
        for lbl, d in (_sat or []):
            files = sorted(f for f in os.listdir(d) if f.endswith('.webp')) if os.path.isdir(d) else []
            if not files:
                continue
            # 一開始顯示最新一幀，播放時從 3 小時前開始輪播
            sat_panels.append(f"""
                <div class="model-panel" data-track="{key_prefix}-sat" data-model="{_esc(lbl)}"{'' if not sat_panels else ' style="display:none;"'}>
                    {_player(f"{track_id}-sat-{lbl}", d, files, f"{track_id} Satellite · {lbl}",
                             f"{track_id} satellite image", start=len(files) - 1)}
                </div>""")
        if sat_panels:
            sec_id = f"sec-{key_prefix}-sat"
            sections.append((sec_id, 'sub.sat', 'Satellite'))
            sat_labels = [lbl for lbl, d in _sat if os.path.isdir(d)
                          and any(f.endswith('.webp') for f in os.listdir(d))]
            sat_html = f"""
            <div class="panel reveal" id="{sec_id}">
                <div class="panel-header">
                    <span class="panel-icon">🛰️</span>
                    <span data-i18n="panel.sat">Satellite Loop (last 3 hours)</span>
                </div>
                {_model_tabs(f"{key_prefix}-sat", sat_labels) if len(sat_labels) > 1 else f'<div class="model-label">{_esc(sat_labels[0])}</div>'}
                {"".join(sat_panels)}
                <p class="map-note" data-i18n="note.sat">Himawari-9 infrared (band 13, 10.4 µm) for the last 3 hours, one frame every 10 minutes, centered on the storm; it opens on the latest frame &nbsp;·&nbsp; Colors show cloud-top temperature: the colder the top, the taller the cloud and the stronger the convection; a warm dot ringed by the coldest colors is the eye and eyewall &nbsp;·&nbsp; Centred on the latest JTWC position (warnings come every 6 h, so the storm may have moved a little since); the track and JTWC forecast are on the ocean heat content map below &nbsp;·&nbsp; Raw data from the NOAA/JMA copy on AWS, observation time in the title of each frame</p>
            </div>"""

        ohc_html = ""
        _ohc = next((m.get('ohc_path') for m in models if isinstance(m, dict) and m.get('ohc_path')), None)
        _ohc_tr = next((m.get('ohc_track_path') for m in models if isinstance(m, dict) and m.get('ohc_track_path')), None)
        _ohc_tr_html = ''
        if _ohc_tr and os.path.exists(_ohc_tr):
            _ohc_tr_html = (f'<h4 class="sub-head" data-i18n="panel.ohctrack">Ocean Heat Content along the JTWC Track</h4>'
                            + _figure(os.path.basename(_ohc_tr), f"{track_id} Ocean Heat Content along the JTWC Track")
                            + f'<p class="map-note" data-i18n="note.ohctrack">{NOTE_OHCTRACK}</p>')
        if _ohc and os.path.exists(_ohc):
            sec_id = f"sec-{key_prefix}-ohc"
            sections.append((sec_id, 'sub.ohc', 'Ocean heat'))
            ohc_html = f"""
            <div class="panel reveal" id="{sec_id}">
                <div class="panel-header">
                    <span class="panel-icon">🌊</span>
                    <span data-i18n="panel.ohc">Ocean Heat Content</span>
                </div>
                {_figure(os.path.basename(_ohc), f"{track_id} Ocean Heat Content")}
                <p class="map-note" data-i18n="note.ohc">Tropical cyclone heat potential: heat stored above 26 °C between the sea surface and the 26 °C isotherm (kJ/cm²), computed from the latest daily CMEMS (Copernicus Marine) 1/12° ocean analysis, or HYCOM (US Navy) as a backup &nbsp;·&nbsp; A thick warm layer keeps the water under a typhoon warm even when it stirs the ocean, which favors strengthening; about 50 kJ/cm² (yellow and warmer) is a common threshold &nbsp;·&nbsp; Black = water colder than 26 °C or land &nbsp;·&nbsp; Dot = current JTWC position, solid line = track so far, dashed = JTWC forecast (dots every 24 h)</p>
                {_ohc_tr_html}
            </div>"""

        shear_html = ""
        _shear = next((m.get('shear_path') for m in models if isinstance(m, dict) and m.get('shear_path')), None)
        if _shear and os.path.exists(_shear):
            sec_id = f"sec-{key_prefix}-shear"
            sections.append((sec_id, 'sub.shear', 'Shear'))
            shear_html = f"""
            <div class="panel reveal" id="{sec_id}">
                <div class="panel-header">
                    <span class="panel-icon">🌀</span>
                    <span data-i18n="panel.shear">Vertical Wind Shear along the AIFS Track</span>
                </div>
                {_figure(os.path.basename(_shear), f"{track_id} Vertical Wind Shear")}
                <p class="map-note" data-i18n="note.shear">Difference between the 200 hPa and 850 hPa winds, averaged 200–800 km from the centre, every 6 h along the AIFS-single (deterministic) forecast track — winds and track come from the same AIFS run &nbsp;·&nbsp; Strong shear tilts the storm's upper and lower circulation apart and usually stops it strengthening: below 10 kt is low, 10–20 kt moderate, above 20 kt high &nbsp;·&nbsp; Arrows = direction the shear points (from the low-level wind toward the upper-level wind); the storm's heaviest rain and convection tend to sit downshear-left &nbsp;·&nbsp; Data: ECMWF Open Data</p>
            </div>"""

        steer_html = ""
        _steer = next((m.get('steering_maps') for m in models
                       if isinstance(m, dict) and m.get('steering_maps')), None)
        steer_items = [(lbl, p) for lbl, p in (_steer or []) if p and os.path.exists(p)]
        if steer_items:
            sec_id = f"sec-{key_prefix}-steer"
            sections.append((sec_id, 'sub.steer', 'Steering'))
            steer_html = _tabbed_image_panel(
                sec_id, f"{key_prefix}-steer", '🌬️', 'panel.steer', 'Steering Flow (500 hPa)',
                steer_items, 'note.steer',
                'AIFS-single 500 hPa streamlines, wind speed (shading) and height (gray, every 30 gpm) '
                '&nbsp;·&nbsp; Red line = 5880 gpm, the usual edge of the subtropical high: typhoons tend to move '
                'around it, west while the high extends west, turning north where it ends &nbsp;·&nbsp; '
                'Navy line and dot = AIFS-single track and the storm\'s position at that time',
                f"{track_id} Steering Flow")
        score_html = ""
        _card_m = next((m for m in models if isinstance(m, dict) and 'scorecard' in m), None)
        if _card_m is not None:
            sec_id = f"sec-{key_prefix}-score"
            sections.append((sec_id, 'sub.score', 'Verification'))
            order = [x for m in models if isinstance(m, dict)
                     for x in (m.get('ens_name') or m.get('model'), m.get('det_name')) if x]
            det_names = {m.get('det_name') for m in models if isinstance(m, dict) and m.get('det_name')}
            # 「這個颱風」排前面（預設），「所有颱風」在後；各自再分同質／全部樣本
            body = _score_block(f"{key_prefix}-score",
                                [('storm', _card_m.get('scorecard')), ('allst', _card_m.get('scorecard_all'))],
                                order, det_names)
            if not body:
                body = ('<p class="map-note" data-i18n="score.pending">Collecting data — the first '
                        'errors appear once a forecast has been out for 24 hours.</p>')
            score_html = f"""
            <div class="panel reveal" id="{sec_id}">
                <div class="panel-header">
                    <span class="panel-icon">🏁</span>
                    <span data-i18n="panel.score">Track Error by Model</span>
                </div>
                {body}
                <p class="map-note" data-i18n="note.score">
                    Mean distance (km) between each forecast position and the JTWC warning position at the same time
                    &nbsp;·&nbsp; Homogeneous = only forecasts every model has for the same storm, init and hour (fair comparison)
                    &nbsp;·&nbsp; Colors compare models per hour: green = best, red = worst; ★ = best, +x% = behind the best
                    &nbsp;·&nbsp; Faded = fewer than 3 forecasts, not ranked
                </p>
            </div>"""

        tmap_html = ""
        _tj = next((m.get('tracks_json') for m in models
                    if isinstance(m, dict) and m.get('tracks_json')), '')
        if _tj and os.path.exists(_tj):
            sec_id = f"sec-{key_prefix}-tmap"
            sections.append((sec_id, 'sub.tmap', 'Map'))
            tmap_html = f"""
            <div class="panel reveal" id="{sec_id}">
                <div class="panel-header">
                    <span class="panel-icon">🧭</span>
                    <span data-i18n="panel.tmap">Interactive Track Map</span>
                </div>
                <div class="track-map" data-src="{_esc(os.path.basename(_tj))}">
                    <div class="tm-controls">
                        <button type="button" class="ghost-btn tm-cmp-btn" aria-pressed="false">{ICONS["compare"]}<span data-i18n="tmap.compare">Compare models</span></button>
                        <select class="tm-model" aria-label="Model"></select>
                        <span class="tm-chips"></span>
                        <span class="tm-init"><span data-i18n="tmap.init">Init</span> <b class="tm-init-val"></b></span>
                        <label><input type="checkbox" class="tm-members" checked> <span data-i18n="tmap.members">Members</span></label>
                        <label><input type="checkbox" class="tm-mean" checked> <span data-i18n="tmap.mean">Mean</span></label>
                        <label class="tm-det-wrap"><input type="checkbox" class="tm-det" checked> <span data-i18n="tmap.det">Deterministic</span></label>
                    </div>
                    <div class="run-picks tm-runs" role="group" aria-label="Init"></div>
                    <div class="tm-map"></div>
                </div>
                <p class="map-note" data-i18n="note.tmap">
                    Drag / scroll to zoom &nbsp;·&nbsp; Hover a line for member, time (UTC) and wind &nbsp;·&nbsp;
                    Member colors = intensity &nbsp;·&nbsp; Compare: pick any models, one color each, dashed = deterministic &nbsp;·&nbsp; Init buttons switch every model to the same run
                </p>
            </div>"""

        trend_html = ""
        trend_items = []
        for m in models:
            if not isinstance(m, dict):
                continue
            for lbl, p in ((m.get('ens_name') or m.get('model'), m.get('trend_path')),
                           (m.get('det_name'), m.get('det_trend_path'))):
                if lbl and p and os.path.exists(p):
                    trend_items.append((lbl, p))
        if trend_items:
            sec_id = f"sec-{key_prefix}-trend"
            sections.append((sec_id, 'sub.trend', 'Trend'))
            trend_html = _tabbed_image_panel(
                sec_id, f"{key_prefix}-trend", '🧭', 'panel.trend', 'Track Trend',
                trend_items, 'note.trend',
                'Ensemble mean tracks from every cycle since the storm first appeared, older = lighter '
                '&nbsp;·&nbsp; Shows which way successive forecasts have shifted &nbsp;·&nbsp; AIFS-single / ECMWF HRES / AIGFS / GFS tabs = deterministic run (amber)',
                f"{track_id} Track Trend")
        plume_items = _model_images(models, 'plume_path', 'plume_1000_path')
        if plume_items:
            plume_html = (f'<div class="callout"><span class="callout-icon" aria-hidden="true">⚠️</span>'
                          f'<p data-i18n="caveat.intensity">{CAVEAT_INTENSITY}</p></div>')
            sec_id = f"sec-{key_prefix}-plume"
            sections.append((sec_id, 'sub.plume', 'Intensity'))
            plume_html += _tabbed_image_panel(
                sec_id, f"{key_prefix}-plume", '📈', 'panel.plume', 'Intensity Forecast',
                plume_items, 'note.plume',
                'Thin lines = members &nbsp;·&nbsp; Navy line = median &nbsp;·&nbsp; Band = 10–90% '
                '&nbsp;·&nbsp; RI = intensifying ≥ 30 kt within 24 h &nbsp;·&nbsp; Amber line = deterministic run (AIFS / ECMWF / AIGFS / GFS)',
                f"{track_id} Intensity Forecast")

        # ── 城市侵襲機率表（欄＝各模式＋1000 成員）
        cities_html = ""
        city_cols = []
        for m in models:
            if not isinstance(m, dict):
                continue
            if m.get('city_strike'):
                city_cols.append((m.get('ens_name') or m.get('model', 'WN2-C r2'), m['city_strike']))
            if m.get('city_strike_det') and m.get('det_name'):
                city_cols.append((m['det_name'], m['city_strike_det'], True))
        city_cols += [(CLUSTER_LABEL, m['city_strike_1000'])
                      for m in models if isinstance(m, dict) and m.get('city_strike_1000')][:1]
        city_cols = _place_1000(city_cols, label=lambda c: c[0])
        table = _city_table(city_cols) if city_cols else ''
        if table:
            sec_id = f"sec-{key_prefix}-cities"
            sections.append((sec_id, 'sub.cities', 'Cities'))
            cities_html = f"""
            <div class="panel reveal" id="{sec_id}">
                <div class="panel-header">
                    <span class="panel-icon">📍</span>
                    <span data-i18n="panel.cities">Taiwan Landfall &amp; City Strike Probability</span>
                </div>
                {table}
                <p class="map-note" data-i18n="note.cities">
                    Share of members whose track passes within 1° (~111 km) of the city &nbsp;·&nbsp;
                    Time below = median first arrival among those members (UTC) &nbsp;·&nbsp;
                    Taiwan cities always shown; others only when any model reaches 1%
                </p>
            </div>"""

        summary_html = _storm_summary(info, city_cols)

        # ── 依讀者的問題分頁：概況／路徑／侵襲／強度／校驗，每頁單欄排列
        panes = [
            ('now', 'tab.now', 'Summary',
             f"{sat_html}{ohc_html}{shear_html}{steer_html}{jtwc_html}{official_html}{cities_html}"),
            ('track', 'tab.track', 'Track', f"{cmp_html}{maps_html}{anim_html}{tmap_html}{trend_html}"),
            ('strike', 'tab.strike', 'Strike', f"{strike_html}{extra_html}"),
            ('intensity', 'tab.int', 'Intensity', plume_html),
            ('score', 'tab.score', 'Verification', score_html),
        ]
        panes = [pn for pn in panes if pn[3].strip()]

        # 圖說收進「怎麼看這張圖」，需要時再展開
        def _fold_notes(html):
            return re.sub(r'(<p class="map-note"[^>]*data-i18n="note\.[^"]+"[^>]*>.*?</p>)',
                          r'<details class="note-fold"><summary data-i18n="note.how">How to read this</summary>\1</details>',
                          html, flags=re.S)

        tab_btns = "".join(
            f'<button class="model-tab-btn storm-tab{" active" if i == 0 else ""}" role="tab" aria-selected="{"true" if i == 0 else "false"}" '
            f'data-track="{key_prefix}-tabs" data-model="{pid}" data-i18n="{k}">{txt}</button>'
            for i, (pid, k, txt, _) in enumerate(panes))
        hide = ' style="display:none;"'
        pane_html = "".join(
            f'<div class="model-panel tab-pane" data-track="{key_prefix}-tabs" data-model="{pid}" role="tabpanel"'
            f'{"" if i == 0 else hide}>{_fold_notes(body)}</div>'
            for i, (pid, _, _, body) in enumerate(panes))

        # 整頁一個模式選單：選項＝各圖分頁裡出現過的模式（同一模式的系集／決定性算一個）
        pick_labels = list(model_names)
        for items in (strike_items, plume_items, trend_items):
            pick_labels += [lbl for lbl, _ in items]
        seen, picks = set(), []
        for lbl in pick_labels:
            g = _model_group(lbl)
            if g not in seen:
                seen.add(g)
                picks.append(lbl)
        picks = _place_1000(picks)
        model_pick = ''
        if len(picks) > 1:
            opts = "".join(f'<option value="{_esc(x)}">{_esc(x)}</option>' for x in picks)
            model_pick = (f'<label class="model-pick"><span data-i18n="mp.label">Model</span>'
                          f'<select class="model-select" aria-label="Model">{opts}</select></label>')
        storm_bar = (f'<div class="storm-bar"><div class="seg model-tabs storm-tabs" role="tablist">'
                     f'<span class="seg-ind"></span>{tab_btns}</div>{model_pick}</div>')

        storm_views.append(f"""
    <section class="view" data-view="storm/{key_prefix}" data-title="{_esc(_title(info))}">
        <div class="page">
            {switcher}
            <div class="storm-hero reveal" style="--cat:{info['color']}">
                <div class="swirl" aria-hidden="true"></div>
                <div class="storm-hero-main">
                    <div class="storm-badges">
                        <span class="badge-cat" style="background:{info['color']};color:{info['text']};"><span data-i18n="catname.{info['cat']}">{info['cat']}</span></span>
                        <span class="badge-id">{_esc(track_id)}</span>
                    </div>
                    <h2 class="storm-title storm-name">{_esc(_title(info))}</h2>
                    {summary_html}
                </div>
                <div class="gauge gauge-lg" data-kt="{kt_txt}" style="--cat:{info['color']}"></div>
            </div>
            <div class="stat-grid">{stats_html}</div>
            <div class="storm-bar-anchor"></div>
            {storm_bar}
            {pane_html}
        </div>
    </section>""")

    # ═════════════════════════════════════════════════════════════════
    #  生成潛勢頁
    # ═════════════════════════════════════════════════════════════════
    def _genesis_note(label):
        src = _esc(_genesis_source(label))
        if label == CLUSTER_LABEL:
            return (f'<p class="map-note" style="margin-top:0;" data-i18n="note.cluster" data-i18n-source="{src}">'
                    'Each line is one of 1000 ensemble members. Named storms are grouped by track ID; '
                    'unnamed tracks are clustered by genesis time and position. Percentages = share of '
                    f'members that produce the system; gray = sparse tracks. Data sourced from {src}.</p>')
        return (f'<p class="map-note" style="margin-top:0;" data-i18n="note.genesis" data-i18n-source="{src}">'
                'Circles = ensemble members at each 6-hr step, colored by minimum sea level '
                'pressure. Gray lines = individual ensemble tracks (up to 360 h; GEFS 120 h). '
                f'Data sourced from {src}.</p>')

    genesis_view = ""
    if _genesis_entries:
        multi_genesis = len(_genesis_entries) > 1
        labels = [lbl for lbl, _ in _genesis_entries]

        genesis_panels_html = "".join(f"""
                <div class="model-panel" data-track="genesis" data-model="{_esc(label)}"{'' if i == 0 else ' style="display:none;"'}>
                    {_figure(img, f"Western Pacific Tropical Cyclone Genesis Potential ({label})",
                             "const p=this.closest('.model-panel'); p.dataset.broken='true'; p.style.display='none';",
                             "genesis-map-wrapper")}
                    <div class="genesis-legend">
                        {_genesis_note(label)}
                    </div>
                </div>""" for i, (label, img) in enumerate(_genesis_entries))

        compare_html = ""
        compare_btn = ""
        # 聚類圖與潛勢圖不是同一種圖，疊在一起比沒有意義，比較器只收潛勢圖
        _cmp_entries = [e for e in _genesis_entries if e[0] != CLUSTER_LABEL]
        if len(_cmp_entries) > 1:
            opts_a = "".join(f'<option value="{_esc(img)}"{" selected" if i == 0 else ""}>{_esc(lbl)}</option>'
                             for i, (lbl, img) in enumerate(_cmp_entries))
            opts_b = "".join(f'<option value="{_esc(img)}"{" selected" if i == 1 else ""}>{_esc(lbl)}</option>'
                             for i, (lbl, img) in enumerate(_cmp_entries))
            compare_btn = (f'<button class="ghost-btn" id="gen-compare-btn" aria-pressed="false">{ICONS["compare"]}'
                           f'<span data-i18n="genesis.compare">Compare models</span></button>')
            compare_html = f"""
                <div class="compare" id="gen-compare" hidden>
                    <div class="compare-pickers">
                        <label><span class="pick-dot a"></span><select id="cmp-a" aria-label="Left model">{opts_a}</select></label>
                        <span class="compare-hint" data-i18n="genesis.compare.hint">Drag the divider to compare two models</span>
                        <label><select id="cmp-b" aria-label="Right model">{opts_b}</select><span class="pick-dot b"></span></label>
                    </div>
                    <div class="cmp-stage" tabindex="0" role="slider" aria-label="Comparison divider" aria-valuemin="0" aria-valuemax="100" aria-valuenow="50">
                        <img class="cmp-base" src="{_esc(_cmp_entries[1][1])}" alt="" draggable="false" loading="lazy" decoding="async">
                        <div class="cmp-top"><img src="{_esc(_cmp_entries[0][1])}" alt="" draggable="false" loading="lazy" decoding="async"></div>
                        <div class="cmp-handle"><span>{ICONS['compare']}</span></div>
                    </div>
                </div>"""

        genesis_view = f"""
    <section class="view" data-view="genesis" data-title-key="nav.genesis">
        <div class="page">
            <div class="page-head reveal">
                <div class="kicker" data-i18n="sec.genesis.kicker">Outlook</div>
                <h2 class="page-title" data-i18n="panel.genesis">Western Pacific Tropical Cyclone Genesis Potential — Ensemble Overview</h2>
            </div>
            <div class="panel genesis-panel reveal">
                <div class="genesis-toolbar">
                    {_model_tabs('genesis', labels, 'genesis-tabs') if multi_genesis else ''}
                    {compare_btn}
                </div>
                <div class="genesis-single">{genesis_panels_html}</div>
                {compare_html}
            </div>
        </div>
    </section>"""

    # ═════════════════════════════════════════════════════════════════
    #  說明頁
    # ═════════════════════════════════════════════════════════════════
    def _range_txt(lo, hi, idx):
        if idx == 0:
            return f"≤ {hi - 1} kt"
        if idx == len(CAT_RANGES) - 1:
            return f"≥ {lo} kt"
        return f"{lo}–{hi - 1} kt"

    scale_rows = "".join(f"""
                    <div class="scale-row reveal">
                        <span class="badge-cat" style="background:{CAT_COLOR_MAP[c]};color:{CAT_TEXT_MAP[c]}">{c}</span>
                        <span data-i18n="catname.{c}">{c}</span>
                        <span class="mono">{_range_txt(lo, hi, i)}</span>
                    </div>""" for i, (c, lo, hi) in enumerate(CAT_RANGES))

    archive_view = ""
    if _archive:
        def _md(iso):
            return f"{iso[5:7]}/{iso[8:10]}" if iso else '?'
        cards = []
        for e in _archive:
            cat = ss_category(e['peak']) if e['peak'] is not None else 'Unknown'
            live = '<span class="arch-live" data-i18n="arch.active">Active</span>' if e['active'] else ''
            cards.append(
                f'<button type="button" class="arch-card" data-arch="{_esc(e["id"])}" style="--cat:{CAT_COLOR_MAP[cat]}">'
                f'<span class="arch-top"><span class="arch-name storm-name">{_esc(e["name"] or e["id"])}</span>{live}</span>'
                f'<span class="arch-meta mono">{_esc(e["id"])} · {_md(e["first"])}–{_md(e["last"])}</span>'
                f'<span class="arch-meta"><span class="badge-cat" style="background:{CAT_COLOR_MAP[cat]};color:{CAT_TEXT_MAP[cat]}">{cat}</span>'
                f' <span class="mono">{e["peak"] if e["peak"] is not None else "–"} kt</span>'
                f' · <span data-i18n="arch.inits" data-i18n-n="{e["n"]}">{e["n"]} forecasts</span></span>'
                f'</button>')
        archive_view = f"""
    <section class="view" data-view="archive" data-title-key="nav.archive">
        <div class="page">
            <div class="page-head reveal">
                <div class="kicker" data-i18n="arch.kicker">Past storms</div>
                <h2 class="page-title" data-i18n="arch.title">Storm Archive</h2>
                <p class="page-lead" data-i18n="arch.lead">Every storm this site has followed: the real JTWC track, how each model's forecasts changed run by run, and how far off they turned out to be.</p>
            </div>
            <div class="arch-grid reveal">{"".join(cards)}</div>
            <div class="panel arch-detail" hidden>
                <div class="panel-header"><span class="panel-icon">🗂️</span><span class="arch-title"></span></div>
                <div class="tm-controls arch-controls">
                    <select class="arch-model" aria-label="Model"></select>
                    <span class="tm-init"><span data-i18n="arch.init">Init</span> <b class="arch-init-val"></b></span>
                    <input type="range" class="arch-slider" min="0" max="0" value="0" aria-label="Init">
                    <label><input type="checkbox" class="arch-all" checked> <span data-i18n="arch.all">Show every run</span></label>
                </div>
                <div class="arch-map"></div>
                <p class="map-note" data-i18n="note.arch.map">Thick colored line = the real JTWC track, colored by intensity &nbsp;·&nbsp; Orange = the selected run's ensemble-mean (or deterministic) forecast, with a dot every 24 h &nbsp;·&nbsp; Thin lines = all other runs of the same model, light = older, dark = newer &nbsp;·&nbsp; Drag the slider to step through the runs</p>
                <div class="arch-trend"></div>
                <div class="arch-score"></div>
            </div>
        </div>
    </section>"""

    about_view = f"""
    <section class="view" data-view="about" data-title-key="nav.about">
        <div class="page">
            <div class="page-head reveal">
                <div class="kicker" data-i18n="about.kicker">About</div>
                <h2 class="page-title" data-i18n="about.title">How to read this site</h2>
                <p class="page-lead" data-i18n="about.intro">This site gathers AI and physics-based ensemble forecasts for Western Pacific tropical cyclones and redraws them in one common style every 10–15 minutes, next to the official forecasts from JTWC, JMA (Japan) and CWA (Taiwan). Each storm page has five tabs: Summary (a 3-hour Himawari-9 infrared satellite loop, the ocean heat content under the storm, the vertical wind shear along the AIFS track, the 500 hPa steering flow, the JTWC forecast, the official forecasts side by side, and Taiwan landfall and city strike probabilities), Track (model comparison, ensemble maps, animation, an interactive map and track trend), Strike (strike probabilities by area, by period and for 34-kt winds), Intensity (intensity forecast) and Verification (track, along-/cross-track and intensity errors). One model menu at the top switches every chart to the same model. The Archive keeps every storm after it is gone, with its real track and how the forecasts did.</p>
            </div>
            <div class="about-grid">
                <div class="panel reveal about-scale">
                    <div class="panel-header"><span class="panel-icon">🎨</span><span data-i18n="about.scale">Intensity categories</span></div>
                    <div class="scale-table">{scale_rows}</div>
                </div>
                <div class="panel reveal about-read">
                    <div class="panel-header"><span class="panel-icon">🧭</span><span data-i18n="about.reading">Reading the maps</span></div>
                    <div class="read-list">
                        <div><h4 data-i18n="panel.sat">Satellite Loop (last 3 hours)</h4><p class="map-note" data-i18n="note.sat"></p></div>
                        <div><h4 data-i18n="panel.ohc">Ocean Heat Content</h4><p class="map-note" data-i18n="note.ohc"></p></div>
                        <div><h4 data-i18n="panel.ohctrack">Ocean Heat Content along the JTWC Track</h4><p class="map-note" data-i18n="note.ohctrack"></p></div>
                        <div><h4 data-i18n="panel.shear">Vertical Wind Shear along the AIFS Track</h4><p class="map-note" data-i18n="note.shear"></p></div>
                        <div><h4 data-i18n="panel.steer">Steering Flow (500 hPa)</h4><p class="map-note" data-i18n="note.steer"></p></div>
                                                <div><h4 data-i18n="panel.jtwc">JTWC Official Forecast</h4><p class="map-note" data-i18n="note.jtwc"></p></div>
                        <div><h4 data-i18n="panel.official">Official Forecasts Compared</h4><p class="map-note" data-i18n="note.official"></p></div>
                        <div><h4 data-i18n="panel.cities">Taiwan Landfall &amp; City Strike Probability</h4><p class="map-note" data-i18n="note.cities"></p></div>
                        <div><h4 data-i18n="panel.comparison">Multi-Model Comparison</h4><p class="map-note" data-i18n="note.comparison"></p></div>
                        <div><h4 data-i18n="panel.ensemble">Ensemble Track Forecast</h4><p class="map-note" data-i18n="note.ensemble" data-i18n-model="WN3-C / GENC / AIFS / ECMWF / AIGFS / GFS"></p></div>
                        <div><h4 data-i18n="panel.anim.generic">Track Evolution Animation</h4><p class="map-note" data-i18n="note.anim"></p></div>
                        <div><h4 data-i18n="panel.tmap">Interactive Track Map</h4><p class="map-note" data-i18n="note.tmap"></p></div>
                        <div><h4 data-i18n="panel.trend">Track Trend</h4><p class="map-note" data-i18n="note.trend"></p></div>
                        <div><h4 data-i18n="panel.strike">Strike Probability</h4><p class="map-note" data-i18n="note.strike"></p></div>
                        <div><h4 data-i18n="panel.strikex">Strike Probability by Period</h4><p class="map-note" data-i18n="note.strikex"></p></div>
                        <div><h4 data-i18n="panel.plume">Intensity Forecast</h4><p class="map-note" data-i18n="note.plume"></p></div>
                        <div><h4 data-i18n="panel.score">Track Error by Model</h4><p class="map-note" data-i18n="note.score"></p></div>
                        <div><h4 data-i18n="arch.title">Storm Archive</h4><p class="map-note" data-i18n="arch.lead"></p></div>
                        <div><h4 data-i18n="nav.genesis">Genesis</h4><p class="map-note" data-i18n="note.genesis" data-i18n-source="Google DeepMind / ECMWF Open Data / NOAA NCEP"></p></div>
                    </div>
                </div>
                <div class="panel reveal about-keys">
                    <div class="panel-header"><span class="panel-icon">⌨️</span><span data-i18n="about.keys">Keyboard shortcuts</span></div>
                    <div class="keys-list">
                        <div><span><kbd>1</kbd>–<kbd>{min(9, len(routes))}</kbd></span><span data-i18n="key.views">Switch pages</span></div>
                        <div><span><kbd>Space</kbd></span><span data-i18n="key.play">Play / pause the animation on screen</span></div>
                        <div><span><kbd>←</kbd><kbd>→</kbd></span><span data-i18n="key.seek">Step animation frames</span></div>
                        <div><span><kbd>Esc</kbd></span><span data-i18n="key.esc">Close the enlarged image</span></div>
                    </div>
                </div>
                <div class="panel reveal about-app">
                    <div class="panel-header"><span class="panel-icon">📱</span><span data-i18n="about.app">Use it like an app</span></div>
                    <p class="map-note" data-i18n="about.app.text">iPhone: open the site in Safari, tap Share → Add to Home Screen. Android: open it in Chrome, tap ⋮ → Add to home screen. It opens full screen like an app and always shows the latest forecast. Links shared on LINE or Facebook show a preview card with the latest map, storm name, intensity and update time.</p>
                </div>
                <div class="panel reveal disclaimer">
                    <div class="panel-header"><span class="panel-icon">⚠️</span><span data-i18n="about.notice">Notice</span></div>
                    <p data-i18n="about.disclaimer">Not for operational use. For official warnings, follow your national meteorological agency.</p>
                    <p class="map-note" data-i18n="about.prob">Probabilities on this site are the share of ensemble members that forecast an outcome — a measure of how much the models agree, not an official forecast probability. A deterministic run (AIFS-single, ECMWF HRES, AIGFS, GFS) is a single possible scenario.</p>
                </div>
            </div>
            <div class="section-head reveal">
                <div><h3 data-i18n="sec.models">Forecast models</h3></div>
                <span class="legend-inline"><span class="model-state on"></span><span data-i18n="models.on">Output in this run</span></span>
            </div>
            <div class="model-grid">{model_cards}</div>
        </div>
    </section>"""

    # ═════════════════════════════════════════════════════════════════
    #  導覽列（桌面頂部／行動版底部）
    # ═════════════════════════════════════════════════════════════════
    nav_links = [f'<a class="nav-link" href="#/overview" data-route="overview">{ICONS["overview"]}<span data-i18n="nav.overview">Overview</span></a>']
    for info in infos.values():
        nav_links.append(
            f'<a class="nav-link nav-storm" href="#/storm/{_esc(info["id"])}" data-route="storm/{_esc(info["id"])}">'
            f'<span class="nav-dot" style="--c:{info["color"]}"></span><span class="storm-name">{_esc(_title(info))}</span></a>')
    # 颱風多時各颱風連結會擠爆頂部導覽列（1440px 放 5 顆就被截字），改收進「颱風 ▾」下拉選單。
    # 超過 NAV_COLLAPSE_AT 顆一律收合；顆數少但螢幕窄、排不下時由前端偵測溢出再收合。
    if len(infos) > 1:
        menu_items = "".join(
            f'<a class="nav-menu-item" role="menuitem" href="#/storm/{_esc(o["id"])}" data-route="storm/{_esc(o["id"])}">'
            f'<span class="nav-dot" style="--c:{o["color"]}"></span>'
            f'<span class="storm-name">{_esc(_title(o))}</span>'
            f'<span class="nm-cat" style="background:{o["color"]};color:{o["text"]}">{o["cat"]}</span>'
            f'<span class="nm-kt mono">{f"{o["wind"]:.0f} kt" if o["wind"] is not None else ""}</span></a>'
            for o in sorted(infos.values(), key=lambda o: -(o['wind'] or 0)))
        nav_links.append(
            f'<div class="nav-drop">'
            f'<button class="nav-link nav-drop-btn" type="button" aria-haspopup="true" aria-expanded="false" data-route-prefix="storm/">'
            f'{ICONS["storm"]}<span data-i18n="nav.storms">Storms</span><em class="nd-count">{len(infos)}</em>'
            f'<svg class="nd-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>'
            f'</button><div class="nav-menu" role="menu">{menu_items}</div></div>')
    if _genesis_entries:
        nav_links.append(f'<a class="nav-link" href="#/genesis" data-route="genesis">{ICONS["genesis"]}<span data-i18n="nav.genesis">Genesis</span></a>')
    if _archive:
        nav_links.append(f'<a class="nav-link" href="#/archive" data-route="archive">{ICONS["archive"]}<span data-i18n="nav.archive">Archive</span></a>')
    nav_links.append(f'<a class="nav-link" href="#/about" data-route="about">{ICONS["about"]}<span data-i18n="nav.about">About</span></a>')

    bottom = [f'<a href="#/overview" data-route="overview">{ICONS["overview"]}<span data-i18n="nav.overview">Overview</span></a>']
    if infos:
        first = next(iter(infos.values()))
        badge = f'<em class="bn-count">{len(infos)}</em>' if len(infos) > 1 else ''
        bottom.append(f'<a href="#/storm/{_esc(first["id"])}" data-route-prefix="storm/">{ICONS["storm"]}{badge}'
                      f'<span data-i18n="nav.storms">Storms</span></a>')
    if _genesis_entries:
        bottom.append(f'<a href="#/genesis" data-route="genesis">{ICONS["genesis"]}<span data-i18n="nav.genesis">Genesis</span></a>')
    if _archive:
        bottom.append(f'<a href="#/archive" data-route="archive">{ICONS["archive"]}<span data-i18n="nav.archive">Archive</span></a>')
    bottom.append(f'<a href="#/about" data-route="about">{ICONS["about"]}<span data-i18n="nav.about">About</span></a>')

    # 給前端腳本的資料（路由、主視覺參數、更新時間）
    joined_ids = " / ".join(track_ids)
    title_track_ids = joined_ids or "Forecast"
    site_data = {
        'routes': routes,
        'archiveOrder': ARCHIVE_MODEL_ORDER,
        'updatedIso': updated_iso,
        'hero': {'rgb': hero_rgb, 'strength': round(hero_strength, 3)},
        'trackIds': joined_ids,
        'scaleMax': SCALE_MAX_KT,
        'bands': [[c, lo, hi, CAT_COLOR_MAP[c]] for c, lo, hi in CAT_RANGES],
        # 3D 地球：各颱風位置／強度色／預報路徑，land 是壓縮過的陸地遮罩
        'globe': {
            'land': _LAND_MASK_B64,
            'focus': lead['id'] if lead else None,
            'storms': [
                {'id': i['id'], 'name': _title(i), 'lat': i['lat'], 'lon': i['lon'],
                 'kt': i['wind'], 'color': i['color'], 'track': i['track']}
                for i in infos.values()
                if (i['lat'] is not None and i['lon'] is not None) or i['track']
            ],
        },
    }
    site_json = json.dumps(site_data, ensure_ascii=False).replace('</', '<\\/')

    docs_dir = os.path.dirname(output_path) or '.'
    share_time = now_local.strftime('%m/%d %H:%M UTC%z').replace('+0800', '+8')
    # 樣式與腳本拆成獨立檔案、網址帶內容雜湊：每 10–15 分鐘重新整理時瀏覽器直接用快取，
    # 只有 HTML 本身重抓；改了產生器雜湊才會變。status.json 給頁面輪詢用：時間沒變就不重新整理。
    asset_ver = _write_static_assets(docs_dir)
    with open(os.path.join(docs_dir, 'status.json'), 'w', encoding='utf-8') as fh:
        json.dump({'updated': updated_iso, 'version': SITE_VERSION, 'storms': list(track_ids)}, fh, ensure_ascii=False)
    try:
        _write_app_assets(docs_dir)
        has_share = _write_share_image(docs_dir, lead, share_time,
                                       os.path.join(docs_dir, _genesis_entries[0][1]) if _genesis_entries else None)
    except Exception as e:  # 預覽圖失敗不該讓整個網站停更
        print(f"[HTML] 分享預覽圖／圖示產生失敗，略過: {e}")
        has_share = os.path.exists(os.path.join(docs_dir, SHARE_IMAGE))
    share_meta = _share_meta(lead, track_ids, share_time, has_share, now_local.strftime('%Y%m%d%H%M'))

    html_content = f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <meta name="color-scheme" content="light dark">
    {share_meta}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300..800&family=Noto+Sans+TC:wght@300..900&display=swap">
    <title>Pillar's Tropical Cyclone Forecast | {_esc(title_track_ids)}</title>
    <script>
    // 在第一次繪製前就決定主題（預設黑底，使用者切過就沿用上次的選擇），避免閃一下
    (function () {{
        var d = document.documentElement;
        d.classList.add('js');
        var saved = null;
        try {{ saved = localStorage.getItem('theme'); }} catch (e) {{}}
        d.setAttribute('data-theme', (saved === 'light' || saved === 'dark') ? saved : 'dark');
    }})();
    </script>
    <link rel="stylesheet" href="site.css?v={asset_ver}">
</head>
<body>
    <canvas id="globe" aria-hidden="true"></canvas>
    <a class="skip-link" href="#views">Skip to content</a>
    <header id="site-header">
        <a class="header-brand" href="#/overview">
            <div class="brand-icon"><span><svg class="brand-mark" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M9 12A6 6 0 0 1 20.2 9M15 12A6 6 0 0 1 3.8 15"/></svg></span></div>
            <div class="brand-text">
                <h1 data-i18n="brand.title">Pillar's Tropical Cyclone Forecast</h1>
                <small data-i18n="brand.sub">Real-time WN3-C / WN2-C r2 / WN2-C r1 / WN2-C 1000 / GENC / AIFS / ECMWF / AIGFS / GFS Ensemble Forecast System · Western Pacific</small>
            </div>
        </a>
        <nav class="top-nav{' collapsed' if len(infos) > NAV_COLLAPSE_AT else ''}" aria-label="Pages"><span class="nav-indicator"></span>{"".join(nav_links)}</nav>
        <div class="header-actions">
            <div class="update-badge" id="update-badge" data-full="{update_time}">
                <svg class="ring" viewBox="0 0 20 20" aria-hidden="true"><circle class="ring-bg" cx="10" cy="10" r="7.5"/><circle class="ring-fg" cx="10" cy="10" r="7.5" pathLength="100"/></svg>
                <span class="ub-text"><span data-i18n="header.updated">Updated</span><span class="ub-long">: {_tz(updated_iso, update_time[:10], "ymd")}</span> {_tz(updated_iso, update_time[11:16], "hm")}<span class="ub-long">{_tz(updated_iso, update_time[16:], "s")}</span></span>
            </div>
            <button class="theme-btn" id="theme-btn">🌙 Dark</button>
            <button class="theme-btn" id="lang-btn" title="Switch language / 切換語言">🌐 中文</button>
            <button class="theme-btn" id="tz-btn" title="UTC / Taiwan time (UTC+8)" aria-pressed="false">🕒 UTC</button>
            <span class="actions-break"></span>
            <span class="version-badge" title="Site version / 網站版本">v{SITE_VERSION}</span>
        </div>
        <div class="scroll-progress" aria-hidden="true"></div>
    </header>

    <main id="views">
{overview_view}
{"".join(storm_views)}
{genesis_view}
{archive_view}
{about_view}
    </main>

    <footer>
        <div class="footer-inner">
            <div class="footer-brand">
                <h3 data-i18n="footer.title">Pillar's Tropical Cyclone Forecast System</h3>
                <p data-i18n="footer.desc">
                    Ensemble track forecasts from DeepMind WeatherNext
                    (WN3-C, WN2-C r2, WN2-C r1, WN2-C 1000, GENC), ECMWF Open Data
                    (AIFS-ENS + AIFS-single, IFS ENS + HRES) and NOAA NCEP (AIGEFS + AIGFS, GEFS + GFS).<br>
                    Official forecasts from JTWC, JMA and CWA; satellite imagery from Himawari-9 (JMA), via NOAA Open Data on AWS; ocean heat content from Copernicus Marine (CMEMS), with HYCOM as backup. Steering flow and vertical wind shear are from AIFS-single (ECMWF Open Data).
                    Data refreshed automatically.
                </p>
            </div>
            <div class="footer-links">
                <a href="https://deepmind.google.com/science/weatherlab" class="footer-link" target="_blank" rel="noopener"
                   data-i18n="footer.link1">🌐 DeepMind Weather</a>
                <a href="https://data.ecmwf.int/forecasts/" class="footer-link" target="_blank" rel="noopener"
                   data-i18n="footer.link2">🇪🇺 ECMWF Open Data</a>
                <a href="https://nomads.ncep.noaa.gov/" class="footer-link" target="_blank" rel="noopener"
                   data-i18n="footer.link3">🇺🇸 NOAA NOMADS</a>
                <a href="https://www.metoc.navy.mil/jtwc/jtwc.html" class="footer-link" target="_blank" rel="noopener">🛰 JTWC</a>
                <a href="https://www.jma.go.jp/bosai/map.html#contents=typhoon" class="footer-link" target="_blank" rel="noopener"
                   data-i18n="footer.link4">🇯🇵 JMA Typhoon Information</a>
                <a href="https://opendata.cwa.gov.tw/" class="footer-link" target="_blank" rel="noopener"
                   data-i18n="footer.link5">🇹🇼 CWA Open Data</a>
                <a href="https://registry.opendata.aws/noaa-himawari/" class="footer-link" target="_blank" rel="noopener"
                   data-i18n="footer.link8">🛰️ Himawari-9 (NOAA Open Data)</a>
                <a href="https://marine.copernicus.eu/" class="footer-link" target="_blank" rel="noopener"
                   data-i18n="footer.link6">🌊 Copernicus Marine (CMEMS)</a>
                <a href="https://www.hycom.org/" class="footer-link" target="_blank" rel="noopener"
                   data-i18n="footer.link7">🌊 HYCOM</a>
            </div>
            <div class="footer-copy" data-i18n="footer.copy">© 2026 Pillar's Weather Site · Made by Pillar · Not for operational use</div>
        </div>
    </footer>

    <nav class="bottom-nav" aria-label="Pages">{"".join(bottom)}</nav>

    <!-- Lightbox：點圖放大，點任意處或按 Esc 關閉（與 v2 相同的簡單版） -->
    <div class="lightbox" id="lightbox">
        <button class="lb-close" data-lb="close" title="Close"
                data-i18n="lb.close" data-i18n-attr="title">✕</button>
        <img id="lightbox-img" alt="Full-size view">
    </div>

    <script id="site-data" type="application/json">{site_json}</script>
    <script src="site.js?v={asset_ver}" defer></script>
</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"[HTML] 已生成網站：{output_path}")


# ═════════════════════════════════════════════════════════════════════════
#  樣式表與前端腳本
#  刻意寫成一般字串（不是 f-string），CSS／JS 的大括號不必再成對跳脫；
#  動態資料一律透過頁面上的 #site-data JSON 與 data-* 屬性傳進來。
# ═════════════════════════════════════════════════════════════════════════
# 3D 地球的陸地遮罩：Natural Earth 50m 陸地柵格化成 0.5° 格點（720×360，由北往南、
# 由 180°W 往東），np.packbits 後 zlib 壓縮再 base64；前端用 DecompressionStream 解開。
_LAND_MASK_B64 = "eNrtndFvJMlZwKumZ92jnM9taSOtUYx70IGOJ9YQBBtktgeCFB4i7g8Asj6BlAeEYsiLIxx3+7yw9xDhvBHEKb53EFqJl5WI4l7tRXu83AZ4IA9R3Msm7ALh3Bsf2fa6XUVVdfVMdfdX1dVjjxDIJe2td9zzm6+/+r6vvu+rmj6ELsfluByX4//OeG2f0vQCeb0tSvcj9oP7kNKLRHt7nJehP/ZfLX64qBFyHCXOES0G2cJN+Pw0EjvHlEEzh5bjmJL6RXisIceeHNw/pD4lLlVGUr1k7pvu4+NIXm4/C/RsP2CzFijgb46n9j3xGU78o++ML4/tyfTRMT2NHIW8WvzG/eg4aGj8EbXDujHC9IzSCKnakGL1SN7UqpsvWxrGsksPmGI9BZzL3/UbCi/eYqcPdy/6D2Z2O+r8ZSP5y5/KbzTfgfNBO/ZqipZRhl4wr/NV9NvlBZkfT+ciEZpjfy0GP2bTr5LfLW+oqYwhQn7SBsZ0iYGd3OeRQp3AZ+NLVIm98h9BXvkgYPjxRx76w8zJuV85ZH9MJtD1n5TWhu8rN6Ubn6S7mZ+iHBVCTHwlAma6fFFEmbviM/yDSGcXLERE6UmJGhseuQvEgFgNX4Wmg9NHOuE9fsUNSg+KWFOSzwBRpC5eKa6Q4UQ/gfUXytG82MnGt8mXBnkDI23AYGHXyYNkq1e+IMYp0dwdG78rrvgrOcVrOpnJBvpbnIa7x2dE0SF9CijDZ38W2BUvhMjMTTGfG406HHr09CvZT+RfdJ9KIQ8L8hEQgbf5hL3Vk59ND4uwtaqzjD3KghlZ9Z7kL2JFZroKk8O3PDVurTPZAtD5MWEGvI22Njx2i+/zV/5EvicFruXkr9MfqOvOCNNHJTmrLGQbzMwIC134RIZkaVInwOJ9i2tv3ztVyXz1JOrieDCeen5vTBxhx99l/14u1LGpkHt/sF7GJsy0d0Ybg6iOR0tj/HIxyT6bkRP2yieKaz9QZH31MC+9wmHk0yZ5YvyBTFaO/vUGF/aHS9vIxbuUsg8KbtXDxhyl/1WoErOsYZ9SkPy0eId0fMJ169HD1L/2npv9dChCQVBZrOQLL/mU8DWK7lF47FISK2FH+ER+Y+DfOXIy7JNJtJuYhrsvw89odSHMg4eHEPdQKqFCjvE7aMUn1xP8kH6b3XFYs7mPy3tI3f/kPzw8otoRKWGHS5PRJ38XUj917/M57h9UdVFGvygpbuahHsyttvqCkPIg6yH+O6+eiUox4qT42zOQH0XVRbogk5RLlxUiqg4orn1E42LWPwj04AOaek7z5R9xxn4iTP0FM6BVLJ32uvioYIG2jn2ahM1Xjz/k/sO8zDkolPGlMjUKaRYyxYft5IjUlFGMPS7tg2J2CyVkpTkn/Od2MGUZkX8M3EriHYokY6+IAvtS2eyTmIrzrVbu2Tcq6+hk+FnPEWKGwuGYjURliIlbTKLMBEEySYMVvnQJMilihAyd3HGtBnvDCqDopI+W0Paa0GteXYJzz46cg8ogIuC8/p6YurTqJ2lgR/7eOGGofd5o77uieHInmfhQ+EniW8grLcoDtb9H5ZSpCWxgRU62pN+6wl/VkU7yQVwnx+3kKJFLBU8Ztv167edK39jrLjPalUvhp9iUhfeb5BORgc1N8oc+J594SdBmFd73B+WCnbPQFlZLNCaz28gErovZDdss+eYkFeCZZFAle4zcyOaun/KV3YgdjNN6Nga/zVW6UK1KfPrjZhXlP2HLmZHMJx+fTJbNYyU7lP7jTgpXOV5nVe0OjQZGZYhmi7Ig/zn/719Ukhynkc25wghvm9Vcq7RWRN38LxUybpBZZYSW6NvLYUu0UMlFwfvzlcCBG00enuRvhnHQGjsnQQwXzvAzlZt6s0Hm5WseoKBtAtEkZfRkxhaqvuJUkkpZkqP0rpkcCz2OtfgLapFUzjGPU6Ri0J9mt/CF22YyqpDLBb+nBr20nnaxZWUToS+yOTRN4GJBxvU6TA0dYb0t5WWsMlmLzZ79rf6kBJ0U9z01ihVLx02VnAZljaYfT28r5LHk+EqDrJau7nNeCrSNH6oyj8efqulXk5yC6VRtfFhWVQgtTt47Ut6Y+vXmg//YhsydZLNZ3KvLd0BrBr3g0Lh9cf2gKDTgRquS7D6pNjSetJN5bFtvlqWNSulBtXfm25GhXkgtCLxR0VXfwjRYEgu2dtdqQSB+Va8tPRls9VRjAlr17tWaTK3jK3CHyqkoOici2E/GZyzImkY6rijylKAgA5tKhqFpkOJKRfqClSP/1lHNRNd6Paz702fhWHiqdcF5be+rUmv0UB8mP9Tl0dmCcbdDcin5fL2BJTs0fG8BXmnTgZXM9FtNMtdXusakh1etpBLiNOQjmuZNMreeJDigBLaUeAlFFjI/jZvkXfF2n+YOnHzN9yy0kS80G737uyJoOzSHHRKtDC3I6XyDTNxYtkQIKDPz2ljTFzXsJ/FW3pLLjY0bEaznTV3HHzfynSo5R6+kniD7BPJIMkQUdSdjTn6T77+JvB0isyjzZzb2nAAyr4fsA9A2I0dvgPliZEHOmzfE3unvUHqfO2Dsgn4ynI4co8R9TH9LxI/k9UZHipMTCz2njbY3M7d15x9O7yiJX2Wh4tlJaiEzQJ5jC/6ObEM0almywnvdFmTybtNPeCoRb2vI+eKKgazcIVGNblT4Nv8xWiu8L/Ya0+ePCxNgW0cRIW5oQ5Rc0dU7MDlFQTTO8ptpgSKzapl9QebWsoV+x4XJ+ciNkaMj+1BLfSwz0+HiMlouLChrkDMn4Zu4rTI3A4A/dA7zPi+rX3JQY01JWMEYRtOQB7x1KVLuDTjqu8mQGjbx9DuCAzx2TDjqs1JUu6nuGPSMFu4IMn6GVuGo7yZhHqFW9ybg9BavrsN1RB+dfq3leAW8n+SPX8Wa1sZr+5H+fIUu7stPzY3kj3/JsD+vn0A8Ca2ajGDgj2zI9XMzEpfyZoij6RO8YdiVdvQT6MrXcx050e7vVjSYa8lMNlfTNVkxkR+obRtociNKvD2NzMbxpI2c6lu4NuR/9zKj54Oj5WTBH/Fr/jnrbxmjFRt34O6UfohiM/5FYEdcid1/z/64XcnL0ktWGiFUicenFNqiaNHzZ8PC4lYanhJWdxZ3AE8Zmsg/5xd2cdMQYOljSoFeR2SW2Zdk32QaqShWOpKdvYLstZHTnwwamzBGNr6jIfu1NmGKGmRsFvqObGybyFnA9yb3dTvzmnG/kLlnSJ9ERvASR7/idiInMmYstpCJG1WjabbaQt6QScXAUJITrhpxpk1V/noLeSmAz0NWbtyV3lxxwbYTWgMfDgBNcm3PJmo9++UJMo0WDQWdI6fMnbRRctR6hs3lZLyXmErFXbkIB4HcDeTxaNRO5noeZvqwQekDKbMfijMs8FEoYPnO+PG2lVYy07MnIqOhM4WrMue84vdM2rgvl8p+QIsNe5vjhgU5UjefmomtCKEfFf6TFf/RjLhWnTEyctcNDYpAriEhD/j8BKHuXGdU1SivkpCTt5BTuTEryJt2J1xFuYGJoY0QyGw14AGfreqJFTmgR8yGVrx/uqElZ75cQ0SHxi3k37SYQmmdPT3Zk1EzkJ6Ywe395lpK2tpibrkVyJmuuiVhPo4KkHGDnIxPjLi3xBssyP6hJM9ryY5cqn0+j54v1Ldh4d8uoWaZiWwc8H5SsUZG2nZMXdN1g3fqZCJDrkwmYzsybqYltQTxgcziVPLQzlliZIp19Im8wFXIv29D9hoy10rA/yaoQf7ryEYdRTehr5X5NCnJYlM+4Mp500bmZp+iRi7P6Tpc5lFBttKzCHaxQRsEKWTkulwbr63bkFmAxpFhzyqXmsKFzA4nD6yEZmuVt2Jo1BMkSyQh85wgv2olM0vaQlLZTak1/vxcIS8IpXzMSs8eI4fPv68nl+UzKWyIRaOe3Vc+rsQorCZ4LkzeigSZLRL9fmSFTlJaPfLlQucpENoWp3X44eRBb9HOoP8SPnRZJ2/EZemxiG5YkRf8WrnkwBXralLMN5ocPG8zDr/WTMKaWpiTi7n7mB25OHKR6HfLyl+JY0Jc5uHgGbITul6khxTcE0lLwdetQn9JzqoGnYZNclLik05kVejanmAlXm2KExDDLmSivvAN1RFVs4m3GslaK1lZaXkL3webyDjdZtdnHcmRrt5UX+UnaDzrr3M5YHv0FlgLb91EkZ90lDnWtKkqyfVNFsoDa7JnJleOBfgr6sGp1vUKbDt5YDvK2yt2LpphtK/ftEk1XY7KvbhP0FV2JbaTuYVcefU1Xl9lw1+zC/1wE84H2yRXOTmlO53Iz2BytYmMX/Kz3FbaWB+H46/D5JrDEUZ+jHCvnTwak0kM+mBaJ/v0cc/ZeW7vgvQstSD3w8ij9+8hJ+1Arn0fyocnNvyqR3fS0SD9jj2ZwuSqjnAQe3SXCTzatreNurfBeyL+CSPfRegeTTqQK4HU1ZBTdOjcm9/8MjMabKuNqtAOTGbBeW7nXr9/3aLr48Bddgx3KnmbBb8j3hXjkVV4bniF5mQAJ39VpA4JjqxlrihaWnn9ck6+LWwndey1UTExzd6TTEN/06PZdn86cgh3hGWnbMCq5qWetdXZkP3irMmAb7e3mV0IkwOYXH7PVGzkDy+SjPYznvUzH72J0G9YrVZ1sq8hO0ScKVgmnvZ7j1OSUe9eyve6tnn+P7LJCur2HBh2C3gY6DvvtykaTg4NZLwTl+4Y2+RIdbJPtd1maW1rltlX3eF8/R7VxEMGliEpBz4Qjjq9yObBCw4c6yT5LfA98+vdyCmoDWj+e3Rk8XwBDJMDE5n5+EIXcgw4fQQ6mkfVjQfcGuxgcgo341a6pAXW5AWfjqYnl69hgBz42hOScEiCyBHUcghCKk9I9u0CB0h2n4Eh3ap4c01kFALf+A752bhEbqNgC7MDyASFTdmuiL3fkty3WK/i5selCEgNPbFDm9rXbRA51pEnHrtkMYVRUxsGsk3LACSH8iXgJJR/AWQCPtnE1xwK0q8qTeVnIDm026qfkAlMjuq7+I7dYQst2Zd33ASoRvrrVuQcImMaYU0E4+ThFGRPHtWg2tUtaTHmCTlrRhOI7KrkvpXVpXZkX38WTUMmCCQTbeZjTc4syb712ZPy2rgrmdqSI4DMbjjXk9+1JEPGlQBbo15XMoHIsTF3jS+YfL0DOehE9s9LxhehDT05MpKT6chIR3Y7kEPQV0ONL3QmZ8CdEHONYElOAXJ+IeS7gHW1kGM7cgSQs9mQPc2RU9yVDNltoiPH5yK7mrdi8W0ru4QjBBcITxPa8fjxM2hqMtGR2Q0dWa1WcGbparZkxNdXnENb8lGTrOuLO+J7MftWazcjP090/ZHm4ELgazZkTKd4KqVbvmf1osm/V/rRUkuDI+9KxiW530ImXcmoJF9pqWHzqcluC7n7c0VDGVWcr5nJ3R+F6stHb5q2kl27akb37tQ4g8nU4MmjGmGZz/FcWNdMPofMTmQsgKYhj2zI+TTCyhNjh4ZLrkxHDgQZmzzhlemMrvhaBE6N5Hx6smOaok9Mp42iTeyZml/OeZ5GHMTGKHoOsjH8XjsHGefmVkE8vQfm5sVy+khnPgL2y+cgG82ZJffTa6OthE1nRL42M3JwnvCM/nf0HFjYxs9ORQ7pjERGt8isyEE+K/L1mZG9XP9N/nPK/HJWMl/53qzIzudmRZ57FM0K/Rnp3b0LJ187a6kApx69WUWky3E5LsfluBznXmVnFaJ7G7MS+er7syLPLONAsyonWmqv84zXnxnLcjUjTkQXrXiir8XYN+Y542JD7FjtkeJ/jhLb5D7OlrmMqT536Hke2h6FQMZvZgXlppbfeBycxVgzlfvyZIBD4e+7mcfNtzS/WC0PayTA47/P3mm35uDbmt9s4fGGXaB7OLFhjE7A8pjPUPCP480v7ZN+TWO+QR5Gw+FtNK+c9Q+1Tyc2WcbN2qmxwToKCc0/FdWeAdAcR+ZpxCSsXLC80ZRwx/RQbO3YptUqFnrioGN8dnVTWPkF3c8FpI38hvEJ040xLM8ThSr5KiQZ7UYO8i/sv43jZx5VQxf0/jNrZSyKGPSr4mmaeeWCns3/rcEk8hq6oT5lKlXIQRdyzaATRF3xhJXxBYp3e13AJ1VwOd9eBn1dy+9CrvguNs9DJy1XQpJzBD02bkpwhfxLblPgaDpVVG7WSz/tGiR2OoIp6U9kemH64K4iU9o3vPcgKRe8zlpm428kdx14725SfAPaz6YgfzgOxMCbGXAzFncT49TrSB7Pff1JR6WbrJYd3XfdbmRkdjEWoNyoeBqGN63RwYYVsSVfqNnmidK6tcoxRSy3u2lEbZEsm9KaVe/WPPhvjj/gKexOzltjZOLQ6UYhdJBpA0MWTEkmU4XILsF/JmhSPAKLXo7LcTn+343/AT4JsPo="


_CSS = r"""
/* ── Design Tokens ─────────────────────────────────────────── */
/* 色票與地圖同源：海軍藍 #16324F = 平均路徑、海洋藍 #2E86C8 = TS、
   青綠 #1FA97E = Cat1，網頁與圖面因此看起來是同一套系統。 */
:root {
    --bg:        #e9eff5;
    --surface:   #ffffff;
    --surface-2: #f2f7fb;
    --surface-3: #e5edf5;
    --accent:    #1b5c94;
    --accent-2:  #0f9b8e;
    --accent-lo: rgba(27,92,148,.10);
    --accent-rgb: 27,92,148;
    --text:      #16324f;
    --text-2:    #4a6076;
    --text-3:    #5c6e81;
    --border:    #d2dde9;
    --danger:    #dc3a4e;
    --ok:        #1fa97e;
    --warn:      #ee7a22;
    --shadow:    0 2px 12px rgba(22,50,79,.07);
    --shadow-md: 0 8px 32px rgba(22,50,79,.10);
    --shadow-lg: 0 20px 60px rgba(22,50,79,.16);
    --btn-bg:    linear-gradient(135deg,#1b5c94,#2e86c8);
    --glass:     rgba(255,255,255,.74);
    --header-h:  64px;
    --radius:    16px;
    --ease-out:  cubic-bezier(.16,1,.3,1);
    --ease-spring: cubic-bezier(.34,1.56,.64,1);
    --hero-1: #04111e; --hero-2: #082239; --hero-3: #0d3558;
    --broken-text: "Image unavailable";
}
[data-theme="dark"] {
    --bg:        #071320;
    --surface:   #0d1e2e;
    --surface-2: #12283b;
    --surface-3: #1a3550;
    --accent:    #58b0e8;
    --accent-2:  #3fcbb4;
    --accent-lo: rgba(88,176,232,.12);
    --accent-rgb: 88,176,232;
    --text:      #dfe9f2;
    --text-2:    #91a6ba;
    --text-3:    #6a8397;
    --border:    rgba(88,176,232,.16);
    --danger:    #f26173;
    --ok:        #35c496;
    --warn:      #f79445;
    --shadow:    0 2px 12px rgba(0,0,0,.32);
    --shadow-md: 0 8px 32px rgba(0,0,0,.42);
    --shadow-lg: 0 20px 60px rgba(0,0,0,.55);
    --glass:     rgba(9,22,35,.74);
}

/* ── Reset ─────────────────────────────────────────────────── */
*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
/* 字體：拉丁字用 Inter，中文落到思源黑體（Noto Sans TC）。
   Google Fonts 載不到時退回系統字（蘋方／微軟正黑），版面不受影響。 */
body {
    font-family: 'Inter', 'Noto Sans TC', 'PingFang TC', 'Microsoft JhengHei',
                 system-ui, -apple-system, 'Segoe UI', sans-serif;
    font-optical-sizing: auto;
    text-rendering: optimizeLegibility;
    background: var(--bg);
    min-height: 100vh;
    color: var(--text);
    transition: background .35s, color .35s;
    -webkit-font-smoothing: antialiased;
}
html, body { max-width: 100%; overflow-x: hidden; }
img { max-width: 100%; height: auto; }
button { font-family: inherit; }
/* 中文內文：稍微加寬字距與行高，讀起來比較鬆 */
html[lang^="zh"] body { letter-spacing: .02em; }
html[lang^="zh"] p, html[lang^="zh"] .map-note { line-height: 1.8; }

.mono { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }
body.lb-lock { overflow: hidden; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 6px; }
.skip-link { position:absolute; left:-9999px; top:8px; z-index:1000; background:var(--surface); padding:8px 14px; border-radius:8px; }
.skip-link:focus { left:8px; }

/* 主題切換時整頁用圓形擴散揭露（View Transitions API） */
::view-transition-old(root), ::view-transition-new(root) { animation: none; mix-blend-mode: normal; }
/* 語言切換：舊文字模糊淡出、新文字從模糊中浮現 */
html.lang-vt::view-transition-old(root) { animation: langOut .26s ease-in both; }
html.lang-vt::view-transition-new(root) { animation: langIn .5s cubic-bezier(.16,1,.3,1) both; }
@keyframes langOut { to { opacity: 0; filter: blur(8px); } }
@keyframes langIn  { from { opacity: 0; filter: blur(8px); } }
/* 不支援 View Transitions 的瀏覽器：只讓換過字的元素淡入 */
html.lang-fallback [data-i18n] { animation: langInFb .45s cubic-bezier(.16,1,.3,1); }
@keyframes langInFb { from { opacity: 0; filter: blur(4px); transform: translateY(4px); } }
#lang-btn .bi { display:inline-block; }
#lang-btn.spin .bi { animation: globeSpin .7s cubic-bezier(.34,1.56,.64,1); }
@keyframes globeSpin { from { transform: rotate(-360deg) scale(.6); } }

/* ── Header ────────────────────────────────────────────────── */
header {
    position: sticky; top: 0; z-index: 300;
    min-height: 64px;
    background: var(--glass);
    -webkit-backdrop-filter: saturate(1.6) blur(16px);
    backdrop-filter: saturate(1.6) blur(16px);
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; flex-wrap: wrap;
    padding: 0 28px; gap: 12px 18px;
    transition: background .35s, border .35s;
    animation: slideDown .5s var(--ease-out);
}
@keyframes slideDown { from { opacity:0; transform:translateY(-14px); } to { opacity:1; transform:none; } }
.scroll-progress {
    position:absolute; left:0; right:0; bottom:-1px; height:2px;
    transform-origin: 0 50%; transform: scaleX(var(--p, 0));
    background: linear-gradient(90deg, var(--accent), var(--accent-2));
    pointer-events: none;
}
.header-brand { display:flex; align-items:center; gap:10px; text-decoration:none; color:inherit; min-width:0; }
.brand-icon {
    width: 38px; height: 38px; border-radius: 11px; flex-shrink: 0;
    background: var(--btn-bg);
    display:flex; align-items:center; justify-content:center; font-size:1.2em;
    box-shadow: 0 4px 12px rgba(var(--accent-rgb),.35);
    transition: transform .5s var(--ease-spring);
}
.brand-icon span { display:inline-block; animation: spin 14s linear infinite; }
.header-brand:hover .brand-icon { transform: rotate(-12deg) scale(1.06); }
@keyframes spin { to { transform: rotate(-360deg); } }
.brand-text h1 { font-size: 1.02em; font-weight: 800; letter-spacing: -.3px; line-height: 1.15; }
.brand-text small { font-size: .7em; color: var(--text-3); font-weight: 500; display:block; margin-top:1px; max-width: 34ch; }

.top-nav { position: relative; display:flex; align-items:center; gap:2px; flex:1; justify-content:center; min-width:0; }
.nav-link {
    position: relative; z-index: 1;
    display:flex; align-items:center; gap:7px;
    padding: 8px 13px; border-radius: 10px;
    color: var(--text-2); text-decoration:none;
    font-size: .85em; font-weight: 650; white-space: nowrap;
    transition: color .25s;
}
.nav-link svg { width: 17px; height: 17px; }
.nav-link:hover { color: var(--text); }
.nav-link.active { color: var(--accent); }
.nav-indicator {
    position:absolute; left:0; top:0; z-index:0; border-radius:10px;
    background: var(--accent-lo); border: 1px solid rgba(var(--accent-rgb),.22);
    opacity: 0;
    transition: transform .5s var(--ease-out), width .5s var(--ease-out), height .5s var(--ease-out), opacity .3s;
}
.nav-dot { width:9px; height:9px; border-radius:50%; background: var(--c); box-shadow: 0 0 0 3px rgba(255,255,255,.0), 0 0 10px var(--c); flex-shrink:0; }

.header-actions { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
/* 頁首按鈕一律排成一排；窄螢幕靠縮短內容（只留圖示、時間只留時分）擠進去 */
.actions-break { display:none; }
.bt-short { display:none; }
.bi:empty { display:none; }
.update-badge {
    display:flex; align-items:center; gap:7px;
    background: var(--surface-2); border: 1px solid var(--border); border-radius: 9px;
    padding: 6px 12px 6px 9px;
    font-size: .76em; font-weight: 600; color: var(--text-2);
    line-height: 1.25;
}
.ring { width: 18px; height: 18px; transform: rotate(-90deg); flex-shrink:0; }
.ring circle { fill:none; stroke-width: 2.6; }
.ring-bg { stroke: var(--border); }
.ring-fg { stroke: var(--ok); stroke-linecap: round; stroke-dasharray: 100; stroke-dashoffset: 0; transition: stroke-dashoffset 1s linear, stroke .3s; }
.update-badge.stale .ring-fg { stroke: var(--warn); }
.theme-btn {
    background: var(--surface-2); border: 1px solid var(--border);
    color: var(--text-2); border-radius: 9px;
    padding: 7px 13px; cursor:pointer;
    font-size: .8em; font-weight: 600;
    display:flex; align-items:center; gap:5px;
    transition: background .2s, color .2s, border-color .2s, transform .2s var(--ease-spring);
}
.theme-btn:hover { background: var(--accent-lo); color: var(--accent); border-color: var(--accent); }
.theme-btn:active { transform: scale(.95); }
/* 版號徽章：與旁邊兩顆按鈕同高，但用實心 accent 底色，一眼看得到 */
.version-badge {
    background: var(--accent); color:#fff;
    border: 1px solid var(--accent); border-radius: 9px;
    padding: 7px 12px; font-size: .8em; font-weight: 700; letter-spacing: .03em;
    display:flex; align-items:center; white-space:nowrap;
}
/* 深色主題的 --accent 是淺藍，白字在上面幾乎讀不到，改用深色字 */
[data-theme="dark"] .version-badge { color:#06263f; border-color: var(--accent); }

/* ── Views（hash 路由切換的頁面）─────────────────────────────── */
.js .view:not(.active) { display:none; }
.view.entering { animation: viewIn .55s var(--ease-out) both; }
.view.leaving  { animation: viewOut .16s ease-in both; pointer-events:none; }
@keyframes viewIn  { from { opacity:0; transform: translate3d(calc(var(--dir,1) * 34px),0,0); } to { opacity:1; transform:none; } }
@keyframes viewOut { to   { opacity:0; transform: translate3d(calc(var(--dir,1) * -18px),0,0); } }

.page { max-width: 1380px; margin: 0 auto; padding: 30px 20px 48px; display:flex; flex-direction:column; gap: 24px; }

/* 捲動進場動畫 */
.js .reveal { opacity:0; transform: translateY(22px); transition: opacity .8s var(--ease-out), transform .8s var(--ease-out); transition-delay: calc(var(--i,0) * 70ms); }
.js .reveal.in { opacity:1; transform:none; }

/* ── Hero ───────────────────────────────────────────────────── */
.hero {
    position: relative; overflow: hidden; isolation: isolate;
    min-height: min(80vh, 720px);
    display:flex; align-items:center;
    color: #eaf4fc;
    background:
        radial-gradient(900px 520px at 72% 46%, rgba(var(--flow-rgb),.16), transparent 62%),
        radial-gradient(1200px 700px at 10% 0%, var(--hero-3), transparent 60%),
        linear-gradient(160deg, var(--hero-1) 0%, var(--hero-2) 60%, #0a2c4a 100%);
}
.hero::after {
    content:""; position:absolute; left:0; right:0; bottom:0; height:140px; z-index:0; pointer-events:none;
    background: linear-gradient(to bottom, transparent, var(--bg));
    transition: background .35s;
}
.hero-canvas { position:absolute; inset:0; width:100%; height:100%; z-index:-1; }
.hero-eye {
    position:absolute; left: var(--ex, 72%); top: var(--ey, 46%); z-index:-1;
    width: 120px; height: 120px; margin: -60px 0 0 -60px; border-radius:50%;
    background: radial-gradient(circle, rgba(4,17,30,.95) 0 14%, rgba(var(--flow-rgb),.20) 30%, transparent 70%);
    animation: eyePulse 5s ease-in-out infinite;
}
@keyframes eyePulse { 50% { transform: scale(1.12); opacity:.8; } }
.hero-inner { position:relative; z-index:1; max-width:1380px; margin:0 auto; width:100%; padding: 72px 28px 150px; }
.eyebrow {
    display:inline-flex; align-items:center; gap:9px;
    padding: 7px 14px; border-radius: 999px;
    background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.16);
    -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
    font-size: .76em; font-weight: 750; letter-spacing: .1em; text-transform: uppercase;
    animation: fadeUp .8s var(--ease-out) both;
}
html[lang^="zh"] .eyebrow { letter-spacing: .06em; }
.calm-dot { width:8px; height:8px; border-radius:50%; background:#8fd3ff; box-shadow:0 0 12px #8fd3ff; animation: breathe 3s ease-in-out infinite; }
@keyframes breathe { 50% { opacity:.4; transform: scale(.8); } }
.hero-title {
    font-size: clamp(2.6rem, 7vw, 5.4rem); font-weight: 850;
    letter-spacing: -.035em; line-height: 1.02;
    margin: 22px 0 16px; max-width: 16ch;
    text-shadow: 0 0 60px var(--glow, rgba(143,211,255,.45));
    overflow-wrap: anywhere;
}
html[lang^="zh"] .hero-title { letter-spacing: .05em; max-width: none; font-size: clamp(2.3rem, 6vw, 4.6rem); line-height: 1.32; }
.hero-title, .page-title, .storm-title { text-wrap: balance; }
/* 颱風名稱（全大寫英文）一律拉開字距，不論出現在哪裡、介面是哪種語言 */
.storm-name { letter-spacing: .06em !important; }
.nav-link .storm-name, .switch-chip .storm-name { letter-spacing: .08em !important; }
.split .w { display:inline-block; white-space: nowrap; }
.split .ch { display:inline-block; opacity:0; transform: translateY(.55em) rotate(6deg); filter: blur(6px);
             animation: chIn .9s var(--ease-out) forwards; animation-delay: calc(var(--i) * 32ms + 120ms); }
@keyframes chIn { to { opacity:1; transform:none; filter:none; } }
.hero-lead { display:flex; flex-wrap:wrap; align-items:center; gap:10px; font-size: clamp(1rem,1.7vw,1.25rem); font-weight:650; animation: fadeUp .9s var(--ease-out) .35s both; }
.hero-lead .sep { opacity:.45; }
/* 同時追蹤好幾顆時，每顆一列、整列可點 */
.hero-storms { list-style:none; margin:0; padding:0; display:grid; width: fit-content; max-width:100%;
               animation: fadeUp .9s var(--ease-out) .35s both; }
.hero-storms a { display:flex; flex-wrap:wrap; align-items:center; gap:10px; padding: 12px 0; color:inherit; text-decoration:none;
                 font-size: clamp(1rem,1.7vw,1.25rem); font-weight:650; border-bottom: 1px solid rgba(255,255,255,.16); }
.hero-storms li:first-child a { border-top: 1px solid rgba(255,255,255,.16); }
.hero-storms .sep { opacity:.45; }
.hero-storms .hs-name { font-weight: 800; min-width: 7.5ch; }
.hero-storms .hs-go { margin-left: 14px; opacity:.5; transition: transform .3s var(--ease-out), opacity .3s; }
.hero-storms a:hover .hs-go, .hero-storms a:focus-visible .hs-go { opacity:1; transform: translateX(4px); }
/* 寬螢幕上每一欄（名字、強度、風速、位置、箭頭）上下對齊；窄螢幕維持自動換行 */
@media (min-width: 700px) {
    @supports (grid-template-columns: subgrid) {
        .hero-storms { grid-template-columns: repeat(7, max-content) auto; column-gap: 10px; }
        .hero-storms li { display: contents; }
        .hero-storms a { display:grid; grid-column: 1 / -1; grid-template-columns: subgrid; }
        .hero-storms .hs-go { margin-left: 14px; justify-self: end; }
    }
}
.cat-pill { padding: 4px 12px; border-radius: 8px; font-weight: 800; font-size:.85em; letter-spacing:.04em; }
.hero-sub { margin-top: 12px; font-size: clamp(.98rem,1.4vw,1.12rem); color: rgba(234,244,252,.74); max-width: 56ch; line-height: 1.65; animation: fadeUp .9s var(--ease-out) .45s both; }
.hero-cta { display:flex; flex-wrap:wrap; gap:12px; margin-top: 30px; animation: fadeUp .9s var(--ease-out) .55s both; }
.btn-primary, .btn-ghost {
    display:inline-flex; align-items:center; gap:8px;
    padding: 13px 22px; border-radius: 13px;
    font-weight: 750; font-size: .95em; text-decoration:none;
    transition: transform .3s var(--ease-spring), box-shadow .3s, background .2s;
}
.btn-primary { background:#fff; color:#08223a; box-shadow: 0 12px 34px rgba(0,0,0,.28); }
.btn-primary:hover { transform: translateY(-3px); box-shadow: 0 18px 40px rgba(0,0,0,.35); }
.btn-primary span[aria-hidden] { transition: transform .3s var(--ease-spring); }
.btn-primary:hover span[aria-hidden] { transform: translateX(4px); }
.btn-ghost { color:#eaf4fc; border: 1px solid rgba(255,255,255,.28); background: rgba(255,255,255,.05); }
.btn-ghost:hover { background: rgba(255,255,255,.12); transform: translateY(-3px); }
.hero-meta { display:flex; flex-wrap:wrap; gap:10px; margin-top: 40px; animation: fadeUp .9s var(--ease-out) .7s both; }
.hero-chip {
    display:flex; flex-direction:column; gap:5px;
    padding: 12px 18px; border-radius: 12px;
    background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.12);
    -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
    min-width: 130px;
}
.chip-k { font-size:.78em; letter-spacing:.1em; text-transform:uppercase; opacity:.78; font-weight:800; }
html[lang^="zh"] .chip-k { letter-spacing:.06em; }
/* 時間數字字距拉開（中英文一致），日期與時間之間再多留一點空 */
.chip-v, html[lang^="zh"] .chip-v { font-size: 1.5em; font-weight: 850; letter-spacing: .035em; white-space: nowrap; }
/* 日期縮小變淡，時間才是主角；手機半寬卡片才放得下 */
.chip-date { font-size: .62em; font-weight: 750; opacity: .7; letter-spacing: .04em; margin-right: .25em; }
.scroll-cue { position:absolute; left:50%; bottom: 58px; z-index:1; width: 24px; height: 38px; margin-left:-12px; border: 2px solid rgba(255,255,255,.35); border-radius: 14px; animation: fadeUp 1s var(--ease-out) 1.2s both; }
.scroll-cue span { position:absolute; left:50%; top:7px; width:4px; height:8px; margin-left:-2px; border-radius:2px; background:#fff; animation: cue 1.8s ease-in-out infinite; }
@keyframes cue { 0% { opacity:0; transform: translateY(0); } 30% { opacity:1; } 100% { opacity:0; transform: translateY(14px); } }
@keyframes fadeUp { from { opacity:0; transform: translateY(16px); } to { opacity:1; transform:none; } }

/* ── Section heads ──────────────────────────────────────────── */
.section-head { display:flex; align-items:flex-end; justify-content:space-between; gap:12px; margin-top: 10px; }
.section-head h3 { font-size: 1.45em; font-weight: 800; letter-spacing: -.02em; }
.kicker { font-size: .72em; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; color: var(--accent); margin-bottom: 4px; }
html[lang^="zh"] .kicker { letter-spacing:.06em; }
.count-chip { background: var(--accent-lo); color: var(--accent); border-radius: 999px; padding: 4px 12px; font-weight: 800; font-size: .9em; }
.legend-inline { display:flex; align-items:center; gap:7px; font-size:.78em; color: var(--text-3); font-weight:600; }
.page-head { padding-top: 8px; }
.page-title { font-size: clamp(1.6rem, 3.2vw, 2.4rem); font-weight: 850; letter-spacing: -.025em; line-height:1.15; max-width: 28ch; }
/* 中文標題：行距拉開、字距微開，兩行時不會擠在一起 */
html[lang^="zh"] .page-title { letter-spacing: .05em; line-height: 1.38; }
html[lang^="zh"] .section-head h3, html[lang^="zh"] .empty-title,
html[lang^="zh"] .brand-text h1 { letter-spacing: .05em; }
.page-lead { margin-top: 10px; color: var(--text-2); max-width: 70ch; line-height: 1.7; }

/* ── Storm tiles (overview) ─────────────────────────────────── */
.storm-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr)); gap: 20px; }
.storm-tile {
    position:relative; display:flex; flex-direction:column; gap:14px;
    text-decoration:none; color:inherit;
    background: var(--surface); border:1px solid var(--border); border-radius: 20px;
    padding: 24px; overflow:hidden; box-shadow: var(--shadow-md);
    transition: transform .5s var(--ease-out), box-shadow .4s, border-color .3s, opacity .8s var(--ease-out);
    will-change: transform;
}
.storm-tile::before { content:""; position:absolute; left:0; right:0; top:0; height:4px; background: var(--cat); }
.storm-tile::after {
    content:""; position:absolute; right:-90px; top:-90px; width:300px; height:300px; border-radius:50%;
    background: radial-gradient(circle, var(--cat), transparent 65%); opacity:.14; pointer-events:none;
    transition: opacity .4s, transform .8s var(--ease-out);
}
.storm-tile:hover { box-shadow: var(--shadow-lg); border-color: var(--cat); }
.storm-tile:hover::after { opacity:.26; transform: scale(1.2); }
.tile-top { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
.tile-body { display:grid; grid-template-columns: 1fr minmax(150px, 190px); gap: 16px; align-items:center; }
.tile-name { font-size: 2em; font-weight: 850; letter-spacing: -.03em; line-height:1.05; overflow-wrap:anywhere; }
.tile-catname { color: var(--text-3); font-weight: 650; font-size: .88em; margin-top: 4px; }
.tile-facts { margin-top: 14px; display:grid; gap: 7px; font-size: .84em; }
.tile-facts div { display:flex; gap: 10px; }
.tile-facts dt { color: var(--text-3); min-width: 72px; font-weight: 600; }
.tile-facts dd { font-weight: 700; white-space: nowrap; overflow:hidden; text-overflow: ellipsis; min-width:0; }
.tile-facts dd.tile-models { white-space: normal; overflow: visible; }
.tile-models span { white-space: nowrap; }
.tile-cta { font-weight: 750; font-size: .88em; color: var(--accent); transition: transform .3s var(--ease-spring); display:inline-block; }
.storm-tile:hover .tile-cta, .genesis-teaser:hover .tile-cta { transform: translateX(6px); }

.empty-card {
    display:flex; align-items:center; gap: 26px;
    background: var(--surface); border: 1px dashed var(--border); border-radius: 20px;
    padding: 28px; box-shadow: var(--shadow);
}
.empty-title { font-size: 1.3em; font-weight: 800; }
.empty-desc { color: var(--text-2); margin-top: 6px; line-height:1.6; font-size:.92em; }
.calm-sea { position:relative; width: 92px; height: 60px; flex-shrink:0; overflow:hidden; border-radius: 14px; background: linear-gradient(180deg, rgba(var(--accent-rgb),.08), rgba(var(--accent-rgb),.18)); }
.calm-sea span { position:absolute; left:-50%; width:200%; height: 12px; border-radius: 50%; border-top: 2px solid rgba(var(--accent-rgb),.55); animation: wave 4s ease-in-out infinite; }
.calm-sea span:nth-child(1) { top: 16px; }
.calm-sea span:nth-child(2) { top: 28px; animation-delay: -1.3s; opacity:.7; }
.calm-sea span:nth-child(3) { top: 40px; animation-delay: -2.6s; opacity:.45; }
@keyframes wave { 50% { transform: translateX(22%); } }

/* ── Genesis teaser ─────────────────────────────────────────── */
.genesis-teaser {
    display:grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); overflow:hidden;
    background: var(--surface); border: 1px solid var(--border); border-radius: 20px;
    text-decoration:none; color:inherit; box-shadow: var(--shadow-md);
    transition: box-shadow .4s, border-color .3s, transform .5s var(--ease-out), opacity .8s var(--ease-out);
}
.genesis-teaser:hover { box-shadow: var(--shadow-lg); border-color: var(--warn); transform: translateY(-3px); }
.teaser-img { position:relative; overflow:hidden; min-height: 220px; background: var(--surface-2); }
.teaser-img img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; animation: kenburns 26s ease-in-out infinite alternate; }
@keyframes kenburns { from { transform: scale(1.05) translate(0,0); } to { transform: scale(1.22) translate(-4%, 2%); } }
.teaser-body { padding: 26px; display:flex; flex-direction:column; gap: 14px; justify-content:center; border-left: 4px solid var(--warn); }
.teaser-body p { color: var(--text-2); line-height: 1.65; }
.mini-chips { display:flex; flex-wrap:wrap; gap:6px; }
.mini-chip { font-size: .74em; font-weight: 750; padding: 4px 10px; border-radius: 999px; background: var(--surface-2); border:1px solid var(--border); color: var(--text-2); }

/* ── Model cards ────────────────────────────────────────────── */
.model-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
.model-card { background: var(--surface); border:1px solid var(--border); border-radius: 14px; padding: 16px 18px; box-shadow: var(--shadow); transition: transform .35s var(--ease-out), box-shadow .3s, opacity .8s var(--ease-out); }
.model-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-md); }
.model-name { display:flex; align-items:center; justify-content:space-between; font-weight: 800; font-size: 1.05em; }
.model-org { margin-top: 6px; font-size: .78em; color: var(--accent); font-weight: 700; }
.model-desc { margin-top: 2px; font-size: .78em; color: var(--text-3); }
.model-state { width:9px; height:9px; border-radius:50%; background: var(--border); display:inline-block; }
.model-card.on .model-state, .model-state.on { background: var(--ok); box-shadow: 0 0 0 3px rgba(31,169,126,.2); animation: pulse-green 2.2s ease-in-out infinite; }
@keyframes pulse-green { 0%,100% { box-shadow: 0 0 0 2px rgba(31,169,126,.25); } 50% { box-shadow: 0 0 0 6px rgba(31,169,126,.05); } }

/* ── Storm page ─────────────────────────────────────────────── */
.storm-switch { display:flex; gap:8px; flex-wrap:wrap; }
.switch-chip { display:flex; align-items:center; gap:8px; padding: 8px 14px; border-radius: 999px; background: var(--surface); border:1px solid var(--border); color: var(--text-2); text-decoration:none; font-weight:700; font-size:.86em; transition: all .25s; }
.switch-chip:hover { color: var(--text); border-color: var(--accent); }
.switch-chip.active { color: var(--accent); border-color: var(--accent); background: var(--accent-lo); }
.storm-hero {
    position:relative; overflow:hidden; isolation:isolate;
    display:grid; grid-template-columns: 1fr minmax(200px, 280px); gap: 24px; align-items:center;
    padding: 36px 38px; border-radius: 24px; color:#eaf4fc;
    background: radial-gradient(700px 380px at 85% 50%, color-mix(in srgb, var(--cat) 26%, transparent), transparent 70%),
                linear-gradient(135deg, var(--hero-1), var(--hero-2) 55%, #0b2f4f);
    box-shadow: var(--shadow-lg);
}
.storm-hero .swirl {
    position:absolute; z-index:-1; right: -160px; top: 50%; width: 620px; height: 620px; margin-top:-310px; border-radius:50%;
    background: conic-gradient(from 0deg, transparent 0 12%, var(--cat) 22%, transparent 36%, transparent 50%, var(--cat) 72%, transparent 86%);
    opacity: .22; filter: blur(34px);
    -webkit-mask: radial-gradient(circle, transparent 10%, #000 34%, transparent 70%);
            mask: radial-gradient(circle, transparent 10%, #000 34%, transparent 70%);
    animation: spin 22s linear infinite;
}
.storm-subtitle { font-size: .76em; color: rgba(234,244,252,.62); font-weight: 700; text-transform: uppercase; letter-spacing: .14em; }
html[lang^="zh"] .storm-subtitle { text-transform:none; letter-spacing: .04em; }
.storm-title { font-size: clamp(2.4rem, 6vw, 4.2rem); font-weight: 850; letter-spacing: -.035em; line-height: 1.02; margin: 10px 0 18px; overflow-wrap:anywhere; text-shadow: 0 0 50px var(--cat); }
.storm-badges { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.badge-cat { padding: 6px 13px; border-radius: 8px; font-size: .82em; font-weight: 800; letter-spacing: .5px; }
.badge-id { background: var(--surface-3); border: 1px solid var(--border); color: var(--text-2); padding: 6px 12px; border-radius: 8px; font-size: .82em; font-weight: 700; font-family: 'Cascadia Mono','Consolas','Courier New', monospace; }
.storm-hero .badge-id, .storm-hero .badge-name { background: rgba(255,255,255,.08); border-color: rgba(255,255,255,.16); color: #eaf4fc; }
.badge-name { padding: 6px 12px; border-radius: 8px; font-size: .8em; font-weight: 700; border: 1px solid; }
.badge-live { background: rgba(220,58,78,.12); border: 1px solid rgba(220,58,78,.34); color: var(--danger); padding: 6px 12px; border-radius: 8px; font-size: .8em; font-weight: 750; display:flex; align-items:center; gap:6px; letter-spacing:.4px; }
.storm-hero .badge-live { color: #ff8a98; }
.live-dot { width:7px; height:7px; border-radius:50%; background: currentColor; animation: pulse-red 1.4s ease-in-out infinite; }
.eyebrow .live-dot { background: #ff6b7d; box-shadow: 0 0 10px #ff6b7d; }
@keyframes pulse-red { 0%,100% { opacity:1; transform:scale(1); } 50% { opacity:.45; transform:scale(.75); } }

/* 風速儀表（SVG 由腳本產生） */
.gauge { position:relative; width:100%; max-width: 280px; aspect-ratio: 200 / 128; margin: 0 auto; }
.gauge svg { width:100%; height:100%; overflow:visible; display:block; }
.g-track { fill:none; stroke: var(--surface-3); stroke-width: 13; stroke-linecap: round; }
.storm-hero .g-track { stroke: rgba(255,255,255,.1); }
.g-band { fill:none; stroke-width: 4; opacity: .75; }
.g-prog { fill:none; stroke: var(--cat); stroke-width: 13; stroke-linecap: round; stroke-dasharray: 100; stroke-dashoffset: 100; transition: stroke-dashoffset 1.8s var(--ease-out); filter: drop-shadow(0 0 6px var(--cat)); }
.g-needle { transform-origin: 100px 100px; transition: transform 1.8s var(--ease-spring); }
.g-needle line { stroke: var(--text); stroke-width: 3.5; stroke-linecap: round; }
.storm-hero .g-needle line { stroke:#fff; }
.g-tick { font-size: 8.5px; fill: var(--text-3); font-weight: 700; font-family: inherit; }
.storm-hero .g-tick { fill: rgba(234,244,252,.5); }
.gauge-val { position:absolute; left:0; right:0; bottom: -2px; text-align:center; line-height:1; }
.gauge-val b { font-size: 2.1em; font-weight: 850; letter-spacing: .05em; margin-left: .05em; }
.gauge-lg .gauge-val b { font-size: 2.8em; }
.gauge-val small { display:block; font-size: .72em; font-weight: 750; opacity: .6; margin-top: 3px; letter-spacing: .1em; }

.stat-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.stat { background: var(--surface); border:1px solid var(--border); border-radius: 14px; padding: 16px 18px; box-shadow: var(--shadow); min-width:0; transition: transform .35s var(--ease-out), box-shadow .3s, opacity .8s var(--ease-out); }
.stat:hover { transform: translateY(-3px); box-shadow: var(--shadow-md); }
.stat-label { font-size: .7em; text-transform: uppercase; letter-spacing: .9px; color: var(--text-3); font-weight: 750; margin-bottom: 8px; }
html[lang^="zh"] .stat-label { letter-spacing: .04em; }
.stat-value { font-size: 1.35em; font-weight: 800; line-height: 1.2; overflow-wrap:anywhere; font-variant-numeric: tabular-nums; }
.stat-value small { font-size: .56em; color: var(--text-3); font-weight: 750; margin-left: 4px; }

.scale-panel { padding: 18px 24px 26px; }
.scale-head { display:flex; justify-content:space-between; align-items:center; font-weight: 750; font-size: .9em; color: var(--text-2); margin-bottom: 14px; }
.scale-now { color: var(--text); font-weight: 850; }
.ss-scale { position:relative; padding-top: 4px; }
.ss-bar { display:flex; gap:3px; height: 30px; }
.ss-seg { position:relative; background: var(--c); border-radius: 6px; opacity: .28; display:flex; align-items:center; justify-content:center; transition: opacity .6s, transform .6s var(--ease-spring); min-width:0; }
.ss-seg em { font-style: normal; font-size: .7em; font-weight: 800; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,.35); white-space:nowrap; overflow:hidden; }
.ss-scale.in .ss-seg { opacity: .55; }
.ss-scale.in .ss-seg.cur { opacity: 1; transform: scaleY(1.22); box-shadow: 0 0 18px var(--c); }
.ss-marker { position:absolute; top: -8px; left: 0; width: 0; height: 50px; transition: left 1.6s var(--ease-out) .2s; }
.ss-scale.in .ss-marker { left: var(--pos); }
.ss-marker span { position:absolute; left:-2px; top: 0; width: 4px; height: 100%; border-radius: 2px; background: var(--text); box-shadow: 0 0 0 3px var(--surface), 0 0 14px var(--cat); }
.ss-marker span::before { content:""; position:absolute; left: 50%; top: -7px; width: 12px; height: 12px; margin-left:-6px; border-radius: 50%; background: var(--cat); box-shadow: 0 0 0 3px var(--surface); }

/* 段落導覽（黏在頁首下方，捲動時標示目前段落） */
.subnav {
    position: sticky; top: calc(var(--header-h) + 10px); z-index: 50;
    display:flex; gap: 4px; padding: 5px; margin: 0 auto;
    width: max-content; max-width: 100%; overflow-x:auto; scrollbar-width:none;
    background: var(--glass); -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px);
    border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow-md);
}
.subnav::-webkit-scrollbar { display:none; }
.subnav:empty { display:none; }
.subnav button { border:0; background:transparent; color: var(--text-2); padding: 8px 15px; border-radius: 10px; font-weight: 700; font-size: .84em; cursor:pointer; white-space:nowrap; transition: background .3s, color .3s; }
.subnav button:hover { color: var(--text); }
.subnav button.active { background: var(--btn-bg); color:#fff; box-shadow: 0 4px 14px rgba(var(--accent-rgb),.3); }
.subnav button[hidden] { display:none; }

/* ── Panels ─────────────────────────────────────────────────── */
.panel { background: var(--surface); border:1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-md); padding: 22px 24px; min-width:0; transition: background .35s, border .35s, opacity .8s var(--ease-out), transform .8s var(--ease-out); scroll-margin-top: calc(var(--header-h) + 80px); }
.maps-grid { scroll-margin-top: calc(var(--header-h) + 80px); }
.panel-header { display:flex; align-items:center; gap:10px; flex-wrap: wrap; font-size: 1.05em; font-weight: 750; margin-bottom: 16px; padding-bottom: 13px; border-bottom: 1px solid var(--border); }
.panel-icon { width: 32px; height: 32px; border-radius: 9px; display:inline-flex; align-items:center; justify-content:center; background: var(--surface-2); border:1px solid var(--border); font-size: .95em; }
.panel-aside { margin-left:auto; }
.maps-grid { display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 24px; }
.city-table-wrap { overflow-x: auto; margin-bottom: 6px; }
.city-table { width: 100%; border-collapse: separate; border-spacing: 3px; font-size: .86em; font-variant-numeric: tabular-nums; }
.city-table th { color: var(--text-2); font-weight: 750; padding: 6px 8px; text-align: center; white-space: nowrap; }
.city-table td { padding: 6px 8px; text-align: center; border-radius: 7px; white-space: nowrap; font-weight: 750; }
.city-table th:first-child, .city-table td.c-name { text-align: left; }
.city-table td.c-name { color: var(--text); background: none; }
/* 「臺灣本島」字數比城市名多，縮小一點免得把第一欄撐寬 */
.city-table td.c-name[data-i18n="city.tw_landfall"] { font-size: .82em; }
.city-table td.c-nil { color: var(--text-2); background: var(--surface-2); font-weight: 500; }
.track-map .tm-controls { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; margin-bottom: 10px; font-size: .88em; color: var(--text-2); }
.track-map select { background: var(--surface-2); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font: inherit; font-weight: 700; }
.track-map .tm-init { color: var(--text-2); }
.track-map .tm-init b { color: var(--text); font-weight: 750; }
.track-map label { display: inline-flex; gap: 6px; align-items: center; cursor: pointer; }
.track-map .tm-chips { display: none; flex-wrap: wrap; gap: 6px; }
.track-map.tm-cmp .tm-chips { display: inline-flex; }
.track-map.tm-cmp .tm-model { display: none; }
.track-map .tm-chip { display: inline-flex; align-items: center; gap: 6px; padding: 5px 11px; border-radius: 999px; border: 1px solid var(--border); background: transparent; color: var(--text-2); font: inherit; font-weight: 600; cursor: pointer; transition: all .2s; }
.track-map .tm-chip i { width: 9px; height: 9px; border-radius: 50%; background: var(--border); }
.track-map .tm-chip:hover { color: var(--text); border-color: var(--text); }
.track-map .tm-chip[aria-pressed="true"] { color: var(--text); border-color: var(--c); }
.track-map .tm-chip[aria-pressed="true"] i { background: var(--c); }
.track-map .tm-chip-all i { display: none; }
.track-map .tm-chip-all[aria-pressed="true"] { background: var(--text); color: var(--bg); border-color: var(--text); }
.track-map .tm-cmp-btn { padding: 6px 12px; box-shadow: none; }
.track-map .tm-chip.tm-na { opacity: .35; text-decoration: line-through; cursor: not-allowed; }
.track-map .tm-msg { position: absolute; left: 50%; top: 14px; transform: translateX(-50%); z-index: 1000; padding: 7px 14px; border-radius: 999px; background: var(--text); color: var(--bg); font-size: .85em; font-weight: 600; pointer-events: none; white-space: nowrap; }
.track-map .tm-map { height: min(68vh, 560px); border-radius: 12px; overflow: hidden; border: 1px solid var(--border); background: var(--surface-2); }
.score-table td { font-weight: 750; }
.score-table td.c-low { background: var(--surface-2); color: var(--text-2); opacity: .55; font-weight: 600; }
.score-table td.c-detname { color: #E8963A; }
.score-table td.c-ref { background: var(--surface-2); color: var(--text); }
.score-chart { margin: 4px 0 14px; }
.score-chart svg { width: 100%; height: auto; display: block; }
.score-chart .sc-axis { font-size: .78em; color: var(--text-2); margin-bottom: 2px; }
.score-chart .sc-legend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: .8em; color: var(--text-2); margin-top: 4px; }
.score-chart .sc-legend i { display: inline-block; width: 14px; height: 3px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }
.city-table th .eta { display: block; font-size: .78em; font-weight: 500; opacity: .75; }
/* 決定報：外框＋琥珀字，不用實心色塊，免得跟 60–70% 的橘色機率格混淆 */
.city-table td.c-det { background: var(--surface-2); color: #E8963A; box-shadow: inset 0 0 0 2px #B45309; }
.city-table tr.grp td { text-align: left; background: none; color: var(--text); font-weight: 800;
    padding: 12px 6px 6px; border-bottom: 1px solid var(--border); }
.city-table tr.grp:first-child td { padding-top: 2px; }
.city-table tr.grp small { margin-left: 10px; color: var(--text-2); font-weight: 500; font-size: .86em; }
.city-table td .eta { display: block; font-size: .78em; font-weight: 500; opacity: .85; }
.model-label { display:inline-block; font-weight: 800; font-size:.82em; padding: 6px 12px; border-radius: 8px; background: var(--accent-lo); color: var(--accent); margin-bottom: 14px; }

/* 模式分頁：滑動的底色指示塊 */
.seg { position:relative; display:inline-flex; flex-wrap:wrap; gap: 3px; padding: 4px; background: var(--surface-2); border:1px solid var(--border); border-radius: 13px; margin-bottom: 16px; max-width:100%; }
.seg-ind { position:absolute; left:0; top:0; z-index:0; border-radius: 10px; background: var(--btn-bg); box-shadow: 0 4px 14px rgba(var(--accent-rgb),.32); opacity:0; transition: transform .5s var(--ease-out), width .5s var(--ease-out), height .5s var(--ease-out), opacity .2s; }
.seg.ready .seg-ind { opacity:1; }
.model-tab-btn { position:relative; z-index:1; border:0; background: transparent; color: var(--text-2); padding: 8px 17px; border-radius: 10px; font-size: .86em; font-weight: 750; letter-spacing: .2px; cursor:pointer; transition: color .3s; }
.model-tab-btn:hover { color: var(--text); }
.model-tab-btn.active { color: #fff; }
.seg:not(.ready) .model-tab-btn.active { background: var(--btn-bg); }
.model-panel.swap-in { animation: swapIn .5s var(--ease-out); }
@keyframes swapIn { from { opacity:0; transform: translateY(8px) scale(.995); } to { opacity:1; transform:none; } }

/* ── Images ─────────────────────────────────────────────────── */
.run-picks { display:flex; flex-wrap:wrap; gap: 6px; margin-bottom: 12px; }
.run-btn { padding: 5px 11px; border-radius: 999px; border: 1px solid var(--border); background: transparent; color: var(--text-2); font: inherit; font-size: .8em; font-weight: 600; cursor: pointer; transition: all .2s; }
.run-btn:hover { color: var(--text); border-color: var(--text); }
.run-btn.active { background: var(--text); color: var(--bg); border-color: var(--text); }
.off-table td.c-off { font-variant-numeric: tabular-nums; white-space: nowrap; }
.score-more { margin: 28px 0 10px; font-size: 1em; font-weight: 750; }
/* ── 颱風歷史存檔 ── */
.arch-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; margin: 18px 0 22px; }
.arch-card { position:relative; display:flex; flex-direction:column; gap: 7px; text-align:left; padding: 16px 18px 15px; border: 1px solid var(--border); border-top: 3px solid var(--cat); border-radius: var(--radius); background: var(--surface); color: var(--text); font: inherit; cursor: pointer; transition: border-color .2s, transform .2s, box-shadow .2s; }
.arch-card:hover { border-color: var(--cat); transform: translateY(-2px); box-shadow: var(--shadow-md); }
.arch-card.active { border-color: var(--text); box-shadow: inset 0 0 0 1px var(--text); }
.arch-top { display:flex; align-items:center; justify-content:space-between; gap: 8px; }
.arch-name { font-size: 1.35em; font-weight: 800; letter-spacing: -.01em; }
.arch-meta { color: var(--text-2); font-size: .82em; display:flex; align-items:center; gap: 6px; flex-wrap: wrap; }
.arch-meta .badge-cat { padding: 3px 8px; font-size: .9em; }
.arch-live { font-size: .7em; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; color: var(--bg); background: var(--accent); padding: 3px 7px; border-radius: 6px; }
.arch-detail { scroll-margin-top: calc(var(--header-h) + 20px); }
.arch-controls { display:flex; align-items:center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.arch-slider { flex: 1 1 220px; min-width: 160px; accent-color: var(--accent); }
.arch-detail .arch-map { height: min(68vh, 560px); border-radius: 12px; overflow: hidden; border: 1px solid var(--border); background: var(--surface-2); }
.arch-score { margin-top: 22px; }
.arch-trend:not(:empty) { margin-top: 26px; }
.arch-sub { font-size: 1.05em; font-weight: 700; margin-bottom: 12px; }
.zoomable { position:relative; border-radius: 12px; overflow:hidden; cursor: zoom-in; background: var(--surface-2); border: 1px solid var(--border); }
.zoomable.skel:not(.loaded) { min-height: 240px; }
.zoomable.skel:not(.loaded)::before {
    content:""; position:absolute; inset:0;
    background: linear-gradient(100deg, transparent 30%, rgba(var(--accent-rgb),.12) 50%, transparent 70%);
    background-size: 220% 100%; animation: shimmer 1.3s linear infinite;
}
@keyframes shimmer { from { background-position: 120% 0; } to { background-position: -120% 0; } }
.zoomable > img { display:block; width:100%; height:auto; }
/* 圖片高度不超過視窗（扣掉頁首與一點留白），寬螢幕上整張圖一眼看得完；
   載入後外框縮到圖片寬度並置中，不會留一大片空白 */
.zoomable > img:not(.frame) { width:auto; max-width:100%; max-height: calc(100vh - var(--header-h) - 150px); margin-inline:auto; }
.zoomable.loaded:not(.frame-stage):not(.broken) { width: fit-content; max-width: 100%; margin-inline: auto; }
.js .zoomable > img:not(.frame) { opacity: 0; transform: scale(1.02); transition: opacity .7s ease, transform .9s var(--ease-out); }
.js .zoomable.loaded > img:not(.frame) { opacity: 1; transform: none; }
.zoomable.loaded:hover > img:not(.frame) { transform: scale(1.01); }
.zoomable.broken { cursor: default; min-height: 160px; }
.zoomable.broken > img { visibility:hidden; }
.zoomable.broken::after { content: var(--broken-text); position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color: var(--text-3); font-weight: 650; font-size:.9em; }
.zoomable.broken .zoom-hint { display:none; }
.zoom-hint { position:absolute; bottom:10px; right:10px; background: rgba(4,17,30,.7); color:#fff; padding: 5px 11px; border-radius: 8px; font-size: .73em; font-weight: 600; opacity:0; transform: translateY(4px); transition: opacity .25s, transform .25s; pointer-events:none; -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px); }
.zoomable:hover .zoom-hint { opacity:1; transform:none; }
.map-note { margin-top: 12px; color: var(--text-3); font-size: .82em; line-height: 1.65; }

/* ── Animation player ───────────────────────────────────────── */
.player { background: var(--surface-2); border:1px solid var(--border); border-radius: 14px; overflow:hidden; }
.frame-stage { border:0; border-radius:0; aspect-ratio: var(--ar, 16 / 10); max-height: calc(100vh - var(--header-h) - 190px); width: 100%; }
.frame-stage .frame { position:absolute; inset:0; width:100%; height:100%; object-fit: contain; opacity:0; }
/* 新的一格疊在上面淡入、上一格在底下維持不透明：交叉淡化時兩張都半透明會透出底色，看起來像閃一下 */
.frame-stage .frame.is-front { opacity:1; z-index:2; transition: opacity .18s linear; }
.frame-stage .frame.was-front { opacity:1; z-index:1; }
.frame-stage.broken .frame { visibility:hidden; }
.buffer { position:absolute; left:0; right:0; bottom:0; height: 3px; background: rgba(var(--accent-rgb),.12); transition: opacity .6s .4s; }
.buffer span { display:block; height:100%; background: var(--accent); transform-origin: 0 50%; transform: scaleX(0); transition: transform .3s; }
.frame-stage.buffered .buffer { opacity:0; }
.player-controls { display:flex; align-items:center; gap: 8px; flex-wrap: wrap; padding: 12px 14px; background: var(--surface); border-top: 1px solid var(--border); }
.pc-btn { width: 38px; height: 38px; flex-shrink:0; display:inline-flex; align-items:center; justify-content:center; border-radius: 11px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); cursor:pointer; transition: transform .25s var(--ease-spring), background .2s, color .2s; }
.pc-btn svg { width: 18px; height: 18px; }
.pc-btn:hover { color: var(--accent); border-color: var(--accent); }
.pc-btn:active { transform: scale(.9); }
.pc-main { width: 46px; height: 46px; border-radius: 50%; border:0; background: var(--btn-bg); color:#fff; box-shadow: 0 6px 18px rgba(var(--accent-rgb),.38); }
.pc-main:hover { color:#fff; transform: scale(1.06); }
.pc-main svg { width: 20px; height: 20px; }
.ic-pause { display:none; }
.player.playing .ic-play { display:none; }
.player.playing .ic-pause { display:inline-flex; }
.ic-play, .ic-pause { display:inline-flex; }
.player.playing .pc-main { animation: glowPulse 2s ease-in-out infinite; }
@keyframes glowPulse { 50% { box-shadow: 0 6px 26px rgba(var(--accent-rgb),.6); } }
.timeline-wrap { flex: 1; min-width: 140px; display:flex; align-items:center; }
.timeline { width:100%; -webkit-appearance:none; appearance:none; height: 6px; border-radius: 3px; cursor:pointer; outline-offset: 6px;
    background: linear-gradient(90deg, var(--accent) 0 var(--fill, 0%), var(--border) var(--fill, 0%) 100%); }
.timeline::-webkit-slider-thumb { -webkit-appearance:none; appearance:none; width: 18px; height: 18px; border-radius: 50%; background: #fff; border: 3px solid var(--accent); box-shadow: 0 2px 8px rgba(0,0,0,.25); transition: transform .2s var(--ease-spring); }
.timeline::-moz-range-thumb { width: 14px; height: 14px; border-radius: 50%; background: #fff; border: 3px solid var(--accent); }
.timeline:active::-webkit-slider-thumb { transform: scale(1.25); }
.frame-counter { font-size: .8em; color: var(--text-3); font-weight: 700; min-width: 52px; text-align: right; }
.speed-seg { display:inline-flex; gap: 2px; padding: 3px; border-radius: 10px; background: var(--surface-2); border:1px solid var(--border); }
.speed-btn { border:0; background: transparent; color: var(--text-3); font-weight: 800; font-size: .76em; padding: 5px 9px; border-radius: 7px; cursor:pointer; transition: all .2s; }
.speed-btn.active { background: var(--surface); color: var(--accent); box-shadow: var(--shadow); }
.kbd-hint { font-size: .7em; color: var(--text-3); font-weight: 600; display:none; }
kbd { background: var(--surface-3); border: 1px solid var(--border); border-bottom-width: 2px; border-radius: 5px; padding: 1px 6px; font-family: 'Cascadia Mono','Consolas','Courier New', monospace; font-size: .9em; }

/* ── Genesis page ───────────────────────────────────────────── */
.genesis-panel { border-top: 4px solid var(--warn); }
.genesis-toolbar { display:flex; align-items:flex-start; justify-content:space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
/* 間距統一由工具列負責：比較模式會把模式分頁藏起來，不能靠分頁自己的下邊距 */
.genesis-toolbar .seg { margin-bottom: 0; }
.genesis-toolbar:empty { display:none; }
.genesis-legend { margin-top: 14px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
.ghost-btn { display:inline-flex; align-items:center; gap: 8px; padding: 9px 15px; border-radius: 11px; border:1px solid var(--border); background: var(--surface); color: var(--text-2); font-weight: 750; font-size:.85em; cursor:pointer; transition: all .25s; box-shadow: var(--shadow); }
.ghost-btn svg { width: 17px; height: 17px; }
.ghost-btn:hover { color: var(--accent); border-color: var(--accent); }
.ghost-btn[aria-pressed="true"] { background: var(--btn-bg); color:#fff; border-color: transparent; }
.genesis-panel.comparing .genesis-single, .genesis-panel.comparing .genesis-tabs { display:none; }
.compare { animation: swapIn .5s var(--ease-out); }
.compare-pickers { display:flex; align-items:center; justify-content:space-between; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; padding-top: 16px; border-top: 1px solid var(--border); }
.compare-pickers label { display:flex; align-items:center; gap: 8px; }
.compare-pickers select { font: inherit; font-weight: 750; font-size: .88em; padding: 7px 12px; border-radius: 10px; border:1px solid var(--border); background: var(--surface-2); color: var(--text); cursor:pointer; }
.compare-hint { font-size: .8em; color: var(--text-3); font-weight: 600; }
.pick-dot { width: 12px; height: 12px; border-radius: 4px; }
.pick-dot.a { background: var(--accent); }
.pick-dot.b { background: var(--warn); }
.cmp-stage { position:relative; overflow:hidden; border-radius: 12px; border:1px solid var(--border); cursor: ew-resize; touch-action: pan-y; user-select:none; background: var(--surface-2); }
.cmp-stage img { display:block; width:100%; height:auto; pointer-events:none; }
/* 與其他圖一樣限高置中：外框縮到底圖寬度，上層圖跟著外框大小走 */
.cmp-stage { width: fit-content; max-width: 100%; margin-inline: auto; }
.cmp-stage .cmp-base { width:auto; max-width:100%; max-height: calc(100vh - var(--header-h) - 150px); }
.cmp-top { position:absolute; inset:0; clip-path: inset(0 50% 0 0); }
.cmp-top img { width:100%; height:100%; object-fit: cover; object-position: left top; }
.cmp-handle { position:absolute; top:0; bottom:0; left: 50%; width: 0; }
.cmp-handle::before { content:""; position:absolute; top:0; bottom:0; left:-1.5px; width: 3px; background: #fff; box-shadow: 0 0 12px rgba(0,0,0,.4); }
.cmp-handle span { position:absolute; top:50%; left: -22px; width: 44px; height: 44px; margin-top:-22px; border-radius:50%; background:#fff; color: #16324f; display:flex; align-items:center; justify-content:center; box-shadow: 0 6px 20px rgba(0,0,0,.35); transition: transform .25s var(--ease-spring); }
.cmp-handle span svg { width: 22px; height: 22px; }
.cmp-stage:active .cmp-handle span { transform: scale(1.12); }

/* ── About page ─────────────────────────────────────────────── */
.about-grid { display:grid; grid-template-columns: minmax(0, 1fr); gap: 20px; align-items:start; }
.scale-table { display:grid; gap: 8px; }
/* 寬螢幕兩欄：「圖面說明」很長，獨佔右欄；強度分級、快捷鍵、App、注意事項依序疊在左欄。
   最後一列 1fr 吸收右欄多出的高度，左欄的字卡才會貼在一起，不會被撐出大片空白。
   窄螢幕一欄，照 HTML 順序（強度分級 → 圖面說明 → 其他）。 */
@media (min-width: 900px) {
    .about-grid { grid-template-columns: minmax(0, 1fr) minmax(0, 1.35fr); grid-template-rows: auto auto auto 1fr; }
    .about-scale { grid-column: 1; grid-row: 1; }
    .about-keys  { grid-column: 1; grid-row: 2; }
    .about-app   { grid-column: 1; grid-row: 3; }
    .about-grid .disclaimer { grid-column: 1; grid-row: 4; }
    .about-read  { grid-column: 2; grid-row: 1 / span 4; }
}
.scale-row { display:grid; grid-template-columns: 70px 1fr auto; align-items:center; gap: 12px; padding: 8px 10px; border-radius: 10px; background: var(--surface-2); font-weight: 650; font-size:.9em; }
.scale-row .badge-cat { text-align:center; }
.read-list { display:grid; gap: 16px; }
.read-list h4 { font-size: .92em; font-weight: 800; }
.read-list .map-note { margin-top: 4px; }
.keys-list { display:grid; gap: 10px; font-size:.9em; }
.keys-list div { display:flex; justify-content:space-between; gap: 12px; align-items:center; padding-bottom: 10px; border-bottom: 1px dashed var(--border); }
.keys-list div:last-child { border-bottom:0; padding-bottom:0; }
.keys-list span:last-child { color: var(--text-2); text-align:right; }
.disclaimer p { color: var(--text-2); line-height:1.7; }

/* ── Lightbox ───────────────────────────────────────────────── */
.lightbox {
    display: none; position: fixed; inset: 0; z-index: 9999;
    background: rgba(0,0,0,.93); cursor: zoom-out;
    align-items: center; justify-content: center; padding: 20px;
}
.lightbox.open { display: flex; }
.lightbox img {
    max-width: 95vw; max-height: 92vh;
    border-radius: 10px; object-fit: contain;
    box-shadow: 0 30px 80px rgba(0,0,0,.6);
}
.lb-close {
    position: absolute; top: 18px; right: 22px;
    background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.2);
    color: #fff; font-size: 1.4em; width: 40px; height: 40px;
    border-radius: 50%; display: flex; align-items: center;
    justify-content: center; cursor: pointer; transition: background .2s;
}
.lb-close:hover { background: rgba(255,255,255,.25); }

/* ── Footer ─────────────────────────────────────────────────── */
footer { border-top: 1px solid var(--border); padding-top: 32px; margin-top: 12px; }
.footer-inner { max-width: 1380px; margin: 0 auto; padding: 0 20px 32px; display:grid; grid-template-columns: 1fr auto; gap: 24px; align-items:start; }
.footer-brand h3 { font-size: 1em; font-weight: 750; margin-bottom: 6px; }
.footer-brand p { font-size: .82em; color: var(--text-3); line-height: 1.65; }
.footer-links { display:flex; flex-direction:column; gap: 8px; align-items:flex-end; }
.footer-link { color: var(--text-2); text-decoration:none; font-size: .83em; font-weight: 550; transition: color .2s; }
.footer-link:hover { color: var(--accent); }
.footer-copy { grid-column: 1 / -1; font-size: .76em; color: var(--text-3); padding-top: 16px; border-top: 1px solid var(--border); }

/* ── Bottom nav (mobile) ────────────────────────────────────── */
.bottom-nav { display:none; }

/* ── Responsive ─────────────────────────────────────────────── */
@media (max-width: 1640px) { .brand-text small { display:none; } }
@media (min-width: 901px) { .kbd-hint { display:inline; } }
@media (max-width: 1100px) {
    .maps-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
    header { padding: 10px 16px; gap: 10px; }
    .top-nav { display:none; }
    .header-brand { flex: 1; }
    .header-actions { width: 100%; justify-content: space-between; flex-wrap: nowrap; }
    .bottom-nav {
        position: fixed; left: 10px; right: 10px; bottom: calc(10px + env(safe-area-inset-bottom)); z-index: 280;
        display:flex; justify-content:space-around; gap: 4px; padding: 6px;
        background: var(--glass); -webkit-backdrop-filter: saturate(1.6) blur(18px); backdrop-filter: saturate(1.6) blur(18px);
        border: 1px solid var(--border); border-radius: 20px; box-shadow: var(--shadow-lg);
        animation: slideUp .6s var(--ease-out) .2s both;
    }
    @keyframes slideUp { from { transform: translateY(120%); } to { transform:none; } }
    .bottom-nav a { position:relative; flex:1; display:flex; flex-direction:column; align-items:center; gap: 3px; padding: 7px 4px; border-radius: 14px; color: var(--text-3); text-decoration:none; font-size: .66em; font-weight: 750; transition: color .25s, background .3s; }
    .bottom-nav a svg { width: 22px; height: 22px; transition: transform .35s var(--ease-spring); }
    .bottom-nav a.active { color: var(--accent); background: var(--accent-lo); }
    .bottom-nav a.active svg { transform: translateY(-1px) scale(1.1); }
    .bn-count { position:absolute; top: 3px; right: calc(50% - 22px); min-width: 16px; height: 16px; padding: 0 4px; border-radius: 8px; background: var(--danger); color:#fff; font-style: normal; font-size: .9em; line-height: 16px; text-align:center; }
    body { padding-bottom: calc(84px + env(safe-area-inset-bottom)); }
    .storm-hero { grid-template-columns: 1fr; padding: 28px 24px; }
    .storm-hero .gauge { max-width: 240px; }
    .genesis-teaser { grid-template-columns: 1fr; }
    .teaser-body { border-left: 0; border-top: 4px solid var(--warn); }
    .hero-inner { padding: 56px 20px 130px; }
}
@media (max-width: 600px) {
    .page { padding: 18px 12px 36px; gap: 18px; }
    header { padding: 10px 12px; }
    .header-brand { width: 100%; min-width: 0; }
    .brand-icon { width: 32px; height: 32px; font-size: 1em; }
    .brand-text h1 { font-size: .95em; }
    .header-actions { gap: 8px; }
    .header-actions { gap: 6px; }
    .update-badge { flex: 1 1 auto; padding: 7px 10px 7px 8px; font-size: .8em; white-space: nowrap; min-width: 0; font-variant-numeric: tabular-nums; }
    .ub-long { display:none; }
    .ring { width: 16px; height: 16px; }
    .theme-btn { flex: 0 0 auto; padding: 7px 11px; font-size: .8em; min-width: 40px; justify-content:center; }
    .theme-btn .bi:not(:empty) + .bt { display:none; }
    #lang-btn .bt { display:none; }
    #lang-btn .bt-short { display:inline; font-weight: 800; }
    #tz-btn .bi, #tz-btn .bt { display:none; }
    #tz-btn .bt-short { display:inline; font-weight: 800; }
    .version-badge { padding: 7px 10px; }
    .hero { min-height: 88vh; }
    .hero-meta { gap: 8px; }
    .hero-chip { min-width: 0; flex: 1 1 40%; padding: 11px 13px; }
    .chip-v, html[lang^="zh"] .chip-v { font-size: 1.4em; }
    .scroll-cue { display:none; }
    .tile-body { grid-template-columns: 1fr; }
    .tile-body .gauge { max-width: 220px; }
    .storm-tile, .panel { padding: 16px; }
    .storm-hero { padding: 24px 18px; border-radius: 20px; }
    .stat-grid { grid-template-columns: 1fr 1fr; gap: 9px; }
    .stat { padding: 13px 14px; }
    .stat-value { font-size: 1.1em; }
    .footer-inner { grid-template-columns: 1fr; }
    .footer-links { align-items: flex-start; }
    .map-note { font-size: .78em; }
    .ss-seg em { font-size: .56em; }
    .player-controls { gap: 6px; padding: 10px; }
    .timeline-wrap { order: 10; flex-basis: 100%; }
    .frame-counter { margin-left: auto; }
    .compare-hint { order: 3; flex-basis: 100%; text-align:center; }
    .empty-card { flex-direction: column; text-align:center; padding: 24px 16px; gap: 18px; }
    html[lang^="zh"] .empty-desc { font-size: .88em; white-space: nowrap; letter-spacing: 0; }
}
@media (max-width: 370px) { .chip-v, html[lang^="zh"] .chip-v { font-size: 1.25em; } }
@media (max-width: 340px) { .chip-v, html[lang^="zh"] .chip-v { font-size: 1.02em; } }
@media (max-width: 340px) { html[lang^="zh"] .empty-desc { white-space: normal; } }
@media (max-width: 380px) {
    .stat-grid { grid-template-columns: 1fr; }
    .badge-cat, .badge-id, .badge-live, .badge-name { padding: 5px 9px; font-size: .72em; }
}

/* ── 3D 地球（v4.1）：固定在整個頁面最底層，WebGL 載好才加 html.has-globe ──
   深色主題時地球一路跟著捲動當背景；淺色主題只在總覽的深色主視覺卡片裡出現，
   由 JS 用 clip-path 裁到 hero 的範圍（含圓角）。 */
#globe {
    position: fixed; inset: 0; width: 100%; height: 100%; z-index: -1;
    pointer-events: none; opacity: 0;
}
[data-theme="light"] #globe { background: #000; }
html.has-globe .hero { background: transparent; }
html.has-globe .hero-canvas, html.has-globe .hero-eye { display: none; }

/* 使用者要求減少動態時：停掉所有非必要的動畫與轉場 */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: .001ms !important; animation-iteration-count: 1 !important; transition-duration: .001ms !important; transition-delay: 0s !important; }
    .split .ch { opacity:1; transform:none; filter:none; }
}

/* ═════════════════════════════════════════════════════════════════
   v6.8「天氣圖室」：預報圖才是內容，頁面是擺圖的桌面
   ═════════════════════════════════════════════════════════════════ */
/* 每張圖放在一張滿版的白色圖紙上（圖本身就是白底），不再是大小不一的白框浮在黑底；
   深色主題整張圖紙調暗一點，不刺眼 */
.zoomable { background: #fff; border: 1px solid var(--border); }
.frame-stage { background: #fff; }
[data-theme="dark"] .zoomable, [data-theme="dark"] .frame-stage { filter: brightness(.9) contrast(1.02); }
[data-theme="dark"] .zoomable.broken { filter: none; background: var(--surface-2); }
.lightbox img { filter: none; }

/* 提醒框（強度分頁：AI 模式強度偏弱） */
.callout { display: flex; gap: 12px; align-items: flex-start; margin: 0 0 16px; padding: 14px 16px; border-radius: 18px;
    background: rgba(238,122,34,.10); border: 1px solid rgba(238,122,34,.32); }
.callout-icon { font-size: 1.05em; line-height: 1.5; flex: 0 0 auto; }
.callout p { margin: 0; font-size: .92em; line-height: 1.6; color: var(--text); }
.sub-head { margin: 18px 0 10px; font-size: 1em; font-weight: 700; color: var(--text); }

/* 只給螢幕閱讀器的文字（表格標題） */
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

/* 颱風頁頂端的白話摘要 */
.i-zh { display: none; }
html[lang^="zh"] .i-zh { display: inline; }
html[lang^="zh"] .i-en { display: none; }
.storm-summary { margin-top: 18px; max-width: 54ch; display: grid; gap: 6px; }
.storm-summary p { font-size: clamp(1rem, 1.5vw, 1.18rem); line-height: 1.55; color: #eaf0f5; font-weight: 400; }
.storm-badges { margin-bottom: 14px; }
.storm-badges .badge-cat { font-family: inherit; text-transform: none; letter-spacing: .02em; }

/* 三組區塊：組標題是結構，不是裝飾；「背景與校驗」預設收合 */
.sec-group { margin-top: 40px; }
.sec-group-title { font-family: var(--display); font-weight: 500; font-size: clamp(1.5rem, 3vw, 2.2rem);
                   letter-spacing: .04em; padding-bottom: 14px; margin-bottom: 22px; border-bottom: 1px solid var(--border); }
html[lang^="zh"] .sec-group-title { letter-spacing: .1em; }
details.sec-group > summary { list-style: none; cursor: pointer; display: flex; align-items: baseline;
                              justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--border); margin-bottom: 22px; }
details.sec-group > summary::-webkit-details-marker { display: none; }
details.sec-group > summary .sec-group-title { border: 0; margin: 0; }
details.sec-group > summary .fold-hint { color: var(--text-2); font-size: .9em; padding-bottom: 14px; }
details.sec-group > summary .fold-hint::after { content: "＋"; margin-left: 10px; }
details.sec-group[open] > summary .fold-hint::after { content: "－"; }
details.sec-group > summary:focus-visible { outline: 2px solid var(--text); outline-offset: 4px; }

/* 城市表：第一欄固定，左右還有內容時邊緣出現陰影 */
.city-table-wrap {
    background:
        linear-gradient(to right, var(--surface) 30%, transparent) left / 40px 100% no-repeat local,
        linear-gradient(to left, var(--surface) 30%, transparent) right / 40px 100% no-repeat local,
        radial-gradient(farthest-side at 0 50%, rgba(var(--accent-rgb),.28), transparent) left / 14px 100% no-repeat scroll,
        radial-gradient(farthest-side at 100% 50%, rgba(var(--accent-rgb),.28), transparent) right / 14px 100% no-repeat scroll;
}
.city-table th:first-child, .city-table td.c-name { position: sticky; left: 0; z-index: 1; background: var(--surface); }
.city-table tr.c-quiet td { text-align: left; color: var(--text-2); font-weight: 500; padding-top: 10px; }
/* 整欄 <1% 的模式預設收起，按鈕展開 */
.city-table-wrap.compact .col-dim { display: none; }
.city-toggle { display: inline-flex; align-items: center; gap: 6px; margin: 2px 0 10px; padding: 6px 2px; border: 0; background: none;
    font: inherit; font-size: .84em; font-weight: 650; color: var(--accent); cursor: pointer; }
.city-toggle::before { content: ''; width: 7px; height: 7px; border-right: 1.8px solid currentColor; border-bottom: 1.8px solid currentColor;
    transform: translateY(-2px) rotate(45deg); transition: transform .25s var(--ease-out); }
.city-toggle[aria-expanded="true"]::before { transform: translateY(1px) rotate(-135deg); }
.city-toggle .ct-less, .city-toggle[aria-expanded="true"] .ct-more { display: none; }
.city-toggle[aria-expanded="true"] .ct-less { display: inline; }
.city-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 6px; }

/* 上方小標（Live、Outlook…）沒有提供資訊，拿掉 */
.kicker { display: none; }

/* 版本號只是給維護者看的，不要當成頁首最醒目的按鈕 */
.version-badge, [data-theme="dark"] .version-badge { background: transparent; color: var(--text-3); border-color: transparent; font-size: .78em; }
@media (max-width: 720px) {
    .version-badge { display: none; }
    .stat-value { font-size: 1.35em; }
    .stat-grid > .stat:first-child { grid-column: 1 / -1; }   /* 觀測時間最長，自己一列，不會折成三行 */
}

/* ═════════════════════════════════════════════════════════════════
   v7「毛玻璃」：參考 iOS 26 Liquid Glass —— 半透明玻璃面板浮在
   柔和的海洋色背景上；面板用 backdrop-filter 模糊＋提高彩度，
   上緣一道高光、大圓角、膠囊形按鈕，字體回到一般大小寫的無襯線字。
   ═════════════════════════════════════════════════════════════════ */
:root, [data-theme="light"] {
    --bg:          #e7eef6;
    --solid:       #eef3f9;          /* 需要不透明底色的地方（表格固定欄） */
    --surface:     rgba(255,255,255,.52);
    --surface-2:   rgba(255,255,255,.42);
    --surface-3:   rgba(110,130,155,.16);
    --accent:      #0a6fdc;
    --accent-2:    #0a6fdc;
    --accent-lo:   rgba(10,111,220,.10);
    --accent-rgb:  10,111,220;
    --text:        #0c1c2d;
    --text-2:      #3f5266;
    --text-3:      #5c6e81;   /* 白底對比 4.7:1（WCAG AA） */
    --border:      rgba(20,45,75,.10);
    --btn-bg:      #0a6fdc;
    --glass:       rgba(255,255,255,.50);
    --glass-hi:    rgba(255,255,255,.72);    /* 較實的玻璃：選單、選取中的膠囊 */
    --glass-line:  rgba(255,255,255,.75);    /* 玻璃外框 */
    --glass-spec:  inset 0 1px 0 rgba(255,255,255,.95), inset 0 0 0 1px rgba(255,255,255,.25);
    --shadow:      0 1px 2px rgba(15,35,60,.05), 0 6px 18px rgba(15,35,60,.07);
    --shadow-md:   0 1px 2px rgba(15,35,60,.05), 0 12px 32px rgba(15,35,60,.09);
    --shadow-lg:   0 2px 6px rgba(15,35,60,.06), 0 24px 60px rgba(15,35,60,.14);
    --blur:        blur(24px) saturate(180%);
    --track:       rgba(118,118,128,.12);   /* iOS 分段控制的底槽 */
    --radius:      26px;
    --display:     'Inter', 'Noto Sans TC', 'PingFang TC', 'Microsoft JhengHei', system-ui, -apple-system, sans-serif;
    --hero-1: #071528; --hero-2: #0b2440; --hero-3: #12365c;
}
[data-theme="dark"] {
    --bg:          #050b15;
    --solid:       #111b28;
    --surface:     rgba(40,52,70,.40);
    --surface-2:   rgba(255,255,255,.06);
    --surface-3:   rgba(255,255,255,.10);
    --accent:      #5ab4ff;
    --accent-2:    #5ab4ff;
    --accent-lo:   rgba(90,180,255,.14);
    --accent-rgb:  90,180,255;
    --text:        #f1f5fa;
    --text-2:      rgba(232,240,248,.74);
    --text-3:      rgba(232,240,248,.50);
    --border:      rgba(255,255,255,.10);
    --btn-bg:      #3a9bf0;
    --glass:       rgba(30,42,60,.42);
    --glass-hi:    rgba(70,86,110,.55);
    --glass-line:  rgba(255,255,255,.14);
    --glass-spec:  inset 0 1px 0 rgba(255,255,255,.16), inset 0 0 0 1px rgba(255,255,255,.04);
    --shadow:      0 1px 2px rgba(0,0,0,.25), 0 8px 22px rgba(0,0,0,.25);
    --shadow-md:   0 1px 2px rgba(0,0,0,.25), 0 14px 36px rgba(0,0,0,.32);
    --shadow-lg:   0 2px 6px rgba(0,0,0,.3), 0 26px 64px rgba(0,0,0,.45);
    --track:       rgba(118,118,128,.24);
}

/* overflow-x: hidden 會讓 body 變成捲動容器，頁首與段落導覽的 sticky 因此失效；
   支援 clip 的瀏覽器改用 clip（只裁切、不建立捲動容器），頁首才會浮在內容上 */
@supports (overflow: clip) { html, body { overflow-x: clip; } }

/* ── 背景：固定的海洋色漸層，讓玻璃有東西可以「透」 ── */
body { font-family: var(--display); font-weight: 400; background: var(--bg); }
body::before {
    content: ""; position: fixed; inset: -12vmax; z-index: -2; pointer-events: none;
    background:
        radial-gradient(42vmax 34vmax at 12% 8%,  rgba(96,176,255,.55), transparent 70%),
        radial-gradient(38vmax 32vmax at 88% 14%, rgba(170,150,255,.42), transparent 70%),
        radial-gradient(44vmax 36vmax at 78% 88%, rgba(80,214,196,.40), transparent 70%),
        radial-gradient(40vmax 32vmax at 8% 92%,  rgba(255,196,160,.38), transparent 70%),
        var(--bg);
    transition: opacity .35s;
}
[data-theme="dark"] body::before {
    background:
        radial-gradient(42vmax 34vmax at 12% 6%,  rgba(28,96,190,.55), transparent 70%),
        radial-gradient(38vmax 30vmax at 90% 22%, rgba(96,64,190,.34), transparent 70%),
        radial-gradient(44vmax 36vmax at 74% 92%, rgba(0,138,140,.30), transparent 70%),
        radial-gradient(40vmax 32vmax at 4% 82%,  rgba(22,62,128,.42), transparent 70%),
        var(--bg);
}
::selection { background: rgba(var(--accent-rgb),.28); }
:focus-visible { outline-color: var(--accent); border-radius: 12px; }

/* 共同的玻璃材質 */
header, .bottom-nav, .subnav, .panel, .stat, .storm-hero, .genesis-teaser, .model-card, .switch-chip,
.update-badge, .theme-btn, .nav-menu, .hero-storms, .hero-chip, .footer-inner, .arch-card,
.empty-card, .player-controls, .lb-close {
    background: var(--glass);
    -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
    border: 1px solid var(--glass-line);
    box-shadow: var(--glass-spec), var(--shadow);
}

/* 大標題：一般大小寫、粗體、字距略收（像 SF Pro Display） */
.hero-title, .storm-title, .page-title, .section-head h3, .sec-group-title, .panel-header, .brand-text h1,
.footer-brand h3, .model-name, .empty-title, .tile-name {
    font-family: var(--display); text-transform: none;
}
.hero-title, .storm-title, .page-title { font-weight: 750; letter-spacing: -.025em; }
html[lang^="zh"] .hero-title, html[lang^="zh"] .storm-title, html[lang^="zh"] .page-title { letter-spacing: .02em; }
.storm-name { letter-spacing: .02em !important; }

/* ── Header：浮在頁面上方的玻璃條 ── */
header {
    top: 10px; margin: 10px 12px 0; padding: 0 12px 0 14px;
    min-height: 60px; border-radius: 24px;
    box-shadow: var(--glass-spec), var(--shadow-md);
}
.scroll-progress { left: 24px; right: 24px; bottom: 0; height: 2px; border-radius: 2px; background: var(--accent); }
.brand-icon {
    position: relative; overflow: hidden; width: 38px; height: 38px; border-radius: 12px; color: #fff;
    background: linear-gradient(145deg, #3aa0ff, #0a5fc4);
    box-shadow: inset 0 1px 0 rgba(255,255,255,.55), inset 0 -1px 0 rgba(0,0,0,.12), 0 4px 12px rgba(10,111,220,.32);
}
/* 上半部一層亮面，像 iOS 圖示的玻璃反光 */
.brand-icon::after { content: ""; position: absolute; inset: 0 0 50% 0; background: linear-gradient(rgba(255,255,255,.28), rgba(255,255,255,0)); pointer-events: none; }
.brand-icon span { display: flex; animation: none; }
/* logo 平常不轉；滑鼠移上去時旋臂逆時針轉一圈（北半球颱風的旋轉方向） */
.header-brand:hover .brand-icon { transform: scale(1.05); }
.brand-mark { transition: transform .9s var(--ease-out); }
.header-brand:hover .brand-mark { transform: rotate(-360deg); }
.brand-mark { width: 24px; height: 24px; filter: drop-shadow(0 1px 1px rgba(0,0,0,.18)); }
.brand-text h1 { font-weight: 700; font-size: 1.02em; letter-spacing: -.01em; }
.brand-text small { display: none; }   /* 模式清單副標在寬螢幕會折成三行，玻璃頁首只留站名 */
html[lang^="zh"] .brand-text h1 { letter-spacing: .04em; }
.nav-link { border-radius: 999px; font-weight: 600; font-size: .86em; color: var(--text-2); padding: 8px 14px; }
.nav-link:hover { color: var(--text); }
.nav-link.active { color: var(--text); }
.nav-indicator {
    border-radius: 999px; border: 1px solid var(--glass-line);
    background: var(--glass-hi); box-shadow: var(--glass-spec), 0 2px 10px rgba(15,35,60,.10);
}
.nav-dot { box-shadow: 0 0 0 2px rgba(255,255,255,.35); }
.update-badge, .theme-btn { border-radius: 999px; color: var(--text-2); box-shadow: var(--glass-spec); }
.update-badge { padding: 7px 13px 7px 10px; }
.theme-btn { padding: 7px 14px; }
.theme-btn:hover { background: var(--glass-hi); color: var(--text); border-color: var(--glass-line); }
.ring-fg { stroke: var(--ok); }
.version-badge, [data-theme="dark"] .version-badge {
    background: transparent; color: var(--text-3); border-color: transparent; font-size: .76em; font-weight: 600; padding: 7px 6px;
}

/* 颱風下拉選單（功能規則） */
/* 颱風下拉選單：.collapsed 時隱藏各颱風連結、改顯示「颱風 ▾」。
   .nav-drop 刻意不設定位，讓按鈕的 offsetParent 仍是 .top-nav，滑動指示塊才對得準；
   選單改以 .top-nav 為定位基準，左緣由 JS 對齊按鈕。 */
.top-nav.measuring .nav-link { flex-shrink: 0; }
header.compact .header-actions { gap: 6px; }
header.compact .ub-long { display: none; }
header.compact .theme-btn { padding-left: 11px; padding-right: 11px; }
header.compact .theme-btn .bi:not(:empty) + .bt { display: none; }
header.compact #lang-btn .bt { display: none; }
header.compact #lang-btn .bt-short { display: inline; font-weight: 800; }
header.compact #tz-btn .bi, header.compact #tz-btn .bt { display: none; }
header.compact #tz-btn .bt-short { display: inline; font-weight: 800; }
time.tz { font-variant-numeric: tabular-nums; }
#tz-btn { min-width: 8em; justify-content: center; }
html[lang="en"] #tz-btn { min-width: 9em; }
header.compact #tz-btn, html[lang="en"] header.compact #tz-btn { min-width: 5.6em; }
@media (max-width: 600px) { #tz-btn, html[lang="en"] #tz-btn { min-width: 6em; } }
/* 最窄的手機（≤360px）：「更新於」字樣省掉只留時間，時區鈕不再撐寬，四個東西才排得下 */
@media (max-width: 360px) {
    #update-badge .ub-text > span:first-child { display: none; }
    #tz-btn, html[lang="en"] #tz-btn { min-width: 0; padding-left: 9px; padding-right: 9px; }
}
header.mini .brand-text { display: none; }
.top-nav.tight .nav-link { padding-left: 9px; padding-right: 9px; }
.top-nav.tight .nav-link > svg:not(.nd-caret) { display: none; }
.nav-drop { display: none; }
.nav-drop-btn { appearance: none; -webkit-appearance: none; background: none; border: 0; margin: 0; font-family: inherit; line-height: inherit; cursor: pointer; }
.top-nav.collapsed .nav-storm { display: none; }
.top-nav.collapsed .nav-drop { display: flex; }
.nd-count { font-style: normal; font-size: .82em; line-height: 1; padding: 3px 6px; border: 1px solid currentColor; opacity: .8; }
.nd-caret { width: 13px !important; height: 13px !important; transition: transform .3s var(--ease-out); }
.nav-drop.open .nd-caret { transform: rotate(180deg); }
.nav-menu {
    position: absolute; top: calc(100% + 12px); left: 0; z-index: 300; min-width: 300px;
    display: flex; flex-direction: column; padding: 6px;
    -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
    border: 1px solid var(--glass-line);
    opacity: 0; visibility: hidden; transform: translateY(-6px);
    transition: opacity .25s, transform .3s var(--ease-out), visibility 0s .3s;
}
.nav-drop.open .nav-menu { opacity: 1; visibility: visible; transform: none; transition: opacity .25s, transform .3s var(--ease-out); }
.nav-menu-item {
    display: grid; grid-template-columns: 9px 1fr auto 56px; align-items: center; gap: 12px;
    padding: 11px 14px; color: var(--text-2); text-decoration: none; white-space: nowrap;
    font-size: .8em; font-weight: 500; letter-spacing: .08em; text-transform: uppercase;
    transition: background .2s, color .2s;
}
.nav-menu-item:hover, .nav-menu-item:focus-visible { background: var(--text); color: var(--bg); outline: none; }
.nav-menu-item.active { color: var(--text); box-shadow: inset 2px 0 0 var(--text); }
.nav-menu-item.active:hover { color: var(--bg); }
.nm-cat { font-size: .82em; font-weight: 700; padding: 3px 7px; letter-spacing: .06em; }
.nm-kt { text-align: right; opacity: .75; }
.nav-menu { border-radius: 22px; background: var(--glass-hi); box-shadow: var(--glass-spec), var(--shadow-lg); }
.nav-menu-item { border-radius: 14px; font-weight: 600; letter-spacing: .02em; text-transform: none; }
.nav-menu-item:hover, .nav-menu-item:focus-visible { background: var(--accent-lo); color: var(--text); }
.nav-menu-item.active { color: var(--accent); box-shadow: none; background: var(--accent-lo); }
.nav-menu-item.active:hover { color: var(--accent); }
.nm-cat { border-radius: 999px; }
.nd-count { border-radius: 999px; }

/* ── 總覽 Hero ── */
.hero { min-height: calc(100svh - var(--header-h) - 20px); background: transparent; }
.hero::after { display: none; }
.hero-inner { max-width: 1380px; padding: 64px 28px 72px; }
/* 寬螢幕：文字不再擠在中間 1380px 的欄裡（左邊空一大片、地球卻貼著右邊），改成依畫面寬度留邊 */
@media (min-width: 1100px) { .hero-inner { max-width: none; padding-left: clamp(28px, 4vw, 112px); padding-right: clamp(28px, 4vw, 112px); } }
.eyebrow {
    background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.22);
    -webkit-backdrop-filter: blur(16px) saturate(160%); backdrop-filter: blur(16px) saturate(160%);
    box-shadow: inset 0 1px 0 rgba(255,255,255,.25);
    font-weight: 600; letter-spacing: .04em; text-transform: none; color: rgba(255,255,255,.88);
}
.hero-title { font-size: clamp(2.6rem, 6.5vw, 5rem); line-height: 1.02; margin: 22px 0 26px; text-shadow: 0 2px 30px rgba(0,0,0,.25); max-width: none; }
html[lang^="zh"] .hero-title { line-height: 1.15; }
/* 颱風清單：一張玻璃卡片，每列一顆 */
.hero-storms {
    background: rgba(255,255,255,.10); border-color: rgba(255,255,255,.22);
    box-shadow: inset 0 1px 0 rgba(255,255,255,.28), 0 18px 50px rgba(0,0,0,.22);
    border-radius: 26px; padding: 4px 22px;
}
.hero-storms a { border-bottom: 1px solid rgba(255,255,255,.14); padding: 14px 0; font-weight: 500; color: rgba(255,255,255,.9); }
.hero-storms li:first-child a { border-top: 0; }
.hero-storms li:last-child a { border-bottom: 0; }
.hero-storms .hs-name { font-weight: 700; color: #fff; }
.cat-pill { border-radius: 999px; font-weight: 700; padding: 4px 12px; text-align: center; }   /* 首頁颱風列對齊成欄時，膠囊會被撐成同寬，字要置中 */
.hero-sub { color: rgba(255,255,255,.72); }
.btn-primary, .btn-ghost { border-radius: 999px; padding: 13px 24px; font-weight: 650; }
.btn-primary { background: rgba(255,255,255,.92); color: #0b2440; box-shadow: inset 0 1px 0 #fff, 0 10px 30px rgba(0,0,0,.25); }
.btn-ghost {
    color: #fff; background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.26);
    -webkit-backdrop-filter: blur(16px) saturate(160%); backdrop-filter: blur(16px) saturate(160%);
    box-shadow: inset 0 1px 0 rgba(255,255,255,.3);
}
.btn-ghost:hover { background: rgba(255,255,255,.2); }
.hero-meta { margin-top: 32px; }
.hero-chip {
    background: rgba(255,255,255,.10); border-color: rgba(255,255,255,.22);
    box-shadow: inset 0 1px 0 rgba(255,255,255,.28); border-radius: 20px; padding: 12px 18px;
}
.chip-k { font-weight: 600; letter-spacing: .04em; text-transform: none; opacity: .7; }
.chip-v, html[lang^="zh"] .chip-v { font-weight: 650; letter-spacing: .01em; }
.scroll-cue { display: none; }
/* 淺色主題：Hero 是一張深色圓角卡片（地球只畫在卡片裡） */
[data-theme="light"] .hero { margin: 12px 12px 0; border-radius: 34px; box-shadow: var(--shadow-lg); }
[data-theme="light"] #globe { background: linear-gradient(160deg, #071528, #0b2440 55%, #12365c); }

/* ── 版面、區塊標題 ── */
.page { max-width: 1380px; padding: 28px 24px 64px; gap: 24px; }
.section-head h3 { font-size: clamp(1.5rem, 2.6vw, 2rem); font-weight: 700; letter-spacing: -.015em; }
.page-title { font-size: clamp(1.8rem, 3.6vw, 2.8rem); }
.page-lead { color: var(--text-2); }
.kicker { display: none; }

/* ── 卡片 ── */
.panel { border-radius: var(--radius); padding: 24px 26px; }
.panel-header { font-weight: 700; font-size: 1.12em; letter-spacing: -.01em; border-bottom-color: var(--border); }
html[lang^="zh"] .panel-header { letter-spacing: .03em; }
.panel-icon { display: none; }
.stat { border-radius: 22px; padding: 16px 20px; }
.stat:hover, .model-card:hover { transform: translateY(-2px); box-shadow: var(--glass-spec), var(--shadow-md); }
.stat-label { font-weight: 600; letter-spacing: .02em; text-transform: none; color: var(--text-3); }
.stat-label span[aria-hidden] { display: none; }
.stat-value { font-weight: 650; font-size: 1.6em; letter-spacing: -.01em; }
.genesis-teaser { border-radius: 30px; }
.genesis-teaser:hover { border-color: var(--glass-line); box-shadow: var(--glass-spec), var(--shadow-lg); }
.teaser-img { border-radius: 22px; margin: 8px; min-height: 240px; }
.teaser-body { border-left: 0; padding: 28px 30px; }
.mini-chip { border-radius: 999px; }
.model-grid { gap: 12px; }
@media (min-width: 900px) { .model-grid { grid-template-columns: repeat(3, 1fr); } }
.model-card { border-radius: 22px; }
.model-name { font-weight: 700; letter-spacing: -.01em; }
.arch-card { border-radius: 22px; border-top: 1px solid var(--glass-line); }
.arch-card::before { content: ""; position: absolute; left: 18px; right: 18px; top: 0; height: 3px; border-radius: 0 0 3px 3px; background: var(--cat); }

/* ── 颱風頁 ── */
.switch-chip { border-radius: 999px; color: var(--text-2); font-weight: 650; }
.switch-chip:hover { color: var(--text); border-color: var(--glass-line); }
.switch-chip.active { color: var(--text); background: var(--glass-hi); border-color: var(--glass-line); box-shadow: var(--glass-spec), 0 4px 14px rgba(15,35,60,.12); }
/* 颱風主卡：玻璃＋颱風強度色的光暈 */
.storm-hero {
    color: var(--text); border-radius: 32px; padding: 36px 40px;
    background:
        radial-gradient(640px 360px at 86% 50%, color-mix(in srgb, var(--cat) 26%, transparent), transparent 70%),
        var(--glass);
    box-shadow: var(--glass-spec), var(--shadow-lg);
}
.storm-hero .swirl { opacity: .16; }
.storm-title { font-size: clamp(2.6rem, 6vw, 4.4rem); text-shadow: none; margin: 12px 0 14px; }
.storm-subtitle { color: var(--text-3); }
.storm-summary p { color: var(--text); font-weight: 450; }
.badge-cat, .badge-id, .badge-name, .badge-live { border-radius: 999px; }
.storm-badges .badge-cat { font-weight: 700; }
.storm-hero .badge-id, .storm-hero .badge-name { background: var(--surface-2); border-color: var(--border); color: var(--text-2); }
.storm-hero .badge-live { color: var(--danger); }
.storm-hero .g-track { stroke: var(--surface-3); }
.storm-hero .g-needle line { stroke: var(--text); }
.storm-hero .g-tick { fill: var(--text-3); }
.gauge-val b { font-weight: 700; }
/* 段落導覽：玻璃膠囊，選中的那格是較亮的玻璃 */
.subnav { top: calc(var(--header-h) + 22px); border-radius: 999px; padding: 5px; gap: 2px; box-shadow: var(--glass-spec), var(--shadow-md); }
.subnav button { border-radius: 999px; font-weight: 600; color: var(--text-2); }
.subnav button.active { background: var(--glass-hi); color: var(--accent); box-shadow: var(--glass-spec), 0 2px 10px rgba(15,35,60,.12); }
[data-theme="dark"] .subnav button.active { color: #fff; background: rgba(255,255,255,.16); }
.sec-group-title { font-weight: 700; font-size: clamp(1.4rem, 2.6vw, 1.9rem); letter-spacing: -.015em; border-bottom: 0; padding-bottom: 6px; margin-bottom: 14px; }
html[lang^="zh"] .sec-group-title { letter-spacing: .04em; }
details.sec-group > summary { border-bottom: 0; margin-bottom: 14px; }
details.sec-group > summary .fold-hint {
    padding: 6px 14px; margin-bottom: 6px; border-radius: 999px; font-size: .84em; font-weight: 600;
    background: var(--glass); border: 1px solid var(--glass-line); box-shadow: var(--glass-spec);
    -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
}
/* iOS 分段控制：灰色底槽＋白色滑塊 */
.seg { background: var(--track); border: 0; border-radius: 999px; padding: 3px; gap: 2px; }
.seg-ind { border-radius: 999px; background: #fff; box-shadow: 0 3px 8px rgba(0,0,0,.12), 0 1px 1px rgba(0,0,0,.04); }
[data-theme="dark"] .seg-ind { background: rgba(255,255,255,.2); box-shadow: inset 0 1px 0 rgba(255,255,255,.18), 0 3px 8px rgba(0,0,0,.3); }
.model-tab-btn { border-radius: 999px; font-weight: 600; padding: 7px 16px; }
/* 分頁鈕太多時不換行（換行會把膠囊撐成一大塊），改成單列左右滑，邊緣淡出提示還有 */
.seg { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; overscroll-behavior-x: contain; }
.seg::-webkit-scrollbar { display: none; }
.seg .model-tab-btn { flex-shrink: 0; white-space: nowrap; }
.seg.fade-r { -webkit-mask-image: linear-gradient(to right, #000 calc(100% - 40px), transparent);
                      mask-image: linear-gradient(to right, #000 calc(100% - 40px), transparent); }
.seg.fade-l { -webkit-mask-image: linear-gradient(to left, #000 calc(100% - 40px), transparent);
                      mask-image: linear-gradient(to left, #000 calc(100% - 40px), transparent); }
.seg.fade-l.fade-r { -webkit-mask-image: linear-gradient(to right, transparent, #000 40px, #000 calc(100% - 40px), transparent);
                             mask-image: linear-gradient(to right, transparent, #000 40px, #000 calc(100% - 40px), transparent); }
.model-tab-btn.active { color: var(--text); }
.seg:not(.ready) .model-tab-btn.active { background: #fff; }
[data-theme="dark"] .seg:not(.ready) .model-tab-btn.active { background: rgba(255,255,255,.2); }
.run-btn { border-radius: 999px; background: var(--surface-2); border-color: var(--glass-line); }
.run-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.ghost-btn { border-radius: 999px; }
.scale-row { border-radius: 16px; background: var(--surface-2); }
.ss-seg { border-radius: 8px; }
.model-label { border-radius: 999px; }

/* 圖：白色圖紙配大圓角（圖本身是白底），深色主題稍微調暗 */
.zoomable { background: #fff; border: 1px solid var(--glass-line); border-radius: 20px; box-shadow: var(--shadow); }
.zoom-hint { border-radius: 999px; background: rgba(20,28,40,.6); -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px); }
.player { background: transparent; border: 0; border-radius: 22px; overflow: hidden; box-shadow: var(--shadow); }
.frame-stage { border-radius: 22px 22px 0 0; }
/* 圖紙貼齊圖片：圖被限高時，白底不再撐滿整個面板寬度、兩旁留白；播放器寬度也依圖的長寬比收窄 */
.player { width: min(100%, calc((100vh - var(--header-h) - 190px) * var(--arv, 1.6))); margin-inline: auto; }
.player-controls { border-radius: 0 0 22px 22px; border-top: 0; box-shadow: var(--glass-spec); }
.pc-btn { border-radius: 999px; background: var(--surface-2); border-color: var(--glass-line); }
.pc-main { background: var(--accent); box-shadow: inset 0 1px 0 rgba(255,255,255,.35), 0 6px 16px rgba(var(--accent-rgb),.35); }
.speed-seg { border-radius: 999px; background: var(--track); border: 0; }
.speed-btn { border-radius: 999px; }
.speed-btn.active { background: #fff; color: var(--text); }
[data-theme="dark"] .speed-btn.active { background: rgba(255,255,255,.2); }
.timeline { accent-color: var(--accent); }
.cmp-stage { border-radius: 20px; }

/* 城市表：固定欄用不透明底色，陰影提示可左右捲動 */
.city-table-wrap {
    background:
        linear-gradient(to right, var(--solid) 30%, transparent) left / 40px 100% no-repeat local,
        linear-gradient(to left, var(--solid) 30%, transparent) right / 40px 100% no-repeat local,
        radial-gradient(farthest-side at 0 50%, rgba(15,35,60,.18), transparent) left / 14px 100% no-repeat scroll,
        radial-gradient(farthest-side at 100% 50%, rgba(15,35,60,.18), transparent) right / 14px 100% no-repeat scroll;
    border-radius: 16px;
}
.city-table th:first-child, .city-table td.c-name { background: var(--solid); }
.city-table td { border-radius: 9px; }

/* ── Footer：底部一張玻璃卡 ── */
footer { border-top: 0; padding: 0 24px 16px; margin-top: 24px; }
.footer-inner { max-width: 1332px; padding: 26px 28px; border-radius: 28px; }
.footer-brand h3 { font-weight: 700; }
.footer-link { border-radius: 999px; }
.footer-copy { border-top-color: var(--border); }

/* ── Lightbox：整頁霧面 ── */
.lightbox { background: rgba(8,14,24,.55); -webkit-backdrop-filter: blur(30px) saturate(140%); backdrop-filter: blur(30px) saturate(140%); }
.lightbox img { border-radius: 18px; }
.lb-close { color: #fff; background: rgba(255,255,255,.16); border-color: rgba(255,255,255,.3); }

@media (max-width: 900px) {
    /* 手機頁首有兩列，黏在上面太佔畫面：讓它跟著捲走，只留段落導覽浮在上方 */
    header { position: relative; top: 0; margin: 8px 8px 0; padding: 10px 12px; border-radius: 22px; }
    .subnav { top: 8px; }
    .panel, .maps-grid { scroll-margin-top: 76px; }
    /* 底部分頁列：iOS 26 那種浮動的玻璃膠囊 */
    .bottom-nav {
        left: 12px; right: 12px; bottom: calc(12px + env(safe-area-inset-bottom));
        border-radius: 30px; padding: 6px; box-shadow: var(--glass-spec), var(--shadow-lg);
    }
    .bottom-nav a { border-radius: 24px; font-weight: 600; color: var(--text-2); }
    .bottom-nav a.active { color: var(--accent); background: var(--glass-hi); box-shadow: var(--glass-spec); }
    [data-theme="dark"] .bottom-nav a.active { color: #fff; background: rgba(255,255,255,.16); }
    .storm-hero { padding: 28px 24px; }
    .hero-inner { padding: 48px 20px 56px; }
    [data-theme="light"] .hero { margin: 10px 8px 0; border-radius: 30px; }
}
@media (max-width: 600px) {
    .page { padding: 18px 12px 40px; gap: 18px; }
    .panel { padding: 18px 16px; border-radius: 24px; }
    .storm-hero { padding: 24px 20px; border-radius: 28px; }
    .stat { padding: 13px 15px; border-radius: 20px; }
    .stat-value { font-size: 1.2em; }
    .hero-inner { padding: 40px 16px 44px; }
    .brand-icon { width: 34px; height: 34px; border-radius: 11px; }
    .brand-mark { width: 22px; height: 22px; }
    .hero-storms { padding: 2px 16px; border-radius: 22px; }
    /* 手機：每顆排兩行 —— 名字＋強度在上、風速與位置在下，箭頭靠右 */
    .hero-storms a { gap: 4px 10px; font-size: 1.02rem; }
    .hero-storms .hs-name { min-width: 0; }
    .hero-storms a > span[data-i18n^="catname"] { flex: 1 0 auto; }
    .hero-storms a > span[data-i18n^="catname"] + .sep { display: none; }
    .hero-storms .hs-go { order: 1; margin-left: 0; }
    .hero-storms a::after { content: ""; order: 2; flex-basis: 100%; }
    .hero-storms a > .mono, .hero-storms a > .mono + .sep { order: 3; font-size: .86em; color: rgba(255,255,255,.72); }
    .hero-cta { flex-wrap: nowrap; gap: 10px; }
    .btn-primary, .btn-ghost { flex: 1 1 auto; justify-content: center; padding: 13px 12px; white-space: nowrap; font-size: .9em; }
    .hero-chip { flex: 1 1 30%; }
    footer { padding: 0 12px 12px; }
    .footer-inner { padding: 22px 20px; border-radius: 24px; }
    .teaser-img { min-height: 190px; }
}

/* ── 颱風頁（v7）：上方一條玻璃列 = 分頁＋模式選單；內容單欄 ── */
.storm-bar {
    position: sticky; top: calc(var(--header-h) + 22px); z-index: 50;
    display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 6px 10px;
    width: max-content; max-width: 100%; margin: 6px auto 4px; padding: 5px;
    border-radius: 999px; background: var(--glass); border: 1px solid var(--glass-line);
    -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
    box-shadow: var(--glass-spec), var(--shadow-md);
}
.storm-tabs { margin: 0; background: transparent; padding: 0; flex-wrap: nowrap; }
.storm-tab { padding: 9px 20px; font-size: .92em; }
.model-pick { display: flex; align-items: center; gap: 8px; padding: 0 2px 0 12px; border-left: 1px solid var(--border);
              font-size: .84em; font-weight: 600; color: var(--text-3); white-space: nowrap; }
/* 全站下拉選單同一個樣式：颱風頁模式選單、互動地圖、歷史頁、生成潛勢比較
  （歷史頁的選單原本沒有樣式，iOS 會畫成文字貼左邊的原生膠囊） */
.model-select, .arch-model, .track-map select, .compare-pickers select {
    appearance: none; -webkit-appearance: none; cursor: pointer;
    font: inherit; font-size: 1.04em; font-weight: 650; color: var(--text);
    padding: 7px 32px 7px 14px; border-radius: 999px; border: 1px solid var(--glass-line);
    background: var(--glass-hi) no-repeat right 12px center / 11px
        url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 8'%3E%3Cpath d='M1 1.5l5 5 5-5' fill='none' stroke='%237f8c99' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
    box-shadow: var(--glass-spec);
}
.model-select:focus-visible, .arch-model:focus-visible, .track-map select:focus-visible, .compare-pickers select:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
[data-theme="dark"] :is(.model-select, .arch-model, .track-map select, .compare-pickers select) option { background: #1b2533; color: #f1f5fa; }
.storm-bar.no-pick .model-pick { display: none; }
.tab-pane { display: flex; flex-direction: column; gap: 24px; }
.tab-pane.swap-in { animation: swapIn .45s var(--ease-out); }

/* 各圖的模式分頁交給上方選單；同一模式有系集／決定性兩種時才留兩顆小分頁 */
.seg.mt-linked { display: none; }
.seg.mt-linked.mt-variants { display: inline-flex; }
.model-tab-btn[hidden] { display: none; }
.mt-shown { margin-left: 4px; padding: 3px 10px; border-radius: 999px; font-size: .72em; font-weight: 650;
            letter-spacing: .01em; background: var(--accent-lo); color: var(--accent); }
.mt-shown:empty { display: none; }
.mt-shown.miss { background: var(--surface-3); color: var(--text-2); }

/* 圖說收合：「ⓘ 怎麼看這張圖」 */
.note-fold { margin-top: 10px; }
.note-fold > summary {
    list-style: none; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 12px 5px 9px; border-radius: 999px; font-size: .8em; font-weight: 600; color: var(--text-3);
    transition: background .2s, color .2s;
}
.note-fold > summary::-webkit-details-marker { display: none; }
.note-fold > summary::before { content: "ⓘ"; font-size: 1.1em; }
.note-fold > summary:hover, .note-fold[open] > summary { background: var(--surface-2); color: var(--text-2); }
.note-fold > .map-note { margin-top: 6px; }
.jtwc-src { margin-top: 10px; font-size: .78em; color: var(--text-3); }

@media (max-width: 900px) {
    .storm-bar { top: 8px; }
}
@media (max-width: 600px) {
    /* 手機：分頁佔滿一列，模式選單縮在第二列右邊 */
    .storm-bar { width: 100%; border-radius: 24px; padding: 4px; justify-content: flex-end; }
    .storm-tabs { width: 100%; justify-content: space-between; }
    .storm-tab { flex: 1 1 0; padding: 8px 4px; font-size: .86em; }
    .model-pick { border-left: 0; padding: 0 2px 2px; font-size: .78em; }
    .model-select { padding: 5px 28px 5px 12px; }
    .tab-pane { gap: 18px; }
}
"""

_JS = r"""
(function () {
'use strict';

const SITE = JSON.parse(document.getElementById('site-data').textContent);
const root = document.documentElement;
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const RM = window.matchMedia('(prefers-reduced-motion: reduce)');
const reduced = () => RM.matches;
const canHover = window.matchMedia('(hover: hover)').matches;

// ── 頂部導覽列的「颱風 ▾」下拉選單 ────────────────────────────────
// 伺服器端在颱風超過 NAV_COLLAPSE_AT 顆時直接輸出 .collapsed；顆數少時由 fit()
// 在排不下（例如窄筆電）才收合。選單以 .top-nav 定位，打開時左緣對齊按鈕。
const NavDrop = (() => {
    const nav = document.querySelector('.top-nav');
    const drop = nav && nav.querySelector('.nav-drop');
    const forced = !!nav && nav.classList.contains('collapsed');
    // 排不下時依序退讓，每一步後重量一次，放得下就停：
    //   1. 各颱風連結收進「颱風 ▾」（.collapsed）
    //   2. 頁首右側按鈕改精簡版：更新時間只留時分、主題／語言鈕只留圖示與短字（header.compact，同手機版）
    //   3. 導覽連結拿掉圖示、縮小間距（.tight）
    //   4. 最後才藏品牌文字，只留圖示（header.mini）
    // 量的時候暫時禁止連結縮小（.measuring），才量得出真正需要的寬度。
    const header = nav && nav.closest('header');
    const fit = () => {
        if (!nav) return;
        header.classList.remove('compact', 'mini');
        nav.classList.remove('tight');
        if (drop && !forced) nav.classList.remove('collapsed');
        if (!nav.offsetParent) return;          // 手機版導覽列隱藏，改用底部分頁列
        nav.classList.add('measuring');
        const over = () => nav.scrollWidth > nav.clientWidth + 1;
        const steps = [
            () => drop && !forced && nav.classList.add('collapsed'),
            () => header.classList.add('compact'),
            () => nav.classList.add('tight'),
            () => header.classList.add('mini'),
        ];
        for (const step of steps) { if (!over()) break; step(); }
        nav.classList.remove('measuring');
        // 版面動了，滑動指示塊要重新對位（updateIndicators 是函式宣告，這裡呼叫得到）
        requestAnimationFrame(() => updateIndicators());
    };
    if (document.fonts) document.fonts.ready.then(() => fit());
    if (!drop) { fit(); return { fit, close() {} }; }
    const btn = drop.querySelector('.nav-drop-btn'), menu = drop.querySelector('.nav-menu');
    let timer = 0;
    const open = () => {
        clearTimeout(timer);
        if (drop.classList.contains('open')) return;
        menu.style.left = btn.offsetLeft + 'px';
        drop.classList.add('open'); btn.setAttribute('aria-expanded', 'true');
        const over = menu.getBoundingClientRect().right - (window.innerWidth - 12);
        if (over > 0) menu.style.left = (btn.offsetLeft - over) + 'px';
    };
    const close = () => { clearTimeout(timer); drop.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); };
    btn.addEventListener('click', e => { e.stopPropagation(); drop.classList.contains('open') ? close() : open(); });
    if (canHover) {
        drop.addEventListener('mouseenter', open);
        drop.addEventListener('mouseleave', () => { timer = setTimeout(close, 180); });
    }
    document.addEventListener('click', e => { if (!drop.contains(e.target)) close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && drop.classList.contains('open')) { close(); btn.focus(); } });
    fit();
    return { fit, close };
})();

// ── i18n（中／英切換）─────────────────────────────────────────────
// 版面上所有固定文案都掛 data-i18n="key"，切換語言時由 applyLang() 一次換掉；
// 帶參數的字串用 {name} 佔位，值由同一元素上的 data-i18n-name 提供。
const I18N = {
  en: {
    'doc.title':        "Pillar's Tropical Cyclone Forecast",
    'brand.title':      "Pillar's Tropical Cyclone Forecast",
    'brand.sub':        'Real-time WN3-C / WN2-C r2 / WN2-C r1 / WN2-C 1000 / GENC / AIFS / ECMWF / AIGFS / GFS Ensemble Forecast System · Western Pacific',
    'header.updated':   'Updated',
    'btn.dark':         '🌙 Dark',
    'btn.light':        '☀️ Light',
    'btn.lang':         '🌐 中文',
    'btn.lang.short':   '中',
    'btn.tz.utc':       '🕒 UTC',
    'btn.tz.tw':        '🕒 Taiwan time',
    'btn.tz.utc.short': 'UTC',
    'btn.tz.tw.short':  'UTC+8',
    'btn.tz.title':     'Update time shown in {z}. Click to switch between UTC and Taiwan time (UTC+8); everything else on the page is in UTC.',
    'nav.overview':     'Overview',
    'nav.storms':       'Storms',
    'nav.genesis':      'Genesis',
    'nav.about':        'About',
    'nav.archive':      'Archive',
    'arch.kicker':      'Past storms',
    'arch.title':       'Storm Archive',
    'arch.lead':        'Every storm this site has followed: the real JTWC track, how each model\'s forecasts changed run by run, and how far off they turned out to be. Pick a storm to open it.',
    'arch.active':      'Active',
    'arch.inits':       '{n} forecasts',
    'arch.init':        'Run',
    'arch.all':         'Show every run',
    'arch.noscore':     'No verified forecasts for this storm yet.',
    'note.arch.trend':  'The last version drawn before the storm ended: ensemble-mean (or deterministic) tracks from every run, older = lighter &nbsp;·&nbsp; Shows which way successive forecasts shifted',
    'note.arch.map':    'Thick colored line = the real JTWC track, colored by intensity &nbsp;·&nbsp; Orange = the selected run\'s forecast, with a dot every 24 h &nbsp;·&nbsp; Thin lines = all other runs of the same model, light = older, dark = newer &nbsp;·&nbsp; Drag the slider to step through the runs; the number after each model is how many runs were saved',
    'hero.eyebrow.live':  'Now tracking',
    'hero.eyebrow.multi': 'Now tracking {count} storms',
    'hero.eyebrow.quiet': 'Western Pacific · Monitoring',
    'hero.quiet.title': 'All quiet in the Western Pacific',
    'hero.quiet.sub':   'No active tropical cyclones right now. The genesis outlook shows where ensemble members hint at something forming next.',
    'hero.live.sub':    '{count} active system(s) · ensemble guidance from {models} models, refreshed every 10–15 minutes.',
    'hero.cta.storm':   'Open forecast',
    'hero.cta.genesis': 'Genesis outlook',
    'hero.now':         'Current time',
    'cap.score':        'Mean forecast error by lead time for each model',
    'cap.cities':       'Taiwan landfall and city strike probability by model',
    'cap.official':     'Official forecasts by agency and forecast hour',
    'hero.active':      'Active systems',
    'statement':        'We track tropical cyclones at the intersection between <strong>artificial intelligence</strong> and <strong>physics</strong> — every ensemble member, every 10–15 minutes, side by side with the official forecast.',
    'sec.active.kicker':'Live',
    'sec.active':       'Active systems',
    'sec.genesis.kicker':'Outlook',
    'sec.genesis':      'Genesis potential',
    'sec.models.kicker':'Sources',
    'sec.models':       'Forecast models',
    'models.on':        'Output in this run',
    'tile.open':        'Open full forecast →',
    'genesis.teaser':   'Where might the next storm form? Explore ensemble genesis signals from {n} models.',
    'genesis.open':     'Explore outlook →',
    'genesis.compare':  'Compare models',
    'genesis.compare.hint': 'Drag the divider to compare two models',
    'empty.title':      'No Active Systems',
    'empty.status':     'Status',
    'empty.await':      'Awaiting data…',
    'empty.desc':       'Nothing is spinning up right now. This page refreshes automatically every 10–15 minutes.',
    'storm.subtitle':   'Western Pacific Tropical Cyclone',
    'badge.live':       'LIVE',
    'catname.TD':       'Tropical Depression',
    'catname.TS':       'Tropical Storm',
    'catname.Cat1':     'Category 1 Typhoon',
    'catname.Cat2':     'Category 2 Typhoon',
    'catname.Cat3':     'Category 3 Typhoon',
    'catname.Cat4':     'Category 4 Typhoon',
    'catname.Cat5':     'Category 5 Super Typhoon',
    'catname.Unknown':  'Intensity unknown',
    'stat.time':        'Obs time',
    'stat.pos':         'Position',
    'stat.wind':        'Max wind',
    'stat.pres':        'Min pressure',
    'stat.models':      'Models',
    'scale.title':      'Intensity scale (Saffir–Simpson)',
    'sub.cmp':          'Comparison',
    'sub.anim':         'Animation',
    'sub.maps':         'Ensemble & JTWC',
    'sub.strike':       'Strike Prob.',
    'panel.strike':     'Strike Probability',
    'note.strike':      'Share of ensemble members whose track passes within 1° (~111 km) of each 0.1° grid point at any time in the forecast &nbsp;·&nbsp; Intensity is not considered',
    'sub.tmap':         'Map',
    'panel.tmap':       'Interactive Track Map',
    'tmap.members':     'Members',
    'tmap.mean':        'Mean',
    'tmap.det':         'Deterministic',
    'tmap.init':        'Init',
    'tmap.compare':     'Compare models',
    'run.latest':       'Latest',
    'tmap.all':         'All',
    'tmap.na':          'not issued yet',
    'note.tmap':        'Drag / scroll to zoom &nbsp;·&nbsp; Hover a line for member, time (UTC) and wind &nbsp;·&nbsp; Member colors = intensity &nbsp;·&nbsp; Compare: pick any models, one color each, dashed = deterministic &nbsp;·&nbsp; Init buttons switch every model to the same run',
    'sub.score':        'Verification',
    'panel.score':      'Track Error by Model',
    'score.model':      'Model',
    'score.all':        'All storms (last 90 days)',
    'score.pending':    'Collecting data — the first errors appear once a forecast has been out for 24 hours.',
    'note.score':       'Track error = mean distance (km) between each forecast position and the JTWC warning position at the same time; the other tabs split it into along-/cross-track parts or check intensity &nbsp;·&nbsp; Homogeneous = only forecasts every model has for the same storm, init and hour (fair comparison) &nbsp;·&nbsp; Colors compare models per hour: green = best, red = worst (along-/cross-track: green = closest to 0); ★ = best, +x% = behind the best &nbsp;·&nbsp; Faded = fewer than 3 forecasts, not ranked',
    'score.tab.allst.homog': 'All storms · homogeneous',
    'score.tab.allst.all': 'All storms · all forecasts',
    'score.tab.storm.homog': 'This storm · homogeneous',
    'score.tab.storm.all': 'This storm · all forecasts',
    'score.tab.allst.same': 'All storms',
    'score.tab.storm.same': 'This storm',
    'score.same':       'Every model has every forecast so far, so the homogeneous and full samples are identical and shown once.',
    'score.onestorm':   'Only this storm has verified forecasts so far, so it matches the all-storms total.',
    'score.grp.ens': 'Ensemble mean',
    'score.grp.det': 'Deterministic',
    'score.grp.det.sub': 'single run — usually less accurate than an ensemble mean',
    'score.grp.jtwc': 'Official (JTWC)',
    'score.grp.jtwc.sub': 'verified against its own warning positions, which flatters JTWC — not ranked',
    'score.chart.y': 'Mean track error (km)',
    'sub.official':     'Official',
    'panel.official':   'Official Forecasts Compared',
    'off.now':          'Now',
    'off.hour':         'Hour',
    'note.official':    'JTWC (US), JMA (Japan) and CWA (Taiwan) official tracks &nbsp;·&nbsp; JTWC reports 1-minute winds, JMA and CWA 10-minute winds, so JTWC numbers run higher for the same storm &nbsp;·&nbsp; Time under each agency = forecast base time (UTC) &nbsp;·&nbsp; Map labels = valid time, day/hour UTC (e.g. 23/12Z = 23rd 12:00 UTC = 20:00 Taiwan time)',
    'sub.sat':          'Satellite',
    'tab.now':          'Summary',
    'tab.track':        'Track',
    'tab.strike':       'Strike',
    'tab.int':          'Intensity',
    'tab.score':        'Verification',
    'mp.label':         'Model',
    'mp.fallback':      'No {m} here · showing {y}',
    'note.how':         'How to read this',
    'tmap.fail':        'The map could not load. Reload the page to try again.',
    'panel.sat':        'Satellite Loop (last 3 hours)',
    'note.sat':         'Himawari-9 infrared (band 13, 10.4 µm) for the last 3 hours, one frame every 10 minutes, centered on the storm; it opens on the latest frame &nbsp;·&nbsp; Colors show cloud-top temperature: the colder the top, the taller the cloud and the stronger the convection; a warm dot ringed by the coldest colors is the eye and eyewall &nbsp;·&nbsp; Centred on the latest JTWC position (warnings come every 6 h, so the storm may have moved a little since); the track and JTWC forecast are on the ocean heat content map below &nbsp;·&nbsp; Raw data from the NOAA/JMA copy on AWS, observation time in the title of each frame',
    'sub.shear':        'Shear',
    'panel.shear':      'Vertical Wind Shear along the AIFS Track',
    'note.shear':       'Difference between the 200 hPa and 850 hPa winds, averaged 200–800 km from the centre, every 6 h along the AIFS-single (deterministic) forecast track — winds and track come from the same AIFS run &nbsp;·&nbsp; Strong shear tilts the storm\'s upper and lower circulation apart and usually stops it strengthening: below 10 kt is low, 10–20 kt moderate, above 20 kt high &nbsp;·&nbsp; Arrows = direction the shear points (from the low-level wind toward the upper-level wind); the storm\'s heaviest rain and convection tend to sit downshear-left &nbsp;·&nbsp; Data: ECMWF Open Data',
    'sub.ohc':          'Ocean heat',
    'panel.ohc':        'Ocean Heat Content',
    'panel.ohctrack':   'Ocean Heat Content along the JTWC Track',
    'note.ohctrack':    'Ocean heat content under the forecast centre, sampled every 6 h along the latest JTWC forecast track (mean within ±0.5° of the centre) &nbsp;·&nbsp; Dashed line = 50 kJ/cm², a common threshold for intensification: above it the warm layer is thick enough that the storm’s own mixing does not cool the surface much &nbsp;·&nbsp; Grey squares = land or water colder than 26 °C &nbsp;·&nbsp; The ocean analysis is one daily snapshot, so this is the ocean the storm will meet if it follows the JTWC track, not a forecast of how the ocean changes',
    'caveat.intensity': 'Read the intensities here as a trend, not as a forecast of peak winds. The AI models (WN3-C, WN2-C, GENC, AIFS, AIGFS) run at about 0.25° and cannot resolve the eyewall, so strong typhoons usually come out tens of knots too weak; the ECMWF and GFS ensembles also run weak. For how strong the storm will get, use the official forecasts (JTWC / JMA / CWA) in Summary; use these curves for whether it strengthens or weakens, and when. The Verification tab shows each model’s actual intensity bias for this storm.',
    'score.official':   'JTWC / JMA / CWA rows are the official forecasts, verified the same way; they appear only in the all-forecasts sample because their archive starts later than the models’ and does not enter the homogeneous sample.',
    'note.ohc':         'Tropical cyclone heat potential: heat stored above 26 °C between the sea surface and the 26 °C isotherm (kJ/cm²), computed from the latest daily CMEMS (Copernicus Marine) 1/12° ocean analysis, or HYCOM (US Navy) as a backup &nbsp;·&nbsp; A thick warm layer keeps the water under a typhoon warm even when it stirs the ocean, which favors strengthening; about 50 kJ/cm² (yellow and warmer) is a common threshold &nbsp;·&nbsp; Black = water colder than 26 °C or land &nbsp;·&nbsp; Dot = current JTWC position, solid line = track so far, dashed = JTWC forecast (dots every 24 h)',
    'sub.steer':        'Steering',
    'panel.steer':      'Steering Flow (500 hPa)',
    'note.steer':       'AIFS-single (ECMWF\'s AI model) 500 hPa streamlines, wind speed (shading) and height (gray, every 30 gpm) &nbsp;·&nbsp; Red line = 5880 gpm, the usual edge of the subtropical high: typhoons tend to move around it, heading west while the high extends west and turning north where it ends &nbsp;·&nbsp; Navy line and dot = AIFS-single track and the storm\'s position at that time &nbsp;·&nbsp; Tabs = forecast hour',
    'score.m.track': 'Track',
    'score.more':     'More measures: along-track, cross-track and intensity',
    'score.m.at': 'Along-track',
    'score.m.ct': 'Cross-track',
    'score.m.int': 'Intensity',
    'score.m.pending': 'Not enough data for this measure yet.',
    'score.chart.at': 'Mean along-track error (km) · + too fast, − too slow',
    'score.chart.ct': 'Mean cross-track error (km) · + right of track, − left',
    'score.chart.int': 'Mean intensity error (kt) · + too strong, − too weak',
    'score.note.at': 'Along-track error: measured along the storm\'s real direction of motion, is the forecast position ahead of (+) or behind (−) the real storm? A steady + means the model moves the storm too fast, − too slow. The small |e| is the average size ignoring the sign. Only counted while the storm moves at least 5 km/h; when it stalls or loops its direction is unreliable.',
    'score.note.ct': 'Cross-track error: at right angles to the real motion, is the forecast to the right (+) or left (−) of the real track? A model that stays on one side usually has a systematic steering bias, for example in how far west the subtropical high reaches. The small |e| is the average size ignoring the sign.',
    'score.note.int': 'Intensity error: forecast maximum wind minus the JTWC maximum wind (kt): + = forecast too strong, − = too weak. The small |e| is the average size ignoring the sign. Ensemble means smooth out the members and usually run weak, and coarser models often underestimate strong typhoons. Wind speeds were only archived from late October 2026 on, so older forecasts have no intensity to compare.',
    'sub.strikex':      'By Period',
    'panel.strikex':    'WN2-C 1000 Strike Probability by Period &amp; 34-kt Wind',
    'note.strikex':     'Same 1° rule split into forecast periods &nbsp;·&nbsp; 34 kt = inside the forecast 34-kt wind radii at any time &nbsp;·&nbsp; 1000 members',
    'city.tw_landfall': 'Taiwan (main island)',
    'sub.trend':        'Trend',
    'panel.trend':      'Track Trend',
    'note.trend':       'Ensemble mean tracks from every cycle since the storm first appeared, older = lighter &nbsp;·&nbsp; Shows which way successive forecasts have shifted &nbsp;·&nbsp; AIFS-single / ECMWF HRES / AIGFS / GFS tabs = deterministic run (amber)',
    'sub.plume':        'Intensity',
    'panel.plume':      'Intensity Forecast',
    'note.plume':       'Thin lines = members &nbsp;·&nbsp; Navy line = median &nbsp;·&nbsp; Band = 10–90% &nbsp;·&nbsp; RI = intensifying ≥ 30 kt within 24 h &nbsp;·&nbsp; Amber line = deterministic run (AIFS / ECMWF / AIGFS / GFS)',
    'sub.cities':     'Landfall & Cities',
    'panel.cities':   'Taiwan Landfall &amp; City Strike Probability',
    'cities.grp.land': 'Taiwan landfall',
    'cities.grp.land.sub': 'storm centre moves onto Taiwan\'s main island (outlying islands excluded)',
    'cities.grp.city': 'City strike',
    'cities.grp.city.sub': 'track passes within 1° (~111 km) of the city',
    'cities.city':    'Model',
    'note.cities':    'Share of members whose track passes within 1° (~111 km) of the city &nbsp;·&nbsp; Time below = median first arrival among those members (UTC) &nbsp;·&nbsp; Under each model: init time (UTC) · forecast length; a short run can show &lt;1% simply because it ends before the storm arrives &nbsp;·&nbsp; Taiwan cities always shown; others only when any model reaches 1% &nbsp;·&nbsp; AIFS-single / ECMWF HRES / AIGFS / GFS = deterministic run: ✓ = hits (with arrival time)',
    'city.taipei':       'Taipei',
    'city.taichung':     'Taichung',
    'city.kaohsiung':    'Kaohsiung',
    'city.hualien':      'Hualien',
    'city.hengchun':     'Hengchun',
    'city.naha':         'Naha',
    'city.manila':       'Manila',
    'city.hongkong':     'Hong Kong',
    'city.xiamen':       'Xiamen',
    'city.shanghai':     'Shanghai',
    'city.seoul':        'Seoul',
    'city.tokyo':        'Tokyo',
    'city.guam':         'Guam',
    'panel.comparison': 'Multi-Model Comparison',
    'note.comparison':  "Ensemble mean tracks and deterministic runs from every model on one map &nbsp;·&nbsp; Hollow dots = 24-hr steps &nbsp;·&nbsp; Parentheses in the legend give each model's initialization time (day/hour Z)",
    'zoom.hint':        '🔍 Click to enlarge',
    'panel.anim':       '{model} Track Evolution Animation',
    'panel.anim.generic': 'Track Evolution Animation',
    'note.anim':        'Step through the forecast frame by frame to watch the ensemble tracks unfold over time.',
    'pl.play':          'Play',
    'pl.pause':         'Pause',
    'pl.prev':          'Previous frame',
    'pl.next':          'Next frame',
    'kbd.hint':         '<kbd>Space</kbd> play/pause &nbsp;<kbd>←</kbd><kbd>→</kbd> seek',
    'panel.ensemble':   'Ensemble Track Forecast',
    'note.ensemble':    '{model} &nbsp;·&nbsp; Colored lines = ensemble members (color = intensity) &nbsp;·&nbsp; Navy line = ensemble mean &nbsp;·&nbsp; Cyclone symbol = initial position',
    'panel.jtwc':       'JTWC Official Forecast',
    'note.jtwc':        'Source: Joint Typhoon Warning Center (JTWC) — U.S. Navy &amp; Air Force',
    'panel.genesis':    'Western Pacific Tropical Cyclone Genesis Potential — Ensemble Overview',
    'note.genesis':     'Circles = ensemble members at each 6-hr step, colored by minimum sea level pressure. Gray lines = individual ensemble tracks (up to 360 h; GEFS 120 h). Data sourced from {source}.',
    'note.cluster':     'Each line is one of 1000 ensemble members. Named storms are grouped by track ID (tracks the tracker lost and re-detected are rejoined); unnamed tracks are clustered by genesis time and position. Percentages = share of members in which the system lasts at least 12 h; gray = sparse tracks. Data sourced from {source}.',
    'about.kicker':     'About',
    'about.title':      'How to read this site',
    'about.intro':      'This site gathers AI and physics-based ensemble forecasts for Western Pacific tropical cyclones and redraws them in one common style every 10–15 minutes, next to the official forecasts from JTWC, JMA (Japan) and CWA (Taiwan). Each storm page has five tabs: Summary (a 3-hour Himawari-9 infrared satellite loop, the ocean heat content under the storm, the vertical wind shear along the AIFS track, the 500 hPa steering flow, the JTWC forecast, the official forecasts side by side, and Taiwan landfall and city strike probabilities), Track (model comparison, ensemble maps, animation, an interactive map and track trend), Strike (strike probabilities by area, by period and for 34-kt winds), Intensity (intensity forecast) and Verification (track, along-/cross-track and intensity errors). One model menu at the top switches every chart to the same model. The Archive keeps every storm after it is gone, with its real track and how the forecasts did.',
    'about.prob':       'Probabilities on this site are the share of ensemble members that forecast an outcome — a measure of how much the models agree, not an official forecast probability. A deterministic run (AIFS-single, ECMWF HRES, AIGFS, GFS) is a single possible scenario.',
    'about.scale':      'Intensity categories',
    'about.reading':    'Reading the maps',
    'about.keys':       'Keyboard shortcuts',
    'about.app':        'Use it like an app',
    'about.app.text':   'iPhone: open the site in Safari, tap Share → Add to Home Screen. Android: open it in Chrome, tap ⋮ → Add to home screen. It opens full screen like an app and always shows the latest forecast. Links shared on LINE or Facebook show a preview card with the latest map, storm name, intensity and update time.',
    'about.notice':     'Notice',
    'about.disclaimer': 'Not for operational use. For official warnings, follow your national meteorological agency.',
    'key.views':        'Switch pages',
    'key.play':         'Play / pause the animation on screen',
    'key.seek':         'Step animation frames',
    'key.esc':          'Close the enlarged image',
    'footer.title':     "Pillar's Tropical Cyclone Forecast System",
    'footer.desc':      'Ensemble track forecasts from DeepMind WeatherNext (WN3-C, WN2-C r2, WN2-C r1, WN2-C 1000, GENC), ECMWF Open Data (AIFS-ENS + AIFS-single, IFS ENS + HRES) and NOAA NCEP (AIGEFS + AIGFS, GEFS + GFS).<br>Official forecasts from JTWC, JMA and CWA; satellite imagery from Himawari-9 (JMA), via NOAA Open Data on AWS; ocean heat content from Copernicus Marine (CMEMS), with HYCOM as backup. Steering flow and vertical wind shear are from AIFS-single (ECMWF Open Data). Data refreshed automatically.',
    'footer.link1':     '🌐 DeepMind Weather',
    'footer.link2':     '🇪🇺 ECMWF Open Data',
    'footer.link3':     '🇺🇸 NOAA NOMADS',
    'footer.link4':     '🇯🇵 JMA Typhoon Information',
    'footer.link5':     '🇹🇼 CWA Open Data',
    'footer.link6':     '🌊 Copernicus Marine (CMEMS)',
    'footer.link7':     '🌊 HYCOM',
    'footer.link8':     '🛰️ Himawari-9 (NOAA Open Data)',
    'footer.copy':      "© 2026 Pillar's Weather Site · Made by Pillar · Not for operational use",
    'lb.close':         'Close',
    'img.broken':       'Image unavailable',
    'rel.now':          'just now',
    'rel.min':          '{n} min ago',
    'rel.hr':           '{n} h ago',
    'status.stale':     'Data may be stale — last update {t}',
    'status.next':      'Next refresh in {t}',
  },
  zh: {
    'doc.title':        'Pillar 熱帶氣旋預報',
    'brand.title':      'Pillar 熱帶氣旋預報',
    'brand.sub':        'WN3-C / WN2-C r2 / WN2-C r1 / WN2-C 1000 / GENC / AIFS / ECMWF / AIGFS / GFS 即時系集預報系統 · 西北太平洋',
    'header.updated':   '更新於',
    'btn.dark':         '🌙 深色',
    'btn.light':        '☀️ 淺色',
    'btn.lang':         '🌐 English',
    'btn.lang.short':   'EN',
    'btn.tz.utc':       '🕒 UTC',
    'btn.tz.tw':        '🕒 臺灣時間',
    'btn.tz.utc.short': 'UTC',
    'btn.tz.tw.short':  'UTC+8',
    'btn.tz.title':     '更新時間以{z}顯示。點一下在 UTC 與臺灣時間（UTC+8）之間切換；頁面其他時間一律是 UTC。',
    'nav.overview':     '總覽',
    'nav.storms':       '颱風',
    'nav.genesis':      '生成潛勢',
    'nav.about':        '說明',
    'nav.archive':      '歷史',
    'arch.kicker':      '過往颱風',
    'arch.title':       '颱風歷史存檔',
    'arch.lead':        '本站追蹤過的每一顆颱風：JTWC 的實際路徑、各模式每一期的預報如何變化，以及最後誤差有多大。點一顆颱風打開。',
    'arch.active':      '進行中',
    'arch.inits':       '{n} 筆預報',
    'arch.init':        '起報',
    'arch.all':         '顯示所有期數',
    'arch.noscore':     '這顆颱風還沒有可校驗的預報。',
    'note.arch.trend':  '颱風結束前畫的最後一版：每一期的系集平均（或決定報）路徑，越舊越淡 &nbsp;·&nbsp; 看預報一路往哪個方向修正',
    'note.arch.map':    '粗的彩色線＝JTWC 實際路徑，依強度上色 &nbsp;·&nbsp; 橘線＝選取那一期的預報，每 24 小時一個圓點 &nbsp;·&nbsp; 細線＝同一模式的其他期數，淺＝較舊、深＝較新 &nbsp;·&nbsp; 拖動滑桿逐期查看；模式名稱後的數字是存了幾期',
    'hero.eyebrow.live':  '正在追蹤',
    'hero.eyebrow.multi': '正在追蹤 {count} 個颱風',
    'hero.eyebrow.quiet': '西北太平洋 · 監測中',
    'hero.quiet.title': '目前風平浪靜',
    'hero.quiet.sub':   '目前沒有活躍的熱帶氣旋。生成潛勢圖顯示各系集成員認為下一個系統可能在哪裡形成。',
    'hero.live.sub':    '{count} 個活躍系統 · 綜合 {models} 個模式的系集預報，每 10–15 分鐘更新。',
    'hero.cta.storm':   '查看預報',
    'hero.cta.genesis': '生成潛勢',
    'hero.now':         '現在時間',
    'cap.score':        '各模式隨預報時數的平均誤差',
    'cap.cities':       '各模式的登陸臺灣與城市侵襲機率',
    'cap.official':     '各單位、各預報時數的官方預報',
    'hero.active':      '活躍系統',
    'statement':        '我們在<strong>人工智慧</strong>與<strong>物理模式</strong>的交會點追蹤熱帶氣旋——每一個系集成員、每 10–15 分鐘更新，與官方預報並列呈現。',
    'sec.active.kicker':'即時',
    'sec.active':       '活躍系統',
    'sec.genesis.kicker':'展望',
    'sec.genesis':      '生成潛勢',
    'sec.models.kicker':'資料來源',
    'sec.models':       '預報模式',
    'models.on':        '本次有產出',
    'tile.open':        '查看完整預報 →',
    'genesis.teaser':   '下一個颱風可能在哪裡生成？查看 {n} 個模式的系集生成訊號。',
    'genesis.open':     '查看生成潛勢 →',
    'genesis.compare':  '模式比較',
    'genesis.compare.hint': '拖曳分隔線比較兩個模式',
    'empty.title':      '目前無活躍系統',
    'empty.status':     '狀態',
    'empty.await':      '等待資料中…',
    'empty.desc':       '目前沒有發展中的系統，每 10–15 分鐘自動更新',
    'storm.subtitle':   '西北太平洋熱帶氣旋',
    'badge.live':       '即時',
    'catname.TD':       '熱帶性低氣壓',
    'catname.TS':       '熱帶風暴',
    'catname.Cat1':     '一級颱風',
    'catname.Cat2':     '二級颱風',
    'catname.Cat3':     '三級颱風',
    'catname.Cat4':     '四級颱風',
    'catname.Cat5':     '五級超級颱風',
    'catname.Unknown':  '強度未知',
    'stat.time':        '觀測時間',
    'stat.pos':         '中心位置',
    'stat.wind':        '最大風速',
    'stat.pres':        '最低氣壓',
    'stat.models':      '模式',
    'scale.title':      '強度分級（薩菲爾－辛普森）',
    'sub.cmp':          '模式比較',
    'sub.anim':         '動畫',
    'sub.maps':         '系集與 JTWC',
    'sub.strike':       '侵襲機率',
    'panel.strike':     '侵襲機率',
    'note.strike':      '各 0.1° 格點：預報期間內路徑曾通過其 1°（約 111 公里）以內的系集成員比例 &nbsp;·&nbsp; 不考慮強度',
    'sub.tmap':         '互動地圖',
    'panel.tmap':       '互動式路徑地圖',
    'tmap.members':     '成員',
    'tmap.mean':        '平均',
    'tmap.det':         '決定報',
    'tmap.init':        '起報',
    'tmap.compare':     '多模式比較',
    'run.latest':       '最新',
    'tmap.all':         '全部',
    'tmap.na':          '尚未出報',
    'note.tmap':        '拖曳、滾輪縮放 &nbsp;·&nbsp; 滑鼠移到線上看成員、時間（UTC）與風速 &nbsp;·&nbsp; 成員顏色＝強度 &nbsp;·&nbsp; 多模式比較：模式可任選、全部也行，一個模式一種顏色，虛線＝決定報 &nbsp;·&nbsp; 起報時間按鈕：所有模式一起切到同一期',
    'sub.score':        '校驗',
    'panel.score':      '模式路徑誤差',
    'score.model':      '模式',
    'score.all':        '所有颱風合計（近 90 天）',
    'score.pending':    '資料累積中——預報發出 24 小時後，才會有第一筆可以比對的誤差。',
    'note.score':       '路徑誤差＝各預報位置與同時間 JTWC 警報位置的平均距離（公里）；其他分頁把它拆成沿／跨路徑，或比較強度 &nbsp;·&nbsp; 同質樣本＝同一颱風、同一起報時間、同一時數上所有模式都有的預報，比較才公平 &nbsp;·&nbsp; 顏色是同一時數內各模式相比：綠＝最好、紅＝最差（沿／跨路徑：越接近 0 越綠）；★＝最好，+x%＝比最好多出的誤差 &nbsp;·&nbsp; 淡色＝不到 3 筆，不參與排名',
    'score.tab.allst.homog': '所有颱風・同質樣本',
    'score.tab.allst.all': '所有颱風・全部樣本',
    'score.tab.storm.homog': '這顆颱風・同質樣本',
    'score.tab.storm.all': '這顆颱風・全部樣本',
    'score.tab.allst.same': '所有颱風',
    'score.tab.storm.same': '這顆颱風',
    'score.same':       '目前每一期各模式都到齊，同質樣本與全部樣本相同，合併顯示。',
    'score.onestorm':   '目前只有這顆颱風有可校驗的預報，與所有颱風合計相同。',
    'score.grp.ens': '系集平均',
    'score.grp.det': '決定報',
    'score.grp.det.sub': '單一路徑，通常不如系集平均準',
    'score.grp.jtwc': '官方預報（JTWC）',
    'score.grp.jtwc.sub': '以 JTWC 自己的警報位置為實況，數字會偏有利，不參與排名',
    'score.chart.y': '平均路徑誤差（公里）',
    'sub.official':     '官方預報',
    'panel.official':   '各國官方預報比較',
    'off.now':          '現在',
    'off.hour':         '時數',
    'note.official':    'JTWC（美國）、JMA（日本氣象廳）與 CWA（中央氣象署）的官方路徑 &nbsp;·&nbsp; JTWC 用 1 分鐘平均風速，JMA 與 CWA 用 10 分鐘平均，同一颱風 JTWC 的數字通常較大 &nbsp;·&nbsp; 各單位下方時間＝預報基準時間（UTC） &nbsp;·&nbsp; 地圖標籤＝預報的實際時間，日/時 UTC（例如 23/12Z＝23 日 12:00 UTC＝臺灣時間 20:00）',
    'sub.sat':          '衛星雲圖',
    'tab.now':          '概況',
    'tab.track':        '路徑',
    'tab.strike':       '侵襲',
    'tab.int':          '強度',
    'tab.score':        '校驗',
    'mp.label':         '模式',
    'mp.fallback':      '這張圖沒有 {m}，顯示 {y}',
    'note.how':         '怎麼看這張圖',
    'tmap.fail':        '地圖載入失敗，請重新整理頁面再試一次。',
    'panel.sat':        '衛星雲圖動畫（最近 3 小時）',
    'note.sat':         '向日葵 9 號紅外線雲圖（第 13 頻道，10.4 µm），最近 3 小時、每 10 分鐘一幀，以颱風為中心，一開始顯示最新一幀 &nbsp;·&nbsp; 顏色代表雲頂溫度：雲頂越冷，雲越高、對流越強；被最冷顏色包圍的暖點就是颱風眼與眼牆 &nbsp;·&nbsp; 以 JTWC 最新位置為中心（公報每 6 小時一次，颱風可能已移動一些）；路徑與 JTWC 預報畫在下方的海洋熱含量圖 &nbsp;·&nbsp; 原始資料取自 NOAA 在 AWS 上的日本氣象廳向日葵資料，每幀標題為觀測時間',
    'sub.shear':        '風切',
    'panel.shear':      '沿 AIFS 路徑的垂直風切',
    'note.shear':       '200 hPa 與 850 hPa 風的向量差，取颱風中心外 200–800 km 的平均，沿 AIFS-single（決定報）的預報路徑每 6 小時一點；風場與路徑來自同一期 AIFS &nbsp;·&nbsp; 風切大時颱風上下層環流被吹得錯開，通常難以增強：10 kt 以下為弱、10–20 kt 中等、20 kt 以上為強 &nbsp;·&nbsp; 箭頭＝風切指向的方向（由低層風指向高層風），颱風最強的對流與降雨常偏在順風切方向的左側 &nbsp;·&nbsp; 資料：ECMWF Open Data',
    'sub.ohc':          '海洋熱含量',
    'panel.ohc':        '海洋熱含量',
    'panel.ohctrack':   '沿 JTWC 路徑的海洋熱含量',
    'note.ohctrack':    '沿 JTWC 最新預報路徑、每 6 小時取樣的颱風中心底下海洋熱含量（中心 ±0.5° 內的平均） &nbsp;·&nbsp; 虛線＝50 kJ/cm²，常用的增強門檻：高於它暖水層夠厚，颱風自己攪動海水也不太會把海面變冷 &nbsp;·&nbsp; 灰方塊＝陸地或低於 26 °C 的海水 &nbsp;·&nbsp; 海洋分析是每日一張快照，這裡畫的是颱風若照 JTWC 路徑走會遇到的海洋，不是海洋本身的變化',
    'caveat.intensity': '這裡的強度只能看趨勢，不能當成最大風速的預報。AI 模式（WN3-C、WN2-C、GENC、AIFS、AIGFS）解析度約 0.25°，解析不出眼牆，強颱常偏弱數十 kt；ECMWF 與 GFS 系集也偏弱。颱風會多強，請看「概況」裡的官方預報（JTWC／JMA／CWA）；這些曲線拿來看會增強還是減弱、大約什麼時候。「校驗」分頁有各模式對這顆颱風實際的強度偏差。',
    'score.official':   'JTWC／JMA／CWA 列是官方預報，用同一套方法校驗；它們的存檔比模式晚開始，只列在「全部」樣本，不進同質樣本。',
    'note.ohc':         '熱帶氣旋熱潛能：海面到 26 °C 等溫線之間、高於 26 °C 的熱量（kJ/cm²），由 CMEMS（歐盟哥白尼海洋服務）1/12° 最新一天的海洋分析計算，取不到時改用 HYCOM（美國海軍） &nbsp;·&nbsp; 暖水層越厚，颱風攪動海水時底下越不容易變冷，越有利增強；常用約 50 kJ/cm²（黃色以上）當門檻 &nbsp;·&nbsp; 黑色＝低於 26 °C 的海水或陸地 &nbsp;·&nbsp; 圓點＝JTWC 目前位置，實線＝目前為止的路徑，虛線＝JTWC 預報（每 24 小時一點）',
    'sub.steer':        '駛流場',
    'panel.steer':      '駛流場（500 hPa）',
    'note.steer':       'AIFS-single（ECMWF 的 AI 模式）的 500 hPa 流線、風速（底色）與高度（灰線，每 30 gpm 一條） &nbsp;·&nbsp; 紅線＝5880 gpm，通常當作太平洋高壓的邊緣：颱風多沿著它的外圍移動，高壓西伸時往西走、到高壓西緣轉北 &nbsp;·&nbsp; 深藍線與圓點＝AIFS-single 路徑與颱風在該時刻的位置 &nbsp;·&nbsp; 分頁＝預報時數',
    'score.m.track': '路徑誤差',
    'score.more':     '其他指標：沿路徑、跨路徑與強度',
    'score.m.at': '沿路徑',
    'score.m.ct': '跨路徑',
    'score.m.int': '強度',
    'score.m.pending': '這項指標的資料還在累積中。',
    'score.chart.at': '平均沿路徑誤差（公里）・＋偏快、−偏慢',
    'score.chart.ct': '平均跨路徑誤差（公里）・＋偏右、−偏左',
    'score.chart.int': '平均強度誤差（kt）・＋偏強、−偏弱',
    'score.note.at': '沿路徑誤差：沿著颱風實際的移動方向，預報位置在實際颱風的前面（＋）還是後面（−）。持續為＋代表模式把颱風移得太快，−代表太慢。小字 |e| 是不分正負的平均大小。只在颱風移動速度至少 5 km/h 時計算；滯留或打轉時方向不可靠。',
    'score.note.ct': '跨路徑誤差：垂直於實際移動方向，預報偏在實際路徑的右側（＋）還是左側（−）。一直偏同一側，通常代表模式對駛流有系統性偏差，例如太平洋高壓西伸的程度。小字 |e| 是不分正負的平均大小。',
    'score.note.int': '強度誤差：預報最大風速減 JTWC 實況最大風速（kt）：＋＝預報太強、−＝太弱。小字 |e| 是不分正負的平均大小。系集平均會把成員的強度平滑掉，通常偏弱；解析度較粗的模式也常低估強颱。2026 年 10 月下旬才開始存預報風速，更早的預報沒有強度可比。',
    'sub.strikex':      '分時段',
    'panel.strikex':    'WN2-C 1000 分時段侵襲機率與七級風機率',
    'note.strikex':     '同樣的 1° 規則，依預報時段分開計算 &nbsp;·&nbsp; 34 kt＝預報期間曾落入 34 kt（七級風）暴風半徑內 &nbsp;·&nbsp; 1000 成員',
    'city.tw_landfall': '臺灣本島',
    'sub.trend':        '趨勢',
    'panel.trend':      '預報趨勢',
    'note.trend':       '這顆颱風從第一報到最新一報的所有系集平均路徑，越舊越淡 &nbsp;·&nbsp; 看預報一路往哪個方向修正 &nbsp;·&nbsp; AIFS-single／ECMWF HRES／AIGFS／GFS 分頁＝決定報（琥珀色）',
    'sub.plume':        '強度',
    'panel.plume':      '強度預報',
    'note.plume':       '細線＝各成員 &nbsp;·&nbsp; 深藍線＝中位數 &nbsp;·&nbsp; 色帶＝10–90% 範圍 &nbsp;·&nbsp; RI（快速增強）＝24 小時內增強 ≥ 30 kt &nbsp;·&nbsp; 琥珀線＝決定報（AIFS／ECMWF／AIGFS／GFS）',
    'sub.cities':     '登陸與城市',
    'panel.cities':   '登陸臺灣與城市侵襲機率',
    'cities.grp.land': '登陸臺灣',
    'cities.grp.land.sub': '颱風中心進入臺灣本島（不含離島）',
    'cities.grp.city': '城市侵襲',
    'cities.grp.city.sub': '路徑通過城市 1°（約 111 公里）以內',
    'cities.city':    '模式',
    'note.cities':    '路徑通過城市 1°（約 111 公里）內的成員比例 &nbsp;·&nbsp; 下方時間＝這些成員最早抵達時間的中位數（UTC） &nbsp;·&nbsp; 模式名稱下＝起報時間（UTC）· 預報長度，預報較短的模式可能在颱風抵達前就結束，因此顯示 &lt;1% &nbsp;·&nbsp; 臺灣城市一律列出，其他城市任一模式達 1% 才列出 &nbsp;·&nbsp; AIFS-single／ECMWF HRES／AIGFS／GFS＝決定報：✓＝會侵襲（附抵達時間）',
    'city.taipei':       '臺北',
    'city.taichung':     '臺中',
    'city.kaohsiung':    '高雄',
    'city.hualien':      '花蓮',
    'city.hengchun':     '恆春',
    'city.naha':         '那霸',
    'city.manila':       '馬尼拉',
    'city.hongkong':     '香港',
    'city.xiamen':       '廈門',
    'city.shanghai':     '上海',
    'city.seoul':        '首爾',
    'city.tokyo':        '東京',
    'city.guam':         '關島',
    'panel.comparison': '多模式比較',
    'note.comparison':  '各模式的系集平均路徑與決定性預報同框比較 &nbsp;·&nbsp; 空心圓點＝每 24 小時 &nbsp;·&nbsp; 圖例括號內為各模式的起報時間（日／時 Z）',
    'zoom.hint':        '🔍 點擊放大',
    'panel.anim':       '{model} 路徑演變動畫',
    'panel.anim.generic': '路徑演變動畫',
    'note.anim':        '逐格檢視預報，看系集路徑如何隨預報時間展開。',
    'pl.play':          '播放',
    'pl.pause':         '暫停',
    'pl.prev':          '上一格',
    'pl.next':          '下一格',
    'kbd.hint':         '<kbd>空白鍵</kbd> 播放／暫停 &nbsp;<kbd>←</kbd><kbd>→</kbd> 逐格',
    'panel.ensemble':   '系集路徑預報',
    'note.ensemble':    '{model} &nbsp;·&nbsp; 彩色線＝系集成員（顏色代表強度） &nbsp;·&nbsp; 深藍線＝系集平均 &nbsp;·&nbsp; 颱風符號＝起始位置',
    'panel.jtwc':       'JTWC 官方預報',
    'note.jtwc':        '資料來源：美國聯合颱風警報中心（JTWC）— 美國海軍與空軍',
    'panel.genesis':    '西北太平洋熱帶氣旋生成潛勢 — 系集綜覽',
    'note.genesis':     '圓圈＝各系集成員每 6 小時的位置，顏色代表海平面最低氣壓。灰線＝各系集成員的個別路徑（最長 360 小時；GEFS 只到 120 小時）。資料來源：{source}。',
    'note.cluster':     '每條線是 1000 個系集成員之一。已命名系統依編號分群（追蹤器跟丟後重新編號的路徑會接回原系統），尚未生成的系統依生成時間與位置聚類；百分比＝該系統延續至少 12 小時的成員比例，灰線＝零星、未成群的路徑。資料來源：{source}。',
    'about.kicker':     '說明',
    'about.title':      '如何閱讀本站',
    'about.intro':      '本站彙整 AI 與物理模式對西北太平洋熱帶氣旋的系集預報，每 10–15 分鐘以統一的樣式重新繪製，並與 JTWC、日本氣象廳與中央氣象署的官方預報並列。每個颱風頁分成五個分頁：「概況」（最近 3 小時的向日葵 9 號紅外線衛星雲圖動畫、颱風底下的海洋熱含量、沿 AIFS 路徑的垂直風切、500 hPa 駛流場、JTWC 預報、各國官方預報比較、登陸臺灣與城市侵襲機率）、「路徑」（模式比較、系集路徑圖、動畫、互動地圖、預報趨勢）、「侵襲」（區域、分時段與七級風侵襲機率）、「強度」（強度預報）、「校驗」（模式的路徑、沿／跨路徑與強度誤差）。上方的模式選單可以一次把所有圖切到同一個模式。「歷史」頁保留每一顆颱風消散後的實際路徑與各模式的預報表現。',
    'about.prob':       '本站的「機率」是系集成員中有多少比例這樣預報，代表模式之間的一致程度，不是官方的機率預報；決定報（AIFS-single、ECMWF HRES、AIGFS、GFS）只是其中一種可能情境。',
    'about.scale':      '強度分級',
    'about.reading':    '圖面說明',
    'about.keys':       '鍵盤快捷鍵',
    'about.app':        '像 App 一樣使用',
    'about.app.text':   'iPhone：用 Safari 打開本站，按「分享 → 加入主畫面」。Android：用 Chrome 打開，按 ⋮ →「加到主畫面」。點圖示會以全螢幕打開，每次都是最新的預報。分享到 LINE 或 Facebook 的連結會顯示預覽卡片：最新的預報圖、颱風名稱、強度與更新時間。',
    'about.notice':     '注意事項',
    'about.disclaimer': '本站僅供參考，不可作為作業依據；官方警報請以各國氣象單位發布為準。',
    'key.views':        '切換頁面',
    'key.play':         '播放／暫停畫面上的動畫',
    'key.seek':         '動畫逐格播放',
    'key.esc':          '關閉放大的圖片',
    'footer.title':     'Pillar 熱帶氣旋預報系統',
    'footer.desc':      '系集路徑預報來自 DeepMind WeatherNext（WN3-C、WN2-C r2、WN2-C r1、WN2-C 1000、GENC）、ECMWF Open Data（AIFS-ENS + AIFS-single、IFS ENS + HRES）與 NOAA NCEP（AIGEFS + AIGFS、GEFS + GFS）。<br>官方預報來自 JTWC、日本氣象廳與中央氣象署；衛星雲圖來自日本氣象廳向日葵 9 號（經 NOAA 在 AWS 上的開放資料）；海洋熱含量來自哥白尼海洋服務（CMEMS），HYCOM 為備援；駛流場與垂直風切來自 ECMWF Open Data 的 AIFS-single。資料自動更新。',
    'footer.link1':     '🌐 DeepMind 天氣實驗室',
    'footer.link2':     '🇪🇺 ECMWF 開放資料',
    'footer.link3':     '🇺🇸 NOAA NOMADS',
    'footer.link4':     '🇯🇵 日本氣象廳颱風資訊',
    'footer.link5':     '🇹🇼 中央氣象署開放資料',
    'footer.link6':     '🌊 哥白尼海洋服務（CMEMS）',
    'footer.link7':     '🌊 HYCOM 海洋模式',
    'footer.link8':     '🛰️ 向日葵 9 號（NOAA 開放資料）',
    'footer.copy':      '© 2026 Pillar 氣象網 · Made by Pillar · 僅供參考，請勿作為作業依據',
    'lb.close':         '關閉',
    'img.broken':       '圖片暫時無法載入',
    'rel.now':          '剛剛',
    'rel.min':          '{n} 分鐘前',
    'rel.hr':           '{n} 小時前',
    'status.stale':     '資料可能已過時（最後更新 {t}）',
    'status.next':      '{t} 後自動更新',
  }
};

// 先讀使用者上次的選擇，沒有的話看瀏覽器語言（zh-* 一律給中文）
let currentLang = (function () {
    try {
        const saved = localStorage.getItem('lang');
        if (saved === 'zh' || saved === 'en') return saved;
    } catch (e) {}
    return (navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en';
})();

function t(key, params) {
    const dict = I18N[currentLang] || I18N.en;
    let s = (dict[key] !== undefined) ? dict[key] : (I18N.en[key] !== undefined ? I18N.en[key] : '');
    if (params) for (const k in params) s = s.split('{' + k + '}').join(params[k]);
    return s;
}

// ── 時區：UTC／臺灣時間（UTC+8，無夏令時間）。只有頁首的更新時間（<time class="tz">）跟著切換，
// 內文的時間（抵達、起報、官方基準時間、地圖提示）一律 UTC，與圖片裡的時間一致 ──
let tzMode = (function () {
    try { const v = localStorage.getItem('tz'); if (v === 'utc' || v === 'tw') return v; } catch (e) {}
    return currentLang === 'zh' ? 'tw' : 'utc';
})();
function tzDate(iso) {
    let s = String(iso || '');
    if (!/[zZ]$|[+-]\d\d:?\d\d$/.test(s)) s += 'Z';       // 沒寫時區的一律當 UTC，不要被當成本地時間
    const d = new Date(s);
    return isNaN(d) ? null : d;
}
function fmtTz(iso, fmt) {
    const d = tzDate(iso);
    if (!d) return null;
    const tw = tzMode === 'tw';
    const u = new Date(d.getTime() + (tw ? 8 * 3600e3 : 0));
    const p = n => String(n).padStart(2, '0');
    const Y = u.getUTCFullYear(), M = p(u.getUTCMonth() + 1), D = p(u.getUTCDate()), H = p(u.getUTCHours()), m = p(u.getUTCMinutes()), s = p(u.getUTCSeconds());
    switch (fmt) {
        case 'mdh':  return tw ? `${M}/${D} ${H}:00` : `${M}/${D} ${H}Z`;
        case 'dhm':  return tw ? `${D} / ${H}:${m} UTC+8` : `${D} / ${H}:${m} UTC`;
        case 'ymd':  return `${Y}-${M}-${D}`;
        case 'hm':   return `${H}:${m}`;
        case 's':    return `:${s}`;
        case 'full': return `${Y}-${M}-${D} ${H}:${m}:${s} ${tw ? 'UTC+8' : 'UTC'}`;
    }
    return null;
}
function applyTz(mode, save = true) {
    tzMode = mode === 'tw' ? 'tw' : 'utc';
    root.setAttribute('data-tz', tzMode);
    $$('time.tz').forEach(el => {
        const txt = fmtTz(el.dataset.utc, el.dataset.fmt || 'mdh');
        if (txt !== null) el.textContent = txt;
    });
    const b = $('#tz-btn');
    if (b) {
        const k = tzMode === 'tw' ? 'btn.tz.tw' : 'btn.tz.utc';
        b.innerHTML = btnHTML(t(k), t(k + '.short'));
        b.setAttribute('aria-pressed', tzMode === 'tw' ? 'true' : 'false');
        b.title = t('btn.tz.title', { z: t(k).replace(/^\S+\s/, '') });
    }
    if (save) {
        try { localStorage.setItem('tz', tzMode); } catch (e) {}
        if (typeof NavDrop !== 'undefined') NavDrop.fit();     // 按鈕寬度變了，導覽列與指示塊要重新量
        requestAnimationFrame(updateIndicators);
    }
    document.dispatchEvent(new CustomEvent('tzchange'));
}

function i18nParams(el) {
    const p = {};
    for (const k in el.dataset) {
        if (k.startsWith('i18n') && k !== 'i18n' && k !== 'i18nAttr') p[k.slice(4).toLowerCase()] = el.dataset[k];
    }
    return p;
}

function applyLang(lang, save = true) {
    currentLang = (lang === 'zh') ? 'zh' : 'en';
    root.setAttribute('lang', currentLang === 'zh' ? 'zh-Hant' : 'en');
    $$('[data-i18n]').forEach(el => {
        const txt = t(el.dataset.i18n, i18nParams(el));
        if (!txt) return;                       // 字典沒這個 key 就保留原文，不要清空
        if (el.dataset.i18nAttr) el.setAttribute(el.dataset.i18nAttr, txt);
        else el.innerHTML = txt;
    });
    root.style.setProperty('--broken-text', JSON.stringify(t('img.broken')));
    const langBtn = $('#lang-btn');
    if (langBtn) langBtn.innerHTML = btnHTML(t('btn.lang'), t('btn.lang.short'));
    applyTz(tzMode, false);                    // 時區按鈕文字跟著語言換；<time> 文字也重排
    applyTheme(root.getAttribute('data-theme') || 'light', false);
    $$('.split').forEach(splitText);
    $$('.words').forEach(splitWords);
    updateWords();
    $$('.player').forEach(el => players[el.dataset.animKey] && setPlayBtn(players[el.dataset.animKey]));
    updateTitle();
    NavDrop.fit();                             // 中英文字寬不同，排不排得下要重算
    requestAnimationFrame(updateIndicators);   // 字寬變了，指示塊要重新量
    tickClock();
    if (save) { try { localStorage.setItem('lang', currentLang); } catch (e) {} }
}

// View Transition 的保險：瀏覽器若遲遲不執行更新（分頁在背景、轉場被中斷等），
// 0.7 秒後直接套用，確保主題／語言一定會切過去；轉場之後才跑到也只是 no-op。
function runTransition(update) {
    let done = false;
    const once = () => { if (!done) { done = true; update(); } };
    const tr = document.startViewTransition(once);
    setTimeout(once, 700);
    return tr;
}

// 切換語言：支援 View Transitions 的瀏覽器整頁模糊交錯淡入，否則只淡入換過字的元素
function switchLang() {
    const next = currentLang === 'zh' ? 'en' : 'zh';
    const spinGlobe = () => {
        const b = $('#lang-btn');
        if (b) { b.classList.remove('spin'); void b.offsetWidth; b.classList.add('spin'); }
    };
    if (reduced()) { applyLang(next); return; }
    if (document.startViewTransition) {
        root.classList.add('lang-vt');
        const tr = runTransition(() => { applyLang(next); spinGlobe(); });
        tr.finished.finally(() => root.classList.remove('lang-vt'));
        setTimeout(() => root.classList.remove('lang-vt'), 1500);
    } else {
        root.classList.remove('lang-fallback'); void root.offsetWidth;
        applyLang(next); spinGlobe();
        root.classList.add('lang-fallback');
        setTimeout(() => root.classList.remove('lang-fallback'), 500);
    }
}

// 標題逐字進場：拆成字元 span；中日文字每個字自成一組，才能正常換行
function splitText(el) {
    const text = el.textContent.trim();
    el.setAttribute('aria-label', text);
    const tokens = text.match(/[⺀-鿿豈-﫿＀-￯]|[^\s⺀-鿿豈-﫿＀-￯]+|\s+/g) || [];
    // 「·」併進前一個字詞（同一個不換行的 .w）：多個颱風名字換行時，點留在上一行尾，不會跑到下一行開頭
    const toks = [];
    for (const tok of tokens) {
        if (tok === '·' && toks.length > 1 && /^\s+$/.test(toks[toks.length - 1])) { toks.pop(); toks[toks.length - 1] += '\u00a0·'; }
        else toks.push(tok);
    }
    let i = 0, out = '';
    toks.forEach(tok => {
        if (/^\s+$/.test(tok)) { out += ' '; return; }
        out += '<span class="w" aria-hidden="true">';
        for (const ch of tok) out += `<span class="ch" style="--i:${i++}">${ch.replace(/&/g,'&amp;').replace(/</g,'&lt;')}</span>`;
        out += '</span>';
    });
    el.innerHTML = out;
}

// 標語逐字點亮：拆成字詞 span（中文一字一組），保留 <strong> 強調；
// 捲動時 updateWords() 依段落在畫面中的位置，由左至右把字點亮。
function splitWords(el) {
    const wrap = s => (s.match(/[⺀-鿿豈-﫿＀-￯]|[^\s⺀-鿿豈-﫿＀-￯]+|\s+/g) || [])
        .map(tok => /^\s+$/.test(tok) ? ' ' : `<span class="wd">${tok.replace(/&/g,'&amp;').replace(/</g,'&lt;')}</span>`).join('');
    let out = '';
    el.childNodes.forEach(n => {
        if (n.nodeType === 3) out += wrap(n.textContent);
        else if (n.nodeType === 1) out += `<${n.tagName.toLowerCase()}>${wrap(n.textContent)}</${n.tagName.toLowerCase()}>`;
    });
    el.innerHTML = out;
}
function updateWords() {
    $$('.view.active .words').forEach(el => {
        const ws = el.querySelectorAll('.wd');
        const r = el.getBoundingClientRect();
        const p = reduced() ? 1 : (innerHeight * 0.82 - r.top) / (r.height + innerHeight * 0.3);
        const lit = Math.round(Math.max(0, Math.min(1, p)) * ws.length);
        ws.forEach((w, i) => w.classList.toggle('lit', i < lit));
    });
}
let wordsRaf = 0;
window.addEventListener('scroll', () => {
    if (!wordsRaf) wordsRaf = requestAnimationFrame(() => { wordsRaf = 0; updateWords(); });
}, { passive: true });
window.addEventListener('resize', updateWords, { passive: true });

// 頁首按鈕拆成「圖示＋文字」：窄螢幕只顯示圖示（或短字），頁首才能擠成一排
function btnHTML(label, short) {
    const i = label.indexOf(' ');
    const icon = i > 0 ? label.slice(0, i) : '', text = i > 0 ? label.slice(i + 1) : label;
    return `<span class="bi">${icon}</span><span class="bt">${text}</span>` +
           (short ? `<span class="bt-short">${short}</span>` : '');
}

// ── Theme ─────────────────────────────────────────────────────────
// 預設依時段（18–6 點深色），已在 <head> 先套用；按鈕切換時用圓形擴散轉場。
function applyTheme(theme, save = true) {
    root.setAttribute('data-theme', theme);
    const btn = $('#theme-btn');
    if (btn) btn.innerHTML = btnHTML(theme === 'dark' ? t('btn.light') : t('btn.dark'));
    if (save) { try { localStorage.setItem('theme', theme); } catch (e) {} }
}

function toggleTheme(ev) {
    const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    if (!document.startViewTransition || reduced()) { applyTheme(next); return; }
    const r = ev && ev.currentTarget ? ev.currentTarget.getBoundingClientRect() : null;
    const x = r ? r.left + r.width / 2 : innerWidth / 2;
    const y = r ? r.top + r.height / 2 : 0;
    const rad = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    const tr = runTransition(() => applyTheme(next));
    tr.ready.then(() => {
        root.animate({ clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${rad}px at ${x}px ${y}px)`] },
                     { duration: 650, easing: 'cubic-bezier(.4,0,.2,1)', pseudoElement: '::view-transition-new(root)' });
    }).catch(() => {});
}

// ── Router（#/overview、#/storm/WP..., #/genesis, #/about）─────────
const ROUTES = SITE.routes;
let currentRoute = null;
let navToken = 0;

function viewFor(route) { return $$('.view').find(v => v.dataset.view === route) || null; }

function parseHash() {
    const h = decodeURIComponent(location.hash.replace(/^#\/?/, ''));
    if (ROUTES.includes(h)) return h;
    if (h === 'storm') return ROUTES.find(r => r.startsWith('storm/')) || 'overview';
    return 'overview';
}

function show(route, first) {
    if (route === currentRoute) return;
    const next = viewFor(route);
    if (!next) return;
    const prevIdx = ROUTES.indexOf(currentRoute);
    const dir = ROUTES.indexOf(route) >= prevIdx ? 1 : -1;
    currentRoute = route;
    const token = ++navToken;
    updateNav();

    const swap = () => {
        if (token !== navToken) return;             // 使用者已經又點了別頁
        $$('.view.active').forEach(v => {
            if (v === next) return;
            v.classList.remove('active', 'leaving', 'entering');
            pausePlayersIn(v);
        });
        next.style.setProperty('--dir', dir);
        next.classList.add('active');
        if (!first && !reduced()) {
            next.classList.remove('entering'); void next.offsetWidth; next.classList.add('entering');
        }
        if (!first) window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
        onViewShown(next);
    };
    const leaving = $$('.view.active').filter(v => v !== next);
    if (!first && leaving.length && !reduced()) {
        leaving.forEach(v => { v.style.setProperty('--dir', dir); v.classList.add('leaving'); });
        setTimeout(swap, 150);
    } else swap();
}

function updateTitle() {
    const v = currentRoute && viewFor(currentRoute);
    let name = '';
    if (v) name = v.dataset.title || (v.dataset.titleKey ? t(v.dataset.titleKey) : '');
    document.title = (name && currentRoute !== 'overview' ? name + ' · ' : '') + t('doc.title')
                   + (SITE.trackIds ? ' | ' + SITE.trackIds : '');
}

function updateNav() {
    $$('.top-nav .nav-link, .nav-menu-item').forEach(a => a.classList.toggle('active', a.dataset.route === currentRoute));
    $$('.top-nav [data-route-prefix]').forEach(b =>
        b.classList.toggle('active', !!(currentRoute && currentRoute.startsWith(b.dataset.routePrefix))));
    NavDrop.close();
    $$('.bottom-nav a').forEach(a => {
        const on = a.dataset.route ? a.dataset.route === currentRoute
                 : (a.dataset.routePrefix && currentRoute && currentRoute.startsWith(a.dataset.routePrefix));
        a.classList.toggle('active', !!on);
        if (on && a.dataset.routePrefix) a.setAttribute('href', '#/' + currentRoute);
    });
    updateTitle();
    requestAnimationFrame(updateIndicators);
}

function onViewShown(view) {
    requestAnimationFrame(updateIndicators);
    refreshSubnavs();
    scrollSpy();
    Hero.setActive(view.dataset.view === 'overview' && !Globe.ready);
    Globe.route(view.dataset.view);
    updateWords();
}

window.addEventListener('hashchange', () => show(parseHash(), false));

// ── 滑動指示塊（頂部導覽列與模式分頁共用）─────────────────────────
function placeIndicator(ind, target) {
    if (!ind || !target || !target.offsetParent) { if (ind) ind.style.opacity = '0'; return; }
    ind.style.width = target.offsetWidth + 'px';
    ind.style.height = target.offsetHeight + 'px';
    ind.style.transform = `translate(${target.offsetLeft}px, ${target.offsetTop}px)`;
    ind.style.opacity = '1';
}
function updateIndicators() {
    const nav = $('.top-nav');
    // 收合時被隱藏的颱風連結也帶 active，要挑看得見的那個
    if (nav) placeIndicator($('.nav-indicator', nav), $$('.nav-link.active', nav).find(a => a.offsetParent));
    $$('.seg').forEach(seg => {
        if (!seg.offsetParent) return;
        placeIndicator($('.seg-ind', seg), $('.model-tab-btn.active', seg));
        seg.classList.add('ready');
        segFade(seg);
    });
}
window.addEventListener('resize', () => requestAnimationFrame(() => { NavDrop.fit(); updateIndicators(); }));
// 分頁列可左右滑時，哪一邊還有東西就淡出哪一邊
function segFade(seg) {
    const max = seg.scrollWidth - seg.clientWidth;
    seg.classList.toggle('fade-l', max > 1 && seg.scrollLeft > 1);
    seg.classList.toggle('fade-r', max > 1 && seg.scrollLeft < max - 1);
}
document.addEventListener('scroll', e => { if (e.target.classList && e.target.classList.contains('seg')) segFade(e.target); }, true);
function revealTab(btn) {
    const seg = btn.closest('.seg');
    if (!seg || seg.scrollWidth <= seg.clientWidth + 1) return;
    const left = btn.offsetLeft - (seg.clientWidth - btn.offsetWidth) / 2;
    seg.scrollTo({ left: Math.max(0, left), behavior: reduced() ? 'auto' : 'smooth' });
}

// ── Model tab switching (WN3-C / WN2-C r2 / WN2-C r1 / GENC for the same storm) ──
function switchModelTab(trackId, model) {
    $$('.model-panel').filter(el => el.dataset.track === trackId).forEach(el => {
        const isActive = el.dataset.model === model;
        const wasHidden = el.style.display === 'none';
        // A panel whose image already failed to load stays hidden even if selected —
        // otherwise switching tabs away and back would silently un-hide the broken image.
        el.style.display = (isActive && el.dataset.broken !== 'true') ? '' : 'none';
        if (isActive && wasHidden && !reduced()) {
            el.classList.remove('swap-in'); void el.offsetWidth; el.classList.add('swap-in');
        }
        // Pause any animation living in the panel being hidden
        if (!isActive) pausePlayersIn(el);
    });
    $$('.model-tab-btn').filter(b => b.dataset.track === trackId)
        .forEach(b => {
            const on = b.dataset.model === model;
            b.classList.toggle('active', on);
            b.setAttribute('aria-selected', on ? 'true' : 'false');
            if (on && b.offsetParent) revealTab(b);
        });
    requestAnimationFrame(updateIndicators);
}

// 模式分頁連動：系集與決定報、名稱寫法不同的分頁（AIFS-ENS／AIFS-single／AIFS）算同一個模式。
// 不是模式名稱的分頁（衛星雲圖、時段、時數、成績單範圍）對不上任何模式，不受影響。
function modelGroup(name) {
    const n = String(name || '').toUpperCase().replace(/-ENS$|-SINGLE$| HRES$/, '');
    return ({AIGEFS: 'AIGFS', GEFS: 'GFS'})[n] || n;
}
function linkModelTabs(tab) {
    const view = tab.closest('.view');
    if (!view) return;
    const g = modelGroup(tab.dataset.model);
    // 頁面分頁（概況／路徑…）不參與連動：成績單的「強度誤差」鈕和「強度」分頁同名，會被誤切過去
    const tracks = new Set($$('.model-tab-btn:not(.storm-tab)', view).map(b => b.dataset.track));
    tracks.delete(tab.dataset.track);
    tracks.forEach(tr => {
        const btns = $$('.model-tab-btn', view).filter(b => b.dataset.track === tr);
        const hit = btns.find(b => b.dataset.model === tab.dataset.model) || btns.find(b => modelGroup(b.dataset.model) === g);
        if (hit && !hit.classList.contains('active')) switchModelTab(tr, hit.dataset.model);
    });
}

// ── 颱風頁：上方分頁（概況／路徑／侵襲／強度／校驗）與整頁一個模式選單 ──────────
// 分頁沿用 model-tab-btn／model-panel 的切換機制；換頁時若已捲過分頁列，捲回分頁列頂端。
// 模式選單取代各圖自己的模式分頁：選了之後每張圖都切到同一個模式，各圖的分頁列隱藏；
// 同一模式有系集與決定性兩種（如 AIFS-ENS／AIFS-single）時，該圖只留這兩顆小分頁。
function pickModel(view, name, save = true) {
    const g = modelGroup(name);
    $$('.seg.mt-linked', view).forEach(seg => {
        const btns = $$('.model-tab-btn', seg);
        const hits = btns.filter(b => modelGroup(b.dataset.model) === g);
        btns.forEach(b => { b.hidden = hits.length > 0 && !hits.includes(b); });
        seg.classList.toggle('mt-variants', hits.length > 1);
        let pick = hits.find(b => b.classList.contains('active')) || hits[0];
        if (!pick) pick = btns.find(b => b.classList.contains('active')) || btns[0];
        if (pick && !pick.classList.contains('active')) switchModelTab(pick.dataset.track, pick.dataset.model);
        const panel = seg.closest('.panel');
        const chip = panel && $('.mt-shown', panel);
        if (!chip || !pick) return;
        chip.classList.toggle('miss', !hits.length);
        if (hits.length) { chip.removeAttribute('data-i18n'); chip.textContent = pick.dataset.model; }
        else {
            chip.setAttribute('data-i18n', 'mp.fallback');
            chip.dataset.i18nM = name; chip.dataset.i18nY = pick.dataset.model;
            chip.textContent = t('mp.fallback', { m: name, y: pick.dataset.model });
        }
    });
    const sel = $('.model-select', view);
    if (sel && sel.value !== name) sel.value = name;
    if (save) try { sessionStorage.setItem('model', name); } catch (e) {}
    requestAnimationFrame(updateIndicators);
}
function initStormTabs() {
    $$('.view[data-view^="storm/"]').forEach(view => {
        const sel = $('.model-select', view);
        if (sel) {
            const groups = new Set([...sel.options].map(o => modelGroup(o.value)));
            $$('.seg.model-tabs:not(.storm-tabs)', view).forEach(seg => {
                if ($$('.model-tab-btn', seg).some(b => groups.has(modelGroup(b.dataset.model)))) seg.classList.add('mt-linked');
            });
            let saved = null;
            try { saved = sessionStorage.getItem('model'); } catch (e) {}
            const opt = saved && [...sel.options].find(o => modelGroup(o.value) === modelGroup(saved));
            pickModel(view, opt ? opt.value : sel.value, false);
            sel.addEventListener('change', () => pickModel(view, sel.value));
        }
        // 自動重新整理後停在原本的分頁
        let tab = null;
        try { tab = sessionStorage.getItem('tab:' + view.dataset.view); } catch (e) {}
        const b = tab && $(`.storm-tab[data-model="${tab}"]`, view);
        if (b) switchModelTab(b.dataset.track, tab);
        syncModelPick(view);
    });
}
// 目前分頁沒有跟著模式切換的圖（概況、成績）時，模式選單先收起來
function syncModelPick(view) {
    const bar = $('.storm-bar', view), pane = $$('.tab-pane', view).find(p => p.style.display !== 'none');
    if (bar) bar.classList.toggle('no-pick', !!pane && !$('.seg.mt-linked', pane));
}
function onStormTab(btn) {
    const view = btn.closest('.view');
    syncModelPick(view);
    try { sessionStorage.setItem('tab:' + view.dataset.view, btn.dataset.model); } catch (e) {}
    const anchor = $('.storm-bar-anchor', view), bar = $('.storm-bar', view);
    if (anchor && bar) {
        const stuck = parseFloat(getComputedStyle(bar).top) || 0;
        const y = anchor.getBoundingClientRect().top + scrollY - stuck;
        if (scrollY > y) window.scrollTo({ top: y, behavior: 'instant' });
    }
}

// ── 捲動進場、數字跳動、儀表 ──────────────────────────────────────
function staggerReveals() {
    const groups = new Map();
    $$('.reveal').forEach(el => {
        const p = el.parentElement;
        const n = groups.get(p) || 0;
        el.style.setProperty('--i', Math.min(n, 8));
        groups.set(p, n + 1);
    });
}

// ── 互動式路徑地圖（Leaflet；捲到才載入函式庫與資料）──────────────
// 比較模式的模式配色：每個模式固定一種顏色（與強度色階無關），全部疊在一起也分得開
const TM_CMP_COLORS = {'WN3-C': '#7C3AED', 'WN2-C r2': '#2563EB', 'WN2-C r1': '#06B6D4', 'GENC': '#65A30D',
                       'AIFS': '#D946EF', 'ECMWF': '#DC2626', 'AIGFS': '#059669', 'GFS': '#F59E0B'};
const TM_CMP_EXTRA = ['#0EA5E9', '#F97316', '#64748B', '#A16207'];   // 沒列到的新模式依序輪用
const TM_COLORS = {TD:'#8A97A6', TS:'#2E86C8', Cat1:'#1FA97E', Cat2:'#E0AC2B', Cat3:'#EE7A22', Cat4:'#DC3A4E', Cat5:'#A548C8'};
function tmCat(kt) {
    if (kt == null) return 'TD';
    return kt < 35 ? 'TD' : kt < 64 ? 'TS' : kt < 83 ? 'Cat1' : kt < 96 ? 'Cat2' : kt < 113 ? 'Cat3' : kt < 137 ? 'Cat4' : 'Cat5';
}
let leafletP = null;
function loadLeaflet() {
    if (leafletP) return leafletP;
    leafletP = new Promise((res, rej) => {
        const css = document.createElement('link');
        css.rel = 'stylesheet';
        css.href = 'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css';
        document.head.appendChild(css);
        const js = document.createElement('script');
        js.src = 'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js';
        js.onload = () => res(window.L);
        js.onerror = rej;
        document.head.appendChild(js);
    });
    return leafletP;
}
function tmTiles(L) {
    const dark = document.documentElement.getAttribute('data-theme') === 'dark';
    // Esri 灰階底圖：不需金鑰（CARTO 底圖已改成要 API key）
    return L.tileLayer(`https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${dark ? 'World_Dark_Gray_Base' : 'World_Light_Gray_Base'}/MapServer/tile/{z}/{y}/{x}`,
        {attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ', maxZoom: 10});
}
async function initTrackMap(box) {
    if (box.dataset.ready) return;
    box.dataset.ready = '1';
    const el = box.querySelector('.tm-map');
    try {
        const [L, data] = await Promise.all([loadLeaflet(), fetch(box.dataset.src).then(r => r.json())]);
        const map = L.map(el, {preferCanvas: true}).setView([20, 130], 4);
        let tiles = tmTiles(L).addTo(map);
        // 切換深淺主題時換底圖
        new MutationObserver(() => { map.removeLayer(tiles); tiles = tmTiles(L).addTo(map); })
            .observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
        const layer = L.layerGroup().addTo(map);
        const sel = box.querySelector('.tm-model');
        const showM = box.querySelector('.tm-members');
        const showA = box.querySelector('.tm-mean');
        const showD = box.querySelector('.tm-det');
        Object.keys(data.models).forEach(m => sel.add(new Option(m, m)));
        const pad = n => String(n).padStart(2, '0');
        const fmtAt = (iso, h) => {
            const d = new Date(new Date(iso).getTime() + h * 3600e3);
            return `${pad(d.getUTCMonth() + 1)}/${pad(d.getUTCDate())} ${pad(d.getUTCHours())}Z`;
        };
        // cur＝目前畫的資料：「最新」是 data（各模式各自最新一期），選了某期就換成那期的檔（所有模式同一期）
        let cur = data, run = null;
        const fmt = (m, h) => fmtAt((cur.inits || {})[m] || cur.init, h);
        const has = m => {
            const d = cur.models[m];
            return !!d && ((d.members || []).length > 0 || (d.mean || []).length > 0 || (d.det || []).length > 1);
        };
        // 經度展開：跨換日線時不會連到地球另一邊
        const unwrap = pts => {
            let prev = null;
            return pts.map(p => {
                let lon = p[1];
                if (prev != null) { while (lon - prev > 180) lon -= 360; while (lon - prev < -180) lon += 360; }
                prev = lon;
                return [p[0], lon, p[2], p[3]];
            });
        };
        // 多模式比較（仿 Weather Lab）：模式數不限，每個模式固定一種顏色；成員、平均、決定報都用該模式的顏色
        const cmpBtn = box.querySelector('.tm-cmp-btn');
        const chipBox = box.querySelector('.tm-chips');
        const names = Object.keys(data.models);
        const palette = {};
        names.filter(m => !TM_CMP_COLORS[m]).forEach((m, i) => { palette[m] = TM_CMP_EXTRA[i % TM_CMP_EXTRA.length]; });
        const colorOf = m => TM_CMP_COLORS[m] || palette[m];
        const defaults = ['WN3-C', 'WN2-C r2', 'ECMWF'].filter(m => data.models[m]);
        names.forEach(m => { if (defaults.length < 2 && !defaults.includes(m)) defaults.push(m); });
        let picks = new Set(defaults);
        const cmpOn = () => cmpBtn.getAttribute('aria-pressed') === 'true';
        const shown = () => names.filter(m => picks.has(m));      // 照模式原本的順序
        const mkChip = (label, onclick) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'tm-chip';
            b.innerHTML = '<i></i>';
            b.append(label);
            b.onclick = () => { onclick(); syncChips(); showInit(); draw(false); };
            chipBox.appendChild(b);
            return b;
        };
        // 「全部」：還沒全選就全選，已全選就回到預設的幾個
        const allChip = mkChip('', () => { picks = new Set(picks.size === names.length ? defaults : names); });
        allChip.classList.add('tm-chip-all');
        allChip.lastChild.replaceWith(Object.assign(document.createElement('span'), {textContent: t('tmap.all') || 'All'}));
        allChip.lastChild.dataset.i18n = 'tmap.all';
        const chips = names.map(m => [m, mkChip(m, () => {
            if (!picks.has(m)) picks.add(m);
            else if (picks.size > 1) picks.delete(m);             // 至少留一個
        })]);
        function syncChips() {
            chips.forEach(([m, b]) => {
                const on = picks.has(m);
                b.setAttribute('aria-pressed', on);
                b.style.setProperty('--c', on ? colorOf(m) : '');
            });
            allChip.setAttribute('aria-pressed', picks.size === names.length);
        }
        syncChips();
        const ptsTip = (m, d, p, det) => det
            ? `${d.det_name || 'DET'} +${p[3]}h · ${d.det_init ? fmtAt(d.det_init, p[3]) : fmt(m, p[3])} · ${p[2] ?? '–'} kt`
            : `${cmpOn() ? m + ' ' : ''}+${p[3]}h · ${fmt(m, p[3])} · ${p[2] ?? '–'} kt`;
        // 平均或決定報：白邊＋色線＋24h 圓點；比較模式的決定報改虛線，與平均區分
        function drawLine(m, d, raw, color, det, bounds) {
            const pts = unwrap(raw), ll = pts.map(p => [p[0], p[1]]);
            const dash = det && cmpOn() ? '6 5' : null;
            // 線細一點、白邊淡一點：與靜態圖一致，經過臺灣時陸地輪廓仍看得到
            L.polyline(ll, {color: '#fff', weight: det ? 4.4 : 4.6, opacity: .6, dashArray: dash}).addTo(layer);
            L.polyline(ll, {color, weight: det ? 2.6 : 2.8, opacity: .9, dashArray: dash})
                .bindTooltip(det ? (d.det_name || 'Deterministic') : `${m} ${t('tmap.mean')}`, {sticky: true}).addTo(layer);
            pts.filter(p => p[3] % 24 === 0).forEach(p =>
                L.circleMarker([p[0], p[1]], {radius: det ? 3.8 : 4, color, weight: 1.6, fillColor: '#fff', fillOpacity: 1})
                    .bindTooltip(ptsTip(m, d, p, det)).addTo(layer));
            ll.forEach(p => bounds.push(p));
        }
        // 只有第一次載入時縮放到路徑範圍；之後切模式／期數都保留使用者目前的畫面，方便對照
        function draw(fit) {
            layer.clearLayers();
            const cmp = cmpOn(), list = (cmp ? shown() : [sel.value]).filter(has), bounds = [];
            // 選了某期而模式還沒出報：地圖上方標示
            const miss = run ? (cmp ? shown() : [sel.value]).filter(m => !has(m)) : [];
            msg.hidden = !miss.length;
            msg.textContent = miss.length ? `${miss.join('、')} ${fmtAt(run, 0)} ${t('tmap.na')}` : '';
            // 先畫所有成員，再畫平均與決定報，粗線才不會被別的模式的成員蓋住
            if (showM.checked) list.forEach(m => (cur.models[m].members || []).forEach((raw, i) => {
                const pts = unwrap(raw);
                if (cmp) {
                    // 模式一多成員線就淡一點，平均線才看得出來
                    L.polyline(pts.map(p => [p[0], p[1]]), {color: colorOf(m), weight: 1.1, opacity: list.length > 3 ? .2 : .35})
                        .bindTooltip(`${m} #${i + 1}`, {sticky: true}).addTo(layer);
                } else for (let k = 0; k < pts.length - 1; k++) {
                    const a = pts[k], b = pts[k + 1];
                    L.polyline([[a[0], a[1]], [b[0], b[1]]], {color: TM_COLORS[tmCat(a[2])], weight: 1.3, opacity: .7})
                        .bindTooltip(`#${i + 1} · ${fmt(m, a[3])} · ${a[2] ?? '–'} kt`, {sticky: true}).addTo(layer);
                }
                pts.forEach(p => bounds.push([p[0], p[1]]));
            }));
            // 決定報（AIFS／ECMWF／AIGFS／GFS 才有）：單一模式時是琥珀色線，沒有時把開關藏起來
            const hasDet = list.some(m => cur.models[m].det && cur.models[m].det.length > 1);
            showD.closest('label').style.display = hasDet ? '' : 'none';
            list.forEach(m => {
                const d = cur.models[m];
                if (showA.checked && (d.mean || []).length) drawLine(m, d, d.mean, cmp ? colorOf(m) : '#16324F', false, bounds);
                if (showD.checked && d.det && d.det.length > 1) drawLine(m, d, d.det, cmp ? colorOf(m) : '#B45309', true, bounds);
            });
            // 與靜態圖一致：轉溫帶後跑到高緯的成員不算進範圍（AIGFS／GFS 會一路追到極區）
            const cap = Math.max(45, Math.min(...bounds.map(p => p[0])) + 10);
            const fb = bounds.filter(p => p[0] <= cap);
            if (fit && fb.length) map.fitBounds(fb, {padding: [20, 20]});
        }
        // 選單旁顯示該模式的起報時間（各模式不一定同一期）
        const initVal = box.querySelector('.tm-init-val');
        const initOf = m => {
            if (run) return has(m) ? fmtAt(run, 0) : t('tmap.na');
            const init = data.inits[m] || data.init;
            const md = data.models[m] || {};
            // 決定報比系集新一期時一併標出，免得以為兩條線是同一期
            return fmtAt(init, 0) + (md.det_init && md.det_init !== init
                ? ` · ${md.det_name || 'DET'} ${fmtAt(md.det_init, 0)}` : '');
        };
        const showInit = () => {
            initVal.textContent = run ? fmtAt(run, 0)
                : cmpOn() ? shown().map(m => `${m} ${initOf(m)}`).join('　') : initOf(sel.value);
        };
        // 起報時間按鈕：「最新」＋各期；選了某期，還沒出報的模式按鈕變灰、按不下去
        const msg = Object.assign(document.createElement('div'), {className: 'tm-msg', hidden: true});
        el.appendChild(msg);
        const runBox = box.querySelector('.tm-runs');
        const runCache = {};
        const loadRun = iso => runCache[iso] || (runCache[iso] = fetch(
            box.dataset.src.replace(/\.json$/, `_${iso.slice(0, 13).replace(/[-T]/g, '')}.json`)).then(r => r.json()));
        function syncAvail() {
            chips.forEach(([m, b]) => {
                const na = !has(m);
                b.classList.toggle('tm-na', na);
                b.disabled = na;
                b.title = na ? t('tmap.na') : '';
            });
            [...sel.options].forEach(o => { o.textContent = has(o.value) ? o.value : `${o.value}（${t('tmap.na')}）`; });
        }
        const runs = data.runs || [];
        if (runs.length) {
            [null, ...runs].forEach(iso => {
                const b = document.createElement('button');
                b.type = 'button';
                b.className = 'run-btn' + (iso ? '' : ' active');
                b.innerHTML = iso ? fmtAt(iso, 0) : `<span data-i18n="run.latest">${t('run.latest') || 'Latest'}</span>`;
                b.onclick = async () => {
                    if (b.classList.contains('active')) return;
                    try { cur = iso ? await loadRun(iso) : data; }
                    catch (e) { console.log('[trackmap]', e); return; }
                    run = iso;
                    runBox.querySelectorAll('.run-btn').forEach(x => x.classList.toggle('active', x === b));
                    syncAvail(); showInit(); draw(false);
                };
                runBox.appendChild(b);
            });
        } else runBox.remove();
        showInit();
        sel.onchange = () => { showInit(); draw(false); };
        cmpBtn.onclick = () => {
            cmpBtn.setAttribute('aria-pressed', !cmpOn());
            box.classList.toggle('tm-cmp', cmpOn());
            showInit(); draw(false);
        };
        showM.onchange = () => draw(false);
        showA.onchange = () => draw(false);
        showD.onchange = () => draw(false);
        draw(true);
    } catch (e) {
        el.textContent = t('tmap.fail');
        console.log('[trackmap]', e);
    }
}
const tmIO = ('IntersectionObserver' in window) ? new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) { tmIO.unobserve(e.target); initTrackMap(e.target); }
}), {rootMargin: '200px'}) : null;
document.querySelectorAll('.track-map').forEach(b => tmIO ? tmIO.observe(b) : initTrackMap(b));

// ── 颱風歷史存檔：點颱風卡片 → 載入 archive/{tid}.json 畫路徑、載入成績單片段 ──
(() => {
    const view = document.querySelector('.view[data-view="archive"]');
    if (!view) return;
    const box = view.querySelector('.arch-detail');
    const sel = box.querySelector('.arch-model');
    const slider = box.querySelector('.arch-slider');
    const allBox = box.querySelector('.arch-all');
    const initVal = box.querySelector('.arch-init-val');
    const mapEl = box.querySelector('.arch-map');
    const scoreEl = box.querySelector('.arch-score');
    const trendEl = box.querySelector('.arch-trend');
    const OLD = [126, 196, 232], NEW = [59, 47, 143];          // 舊期淺藍 → 新期深紫，同趨勢圖
    const PICK = '#E8963A';
    const PREFER = ['WN3-C', 'ECMWF-ENS', 'WN2-C r2', 'AIFS-ENS', 'GENC'];
    const pad = n => String(n).padStart(2, '0');
    const fmt = (iso, h = 0) => {
        const d = new Date(new Date(iso).getTime() + h * 3600e3);
        return `${pad(d.getUTCMonth() + 1)}/${pad(d.getUTCDate())} ${pad(d.getUTCHours())}Z`;
    };
    const isoOf = st => `${st.slice(0, 4)}-${st.slice(4, 6)}-${st.slice(6, 8)}T${st.slice(8, 10)}:00:00Z`;
    const mix = f => `rgb(${OLD.map((a, i) => Math.round(a + (NEW[i] - a) * f)).join(',')})`;
    const unwrap = pts => { let prev = null; return pts.map(p => {
        let lon = p[2];
        if (prev != null) { while (lon - prev > 180) lon -= 360; while (lon - prev < -180) lon += 360; }
        prev = lon; return [p[1], lon, p]; }); };
    let L = null, map = null, layer = null, tiles = null, data = null, inits = [];
    const i18nIn = el => el.querySelectorAll('[data-i18n]').forEach(x => {
        const txt = t(x.dataset.i18n, i18nParams(x)); if (txt) x.innerHTML = txt; });

    function draw(fit) {
        layer.clearLayers();
        const m = sel.value, fc = data.fcst[m] || {};
        const k = +slider.value, pick = inits[k];
        initVal.textContent = pick ? fmt(isoOf(pick)) : '–';
        const bounds = [];
        if (allBox.checked) inits.forEach((st, i) => {
            if (st === pick) return;
            const pts = unwrap(fc[st]);
            L.polyline(pts.map(p => [p[0], p[1]]), {color: mix(inits.length > 1 ? i / (inits.length - 1) : 1), weight: 1.4, opacity: .55})
                .bindTooltip(`${m} · ${fmt(isoOf(st))}`, {sticky: true}).addTo(layer);
        });
        // 實況：白邊＋依強度分段上色，每個定位點一個小圓點
        const obs = (data.obs || []).map(r => [r[1], r[2], r]);
        let prev = null;
        const ob = obs.map(o => { let lon = o[1]; if (prev != null) { while (lon - prev > 180) lon -= 360; while (lon - prev < -180) lon += 360; } prev = lon; return [o[0], lon, o[2]]; });
        L.polyline(ob.map(p => [p[0], p[1]]), {color: '#fff', weight: 7, opacity: .75}).addTo(layer);
        for (let i = 0; i < ob.length - 1; i++)
            L.polyline([[ob[i][0], ob[i][1]], [ob[i + 1][0], ob[i + 1][1]]], {color: TM_COLORS[tmCat(ob[i][2][3])], weight: 4.5, opacity: 1}).addTo(layer);
        ob.forEach(p => {
            L.circleMarker([p[0], p[1]], {radius: 3.2, color: '#16324F', weight: 1, fillColor: TM_COLORS[tmCat(p[2][3])], fillOpacity: 1})
                .bindTooltip(`JTWC · ${fmt(p[2][0])} · ${p[2][3] ?? '–'} kt`).addTo(layer);
            bounds.push([p[0], p[1]]);
        });
        if (pick) {
            const pts = unwrap(fc[pick]), ll = pts.map(p => [p[0], p[1]]);
            L.polyline(ll, {color: '#fff', weight: 5.2, opacity: .8}).addTo(layer);
            L.polyline(ll, {color: PICK, weight: 3.2, opacity: 1}).bindTooltip(`${m} · ${fmt(isoOf(pick))}`, {sticky: true}).addTo(layer);
            pts.filter(p => p[2][0] % 24 === 0).forEach(p =>
                L.circleMarker([p[0], p[1]], {radius: 4, color: PICK, weight: 1.6, fillColor: '#fff', fillOpacity: 1})
                    .bindTooltip(`${m} +${p[2][0]}h · ${fmt(isoOf(pick), p[2][0])} · ${p[2][3] ?? '–'} kt`).addTo(layer));
            ll.forEach(p => bounds.push(p));
        }
        if (fit && bounds.length) map.fitBounds(bounds, {padding: [24, 24]});
    }
    function setModel(fit) {
        inits = Object.keys(data.fcst[sel.value] || {}).sort();
        slider.max = Math.max(0, inits.length - 1);
        slider.value = slider.max;
        draw(fit);
    }
    async function open(tid, card) {
        view.querySelectorAll('.arch-card').forEach(c => c.classList.toggle('active', c === card));
        box.hidden = false;
        box.querySelector('.arch-title').textContent = card.querySelector('.arch-name').textContent + ' · ' + tid;
        try {
            // 成績單與趨勢圖不需要地圖：先放上去，地圖函式庫載不到也看得到
            const [html, trendHtml] = await Promise.all([
                fetch(`archive/${tid}_score.html`).then(r => r.ok ? r.text() : '').catch(() => ''),
                fetch(`archive/${tid}_trend.html`).then(r => r.ok ? r.text() : '').catch(() => '')]);
            scoreEl.innerHTML = html;
            i18nIn(scoreEl);
            trendEl.innerHTML = trendHtml;
            i18nIn(trendEl);
            // 預設顯示 WN3-C（有的話），與地圖的預設模式一致
            const tb = trendEl.querySelector('.model-tab-btn[data-model="WN3-C"]');
            if (tb) switchModelTab(tb.dataset.track, 'WN3-C');
            requestAnimationFrame(updateIndicators);
            box.scrollIntoView({behavior: reduced() ? 'auto' : 'smooth', block: 'start'});
            const [lib, d] = await Promise.all([loadLeaflet(), fetch(`archive/${tid}.json`).then(r => r.json())]);
            L = lib; data = d;
            if (!map) {
                map = L.map(mapEl, {preferCanvas: true}).setView([20, 130], 4);
                tiles = tmTiles(L).addTo(map);
                new MutationObserver(() => { map.removeLayer(tiles); tiles = tmTiles(L).addTo(map); })
                    .observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
                layer = L.layerGroup().addTo(map);
            }
            const models = Object.keys(data.fcst);
            models.sort((a, b) => (ARCH_ORDER.indexOf(a) + 99) % 99 - (ARCH_ORDER.indexOf(b) + 99) % 99);
            sel.innerHTML = '';
            models.forEach(m => sel.add(new Option(`${m}（${Object.keys(data.fcst[m]).length}）`, m)));
            sel.value = PREFER.find(m => data.fcst[m]) || models[0];
            setModel(true);
            requestAnimationFrame(() => { map.invalidateSize(); updateIndicators(); });
        } catch (e) {
            mapEl.textContent = 'Archive failed to load';
            console.log('[archive]', e);
        }
    }
    const ARCH_ORDER = SITE.archiveOrder || [];
    sel.onchange = () => setModel(false);
    slider.oninput = () => draw(false);
    allBox.onchange = () => draw(false);
    view.addEventListener('click', e => { const c = e.target.closest('.arch-card'); if (c) open(c.dataset.arch, c); });
})();

const revealIO = ('IntersectionObserver' in window) ? new IntersectionObserver(entries => {
    for (const e of entries) {
        if (!e.isIntersecting) continue;
        e.target.classList.add('in');
        revealIO.unobserve(e.target);
        onReveal(e.target);
    }
}, { threshold: 0.12, rootMargin: '0px 0px -5% 0px' }) : null;

function onReveal(el) {
    const scope = [el, ...$$('*', el)];
    scope.filter(n => n.dataset && n.dataset.count !== undefined).forEach(countUp);
    scope.filter(n => n.classList && n.classList.contains('gauge')).forEach(animateGauge);
    scope.filter(n => n.classList && n.classList.contains('ss-scale')).forEach(s => s.classList.add('in'));
}

function countUp(el) {
    const end = parseFloat(el.dataset.count);
    if (isNaN(end) || el._counted) return;
    el._counted = true;
    if (reduced()) { el.textContent = Math.round(end); return; }
    const t0 = performance.now(), dur = 1500;
    const from = end > 500 ? end - 60 : 0;         // 氣壓從接近的數字開始，不從 0 爬到 980
    const step = now => {
        const p = Math.min(1, (now - t0) / dur);
        const e = 1 - Math.pow(1 - p, 4);
        el.textContent = Math.round(from + (end - from) * e);
        if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
}

const G = { cx: 100, cy: 100, r: 78, rb: 93 };
function gPoint(v, r) {
    const th = Math.PI + (Math.min(Math.max(v, 0), SITE.scaleMax) / SITE.scaleMax) * Math.PI;
    return [G.cx + r * Math.cos(th), G.cy + r * Math.sin(th)];
}
function gArc(a, b, r) {
    const [x1, y1] = gPoint(a, r), [x2, y2] = gPoint(b, r);
    return `M${x1.toFixed(2)} ${y1.toFixed(2)} A${r} ${r} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}
function buildGauge(el) {
    const kt = parseFloat(el.dataset.kt);
    const bands = SITE.bands.map(([c, lo, hi, col]) =>
        `<path class="g-band" d="${gArc(lo + 0.8, hi - 0.8, G.rb)}" stroke="${col}"/>`).join('');
    const ticks = [64, 137].map(v => {
        const [x, y] = gPoint(v, 108);
        return `<text class="g-tick" x="${x.toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="middle">${v}</text>`;
    }).join('');
    el.innerHTML =
        `<svg viewBox="0 -12 200 128" aria-hidden="true">
            ${bands}
            <path class="g-track" d="${gArc(0, SITE.scaleMax, G.r)}"/>
            <path class="g-prog" d="${gArc(0, SITE.scaleMax, G.r)}" pathLength="100"/>
            ${ticks}
            <g class="g-needle"><line x1="${100 - 60}" y1="100" x2="${100 - 96}" y2="100"/></g>
        </svg>
        <div class="gauge-val"><b>${isNaN(kt) ? '—' : '<span data-count="' + kt + '">0</span>'}</b><small>KT</small></div>`;
    el.setAttribute('role', 'img');
    el.setAttribute('aria-label', isNaN(kt) ? 'Wind unknown' : `${kt} kt`);
    if (reduced()) animateGauge(el);
}
function animateGauge(el) {
    const kt = parseFloat(el.dataset.kt);
    if (isNaN(kt) || el._animated) return;
    el._animated = true;
    const frac = Math.min(kt, SITE.scaleMax) / SITE.scaleMax;
    const prog = $('.g-prog', el), needle = $('.g-needle', el);
    requestAnimationFrame(() => {
        if (prog) prog.style.strokeDashoffset = (100 - frac * 100).toFixed(2);
        if (needle) needle.style.transform = `rotate(${(frac * 180).toFixed(2)}deg)`;
    });
    const num = $('[data-count]', el);
    if (num) countUp(num);
}

// ── 段落導覽（颱風頁）：點擊平滑捲動、捲動時標示目前段落 ─────────────
function refreshSubnavs() {
    $$('.subnav').forEach(nav => {
        $$('button[data-target]', nav).forEach(b => {
            const sec = document.getElementById(b.dataset.target);
            // 收合起來的那組（details）裡的區塊沒有 offsetParent，但按了會展開，照樣列出
            const folded = sec && sec.closest('details:not([open])');
            b.hidden = !sec || sec.style.display === 'none' || !sec.offsetParent && !folded && nav.offsetParent !== null;
        });
    });
}
let spyRaf = 0;
function scrollSpy() {
    spyRaf = 0;
    const view = currentRoute && viewFor(currentRoute);
    const nav = view && $('.subnav', view);
    if (!nav) return;
    const line = nav.getBoundingClientRect().bottom + 60;   // 段落導覽黏在上方，以它的底緣為準（手機頁首不黏，不能用頁首高度算）
    let active = null;
    $$('button[data-target]', nav).forEach(b => {
        const sec = document.getElementById(b.dataset.target);
        if (sec && !b.hidden && sec.offsetParent && sec.getBoundingClientRect().top <= line) active = b;
    });
    if (!active) active = $$('button[data-target]', nav).find(b => !b.hidden) || null;
    $$('button', nav).forEach(b => b.classList.toggle('active', b === active));
}
document.addEventListener('click', e => {
    const b = e.target.closest('.subnav button[data-target]');
    if (!b) return;
    const sec = document.getElementById(b.dataset.target);
    if (!sec) return;
    const fold = sec.closest('details');
    if (fold && !fold.open) fold.open = true;
    sec.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' });
});
// 展開／收合「背景與校驗」後，區塊位置變了，段落導覽重新標示
document.addEventListener('toggle', e => {
    if (e.target.classList && e.target.classList.contains('sec-group')) { refreshSubnavs(); scrollSpy(); }
}, true);
document.addEventListener('error', e => { if (e.target && e.target.tagName === 'IMG') refreshSubnavs(); }, true);

// ── 捲動：頁首進度條、段落導覽 ──────────────────────────────────────
let progRaf = 0;
window.addEventListener('scroll', () => {
    if (!progRaf) progRaf = requestAnimationFrame(() => {
        progRaf = 0;
        const max = document.documentElement.scrollHeight - innerHeight;
        const bar = $('.scroll-progress');
        if (bar) bar.style.setProperty('--p', max > 0 ? (scrollY / max).toFixed(4) : 0);
    });
    if (!spyRaf) spyRaf = requestAnimationFrame(scrollSpy);
}, { passive: true });

// 頁首高度會因換行而變（手機兩列），黏性元素要跟著它的實際高度走
const header = $('#site-header');
function syncHeaderH() { if (header) root.style.setProperty('--header-h', header.offsetHeight + 'px'); }
if ('ResizeObserver' in window && header) new ResizeObserver(syncHeaderH).observe(header);
syncHeaderH();

// ── 卡片 3D 傾斜（僅限有滑鼠的裝置）────────────────────────────────
if (canHover) {
    document.addEventListener('pointermove', e => {
        const card = e.target.closest && e.target.closest('.tilt');
        $$('.tilt.tilting').forEach(c => { if (c !== card) { c.classList.remove('tilting'); c.style.transform = ''; } });
        if (!card || reduced()) return;
        const r = card.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5;
        card.classList.add('tilting');
        card.style.transform = `perspective(1000px) rotateX(${(-py * 5).toFixed(2)}deg) rotateY(${(px * 6).toFixed(2)}deg) translateY(-4px)`;
    }, { passive: true });
}

// ── Lightbox ──────────────────────────────────────────────────────
const lightbox = $('#lightbox');
function zoomImgOf(fig) { return $('img.is-front', fig) || $('img', fig); }
function openLightbox(src) {
    $('#lightbox-img').src = src;
    lightbox.classList.add('open');
    document.body.classList.add('lb-lock');
}
function closeLightbox() {
    lightbox.classList.remove('open');
    document.body.classList.remove('lb-lock');
}
// 系集路徑圖的歷史期數：同一個 model-panel 裡換圖
document.addEventListener('click', e => {
    const b = e.target.closest && e.target.closest('.run-btn');
    if (!b || b.classList.contains('active')) return;
    const panel = b.closest('.model-panel');
    if (!panel) return;                         // 互動地圖的期數鈕自己處理
    panel.querySelectorAll('.run-btn').forEach(x => x.classList.toggle('active', x === b));
    const img = panel.querySelector('.zoomable > img');
    if (img) img.src = b.dataset.src;
});
document.addEventListener('click', e => {
    if (lightbox.classList.contains('open')) { closeLightbox(); return; }   // 點任意處關閉
    const fig = e.target.closest('.zoomable');
    if (fig && !fig.classList.contains('broken')) { const img = zoomImgOf(fig); openLightbox(img.currentSrc || img.src); }
});

// ═════════════════════════════════════════════════════════════════
//  動畫播放器：進入畫面才預載、全部載完自動播放、雙緩衝淡入換格
// ═════════════════════════════════════════════════════════════════
const players = {};

function initPlayer(el) {
    let frames = [];
    try { frames = JSON.parse(el.dataset.frames || '[]'); } catch (e) {}
    const dir = el.dataset.framesDir || '';
    const P = {
        el, key: el.dataset.animKey,
        urls: frames.map(f => `${dir}/${f}`),
        i: Math.max(0, Math.min(frames.length - 1, parseInt(el.dataset.start, 10) || 0)),
        playing: false, timer: null, speed: 2,
        imgs: $$('.frame', el), front: 0,
        cache: [], loaded: 0, preloading: false,
        touched: false, autoPaused: false,
        stage: $('.frame-stage', el), slider: $('.timeline', el),
        counter: $('.frame-counter', el), btn: $('[data-act="toggle"]', el),
        buf: $('.buffer span', el),
    };
    players[P.key] = P;
    const first = P.imgs[0];
    const size = () => {
        if (!first.naturalWidth) return;
        P.stage.style.setProperty('--ar', `${first.naturalWidth} / ${first.naturalHeight}`);
        el.style.setProperty('--arv', (first.naturalWidth / first.naturalHeight).toFixed(4));   // 播放器寬度跟著圖，左右不留白
    };
    if (first.complete) size(); else first.addEventListener('load', size, { once: true });
    setPlayBtn(P);
    updPlayerUI(P);
    if (playerIO) playerIO.observe(el);
}
function preload(P) {
    if (P.preloading) return;
    P.preloading = true;
    const n = P.urls.length;
    P.urls.forEach((u, i) => {
        const im = new Image();
        im.decoding = 'async';
        im.onload = im.onerror = () => {
            P.loaded++;
            if (P.buf) P.buf.style.transform = `scaleX(${P.loaded / n})`;
            if (P.loaded === n) { P.stage.classList.add('buffered'); maybeAutoplay(P); }
        };
        im.src = u;
        P.cache[i] = im;
    });
}
function maybeAutoplay(P) {
    if (!P.touched && P.visible && !reduced() && P.loaded === P.urls.length && !lightbox.classList.contains('open')) play(P);
}
function renderFrame(P) {
    const url = P.urls[P.i];
    const front = P.imgs[P.front], back = P.imgs[1 - P.front];
    updPlayerUI(P);
    if (!url || !back || front.getAttribute('src') === url) return;
    let swapped = false;
    const swap = () => {
        if (swapped || back.getAttribute('src') !== url) return;   // 已被更新的一格取代
        swapped = true;
        back.classList.remove('was-front');
        back.classList.add('is-front');
        front.classList.replace('is-front', 'was-front');
        P.front = 1 - P.front;
    };
    // 換 src 前先把它沉到底層藏起來，解碼完才浮上來，不會露出還沒畫好的空白
    back.classList.remove('is-front', 'was-front');
    back.onload = null;
    back.src = url;
    const ready = () => (back.decode ? back.decode().catch(() => {}) : Promise.resolve()).then(swap);
    if (back.complete && back.naturalWidth) ready();
    else back.onload = () => { back.onload = null; ready(); };
}
function updPlayerUI(P) {
    const n = P.urls.length;
    if (P.slider) {
        P.slider.value = P.i;
        P.slider.style.setProperty('--fill', (n > 1 ? P.i / (n - 1) * 100 : 0) + '%');
    }
    if (P.counter) P.counter.textContent = `${P.i + 1}/${n}`;
}
function setPlayBtn(P) {
    if (P.btn) { const s = P.playing ? t('pl.pause') : t('pl.play'); P.btn.title = s; P.btn.setAttribute('aria-label', s); }
}
function frameDelay(P) { return Math.round(1000 / (P.speed * 1.5)); }
function tick(P) {
    if (!P.playing) return;
    const last = P.i === P.urls.length - 1;
    // 播到最後一格多停一下再從頭開始，看得清楚預報的終點
    P.timer = setTimeout(() => {
        P.i = (P.i + 1) % P.urls.length;
        renderFrame(P);
        tick(P);
    }, last ? frameDelay(P) * 5 : frameDelay(P));
}
function play(P) {
    if (P.playing || P.urls.length < 2) return;
    preload(P);
    P.playing = true;
    P.el.classList.add('playing');
    setPlayBtn(P);
    tick(P);
}
function pause(P) {
    P.playing = false;
    clearTimeout(P.timer); P.timer = null;
    P.el.classList.remove('playing');
    setPlayBtn(P);
}
function seek(P, i) {
    pause(P);
    P.i = Math.max(0, Math.min(P.urls.length - 1, i));
    renderFrame(P);
}
function pausePlayersIn(scope) {
    $$('.player', scope).forEach(el => { const P = players[el.dataset.animKey]; if (P) { pause(P); P.autoPaused = false; } });
}
const playerIO = ('IntersectionObserver' in window) ? new IntersectionObserver(entries => {
    for (const e of entries) {
        const P = players[e.target.dataset.animKey];
        if (!P) continue;
        P.visible = e.isIntersecting;
        if (e.isIntersecting) {
            preload(P);
            if (P.autoPaused) { P.autoPaused = false; play(P); }
            else maybeAutoplay(P);
        } else if (P.playing) {
            pause(P); P.autoPaused = true;      // 捲出畫面就先停，省電；捲回來再接著播
        }
    }
}, { threshold: 0.35 }) : null;

document.addEventListener('click', e => {
    const ct = e.target.closest('.city-toggle');
    if (ct) {
        const open = ct.getAttribute('aria-expanded') !== 'true';
        ct.setAttribute('aria-expanded', open ? 'true' : 'false');
        const wrap = ct.previousElementSibling;
        if (wrap && wrap.classList.contains('city-table-wrap')) wrap.classList.toggle('compact', !open);
        return;
    }
    const tab = e.target.closest('.model-tab-btn');
    if (tab) {
        switchModelTab(tab.dataset.track, tab.dataset.model);
        if (tab.classList.contains('storm-tab')) onStormTab(tab); else linkModelTabs(tab);
        return;
    }
    const pl = e.target.closest('.player');
    if (!pl) return;
    const P = players[pl.dataset.animKey];
    if (!P) return;
    const act = e.target.closest('[data-act]');
    const sp = e.target.closest('.speed-btn');
    if (act) {
        P.touched = true; P.autoPaused = false;
        if (act.dataset.act === 'toggle') P.playing ? pause(P) : play(P);
        else if (act.dataset.act === 'prev') seek(P, P.i - 1);
        else if (act.dataset.act === 'next') seek(P, P.i + 1);
    } else if (sp) {
        P.speed = parseFloat(sp.dataset.speed);
        $$('.speed-btn', pl).forEach(b => b.classList.toggle('active', b === sp));
        if (P.playing) { clearTimeout(P.timer); tick(P); }
    }
});
document.addEventListener('input', e => {
    if (!e.target.classList.contains('timeline')) return;
    const P = players[e.target.closest('.player').dataset.animKey];
    if (P) { P.touched = true; P.autoPaused = false; seek(P, parseInt(e.target.value, 10)); }
});

function visiblePlayer() {
    const view = currentRoute && viewFor(currentRoute);
    if (!view) return null;
    // 一頁有好幾個播放器（衛星雲圖、路徑動畫）時，鍵盤控制畫面上看得到的那個
    const shown = $$('.player', view).filter(p => p.offsetParent !== null);
    const el = shown.find(p => players[p.dataset.animKey] && players[p.dataset.animKey].visible) || shown[0];
    return el ? players[el.dataset.animKey] : null;
}

// ═════════════════════════════════════════════════════════════════
//  生成潛勢：左右拖曳比較兩個模式
// ═════════════════════════════════════════════════════════════════
function initCompare() {
    const box = $('#gen-compare'), btn = $('#gen-compare-btn');
    if (!box || !btn) return;
    const panel = box.closest('.genesis-panel');
    const stage = $('.cmp-stage', box), clip = $('.cmp-top', box), handle = $('.cmp-handle', box);
    const topImg = $('.cmp-top img', box), baseImg = $('.cmp-base', box);
    const selA = $('#cmp-a'), selB = $('#cmp-b');
    let pos = 50, dragging = false, swept = false;
    const set = p => {
        pos = Math.max(0, Math.min(100, p));
        clip.style.clipPath = `inset(0 ${100 - pos}% 0 0)`;
        handle.style.left = pos + '%';
        stage.setAttribute('aria-valuenow', Math.round(pos));
    };
    const fromEvent = e => { const r = stage.getBoundingClientRect(); set((e.clientX - r.left) / r.width * 100); };
    stage.addEventListener('pointerdown', e => { dragging = true; stage.setPointerCapture(e.pointerId); fromEvent(e); });
    stage.addEventListener('pointermove', e => { if (dragging) fromEvent(e); });
    stage.addEventListener('pointerup', () => { dragging = false; });
    stage.addEventListener('pointercancel', () => { dragging = false; });
    stage.addEventListener('keydown', e => {
        if (e.key === 'ArrowLeft') { set(pos - 4); e.preventDefault(); e.stopPropagation(); }
        if (e.key === 'ArrowRight') { set(pos + 4); e.preventDefault(); e.stopPropagation(); }
    });
    selA.addEventListener('change', () => { topImg.src = selA.value; });
    selB.addEventListener('change', () => { baseImg.src = selB.value; });
    // 第一次打開時分隔線左右掃一下，提示可以拖
    const sweep = () => {
        if (swept || reduced()) return;
        swept = true;
        const t0 = performance.now();
        const f = now => {
            const p = Math.min(1, (now - t0) / 1600);
            set(50 + Math.sin(p * Math.PI * 2) * 22 * (1 - p));
            if (p < 1 && !dragging) requestAnimationFrame(f);
        };
        requestAnimationFrame(f);
    };
    btn.addEventListener('click', () => {
        const on = btn.getAttribute('aria-pressed') !== 'true';
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        panel.classList.toggle('comparing', on);
        box.hidden = !on;
        if (on) { set(50); setTimeout(sweep, 350); }
        else requestAnimationFrame(updateIndicators);
    });
    set(50);
}

// ═════════════════════════════════════════════════════════════════
//  主視覺：以粒子描繪逆時針旋轉的氣旋風場（有颱風時顏色與強度跟著最強的那顆）
// ═════════════════════════════════════════════════════════════════
const Hero = (function () {
    const cv = $('#hero-canvas');
    const api = { setActive() {} };
    if (!cv || !cv.getContext) return api;
    const hero = cv.closest('.hero');
    const ctx = cv.getContext('2d');
    const S = Math.max(0, Math.min(1, SITE.hero.strength));
    const RGB = SITE.hero.rgb;
    const V = 0.7 + 2.4 * S;             // 最大切向速度（px/frame）
    const INFLOW = 0.16 + 0.10 * S;      // 向內流入比例，讓流線呈螺旋
    const DRIFT = -0.25;                 // 背景往西的駛流
    let W = 0, H = 0, ex = 0, ey = 0, R = 60, parts = [], raf = 0;
    let onScreen = true, active = false;

    function spawn(p, init) {
        p.x = Math.random() * W; p.y = Math.random() * H;
        p.age = init ? Math.random() * 120 : 0;
        p.life = 90 + Math.random() * 150;
        return p;
    }
    function resize() {
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        W = hero.clientWidth; H = hero.clientHeight;
        if (!W || !H) return;
        cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const narrow = W < 760;
        ex = W * (narrow ? 0.66 : 0.72); ey = H * (narrow ? 0.28 : 0.46);
        R = Math.min(W, H) * (0.05 + 0.05 * S);
        hero.style.setProperty('--ex', ex + 'px');
        hero.style.setProperty('--ey', ey + 'px');
        const n = Math.round(Math.min(1100, W * H / (narrow ? 1500 : 1100)));
        parts = Array.from({ length: n }, () => spawn({}, true));
        ctx.clearRect(0, 0, W, H);
    }
    function vel(x, y) {
        const dx = x - ex, dy = y - ey;
        const r = Math.hypot(dx, dy) + 0.001;
        const vt = r < R ? V * r / R : V * Math.pow(R / r, 0.5);
        // 北半球逆時針：螢幕座標 y 朝下，所以切向量取 (dy, -dx)
        return [vt * dy / r - INFLOW * vt * dx / r + DRIFT, -vt * dx / r - INFLOW * vt * dy / r];
    }
    const BUCKETS = 4;
    const paths = Array.from({ length: BUCKETS }, () => []);
    function step() {
        ctx.globalCompositeOperation = 'destination-out';
        ctx.fillStyle = 'rgba(0,0,0,0.07)';
        ctx.fillRect(0, 0, W, H);
        ctx.globalCompositeOperation = 'lighter';
        for (const b of paths) b.length = 0;
        for (const p of parts) {
            const [vx, vy] = vel(p.x, p.y);
            const nx = p.x + vx, ny = p.y + vy;
            const fade = Math.min(1, p.age / 25, (p.life - p.age) / 25);
            const a = Math.max(0, fade) * Math.min(1, Math.hypot(vx, vy) / (V * 0.8));
            paths[Math.min(BUCKETS - 1, Math.floor(a * BUCKETS))].push(p.x, p.y, nx, ny);
            p.x = nx; p.y = ny; p.age++;
            const r = Math.hypot(p.x - ex, p.y - ey);
            if (p.age > p.life || r < R * 0.4 || p.x < -30 || p.x > W + 30 || p.y < -30 || p.y > H + 30) spawn(p, false);
        }
        ctx.lineWidth = 1.15; ctx.lineCap = 'round';
        for (let b = 0; b < BUCKETS; b++) {
            const seg = paths[b];
            if (!seg.length) continue;
            ctx.strokeStyle = `rgba(${RGB},${(0.06 + 0.5 * (b + 1) / BUCKETS).toFixed(3)})`;
            ctx.beginPath();
            for (let i = 0; i < seg.length; i += 4) { ctx.moveTo(seg[i], seg[i + 1]); ctx.lineTo(seg[i + 2], seg[i + 3]); }
            ctx.stroke();
        }
        ctx.globalCompositeOperation = 'source-over';
    }
    function loop() { raf = 0; step(); schedule(); }
    function schedule() {
        if (!raf && active && onScreen && !document.hidden && !reduced()) raf = requestAnimationFrame(loop);
    }
    function still() { for (let i = 0; i < 140; i++) step(); }   // 減少動態：只畫一張靜態的流線圖
    if ('IntersectionObserver' in window) {
        new IntersectionObserver(es => { onScreen = es[0].isIntersecting; schedule(); }).observe(hero);
    }
    document.addEventListener('visibilitychange', schedule);
    let rsT = 0;
    window.addEventListener('resize', () => {
        clearTimeout(rsT);
        rsT = setTimeout(() => { if (active) { resize(); if (reduced()) still(); } }, 150);
    });
    api.setActive = on => {
        const wasActive = active;
        active = on;
        if (on && !wasActive) { resize(); if (reduced()) still(); }
        schedule();
    };
    return api;
})();

// ═════════════════════════════════════════════════════════════════
//  3D 地球（v4.1，WebGL 背景）
//  點陣陸地＋即時晨昏線、颱風雲系 shader、系集平均預報路徑、繞行的衛星。
//  固定在頁面最底層，跟著捲動換位置／旋轉、跟著滑鼠微微偏轉。
//  Three.js 等頁面載完才從 CDN 載入；載入失敗或不支援 WebGL 就保留 2D 流線主視覺。
// ═════════════════════════════════════════════════════════════════
const Globe = (function () {
    const cv = $('#globe');
    const G = SITE.globe;
    const api = { ready: false, route() {} };
    if (!cv || !G) return api;
    try {
        const c = document.createElement('canvas');
        if (!(c.getContext('webgl2') || c.getContext('webgl'))) return api;
    } catch (e) { return api; }

    const D2R = Math.PI / 180;
    const WPAC = [20, 140];                  // 沒有颱風時看西太平洋
    let route = 'overview', ctl = null;
    api.route = r => { route = r; if (ctl) ctl.kick(); };

    function start() {
        import('https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.min.js')
            .then(THREE => decodeLand(G.land).then(land => {
                ctl = build(THREE, land);
                api.ready = true;
                root.classList.add('has-globe');
                Hero.setActive(false);
                ctl.kick();
            }))
            .catch(err => console.warn('[globe]', err));
    }
    if (document.readyState === 'complete') setTimeout(start, 50);
    else window.addEventListener('load', () => setTimeout(start, 50));

    async function decodeLand(b64) {
        if (!b64 || typeof DecompressionStream === 'undefined') return null;
        try {
            const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
            const out = new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream('deflate')));
            return new Uint8Array(await out.arrayBuffer());
        } catch (e) { return null; }
    }
    function catColor(kt) {
        if (kt == null) return '#ffffff';
        for (const [, lo, hi, col] of SITE.bands) if (kt < hi) return col;
        return SITE.bands[SITE.bands.length - 1][3];
    }
    const clamp01 = v => Math.max(0, Math.min(1, v));
    const ease = v => v < .5 ? 4 * v * v * v : 1 - Math.pow(-2 * v + 2, 3) / 2;
    const mix = (a, b, f) => a + (b - a) * f;

    function build(THREE, land) {
        const geo = (lat, lon, r) => {
            const la = lat * D2R, lo = lon * D2R;
            return new THREE.Vector3(r * Math.cos(la) * Math.sin(lo), r * Math.sin(la), r * Math.cos(la) * Math.cos(lo));
        };
        const narrow = innerWidth < 760;
        const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: !narrow, alpha: true, powerPreference: 'high-performance' });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, narrow ? 1.5 : 1.75));
        renderer.setClearColor(0x000000, 0);
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
        camera.position.set(0, 0, 6);

        // 太陽直射點（赤緯＋時角，忽略均時差）→ 給陸地點與海洋畫晨昏
        const now = new Date();
        const doy = (now - Date.UTC(now.getUTCFullYear(), 0, 0)) / 864e5;
        const decl = -23.44 * Math.cos(2 * Math.PI / 365 * (doy + 10));
        const sunLon = (12 - now.getUTCHours() - now.getUTCMinutes() / 60) * 15;
        const uni = {
            uTime: { value: 0 },
            uSun:  { value: geo(decl, sunLon, 1) },
            uPR:   { value: renderer.getPixelRatio() },
        };

        // 階層：anchor（畫面上的位置、捲動位移）→ tilt（緯度）→ spin（經度）→ 地球本體
        const anchor = new THREE.Group(), tilt = new THREE.Group(), spin = new THREE.Group();
        anchor.add(tilt); tilt.add(spin); scene.add(anchor);

        // 海洋：近黑球體，白天那側帶一點灰，邊緣淡淡的 fresnel
        spin.add(new THREE.Mesh(new THREE.SphereGeometry(0.995, 96, 64), new THREE.ShaderMaterial({
            uniforms: uni,
            vertexShader: `varying vec3 vG; varying vec3 vN; varying vec3 vV;
                void main(){ vG = normal; vN = normalize(normalMatrix * normal);
                vec4 mv = modelViewMatrix * vec4(position, 1.); vV = normalize(-mv.xyz);
                gl_Position = projectionMatrix * mv; }`,
            fragmentShader: `uniform vec3 uSun; varying vec3 vG; varying vec3 vN; varying vec3 vV;
                void main(){ float day = smoothstep(-.2, .35, dot(normalize(vG), uSun));
                float rim = pow(1. - max(dot(vN, vV), 0.), 3.);
                vec3 c = mix(vec3(.006, .007, .01), vec3(.04, .045, .055), day) + rim * vec3(.05, .06, .085);
                gl_FragColor = vec4(c, 1.); }`,
        })));

        // 陸地：費氏球面均勻撒點，落在陸地遮罩上的才留；夜側壓暗、背光面淡出
        if (land) {
            const N = narrow ? 42000 : 80000, GA = Math.PI * (3 - Math.sqrt(5));
            const pos = [], rnd = [];
            for (let i = 0; i < N; i++) {
                const y = 1 - (i + .5) / N * 2, r = Math.sqrt(1 - y * y), th = GA * i;
                const x = r * Math.cos(th), z = r * Math.sin(th);
                const lat = Math.asin(y) / D2R, lon = Math.atan2(x, z) / D2R;
                const k = Math.min(359, Math.floor((90 - lat) * 2)) * 720 + Math.min(719, Math.floor((lon + 180) * 2));
                if (!(land[k >> 3] & (128 >> (k & 7)))) continue;
                pos.push(x * 1.001, y * 1.001, z * 1.001); rnd.push(Math.random());
            }
            const g = new THREE.BufferGeometry();
            g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
            g.setAttribute('aRand', new THREE.Float32BufferAttribute(rnd, 1));
            spin.add(new THREE.Points(g, new THREE.ShaderMaterial({
                uniforms: Object.assign({ uSize: { value: narrow ? 1.9 : 1.6 } }, uni),
                vertexShader: `uniform float uSize, uPR; uniform vec3 uSun; attribute float aRand; varying float vA;
                    void main(){ vec3 n = normalize(position);
                    vec4 mv = modelViewMatrix * vec4(position, 1.);
                    float facing = dot(normalize(normalMatrix * n), normalize(-mv.xyz));
                    float day = smoothstep(-.15, .3, dot(n, uSun));
                    vA = smoothstep(0., .35, facing) * mix(.3, 1., day) * (.65 + .35 * aRand);
                    gl_PointSize = uSize * uPR * (6. / -mv.z);
                    gl_Position = projectionMatrix * mv; }`,
                fragmentShader: `varying float vA;
                    void main(){ vec2 c = gl_PointCoord - .5; if (dot(c, c) > .25) discard;
                    gl_FragColor = vec4(vec3(1.), vA * .9); }`,
                transparent: true, depthWrite: false,
            })));
        }

        // 經緯網格：30° 一條，極淡
        const grat = [];
        const seg = (a, b) => grat.push(a.x, a.y, a.z, b.x, b.y, b.z);
        for (let la = -60; la <= 60; la += 30) for (let lo = -180; lo < 180; lo += 3) seg(geo(la, lo, 1.002), geo(la, lo + 3, 1.002));
        for (let lo = -180; lo < 180; lo += 30) for (let la = -84; la < 84; la += 3) seg(geo(la, lo, 1.002), geo(la + 3, lo, 1.002));
        const gg = new THREE.BufferGeometry();
        gg.setAttribute('position', new THREE.Float32BufferAttribute(grat, 3));
        spin.add(new THREE.LineSegments(gg, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: .07, depthWrite: false })));

        // 大氣光暈：背面球殼，越靠近地球邊緣越亮
        const atmo = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 48), new THREE.ShaderMaterial({
            vertexShader: `varying vec3 vN; varying vec3 vV;
                void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.);
                vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz);
                gl_Position = projectionMatrix * mv; }`,
            fragmentShader: `varying vec3 vN; varying vec3 vV;
                void main(){ float i = pow(smoothstep(0., .45, -dot(vN, vV)), 3.);
                gl_FragColor = vec4(vec3(.72, .82, 1.) * i * .3, 1.); }`,
            side: THREE.BackSide, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
        }));
        atmo.scale.setScalar(1.1);
        tilt.add(atmo);

        // ── 颱風：螺旋雲帶 shader（北半球逆時針、南半球順時針），強度越強眼越清楚 ──
        const vortexFS = `uniform float uTime, uDir, uStr; uniform vec3 uColor; varying vec2 vUv;
            float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
            float n(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f);
                return mix(mix(h(i), h(i + vec2(1, 0)), f.x), mix(h(i + vec2(0, 1)), h(i + vec2(1, 1)), f.x), f.y); }
            void main(){
                vec2 p = (vUv - .5) * 2.; float r = length(p); if (r > 1.) discard;
                float lr = log(r + .02), spd = .35 + .5 * uStr;
                float a = atan(p.y, p.x) * uDir - uTime * spd;
                float band = pow(.5 + .5 * sin(2. * a + 5.5 * lr), 2.2);
                float th = uDir * (uTime * spd - 2.75 * lr);
                vec2 q = mat2(cos(th), -sin(th), sin(th), cos(th)) * p;
                float tex = .45 + .55 * (n(q * 5.) * .65 + n(q * 11.) * .35);
                float fall = smoothstep(1., .3, r), core = smoothstep(.42, .1, r);
                float eyeOn = smoothstep(.35, .7, uStr);
                float eye = mix(1., smoothstep(.035, .1, r), eyeOn);
                float wall = exp(-pow((r - .12) / .05, 2.)) * eyeOn;
                float d = (band * .8 * fall * tex + core * .85 * tex + wall * .6) * eye;
                vec3 col = mix(uColor, vec3(1.), smoothstep(.25, .9, d));
                gl_FragColor = vec4(col, clamp(d, 0., 1.) * .92);
            }`;
        const plainVS = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`;
        const dotVS = `uniform float uPR, uProg; attribute vec3 aCol; attribute float aT; varying vec3 vC; varying float vA;
            void main(){ vC = aCol; vA = step(aT, uProg); gl_PointSize = 5. * uPR;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`;
        const dotFS = `varying vec3 vC; varying float vA;
            void main(){ vec2 c = gl_PointCoord - .5; if (dot(c, c) > .25 || vA < .5) discard; gl_FragColor = vec4(vC, 1.); }`;

        const LAB_W = .52, LAB_H = .13;
        function labelText(s) {
            const name = String(s.name || s.id).toUpperCase();
            const sub = (name === s.id ? '' : s.id) + (s.kt != null ? (name === s.id ? '' : ' · ') + Math.round(s.kt) + ' KT' : '');
            return { name, sub };
        }
        // 標籤實際有字的寬度（佔畫布 512px 的比例），給 placeLabels 估算佔多少經度
        const measureCtx = document.createElement('canvas').getContext('2d');
        function labelFrac(s) {
            const { name, sub } = labelText(s);
            measureCtx.font = '600 60px Inter, sans-serif'; const a = measureCtx.measureText(name).width;
            measureCtx.font = '400 30px Inter, sans-serif'; const b = measureCtx.measureText(sub).width;
            return Math.min(1, (Math.max(a, b) + 34) / 512);
        }
        // 颱風靠得近時名稱會疊在一起：由強到弱依序放，每顆從「右上」開始試幾個候選位置
        // （右下、左上、左下，再往上／下錯開一兩行），挑第一個不壓到已放好的標籤與其他颱風渦旋的位置；
        // 都會壓到就挑重疊面積最小的。以經緯度矩形近似，地球只微轉，夠用。
        function placeLabels(list) {
            const H = LAB_H / D2R;
            const info = list.map(s => {
                const tr = s.track || [];
                const lat = s.lat != null ? s.lat : tr[0][0], lon = s.lon != null ? s.lon : tr[0][1];
                const size = .2 + .16 * clamp01(((s.kt || 30) - 25) / 100);
                const off = size * .45 / D2R, k = 1 / Math.max(.3, Math.cos(lat * D2R));
                return { lat, lon, off, k, w: LAB_W * labelFrac(s) / D2R * k };
            });
            const boxes = info.map(o => [o.lon - o.off * o.k, o.lat - o.off, o.lon + o.off * o.k, o.lat + o.off]);
            const overlap = (a, b) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
            const res = new Array(list.length);
            const order = info.map((_, i) => i).sort((i, j) => (list[j].kt || 0) - (list[i].kt || 0));
            for (const i of order) {
                const o = info[i], cands = [];
                for (const step of [0, 1, 2])
                    for (const [side, vy] of [[1, 1], [1, -1], [-1, 1], [-1, -1]])
                        cands.push({ step, side, dLat: vy * (o.off * .6 + step * H), dLon: side * o.off * o.k });
                let best = null, bestCost = Infinity;
                for (const c of cands) {
                    const x0 = o.lon + c.dLon, y = o.lat + c.dLat;
                    const box = c.side > 0 ? [x0, y - H / 2, x0 + o.w, y + H / 2] : [x0 - o.w, y - H / 2, x0, y + H / 2];
                    let cost = 0;
                    boxes.forEach((b, j) => { if (j !== i) cost += overlap(box, b); });
                    if (cost < bestCost - 1e-9) { best = { ...c, box }; bestCost = cost; }
                    if (cost === 0) break;
                }
                res[i] = best;
                boxes.push(best.box);
            }
            return res;
        }
        function label(s, side = 1) {
            const c = document.createElement('canvas'); c.width = 512; c.height = 128;
            const x = c.getContext('2d');
            const tex = new THREE.CanvasTexture(c);
            tex.colorSpace = THREE.SRGBColorSpace;
            const { name, sub } = labelText(s);
            // 放在颱風左側時整個鏡像：色條在右、文字靠右對齊，貼近颱風那一側
            const draw = () => {
                x.clearRect(0, 0, 512, 128);
                x.textAlign = side > 0 ? 'left' : 'right';
                x.fillStyle = s.color || '#fff'; x.fillRect(side > 0 ? 0 : 507, 16, 5, 96);
                x.fillStyle = '#fff'; x.font = '600 60px Inter, sans-serif'; x.fillText(name, side > 0 ? 22 : 490, 70);
                x.fillStyle = 'rgba(255,255,255,.66)'; x.font = '400 30px Inter, sans-serif'; x.fillText(sub, side > 0 ? 24 : 488, 110);
                tex.needsUpdate = true;
            };
            draw();
            if (document.fonts) document.fonts.load('600 60px Inter').then(draw).catch(() => {});
            // 不做深度測試：標籤是面向鏡頭的平板，颱風靠近地球邊緣時平板會斜插進球面，
            // 下半（ID・風速那行）被球體擋掉；改成永遠畫在最上層，背面時由 frame() 淡出
            const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false }));
            sp.renderOrder = 10;
            sp.center.set(side > 0 ? 0 : 1, .5);
            sp.scale.set(LAB_W, LAB_H, 1);
            return sp;
        }

        const storms = [], byId = {};
        const places = placeLabels(G.storms || []);
        (G.storms || []).forEach((s, idx) => {
            const tr = s.track || [];
            const lat = s.lat != null ? s.lat : tr[0][0], lon = s.lon != null ? s.lon : tr[0][1];
            const str = clamp01(((s.kt || 30) - 25) / 100);
            const col = new THREE.Color(s.color || '#ffffff');
            const out = geo(lat, lon, 2);
            const size = .2 + .16 * str;
            const vortex = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.ShaderMaterial({
                uniforms: Object.assign({ uDir: { value: lat >= 0 ? 1 : -1 }, uStr: { value: str }, uColor: { value: col } }, uni),
                vertexShader: plainVS, fragmentShader: vortexFS, transparent: true, depthWrite: false,
            }));
            vortex.position.copy(geo(lat, lon, 1.006)); vortex.lookAt(out);
            spin.add(vortex);
            // 擴散的強度色圓圈，像雷達掃到的回波
            const ring = new THREE.Mesh(new THREE.RingGeometry(.47, .5, 64), new THREE.MeshBasicMaterial({
                color: col, transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide }));
            ring.position.copy(geo(lat, lon, 1.004)); ring.lookAt(out);
            spin.add(ring);
            // 名稱標籤（跟頁面一樣用 Inter）
            const pl = places[idx];
            const lab = label(s, pl.side);
            lab.position.copy(geo(lat + pl.dLat, lon + pl.dLon, 1.03));
            spin.add(lab);
            // 標籤被擠離颱風一兩行時，拉一條細引線，才看得出是哪一顆的
            if (pl.step > 0) spin.add(new THREE.Line(
                new THREE.BufferGeometry().setFromPoints([geo(lat, lon, 1.012), lab.position.clone()]),
                new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: .55, depthWrite: false })));

            // 預報路徑：點與點之間走大圓，依強度上色；每 24 小時一個點
            let line = null, dots = null, total = 0;
            if (tr.length > 1) {
                const P = [], C = [], DP = [], DC = [], DT = [], tc = new THREE.Color();
                const put = (v, kt) => { P.push(v.x, v.y, v.z); tc.set(catColor(kt)); C.push(tc.r, tc.g, tc.b); };
                for (let k = 0; k < tr.length - 1; k++) {
                    const a = geo(tr[k][0], tr[k][1], 1), b = geo(tr[k + 1][0], tr[k + 1][1], 1);
                    const ang = a.angleTo(b), steps = Math.max(2, Math.ceil(ang / .01));
                    for (let j = 0; j < steps; j++) {
                        const f = j / steps, kt = tr[k][2] == null ? null : mix(tr[k][2], tr[k + 1][2] ?? tr[k][2], f);
                        const v = ang < 1e-4 ? a.clone() : a.clone().multiplyScalar(Math.sin((1 - f) * ang))
                            .addScaledVector(b, Math.sin(f * ang)).divideScalar(Math.sin(ang));
                        put(v.multiplyScalar(1.004), kt);
                    }
                    if (tr[k][3] != null ? tr[k][3] % 24 === 0 : k % 4 === 0) { const v = a.multiplyScalar(1.005); DP.push(v.x, v.y, v.z); tc.set(catColor(tr[k][2])); DC.push(tc.r, tc.g, tc.b); DT.push(k / (tr.length - 1)); }
                }
                const last = tr[tr.length - 1];
                put(geo(last[0], last[1], 1.004), last[2]);
                total = P.length / 3;
                const lg = new THREE.BufferGeometry();
                lg.setAttribute('position', new THREE.Float32BufferAttribute(P, 3));
                lg.setAttribute('color', new THREE.Float32BufferAttribute(C, 3));
                line = new THREE.Line(lg, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: .95, depthWrite: false }));
                spin.add(line);
                const dg = new THREE.BufferGeometry();
                dg.setAttribute('position', new THREE.Float32BufferAttribute(DP, 3));
                dg.setAttribute('aCol', new THREE.Float32BufferAttribute(DC, 3));
                dg.setAttribute('aT', new THREE.Float32BufferAttribute(DT, 1));
                dots = new THREE.Points(dg, new THREE.ShaderMaterial({
                    uniforms: { uPR: uni.uPR, uProg: { value: 0 } }, vertexShader: dotVS, fragmentShader: dotFS, transparent: true }));
                spin.add(dots);
            }
            const S = { id: s.id, lat, lon, size, ring, line, dots, total, lab, phase: idx * .37 };
            storms.push(S); byId[s.id] = S;
        });


        // ── 衛星：太陽同步極軌道氣象衛星（參考 NOAA-20／JPSS：高度約 824 km、傾角 98.7°、
        //    升交點地方時 13:30）。軌道固定在地球座標上、依即時太陽位置擺放，白天那側往北飛；
        //    姿態對地（碟形天線朝地心、機身順著飛行方向），太陽能板繞俯仰軸追太陽，
        //    光照來自真實太陽方向，進入地影就變暗。實際週期約 101 分鐘，動畫快轉 100 倍。
        //    （衛星本體放大很多才看得到；地球在這裡不自轉，所以星下點軌跡不會逐圈西移） ──
        const metal = new THREE.MeshStandardMaterial({ color: 0xd9d9d9, metalness: .7, roughness: .3 });
        const panelM = new THREE.MeshStandardMaterial({ color: 0x1c2b4a, metalness: .4, roughness: .45, emissive: 0x05080f });
        const sat = new THREE.Group(), wings = [];
        sat.add(new THREE.Mesh(new THREE.BoxGeometry(.045, .045, .07), metal));
        for (const sx of [-1, 1]) {
            const w = new THREE.Group();
            const pn = new THREE.Mesh(new THREE.BoxGeometry(.16, .003, .05), panelM); pn.position.x = sx * .115; w.add(pn);
            sat.add(w); wings.push(w);
            const arm = new THREE.Mesh(new THREE.CylinderGeometry(.003, .003, .04, 6), metal);
            arm.rotation.z = Math.PI / 2; arm.position.x = sx * .03; sat.add(arm);
        }
        const dish = new THREE.Mesh(new THREE.ConeGeometry(.022, .018, 20, 1, true), metal);
        dish.rotation.x = -Math.PI / 2; dish.position.z = .045; sat.add(dish);
        sat.scale.setScalar(.75);
        const ORBIT_R = 1 + 824 / 6371, INC = 98.7 * D2R;
        const SAT_W = 2 * Math.PI / (101.4 * 60) * 100;          // 角速度（rad/s，已快轉 100 倍）
        // 軌道座標：x＝升交點方向、z＝升交點後 90°（往北、略偏西）、y＝z×x
        const nodeLon = sunLon + (13.5 - 12) * 15;
        const N = geo(0, nodeLon, 1), E = geo(0, nodeLon + 90, 1);
        const M = E.clone().multiplyScalar(Math.cos(INC)).add(new THREE.Vector3(0, Math.sin(INC), 0));
        const orbit = new THREE.Group();
        orbit.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(N, M.clone().cross(N), M));
        orbit.add(sat);
        const og = new THREE.BufferGeometry().setFromPoints(
            Array.from({ length: 181 }, (_, i) => new THREE.Vector3(ORBIT_R * Math.cos(i / 90 * Math.PI), 0, ORBIT_R * Math.sin(i / 90 * Math.PI))));
        orbit.add(new THREE.Line(og, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: .08, depthWrite: false })));
        spin.add(orbit);
        const sunOrb = uni.uSun.value.clone().applyQuaternion(orbit.quaternion.clone().invert());
        const labW = new THREE.Vector3(), labC = new THREE.Vector3(), labN = new THREE.Vector3(), labV = new THREE.Vector3();
        const satBasis = new THREE.Matrix4(), bX = new THREE.Vector3(0, 1, 0), bY = new THREE.Vector3(), bZ = new THREE.Vector3();
        const sunW = new THREE.Vector3(), spinQ = new THREE.Quaternion();
        scene.add(new THREE.AmbientLight(0xffffff, .35));
        const light = new THREE.DirectionalLight(0xffffff, 2.2);
        scene.add(light);

        // ── 背景星點 ──
        const sp = [];
        for (let i = 0; i < 1400; i++) {
            const v = new THREE.Vector3().randomDirection().multiplyScalar(18 + Math.random() * 22);
            sp.push(v.x, v.y, v.z);
        }
        const sg = new THREE.BufferGeometry();
        sg.setAttribute('position', new THREE.Float32BufferAttribute(sp, 3));
        const sky = new THREE.Points(sg, new THREE.PointsMaterial({ color: 0xffffff, size: 1.3, sizeAttenuation: false, transparent: true, opacity: .45, depthWrite: false }));
        scene.add(sky);

        // ── 狀態：cur 每格往 tgt 靠（像 GSAP 的 scrub），一開場從遠處轉進來 ──
        const cur = { x: 0, y: 0, z: -7, lat: 0, lon: 0, extra: -1.8, tiltX: 0, op: 0 };
        let mx = 0, my = 0, pmx = 0, pmy = 0, raf = 0, last = 0, t0 = 0, prog = reduced() ? 1 : 0, first = true;
        window.addEventListener('pointermove', e => { mx = e.clientX / innerWidth - .5; my = e.clientY / innerHeight - .5; }, { passive: true });

        function focusOf() {
            const s = route.startsWith('storm/') ? byId[route.slice(6)] : (route === 'overview' && G.focus ? byId[G.focus] : null);
            return s ? [s.lat, s.lon] : WPAC;
        }
        // 總覽 hero 文字（標題、颱風清單、說明、按鈕…）實際的右緣（px）；量的是內容，不是撐滿整欄的區塊。
        // 只在視窗大小或語言改變時重量
        let textRKey = '', textRVal = 0;
        function heroTextRight(W, H) {
            const key = `${W}x${H}:${currentLang}`;
            if (key === textRKey) return textRVal;
            const inner = $('.view[data-view="overview"] .hero-inner');
            let r = 0;
            if (inner && inner.offsetParent) {
                const rg = document.createRange();
                for (const c of inner.children) { rg.selectNodeContents(c); r = Math.max(r, rg.getBoundingClientRect().right); }
            }
            textRKey = inner && inner.offsetParent ? key : '';
            return (textRVal = r);
        }

        function targets(W, H) {
            const asp = W / H, portrait = asp < .8;
            const hv = portrait ? 1 / (.78 * asp) : asp < 1.2 ? 1.9 : 1.6;   // 可視半高（世界單位）＝決定地球多大
            const camZ = hv / Math.tan(17.5 * D2R);
            const hw = hv * asp;
            const dark = root.getAttribute('data-theme') !== 'light';
            const docH = document.documentElement.scrollHeight - H;
            const [fl, fo] = focusOf();
            const T = { camZ, lat: fl, lon: fo, extra: -.25, tiltX: 0, clip: 'none' };
            if (route === 'overview') {
                const hero = $('.view.active .hero');
                const hr = hero ? hero.getBoundingClientRect() : { top: 0, bottom: H, left: 0, right: W, height: H };
                const hp = reduced() ? 0 : clamp01(scrollY / Math.max(1, hr.height));
                const pp = reduced() ? 0 : clamp01((scrollY - hr.height) / Math.max(1, docH - hr.height));
                // 直式平板：起始位置置中在封面（未捲動時）看得到的範圍內，扣掉頁首與底部導覽列
                let y0 = .18;
                if (portrait && W >= 600) {
                    const bn = $('.bottom-nav'), nb = bn ? bn.offsetHeight : 0;
                    const top = Math.max(hr.top + scrollY, 0), bot = Math.min(hr.bottom + scrollY, H - nb);
                    if (bot > top) y0 = 1 - (top + bot) / H + .08;     // 置中後再略往上一點
                }
                let K;
                if (portrait) K = [[0, y0, 0], [.42, .12, -2], [-.4, -.2, -3]];   // 手機直式：地球起始位置往下移一點
                else {
                    // 橫式：起始位置在右側約 71% 處、略低於畫面中央（hero 在浮動頁首下方）。
                    // 中等寬度的橫式螢幕（1024×768 之類）會壓到左邊的文字：往右移並縮小，右側最多切掉約 15%
                    //（再多，颱風標籤就會被畫面右緣切掉）
                    const ppu = H / 2 / hv, R = 1.1 * ppu, gap = 28;   // 每單位多少 px；R＝含光暈的半徑
                    const textR = heroTextRight(W, H);
                    let sc = 1, cx = W * .71;
                    if (cx - R < textR + gap) {
                        sc = Math.max(.6, Math.min(1, (W - textR - gap) / (1.7 * R)));
                        cx = textR + gap + R * sc;
                    }
                    K = [[(cx - W / 2) / (ppu * sc) / hw, -.12 / sc, camZ * (1 - 1 / sc)], [-.5, -.12, -1.5], [.55, .25, -3]];
                }
                const e1 = ease(hp), e2 = ease(pp);
                T.x = mix(mix(K[0][0], K[1][0], e1), K[2][0], e2) * hw;
                T.y = mix(mix(K[0][1], K[1][1], e1), K[2][1], e2) * hv;
                T.z = mix(mix(K[0][2], K[1][2], e1), K[2][2], e2);
                T.extra += .2 * e1 + .2 * e2;     // 捲動只微轉（合計約 23°），西北太平洋始終朝前
                T.tiltX = .25 * e2;
                const dim = (portrait && W < 600) ? .62 : 1;   // 手機直式：地球疊在封面文字底下，淡一些才讀得清
                if (dark) T.op = dim * (1 - .3 * e1 - .12 * e2);
                else {
                    // 淺色主題：只畫在深色的 hero 卡片裡（連圓角一起裁），捲出去就淡掉
                    T.op = dim * (1 - hp);
                    const rad = hero ? parseFloat(getComputedStyle(hero).borderTopLeftRadius) || 0 : 0;
                    T.clip = `inset(${hr.top.toFixed(0)}px ${Math.max(0, W - hr.right).toFixed(0)}px ${(H - hr.bottom).toFixed(0)}px ${Math.max(0, hr.left).toFixed(0)}px round ${rad}px)`;
                }
            } else {
                const p = reduced() ? 0 : clamp01(scrollY / Math.max(1, docH));
                T.x = .5 * hw; T.y = .08 * hv; T.z = -1.3;
                T.extra += .3 * p;
                T.op = dark ? (route.startsWith('storm/') ? .3 : .22) : 0;
            }
            return T;
        }

        function frame(ts) {
            raf = 0;
            const dt = Math.min(.05, last ? (ts - last) / 1000 : .016);
            last = ts;
            if (!t0) t0 = ts;
            const t = (ts - t0) / 1000;
            const W = cv.clientWidth, H = cv.clientHeight;
            if (!W || !H) return;
            const sz = renderer.getSize(new THREE.Vector2());
            if (sz.x !== W || sz.y !== H) { renderer.setSize(W, H, false); camera.aspect = W / H; camera.updateProjectionMatrix(); }

            const T = targets(W, H);
            const k = reduced() || (first && route !== 'overview') ? 1 : 1 - Math.pow(.02, dt * 1.6);
            first = false;
            camera.position.z = T.camZ;
            pmx += (mx - pmx) * Math.min(1, dt * 3); pmy += (my - pmy) * Math.min(1, dt * 3);
            cur.x += (T.x - cur.x) * k; cur.y += (T.y - cur.y) * k; cur.z += (T.z - cur.z) * k;
            cur.lat += (T.lat - cur.lat) * k;
            cur.lon += ((((T.lon - cur.lon) % 360) + 540) % 360 - 180) * k;     // 走最短的經度差，跨換日線不會繞一圈
            cur.extra += (T.extra - cur.extra) * k;
            cur.tiltX += (T.tiltX - cur.tiltX) * k;
            cur.op += (T.op - cur.op) * (reduced() ? 1 : Math.min(1, dt * 2.5));

            const idle = reduced() ? 0 : Math.sin(t * .15) * .06;
            anchor.position.set(cur.x + pmx * .08, cur.y - pmy * .06, cur.z);
            spin.rotation.y = -cur.lon * D2R + cur.extra + idle + pmx * .22;
            tilt.rotation.x = cur.lat * D2R * .9 + cur.tiltX + pmy * .12;
            sky.rotation.y = cur.extra * .08 + pmx * .03;
            sky.rotation.x = scrollY * .00004 + pmy * .02;

            const at = reduced() ? 0 : t;
            uni.uTime.value = at;
            if (!reduced() && t > .8) prog = Math.min(1, prog + dt / 2.6);
            for (const S of storms) {
                const ph = reduced() ? .35 : (at * .45 + S.phase) % 1;
                S.ring.scale.setScalar(S.size * (.5 + ph * 1.3));
                S.ring.material.opacity = (1 - ph) * .7;
                if (S.line) { S.line.geometry.setDrawRange(0, Math.ceil(S.total * ease(prog))); S.dots.material.uniforms.uProg.value = ease(prog); }
                // 標籤不吃深度了，轉到地球背面時要自己藏起來：看標籤錨點的球面法線朝不朝鏡頭
                S.lab.getWorldPosition(labW); anchor.getWorldPosition(labC);
                labN.subVectors(labW, labC).normalize();
                const facing = labN.dot(labV.subVectors(camera.position, labW).normalize());
                S.lab.material.opacity = Math.min(1, Math.max(0, (facing - .02) / .15));
            }
            const th = orbit.userData.a = (orbit.userData.a || 0) + (reduced() ? 0 : dt * SAT_W);
            const c = Math.cos(th), s = Math.sin(th);
            sat.position.set(ORBIT_R * c, 0, ORBIT_R * s);
            // 機身：z 朝地心、x 沿軌道法向（太陽能板伸展方向）、-y 為飛行方向
            bY.set(s, 0, -c); bZ.set(-c, 0, -s);
            sat.quaternion.setFromRotationMatrix(satBasis.makeBasis(bX, bY, bZ));
            const pitch = Math.atan2(sunOrb.dot(bZ), sunOrb.dot(bY));
            for (const w of wings) w.rotation.x = pitch;
            // 太陽光方向跟著地球轉；衛星在地球背日面的圓柱陰影內就只剩環境光
            spin.getWorldQuaternion(spinQ);
            light.position.copy(sunW.copy(uni.uSun.value).applyQuaternion(spinQ)).multiplyScalar(5);
            const along = -ORBIT_R * (sunOrb.x * c + sunOrb.z * s);   // 衛星位置在「背日」方向的投影
            const perp = Math.sqrt(Math.max(0, ORBIT_R * ORBIT_R - along * along));
            light.intensity = 2.2 * (along > 0 ? THREE.MathUtils.smoothstep(perp, .96, 1.04) : 1);

            cv.style.opacity = cur.op.toFixed(3);
            cv.style.clipPath = T.clip;
            if (cur.op > .004) renderer.render(scene, camera);
            // 減少動態或淡到看不見、分頁在背景時就不跑迴圈，改成事件驅動
            const settled = Math.abs(T.op - cur.op) < .003 && Math.abs(T.x - cur.x) < .002 && Math.abs(T.z - cur.z) < .002;
            if (!document.hidden && !(reduced() && settled) && !(T.op === 0 && settled)) raf = requestAnimationFrame(frame);
        }
        const kick = () => { if (!raf && !document.hidden) raf = requestAnimationFrame(frame); };
        window.addEventListener('scroll', kick, { passive: true });
        window.addEventListener('resize', kick);
        window.addEventListener('pointermove', kick, { passive: true });
        document.addEventListener('visibilitychange', () => { last = 0; kick(); });
        new MutationObserver(kick).observe(root, { attributes: true, attributeFilter: ['data-theme'] });
        return { kick };
    }
    return api;
})();

// ═════════════════════════════════════════════════════════════════
//  更新時間：相對時間、倒數下一次自動重新整理、資料過時提示
// ═════════════════════════════════════════════════════════════════
const UPDATED = new Date(SITE.updatedIso);
// 每 10 分鐘（HH:05、HH:15…HH:55）自動重新整理，與雲端每 10 分鐘一輪的更新對齊
const REFRESH_MIN = 10;
function nextRefresh(now) {
    const next = new Date(now);
    const m = now.getMinutes();
    const slot = Math.floor((m - 5) / REFRESH_MIN) * REFRESH_MIN + 5 + REFRESH_MIN;   // 下一個 HH:x5
    next.setMinutes(slot, 0, 0);    // slot 超過 59 時 Date 會自動進位到下一小時
    return next;
}
let REFRESH_AT = nextRefresh(new Date());
let REFRESH_SPAN = REFRESH_AT - Date.now();
function fmtRemain(ms) {
    const s = Math.max(0, Math.round(ms / 1000));
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}
function tickClock() {
    const now = new Date();
    const remain = REFRESH_AT - now;
    const clk = $('#hero-clock');
    if (clk) clk.textContent = [now.getHours(), now.getMinutes(), now.getSeconds()].map(v => String(v).padStart(2, '0')).join(':');
    const ring = $('.ring-fg');
    if (ring) ring.style.strokeDashoffset = (100 - Math.max(0, Math.min(1, remain / Math.max(1, REFRESH_SPAN))) * 100).toFixed(2);
    const mins = Math.floor((now - UPDATED) / 60000);
    const rel = isNaN(mins) ? '' : mins < 1 ? t('rel.now') : mins < 60 ? t('rel.min', { n: mins }) : t('rel.hr', { n: Math.floor(mins / 60) });
    const badge = $('#update-badge');
    if (badge) {
        const stale = mins > 40;      // 10 分鐘一輪，有新資料時一輪約 15 分鐘，40 分鐘沒更新就算過時
        badge.classList.toggle('stale', stale);
        badge.title = t('header.updated') + ': ' + (fmtTz(SITE.updatedIso, 'full') || badge.dataset.full) + ' · ' +
            (stale ? t('status.stale', { t: rel }) : t('status.next', { t: fmtRemain(remain) }));
    }
}
// 到點先抓 status.json（百來個位元組），資料時間變了才整頁重新整理；沒變就 2 分鐘後再看。
// 抓不到（離線、file://）連續兩次就退回原本的做法：到點直接重新整理。
let statusFails = 0, checking = false;
function reloadPage() {
    try { sessionStorage.setItem('scroll:' + location.hash, String(scrollY)); } catch (e) {}
    location.reload();
}
async function checkUpdate() {
    if (checking) return;
    checking = true;
    try {
        const r = await fetch('status.json?_=' + Date.now(), { cache: 'no-store' });
        if (!r.ok) throw new Error(r.status);
        const j = await r.json();
        statusFails = 0;
        if (j.updated && j.updated !== SITE.updatedIso) { reloadPage(); return; }
        REFRESH_AT = new Date(Date.now() + 2 * 60000);
    } catch (e) {
        statusFails++;
        if (statusFails >= 2 && location.protocol.startsWith('http')) { reloadPage(); return; }
        REFRESH_AT = nextRefresh(new Date());
    } finally {
        checking = false;
    }
    REFRESH_SPAN = REFRESH_AT - Date.now();
    scheduleCheck();
}
function scheduleCheck() {
    setTimeout(() => {
        if (document.hidden) { REFRESH_AT = new Date(Date.now() + 60000); scheduleCheck(); return; }   // 背景分頁不抓，回前景時再看
        checkUpdate();
    }, Math.max(1000, REFRESH_AT - Date.now()));
}
scheduleCheck();
document.addEventListener('visibilitychange', () => {
    if (!document.hidden && Date.now() - UPDATED > 12 * 60000) checkUpdate();   // 回到前景：上次資料超過一輪就立刻看一眼
});

// ── Keyboard shortcuts ─────────────────────────────────────────────
document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    // 分頁列（role=tablist）：左右鍵／Home／End 在同一列的分頁間移動並切換（WAI-ARIA tabs 的鍵盤操作）
    const tab = e.target.closest ? e.target.closest('.model-tab-btn[role="tab"]') : null;
    if (tab && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
        const tabs = $$('.model-tab-btn', tab.parentElement);
        let i = tabs.indexOf(tab);
        if (e.key === 'ArrowLeft') i = (i - 1 + tabs.length) % tabs.length;
        else if (e.key === 'ArrowRight') i = (i + 1) % tabs.length;
        else i = e.key === 'Home' ? 0 : tabs.length - 1;
        e.preventDefault();
        tabs[i].focus();
        tabs[i].click();
        return;
    }
    if (lightbox.classList.contains('open')) {
        if (e.key === 'Escape') { closeLightbox(); e.preventDefault(); }
        return;
    }
    if (/^[1-9]$/.test(e.key)) {
        const r = ROUTES[parseInt(e.key, 10) - 1];
        if (r) { location.hash = '#/' + r; e.preventDefault(); }
        return;
    }
    const P = visiblePlayer();
    if (!P) return;
    if (e.code === 'Space') { e.preventDefault(); P.touched = true; P.playing ? pause(P) : play(P); }
    if (e.code === 'ArrowRight') { e.preventDefault(); P.touched = true; seek(P, P.i + 1); }
    if (e.code === 'ArrowLeft')  { e.preventDefault(); P.touched = true; seek(P, P.i - 1); }
});

// ── Init ───────────────────────────────────────────────────────────
$('#theme-btn').addEventListener('click', toggleTheme);
$('#lang-btn').addEventListener('click', switchLang);
$('#tz-btn').addEventListener('click', () => applyTz(tzMode === 'tw' ? 'utc' : 'tw'));

$$('.gauge').forEach(buildGauge);
if (!reduced()) $$('[data-count]').forEach(el => { if (!el.closest('.gauge')) el.textContent = '0'; });
$$('.player').forEach(initPlayer);
initStormTabs();
initCompare();
staggerReveals();
applyLang(currentLang, false);
show(parseHash(), true);
if (revealIO) $$('.reveal').forEach(el => revealIO.observe(el));
else $$('.reveal').forEach(el => { el.classList.add('in'); onReveal(el); });
tickClock();
setInterval(tickClock, 1000);

// 自動重新整理後回到原本的捲動位置
window.addEventListener('load', () => {
    try {
        const k = 'scroll:' + location.hash, y = sessionStorage.getItem(k);
        if (y !== null) { sessionStorage.removeItem(k); window.scrollTo({ top: +y, behavior: 'instant' }); }
    } catch (e) {}
    updateIndicators();
});
})();
"""


if __name__ == "__main__":
    # 單獨執行時：以 forecast.py 偵測到的第一顆颱風快速重建 index.html（測試用）
    from forecast import TARGET_TRACK_IDS, OUTPUT_DIR
    html_output_path = os.path.join(OUTPUT_DIR, "index.html")
    if not TARGET_TRACK_IDS:
        print("[INFO] 目前無活動颱風，生成空白網站")
        generate_forecast_html([], html_output_path)
    else:
        track_id = TARGET_TRACK_IDS[0]
        forecast_map_path = os.path.join(OUTPUT_DIR, f"{track_id}_Forecast_Map.png")
        if os.path.exists(forecast_map_path):
            storms = [{'track_id': track_id, 'forecast_map_path': forecast_map_path, 'current_info': {}}]
            generate_forecast_html(storms, html_output_path)
            print(f"[SUCCESS] 請開啟: {html_output_path}")
        else:
            print(f"[ERROR] 找不到預報地圖：{forecast_map_path}")
