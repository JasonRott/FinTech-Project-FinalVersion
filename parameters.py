# ==========================================
# 參數設定區
# ==========================================
import os
from dotenv import load_dotenv

load_dotenv()

CSV_UNIVERSE_FILE = "csv\\all_etfs.csv"       # 步驟一產生的全市場排序清單
YQ_OUTPUT_FILE = "csv\\stage0_yq_features.csv" # YQ 財務特徵的輸出檔案
AV_DB_FILE = "json\\etf_database.json"         # AV 分散度特徵的本地資料庫
AV_API_KEY = os.getenv("AV_API_KEY", "")
AV_MAX_CALLS_PER_DAY = 25                # AV 每日安全呼叫上限
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TOP_N_ETFS = 500                         # 我們要送入 DEA 模型的候選數量
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")  # 請填入你的 Finnhub API Key
OUTPUT_FILE = "csv\\stage0_final_matrix.csv" # 最終多維度特徵矩陣的輸出檔案
USE_TRUE_HHI_OPTIMIZATION = True # 是否使用真正的 HHI 最小化優化（會增加計算時間），否則使用近似方法
ALPHA_BASELINE = 0.0 # 基線模型的 alpha 預期值 (可以根據歷史數據調整)
BASELINE_WEIGHTS = { # 專家先驗權重矩陣 (總和必須為 1.0)
    "Return_CAGR": 0.23,
    "Return_Div": 0.10,
    "Risk_Vol": 0.10,
    "Risk_MaxDD": 0.12,
    "Cost_ExpRatio": 0.15,
    "Liq_Volume": 0.05,
    "Liq_AUM": 0.05,
    "Div_Score": 0.15,
    "FinBERT_score": 0.0
}
MAX_WEIGHT_LIMIT = 0.40 # 單一標的最大權重限制 (40%)

# ==========================================
# 演算法升級：兩臂賽馬（Arm A vs Arm B）
# ==========================================
# Arm A = 現況線性加權偏好分數（baseline）；Arm B = 真實期望報酬 + 風險預算（U-1 + U-2）。
# 主系統 Stage 3 與回測引擎讀同一個開關，確保兩者永遠用同一臂、維持一致性。
OPTIMIZATION_ARM = "C2"         # ★生產預設 = C2（profile-dependent 三核心,2026-06-05 定案）★
                                # "A"舊線性加權 / "B"mean-variance / "C"最小變異+傾斜 / "C2"三核心(minvar/market/beta,由 g(w)選) / "BL"統一(BL 理論地基,消融對照)
RISK_AVERSION_LAMBDA = 2.0      # Arm B：U = w·μ_total − (λ/2)·wᵀΣw 的風險趨避係數，之後可依使用者風格調整
RISK_BUDGET_VOL = 0.30          # Arm B/C：投組年化波動上限約束（成長型放寬、保守型收緊）
DEA_TOP_FRACTION = 0.25         # DEA 候選池改用「取前 25%」百分位門檻，取代絕對 0.80
USE_LEDOIT_WOLF_COV = True      # 最佳化器共變異數改用 Ledoit-Wolf 收縮估計（降低估計誤差）
USE_MEAN_SHRINKAGE = True       # Arm B：對資本利得樣本平均報酬做收縮（降低均值估計雜訊）
MEAN_SHRINKAGE_INTENSITY = 0.5  # 收縮強度 δ∈[0,1]：0=純樣本平均，1=完全用橫斷面總平均
# --- Arm C：最小變異核心 + 排名式偏好傾斜 ---
TILT_STRENGTH = 0.1             # Arm C：偏好傾斜強度 τ（min ½wᵀΣw − τ·wᵀs）；τ=0 純最小變異
TILT_INCLUDE_CAGR = False       # Arm C/C2：傾斜目標 s 是否含資本利得排名（True=s_full，False=s_noCAGR）。
                                # ★可切換旗標，不強制單一預設★（使用者 2026-06-05 決議）：跨規制是 wash
                                # （Exp3，見 06 §6.6），依 profile/情境選用。nominal 值留 False；
                                # 未來可考慮讓 g(w) 依 profile 自動選 s 版本（如 core_mode 那樣 profile-dependent）。
