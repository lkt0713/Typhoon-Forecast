# Pillar 熱帶氣旋預報系統 · Pillar's Tropical Cyclone Forecast

🌀 **網站：https://lkt0713.github.io/Typhoon-Forecast/**

西北太平洋颱風路徑預報站。彙整 AI 與物理模式的系集預報，與各國官方預報並列，每 10–15 分鐘在 GitHub Actions 上自動更新，電腦不用開。

## 網站內容

**颱風頁最上面**是颱風卡片和互動地圖並排（手機上卡片在上、地圖在下）：

- **颱風卡片**：目前風速、氣壓、位置；白話摘要（往哪走、會變強還是變弱）；登陸臺灣與沖繩／東京的侵襲機率（哪個模式最高、幾個模式同意）；跟上一報比變了什麼、各模式的共識與離群值、目前校驗最準的模式
- **互動地圖**：所有模式的平均路徑，有勾選的模式都會畫出系集成員；時間軸可以拖曳或播放，路徑只畫到所選時數（之後用虛線），並標出每個成員當時的位置與涵蓋 67% 成員的範圍；可切換起報時間，或改看單一模式

下面分成五個分頁。分頁列上的「區塊」選單可以直接跳到某一區，「模式」選單可以一次把所有圖切到同一個模式：

- **概況**
  - **衛星雲圖動畫**：向日葵 9 號 B13 紅外線最近 3 小時（每 10 分鐘一幀，共 18 幀），以颱風為中心，彩色強化與黑白兩種
  - **環境**（三張點開才展開的小卡）
    - **海洋熱含量（OHC）**：由 CMEMS 1/12° 海洋分析計算熱帶氣旋熱潛能，疊上已走過的路徑與 JTWC 預報路徑；另有沿 JTWC 預報路徑每 6 小時取樣的熱含量
    - **垂直風切**：AIFS-single 200–850 hPa 風切，取中心外 200–800 km 平均（SHIPS 的定義），沿 AIFS 路徑每 6 小時一點到 120 小時
    - **500 hPa 駛流場**：AIFS-single 流線、風速與 5880 gpm 線，疊上同一期 AIFS 路徑
  - **JTWC 官方預報**與**各國官方預報比較**：JTWC、日本氣象廳（JMA）、中央氣象署（CWA）的路徑與強度並列
  - **登陸臺灣與城市侵襲機率**
  - **臺灣各縣市**：各模式中心經過每個縣市 110 公里內的機率，以及中心在附近的時間窗
- **路徑**：多模式比較、0～120 小時系集路徑圖、完整系集路徑圖（可切換起報時間）、路徑動畫、預報趨勢；可下載平均路徑（CSV、GeoJSON）
- **侵襲**：仿 JTWC 警報圖的暴風圈預報（WeatherNext、ECMWF、NOAA 系集，34／50／64 kt）、侵襲機率、分時段與 34 kt 暴風圈機率，以及**指定地點的風險**（用你的位置或任一地點，在瀏覽器內計算，位置不會送出）
- **強度**：各模式強度預報，以及扣掉該模式本季平均偏差的**偏差修正強度**
- **校驗**：路徑誤差、沿路徑／跨路徑誤差與強度誤差（這顆颱風與所有颱風、同質與全部樣本），折線圖預設突顯最準的三個模式；可下載校驗表（CSV）

其他頁面：

- **總覽**：目前追蹤的颱風與重點數字
- **生成潛勢**：各模式的系集生成訊號
- **歷史**：每顆颱風的實際路徑、各報預報、成績單（颱風結束後自動產生的排名圖）與資料下載；「本季至今」有所有颱風合計的校驗、依情境拆開的校驗（轉向前／後、起報時強度），以及生成訊號對照（1000 成員系集的生成群 vs 實際生成的颱風）
- **說明**：各分頁的內容、強度分級、更新內容（點頁首的版本號會直接跳過去；資料在 `generate_forecast_website.py` 的 `CHANGELOG`，改版號時一併補上）

**通知**：每次更新會記錄新系統、命名、強度分級變化、預報路徑大幅移動（150 公里以上）、登陸臺灣機率變動（10 個百分點以上）等事件，可用 RSS（[`feed.xml`](https://lkt0713.github.io/Typhoon-Forecast/feed.xml)）或 JSON Feed（[`feed.json`](https://lkt0713.github.io/Typhoon-Forecast/feed.json)）訂閱；設定 `NTFY_TOPIC` 後也會推播到 [ntfy](https://ntfy.sh) 的該主題。

網站可以加到手機主畫面當 App 使用，離線時也能開啟最後一次更新的文字與資料（圖片不存快取，連線時一律顯示最新的）；分享到 LINE、Facebook 時會顯示最新預報圖的預覽卡片。介面有中文／英文、深色／淺色主題，時間可切換 UTC 或臺灣時間。

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
| `generate_forecast_website.py` | 產生網站（`docs/index.html`、樣式與腳本、點開才載入的片段、資料下載檔、通知 feed、離線用的 service worker、分享預覽圖、App 圖示） |
| `ecmwf_bufr.py` | 把 ECMWF Open Data 的熱帶氣旋路徑 BUFR（IFS ENS／HRES、AIFS）轉成專案的路徑格式，含暴風圈半徑 |
| `noaa_atcf.py` | 把 NCEP 的 ATCF 路徑（AIGEFS／AIGFS、GEFS／GFS）轉成專案的路徑格式，含暴風圈半徑 |
| `official.py` | 讀取日本氣象廳與中央氣象署的颱風預報 |
| `satellite.py` | 下載並解讀向日葵 9 號 B13 原始檔（HSD），裁出颱風附近的亮度溫度 |
| `ohc.py` | 由 CMEMS／HYCOM 水溫剖面計算熱帶氣旋熱潛能 |
| `ecmwf_steering.py` | 下載 AIFS-single 500 hPa 高度與風場（駛流場） |
| `ecmwf_shear.py` | 下載 AIFS-single 200／850 hPa 風場，沿路徑計算垂直風切 |

需要的 GitHub Actions secrets：`CWA_API_KEY`（中央氣象署）、`COPERNICUSMARINE_SERVICE_USERNAME`、`COPERNICUSMARINE_SERVICE_PASSWORD`（CMEMS）。沒有設定時，官方預報只顯示 JTWC 與日本氣象廳，海洋熱含量改用 HYCOM。

選用的 secret：`NTFY_TOPIC`（ntfy.sh 的主題名稱）。設定後，每次更新發現的新事件會推播到該主題，在 ntfy app 訂閱同一個主題就會收到通知；沒有設定就不會發送。

`tests/test_site.py` 是不需下載資料的建站測試（`.github/workflows/ci.yml` 在每個 PR 上執行）。

## 注意

本站僅供參考，不可作為作業依據；官方警報請以各國氣象單位發布為準。網站上的「機率」是系集成員中有多少比例這樣預報，代表模式之間的一致程度，不是官方的機率預報。
