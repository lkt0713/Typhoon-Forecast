import os
import json
import html
import pandas as pd  # type: ignore
from datetime import datetime

# 網站版號，顯示在頁首語言切換鈕右邊。改版時只動這裡 —— HTML 由 f-string 取值。
SITE_VERSION = "4.0.0"

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
    ('TD', 0, 34), ('TS', 34, 64), ('Cat1', 64, 83), ('Cat2', 83, 96),
    ('Cat3', 96, 113), ('Cat4', 113, 137), ('Cat5', 137, 170),
]
SCALE_MAX_KT = 170

# 總覽頁「預報模式」一欄的清單（顯示順序即此順序）
KNOWN_MODELS = [
    ('WNC3', 'Google DeepMind', 'WeatherNext · Ensemble'),
    ('WNC2-r2', 'Google DeepMind', 'WeatherNext · Ensemble'),
    ('WNC2-r1', 'Google DeepMind', 'WeatherNext · Ensemble'),
    ('GENC', 'Google DeepMind', 'WeatherNext · Ensemble'),
    ('AIFS', 'ECMWF', 'AIFS-ENS + AIFS-single'),
    ('ECMWF', 'ECMWF', 'IFS ENS + HRES'),
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
    if kt < 34: return 'TD'
    elif kt < 64: return 'TS'
    elif kt < 83: return 'Cat1'
    elif kt < 96: return 'Cat2'
    elif kt < 113: return 'Cat3'
    elif kt < 137: return 'Cat4'
    else: return 'Cat5'


# ECMWF／AIFS 來自 ECMWF Open Data（CC-BY，授權與 WeatherNext 不同），
# 其餘模式來自 Weather Lab；圖說的來源字串不能寫死成 DeepMind。
ECMWF_MODELS = {'ECMWF', 'AIFS'}


def _genesis_source(model_label: str) -> str:
    if model_label in ECMWF_MODELS:
        return 'ECMWF Open Data'
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


def _fmt_obs_time(raw: str) -> str:
    """JTWC 的 'DDHHMM Z' → 'DD / HH:MM UTC'；格式不符就原樣回傳。"""
    s = str(raw).replace('Z', '').strip()
    if len(s) == 6 and s.isdigit():
        return f"{s[:2]} / {s[2:4]}:{s[4:]} UTC"
    return str(raw)


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
        f'<button class="model-tab-btn{" active" if i == 0 else ""}" role="tab" '
        f'data-track="{_esc(track)}" data-model="{_esc(lbl)}">{_esc(lbl)}</button>'
        for i, lbl in enumerate(labels))
    return f'<div class="seg model-tabs {extra_cls}" role="tablist"><span class="seg-ind"></span>{buttons}</div>'


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
    'play': '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M8 5.5v13a1 1 0 0 0 1.5.86l10.2-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>',
    'pause': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect fill="currentColor" x="6.5" y="5" width="4" height="14" rx="1.2"/><rect fill="currentColor" x="13.5" y="5" width="4" height="14" rx="1.2"/></svg>',
    'prev': f'<svg {_ICON_ATTR}><path d="M15 6l-6 6 6 6"/></svg>',
    'next': f'<svg {_ICON_ATTR}><path d="M9 6l6 6-6 6"/></svg>',
    'compare': f'<svg {_ICON_ATTR}><path d="M12 3v18M7 8l-4 4 4 4M17 8l4 4-4 4"/></svg>',
}


def _marquee(items: list[tuple], reverse: bool = False) -> str:
    """跑馬燈大字列：items 為 (文字, 是否描邊, 顏色或 None)。內容重複兩次，
    CSS 平移 -50% 即可無縫循環；太短時先補到至少 6 個字塊，寬螢幕才不會露出空白。"""
    seq = list(items)
    while items and len(seq) < 6:
        seq += items
    spans = []
    for text, outline, color in seq:
        style = f' style="--c:{color}"' if color else ''
        spans.append(f'<span class="mq{" o" if outline else ""}"{style}>{_esc(text)}</span>')
    run = "".join(spans)
    return f'<div class="strip{" reverse" if reverse else ""}">{run}{run}</div>'


