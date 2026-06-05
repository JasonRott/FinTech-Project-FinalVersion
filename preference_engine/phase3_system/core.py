"""Phase 3 互動系統 — 自包含定案核心（與 #79 位元一致）。

本檔把分散在 active_preference_v2/scripts/*、models/、features.py、dimensions.py 的定案函式
**逐字複製**進來，讓本 app 完全不依賴原始實驗腳本樹（可整包傳給別人）。每段標明出處。
請勿在此『改進』數學——這是凍結定案（#79）。
"""
from __future__ import annotations
import math
import numpy as np
import torch
from torch import nn
from scipy.special import gammaln, psi
from scipy.stats import beta as _beta

# ── 維度（active_preference_v2/dimensions.py）──
DIMENSION_KEYS = ("Return_CAGR", "Return_Div", "Risk_Vol", "Risk_MaxDD", "Cost_ExpRatio",
                  "Liq_Volume", "Liq_AUM", "Div_Score", "FinBERT_score")

# ── 定案凍結常數（#79；另見 assets/config.json）──
A_PRIOR = 1.0 / 3.0
C_COUNT = 1.0
T_TRUST = 1.0
REL_MIN = 0.2
W_CONF = 1.0
W_SIG = 0.0
RHO_MAX = 0.6
S_LO, S_HI = 0.1, 0.9
PLATEAU_DELTA = 0.02
PLATEAU_MINSTEPS = 2


def unit(x):
    return x / np.clip(np.linalg.norm(x, axis=-1, keepdims=True), 1e-9, None)


