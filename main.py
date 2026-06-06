"""Project entry point with standardized stage names."""

from __future__ import annotations

from pipeline_stages import PipelineConfig, run_full_pipeline


if __name__ == "__main__":
    config = PipelineConfig(
        run_stage0_fetch=True,
        run_stage0_feature_processing=True,
        run_stage1_dea=True,
        run_stage2_1_preference=True,
        run_stage2_2_cluster_selection=True,
        run_stage3_optimization=True,
        run_stage3_backtest_prompt=True,  # Stage 3 後詢問是否跑「針對此偏好」的歷史回測
        # Options:
        #   "web_preference"   ← 網頁版偏好：先跑 `python etf_preference_bundle/run_web.py`
        #                         在瀏覽器完成問答（完成時自動把 9 維權重交付到 json/），再跑本檔讀取結果
        #   "preference_engine" 終端版偏好：在終端逐題回答（投資理念+問答 BNN 誘出，預設答完 9 題）
        #   "static_ahp"        靜態 AHP 問卷 / 指定 USER_PROFILES 原型
        #   "active_bayesian"   舊版 active_preference
        preference_mode="web_preference",
        preference_output_path="json/stage2_ahp_global_weights.json",
    )
    run_full_pipeline(config)
