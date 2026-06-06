# 把 ETF 系統當成「應用程式」使用 / 打包

這個 `app/` 資料夾把專案包成像應用程式那樣：可整包傳、有桌面圖示、可雙擊啟動網頁版。

| 檔案 | 用途 |
|---|---|
| `etf_icon.ico` / `etf_icon.png` | 應用程式圖示（藍底 + ETF + 上升長條） |
| `啟動_ETF.bat` | **雙擊即啟動**網頁版（最簡單，免建置） |
| `build_exe.py` | 用 PyInstaller 產生 `dist/ETF偏好投組.exe`（帶圖示） |
| `_launcher_bootstrap.py` | exe 的小型啟動器原始碼（被 build_exe.py 使用） |
| `建立桌面捷徑.ps1` | 在**桌面建立帶圖示的捷徑** |
| `打包成zip.ps1` | 把整個專案壓成一個可傳送的 zip（排除大型模型/快取） |

| `setup_and_run.py` | 啟動前自動檢查並 `pip install` 缺的相依套件，再啟動網頁 |

---

## 相依套件：會自動安裝（免手動）
雙擊啟動時（.bat 或 exe）會先**自動偵測缺哪些套件**，缺了就自動 `pip install -r requirements.txt`，然後啟動。
- 只有「偵測到缺套件」才會安裝 → **裝過之後再開都很快**；第一次會花幾分鐘裝套件。
- 首次啟動也會自動下載文字編碼模型 BGE-M3（約 2.2GB，需聯網一次）與 FinBERT；之後離線可用。
- 仍可手動先裝：`pip install -r requirements.txt`（可選）。
> 前提：電腦要先有 **Python**（建議 3.10）。自動安裝的是「Python 套件」，不是 Python 本身。

## 方式 A（最簡單）：雙擊 .bat
直接雙擊 `app\啟動_ETF.bat` → 載入模型後瀏覽器自動開 `http://127.0.0.1:8050`。
要關閉就關掉那個黑色視窗。

## 方式 B：做一個真正的 .exe（雙擊直接跑）
```bat
pip install pyinstaller
python app\build_exe.py
```
產生 `dist\ETF偏好投組.exe`（帶圖示）。把它複製回 `app\` 後雙擊即可。
> 此 exe 是「啟動器」：很小、可隨整包傳，但**執行的電腦仍需裝 Python 與上面的相依套件**。

## 桌面捷徑（圖示）
```bat
powershell -ExecutionPolicy Bypass -File app\建立桌面捷徑.ps1
```
會在桌面建立「ETF 偏好投組」捷徑：若已建好 exe 就指向 exe，否則指向 `.bat`，並套用 `etf_icon.ico`。
之後雙擊桌面圖示就像開應用程式一樣。

## 整包傳給別人
```bat
powershell -ExecutionPolicy Bypass -File app\打包成zip.ps1
```
會在桌面產生 `ETF偏好投組_<時間>.zip`（已排除 `.git`、`__pycache__`、`encoder_model`（2.2GB 模型）、`dist`、回測報表、log 等）。
對方解壓後：① `pip install -r requirements.txt` ② 雙擊 `app\啟動_ETF.bat`（或 `python app\build_exe.py` 做 exe）。模型會在對方第一次執行時自動下載。

---

## 進階：完全免裝 Python 的「單機資料夾」（體積大，但對方零安裝）
若要對方**完全不用裝 Python/套件**，用 `app/etf_app.spec`（已備妥）把整個網頁版連同 torch、transformers、sentence-transformers、scipy、flask… 一起凍結成 **onedir 資料夾**：
```bat
pip install pyinstaller
:: 建議輸出到 OneDrive 以外的路徑（避免同步卡住），例如 C:\etf_build
pyinstaller app\etf_app.spec --noconfirm --distpath C:\etf_build\dist --workpath C:\etf_build\build
```
產出 `C:\etf_build\dist\ETF偏好投組\`（整個資料夾，約 **3–5GB**）。把**整個資料夾**壓縮傳給對方，對方解壓後**雙擊裡面的 `ETF偏好投組.exe`** 即可，**完全不用裝 Python**。
- 模型 BGE-M3／FinBERT 仍會在「首次執行」自動下載（需聯網一次）。
- 體積大、且 PyInstaller 偶爾需要補 hidden import；故平常交付建議用上面的「啟動器 exe／.bat ＋ 整包 zip」（小、夠用）；這個 onedir 版適合「對方完全不能裝 Python」時。
