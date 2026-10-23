# Pillar 熱帶氣旋預報系統 · Pillar's Tropical Cyclone Forecast

🌀 **網站：https://lkt0713.github.io/Typhoon-Forecast/**

西北太平洋颱風路徑預報站。彙整 AI 與物理模式的系集預報，與各國官方預報並列，每 10 分鐘在 GitHub Actions 上自動更新，電腦不用開。

## 網站內容

每個颱風頁由整體到細節：

- **衛星雲圖動畫**：向日葵 9 號 B13 紅外線最近 3 小時（每 10 分鐘一幀，共 18 幀），以颱風為中心，彩色強化與黑白兩個分頁，疊上路徑與 JTWC 預報
- **多模式比較**：各模式系集平均與決定報路徑畫在同一張圖
- **路徑動畫、系集路徑圖、互動地圖**：可逐一查看每個系集成員，或切換起報時間比較
- **各國官方預報比較**：JTWC、日本氣象廳（JMA）、中央氣象署（CWA）的路徑與強度並列，地圖標籤為預報的實際時間
- **侵襲機率**：區域、分時段、34 kt 暴風圈，以及登陸臺灣與各城市的機率
- **預報趨勢、強度預報**
- **海洋熱含量（OHC）**：由 CMEMS 1/12° 海洋分析計算熱帶氣旋熱潛能，並標出颱風目前位置
- **500 hPa 駛流場**：ECMWF HRES 流線與 5880 gpm 線，看太平洋高壓如何影響路徑
- **預報校驗成績單**：路徑誤差，以及沿路徑／跨路徑誤差與強度誤差

另外還有**生成潛勢**頁，以及保留過往颱風實際路徑與各模式預報表現的**歷史存檔**頁。網站可以加到手機主畫面當 App 使用，分享到 LINE、Facebook 時會顯示最新預報圖的預覽卡片。

## 資料來源

| 類別 | 來源 |
|---|---|
| AI 系集 | Google DeepMind WeatherNext（WN3-C、WN2-C r2、WN2-C r1、WN2-C 1000、GENC） |
| ECMWF | Open Data：AIFS-ENS + AIFS-single、IFS ENS + HRES（含 500 hPa 駛流場） |
| NOAA | NCEP：AIGEFS + AIGFS、GEFS + GFS |
| 官方預報 | JTWC、日本氣象廳、中央氣象署（氣象資料開放平臺 W-C0034-005） |
| 海洋熱含量 | Copernicus Marine（CMEMS），備援為 HYCOM |
| 衛星雲圖 | 向日葵 9 號 L1b 原始資料（NOAA Open Data，AWS `noaa-himawari9`，不需帳號） |

## 運作方式

`.github/workflows/auto-update.yml` 每輪執行 `forecast.py` 下載資料、畫圖，並用 `generate_forecast_website.py` 產生 `docs/` 裡的網站，再發布到 GitHub Pages。每輪結束約 10 分鐘後自動接下一輪，排程（每小時 :13、:43）作為備援，`watchdog.yml` 會取消卡住超過一小時的執行。

| 檔案 | 用途 |
|---|---|
| `forecast.py` | 主程式：下載、追蹤配對、繪圖、校驗、官方預報、衛星雲圖、海洋熱含量、駛流場 |
| `generate_forecast_website.py` | 產生網站（`docs/index.html`、分享預覽圖、App 圖示） |
| `official.py` | 讀取日本氣象廳與中央氣象署的颱風預報 |
| `satellite.py` | 下載並解讀向日葵 9 號 B13 原始檔（HSD），裁出颱風附近的亮度溫度 |
| `ohc.py` | 由 CMEMS／HYCOM 水溫剖面計算熱帶氣旋熱潛能 |
| `ecmwf_steering.py` | 下載 ECMWF 500 hPa 高度與風場 |

需要的 GitHub Actions secrets：`CWA_API_KEY`（中央氣象署）、`COPERNICUSMARINE_SERVICE_USERNAME`、`COPERNICUSMARINE_SERVICE_PASSWORD`（CMEMS）。沒有設定時，官方預報只顯示 JTWC 與日本氣象廳，海洋熱含量改用 HYCOM。

## 注意

本站僅供參考，不可作為作業依據；官方警報請以各國氣象單位發布為準。網站上的「機率」是系集成員中有多少比例這樣預報，代表模式之間的一致程度，不是官方的機率預報。