def generate_forecast_html(storms: list[dict], output_path: str,
                           genesis_map_paths: list | None = None):
    """生成預報網站（多頁式：總覽／各颱風／生成潛勢／說明，以 hash 路由切換）。

    同一顆颱風若同時有 WNC3 / WNC2-r2 / WNC2-r1 / GENC 多種模式的預報，會合併成
    單一颱風頁：颱風字卡與 JTWC 官方預報圖僅顯示一次，Ensemble 路徑圖與動畫則
    透過分頁切換，避免同一顆颱風重複出現多張幾乎相同的卡片。

    genesis_map_paths 收 (模式名稱, 圖檔路徑) 的序列；為相容舊呼叫方式，也接受
    純路徑字串，此時退回以檔名判斷模式。
    """

    now_local = datetime.now().astimezone()
    update_time = now_local.strftime('%Y-%m-%d %H:%M:%S')

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
            'models': [m.get('model', 'WNC2-r2') for m in models if isinstance(m, dict)],
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
            # 者即現行主力模式 WNC2-r2）
            _gpath = _entry
            _stem = os.path.basename(str(_gpath)).upper()
            _model_label = next(
                (lbl for key, lbl in (("GENC", "GENC"), ("WNC3", "WNC3"),
                                      ("WNC2-R1", "WNC2-r1"), ("WNC-R1", "WNC2-r1"))
                 if key in _stem),
                "WNC2-r2")
        if not (_gpath and os.path.exists(_gpath)):
            continue
        _genesis_entries.append((_model_label, os.path.basename(_gpath)))

    # 路由順序同時決定導覽列排列與換頁動畫的方向（往右的頁面從右邊滑入）
    routes = ['overview'] + [f'storm/{tid}' for tid in order]
    if _genesis_entries:
        routes.append('genesis')
    routes.append('about')

    active_models = set()
    for info in infos.values():
        active_models.update(info['models'])
    active_models.update(lbl for lbl, _ in _genesis_entries)

    # ═════════════════════════════════════════════════════════════════
    #  總覽頁
    # ═════════════════════════════════════════════════════════════════
    if lead:
        hero_rgb = _hex_rgb(lead['color'], 0.35)
        hero_strength = min(1.0, max(0.15, ((lead['wind'] or 30) - 20) / 120))
        lead_wind = f"{lead['wind']:.0f} kt" if lead['wind'] is not None else "— kt"
        hero_inner = f"""
                <div class="eyebrow"><span class="live-dot"></span><span data-i18n="hero.eyebrow.live">Now tracking</span></div>
                <h2 class="hero-title storm-name split" style="--glow:{lead['color']}">{_esc(_title(lead))}</h2>
                <p class="hero-lead">
                    <span class="cat-pill" style="background:{lead['color']};color:{lead['text']}">{lead['cat']}</span>
                    <span data-i18n="catname.{lead['cat']}">{lead['cat']}</span>
                    <span class="sep">·</span><span class="mono">{lead_wind}</span>
                    <span class="sep">·</span><span class="mono">{_esc(lead['pos'])}</span>
                </p>
                <p class="hero-sub" data-i18n="hero.live.sub" data-i18n-count="{len(infos)}"
                   data-i18n-models="{len(active_models)}">{len(infos)} active system(s) · ensemble guidance from {len(active_models)} models, refreshed every 30 minutes.</p>
                <div class="hero-cta">
                    <a class="btn-primary" href="#/storm/{_esc(lead['id'])}"><span data-i18n="hero.cta.storm">Open forecast</span> <span aria-hidden="true">→</span></a>
                    {'<a class="btn-ghost" href="#/genesis" data-i18n="hero.cta.genesis">Genesis outlook</a>' if _genesis_entries else ''}
                </div>"""
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
                <div class="hero-meta">
                    <div class="hero-chip"><span class="chip-k" data-i18n="hero.now">Current time</span><span class="chip-v mono" id="hero-clock">--:--:--</span></div>
                    <div class="hero-chip"><span class="chip-k" data-i18n="hero.updated">Data updated</span><span class="chip-v mono"><span class="chip-date">{update_time[5:10]}</span> {update_time[11:16]}</span></div>
                    <div class="hero-chip"><span class="chip-k" data-i18n="hero.active">Active systems</span><span class="chip-v mono">{len(infos)}</span></div>
                </div>
            </div>
            <div class="scroll-cue" aria-hidden="true"><span></span></div>
        </div>"""

    # 活躍系統卡片
    if infos:
        tiles = []
        for info in infos.values():
            kt = f"{info['wind']:.0f}" if info['wind'] is not None else ''
            tiles.append(f"""
                <a class="storm-tile reveal tilt" href="#/storm/{_esc(info['id'])}" style="--cat:{info['color']};--cat-text:{info['text']}">
                    <div class="tile-top">
                        <span class="badge-cat" style="background:{info['color']};color:{info['text']}">{info['cat']}</span>
                        <span class="badge-id">{_esc(info['id'])}</span>
                        <span class="badge-live"><span class="live-dot"></span><span data-i18n="badge.live">LIVE</span></span>
                    </div>
                    <div class="tile-body">
                        <div>
                            <div class="tile-name storm-name">{_esc(_title(info))}</div>
                            <div class="tile-catname" data-i18n="catname.{info['cat']}">{info['cat']}</div>
                            <dl class="tile-facts">
                                <div><dt data-i18n="stat.pos">Position</dt><dd class="mono">{_esc(info['pos'])}</dd></div>
                                <div><dt data-i18n="stat.time">Obs time</dt><dd class="mono">{_esc(info['time'])}</dd></div>
                                <div><dt data-i18n="stat.models">Models</dt><dd class="tile-models">{' · '.join(f'<span>{_esc(m)}</span>' for m in info['models'])}</dd></div>
                            </dl>
                        </div>
                        <div class="gauge" data-kt="{kt}" style="--cat:{info['color']}"></div>
                    </div>
                    <span class="tile-cta" data-i18n="tile.open">Open full forecast →</span>
                </a>""")
        active_html = f'<div class="storm-grid">{"".join(tiles)}</div>'
    else:
        active_html = """
            <div class="empty-card reveal">
                <div class="calm-sea" aria-hidden="true"><span></span><span></span><span></span></div>
                <div>
                    <div class="empty-title" data-i18n="empty.title">No Active Systems</div>
                    <p class="empty-desc" data-i18n="empty.desc">Nothing is spinning up right now. This page refreshes automatically every 30 minutes.</p>
                </div>
            </div>"""

    genesis_teaser = ""
    if _genesis_entries:
        chips = "".join(f'<span class="mini-chip">{_esc(lbl)}</span>' for lbl, _ in _genesis_entries)
        genesis_teaser = f"""
            <div class="section-head reveal">
                <div><div class="kicker" data-i18n="sec.genesis.kicker">Outlook</div>
                <h3 data-i18n="sec.genesis">Genesis potential</h3></div>
            </div>
            <a class="genesis-teaser reveal" href="#/genesis">
                <div class="teaser-img"><img src="{_esc(_genesis_entries[0][1])}" alt="" loading="lazy" decoding="async"></div>
                <div class="teaser-body">
                    <p data-i18n="genesis.teaser" data-i18n-n="{len(_genesis_entries)}">Where might the next storm form? Explore ensemble genesis signals from {len(_genesis_entries)} models.</p>
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

    if infos:
        mq_top = []
        for info in infos.values():
            mq_top += [(_title(info), False, info['color']), ('Typhoon Forecast', True, None)]
    else:
        mq_top = [('All Quiet', False, None), ('Western Pacific', True, None)]
    mq_bottom = [(name, i % 2 == 0, None) for i, (name, _, _) in enumerate(KNOWN_MODELS)]
    marquee_html = f"""
        <div class="marquee" aria-hidden="true">
            {_marquee(mq_top)}
            {_marquee(mq_bottom, reverse=True)}
        </div>"""

    statement_html = """
        <div class="statement">
            <p class="words" data-i18n="statement">We track tropical cyclones at the intersection between
            <strong>artificial intelligence</strong> and <strong>physics</strong> — every ensemble member,
            every 30 minutes, side by side with the official forecast.</p>
        </div>"""

    overview_view = f"""
    <section class="view" data-view="overview" data-title-key="nav.overview">
        {hero_html}
        {marquee_html}
        {statement_html}
        <div class="page">
            <div class="section-head reveal">
                <div><div class="kicker" data-i18n="sec.active.kicker">Live</div>
                <h3 data-i18n="sec.active">Active systems</h3></div>
                <span class="count-chip mono">{len(infos)}</span>
            </div>
            {active_html}
            {genesis_teaser}
            <div class="section-head reveal">
                <div><div class="kicker" data-i18n="sec.models.kicker">Sources</div>
                <h3 data-i18n="sec.models">Forecast models</h3></div>
                <span class="legend-inline"><span class="model-state on"></span><span data-i18n="models.on">Output in this run</span></span>
            </div>
            <div class="model-grid">{model_cards}</div>
        </div>
    </section>"""

    # ═════════════════════════════════════════════════════════════════
    #  各颱風頁
    # ═════════════════════════════════════════════════════════════════
    scale_segs = "".join(
        f'<span class="ss-seg" data-cat="{c}" style="flex:{hi - lo};--c:{CAT_COLOR_MAP[c]}"><em>{c}</em></span>'
        for c, lo, hi in CAT_RANGES)

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
            ('stat.wind', '💨', 'Max wind',
             f'<span data-count="{info["wind"]:.0f}">{info["wind"]:.0f}</span><small>kt</small>'
             if info['wind'] is not None else 'N/A'),
        ]
        if info['pressure'] is not None:
            stats.append(('stat.pres', '🧭', 'Min pressure',
                          f'<span data-count="{info["pressure"]:.0f}">{info["pressure"]:.0f}</span><small>hPa</small>'))
        stats_html = "".join(f"""
                <div class="stat reveal">
                    <div class="stat-label"><span aria-hidden="true">{icon}</span> <span data-i18n="{key}">{label}</span></div>
                    <div class="stat-value">{val}</div>
                </div>""" for key, icon, label, val in stats)

        scale_pos = (min(info['wind'], SCALE_MAX_KT) / SCALE_MAX_KT * 100) if info['wind'] is not None else 0
        scale_html = f"""
            <div class="panel scale-panel reveal">
                <div class="scale-head">
                    <span data-i18n="scale.title">Intensity scale (Saffir–Simpson)</span>
                    <span class="mono scale-now">{(kt_txt + ' kt') if kt_txt else 'N/A'}</span>
                </div>
                <div class="ss-scale" data-cur="{info['cat']}" style="--pos:{scale_pos:.2f}%">
                    <div class="ss-bar">{scale_segs}</div>
                    <div class="ss-marker" style="--cat:{info['color']}"><span></span></div>
                </div>
            </div>"""

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
            model_name = m.get('model', 'WNC2-r2')
            storm_frames_dir = m.get('frames_dir', '')
            if not (storm_frames_dir and os.path.exists(storm_frames_dir)):
                continue
            frame_files = sorted([f for f in os.listdir(storm_frames_dir) if f.endswith('.png')])
            if not frame_files:
                continue
            key = f"{track_id}-{model_name}"
            frames_folder_name = os.path.basename(storm_frames_dir)
            hide_attr = '' if i == 0 else ' style="display:none;"'
            n = len(frame_files)
            anim_panels.append(f"""
                <div class="model-panel" data-track="{key_prefix}" data-model="{_esc(model_name)}"{hide_attr}>
                    <div class="player" data-anim-key="{_esc(key)}" data-frames-dir="{_esc(frames_folder_name)}"
                         data-frames='{_esc(json.dumps(frame_files))}'>
                        <figure class="zoomable skel frame-stage" data-caption="{_esc(model_name)} · {_esc(track_id)}">
                            <img class="frame is-front" src="{_esc(frames_folder_name)}/{_esc(frame_files[0])}" alt="{_esc(model_name)} animation frame"
                                 decoding="async" onload="this.parentNode.classList.add('loaded')"
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
                                <input type="range" class="timeline" min="0" max="{n - 1}" value="0" aria-label="Frame">
                            </div>
                            <span class="frame-counter mono">1/{n}</span>
                            <div class="speed-seg" role="group">
                                <button class="speed-btn" data-speed="1">1×</button><button class="speed-btn active" data-speed="2">2×</button><button class="speed-btn" data-speed="4">4×</button><button class="speed-btn" data-speed="8">8×</button>
                            </div>
                        </div>
                    </div>
                </div>""")

        anim_html = ""
        if anim_panels:
            sec_id = f"sec-{key_prefix}-anim"
            sections.append((sec_id, 'sub.anim', 'Animation'))
            first_anim_model = next(
                (m.get('model', 'WNC2-r2') for m in models
                 if m.get('frames_dir') and os.path.exists(m.get('frames_dir'))), model_names[0])
            anim_html = f"""
            <div class="panel reveal" id="{sec_id}">
                <div class="panel-header">
                    <span class="panel-icon">🎬</span>
                    <span data-i18n="panel.anim.generic">Track Evolution Animation</span>
                    <span class="panel-aside kbd-hint" data-i18n="kbd.hint"><kbd>Space</kbd> play/pause &nbsp;<kbd>←</kbd><kbd>→</kbd> seek</span>
                </div>
                {_model_tabs(track_id, model_names) if multi_model else f'<div class="model-label">{_esc(first_anim_model)}</div>'}
                {"".join(anim_panels)}
            </div>"""

        # ── Ensemble 路徑圖（依模式分頁切換）+ JTWC 官方預報（每顆颱風僅一份）
        map_panels = []
        for i, m in enumerate(models):
            model_name = m.get('model', 'WNC2-r2')
            forecast_map_path = m.get('forecast_map_path', '') if isinstance(m, dict) else ''
            map_src = os.path.basename(forecast_map_path) if forecast_map_path else ''
            hide_attr = '' if i == 0 else ' style="display:none;"'
            map_panels.append(f"""
                <div class="model-panel" data-track="{key_prefix}" data-model="{_esc(model_name)}"{hide_attr}>
                    {_figure(map_src, f"{track_id} {model_name} Forecast Map")}
                    <p class="map-note" data-i18n="note.ensemble" data-i18n-model="{_esc(model_name)}">
                        {_esc(model_name)} &nbsp;·&nbsp; Gray lines = ensemble members &nbsp;·&nbsp;
                        Navy line = ensemble mean &nbsp;·&nbsp; Shaded cone = track uncertainty &nbsp;·&nbsp;
                        Dots = 6-hr intensity (filled ≥ 34 kt) &nbsp;·&nbsp; ★ = initial position
                    </p>
                </div>""")

        sec_id = f"sec-{key_prefix}-maps"
        sections.append((sec_id, 'sub.maps', 'Ensemble & JTWC'))
        maps_html = f"""
            <div class="maps-grid" id="{sec_id}">
                <div class="panel reveal">
                    <div class="panel-header">
                        <span class="panel-icon">🗺</span>
                        <span data-i18n="panel.ensemble">Ensemble Track Forecast</span>
                    </div>
                    {_model_tabs(track_id, model_names) if multi_model else ''}
                    {"".join(map_panels)}
                </div>

                <div class="panel reveal">
                    <div class="panel-header">
                        <span class="panel-icon">🛰</span>
                        <span data-i18n="panel.jtwc">JTWC Official Forecast</span>
                    </div>
                    {_figure(f"jtwc_{track_id}.gif", "JTWC Forecast", "this.closest('.panel').style.display='none';")}
                    <p class="map-note" data-i18n="note.jtwc">Source: Joint Typhoon Warning Center (JTWC) — U.S. Navy &amp; Air Force</p>
                </div>
            </div>"""

        subnav = "".join(
            f'<button data-target="{sid}" data-i18n="{k}">{txt}</button>' for sid, k, txt in sections)

        storm_views.append(f"""
    <section class="view" data-view="storm/{key_prefix}" data-title="{_esc(_title(info))}">
        <div class="page">
            {switcher}
            <div class="storm-hero reveal" style="--cat:{info['color']}">
                <div class="swirl" aria-hidden="true"></div>
                <div class="storm-hero-main">
                    <div class="storm-subtitle" data-i18n="storm.subtitle">Western Pacific Tropical Cyclone</div>
                    <h2 class="storm-title storm-name">{_esc(_title(info))}</h2>
                    <div class="storm-badges">
                        <span class="badge-cat" style="background:{info['color']};color:{info['text']};">{info['cat']}</span>
                        <span class="badge-id">{_esc(track_id)}</span>
                        <span class="badge-live"><span class="live-dot"></span><span data-i18n="badge.live">LIVE</span></span>
                        <span class="badge-name" data-i18n="catname.{info['cat']}">{info['cat']}</span>
                    </div>
                </div>
                <div class="gauge gauge-lg" data-kt="{kt_txt}" style="--cat:{info['color']}"></div>
            </div>
            <div class="stat-grid">{stats_html}</div>
            {scale_html}
            <nav class="subnav" aria-label="Sections">{subnav}</nav>
            {cmp_html}
            {anim_html}
            {maps_html}
        </div>
    </section>""")

    # ═════════════════════════════════════════════════════════════════
    #  生成潛勢頁
    # ═════════════════════════════════════════════════════════════════
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
                        <p class="map-note" style="margin-top:0;"
                           data-i18n="note.genesis" data-i18n-source="{_esc(_genesis_source(label))}">
                            Circles = ensemble members at each 6-hr step, colored by minimum sea level
                            pressure. Gray lines = individual ensemble tracks (0–360 h).
                            Data sourced from {_esc(_genesis_source(label))}.
                        </p>
                    </div>
                </div>""" for i, (label, img) in enumerate(_genesis_entries))

        compare_html = ""
        compare_btn = ""
        if multi_genesis:
            opts_a = "".join(f'<option value="{_esc(img)}"{" selected" if i == 0 else ""}>{_esc(lbl)}</option>'
                             for i, (lbl, img) in enumerate(_genesis_entries))
            opts_b = "".join(f'<option value="{_esc(img)}"{" selected" if i == 1 else ""}>{_esc(lbl)}</option>'
                             for i, (lbl, img) in enumerate(_genesis_entries))
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
                        <img class="cmp-base" src="{_esc(_genesis_entries[1][1])}" alt="" draggable="false">
                        <div class="cmp-top"><img src="{_esc(_genesis_entries[0][1])}" alt="" draggable="false"></div>
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
            return f"&lt; {hi} kt"
        if idx == len(CAT_RANGES) - 1:
            return f"≥ {lo} kt"
        return f"{lo}–{hi - 1} kt"

    scale_rows = "".join(f"""
                    <div class="scale-row reveal">
                        <span class="badge-cat" style="background:{CAT_COLOR_MAP[c]};color:{CAT_TEXT_MAP[c]}">{c}</span>
                        <span data-i18n="catname.{c}">{c}</span>
                        <span class="mono">{_range_txt(lo, hi, i)}</span>
                    </div>""" for i, (c, lo, hi) in enumerate(CAT_RANGES))

    about_view = f"""
    <section class="view" data-view="about" data-title-key="nav.about">
        <div class="page">
            <div class="page-head reveal">
                <div class="kicker" data-i18n="about.kicker">About</div>
                <h2 class="page-title" data-i18n="about.title">How to read this site</h2>
                <p class="page-lead" data-i18n="about.intro">This site gathers AI and physics-based ensemble forecasts for Western Pacific tropical cyclones and redraws them on a common style every 30 minutes, next to the official JTWC forecast.</p>
            </div>
            <div class="about-grid">
                <div class="panel reveal about-scale">
                    <div class="panel-header"><span class="panel-icon">🎨</span><span data-i18n="about.scale">Intensity categories</span></div>
                    <div class="scale-table">{scale_rows}</div>
                </div>
                <div class="panel reveal about-read">
                    <div class="panel-header"><span class="panel-icon">🧭</span><span data-i18n="about.reading">Reading the maps</span></div>
                    <div class="read-list">
                        <div><h4 data-i18n="panel.comparison">Multi-Model Comparison</h4><p class="map-note" data-i18n="note.comparison"></p></div>
                        <div><h4 data-i18n="panel.ensemble">Ensemble Track Forecast</h4><p class="map-note" data-i18n="note.ensemble" data-i18n-model="WNC3 / GENC / AIFS / ECMWF"></p></div>
                        <div><h4 data-i18n="panel.anim.generic">Track Evolution Animation</h4><p class="map-note" data-i18n="note.anim"></p></div>
                        <div><h4 data-i18n="nav.genesis">Genesis</h4><p class="map-note" data-i18n="note.genesis" data-i18n-source="Google DeepMind / ECMWF Open Data"></p></div>
                    </div>
                </div>
                <div class="panel reveal about-keys">
                    <div class="panel-header"><span class="panel-icon">⌨️</span><span data-i18n="about.keys">Keyboard shortcuts</span></div>
                    <div class="keys-list">
                        <div><span><kbd>1</kbd>–<kbd>{min(9, len(routes))}</kbd></span><span data-i18n="key.views">Switch pages</span></div>
                        <div><span><kbd>Space</kbd></span><span data-i18n="key.play">Play / pause the animation</span></div>
                        <div><span><kbd>←</kbd><kbd>→</kbd></span><span data-i18n="key.seek">Step animation frames</span></div>
                        <div><span><kbd>Esc</kbd></span><span data-i18n="key.esc">Close the enlarged image</span></div>
                    </div>
                </div>
                <div class="panel reveal disclaimer">
                    <div class="panel-header"><span class="panel-icon">⚠️</span><span data-i18n="about.notice">Notice</span></div>
                    <p data-i18n="about.disclaimer">Not for operational use. For official warnings, follow your national meteorological agency.</p>
                </div>
            </div>
        </div>
    </section>"""

    # ═════════════════════════════════════════════════════════════════
    #  導覽列（桌面頂部／行動版底部）
    # ═════════════════════════════════════════════════════════════════
    nav_links = [f'<a class="nav-link" href="#/overview" data-route="overview">{ICONS["overview"]}<span data-i18n="nav.overview">Overview</span></a>']
    for info in infos.values():
        nav_links.append(
            f'<a class="nav-link" href="#/storm/{_esc(info["id"])}" data-route="storm/{_esc(info["id"])}">'
            f'<span class="nav-dot" style="--c:{info["color"]}"></span><span class="storm-name">{_esc(_title(info))}</span></a>')
    if _genesis_entries:
        nav_links.append(f'<a class="nav-link" href="#/genesis" data-route="genesis">{ICONS["genesis"]}<span data-i18n="nav.genesis">Genesis</span></a>')
    nav_links.append(f'<a class="nav-link" href="#/about" data-route="about">{ICONS["about"]}<span data-i18n="nav.about">About</span></a>')

    bottom = [f'<a href="#/overview" data-route="overview">{ICONS["overview"]}<span data-i18n="nav.overview">Overview</span></a>']
    if infos:
        first = next(iter(infos.values()))
        badge = f'<em class="bn-count">{len(infos)}</em>' if len(infos) > 1 else ''
        bottom.append(f'<a href="#/storm/{_esc(first["id"])}" data-route-prefix="storm/">{ICONS["storm"]}{badge}'
                      f'<span data-i18n="nav.storms">Storms</span></a>')
    if _genesis_entries:
        bottom.append(f'<a href="#/genesis" data-route="genesis">{ICONS["genesis"]}<span data-i18n="nav.genesis">Genesis</span></a>')
    bottom.append(f'<a href="#/about" data-route="about">{ICONS["about"]}<span data-i18n="nav.about">About</span></a>')

    # 給前端腳本的資料（路由、主視覺參數、更新時間）
    joined_ids = " / ".join(track_ids)
    title_track_ids = joined_ids or "Forecast"
    site_data = {
        'routes': routes,
        'updatedIso': now_local.isoformat(timespec='seconds'),
        'hero': {'rgb': hero_rgb, 'strength': round(hero_strength, 3)},
        'trackIds': joined_ids,
        'scaleMax': SCALE_MAX_KT,
        'bands': [[c, lo, hi, CAT_COLOR_MAP[c]] for c, lo, hi in CAT_RANGES],
    }
    site_json = json.dumps(site_data, ensure_ascii=False).replace('</', '<\\/')

    html_content = f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <meta name="color-scheme" content="light dark">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Montserrat:wght@200..800&family=Oswald:wght@300..700&family=Noto+Sans+TC:wght@300..900&display=swap">
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
    <style>{_CSS}</style>
</head>
<body>
    <a class="skip-link" href="#views">Skip to content</a>
    <header id="site-header">
        <a class="header-brand" href="#/overview">
            <div class="brand-icon"><span>🌀</span></div>
            <div class="brand-text">
                <h1 data-i18n="brand.title">Pillar's Tropical Cyclone Forecast</h1>
                <small data-i18n="brand.sub">Real-time WNC3 / WNC2-r2 / WNC2-r1 / GENC / AIFS / ECMWF Ensemble Forecast System · Western Pacific</small>
            </div>
        </a>
        <nav class="top-nav" aria-label="Pages"><span class="nav-indicator"></span>{"".join(nav_links)}</nav>
        <div class="header-actions">
            <div class="update-badge" id="update-badge" data-full="{update_time}">
                <svg class="ring" viewBox="0 0 20 20" aria-hidden="true"><circle class="ring-bg" cx="10" cy="10" r="7.5"/><circle class="ring-fg" cx="10" cy="10" r="7.5" pathLength="100"/></svg>
                <span class="ub-text"><span data-i18n="header.updated">Updated</span><span class="ub-long">: {update_time[:10]}</span> {update_time[11:16]}<span class="ub-long">{update_time[16:]}</span></span>
            </div>
            <button class="theme-btn" id="theme-btn">🌙 Dark</button>
            <button class="theme-btn" id="lang-btn" title="Switch language / 切換語言">🌐 中文</button>
            <span class="actions-break"></span>
            <span class="version-badge" title="Site version / 網站版本">v{SITE_VERSION}</span>
        </div>
        <div class="scroll-progress" aria-hidden="true"></div>
    </header>

    <main id="views">
{overview_view}
{"".join(storm_views)}
{genesis_view}
{about_view}
    </main>

    <footer>
        <div class="marquee footer-marquee" aria-hidden="true">
            {_marquee([("Pillar's", False, None), ("Tropical Cyclone", True, None), ("Forecast", False, None), ("Western Pacific", True, None)])}
        </div>
        <div class="footer-inner">
            <div class="footer-brand">
                <h3 data-i18n="footer.title">Pillar's Tropical Cyclone Forecast System</h3>
                <p data-i18n="footer.desc">
                    Ensemble track forecasts from DeepMind WeatherNext —
                    WNC3, WNC2-r2, WNC2-r1 &amp; GENC — and from ECMWF Open Data —
                    AIFS-ENS + AIFS-single &amp; IFS ENS + HRES.<br>
                    Official intensity guidance from JTWC. Data refreshed automatically.
                </p>
            </div>
            <div class="footer-links">
                <a href="https://deepmind.google.com/science/weatherlab" class="footer-link" target="_blank" rel="noopener"
                   data-i18n="footer.link1">🌐 DeepMind Weather</a>
                <a href="https://data.ecmwf.int/forecasts/" class="footer-link" target="_blank" rel="noopener"
                   data-i18n="footer.link2">🇪🇺 ECMWF Open Data</a>
                <a href="https://www.metoc.navy.mil/jtwc/jtwc.html" class="footer-link" target="_blank" rel="noopener">🛰 JTWC</a>
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
    <script>{_JS}</script>
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
    --text-3:    #72869b;
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
.frame-stage .frame { position:absolute; inset:0; width:100%; height:100%; object-fit: contain; opacity:0; transition: opacity .18s linear; }
.frame-stage .frame.is-front { opacity:1; }
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
.about-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: 20px; align-items:start; }
.scale-table { display:grid; gap: 8px; }
/* 寬螢幕排成三欄時，注意事項固定放右下（快捷鍵下方），不要掉到左邊第二列 */
@media (min-width: 1340px) {
    .about-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: stretch; }
    .about-scale { grid-column: 1; grid-row: 1 / span 2; }
    .about-read  { grid-column: 2; grid-row: 1 / span 2; }
    .about-keys  { grid-column: 3; grid-row: 1; }
    .about-grid .disclaimer { grid-column: 3; grid-row: 2; }
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

/* ═════════════════════════════════════════════════════════════════
   Noir 版面（v4）：參考 usta.agency —— 純黑底、白字、Oswald 大寫巨型標題、
   描邊字跑馬燈、difference 混色游標、hover 由下往上填滿的反白。
   寫在最後面整層覆蓋上方的 v3 樣式；淺色主題是同一套語言的「白紙黑字」版。
   ═════════════════════════════════════════════════════════════════ */
:root, [data-theme="light"] {
    --bg:        #f3f1ec;
    --surface:   #f8f7f3;
    --surface-2: #ece9e2;
    --surface-3: #e2ded5;
    --accent:    #0a0a0a;
    --accent-2:  #0a0a0a;
    --accent-lo: rgba(0,0,0,.06);
    --accent-rgb: 10,10,10;
    --text:      #0a0a0a;
    --text-2:    #3a3a3a;
    --text-3:    #7a756c;
    --border:    rgba(0,0,0,.16);
    --shadow: none; --shadow-md: none; --shadow-lg: none;
    --btn-bg:    #0a0a0a;
    --glass:     rgba(243,241,236,.62);
    --radius:    0px;
    --hero-1: #000; --hero-2: #000; --hero-3: #000;
    --display: 'Oswald', 'Noto Sans TC', 'Microsoft JhengHei', sans-serif;
}
[data-theme="dark"] {
    --bg:        #000000;
    --surface:   #050505;
    --surface-2: #0d0d0d;
    --surface-3: #181818;
    --accent:    #fff3dd;
    --accent-2:  #ffffff;
    --accent-lo: rgba(255,243,221,.08);
    --accent-rgb: 255,243,221;
    --text:      #ffffff;
    --text-2:    #d1d5db;
    --text-3:    #7d828a;
    --border:    rgba(255,255,255,.2);
    --btn-bg:    #ffffff;
    --glass:     rgba(0,0,0,.45);
}
body {
    font-family: 'Montserrat', 'Noto Sans TC', 'PingFang TC', 'Microsoft JhengHei', system-ui, sans-serif;
    font-weight: 400;
}
::selection { background: #fff3dd; color: #000; }

/* 大標一律 Oswald 大寫；中文落到 Noto Sans TC（大寫對中文無作用） */
.hero-title, .storm-title, .page-title, .section-head h3, .tile-name, .brand-text h1,
.empty-title, .model-name, .footer-brand h3, .panel-header, .stat-value, .chip-v,
.gauge-val b, .scale-now, .btn-primary, .btn-ghost, .mq {
    font-family: var(--display);
    text-transform: uppercase;
}

/* 方角、無陰影 */
.storm-tile, .empty-card, .genesis-teaser, .storm-hero, .stat, .model-card, .panel, .subnav,
.subnav button, .seg, .seg-ind, .model-tab-btn, .zoomable, .player, .update-badge, .theme-btn,
.version-badge, .btn-primary, .btn-ghost, .hero-chip, .eyebrow, .badge-cat, .badge-id, .badge-live,
.badge-name, .cat-pill, .count-chip, .mini-chip, .switch-chip, .ghost-btn, .pc-btn:not(.pc-main),
.speed-seg, .speed-btn, .genesis-legend, .scale-row, .model-label, .cmp-stage, .lightbox img,
.lb-close, .compare-pickers select, .ss-seg, .teaser-img, .calm-sea, .bottom-nav, .bottom-nav a,
.zoom-hint, kbd, .brand-icon, .nav-link, .nav-indicator { border-radius: 0 !important; }
.btn-primary, .btn-primary:hover, .subnav button.active, .pc-main, .seg-ind, .storm-hero,
.storm-tile, .panel, .stat, .model-card { box-shadow: none !important; }

/* ── 自訂游標：外層跟著滑鼠平移，內層圓點縮放；整顆用 difference 混色 ── */
html.has-cursor, html.has-cursor * { cursor: none !important; }
html.has-cursor input[type="range"], html.has-cursor select, html.has-cursor .cmp-stage { cursor: auto !important; }
#cursor {
    position: fixed; left: 0; top: 0; z-index: 100000; pointer-events: none;
    width: 0; height: 0; mix-blend-mode: difference;
    opacity: 0; transition: opacity .3s;
}
#cursor::before {
    content: ""; position: absolute; left: -8px; top: -8px; width: 16px; height: 16px; border-radius: 50%;
    background: #fff;
    transition: transform .45s cubic-bezier(.16,1,.3,1);
}
#cursor.on { opacity: 1; }
#cursor.big::before  { transform: scale(3.4); }
#cursor.zoom::before { transform: scale(5.5); }
#cursor.press::before { transform: scale(.7); }
#cursor.big.press::before { transform: scale(2.8); }

/* ── Header：黑色毛玻璃 ── */
header { background: var(--glass); -webkit-backdrop-filter: blur(20px); backdrop-filter: blur(20px); padding: 0 32px; }
[data-theme="dark"] header { background: linear-gradient(to top, rgba(0,0,0,.55), rgba(0,0,0,.15)); }
.scroll-progress { background: var(--text); height: 1px; }
.brand-icon { background: none; box-shadow: none; border: 1px solid var(--border); }
.brand-text h1 { font-weight: 600; font-size: 1.15em; letter-spacing: .06em; }
html[lang^="zh"] .brand-text h1 { letter-spacing: .08em; }

/* 導覽連結等：hover 時色塊由下往上填滿、字反白 */
.nav-link, .footer-link, .theme-btn, .btn-ghost {
    isolation: isolate; overflow: hidden; position: relative;
    transition: color .55s cubic-bezier(0,0,.2,1), border-color .3s;
}
.nav-link { text-transform: uppercase; letter-spacing: .08em; font-weight: 500; font-size: .8em; color: var(--text-2); }
html[lang^="zh"] .nav-link { letter-spacing: .1em; }
.nav-link::before, .footer-link::before, .theme-btn::before, .btn-ghost::before {
    content: ""; position: absolute; left: 0; right: 0; top: 100%; bottom: 0; z-index: -1;
    background: var(--text);
    transition: top .6s cubic-bezier(0,0,.2,1);
}
.nav-link:hover::before, .footer-link:hover::before, .theme-btn:hover::before, .btn-ghost:hover::before { top: 0; }
.nav-link:hover, .footer-link:hover, .theme-btn:hover, .btn-ghost:hover,
.nav-link.active:hover { color: var(--bg) !important; }
.nav-link.active { color: var(--text); }
.nav-indicator { background: none; border: 0; box-shadow: inset 0 -2px 0 var(--text); }
.nav-dot { box-shadow: none; }

.update-badge, .theme-btn { background: transparent; border-color: var(--border); color: var(--text-2); }
.theme-btn:hover { background: transparent; border-color: var(--text); }
.version-badge, [data-theme="dark"] .version-badge { background: var(--text); color: var(--bg); border-color: var(--text); font-family: var(--display); letter-spacing: .08em; }
.ring-fg { stroke: var(--text); }

/* ── Hero：滿版黑、文字貼底 ── */
.hero {
    background: #000;
    min-height: calc(100svh - var(--header-h));
    align-items: flex-end;
}
[data-theme="light"] .hero::after { background: linear-gradient(to bottom, transparent, var(--bg)); height: 90px; }
[data-theme="dark"] .hero::after { display: none; }
.hero-eye { background: radial-gradient(circle, #000 0 16%, rgba(var(--flow-rgb),.14) 32%, transparent 70%); }
.hero-inner { max-width: 1480px; padding: 80px 32px 64px; }
.eyebrow {
    background: none; border: 0; padding: 0; -webkit-backdrop-filter: none; backdrop-filter: none;
    font-weight: 500; letter-spacing: .3em; color: rgba(255,255,255,.72);
}
.eyebrow::before { content: ""; width: 42px; height: 1px; background: currentColor; }
.hero-title {
    font-weight: 600; font-size: clamp(3.6rem, 13vw, 11.5rem);
    line-height: .9; letter-spacing: .01em; max-width: none;
    margin: 22px 0 26px; text-shadow: none;
}
html[lang^="zh"] .hero-title { font-size: clamp(2.8rem, 9vw, 7.5rem); line-height: 1.12; letter-spacing: .06em; }
.hero-title.storm-name, .storm-title.storm-name { letter-spacing: .02em !important; }
.hero-lead { font-weight: 300; font-size: clamp(1.05rem, 1.8vw, 1.5rem); color: rgba(255,255,255,.86); }
.hero-sub { font-weight: 300; color: rgba(255,255,255,.62); }
.cat-pill { font-family: var(--display); font-weight: 500; letter-spacing: .1em; }
.btn-primary, .btn-ghost { padding: 16px 28px; font-weight: 500; letter-spacing: .14em; font-size: .9em; }
.btn-primary { background: #fff; color: #000; transition: background .4s, color .4s, transform .4s var(--ease-out); }
.btn-primary:hover { transform: none; background: #fff3dd; }
.btn-ghost { color: #fff; border: 1px solid rgba(255,255,255,.4); background: transparent; }
.btn-ghost::before { background: #fff; }
.btn-ghost:hover { color: #000 !important; background: transparent; transform: none; }
.hero-meta { gap: 0; margin-top: 56px; border-top: 1px solid rgba(255,255,255,.2); }
.hero-chip {
    background: none; border: 0; border-right: 1px solid rgba(255,255,255,.2);
    -webkit-backdrop-filter: none; backdrop-filter: none;
    padding: 18px 34px 4px 0; margin-right: 34px; min-width: 0;
}
.hero-chip:last-child { border-right: 0; margin-right: 0; }
.chip-k { font-weight: 500; letter-spacing: .24em; opacity: .55; font-size: .7em; }
.chip-v, html[lang^="zh"] .chip-v { font-weight: 400; font-size: 2.1em; letter-spacing: .04em; }
.scroll-cue { display: none; }

/* ── 跑馬燈：實心／描邊交替的巨型字，中間用小圓點隔開 ── */
.marquee {
    overflow: hidden; padding: clamp(28px, 5vw, 64px) 0;
    border-bottom: 1px solid var(--border); background: var(--bg);
    display: flex; flex-direction: column; gap: clamp(8px, 1.5vw, 20px);
}
.strip { display: flex; width: max-content; animation: run 42s linear infinite; will-change: transform; }
.strip.reverse { animation-direction: reverse; animation-duration: 56s; }
.marquee:hover .strip { animation-play-state: paused; }
@keyframes run { to { transform: translate3d(-50%,0,0); } }
.mq {
    display: inline-flex; align-items: center; white-space: nowrap;
    font-size: clamp(3rem, 9vw, 8.5rem); font-weight: 600; line-height: 1.02; letter-spacing: .01em;
    color: var(--c, var(--text));
}
.mq::after {
    content: ""; flex-shrink: 0; width: .09em; height: .09em; min-width: 7px; min-height: 7px; border-radius: 50%;
    background: var(--text); margin: 0 .45em;
}
.mq.o { color: transparent; -webkit-text-stroke: 1px var(--text); }
@media (min-width: 1024px) { .mq.o { -webkit-text-stroke-width: 2px; } }
.strip.reverse .mq { font-size: clamp(2.2rem, 6vw, 5.5rem); font-weight: 300; }
.footer-marquee { border-top: 1px solid var(--border); border-bottom: 0; background: transparent; margin-bottom: 40px; }

/* ── 標語：捲動時逐字點亮 ── */
.statement {
    max-width: 1480px; margin: 0 auto; padding: clamp(90px, 16vh, 200px) 32px;
    min-height: 70vh; display: flex; align-items: center;
}
.words {
    font-size: clamp(1.9rem, 4.6vw, 4.4rem); font-weight: 200; line-height: 1.22;
    color: var(--text-3); max-width: 24ch;
}
html[lang^="zh"] .words { font-weight: 300; line-height: 1.5; letter-spacing: .06em; max-width: 20em; font-size: clamp(1.6rem, 3.6vw, 3.4rem); }
.words strong { font-weight: 600; }
.wd { opacity: .22; transition: opacity .5s ease, color .5s ease; }
.wd.lit { opacity: 1; color: var(--text-2); }
.words strong .wd.lit { color: var(--text); }

/* ── 版面與區塊標題 ── */
.page { max-width: 1480px; padding: 40px 32px 72px; gap: 32px; }
.section-head {
    margin-top: 70px; padding-bottom: 22px; border-bottom: 1px solid var(--border);
    align-items: flex-end;
}
.section-head:first-child { margin-top: 10px; }
.section-head h3 { font-size: clamp(2.6rem, 6.5vw, 5.6rem); font-weight: 600; line-height: .95; letter-spacing: .01em; }
html[lang^="zh"] .section-head h3 { letter-spacing: .08em; line-height: 1.15; }
.kicker { color: var(--text-3); font-weight: 500; letter-spacing: .3em; margin-bottom: 14px; display: flex; align-items: center; gap: 12px; }
.kicker::before { content: ""; width: 32px; height: 1px; background: currentColor; }
.count-chip { background: none; color: var(--text); font-family: var(--display); font-size: clamp(2.6rem, 6.5vw, 5.6rem); font-weight: 200; line-height: .95; padding: 0; }
.page-title { font-size: clamp(2.4rem, 6vw, 5.2rem); font-weight: 600; line-height: .98; letter-spacing: .01em; max-width: 20ch; }
html[lang^="zh"] .page-title { line-height: 1.2; letter-spacing: .06em; }
.page-lead { font-weight: 300; font-size: 1.1em; }
.legend-inline { text-transform: uppercase; letter-spacing: .14em; font-weight: 500; }

/* ── 卡片：透明底＋細框，hover 框變實 ── */
.storm-tile, .empty-card, .genesis-teaser, .model-card, .stat, .panel {
    background: transparent; border: 1px solid var(--border);
}
.storm-tile { padding: 30px; transition: border-color .4s, transform .5s var(--ease-out), opacity .8s var(--ease-out); }
.storm-tile:hover, .genesis-teaser:hover, .model-card:hover, .stat:hover { border-color: var(--text); transform: none; }
.storm-tile::before { height: 2px; }
.storm-tile::after { opacity: .1; }
.storm-grid { grid-template-columns: repeat(auto-fit, minmax(min(100%, 520px), 1fr)); gap: 24px; }
.tile-name { font-size: clamp(2.6rem, 5vw, 4.4rem); font-weight: 600; line-height: .95; overflow-wrap: normal; }
.tile-catname { font-weight: 400; letter-spacing: .06em; }
.tile-facts dt { font-weight: 400; text-transform: uppercase; letter-spacing: .12em; font-size: .85em; }
.tile-facts dd { font-weight: 500; }
.tile-cta { color: var(--text); font-weight: 500; letter-spacing: .16em; text-transform: uppercase; font-size: .78em; }
.empty-card { border-style: solid; }
.empty-title { font-weight: 500; font-size: 1.8em; letter-spacing: .04em; }
.teaser-body { border-left: 1px solid var(--border); padding: 34px; }
.mini-chip { background: none; }
.model-grid { grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0; border-top: 1px solid var(--border); border-left: 1px solid var(--border); }
.model-card { border-width: 0 1px 1px 0; padding: 24px; }
.model-card:hover { background: var(--surface-2); }
.model-name { font-weight: 500; font-size: 1.6em; letter-spacing: .04em; }
.model-org { color: var(--text-2); font-weight: 500; text-transform: uppercase; letter-spacing: .14em; font-size: .7em; margin-top: 10px; }
.model-state.on, .model-card.on .model-state { background: #fff3dd; box-shadow: none; animation: none; }
[data-theme="light"] .model-state.on, [data-theme="light"] .model-card.on .model-state { background: #0a0a0a; }

/* ── 颱風頁 ── */
.switch-chip { background: none; text-transform: uppercase; }
.switch-chip.active { background: var(--text); color: var(--bg); border-color: var(--text); }
.storm-hero {
    background: radial-gradient(700px 380px at 85% 50%, color-mix(in srgb, var(--cat) 18%, transparent), transparent 70%), #000;
    border: 1px solid rgba(255,255,255,.14); padding: 48px 44px;
}
.storm-hero .swirl { opacity: .14; }
.storm-subtitle { font-weight: 500; letter-spacing: .3em; }
.storm-title { font-size: clamp(3.4rem, 10vw, 9rem); font-weight: 600; line-height: .9; text-shadow: none; margin: 16px 0 24px; }
.badge-cat, .badge-name, .badge-live, .badge-id { font-weight: 500; letter-spacing: .1em; text-transform: uppercase; }
.badge-id { font-family: var(--display); }
.gauge-val b { font-weight: 400; }
.g-prog { filter: none; }
.stat-grid { gap: 0; border-left: 1px solid var(--border); }
.stat { border-left: 0; padding: 22px 24px; }
.stat-label { font-weight: 500; letter-spacing: .24em; }
.stat-label span[aria-hidden] { display: none; }
.stat-value { font-weight: 400; font-size: 2.2em; letter-spacing: .03em; }
.stat-value small { font-family: 'Montserrat', sans-serif; text-transform: none; }
.scale-head { text-transform: uppercase; letter-spacing: .16em; font-weight: 500; font-size: .78em; }
.scale-now { font-size: 1.6em; font-weight: 400; letter-spacing: .04em; }
.ss-seg em { font-weight: 600; }
.ss-marker span, .ss-marker span::before { box-shadow: 0 0 0 3px var(--bg); }
.subnav { background: var(--glass); padding: 0; gap: 0; }
.subnav button { text-transform: uppercase; letter-spacing: .14em; font-weight: 500; font-size: .74em; padding: 12px 20px; }
.subnav button.active { background: var(--text); color: var(--bg); }

.panel { padding: 28px; }
.panel-header { font-size: 1.5em; font-weight: 500; letter-spacing: .05em; padding-bottom: 18px; margin-bottom: 22px; }
html[lang^="zh"] .panel-header { font-size: 1.3em; letter-spacing: .08em; }
.panel-icon { display: none; }
.kbd-hint { font-family: 'Montserrat', sans-serif; text-transform: none; letter-spacing: 0; }
.map-note { font-weight: 300; }
.model-label { background: var(--text); color: var(--bg); font-weight: 500; letter-spacing: .1em; }
.seg { background: transparent; padding: 0; gap: 0; }
.model-tab-btn { font-weight: 500; letter-spacing: .1em; padding: 10px 18px; }
.model-tab-btn.active { color: var(--bg); }
.seg-ind { background: var(--text); }
.zoom-hint { background: #000; letter-spacing: .08em; }
.player, .player-controls, .pc-btn, .speed-seg { background: transparent; }
.pc-btn:hover { color: var(--text); border-color: var(--text); }
.pc-main, .pc-main:hover { background: var(--text); color: var(--bg); }
.player.playing .pc-main { animation: none; }
.timeline { height: 2px; background: linear-gradient(90deg, var(--text) 0 var(--fill, 0%), var(--border) var(--fill, 0%) 100%); }
.timeline::-webkit-slider-thumb { background: var(--text); border: 0; width: 14px; height: 14px; }
.timeline::-moz-range-thumb { background: var(--text); border: 0; }
.buffer span { background: var(--text); }
.speed-btn.active { background: var(--text); color: var(--bg); }

/* ── 生成潛勢／說明 ── */
.genesis-panel { border-top: 2px solid var(--warn); }
.genesis-legend { background: transparent; }
.ghost-btn { background: transparent; text-transform: uppercase; letter-spacing: .1em; font-weight: 500; }
.ghost-btn:hover { color: var(--text); border-color: var(--text); }
.ghost-btn[aria-pressed="true"] { background: var(--text); color: var(--bg); }
.pick-dot.a { background: var(--text); }
.scale-row { background: transparent; border-bottom: 1px solid var(--border); padding: 12px 4px; font-weight: 400; }
.read-list h4 { font-family: var(--display); text-transform: uppercase; font-weight: 500; font-size: 1.1em; letter-spacing: .05em; }

/* ── Footer ── */
footer { border-top: 0; padding-top: 0; margin-top: 60px; }
.footer-inner { max-width: 1480px; padding: 0 32px 40px; }
.footer-brand h3 { font-weight: 500; font-size: 1.6em; letter-spacing: .04em; }
.footer-brand p { font-weight: 300; }
.footer-link { padding: 4px 8px; text-transform: uppercase; letter-spacing: .12em; font-weight: 500; font-size: .74em; }
.footer-copy { text-transform: uppercase; letter-spacing: .14em; font-size: .68em; }

/* ── Lightbox ── */
.lightbox { background: rgba(0,0,0,.96); }
.lb-close { background: transparent; border-color: rgba(255,255,255,.4); }

@media (max-width: 900px) {
    header { padding: 10px 16px; }
    .bottom-nav { left: 0; right: 0; bottom: 0; padding-bottom: calc(6px + env(safe-area-inset-bottom)); border-width: 1px 0 0; }
    .bottom-nav a { text-transform: uppercase; letter-spacing: .08em; font-weight: 500; }
    .bottom-nav a.active { background: var(--text); color: var(--bg); }
    .hero-inner { padding: 60px 20px 48px; }
    .statement { padding: 90px 20px; min-height: 0; }
    .page { padding: 28px 20px 56px; }
    .storm-hero { padding: 32px 24px; }
    .teaser-body { border-left: 0; border-top: 1px solid var(--border); }
}
@media (max-width: 600px) {
    .page { padding: 20px 16px 48px; gap: 22px; }
    .hero-inner { padding: 48px 16px 36px; }
    .hero-title { font-size: clamp(3.4rem, 17vw, 6rem); }
    .hero-meta { margin-top: 36px; }
    .hero-chip { flex: 1 1 30%; padding: 14px 10px 2px 0; margin-right: 10px; }
    .chip-v, html[lang^="zh"] .chip-v { font-size: 1.35em; }
    .statement { padding: 72px 16px; }
    .section-head { margin-top: 44px; }
    .storm-tile, .panel { padding: 18px; }
    .footer-inner { padding: 0 16px 32px; }
}
@media (max-width: 370px) { .chip-v, html[lang^="zh"] .chip-v { font-size: 1.15em; } }

/* 使用者要求減少動態時：停掉所有非必要的動畫與轉場 */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: .001ms !important; animation-iteration-count: 1 !important; transition-duration: .001ms !important; transition-delay: 0s !important; }
    .split .ch { opacity:1; transform:none; filter:none; }
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

// ── i18n（中／英切換）─────────────────────────────────────────────
// 版面上所有固定文案都掛 data-i18n="key"，切換語言時由 applyLang() 一次換掉；
// 帶參數的字串用 {name} 佔位，值由同一元素上的 data-i18n-name 提供。
const I18N = {
  en: {
    'doc.title':        "Pillar's Tropical Cyclone Forecast",
    'brand.title':      "Pillar's Tropical Cyclone Forecast",
    'brand.sub':        'Real-time WNC3 / WNC2-r2 / WNC2-r1 / GENC / AIFS / ECMWF Ensemble Forecast System · Western Pacific',
    'header.updated':   'Updated',
    'btn.dark':         '🌙 Dark',
    'btn.light':        '☀️ Light',
    'btn.lang':         '🌐 中文',
    'btn.lang.short':   '中',
    'nav.overview':     'Overview',
    'nav.storms':       'Storms',
    'nav.genesis':      'Genesis',
    'nav.about':        'About',
    'hero.eyebrow.live':  'Now tracking',
    'hero.eyebrow.quiet': 'Western Pacific · Monitoring',
    'hero.quiet.title': 'All quiet in the Western Pacific',
    'hero.quiet.sub':   'No active tropical cyclones right now. The genesis outlook shows where ensemble members hint at something forming next.',
    'hero.live.sub':    '{count} active system(s) · ensemble guidance from {models} models, refreshed every 30 minutes.',
    'hero.cta.storm':   'Open forecast',
    'hero.cta.genesis': 'Genesis outlook',
    'hero.now':         'Current time',
    'hero.updated':     'Data updated',
    'hero.active':      'Active systems',
    'statement':        'We track tropical cyclones at the intersection between <strong>artificial intelligence</strong> and <strong>physics</strong> — every ensemble member, every 30 minutes, side by side with the official forecast.',
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
    'empty.desc':       'Nothing is spinning up right now. This page refreshes automatically every 30 minutes.',
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
    'note.ensemble':    '{model} &nbsp;·&nbsp; Gray lines = ensemble members &nbsp;·&nbsp; Navy line = ensemble mean &nbsp;·&nbsp; Shaded cone = track uncertainty &nbsp;·&nbsp; Dots = 6-hr intensity (filled ≥ 34 kt) &nbsp;·&nbsp; ★ = initial position',
    'panel.jtwc':       'JTWC Official Forecast',
    'note.jtwc':        'Source: Joint Typhoon Warning Center (JTWC) — U.S. Navy &amp; Air Force',
    'panel.genesis':    'Western Pacific Tropical Cyclone Genesis Potential — Ensemble Overview',
    'note.genesis':     'Circles = ensemble members at each 6-hr step, colored by minimum sea level pressure. Gray lines = individual ensemble tracks (0–360 h). Data sourced from {source}.',
    'about.kicker':     'About',
    'about.title':      'How to read this site',
    'about.intro':      'This site gathers AI and physics-based ensemble forecasts for Western Pacific tropical cyclones and redraws them in one common style every 30 minutes, next to the official JTWC forecast.',
    'about.scale':      'Intensity categories',
    'about.reading':    'Reading the maps',
    'about.keys':       'Keyboard shortcuts',
    'about.notice':     'Notice',
    'about.disclaimer': 'Not for operational use. For official warnings, follow your national meteorological agency.',
    'key.views':        'Switch pages',
    'key.play':         'Play / pause the animation',
    'key.seek':         'Step animation frames',
    'key.esc':          'Close the enlarged image',
    'footer.title':     "Pillar's Tropical Cyclone Forecast System",
    'footer.desc':      'Ensemble track forecasts from DeepMind WeatherNext — WNC3, WNC2-r2, WNC2-r1 &amp; GENC — and from ECMWF Open Data — AIFS-ENS + AIFS-single &amp; IFS ENS + HRES.<br>Official intensity guidance from JTWC. Data refreshed automatically.',
    'footer.link1':     '🌐 DeepMind Weather',
    'footer.link2':     '🇪🇺 ECMWF Open Data',
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
    'brand.sub':        'WNC3 / WNC2-r2 / WNC2-r1 / GENC / AIFS / ECMWF 即時系集預報系統 · 西北太平洋',
    'header.updated':   '更新於',
    'btn.dark':         '🌙 深色',
    'btn.light':        '☀️ 淺色',
    'btn.lang':         '🌐 English',
    'btn.lang.short':   'EN',
    'nav.overview':     '總覽',
    'nav.storms':       '颱風',
    'nav.genesis':      '生成潛勢',
    'nav.about':        '說明',
    'hero.eyebrow.live':  '正在追蹤',
    'hero.eyebrow.quiet': '西北太平洋 · 監測中',
    'hero.quiet.title': '目前風平浪靜',
    'hero.quiet.sub':   '目前沒有活躍的熱帶氣旋。生成潛勢圖顯示各系集成員認為下一個系統可能在哪裡形成。',
    'hero.live.sub':    '{count} 個活躍系統 · 綜合 {models} 個模式的系集預報，每 30 分鐘更新。',
    'hero.cta.storm':   '查看預報',
    'hero.cta.genesis': '生成潛勢',
    'hero.now':         '現在時間',
    'hero.updated':     '資料更新',
    'hero.active':      '活躍系統',
    'statement':        '我們在<strong>人工智慧</strong>與<strong>物理模式</strong>的交會點追蹤熱帶氣旋——每一個系集成員、每 30 分鐘更新，與官方預報並列呈現。',
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
    'empty.desc':       '目前沒有發展中的系統，每 30 分鐘自動更新',
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
    'note.ensemble':    '{model} &nbsp;·&nbsp; 灰線＝系集成員 &nbsp;·&nbsp; 深藍線＝系集平均 &nbsp;·&nbsp; 陰影錐＝路徑不確定範圍 &nbsp;·&nbsp; 圓點＝每 6 小時強度（≥ 34 kt 為實心） &nbsp;·&nbsp; ★＝起始位置',
    'panel.jtwc':       'JTWC 官方預報',
    'note.jtwc':        '資料來源：美國聯合颱風警報中心（JTWC）— 美國海軍與空軍',
    'panel.genesis':    '西北太平洋熱帶氣旋生成潛勢 — 系集綜覽',
    'note.genesis':     '圓圈＝各系集成員每 6 小時的位置，顏色代表海平面最低氣壓。灰線＝各系集成員的個別路徑（0–360 小時）。資料來源：{source}。',
    'about.kicker':     '說明',
    'about.title':      '如何閱讀本站',
    'about.intro':      '本站彙整 AI 與物理模式對西北太平洋熱帶氣旋的系集預報，每 30 分鐘以統一的樣式重新繪製，並與 JTWC 官方預報並列。',
    'about.scale':      '強度分級',
    'about.reading':    '圖面說明',
    'about.keys':       '鍵盤快捷鍵',
    'about.notice':     '注意事項',
    'about.disclaimer': '本站僅供參考，不可作為作業依據；官方警報請以各國氣象單位發布為準。',
    'key.views':        '切換頁面',
    'key.play':         '播放／暫停動畫',
    'key.seek':         '動畫逐格播放',
    'key.esc':          '關閉放大的圖片',
    'footer.title':     'Pillar 熱帶氣旋預報系統',
    'footer.desc':      '系集路徑預報來自 DeepMind WeatherNext — WNC3、WNC2-r2、WNC2-r1 與 GENC — 以及 ECMWF Open Data — AIFS-ENS + AIFS-single 與 IFS ENS + HRES。<br>官方強度指引來自 JTWC，資料自動更新。',
    'footer.link1':     '🌐 DeepMind 天氣實驗室',
    'footer.link2':     '🇪🇺 ECMWF 開放資料',
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
    applyTheme(root.getAttribute('data-theme') || 'light', false);
    $$('.split').forEach(splitText);
    $$('.words').forEach(splitWords);
    updateWords();
    $$('.player').forEach(el => players[el.dataset.animKey] && setPlayBtn(players[el.dataset.animKey]));
    updateTitle();
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
    let i = 0, out = '';
    for (const tok of tokens) {
        if (/^\s+$/.test(tok)) { out += ' '; continue; }
        out += '<span class="w" aria-hidden="true">';
        for (const ch of tok) out += `<span class="ch" style="--i:${i++}">${ch.replace(/&/g,'&amp;').replace(/</g,'&lt;')}</span>`;
        out += '</span>';
    }
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
    $$('.top-nav .nav-link').forEach(a => a.classList.toggle('active', a.dataset.route === currentRoute));
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
    Hero.setActive(view.dataset.view === 'overview');
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
    if (nav) placeIndicator($('.nav-indicator', nav), $('.nav-link.active', nav));
    $$('.seg').forEach(seg => {
        if (!seg.offsetParent) return;
        placeIndicator($('.seg-ind', seg), $('.model-tab-btn.active', seg));
        seg.classList.add('ready');
    });
}
window.addEventListener('resize', () => requestAnimationFrame(updateIndicators));

// ── Model tab switching (WNC3 / WNC2-r2 / WNC2-r1 / GENC for the same storm) ──
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
        .forEach(b => b.classList.toggle('active', b.dataset.model === model));
    requestAnimationFrame(updateIndicators);
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
            b.hidden = !sec || sec.style.display === 'none' || !sec.offsetParent && nav.offsetParent !== null;
        });
    });
}
let spyRaf = 0;
function scrollSpy() {
    spyRaf = 0;
    const view = currentRoute && viewFor(currentRoute);
    const nav = view && $('.subnav', view);
    if (!nav) return;
    const line = (parseFloat(getComputedStyle(root).getPropertyValue('--header-h')) || 64) + nav.offsetHeight + 60;
    let active = null;
    $$('button[data-target]', nav).forEach(b => {
        const sec = document.getElementById(b.dataset.target);
        if (sec && !b.hidden && sec.getBoundingClientRect().top <= line) active = b;
    });
    if (!active) active = $$('button[data-target]', nav).find(b => !b.hidden) || null;
    $$('button', nav).forEach(b => b.classList.toggle('active', b === active));
}
document.addEventListener('click', e => {
    const b = e.target.closest('.subnav button[data-target]');
    if (!b) return;
    const sec = document.getElementById(b.dataset.target);
    if (sec) sec.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' });
});
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

// ── 自訂游標：白點以 difference 混色反白底下的內容，移到可點的東西上會放大 ──
if (canHover && !reduced()) {
    const cur = document.createElement('div');
    cur.id = 'cursor';
    cur.setAttribute('aria-hidden', 'true');
    document.body.appendChild(cur);
    root.classList.add('has-cursor');
    let x = 0, y = 0, cx = 0, cy = 0, raf = 0, shown = false;
    const follow = () => {
        cx += (x - cx) * 0.24; cy += (y - cy) * 0.24;
        cur.style.transform = `translate3d(${cx.toFixed(1)}px,${cy.toFixed(1)}px,0)`;
        raf = (Math.abs(x - cx) + Math.abs(y - cy) > 0.2) ? requestAnimationFrame(follow) : 0;
    };
    document.addEventListener('pointermove', e => {
        if (e.pointerType !== 'mouse') return;
        x = e.clientX; y = e.clientY;
        if (!shown) { cx = x; cy = y; shown = true; cur.classList.add('on'); }
        const hit = e.target.closest && e.target.closest('a, button, select, label, input, [role="slider"], .zoomable, .lightbox');
        const zoom = !!hit && hit.matches('.zoomable:not(.broken)');
        cur.classList.toggle('zoom', zoom);
        cur.classList.toggle('big', !!hit && !zoom);
        if (!raf) raf = requestAnimationFrame(follow);
    }, { passive: true });
    document.documentElement.addEventListener('mouseleave', () => { cur.classList.remove('on'); shown = false; });
    document.addEventListener('pointerdown', () => cur.classList.add('press'));
    document.addEventListener('pointerup', () => cur.classList.remove('press'));
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
        i: 0, playing: false, timer: null, speed: 2,
        imgs: $$('.frame', el), front: 0,
        cache: [], loaded: 0, preloading: false,
        touched: false, autoPaused: false,
        stage: $('.frame-stage', el), slider: $('.timeline', el),
        counter: $('.frame-counter', el), btn: $('[data-act="toggle"]', el),
        buf: $('.buffer span', el),
    };
    players[P.key] = P;
    const first = P.imgs[0];
    const size = () => { if (first.naturalWidth) P.stage.style.setProperty('--ar', `${first.naturalWidth} / ${first.naturalHeight}`); };
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
    const swap = () => {
        back.classList.add('is-front');
        front.classList.remove('is-front');
        P.front = 1 - P.front;
    };
    back.onload = null;
    back.src = url;
    if (back.complete && back.naturalWidth) swap();
    else back.onload = () => { back.onload = null; if (back.getAttribute('src') === P.urls[P.i]) swap(); };
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
    const tab = e.target.closest('.model-tab-btn');
    if (tab) { switchModelTab(tab.dataset.track, tab.dataset.model); return; }
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
    const el = $$('.player', view).find(p => p.offsetParent !== null);
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
//  更新時間：相對時間、倒數下一次自動重新整理、資料過時提示
// ═════════════════════════════════════════════════════════════════
const UPDATED = new Date(SITE.updatedIso);
// 每半小時（HH:05 與 HH:35）自動重新整理
// ——排程任務於 HH:00 與 HH:30 更新資料並推送，各留 5 分鐘緩衝
function nextRefresh(now) {
    const next = new Date(now);
    const m = now.getMinutes();
    if (m < 5)        next.setMinutes(5, 0, 0);
    else if (m < 35)  next.setMinutes(35, 0, 0);
    else { next.setHours(next.getHours() + 1); next.setMinutes(5, 0, 0); }
    return next;
}
const REFRESH_AT = nextRefresh(new Date());
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
    if (ring) ring.style.strokeDashoffset = (100 - Math.max(0, Math.min(1, remain / (30 * 60000))) * 100).toFixed(2);
    const mins = Math.floor((now - UPDATED) / 60000);
    const rel = isNaN(mins) ? '' : mins < 1 ? t('rel.now') : mins < 60 ? t('rel.min', { n: mins }) : t('rel.hr', { n: Math.floor(mins / 60) });
    const badge = $('#update-badge');
    if (badge) {
        const stale = mins > 75;
        badge.classList.toggle('stale', stale);
        badge.title = t('header.updated') + ': ' + badge.dataset.full + ' · ' +
            (stale ? t('status.stale', { t: rel }) : t('status.next', { t: fmtRemain(remain) }));
    }
}
setTimeout(() => {
    try { sessionStorage.setItem('scroll:' + location.hash, String(scrollY)); } catch (e) {}
    location.reload();
}, REFRESH_AT - new Date());

// ── Keyboard shortcuts ─────────────────────────────────────────────
document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
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

$$('.gauge').forEach(buildGauge);
if (!reduced()) $$('[data-count]').forEach(el => { if (!el.closest('.gauge')) el.textContent = '0'; });
$$('.player').forEach(initPlayer);
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
