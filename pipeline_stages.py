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

PreferenceMode = Literal["static_ahp", "active_bayesian"]


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


# 主系統推薦後「針對使用者偏好的回測」預設時間窗（資料約 2016-2026；固定一個預設窗，
# 頻率由使用者選。lookback 預設 3 年與主系統一致；2018 起的早期再平衡 lookback 會用到的
# 較早資料若不足，回測會自動以可用資料計算/跳過）。
DEFAULT_PROMPT_BACKTEST_START = "2018-06-01"   # 近 ~8 年 OOS


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
    outputs = [
        f"report/{case_name}_summary.txt",
        f"report/{case_name}_weights.csv",
        f"report/{case_name}_analytics.csv",
        f"png/{case_name}_portfolio_performance.png",
        f"png/{case_name}_mpt_efficient_frontier.png",
        f"png/{case_name}_Mathematical Efficient Frontier.png",
        f"png/{case_name}_radar_chart.png",
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
    deterministic = parameters.DETERMINISTIC_AHP_WEIGHTS
    user_inputs = build_user_simulation(deterministic=deterministic)
    ahp_model = TwoLevel_AHP_Model()
    global_weights, cr = ahp_model.calculate_global_weights(user_inputs)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "CR": cr,
        "Global_Weights": global_weights,
        "Source": "stage2_1_static_ahp_preference_extraction",
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


def stage2_1_preference_extraction(
    mode: PreferenceMode = "static_ahp",
    output_path: str = "json/stage2_ahp_global_weights.json",
    active_answers: list[str] | None = None,
) -> Path:
    """Stage 2_1 router for both supported preference extraction methods."""
    if mode == "static_ahp":
        return stage2_1_static_ahp_preference_extraction(output_path=output_path)
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

    from backtest_engine import run_rolling_backtest, BacktestConfig

    # 偏好回測需要「起點再往前 lookback 年」的歷史。若回測價格快取不夠長，
    # filter_min_history 會擲出 "No ETF passes the minimum history filter"。
    # 為了讓使用者「直接跑就有結果」，這裡做兩件事：
    #   1. 開啟 fetch_missing_data + fetch_period="max"：第一次執行會自動補抓
    #      完整歷史價格並寫入回測快取（之後快取夠長就不會重抓，後續執行很快）。
    #   2. 若指定的「近 ~8 年」窗仍湊不到足夠標的（離線／標的太年輕），自動退而
    #      改用較近的起點重試，確保一定能產出回測，並告知實際採用的窗。
    _common = dict(
        end_date=None,                       # 用到資料最新日
        rebalance_freq=freq,                 # 使用者選
        preference_file=preference_file,     # ★用剛產生的使用者偏好★
        fetch_missing_data=True,             # 缺歷史就自動補抓
        fetch_period="max",                  # 補抓全歷史（涵蓋 8 年窗 + lookback）
    )
    _candidate_starts = [DEFAULT_PROMPT_BACKTEST_START, "2020-06-01", "2022-01-01"]
    _probe = BacktestConfig(start_date=DEFAULT_PROMPT_BACKTEST_START, **_common)
    print(f"\n啟動偏好回測：演算法={parameters.OPTIMIZATION_ARM}、再平衡={freq_map[freq]}、"
          f"目標窗={DEFAULT_PROMPT_BACKTEST_START}~最新、lookback={_probe.lookback_years}年、"
          f"基準={_probe.benchmark_ticker}")
    print("（首次執行會自動補抓完整歷史價格，可能需要數分鐘；之後用快取加速…）")
    _done = False
    for _i, _sd in enumerate(_candidate_starts):
        cfg = BacktestConfig(start_date=_sd, **_common)
        try:
            run_rolling_backtest(cfg)
            _done = True
            if _i > 0:
                print(f"（提示：價格快取歷史不足以支撐 {DEFAULT_PROMPT_BACKTEST_START} 起點，"
                      f"已自動改用較近起點 {_sd} 完成回測。）")
            print(f"\n✅ 偏好回測完成（起點 {_sd}）。輸出在 user_results/（backtest_* 夾）"
                  f"與 backtest_report/。")
            break
        except ValueError as exc:
            if "minimum history filter" in str(exc).lower() and _i < len(_candidate_starts) - 1:
                print(f"⚠️ 起點 {_sd} 無足夠歷史標的，改用較近起點重試…")
                continue
            print(f"⚠️ 偏好回測失敗：{exc}")
            break
        except Exception as exc:
            print(f"⚠️ 偏好回測失敗：{exc}")
            break


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
