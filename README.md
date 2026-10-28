# Pillar 熱帶氣旋預報系統 · Pillar's Tropical Cyclone Forecast

🌀 **網站：https://lkt0713.github.io/Typhoon-Forecast/**

西北太平洋颱風路徑預報站。彙整 AI 與物理模式的系集預報，與各國官方預報並列，每 10–15 分鐘在 GitHub Actions 上自動更新，電腦不用開。

## 網站內容

每個颱風頁上方是白話摘要（往哪走、會變強還是變弱、臺灣有沒有威脅）與目前強度，下面分成五個分頁，最上方的模式選單可以一次把所有圖切到同一個模式：

- **概況**
  - **衛星雲圖動畫**：向日葵 9 號 B13 紅外線最近 3 小時（每 10 分鐘一幀，共 18 幀），以颱風為中心、只標名字，彩色強化與黑白兩種
  - **海洋熱含量（OHC）**：由 CMEMS 1/12° 海洋分析計算熱帶氣旋熱潛能，疊上颱風已走過的路徑與 JTWC 預報路徑
  - **沿 JTWC 路徑的海洋熱含量**：沿 JTWC 最新預報路徑每 6 小時取樣颱風中心底下的熱含量，看颱風接下來會遇到多暖的海
  - **沿 AIFS 路徑的垂直風切**：AIFS-single 200–850 hPa 風切，取中心外 200–800 km 平均（SHIPS 的定義），每 6 小時一點到 120 小時
  - **500 hPa 駛流場**：AIFS-single 流線、風速與 5880 gpm 線，疊上同一期 AIFS 路徑，看太平洋高壓如何影響路徑
  - **JTWC 官方預報**：JTWC 原始預報圖
  - **各國官方預報比較**：JTWC、日本氣象廳（JMA）、中央氣象署（CWA）的路徑與強度並列
  - **登陸臺灣與城市侵襲機率**
- **路徑**：多模式比較、系集路徑圖（可切換起報時間）、路徑動畫、互動地圖（可逐一查看系集成員）、預報趨勢
- **侵襲**：侵襲機率，以及分時段與 34 kt 暴風圈機率
- **強度**：各模式強度預報
- **校驗**：路徑誤差，以及沿路徑／跨路徑誤差與強度誤差（這顆颱風與所有颱風、同質與全部樣本）

另外還有**生成潛勢**頁，以及保留過往颱風實際路徑與各模式預報表現的**歷史存檔**頁。網站可以加到手機主畫面當 App 使用，分享到 LINE、Facebook 時會顯示最新預報圖的預覽卡片。

## 資料來源

| 類別 | 來源 |
|---|---|
| AI 系集 | Google DeepMind WeatherNext（WN3-C、WN2-C r2、WN2-C r1、WN2-C 1000、GENC） |
| ECMWF | Open Data：AIFS-ENS + AIFS-single、IFS ENS + HRES；AIFS-single 的 500 hPa 駛流場與 200／850 hPa 風切 |
| NOAA | NCEP：AIGEFS + AIGFS、GEFS + GFS |
| 官方預報 | JTWC、日本氣象廳、中央氣象署（氣象資料開放平臺 W-C0034-005） |
| 海洋熱含量 | Copernicus Marine（CMEMS），備援為 HYCOM |
| 衛星雲圖 | 向日葵 9 號 L1b 原始資料（NOAA Open Data，AWS `noaa-himawari9`，不需帳號） |

## 運作方式

`.github/workflows/auto-update.yml` 每輪執行 `forecast.py` 下載資料、畫圖，並用 `generate_forecast_website.py` 產生 `docs/` 裡的網站，再發布到 GitHub Pages。每輪結束約 10 分鐘後自動接下一輪，排程（每小時 :13、:43）作為備援，`watchdog.yml` 會取消卡住超過一小時的執行。

| 檔案 | 用途 |
|---|---|
| `forecast.py` | 主程式：下載、追蹤配對、繪圖、校驗、官方預報、衛星雲圖、海洋熱含量、垂直風切、駛流場 |
| `generate_forecast_website.py` | 產生網站（`docs/index.html`、分享預覽圖、App 圖示） |
| `official.py` | 讀取日本氣象廳與中央氣象署的颱風預報 |
| `satellite.py` | 下載並解讀向日葵 9 號 B13 原始檔（HSD），裁出颱風附近的亮度溫度 |
| `ohc.py` | 由 CMEMS／HYCOM 水溫剖面計算熱帶氣旋熱潛能 |
| `ecmwf_steering.py` | 下載 AIFS-single 500 hPa 高度與風場（駛流場） |
| `ecmwf_shear.py` | 下載 AIFS-single 200／850 hPa 風場，沿路徑計算垂直風切 |

需要的 GitHub Actions secrets：`CWA_API_KEY`（中央氣象署）、`COPERNICUSMARINE_SERVICE_USERNAME`、`COPERNICUSMARINE_SERVICE_PASSWORD`（CMEMS）。沒有設定時，官方預報只顯示 JTWC 與日本氣象廳，海洋熱含量改用 HYCOM。

## 注意

本站僅供參考，不可作為作業依據；官方警報請以各國氣象單位發布為準。網站上的「機率」是系集成員中有多少比例這樣預報，代表模式之間的一致程度，不是官方的機率預報。
