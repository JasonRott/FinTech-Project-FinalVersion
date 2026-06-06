"""Phase3Engine（portable 版）：有狀態互動引擎，CLI / 未來網頁版共用後端。

與 #79 定案位元一致（選題/更新/讀出/停止數學全來自 core.py 逐字複製）。
本版加入「B 衝突重問層」（在定案之上，不改定案數學）：
  選題 hybrid-EIG 覆蓋 → 首答 E5d signed 先驗矛盾【只標記】→ 覆蓋完進 T3 重問裁決
  （只重問被標記衝突維，每維上限 1、全程上限 4，題庫換句）→ Semantics C 的 κ 裁決
  （一致→累積收窄 CI、矛盾→遺忘+CI 變寬，此前 κ 因不重問而休眠）。
停止三層：T1 Σα≥τ（排序，提議停，不動）/ T2 覆蓋到 9（不在 9 硬停）/
  T3 衝突清空 或 信念穩定(ΔE[w]<ε) 或 硬上限。LLM 開口預設關閉。
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import torch
from scipy.stats import beta as Beta

from .core import (
    DIMENSION_KEYS, PhilHead, load_1d_model, mc_predict_with_uncertainty_scores, calibrated_sigma,
    beig_select, prior_dominance, semC_gated, temp_scale, report_state, unit, compact_dense_features,
)
from .encoder import safe_encode, get_encoder

APP_DIR = Path(__file__).resolve().parents[1]
ASSETS = APP_DIR / "assets"
ENCODER_PATH = APP_DIR / "encoder_model" / "bge-m3"
BNN_DIR = ASSETS / "bnn"
CALIB_PATH = ASSETS / "uncertainty_calibration_params.json"
BNN_SUFFIX = "_gemini10_multitask_mc_dropout.pt"

# ── 重問層常數（新增；非 #79 凍結，可調）──
CONF_HI, CONF_LO = 0.6, 0.3          # 答案強度「高/低」門檻（用於先驗矛盾偵測）
REASK_CAP_PER_DIM = 1                 # 每維最多重問次數
GLOBAL_REASK_CAP = 4                  # 全程最多重問次數
HARDCAP_TURNS = 13                    # 總題數硬上限（9 覆蓋 + 最多 4 重問）

# ── 讀出層 warm-start（新增；非 #79 凍結，可調；覆蓋滿 9 維時全部歸零 → k=9 與 #79 位元一致）──
WARM_BETA0 = 8.0                      # 往 prior 收縮的均勻底起始強度（覆蓋 0 最大、線性遞減到 0）；越大早期越貼 prior

DIM_LABELS = {
    "Return_CAGR": "資本增值 / 長期報酬成長", "Return_Div": "股息 / 穩定現金流",
    "Risk_Vol": "價格波動小 / 穩健", "Risk_MaxDD": "抗跌 / 避免重大虧損",
    "Cost_ExpRatio": "費用率 / 管理成本", "Liq_Volume": "成交量 / 流動性",
    "Liq_AUM": "基金規模 / 穩定性", "Div_Score": "持股 / 產業分散度",
    "FinBERT_score": "市場情緒 / 新聞語氣",
}


class Phase3Engine:
    def __init__(self, device: str | None = None, enable_llm: bool = False):
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.enable_llm = enable_llm
        cfg = json.loads((ASSETS / "config.json").read_text(encoding="utf-8"))
        self.cfg = cfg
        self.a_prior = float(cfg["a_prior"]); self.T = float(cfg["readout_temp_T"]); self.tau = float(cfg["stop_tau"])
        self.M_foc = float(cfg["M_foc"]); self.M_bal = float(cfg["M_bal"]); self.conc_med = float(cfg["conc_med"])
        self.mc_passes = int(cfg["mc_passes"])

        ph = torch.load(ASSETS / "philhead.pt", map_location=self.device, weights_only=False)
        self.philhead = PhilHead(ph["in_dim"], ph["hidden"], ph["dropout"]).to(self.device)
        self.philhead.load_state_dict(ph["state_dict"]); self.philhead.eval()
        self.phil_xm = ph["xm"].astype(np.float32); self.phil_xs = ph["xs"].astype(np.float32)

        g = np.load(ASSETS / "gate_assets.npz", allow_pickle=True)
        self.cent = g["centroids"].astype(np.float64); self.c_hi = float(g["c_hi"]); self.c_lo = float(g["c_lo"])

        self.pool = json.loads((ASSETS / "question_pool.json").read_text(encoding="utf-8"))
        self.canonical = json.loads((ASSETS / "canonical_questions.json").read_text(encoding="utf-8"))

        self.bnn = {d: load_1d_model(BNN_DIR / f"{dim}{BNN_SUFFIX}", self.device)
                    for d, dim in enumerate(DIMENSION_KEYS)}
        self.calib = json.loads(CALIB_PATH.read_text(encoding="utf-8"))

        get_encoder(ENCODER_PATH, device=("cuda" if self.device.type == "cuda" else "cpu"))
        self._reset_state()

    # ---------- gate ----------
    def _rel(self, cos):
        return float(np.clip((cos - self.c_lo) / max(self.c_hi - self.c_lo, 1e-6),
                             float(self.cfg["rel_min"]), 1.0))

    # ---------- 編碼 / 推論 ----------
    def _encode_turn(self, question, answer):
        input_text = f"顧問問題：{question}\n使用者回答：{answer}"
        sem, _ = safe_encode([input_text], ENCODER_PATH, on_overflow="raise", normalize=True)
        sem = sem[0].astype(np.float32)
        dense = compact_dense_features(input_text).astype(np.float32)
        return np.concatenate([sem, dense]).astype(np.float32), sem.astype(np.float64)

    def _bnn_mu(self, d, feat):
        x = torch.from_numpy(feat[None, :]).float().to(self.device)
        mu_t, raw_t, _, _, ent_t, _ = mc_predict_with_uncertainty_scores(self.bnn[d], x, passes=self.mc_passes)
        mu = float(mu_t.detach().cpu().numpy()[0])
        sig = float(calibrated_sigma(raw_t.detach().cpu().numpy().astype(np.float64),
                                     ent_t.detach().cpu().numpy().astype(np.float64),
                                     self.calib[DIMENSION_KEYS[d]])[0])
        return mu, sig

    # ---------- E5d 先驗矛盾監視（[監視]：只標記、不餵更新）----------
    def _prior_conflict(self, d, mu):
        p0 = self.p0
        med = float(np.median(p0)); top3 = {int(i) for i in np.argsort(-p0)[:3]}
        if mu >= CONF_HI and float(p0[d]) < med:
            return True, f"您表達很重視（強度 {mu:.2f}），但開場理念顯示這不是您的重點 → 再確認一次"
        if mu <= CONF_LO and d in top3:
            return True, f"您表達不太在意（強度 {mu:.2f}），但開場理念顯示這是您的重點 → 再確認一次"
        return False, None

    # ---------- 會話 ----------
    def _reset_state(self):
        self.started = False
        self.p0 = self.prior = self.pdom = self.alpha = None
        self.kcnt = np.zeros(9)
        self.asked = []                       # 完整逐輪維度（含重問，可重複）
        self.asked_questions = set(); self.history = []
        self.switched = False; self.prev_ew = None; self.last_dE = None; self.pending = None
        self.conflict_flags = []              # 被先驗監視標記、待 T3 重問的維
        self.reask_count = np.zeros(9, int)
        self._flag_reason = {}
        self.phase = "coverage"               # coverage → reask
        self.read_mu = np.zeros(9)            # 每維目前強度讀數（首答；重問依同向確認/反向修正規則更新）
        self.read_rel = np.zeros(9)           # 對應 gate 可靠度

    def start_session(self, philosophy_text):
        self._reset_state()
        text = (philosophy_text or "").strip()
        if text:
            emb, _ = safe_encode([text], ENCODER_PATH, on_overflow="raise", normalize=True)
            x = ((emb.astype(np.float32) - self.phil_xm) / self.phil_xs).astype(np.float32)
            with torch.no_grad():
                p0 = self.philhead(torch.from_numpy(x).float().to(self.device)).cpu().numpy()[0]
        else:
            p0 = np.full(9, 1.0 / 9)
        self.p0 = np.asarray(p0, np.float64)
        self.prior = self.a_prior * self.p0
        self.pdom = prior_dominance(self.p0)
        self.alpha = self.prior.copy()
        self.prev_ew = self.alpha / self.alpha.sum()
        self.started = True
        return self.snapshot(stage="start")

    def _pick_question(self, dim):
        """canonical 優先；已問過則從題庫換句、跳已問。"""
        canon = self.canonical[dim]
        if canon not in self.asked_questions:
            return f"canonical_{dim}", canon, "canonical"
        it = next((x for x in self.pool[dim] if x["question"] not in self.asked_questions), None)
        if it is None:
            return f"canonical_{dim}", canon, "canonical_repeat"
        return it["qid"], it["question"], "pool"

    def t3_pending(self):
        return [d for d in self.conflict_flags if self.reask_count[d] < REASK_CAP_PER_DIM]

    def next_question(self):
        assert self.started, "請先 start_session"
        asked_set = set(self.asked)
        cand = [d for d in range(9) if d not in asked_set]
        if cand:
            # ── T1/T2 覆蓋階段：hybrid 2側EIG → plateau argmin ──
            self.phase = "coverage"
            step = len(self.asked)
            if (not self.switched and step >= int(self.cfg["plateau_minsteps"])
                    and self.last_dE is not None and self.last_dE < float(self.cfg["plateau_delta"])):
                self.switched = True
            d = int(min(cand, key=lambda x: self.alpha[x])) if self.switched \
                else beig_select(self.alpha, self.pdom, cand, two_sided=True)
            sel = "argmin_alpha(plateau)" if self.switched else "two_sided_EIG"
            reask_reason, is_reask = None, False
        else:
            # ── T3 重問裁決：只重問被標記衝突維（B），上限/穩定/硬上限即停 ──
            self.phase = "reask"
            pend = self.t3_pending()
            n_reasks = int(self.reask_count.sum())
            # T3 停止＝衝突清空（被標記維各重問一次）；信念穩定為自然結果。上限/硬上限封頂。
            if (not pend) or n_reasks >= GLOBAL_REASK_CAP or len(self.asked) >= HARDCAP_TURNS:
                return None
            d = pend[0]; sel = "reask_conflict"; reask_reason = self._flag_reason.get(d); is_reask = True
        dim = DIMENSION_KEYS[d]
        if is_reask:
            # 保守：重問沿用 canonical 問法（與前九題一致 → gate-safe → mu 可靠）。
            # gate 低代表模型對該答案解釋力低、mu 也不可信，故不換成低 gate 的題庫問法、不繞過 gate。
            qid, question, src = f"canonical_{dim}", self.canonical[dim], "canonical_reask"
        else:
            qid, question, src = self._pick_question(dim)
        self.pending = (d, qid, question)
        return {"step": len(self.asked) + 1, "dim_index": d, "dim_key": dim, "dim_label": DIM_LABELS[dim],
                "question": question, "qid": qid, "question_source": src, "selection": sel,
                "is_reask": is_reask, "reask_reason": reask_reason, "phase": self.phase}

    def submit_answer(self, answer_text):
        assert self.pending is not None, "沒有待答題（請先 next_question）"
        d, qid, question = self.pending
        is_reask = d in set(self.asked)                       # 此維之前已答過 → 這是重問
        feat, turn_sem = self._encode_turn(question, answer_text)
        mu, sig = self._bnn_mu(d, feat)
        cos = float(unit(turn_sem) @ self.cent[d]); gate_rel = self._rel(cos)
        # 證據更新（質量恆等「一次測量」c·mu·rel，重問不累加/不翻倍）：
        #   覆蓋(首答)：mu_d=mu → α_d=prior+c·mu·rel，與 #79 κ=0 逐位元相同。
        #   重問：同向(都≥0.5或都<0.5)＝確認 → 取較果斷讀數(兩高 max/兩低 min)，不因再確認而下修；
        #         反向(跨 0.5)＝矛盾 → 以重問為準(修正)。
        c = float(self.cfg["c_count"])
        if is_reask:
            mu1 = float(self.read_mu[d])
            if (mu1 >= 0.5) == (mu >= 0.5):
                mu_d = max(mu1, mu) if mu >= 0.5 else min(mu1, mu)
                rel_d = max(float(self.read_rel[d]), gate_rel)
            else:
                mu_d, rel_d = mu, gate_rel
            revision = float(mu_d - mu1)             # 強度估計移動量（顯示用）
        else:
            mu_d, rel_d, revision = mu, gate_rel, 0.0
        self.read_mu[d] = mu_d; self.read_rel[d] = rel_d
        self.alpha[d] = self.prior[d] + c * mu_d * rel_d
        self.asked.append(d); self.asked_questions.add(question); self.pending = None
        flagged_now = False
        if is_reask:
            self.reask_count[d] += 1
        else:
            f, reason = self._prior_conflict(d, mu)
            if f and d not in self.conflict_flags:
                self.conflict_flags.append(d); self._flag_reason[d] = reason; flagged_now = True
        ew_raw = self.alpha / self.alpha.sum()
        self.last_dE = float(np.abs(ew_raw - self.prev_ew).sum()); self.prev_ew = ew_raw
        turn = {"dim_key": DIMENSION_KEYS[d], "dim_label": DIM_LABELS[DIMENSION_KEYS[d]], "answer": answer_text,
                "mu": round(mu, 4), "sigma": round(sig, 4), "gate_cos": round(cos, 4),
                "gate_rel": round(gate_rel, 4), "revision": round(revision, 4),
                "is_reask": is_reask, "flagged_for_reask": flagged_now,
                "flag_reason": (self._flag_reason.get(d) if flagged_now else None)}
        self.history.append(turn)
        snap = self.snapshot(stage="turn"); snap["last_turn"] = turn
        return snap

    # ---------- 讀出 ----------
    def _warm_params(self):
        """讀出層 warm-start：β·p0 往先驗收縮（覆蓋滿→β=0→#79）；溫度恆 T=readout_temp_T(0.4)，
        故 prior 顯示＝temp_scale(p0,0.4)（與 #79/CLI 完全一致），早期溫和靠 β·p0。"""
        frac = (9 - len(set(self.asked))) / 9.0
        return WARM_BETA0 * frac, self.T

    def _readout(self):
        """E[w] + 90% CI（含 warm-start：往 prior 形狀收縮 β·p0、覆蓋退火溫度 T_eff）。"""
        beta, T_eff = self._warm_params()
        # 往 prior p0 收縮（非均勻）→ 覆蓋0時 a_disp=(a+β)·p0 → 顯示恰為 p0（不壓平 prior）；
        # 早期未測維留在 prior 隱含值（非 0、非均勻）；覆蓋滿 β=0 → 與 #79 位元一致。
        a_disp = self.alpha + beta * self.p0
        ew_raw = a_disp / a_disp.sum()
        ew = temp_scale(ew_raw[None, :], T_eff)[0]
        conc = float(ew_raw.max())
        M = self.M_foc if conc >= self.conc_med else self.M_bal
        cal = temp_scale(ew_raw[None, :], T_eff)[0] * M
        lo = np.nan_to_num(Beta.ppf(0.05, cal, M - cal)); hi = np.nan_to_num(Beta.ppf(0.95, cal, M - cal))
        return ew, lo, hi, M

    def should_stop(self):
        """T1：Σα≥τ（排序操作點，提議停；不動 #79 定案）。"""
        return self.started and len(self.asked) >= 1 and float(self.alpha.sum()) >= self.tau

    def all_covered(self):
        return len(set(self.asked)) >= 9

    def snapshot(self, stage="turn"):
        ew, lo, hi, M = self._readout()                  # 含 warm-start（覆蓋滿時＝#79）
        st = report_state(self.alpha)                    # 不確定性排行用真實 α
        order = list(np.argsort(-ew))
        ci_trust = self.all_covered()
        return {
            "stage": stage, "phase": self.phase, "n_asked": len(self.asked),
            "n_covered": len(set(self.asked)), "n_reasks": int(self.reask_count.sum()),
            "pending_conflicts": [DIMENSION_KEYS[d] for d in self.t3_pending()],
            "Sigma_alpha": round(float(self.alpha.sum()), 4), "tau": self.tau,
            "stop_progress": round(min(float(self.alpha.sum()) / self.tau, 1.0), 3),
            "should_stop": self.should_stop(),
            "Ew": {DIMENSION_KEYS[d]: round(float(ew[d]), 4) for d in range(9)},
            "ranking": [{"rank": r + 1, "dim_key": DIMENSION_KEYS[d], "dim_label": DIM_LABELS[DIMENSION_KEYS[d]],
                         "Ew": round(float(ew[d]), 4), "ci90": [round(float(lo[d]), 4), round(float(hi[d]), 4)]}
                        for r, d in enumerate(order)],
            "uncertainty_rank_dims": st["uncertainty_rank_dims"], "ci_M": M, "ci_trustworthy": ci_trust,
            "ci_note": ("完整 9 題，CI 已校準可信（#79 coverage≈0.869）" if ci_trust
                        else "早停 CI 不可信（未問維仍為先驗；需完整 9 題，#79 限制）"),
        }

    # LLM 開口（預設關閉，保留未來擴充）
    def _llm_generate_question(self, dim_key, snapshot):
        raise NotImplementedError("LLM 出題開口關閉（enable_llm=False）。現走凍結題庫。")

    def _llm_interpret_answer(self, question, answer):
        raise NotImplementedError("LLM 解讀答案開口關閉（enable_llm=False）。現走本地 1D BNN。")
