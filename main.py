"""Project entry point with standardized stage names.

══════════════════════════════════════════════════════════════════════════════
 一個開關搞定執行方式：改下面的 RUN_MODE 即可（不依賴已移除的 preference_engine）
──────────────────────────────────────────────────────────────────────────────
  RUN_MODE = "terminal"  一鍵終端問答：在終端輸入投資理念 + 逐題回答（BNN 9 維權重），
                         接著自動跑完整 pipeline（Stage0~3）+ 詢問是否回測。全程在終端。
  RUN_MODE = "web"       網頁版：啟動 ETF 網頁（http://127.0.0.1:8050），偏好問答、
                         執行分析、結果呈現全部在瀏覽器上完成。
  RUN_MODE = "profile"   不問答：直接用指定的 USER_PROFILES 原型 / 靜態 AHP 權重
                         （由 parameters.ACTIVE_USER_PROFILE 控制），跑完整 pipeline。
══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

RUN_MODE = "terminal"   # ← 改這裡："terminal" / "web" / "profile"


def main() -> None:
    if RUN_MODE == "web":
        # 整個流程都在瀏覽器上跑、結果也在瀏覽器上呈現。
        from etf_web.run_web import main as run_etf_web
        run_etf_web()
        return

    from pipeline_stages import PipelineConfig, run_full_pipeline

    # terminal → 終端逐題 BNN 問答；profile → 靜態原型 / AHP（不問答）。
    preference_mode = "preference_engine" if RUN_MODE == "terminal" else "static_ahp"

    config = PipelineConfig(
        run_stage0_fetch=True,
        run_stage0_feature_processing=True,
        run_stage1_dea=True,
        run_stage2_1_preference=True,
        run_stage2_2_cluster_selection=True,
        run_stage3_optimization=True,
        run_stage3_backtest_prompt=True,   # Stage 3 後詢問是否跑「針對此偏好」的歷史回測
        preference_mode=preference_mode,
        preference_output_path="json/stage2_ahp_global_weights.json",
    )
    run_full_pipeline(config)


if __name__ == "__main__":
    main()
