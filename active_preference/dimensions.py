"""ETF 偏好萃取共用維度定義。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreferenceDimension:
    """單一偏好維度的描述。"""

    key: str
    label_zh: str
    description: str
    portfolio_impact: float = 1.0


MAIN_DIMENSIONS: tuple[PreferenceDimension, ...] = (
    PreferenceDimension("Return", "報酬", "Preference for growth or income return.", 1.20),
    PreferenceDimension("Risk", "風險控制", "Preference for smoother returns and drawdown control.", 1.30),
    PreferenceDimension("Cost", "成本", "Preference for lower expense ratio and fees.", 0.95),
    PreferenceDimension("Liquidity", "流動性", "Preference for tradability and fund scale.", 0.75),
    PreferenceDimension("Diversification", "分散度", "Preference for sector or asset-class diversification.", 1.00),
    PreferenceDimension("Sentiment", "市場情緒", "Preference for better news sentiment and narrative quality.", 0.55),
)

SUB_DIMENSIONS: dict[str, tuple[PreferenceDimension, ...]] = {
    "Return": (
        PreferenceDimension("Return_CAGR", "長期資本成長", "Preference for long-term CAGR.", 1.20),
        PreferenceDimension("Return_Div", "股息現金流", "Preference for dividend yield.", 0.85),
    ),
    "Risk": (
        PreferenceDimension("Risk_Vol", "低波動穩定度", "Preference for lower volatility.", 1.25),
        PreferenceDimension("Risk_MaxDD", "抗跌與回撤控制", "Preference for lower maximum drawdown.", 1.30),
    ),
    "Cost": (
        PreferenceDimension("Cost_ExpRatio", "低內扣成本", "Preference for lower expense ratio.", 0.95),
    ),
    "Liquidity": (
        PreferenceDimension("Liq_Volume", "成交流動性", "Preference for higher trading volume.", 0.70),
        PreferenceDimension("Liq_AUM", "基金規模", "Preference for larger fund AUM.", 0.65),
    ),
    "Diversification": (
        PreferenceDimension("Div_Score", "投資組合分散度", "Preference for better diversification.", 1.00),
    ),
    "Sentiment": (
        PreferenceDimension("FinBERT_score", "市場情緒與新聞品質", "Preference for better sentiment score.", 0.55),
    ),
}

MAIN_KEYS: tuple[str, ...] = tuple(dim.key for dim in MAIN_DIMENSIONS)
SOLVER_DIMENSION_KEYS: tuple[str, ...] = tuple(
    sub_dim.key for main_key in MAIN_KEYS for sub_dim in SUB_DIMENSIONS[main_key]
)
DIMENSION_KEYS = SOLVER_DIMENSION_KEYS

MAIN_LABELS_ZH: dict[str, str] = {dim.key: dim.label_zh for dim in MAIN_DIMENSIONS}
SUB_LABELS_ZH: dict[str, str] = {
    sub_dim.key: sub_dim.label_zh
    for sub_dims in SUB_DIMENSIONS.values()
    for sub_dim in sub_dims
}
DIMENSION_LABELS_ZH: dict[str, str] = {**MAIN_LABELS_ZH, **SUB_LABELS_ZH}

SUB_TO_MAIN: dict[str, str] = {
    sub_dim.key: main_key
    for main_key, sub_dims in SUB_DIMENSIONS.items()
    for sub_dim in sub_dims
}

NODE_IMPACT: dict[str, float] = {
    **{dim.key: dim.portfolio_impact for dim in MAIN_DIMENSIONS},
    **{
        sub_dim.key: sub_dim.portfolio_impact
        for sub_dims in SUB_DIMENSIONS.values()
        for sub_dim in sub_dims
    },
}
DIMENSION_IMPACT = NODE_IMPACT


def normalize_weights(weights: dict[str, float], keys: tuple[str, ...] | None = None) -> dict[str, float]:
    """把權重正規化到總和為 1。"""
    target_keys = keys or tuple(weights.keys())
    cleaned = {key: max(float(weights.get(key, 0.0)), 0.0) for key in target_keys}
    total = sum(cleaned.values())
    if total <= 0:
        equal = 1.0 / len(target_keys)
        return {key: equal for key in target_keys}
    return {key: value / total for key, value in cleaned.items()}


def dimension_descriptions_for_prompt() -> str:
    """產生可放進 Gemini prompt 的維度說明。"""
    lines = []
    for key in SOLVER_DIMENSION_KEYS:
        lines.append(f"- {key}：{DIMENSION_LABELS_ZH[key]}")
    return "\n".join(lines)
