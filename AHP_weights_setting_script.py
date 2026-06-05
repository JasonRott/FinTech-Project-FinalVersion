def generate_ahp_inputs(target_main_weights, target_sub_weights):
    """
    AHP 逆向工程腳本：從目標權重反推完美一致的成對比較矩陣
    """
    # 1. 確保主維度權重總和為 1.0 (自動正規化)
    total_main = sum(target_main_weights.values())
    main_w = {k: v / total_main for k, v in target_main_weights.items()}

    # 定義與你的系統完全一致的維度順序
    main_criteria = [
        "Return_Main", 
        "Risk_Main", 
        "Cost_Main", 
        "Liquidity_Main", 
        "Diversity_Main", 
        "Sentiment_Main"
    ]

    print("\n" + "="*50)
    print(" 🎯 AHP 權重逆向工程產生器 (CR = 0.0 完美矩陣)")
    print("="*50)
    print("你設定的目標主權重分佈：")
    for k, v in main_w.items():
        print(f" - {k}: {v*100:.1f}%")

    # 2. 產生 15 個主維度比較值 (w_i / w_j)
    main_comparisons = []
    for i in range(len(main_criteria)):
        for j in range(i + 1, len(main_criteria)):
            val = main_w[main_criteria[i]] / (main_w[main_criteria[j]] + 1e-9)  # 加小數避免除以零
            main_comparisons.append(round(val, 4))

    # 3. 產生子維度比較值
    sub_comparisons = {}
    for main_cat, subs in target_sub_weights.items():
        keys = list(subs.keys())
        if len(keys) == 2: # 針對有兩個子特徵的維度
            val = subs[keys[0]] / (subs[keys[1]] + 1e-9)  # 加小數避免除以零
            sub_comparisons[main_cat] = [round(val, 4)]

    # 4. 輸出可以直接貼上程式碼的 Python 字典格式
    print("\n✅ 請將以下程式碼直接複製，貼上並覆蓋你的 DETERMINISTIC_USER_INPUTS：\n")
    print("DETERMINISTIC_USER_INPUTS = {")
    print(f"    \"Main\": {main_comparisons},")
    print(f"    \"Sub\": {sub_comparisons}")
    print("}")

# ==========================================
# ⚡ 在這裡設定你想要的「目標權重」
# 數字不一定要加總為 100，隨便打也可以，程式會自動依照比例幫你正規化。
# ==========================================

TARGET_MAIN_WEIGHTS = {
    "Return_Main": 50,    # 報酬佔 50%
    "Risk_Main": 20,      # 風險佔 20% 
    "Cost_Main": 10,      # 成本佔 10%
    "Liquidity_Main": 8,  # 流動性佔 8%
    "Diversity_Main": 7, # 分散度佔 7%
    "Sentiment_Main": 5   # 情感佔 5%
}

TARGET_SUB_WEIGHTS = {
    "Return_Main": {"CAGR": 8, "Div": 2},        # 歷史報酬 70%，殖利率 30%
    "Risk_Main": {"Vol": 7, "MaxDD": 3},         # 抗波動 80%，抗回撤 20%
    "Liquidity_Main": {"Volume": 5, "AUM": 5}    # 交易量 50%，資產規模 50%
}

# 執行生成
generate_ahp_inputs(TARGET_MAIN_WEIGHTS, TARGET_SUB_WEIGHTS)