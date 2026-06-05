# -*- coding: utf-8 -*-
"""驗證主系統 Stage 3 的 beta 展示分數同步：
- beta 路徑能跑完不崩(beta_score_vec 計算、抓 VT、評分)。
- pref_utility_score 在 cagr vs beta 應「不同」(展示層改了)。
- 求解器投組相同是結構保證(objective_function 用 calc_utility(w) 不帶 for_display)，此處不重複驗。
"""
import io, contextlib, glob, os
import pandas as pd
import parameters, functions

def run_and_grab(basis):
    parameters.PREF_RETURN_BASIS = basis
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        functions.run_stage3_pipeline()
    out = buf.getvalue()
    score = None
    for line in out.splitlines():
        if "偏好驅動組合【偏好效用分數】" in line:
            try: score = float(line.split(":")[-1].strip())
            except Exception: pass
    # 抓最新的 *_weights.csv 的 Preference_Driven 權重欄做比對
    files = sorted(glob.glob("**/*_weights.csv", recursive=True), key=os.path.getmtime)
    wsig = None
    if files:
        try:
            df = pd.read_csv(files[-1])
            numcol = [c for c in df.columns if df[c].dtype.kind in "fi"]
            wsig = tuple(round(float(x), 5) for x in df[numcol[0]].fillna(0).tolist()) if numcol else None
        except Exception: pass
    return score, wsig

orig = getattr(parameters, "PREF_RETURN_BASIS", "cagr")
try:
    s_cagr, w_cagr = run_and_grab("cagr")
    s_beta, w_beta = run_and_grab("beta")
finally:
    parameters.PREF_RETURN_BASIS = orig

print("\n================ 驗證結果 ================")
print(f"pref_utility_score  cagr={s_cagr}  beta={s_beta}  ->",
      "不同 ✓ (展示層已同步 beta)" if (s_cagr is not None and s_beta is not None and s_cagr != s_beta) else "相同/缺值 ⚠")
if w_cagr is not None and w_beta is not None:
    print("最新權重檔首數值欄 cagr==beta ?", w_cagr == w_beta,
          "(若同一檔被覆寫則僅供參考;求解器相同為結構保證)")
print("DONE_VERIFY_MAINSYS_BETA")
