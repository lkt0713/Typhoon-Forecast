"""建站冒煙測試：不下載任何資料，只確認網站產生器還能跑、產出的頁面沒有明顯壞掉。

    python tests/test_site.py            # 本機
    （CI：.github/workflows/ci.yml 在每個 PR 上跑）

兩個情境：
1. 沒有颱風：generate_forecast_html([]) 要能產出總覽／生成潛勢／說明頁。
2. 用 repo 裡 docs/ 現有的圖檔重建目前的網站（跟自動更新產出的一樣），檢查：
   - 每個 data-i18n 鍵在中英文字典都有，兩邊鍵集合相同
   - 頁面引用的本地圖片／檔案都存在（抓到路徑拼錯）
   - 沒有 None／nan 漏進屬性裡
   - 每顆颱風都有五個分頁與摘要，概況裡的區塊順序正確
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import forecast as f  # noqa: E402
import generate_forecast_website as g  # noqa: E402

PANE_NOW = ['sat', 'ohc', 'shear', 'steer', 'jtwc', 'official', 'cities']
PANE_TRACK = ['cmp', 'maps', 'anim', 'tmap', 'trend']


def _i18n_dicts() -> tuple[set, set]:
    s = open(os.path.join(ROOT, 'generate_forecast_website.py'), encoding='utf-8').read()
    a = s.index('const I18N = {'); b = s.index('\n};', a)
    blk = s[a:b]
    en_i, zh_i = blk.index('  en: {'), blk.index('  zh: {')
    key = re.compile(r"^\s+'([^']+)':", re.M)
    return set(key.findall(blk[en_i:zh_i])), set(key.findall(blk[zh_i:]))


def check_html(html: str, docs: str, storms: list[dict]) -> list[str]:
    """回傳問題清單（空＝通過）。"""
    problems = []
    en, zh = _i18n_dicts()
    if en != zh:
        problems.append(f'i18n 鍵不一致：只在 en {sorted(en - zh)[:5]}，只在 zh {sorted(zh - en)[:5]}')
    dynamic = ('catname.', 'city.', 'score.tab.')          # 由資料決定、在字典裡用前綴展開的鍵
    for k in sorted(set(re.findall(r'<[^>]*\sdata-i18n="([^"]+)"', html))):   # 只看標籤，不看腳本註解
        if k not in en and not k.startswith(dynamic):
            problems.append(f'data-i18n="{k}" 不在字典裡')
    for m in re.finditer(r'(?:src|href)="([^"#?:]+\.(?:png|webp|jpg|gif|json|html))"', html):
        p = m.group(1)
        if not os.path.exists(os.path.join(docs, p)):
            problems.append(f'引用了不存在的檔案 {p}')
    for m in re.finditer(r'="(None|nan|undefined)"', html):
        problems.append(f'屬性值漏出 {m.group(0)} @{m.start()}')
    tids = sorted({s['track_id'] for s in storms})
    for tid in tids:
        if f'data-view="storm/{tid}"' not in html:
            problems.append(f'{tid} 沒有颱風頁'); continue
        v = html[html.index(f'data-view="storm/{tid}"'):]
        tabs = re.findall(rf'class="model-tab-btn storm-tab[^"]*" role="tab" aria-selected="(?:true|false)" data-track="{tid}-tabs" data-model="([^"]+)"', v)
        if tabs != ['now', 'track', 'strike', 'intensity', 'score'][:len(tabs)] or len(tabs) < 3:
            problems.append(f'{tid} 分頁不對：{tabs}')
        if 'class="storm-summary"' not in v:
            problems.append(f'{tid} 沒有白話摘要')
        for pid, want in (('now', PANE_NOW), ('track', PANE_TRACK)):
            m = re.search(rf'class="model-panel tab-pane" data-track="{tid}-tabs" data-model="{pid}"', v)
            if not m:
                continue
            n = re.search(r'class="model-panel tab-pane"', v[m.end():])
            got = re.findall(rf'id="sec-{tid}-(\w+)"', v[m.end():m.end() + (n.start() if n else len(v))])
            if [x for x in want if x in got] != got:
                problems.append(f'{tid} {pid} 區塊順序 {got}，應為 {want} 的子序列')
    return problems


def rebuild_from_docs(src_docs: str, out_docs: str) -> list[dict]:
    """用 docs/ 裡現有的產物重建 storms（與自動更新的結果相同），不跑預報、不下載。"""
    live = open(os.path.join(src_docs, 'index.html'), encoding='utf-8').read()
    site = json.loads(re.search(r'<script id="site-data" type="application/json">(.*?)</script>', live, re.S).group(1))
    globe = {s['id']: s for s in site['globe']['storms']}
    D = out_docs
    storms = []
    for tid, gs in globe.items():
        obs_csv = os.path.join(ROOT, 'docs', 'verification', 'obs', f'{tid}.csv')
        obs = open(obs_csv).read().strip().splitlines()[-1].split(',')[0] if os.path.exists(obs_csv) else '2026-01-01T00:00Z'
        jt = {'name': gs['name'], 'latitude': f"{gs['lat']}N", 'longitude': f"{gs['lon']}E", 'max_winds_kt': gs['kt'],
              'pressure_mb': None, 'update_time': f"{obs[8:10]}{obs[11:13]}{obs[14:16]}Z",
              'forecast_track': [[la, lo % 360, kt, tau] for la, lo, kt, tau in gs['track'][1:]]}
        group = []
        for cfg in f.MODEL_CONFIGS:
            pre = cfg['local_prefix']
            pre = '' if pre == 'WNC2-r2' else pre + '_'
            P = lambda name: (os.path.join(D, f'{pre}{tid}_{name}') if os.path.exists(os.path.join(D, f'{pre}{tid}_{name}')) else None)
            if not P('Forecast_Map.png'):
                continue
            ens, det = f._ens_name(cfg), cfg.get('det_name')
            group.append({'track_id': tid, 'model': cfg['display'], 'ens_name': ens,
                          'forecast_map_path': P('Forecast_Map.png'), 'forecast_map_history': [],
                          'strike_map_path': P('Strike_Probability.png'), 'plume_path': P('Intensity_Plume.png'),
                          'trend_path': P('Track_Trend.png'), 'det_trend_path': P('Det_Track_Trend.png'),
                          'det_name': det if P('Det_Track_Trend.png') else None,
                          'current_info': {'jtwc': jt}, 'frames_dir': os.path.join(D, f'animation_frames_{pre}{tid}')})
        if not group:
            continue
        head = group[0]
        L = lambda n: os.path.join(D, f'WNC2-1000_{tid}_{n}')
        head.update({
            'comparison_map_path': os.path.join(D, f'{tid}_Model_Comparison.png'),
            'strike_1000_path': L('Strike_Probability.png'), 'plume_1000_path': L('Intensity_Plume.png'),
            'strike_1000_extra': [(lbl, L(n)) for lbl, n in (('0–72 h', 'Strike_0_72h.png'), ('72–120 h', 'Strike_72_120h.png'),
                                                             ('120 h+', 'Strike_120_endh.png'), ('34 kt', 'Wind34_Probability.png'))],
            'ohc_path': os.path.join(D, 'WP_OHC.png'), 'shear_path': os.path.join(D, f'{tid}_Shear.png'),
            'steering_maps': [(f"+{int(re.search(r'_(\d+)h', p).group(1))} h", p) for p in sorted(glob.glob(os.path.join(D, 'WP_Steering_*h.png')))],
            'satellite_maps': [('Enhanced IR', os.path.join(D, f'satellite_frames_{tid}_IR')),
                               ('Grayscale IR', os.path.join(D, f'satellite_frames_{tid}_Gray'))],
            'tracks_json': os.path.join(D, f'{tid}_Tracks.json'),
        })
        off = os.path.join(D, f'{tid}_Official.png')
        jo = f._jtwc_official(head)
        if os.path.exists(off) and jo:
            head['official'] = {'path': off, 'forecasts': [jo]}
        storms += group
    card = f.compute_scorecard()
    for tid in {s['track_id'] for s in storms}:
        head = next(s for s in storms if s['track_id'] == tid)
        head['scorecard'], head['scorecard_all'] = card.get(tid, {}), card.get('_all', {})
    gen = [(os.path.basename(p)[len('WP_Genesis_Potential_'):-4] or 'WN2-C r2', p)
           for p in sorted(glob.glob(os.path.join(D, 'WP_Genesis_Potential*.png')))]
    g.generate_forecast_html(storms, os.path.join(D, 'index.html'), genesis_map_paths=gen)
    return storms


def main() -> int:
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        # 1. 沒有颱風
        empty = os.path.join(tmp, 'empty'); os.makedirs(empty)
        g.generate_forecast_html([], os.path.join(empty, 'index.html'), genesis_map_paths=[])
        h = open(os.path.join(empty, 'index.html'), encoding='utf-8').read()
        for marker in ('data-view="overview"', 'data-view="about"', 'id="site-data"'):   # 沒有潛勢圖時不會有生成潛勢頁
            if marker not in h:
                bad.append(f'[空站] 缺 {marker}')
        bad += [f'[空站] {p}' for p in check_html(h, empty, [])]

        # 2. 用 docs/ 重建目前的網站
        src = os.path.join(ROOT, 'docs')
        if os.path.exists(os.path.join(src, 'index.html')):
            out = os.path.join(tmp, 'docs')
            shutil.copytree(src, out, ignore=shutil.ignore_patterns('animation_frames_*', 'satellite_frames_*', 'verification'))
            # 動畫／衛星幀只要目錄存在、有一幀就夠（省時間）
            for d in glob.glob(os.path.join(src, '*_frames_*')):
                if os.path.isdir(d):
                    od = os.path.join(out, os.path.basename(d)); os.makedirs(od, exist_ok=True)
                    for fn in sorted(os.listdir(d))[:2]:
                        shutil.copy(os.path.join(d, fn), od)
            storms = rebuild_from_docs(src, out)
            h = open(os.path.join(out, 'index.html'), encoding='utf-8').read()
            bad += [f'[重建] {p}' for p in check_html(h, out, storms)]
            print(f'[TEST] 重建 {len({s["track_id"] for s in storms})} 顆颱風、{len(storms)} 個模式項目，頁面 {len(h) // 1024} KB')
    for p in bad:
        print('FAIL:', p)
    print('[TEST]', 'OK' if not bad else f'{len(bad)} 個問題')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
