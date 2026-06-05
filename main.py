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
        # Options: "static_ahp" or "active_bayesian"
        preference_mode="static_ahp",
        preference_output_path="json/stage2_ahp_global_weights.json",
    )
    run_full_pipeline(config)
