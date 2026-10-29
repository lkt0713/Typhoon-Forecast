
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
    'cl.title':         'What’s new',
    'cl.version':       'Version',
    'cl.history':       'Version history',
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
    'cl.title':         '更新內容',
    'cl.version':       '版本',
    'cl.history':       '版本紀錄',
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
    // 頁首版本號 → 說明頁的「更新內容」：先換頁（連結本身處理），換好再捲過去
    const go = e.target.closest('[data-goto]');
    if (go) {
        const id = go.dataset.goto, wait = currentRoute === 'about' ? 0 : 380;
        setTimeout(() => {
            const el = document.getElementById(id);
            if (el) el.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'start' });
        }, wait);
    }
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
