# -*- coding: utf-8 -*-
"""驗收 g(w) 偏好→參數映射：印出 7 個 profile 的 (R, T, 核心類型, vol_budget, τ)。
人工確認方向：aggressive→beta 核心/τ≈0；conservative→minvar/τ 大。"""
import parameters
from functions import derive_params_from_weights

rows = []
for name, w in parameters.USER_PROFILES.items():
    p = derive_params_from_weights(w)
    rows.append((name, p["R"], p["T_growth"], p["core_mode"], p["vol_budget"], p["tau"]))

# 依 T_growth 由高到低排序，方便看單調性
rows.sort(key=lambda r: r[2], reverse=True)

print(f"{'profile':<22}{'R':>7}{'Tg':>7}  {'core':<8}{'vol_budget':>12}{'tau':>9}")
print("-" * 70)
for name, R, T, core, vb, tau in rows:
    print(f"{name:<22}{R:>7.3f}{T:>7.3f}  {core:<8}{vb:>12.3f}{tau:>9.4f}")