# ── 1D BNN 模型（models/multitask_one_dim_bnn.py，verbatim）──
class MultiTaskMCDropout1DRegressor(nn.Module):
    def __init__(self, input_dim, hidden_dim=128, dropout=0.25, bucket_count=3):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden_dim), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2), nn.GELU(), nn.Dropout(dropout),
        )
        self.regression_head = nn.Sequential(nn.Linear(hidden_dim // 2, 1), nn.Sigmoid())
        self.classification_head = nn.Linear(hidden_dim // 2, bucket_count)

    def forward(self, features):
        hidden = self.encoder(features)
        strength = self.regression_head(hidden).squeeze(-1)
        bucket_logits = self.classification_head(hidden)
        return strength, bucket_logits


def load_1d_model(checkpoint_path, device):
    """train_belief_fusion_v1.load_1d_model（verbatim）。"""
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model = MultiTaskMCDropout1DRegressor(
        input_dim=int(checkpoint["input_dim"]),
        hidden_dim=int(checkpoint["hidden_dim"]),
        dropout=float(checkpoint["dropout"]),
    ).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model


def mc_predict_with_uncertainty_scores(model, features, passes):
    """calibrate_gemini10_1d_bnn_uncertainty.mc_predict_with_uncertainty_scores（verbatim）。
    回傳 (strength_mu, strength_sigma, mean_bucket_probs, MSP, predictive_entropy, variation_ratio)。"""
    model.train()
    strengths, probabilities, predicted_classes = [], [], []
    for _ in range(passes):
        strength, logits = model(features)
        probs = torch.softmax(logits, dim=-1)
        strengths.append(strength); probabilities.append(probs)
        predicted_classes.append(torch.argmax(probs, dim=-1))
    stacked_strengths = torch.stack(strengths, dim=0)
    stacked_probabilities = torch.stack(probabilities, dim=0)
    stacked_classes = torch.stack(predicted_classes, dim=0)
    mean_probs = stacked_probabilities.mean(dim=0)
    msp = mean_probs.max(dim=1).values
    clipped_probs = mean_probs.clamp_min(1e-8)
    predictive_entropy = -torch.sum(clipped_probs * torch.log(clipped_probs), dim=1) / math.log(mean_probs.shape[1])
    class_counts = torch.stack([(stacked_classes == c).sum(dim=0) for c in range(mean_probs.shape[1])])
    variation_ratio = 1.0 - class_counts.max(dim=0).values.float() / float(passes)
    return (stacked_strengths.mean(dim=0), stacked_strengths.std(dim=0), mean_probs,
            msp, predictive_entropy, variation_ratio)


def calibrated_sigma(raw_sigma, entropy, params):
    """train_belief_fusion_v1.calibrated_sigma（verbatim）。"""
    selected = str(params["selected_sigma"])
    if selected == "entropy_calibrated":
        cal = params["entropy_calibrator"]
        a = float(cal["a_mc_scale"]); b = float(cal["b_error_floor"]); c = float(cal["c_entropy_scale"])
        sigma_sq = (a * raw_sigma) ** 2 + b ** 2 + (c * entropy) ** 2
    else:
        cal = params["gaussian_calibrator"]
        a = float(cal["a_mc_scale"]); b = float(cal["b_error_floor"])
        sigma_sq = (a * raw_sigma) ** 2 + b ** 2
    return np.sqrt(np.clip(sigma_sq, 1e-8, 10.0))


# ── PhilHead 理念→p0（phase3_e1_conjugate_calibration.PhilHead，verbatim）──
class PhilHead(nn.Module):
    def __init__(self, in_dim=1024, hidden=128, dropout=0.2):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(in_dim, hidden), nn.LayerNorm(hidden), nn.GELU(),
                                 nn.Dropout(dropout), nn.Linear(hidden, 9))

    def forward(self, x):
        return torch.softmax(self.net(x), -1)


# ── 選題（phase3_e2_selection / phase3_e5eig_closedform，verbatim）──
def prior_dominance(p0_row):
    p0 = np.asarray(p0_row, dtype=np.float64)
    return p0 / max(float(p0.max()), 1e-9)


def _delta_entropy(alpha, Sa, d, dnew):
    K = 9
    ad = float(alpha[d]); Sa2 = Sa + (dnew - ad)
    dH = (gammaln(dnew) - gammaln(ad)) - (gammaln(Sa2) - gammaln(Sa))
    dH += (Sa2 - K) * psi(Sa2) - (Sa - K) * psi(Sa)
    dH -= (dnew - 1.0) * psi(dnew) - (ad - 1.0) * psi(ad)
    return dH


def beig_select(alpha, prior_dom, cand, two_sided=False):
    """閉式定向 Bernoulli EIG（雙側為 #79 定案）。"""
    Sa = float(alpha.sum())
    if two_sided:
        p = np.clip(prior_dom, 0.0, 1.0)
        best, best_eig = cand[0], -1e18
        for d in cand:
            dH_hi = _delta_entropy(alpha, Sa, d, alpha[d] + C_COUNT * S_HI)
            dH_lo = _delta_entropy(alpha, Sa, d, alpha[d] + C_COUNT * S_LO)
            eig = -(float(p[d]) * dH_hi + (1.0 - float(p[d])) * dH_lo)
            if eig > best_eig:
                best_eig, best = eig, d
        return int(best)
    p = alpha / float(alpha.sum())
    best, best_eig = cand[0], -1e18
    for d in cand:
        dH = _delta_entropy(alpha, Sa, d, alpha[d] + C_COUNT)
        eig = float(p[d]) * (-dH)
        if eig > best_eig:
            best_eig, best = eig, d
    return int(best)


# ── 更新 / 讀出（phase3_e15_* / phase3_integration_test，verbatim）──
def temp_scale(ew, T):
    z = np.log(np.clip(ew, 1e-8, 1.0)) / T
    z -= z.max(-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(-1, keepdims=True)


def ci_width(alpha, d, lo=0.025, hi=0.975):
    Sa = float(alpha.sum()); ad = float(alpha[d])
    return float(_beta.ppf(hi, ad, Sa - ad) - _beta.ppf(lo, ad, Sa - ad))


def semC_gated(alpha, prior, kc, d, s, gate_rel):
    """Semantics C 方向感知局部遺忘 × OOD relevance gate（只動被問維）。"""
    a = alpha.copy(); k = kc.copy()
    n_old = max(float(a[d] - prior[d]), 0.0)
    if k[d] >= 1 and n_old > 1e-9:
        expected = n_old / (C_COUNT * k[d])
        trust = float(np.clip(n_old / (C_COUNT * T_TRUST), 0.0, 1.0))
        conflict = trust * abs(s - expected)
    else:
        conflict = 0.0
    kappa = float(np.clip(W_CONF * conflict, 0.0, RHO_MAX))
    n_new = (1.0 - kappa) * n_old + C_COUNT * s * gate_rel
    a[d] = prior[d] + n_new; k[d] += 1
    return a, k


def report_state(alpha):
    Sa = float(alpha.sum()); Ew = alpha / Sa
    var = alpha * (Sa - alpha) / (Sa ** 2 * (Sa + 1.0))
    ci = np.array([ci_width(alpha, d) for d in range(len(alpha))])
    rank = [int(i) for i in np.argsort(-var)]
    p = np.clip(Ew, 1e-12, 1.0); ent = float(-np.sum(p * np.log(p)))
    return {"Ew": Ew, "per_dim_var": var, "per_dim_ci_width": ci,
            "uncertainty_rank": rank, "uncertainty_rank_dims": [DIMENSION_KEYS[i] for i in rank],
            "Sigma_alpha": Sa, "entropy": ent, "total_var": float(var.sum())}


# ── dense 特徵（features.py，verbatim）──
UNCERTAIN_MARKERS = ("不確定", "不知道", "不太懂", "有點難", "看情況", "可能", "應該", "也許", "大概")
NEGATION_MARKERS = ("不", "不要", "不想", "不能", "沒", "沒有", "無法")
STRONG_PREFERENCE_MARKERS = ("非常", "很重視", "最重要", "一定", "必須", "不能接受", "希望越")
WEAK_PREFERENCE_MARKERS = ("有點", "稍微", "還可以", "不錯", "可以接受", "比較")


def count_markers(text, markers):
    return sum(text.count(m) for m in markers)


def scaled_length(text, denominator=240.0):
    return min(len(text) / denominator, 1.0)


def safe_ratio(count, text):
    return float(count) / max(len(text), 1)


def split_question_answer(input_text):
    qm = "顧問問題："; am = "\n使用者回答："
    if qm in input_text and am in input_text:
        qp, answer = input_text.split(am, 1)
        return qp.replace(qm, "", 1).strip(), answer.strip()
    return "", input_text.strip()


def simple_token_set(text):
    cleaned = text.replace("ETF", " ETF ")
    tokens = {t for t in cleaned.replace("\n", " ").split(" ") if t}
    chars = [c for c in cleaned if not c.isspace()]
    tokens.update("".join(chars[i:i + 2]) for i in range(max(len(chars) - 1, 0)))
    return tokens


def question_answer_similarity(question, answer):
    qt = simple_token_set(question); at = simple_token_set(answer)
    if not qt or not at:
        return 0.0
    return len(qt & at) / len(qt | at)


def compact_dense_features(input_text):
    question, answer = split_question_answer(input_text)
    uc = count_markers(answer, UNCERTAIN_MARKERS); nc = count_markers(answer, NEGATION_MARKERS)
    sc = count_markers(answer, STRONG_PREFERENCE_MARKERS); wc = count_markers(answer, WEAK_PREFERENCE_MARKERS)
    short = 1.0 if len(answer.strip()) < 8 else 0.0
    return np.array([scaled_length(answer), scaled_length(question), safe_ratio(uc, answer),
                     safe_ratio(nc, answer), safe_ratio(sc, answer), safe_ratio(wc, answer),
                     question_answer_similarity(question, answer), short], dtype=np.float32)
