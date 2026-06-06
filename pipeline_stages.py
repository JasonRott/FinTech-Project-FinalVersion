"""Unified stage orchestration for the ETF preference optimization project.

The functions in this module are thin wrappers around the existing production
functions. The goal is to standardize stage names without rewriting the solver,
DEA implementation, or data ETL code.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import parameters

PreferenceMode = Literal["static_ahp", "active_bayesian", "preference_engine", "web_preference"]


STAGE_NAMES = {
    "stage0": "stage0_market_data_preparation",
    "stage1": "stage1_dea_screening",
    "stage2_1_static": "stage2_1_static_ahp_preference_extraction",
    "stage2_1_active": "stage2_1_active_bayesian_preference_elicitation",
    "stage2_2": "stage2_2_preference_cluster_selection",
    "stage3": "stage3_preference_portfolio_optimization",
}

ACTIVE_BAYESIAN_LOOP_STAGES = {
    "stage2_1B_0": "initialize_hierarchical_belief",
    "stage2_1B_1": "select_uncertain_targets",
    "stage2_1B_2": "ask_contextual_question",
    "stage2_1B_3": "extract_semantic_evidence",
    "stage2_1B_4": "update_bayesian_belief",
    "stage2_1B_5": "check_convergence_or_continue",
    "stage2_1B_6": "export_solver_compatible_weights",
}

STAGE_TITLES = {
    "stage0": "Stage 0 - 市場資料擷取與特徵處理",
    "stage1": "Stage 1 - DEA 效率篩選",
    "stage2_1_static": "Stage 2_1-A - 靜態 AHP 偏好提取",
    "stage2_1_active": "Stage 2_1-B - 自然語言貝式偏好探測",
    "stage2_2": "Stage 2_2 - 高相關 ETF 分群與偏好篩選",
    "stage3": "Stage 3 - 偏好投資組合最佳化",
}


# 主系統推薦後「針對使用者偏好的回測」：資料/視窗固定在 10 年以內。
# 設計（使用者指定）：OOS 視窗從「7 年前」開始，估計 lookback 最多 3 年，
#   → 視窗 + lookback ≤ 10 年（與既有約 2016–2026 的回測快取相符，通常免大量補抓）。
# 起點以「今天往前推 7 年」動態計算（隨時間滑動），頻率由使用者選。
PROMPT_BACKTEST_WINDOW_YEARS = 7      # OOS 視窗長度（從 7 年前開始）
PROMPT_BACKTEST_LOOKBACK_YEARS = 3    # 估計 lookback（最多 3 年）
PROMPT_BACKTEST_MAX_DATA_YEARS = (    # 回測實際用到的資料總跨度上限（年）= 10
    PROMPT_BACKTEST_WINDOW_YEARS + PROMPT_BACKTEST_LOOKBACK_YEARS
)


@dataclass
class PipelineConfig:
    run_stage0_fetch: bool = True
    run_stage0_feature_processing: bool = True
    run_stage1_dea: bool = True
    run_stage2_1_preference: bool = True
    run_stage2_2_cluster_selection: bool = True
    run_stage3_optimization: bool = True
    run_stage3_backtest_prompt: bool = True   # Stage 3 後詢問是否跑「針對此偏好」的回測
    preference_mode: PreferenceMode = "static_ahp"
    active_answers: list[str] | None = None
    preference_output_path: str = "json/stage2_ahp_global_weights.json"


def initialize_project_environment() -> None:
    """Create required output folders."""
    for folder in ("csv", "json", "png", "report"):
        os.makedirs(folder, exist_ok=True)


def _announce_stage_start(stage_key: str, detail: str = "") -> None:
    title = STAGE_TITLES.get(stage_key, stage_key)
    print("\n" + "=" * 72)
    print(f">>> 開始 {title}")
    if detail:
        print(f"    {detail}")
    print("=" * 72)


def _announce_stage_end(stage_key: str, output_hint: str = "") -> None:
    title = STAGE_TITLES.get(stage_key, stage_key)
    print("-" * 72)
    print(f"<<< 結束 {title}")
    if output_hint:
        print(f"    輸出檔案：{output_hint}")
    print("-" * 72)


def _stage3_output_hint() -> str:
    case_name = parameters.CASE_NAME
    # 註：投組績效圖與蒙地卡羅前緣圖已停用,不再輸出（見 functions.py）。
    outputs = [
        f"report/{case_name}_summary.txt",
        f"report/{case_name}_weights.csv",
        f"report/{case_name}_analytics.csv",
        f"png/{case_name}_Mathematical Efficient Frontier.png",
        f"png/{case_name}_radar_chart.png",
        "（圖表+報表已自動彙整到 user_results/new_user_<n>/）",
    ]
    return ", ".join(outputs)


def _export_fallback_active_bayesian_weights(output_path: str) -> Path:
    """Fallback output when the active_preference package API is unavailable."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    equal_weight = 1.0 / 9.0
    payload = {
        "CR": None,
        "Global_Weights": {
            "Return_CAGR": equal_weight,
            "Return_Div": equal_weight,
            "Risk_Vol": equal_weight,
            "Risk_MaxDD": equal_weight,
            "Cost_ExpRatio": equal_weight,
            "Liq_Volume": equal_weight,
            "Liq_AUM": equal_weight,
            "Div_Score": equal_weight,
            "FinBERT_score": equal_weight,
        },
        "Source": "stage2_1_active_bayesian_preference_elicitation_fallback",
        "Warning": (
            "active_preference.ActivePreferenceSystem is not available in the current package API; "
            "fallback equal weights were exported so downstream stages keep a valid interface."
        ),
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
    return output


def stage0_market_data_preparation(
    run_fetch: bool = True,
    run_feature_processing: bool = True,
) -> None:
    """Stage 0: fetch ETF data, engineer features, run EDA, and normalize data."""
    _announce_stage_start(
        "stage0",
        "擷取 ETF 資料、建立特徵、執行 EDA，並產生 DEA 前置正規化矩陣。",
    )
    from functions import (
        append_sentiment_to_csv,
        build_etf_database_av,
        clean_existing_database,
        fetch_etf_data_yq,
        get_all_etfs,
        get_target_tickers_from_csv,
        log,
        merge_final_features,
        patch_aum_from_csv,
        run_stage0_2_eda,
        run_stage0_normalization_and_reduction,
    )

    log.info("Stage 0 - Market data preparation started.")

    if run_fetch:
        get_all_etfs()
        target_tickers = get_target_tickers_from_csv(parameters.CSV_UNIVERSE_FILE, parameters.TOP_N_ETFS)
        if target_tickers:
            fetch_etf_data_yq(target_tickers)
            build_etf_database_av(target_tickers)
            clean_existing_database()
            append_sentiment_to_csv()
            merge_final_features()
            patch_aum_from_csv()

    if run_feature_processing:
        run_stage0_2_eda()
        run_stage0_normalization_and_reduction()

    log.info("Stage 0 - Market data preparation finished.")
    _announce_stage_end(
        "stage0",
        "csv/stage0_final_matrix.csv, csv/stage0_dea_ready_matrix.csv, png/eda_*.png",
    )


def stage1_dea_screening() -> None:
    """Stage 1: run standard DEA, super-efficiency DEA, and cross-efficiency DEA."""
    _announce_stage_start(
        "stage1",
        "執行標準 DEA、超級效率 DEA 與交互效率 DEA。",
    )
    from functions import (
        log,
        plot_dea_distribution,
        run_cross_efficiency_dea,
        run_stage1_normalized_dea,
        run_stage1_super_efficiency_normalized,
    )

    log.info("Stage 1 - DEA screening started.")
    run_stage1_normalized_dea()
    plot_dea_distribution()
    run_stage1_super_efficiency_normalized()
    run_cross_efficiency_dea()
    log.info("Stage 1 - DEA screening finished.")
    _announce_stage_end(
        "stage1",
        "csv/stage1_dea_results.csv, csv/stage1_super_efficiency_results.csv, csv/stage1_final_candidates.csv",
    )


def stage2_1_static_ahp_preference_extraction(
    output_path: str = "json/stage2_ahp_global_weights.json",
) -> Path:
    """Stage 2_1-A: extract preference weights through the static AHP questionnaire."""
    _announce_stage_start(
        "stage2_1_static",
        "透過原本的靜態 AHP 問卷提取使用者偏好權重。",
    )
    from functions import TwoLevel_AHP_Model, build_user_simulation, log

    log.info("Stage 2_1-A - Static AHP preference extraction started.")
    active_profile = getattr(parameters, "ACTIVE_USER_PROFILE", None)
    if active_profile:
        # 直接採用指定使用者原型的 9 維全局權重當「系統輸入」（繞過 AHP 成對比較模擬）。
        # 下游 stage2_2 / stage3 / 回測都讀此 JSON，故權重會隨選定的 user 一起變動。
        global_weights = dict(parameters.USER_PROFILES[active_profile])
        cr = 0.0
        source = f"USER_PROFILES[{active_profile}] (direct profile weights)"
        log.info(f"Stage 2_1-A - 使用指定使用者原型 '{active_profile}' 的全局權重（略過 AHP 模擬）。")
    else:
        deterministic = parameters.DETERMINISTIC_AHP_WEIGHTS
        user_inputs = build_user_simulation(deterministic=deterministic)
        ahp_model = TwoLevel_AHP_Model()
        global_weights, cr = ahp_model.calculate_global_weights(user_inputs)
        source = "stage2_1_static_ahp_preference_extraction"

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "CR": cr,
        "Global_Weights": global_weights,
        "Source": source,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
    log.info("Stage 2_1-A - Static AHP preference extraction finished.")
    _announce_stage_end("stage2_1_static", str(output))
    return output


def stage2_1_active_bayesian_preference_elicitation(
    answers: list[str] | None = None,
    output_path: str = "json/stage2_ahp_global_weights.json",
    max_turns: int = 6,
) -> Path:
    """Stage 2_1-B: extract preference through natural language and Bayesian belief updates.

    In production, `answers` should come from the user interface. When answers
    are omitted, this wrapper uses synthetic statements so the pipeline remains
    runnable for development and tests.
    """
    _announce_stage_start(
        "stage2_1_active",
        "透過自然語言回答進行偏好探測，並更新階層式貝式信念。",
    )
    try:
        from active_preference import ActivePreferenceSystem, SyntheticPreferenceGenerator
    except ImportError:
        output = _export_fallback_active_bayesian_weights(output_path)
        state_output = Path("json/stage2_1_active_bayesian_state.json")
        state_output.write_text(
            json.dumps(
                {
                    "loop_stages": ACTIVE_BAYESIAN_LOOP_STAGES,
                    "warning": "active_preference.ActivePreferenceSystem is not available.",
                    "state": None,
                },
                ensure_ascii=False,
                indent=4,
            ),
            encoding="utf-8",
        )
        _announce_stage_end("stage2_1_active", f"{output}, {state_output}")
        return output

    system = ActivePreferenceSystem()

    if answers is None:
        generator = SyntheticPreferenceGenerator(seed=17)
        profile = generator.generate_profiles(count=1)[0]
        answers = profile.statements

    transcript = []
    for answer in answers[:max_turns]:
        question = system.next_question()
        result = system.answer(answer)
        transcript.append(
            {
                "question": question,
                "answer": answer,
                "ready_for_optimization": result["ready_for_optimization"],
            }
        )
        if result["ready_for_optimization"]:
            break

    output = system.export_solver_weights(output_path)
    state_output = Path("json/stage2_1_active_bayesian_state.json")
    state_output.write_text(
        json.dumps(
            {
                "loop_stages": ACTIVE_BAYESIAN_LOOP_STAGES,
                "transcript": transcript,
                "state": system.tracker.state.to_dict(),
            },
            ensure_ascii=False,
            indent=4,
        ),
        encoding="utf-8",
    )
    _announce_stage_end("stage2_1_active", f"{output}, {state_output}")
    return output


_PREF_DIMS = [
    "Return_CAGR", "Return_Div", "Risk_Vol", "Risk_MaxDD", "Cost_ExpRatio",
    "Liq_Volume", "Liq_AUM", "Div_Score", "FinBERT_score",
]


def stage2_1_preference_engine_elicitation(
    output_path: str = "json/stage2_ahp_global_weights.json",
    philosophy_text: str | None = None,
    answers: list[str] | None = None,
    max_questions: int = 9,
) -> Path:
    """Stage 2_1-C：用 `preference_engine`（投資理念 + 逐輪自然語言問答 → BNN 偏好誘出）
    產生 9 維全局權重，並寫成下游認得的 `Global_Weights` JSON（與 AHP 路徑同格式）。

    互動模式（預設）：終端逐題詢問，**預設答完整 9 題**（引擎在 Σα≥τ 會提議早停，但未答完 9 題
    時 CI 不可信，故預設續答；首次提議早停時詢問一次，直接 Enter 繼續）。
    `philosophy_text` / `answers` 有給時可非互動執行（供測試或外部 UI 串接：把 UI 收到的開場理念
    與逐題答案傳進來即可；非互動會自動答到完整 9 題）。引擎輸出的 `Ew` 維度鍵與本系統 9 維一致，無需映射。
    """
    _announce_stage_start(
        "stage2_1_active",
        "透過 preference_engine（投資理念 + 逐輪問答）誘出 9 維偏好權重。",
    )
    import sys as _sys
    from functions import log

    _eng_dir = str(Path(__file__).resolve().parent / "etf_preference_bundle")
    if _eng_dir not in _sys.path:
        _sys.path.insert(0, _eng_dir)
    try:
        from phase3_system import Phase3Engine  # type: ignore
    except Exception as exc:  # 套件/相依缺失 → 退回既有 fallback 權重，管線不中斷
        log.error(f"無法載入 etf_preference_bundle（{exc}）；改用 fallback 權重。")
        output = _export_fallback_active_bayesian_weights(output_path)
        _announce_stage_end("stage2_1_active", str(output))
        return output

    interactive = answers is None  # 沒給預錄答案 → 終端互動

    # --- 開場投資理念 ---
    if philosophy_text is None:
        try:
            philosophy_text = input("\n請輸入你的投資理念（直接 Enter 用預設範例）：\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            philosophy_text = ""
    if not philosophy_text:
        philosophy_text = "我希望長期穩健成長，能接受一點波動但很怕大跌，偏好低費用、分散持股的標的。"
        print(f"(使用預設投資理念) {philosophy_text}")

    # ★預設「答完整 9 題」，不在 should_stop 自動早停★：
    # 引擎在 Σα≥τ（約掌握 top-1/2）就會提議停，但未答完 9 題時未問維仍留在先驗、CI 不可信
    # （引擎自身 ci_note 也會警告）。故預設續答到 next_question() 回 None（含 T3 重問）。
    # 互動模式下，當引擎「首次」提議早停時詢問一次是否要現在停（直接 Enter = 繼續答完更準）。
    engine = Phase3Engine()
    engine.start_session(philosophy_text)
    _answers_iter = iter(answers) if answers is not None else None

    snap = engine.snapshot()
    prompted_stop = False
    _safety = 0
    while _safety < 50:  # 安全上限（引擎本身會在覆蓋+重問封頂後回 None 自然結束）
        _safety += 1
        q = engine.next_question()
        if q is None:
            break
        if _answers_iter is not None:
            ans = next(_answers_iter, "普通，沒有特別偏好。")
        else:
            _tag = "（重問釐清）" if q.get("is_reask") else ""
            print(f"\n[第 {q['step']} 題 · {q['dim_label']}]{_tag}")
            try:
                ans = input(f"  {q['question']}\n  > ").strip()
            except (EOFError, KeyboardInterrupt):
                ans = ""
        snap = engine.submit_answer(ans)
        if interactive and snap.get("should_stop") and snap.get("n_covered", 0) < 9 and not prompted_stop:
            prompted_stop = True
            try:
                _r = input(
                    "\n（引擎已大致掌握你的前幾名偏好，但尚未答完 9 題，信賴區間還不可信）\n"
                    "  要現在就停嗎？輸入 y 停止，直接 Enter 繼續答完更準： "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                _r = ""
            if _r in ("y", "yes", "是"):
                break

    snap = engine.snapshot()
    weights = snap.get("Ew", {})

    # --- 防呆：確保 9 維齊全、總和正規化為 1 ---
    w = {d: float(weights.get(d, 0.0)) for d in _PREF_DIMS}
    total = sum(w.values()) or 1.0
    w = {d: v / total for d, v in w.items()}

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "CR": 0.0,
        "Global_Weights": w,
        "Source": "etf_preference_bundle terminal (Phase3 BNN elicitation)",
        "Sigma_alpha": snap.get("Sigma_alpha"),
        "n_covered": snap.get("n_covered"),
        "ci_trustworthy": snap.get("ci_trustworthy"),
        "ci_note": snap.get("ci_note"),
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
    log.info(f"Stage 2_1-C - preference_engine 偏好誘出完成（9 維權重已寫入 {output}）。")
    _announce_stage_end("stage2_1_active", str(output))
    return output


def stage2_1_web_preference_ingest(
    output_path: str = "json/stage2_ahp_global_weights.json",
) -> Path:
    """Stage 2_1-D：讀取「網頁版偏好誘出」(`etf_preference_bundle` 網頁問答) 最近一次完成的
    9 維權重，寫成下游認得的 `Global_Weights` JSON（與 AHP 路徑同格式）。

    使用流程（兩步、跨行程）：
      1) `python etf_preference_bundle/run_web.py` → 瀏覽器完成問答；
         完成時 `recommender_hook.deliver_weights()` 會把權重交付到主系統
         `json/stage2_ahp_global_weights.json`，並同時留一份 `etf_preference_bundle/web/last_result.json`。
      2) `python main.py`（preference_mode="web_preference"）→ 本函式讀取該結果、正規化 9 維、續跑下游。

    來源優先序：`etf_preference_bundle/web/last_result.json` ⇒ 既有 `output_path`（hook 直寫的檔）。
    都找不到時 → 退回 fallback 等權重，並提示先跑網頁問答，管線不中斷。
    """
    _announce_stage_start(
        "stage2_1_active",
        "讀取網頁版偏好誘出（etf_preference_bundle 網頁問答）最近一次完成的 9 維權重。",
    )
    from functions import log

    bundle_dir = Path(__file__).resolve().parent / "etf_preference_bundle"
    last_result = bundle_dir / "web" / "last_result.json"

    weights: dict | None = None
    snap: dict = {}
    source_file: str | None = None

    # ① 優先讀網頁版完成時寫出的 last_result.json（最權威、含完整快照）
    if last_result.exists():
        try:
            data = json.loads(last_result.read_text(encoding="utf-8"))
            weights = data.get("weights") or {}
            snap = data.get("snapshot") or {}
            source_file = str(last_result)
        except Exception as exc:
            log.error(f"無法解析 {last_result}（{exc}）；改試既有權重檔。")

    # ② 退而求其次：hook 已直寫的主系統權重檔
    if not weights:
        existing = Path(output_path)
        if existing.exists():
            try:
                data = json.loads(existing.read_text(encoding="utf-8"))
                gw = data.get("Global_Weights") or {}
                if gw:
                    weights = gw
                    snap = {
                        "Sigma_alpha": data.get("Sigma_alpha"),
                        "n_covered": data.get("n_covered"),
                        "ci_trustworthy": data.get("ci_trustworthy"),
                        "ci_note": data.get("ci_note"),
                    }
                    source_file = str(existing)
            except Exception as exc:
                log.error(f"無法解析 {existing}（{exc}）。")

    # ③ 都沒有 → fallback，提示先跑網頁
    if not weights:
        log.error(
            "找不到網頁版偏好結果（etf_preference_bundle/web/last_result.json）。"
            "請先執行 `python etf_preference_bundle/run_web.py` 在瀏覽器完成問答後再跑 main.py；"
            "本次先用 fallback 等權重維持管線。"
        )
        output = _export_fallback_active_bayesian_weights(output_path)
        _announce_stage_end("stage2_1_active", str(output))
        return output

    # --- 防呆：確保 9 維齊全、總和正規化為 1 ---
    w = {d: float(weights.get(d, 0.0)) for d in _PREF_DIMS}
    total = sum(w.values()) or 1.0
    w = {d: v / total for d, v in w.items()}

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "CR": 0.0,
        "Global_Weights": w,
        "Source": f"etf_preference_bundle web ({source_file})",
        "Sigma_alpha": snap.get("Sigma_alpha"),
        "n_covered": snap.get("n_covered"),
        "ci_trustworthy": snap.get("ci_trustworthy"),
        "ci_note": snap.get("ci_note"),
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
    log.info(f"Stage 2_1-D - 網頁版偏好權重已寫入 {output}（來源：{source_file}）。")
    _announce_stage_end("stage2_1_active", str(output))
    return output


def stage2_1_preference_extraction(
    mode: PreferenceMode = "static_ahp",
    output_path: str = "json/stage2_ahp_global_weights.json",
    active_answers: list[str] | None = None,
) -> Path:
    """Stage 2_1 router for the supported preference extraction methods."""
    if mode == "static_ahp":
        return stage2_1_static_ahp_preference_extraction(output_path=output_path)
    if mode == "web_preference":
        return stage2_1_web_preference_ingest(output_path=output_path)
    if mode == "preference_engine":
        return stage2_1_preference_engine_elicitation(
            output_path=output_path,
            answers=active_answers,
        )
    if mode == "active_bayesian":
        return stage2_1_active_bayesian_preference_elicitation(
            answers=active_answers,
            output_path=output_path,
        )
    raise ValueError(f"Unsupported preference mode: {mode}")


def stage2_2_preference_cluster_selection() -> None:
    """Stage 2_2: cluster highly correlated ETFs and select the best ETF per cluster."""
    _announce_stage_start(
        "stage2_2",
        "針對高相關性 ETF 分群，並依照使用者偏好選出每群最佳標的。",
    )
    from functions import log, run_stage2_5_preference_deduplication_yq

    log.info("Stage 2_2 - Preference cluster selection started.")
    run_stage2_5_preference_deduplication_yq()
    log.info("Stage 2_2 - Preference cluster selection finished.")
    _announce_stage_end(
        "stage2_2",
        "csv/stage2_final_user_universe.csv, csv/stage2_normalized_features.csv",
    )


def stage3_preference_portfolio_optimization() -> None:
    """Stage 3: optimize the preference-driven portfolio and compare with Max Sharpe."""
    _announce_stage_start(
        "stage3",
        "求解偏好驅動投資組合，並與傳統最大夏普值組合進行比較分析。",
    )
    from functions import log, run_stage3_pipeline

    log.info("Stage 3 - Preference portfolio optimization started.")
    run_stage3_pipeline()
    log.info("Stage 3 - Preference portfolio optimization finished.")
    _announce_stage_end("stage3", _stage3_output_hint())


def run_preference_backtest_core(
    rebalance_freq: str = "Q",
    preference_file: str = "json/stage2_ahp_global_weights.json",
    emit=print,
) -> bool:
    """非互動版偏好回測核心（終端 prompt 與網頁版共用）。

    讀取剛產生的偏好權重檔、用生產演算法（parameters.OPTIMIZATION_ARM，預設 C2）跑滾動回測；
    資料/視窗固定在 10 年內（OOS 7 年 + lookback 3 年），起點動態（今天往前推），
    7 年窗湊不到足夠標的時自動退到較近起點（仍 ≤ 10 年）。回測夾巢狀進主系統本次使用者資料夾。

    `emit` 為輸出函式（預設 print；網頁版可傳入把訊息送進進度緩衝區）。回測成功回傳 True。
    """
    from datetime import datetime
    from backtest_engine import run_rolling_backtest, BacktestConfig

    freq_map = {"M": "月度", "Q": "季度", "6M": "半年", "Y": "年度"}
    freq = rebalance_freq if rebalance_freq in freq_map else "Q"

    # 取剛剛主系統建立的 user_results/new_user_*/ 路徑，讓本次回測夾巢狀進同一個使用者資料夾。
    try:
        import functions as _functions
        _user_parent = getattr(_functions, "LAST_MAIN_USER_DIR", None)
    except Exception:
        _user_parent = None

    _now = datetime.now()

    def _years_ago(n: int) -> str:
        return f"{_now.year - n:04d}-{_now.month:02d}-01"

    _common = dict(
        end_date=None,                                   # 用到資料最新日
        lookback_years=PROMPT_BACKTEST_LOOKBACK_YEARS,   # 最多 3 年
        rebalance_freq=freq,                             # 使用者選
        preference_file=preference_file,                 # ★用剛產生的使用者偏好★
        fetch_missing_data=True,                         # 僅補「缺資料」的標的（快取夠就不抓）
        fetch_period="max",                              # 安全網：無快取時才會真的補抓
        user_results_parent=_user_parent,                # 巢狀於主系統本次使用者資料夾內
    )
    _primary_start = _years_ago(PROMPT_BACKTEST_WINDOW_YEARS)            # 7 年前
    _candidate_starts = [_primary_start, _years_ago(5), _years_ago(3)]  # 退而求其次：仍 ≤10 年
    _probe = BacktestConfig(start_date=_primary_start, **_common)
    emit(f"\n啟動偏好回測：演算法={parameters.OPTIMIZATION_ARM}、再平衡={freq_map[freq]}、"
         f"OOS 視窗={_primary_start}~最新（約 {PROMPT_BACKTEST_WINDOW_YEARS} 年）、"
         f"lookback={_probe.lookback_years} 年 → 資料跨度上限 {PROMPT_BACKTEST_MAX_DATA_YEARS} 年、"
         f"基準={_probe.benchmark_ticker}")
    emit("（資料/視窗固定在 10 年內；通常直接用既有快取，缺資料才會自動補抓…）")
    _done = False
    for _i, _sd in enumerate(_candidate_starts):
        cfg = BacktestConfig(start_date=_sd, **_common)
        try:
            run_rolling_backtest(cfg)
            _done = True
            if _i > 0:
                emit(f"（提示：{_primary_start} 起點在當前快取湊不到足夠標的，"
                     f"已自動改用較近起點 {_sd}；視窗縮短但仍在 10 年內。）")
            emit(f"\n✅ 偏好回測完成（起點 {_sd}）。輸出在 user_results/（backtest_* 夾）"
                 f"與 backtest_report/。")
            break
        except ValueError as exc:
            if "minimum history filter" in str(exc).lower() and _i < len(_candidate_starts) - 1:
                emit(f"⚠️ 起點 {_sd} 無足夠歷史標的，改用較近起點重試…")
                continue
            emit(f"⚠️ 偏好回測失敗：{exc}")
            break
        except Exception as exc:
            emit(f"⚠️ 偏好回測失敗：{exc}")
            break
    return _done


def stage3b_optional_preference_backtest(
    preference_file: str = "json/stage2_ahp_global_weights.json",
) -> None:
    """Stage 3 後：詢問使用者是否要看「針對自己偏好」的歷史回測。

    回測直接讀取剛產生的偏好權重檔（與 Stage 3 相同），並使用生產演算法
    （parameters.OPTIMIZATION_ARM，預設 C2）—— 與主系統完全一致。
    使用者只需選再平衡頻率；時間窗固定為預設（近 ~8 年）。
    """
    print("\n" + "=" * 72)
    print(">>> Stage 3 後：偏好回測（選用）")
    print("=" * 72)
    try:
        ans = input("要看「針對你的偏好」的歷史回測嗎？(y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("（非互動環境/已略過回測）")
        return
    if ans not in ("y", "yes", "是"):
        print("已略過偏好回測。")
        return

    freq_map = {"M": "月度", "Q": "季度", "6M": "半年", "Y": "年度"}
    try:
        raw = input("選擇再平衡頻率 [M=月 / Q=季 / 6M=半年 / Y=年]（預設 Q，月度較慢）: ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        raw = ""
    freq = raw if raw in freq_map else "Q"
    run_preference_backtest_core(rebalance_freq=freq, preference_file=preference_file)


def run_full_pipeline(config: PipelineConfig | None = None) -> None:
    """Run the standardized end-to-end project pipeline."""
    cfg = config or PipelineConfig()
    initialize_project_environment()

    if cfg.run_stage0_fetch or cfg.run_stage0_feature_processing:
        stage0_market_data_preparation(
            run_fetch=cfg.run_stage0_fetch,
            run_feature_processing=cfg.run_stage0_feature_processing,
        )
    if cfg.run_stage1_dea:
        stage1_dea_screening()
    if cfg.run_stage2_1_preference:
        stage2_1_preference_extraction(
            mode=cfg.preference_mode,
            output_path=cfg.preference_output_path,
            active_answers=cfg.active_answers,
        )
    if cfg.run_stage2_2_cluster_selection:
        stage2_2_preference_cluster_selection()
    if cfg.run_stage3_optimization:
        stage3_preference_portfolio_optimization()
        if cfg.run_stage3_backtest_prompt:
            stage3b_optional_preference_backtest(preference_file=cfg.preference_output_path)