USE_QUALITY_CONSTRAINTS = True  # 品質約束總開關（Arm C/C2）
# --- 品質約束系統化框架（2026-06-05，取代魔術數字；設計見 07）---
# 門檻 = 放在「該維度當期候選池可行範圍 [v_min,v_max]」內，位置由偏好權重決定（恆可行）。
# tightness 中性點 = 該使用者品質維度平均權重；fully tight at FULL_RATIO×平均。
QUALITY_TIGHTNESS_FULL_RATIO = 2.0
# 逐維度開關（OAT：一次開一個、各自驗證 OOS）。順序：成本→HHI→流動性→情緒。
QC_ENABLE_COST = False          # OAT-1 結論：硬成本約束有害或無用 → 不採用（成本已在軟傾斜+DEA）。見 02。
QC_ENABLE_HHI = False           # OAT-2：分散 HHI 上限（測試中）
QC_ENABLE_LIQ = False           # OAT-3：合併流動性下限
QC_ENABLE_SENT = False          # OAT-4：情緒下限（FinBERT 資料不穩，謹慎/可能保持關閉）
# 舊魔術數字（已棄用，新框架不使用；保留供參考）
COST_BUDGET_QUANTILE = 0.75     # [DEPRECATED]
HHI_CEILING = 0.50              # [DEPRECATED]

# ==========================================
# 偏好→參數映射 g(w)（U-C2 前置：把 τ / 風險預算 / 核心類型變成權重向量的連續函數）
# ==========================================
# 目的：不用 profile 名稱查表，而用 9 維全局權重的函數推導參數，讓 AHP 任意權重與手設
# profile 走同一條路、自動校準（見 05 §4.57）。derive_params_from_weights() 在
# functions.py 與 backtest_engine.py 各實作一份，數值必須完全一致。
USE_PREF_PARAM_MAPPING = False  # True 時 Arm C/C2 改用 g(w) 推導 τ 與 vol_budget（取代固定值）
# 核心類型門檻（依風險容忍 T 切換）：T<低門檻=最小變異；中間=市場追蹤；≥高門檻=beta 曝險
CORE_MODE_T_LOW = 0.40
CORE_MODE_T_HIGH = 0.65
# 風險預算映射（legacy 絕對值，C/C2 已改用下方 risk_fraction 相對可行範圍；保留供記錄/log）
VOL_BUDGET_BASE = 0.10
VOL_BUDGET_SLOPE = 0.40
VOL_BUDGET_MIN = 0.10
VOL_BUDGET_MAX = 0.45
# 傾斜強度映射 τ = 係數·(1−T)·R_hat（報酬導向 T 高 → τ 趨近 0；保守 → τ 大）
TAU_MAP_COEF = 0.30
# --- C2 風險預算：相對候選池「可行波動範圍」（取代絕對 vol_budget）---
# g(w) 輸出無量綱 risk_fraction∈[0,1]；求解器算 v_min(最小變異波動)、v_max(最大變異波動)，
# vol_budget = v_min + risk_fraction·(v_max−v_min)。恆可行（≥v_min，永不無解）且不脫離當期池子。
RISK_FRACTION_MIN = 0.05        # risk_fraction 下限（避免恰好貼 v_min）
RISK_FRACTION_MAX = 0.95        # risk_fraction 上限。
                                # 註：2026-06-05 曾試降到 0.60(以為能避回撤),但驗證(_rf_cap)顯示
                                # 封頂反而 CAGR↓、回撤更深、Sharpe 略↓(vol約束≠回撤控制)→ 還原 0.95。
                                # 結論:報酬導向高 rf=最大絕對報酬,低 Sharpe 是低波動異常的本質代價,無免費修法。見 02。
RISK_FRACTION_OVERRIDE = None   # 非 None 時直接用此值當 risk_fraction（實驗掃描用，繞過 g(w) 映射）
# C2 的 beta/市場核心「市場錨」可與「報告基準」解耦：
# 報告基準（DEFAULT_BENCHMARK_TICKER，目前 VT）= 報表比較對象；
# beta 錨（BETA_ANCHOR_TICKER）= beta 核心 max wᵀβ、市場核心追蹤誤差所用的 r_anchor。
# None = 沿用報告基準。實驗：設 "VTI"（整體美國市場）看報酬導向 vs 保守的價差是否拉開。
BETA_ANCHOR_TICKER = None

# ==========================================
# 偏好分數「報酬維度」的評分基礎（2026-06-05 實驗）
# ==========================================
# 問題：報酬維度用「過去 CAGR 排名」衡量，不持續（V-1 r≈0）→ 報酬導向使用者的事後偏好分數
# 贏不過 VT（win_VT 低）。改用「beta（系統性風險曝險）」這個會持續、且 beta 核心真的交付的訊號：
#   報酬分數 = clip(beta_vs_anchor / PREF_BETA_REF, 0, 1)
# VT 的 beta=1 → 0.5；高 beta 投組 >0.5 → 結構上每期都贏 VT 的報酬維度 → win_VT 應衝高。
# ★只影響「評估/偏好分數(win_VT)」，不動最佳化器的傾斜 s★（乾淨 A/B 測試）。
PREF_RETURN_BASIS = "beta"      # "cagr"（過去 CAGR 排名）/ "beta"（系統性風險曝險，2026-06-05 採用為預設）
PREF_BETA_REF = 2.0             # beta 參考值：報酬分數 = 0.5 + 0.5·clip((beta−1)/(REF−1),0,1)
                                # 市場 beta=1 → 0.5；低於市場 → 0.5(不懲罰)；beta=REF → 1.0。

# ==========================================
# 偏好分數：資本利得成長獎勵（展示/評估層，2026-06-05）
# ==========================================
# 問題：Norm_Return_CAGR 的 winsorize 上界 p99 會把極端高成長砍平到同一個 1.0（見 02 結構分析）。
# 放寬上界讓「更高的資本利得 → 更高分數」，使偏好分數忠實代表成長型使用者的訴求（V-1/V-6 招牌）。
# ★只影響展示/評估分數★：最佳化器為 noCAGR，s_noCAGR 中 Norm_Return_CAGR 代數上完全抵消，不受影響。
# 僅改 CAGR 一維（Div 等若改會經 s_noCAGR 漏進最佳化器，故不動）。
PREF_SCORE_CAGR_UPPER_Q = 0.999  # CAGR 正規化上尾 winsorize 分位（原 0.99；提高=更不砍平高成長）

# ==========================================
# 多 profile 使用者偏好原型（9 維全局權重，各自總和=1.0）
# ==========================================
# 用途：對不同風格使用者各跑 τ sweep，檢驗「財務 vs 偏好 trade-off」如何隨 profile 改變
#（避免只用單一 return-leaning 使用者校準而失真）。這是直接指定的全局權重，
# 供 profile 實驗使用（繞過 AHP 成對比較；AHP 只是產生權重的其中一種方式）。
# 維度順序：Return_CAGR, Return_Div, Risk_Vol, Risk_MaxDD, Cost_ExpRatio,
#           Liq_Volume, Liq_AUM, Div_Score, FinBERT_score
USER_PROFILES = {
    # 1. 積極成長：純資本利得導向、低風險趨避
    "aggressive_growth": {
        "Return_CAGR": 0.55, "Return_Div": 0.00, "Risk_Vol": 0.05, "Risk_MaxDD": 0.05,
        "Cost_ExpRatio": 0.05, "Liq_Volume": 0.05, "Liq_AUM": 0.05, "Div_Score": 0.10, "FinBERT_score": 0.10,
    },
    # 2. 報酬導向（現行 Neutral_user，偏報酬）
    "return_leaning": {
        "Return_CAGR": 0.40, "Return_Div": 0.10, "Risk_Vol": 0.14, "Risk_MaxDD": 0.06,
        "Cost_ExpRatio": 0.10, "Liq_Volume": 0.04, "Liq_AUM": 0.04, "Div_Score": 0.07, "FinBERT_score": 0.05,
    },
    # 3. 平衡型
    "balanced": {
        "Return_CAGR": 0.22, "Return_Div": 0.13, "Risk_Vol": 0.15, "Risk_MaxDD": 0.12,
        "Cost_ExpRatio": 0.10, "Liq_Volume": 0.05, "Liq_AUM": 0.05, "Div_Score": 0.13, "FinBERT_score": 0.05,
    },
    # 4. 保守型 / 資本保全：高風險趨避
    "conservative": {
        "Return_CAGR": 0.08, "Return_Div": 0.12, "Risk_Vol": 0.28, "Risk_MaxDD": 0.22,
        "Cost_ExpRatio": 0.10, "Liq_Volume": 0.04, "Liq_AUM": 0.06, "Div_Score": 0.08, "FinBERT_score": 0.02,
    },
    # 5. 收入型 / 高股息
    "income": {
        "Return_CAGR": 0.10, "Return_Div": 0.40, "Risk_Vol": 0.12, "Risk_MaxDD": 0.10,
        "Cost_ExpRatio": 0.10, "Liq_Volume": 0.03, "Liq_AUM": 0.05, "Div_Score": 0.08, "FinBERT_score": 0.02,
    },
    # 6. 成本/流動性敏感（被動/機構型）
    "cost_liquidity": {
        "Return_CAGR": 0.18, "Return_Div": 0.10, "Risk_Vol": 0.12, "Risk_MaxDD": 0.08,
        "Cost_ExpRatio": 0.22, "Liq_Volume": 0.12, "Liq_AUM": 0.10, "Div_Score": 0.06, "FinBERT_score": 0.02,
    },
    # 7. 分散/情緒導向（品質/ESG-ish）
    "diversified_quality": {
        "Return_CAGR": 0.15, "Return_Div": 0.10, "Risk_Vol": 0.12, "Risk_MaxDD": 0.10,
        "Cost_ExpRatio": 0.08, "Liq_Volume": 0.04, "Liq_AUM": 0.06, "Div_Score": 0.20, "FinBERT_score": 0.15,
    },
}

CASE_NAME = "Neutral_user" # 預設情境名稱
# 使用者結果總資料夾：主系統與回測「每次執行」各開一個含全部圖表+報表的時間戳子資料夾。
USER_RESULTS_DIR = "user_results"
VERBOSE = True # 是否輸出詳細的運算過程訊息 True (Verbose 模式) -> 顯示普通資訊與除錯訊息，False (Silence 模式) -> 只顯示警告與錯誤
DETERMINISTIC_AHP_WEIGHTS = True # 這裡可以切換是否使用確定性模擬結果, 若想讓教授體驗互動問卷，可以改成 DETERMINISTIC_AHP_WEIGHTS=False

# AHP 尺度提醒：
# 1.0 = 兩者同等重要
# 3.0 = 前者稍微重要 | 1/3 = 後者稍微重要
# 5.0 = 前者明顯重要 | 1/5 = 後者明顯重要
# 7.0 = 前者強烈重要 | 1/7 = 後者強烈重要
# 9.0 = 前者極端重要 | 1/9 = 後者極端重要
DETERMINISTIC_USER_INPUTS = {
    "Main": [2.5, 5.0, 6.25, 7.1429, 10.0, 2.0, 2.5, 2.8571, 4.0, 1.25, 1.4286, 2.0, 1.1429, 1.6, 1.4],
    "Sub": {'Return_Main': [4.0], 'Risk_Main': [2.3333], 'Liquidity_Main': [1.0]}
}
'''
DETERMINISTIC_USER_INPUTS = {
    "Main": [
        # --- [0] 報酬 (Return) vs 其他 ---
        1.0,  # 0:  報酬 vs 風險 (Risk)
        1.0,  # 1:  報酬 vs 成本 (Cost)
        1.0,  # 2:  報酬 vs 流動性 (Liquidity)
        1.0,  # 3:  報酬 vs 產業分散 (Diversity)
        1.0,  # 4:  報酬 vs 市場情緒 (Sentiment)

        # --- [1] 風險 (Risk) vs 其他 ---
        1.0,  # 5:  風險 vs 成本
        1.0,  # 6:  風險 vs 流動性
        1.0,  # 7:  風險 vs 產業分散
        1.0,  # 8:  風險 vs 市場情緒

        # --- [2] 成本 (Cost) vs 其他 ---
        1.0,  # 9:  成本 vs 流動性
        1.0,  # 10: 成本 vs 產業分散
        1.0,  # 11: 成本 vs 市場情緒

        # --- [3] 流動性 (Liquidity) vs 其他 ---
        1.0,  # 12: 流動性 vs 產業分散
        1.0,  # 13: 流動性 vs 市場情緒

        # --- [4] 產業分散 (Diversity) vs 其他 ---
        1.0   # 14: 產業分散 vs 市場情緒
    ],
    
    "Sub": {
        # 歷史報酬 (CAGR) vs 殖利率 (Div)
        "Return_Main": [1.0],     
        
        # 抗波動 (Vol) vs 抗回撤 (MaxDD)
        "Risk_Main": [1.0],       
        
        # 交易量 (Volume) vs 資產規模 (AUM)
        "Liquidity_Main": [1.0]   
    }
}
'''