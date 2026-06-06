"use strict";
const $ = (id) => document.getElementById(id);
let lastSnap = null;
let statusTimer = null;
let userName = "";   // 使用者填的名稱（空則 fallback new_user）

async function api(path, body) {
  const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"},
                              body: JSON.stringify(body || {})});
  return r.json();
}
async function getJSON(path) { const r = await fetch(path); return r.json(); }
function esc(s){return (s==null?"":String(s)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}

// 各步驟是否已到達過（用於 stepbar 完成標記 + 允許自由回看；偏好問答永遠可回看，#5）
const reached = {pref: true, run: false, results: false};

function showStage(name) {
  ["pref", "run", "results"].forEach((s, i) => {
    $("stage-" + s).hidden = (s !== name);
    const el = $("stepbar-" + (i + 1));
    el.classList.toggle("active", s === name);
    el.classList.toggle("done", reached[s] && s !== name);
  });
}

// ========== 偏好問答（與語意萃取網頁同一套引擎）==========
function scrollConv() {
  // 等版面重排（輸入框/回饋訊息長高後）再捲到底，確保每次答完都看得到最新題目
  const c = $("conv"); if (!c) return;
  requestAnimationFrame(() => {
    c.scrollTop = c.scrollHeight;
    requestAnimationFrame(() => { c.scrollTop = c.scrollHeight; });
  });
}

function appendConv(role, html, cls) {
  const d = document.createElement("div");
  d.className = "msg " + (cls || role);
  const r = role === "q" ? "顧問" : role === "a" ? (userName || "您") : "系統";
  d.innerHTML = `<div class="role">${r}</div><div class="bubble">${html}</div>`;
  const c = $("conv"); c.appendChild(d); c.scrollTop = c.scrollHeight;
  return d;
}

function renderBelief(s) {
  if (!s) return;
  lastSnap = s;
  $("phase-badge").textContent = s.phase === "reask" ? "重新確認中" : (s.n_covered>=9 ? "完整覆蓋" : "覆蓋中");
  $("phase-badge").className = "badge " + (s.phase==="reask" ? "badge-reask" : "badge-cover");
  $("sigma-val").textContent = (s.Sigma_alpha||0).toFixed(2);
  $("tau-val").textContent = (s.tau||0).toFixed(2);
  $("sigma-fill").style.width = Math.round((s.stop_progress||0)*100) + "%";
  $("cover-val").textContent = `覆蓋 ${s.n_covered||0}/9`;
  $("reask-val").textContent = s.n_reasks ? `重問 ${s.n_reasks}` : "";
  const bars = $("bars"); bars.innerHTML = "";
  (s.ranking||[]).forEach((row, i) => {
    const ew = row.Ew, lo = row.ci90[0], hi = row.ci90[1], top = i===0;
    const div = document.createElement("div");
    div.className = "bar-row";
    div.innerHTML = `
      <div class="bar-label ${top?"top":""}" title="${esc(row.dim_label)}">${esc(row.dim_label)}</div>
      <div class="track">
        <div class="ci-band" style="left:${lo*100}%;width:${Math.max((hi-lo)*100,0)}%"></div>
        <div class="fill ${top?"top":""}" style="width:${ew*100}%"></div>
      </div>
      <div class="bar-val ${top?"top":""}">${ew.toFixed(3)}</div>`;
    bars.appendChild(div);
  });
  $("ci-note").textContent = s.ci_note || "";
}

function renderAction(action) {
  renderBelief(action.snapshot);
  const ia = $("input-area"); ia.innerHTML = "";
  if (action.type === "question") {
    const q = action.q;
    if (q.is_reask) {
      let h = `<span class="tag tag-reask">重新確認</span> ${esc(q.question)}`;
      if (q.reask_reason) h += `<div class="reason">↳ ${esc(q.reask_reason)}</div>`;
      appendConv("q", h, "q");
    } else {
      appendConv("q", `<span class="tag tag-cover">第 ${q.step} 題 · ${esc(q.dim_label)}</span> ${esc(q.question)}`, "q");
    }
    ia.innerHTML = `
      <textarea id="ans" placeholder="請用自然語句具體回答…"></textarea>
      <div class="row">
        <button class="btn" id="send">送出</button>
        <span class="hint" style="margin:0">為求結果完整可信，將完整詢問 9 個面向。</span>
      </div>`;
    $("send").onclick = submitAnswer;
    $("ans").focus();
    $("ans").addEventListener("keydown", e => { if (e.key==="Enter" && (e.metaKey||e.ctrlKey)) submitAnswer(); });
  } else if (action.type === "offer") {
    const card = document.createElement("div");
    card.className = "offer";
    card.innerHTML = `<div class="title">${esc(action.title)}</div><div class="msg">${esc(action.message)}</div>
      <div class="row">
        <button class="btn" id="cont">${esc(action.continue_label)}</button>
        <button class="btn-ghost" id="stop2">${esc(action.stop_label)}</button>
      </div>`;
    ia.appendChild(card);
    $("cont").onclick = () => choose(action.kind, "continue");
    $("stop2").onclick = () => choose(action.kind, "stop");
  } else if (action.type === "done") {
    onPrefDone(action.snapshot, action.reason);
  }
  scrollConv();   // 版面定案後再捲到底（修「答完沒自動到最下面、看不到題目」）
}

async function submitAnswer() {
  const t = $("ans"); if (!t) return;
  const text = t.value.trim(); if (!text) { t.focus(); return; }
  appendConv("a", esc(text), "a");
  $("input-area").innerHTML = `<div class="hint">推論中…（本地 BNN MC-dropout）</div>`;
  const res = await api("/api/pref/answer", {answer: text});
  // 每答一題顯示推估強度 μ 與不確定性 σ（引擎 last_turn 提供）
  const lt = res.last_turn;
  if (lt && lt.mu != null) {
    let fb = `推估強度 μ=<b>${Number(lt.mu).toFixed(2)}</b> · 不確定性 σ=<b>${Number(lt.sigma).toFixed(2)}</b> · 相關度 gate=${Number(lt.gate_rel).toFixed(2)}`;
    if (lt.gate_rel <= 0.8) fb += ` <span class="warn">⚠ 可能離題，已降權</span>`;
    if (lt.flagged_for_reask) fb += `<br><span class="warn">↳ 與您開場理念有些出入，已記下、稍後再確認一次。</span>`;
    if (lt.is_reask) {
      const r = Number(lt.revision || 0);
      const note = Math.abs(r) < 0.05 ? "與先前一致，估計穩定"
        : (r < 0 ? `已下修此面向估計（Δ${r.toFixed(2)}）` : `已上修此面向估計（Δ+${r.toFixed(2)}）`);
      fb += `<br>↳ 重新確認：${note}`;
    }
    appendConv("sys", `<div class="fb">${fb}</div>`, "sys");
  }
  renderAction(res.action);
}

async function choose(kind, decision) {
  const res = await api("/api/pref/choose", {kind, decision});
  renderAction(res.action);
}

function onPrefDone(s, reason) {
  renderBelief(s);
  $("phase-badge").textContent = "已完成"; $("phase-badge").className = "badge badge-done";
  appendConv("sys", `偏好問答完成：${esc(reason||"")}。權重已交付，請至步驟 2 執行分析。`, "sys");
  reached.run = true;
  const ia = $("input-area");
  ia.innerHTML = `<div class="hint">問答已完成。隨時可點上方「① 偏好問答」回來檢視此權重結果。</div>
    <div class="row"><button class="btn" id="to-run">前往執行分析 →</button></div>`;
  $("to-run").onclick = () => showStage("run");
}

async function startSession() {
  userName = (($("uname") || {}).value || "").trim();
  const philo = ($("philo") || {}).value || "";
  $("conv").innerHTML = "";   // 清掉歡迎詞，進入對話
  appendConv("a", esc(philo) || "（未填理念）", "a");
  $("input-area").innerHTML = `<div class="hint">建立個人化先驗中…（首次載入模型約需 30–60 秒，請稍候，這不是當機）</div>`;
  const res = await api("/api/pref/start", {philosophy: philo});
  appendConv("sys", "已依您的理念建立個人化先驗。", "sys");
  renderAction(res.action);
}

// 範例偏好（一鍵帶入）：理念 + 每維對應的示範回答（依 dim_key）
const PRESETS = {
  income: {
    label: "💵 現金流／收入導向",
    philosophy: "我是想要穩定被動現金流的投資人，最重視股息與配息收入，報酬普通就好、不追求高成長，但希望波動與回撤不要太誇張。",
    answers: {
      Return_Div: "我最重視穩定的股息與現金流，希望配息高又穩定，這是我選 ETF 最在意的事。",
      Return_CAGR: "資本增值還好，我不追求高成長，穩穩領息更重要。",
      Risk_Vol: "波動希望溫和一點，但可以接受一些。",
      Risk_MaxDD: "我不喜歡大跌，抗跌中等重要。",
      Cost_ExpRatio: "費用低一點當然好，但不是我的首要考量。",
      Div_Score: "適度分散即可，不用特別追求。",
      Liq_Volume: "成交量普通就好，我不太在意。",
      Liq_AUM: "基金規模普通即可。",
      FinBERT_score: "市場情緒我不太參考。",
      _default: "普通，沒有特別偏好。",
    },
  },
  growth: {
    label: "📈 成長／報酬導向",
    philosophy: "我追求長期資本增值與較高報酬，願意承擔較高的波動，不太在意股息，標的要能充分參與市場成長。",
    answers: {
      Return_CAGR: "我最重視長期資本增值與成長，這是我最在意的，願意為此承擔風險。",
      Return_Div: "股息我不太在意，能成長比較重要。",
      Risk_Vol: "我可以接受較高的波動。",
      Risk_MaxDD: "大跌還能忍受，只要長期能漲。",
      Cost_ExpRatio: "費用普通即可。",
      Div_Score: "分散普通即可。",
      Liq_Volume: "成交量普通即可。",
      Liq_AUM: "基金規模普通即可。",
      FinBERT_score: "市場情緒參考一下就好。",
      _default: "普通，沒有特別偏好。",
    },
  },
  conservative: {
    label: "🛡️ 保守／抗跌",
    philosophy: "我很保守，最怕大跌，希望波動低、抗跌強，報酬普通就好，寧可少賺也不要大賠。",
    answers: {
      Risk_MaxDD: "我最怕大跌，抗跌對我最重要，寧可少賺也不要大賠。",
      Risk_Vol: "波動越低越好，我要睡得安穩。",
      Return_CAGR: "報酬普通就好，不追求高成長。",
      Return_Div: "有一點配息不錯，但不是重點。",
      Cost_ExpRatio: "費用低一點比較好。",
      Div_Score: "希望適度分散降低風險。",
      Liq_Volume: "成交量普通即可。",
      Liq_AUM: "規模大一點比較安心。",
      FinBERT_score: "市場情緒我不太參考。",
      _default: "普通，沒有特別偏好。",
    },
  },
};

async function runPreset(key) {
  const p = PRESETS[key];
  if (!p) return;
  userName = (($("uname") || {}).value || "").trim() || userName;
  $("conv").innerHTML = "";
  appendConv("a", esc(p.philosophy), "a");
  $("input-area").innerHTML = `<div class="hint">套用範例「${esc(p.label)}」，系統自動逐題作答中…（首次載入模型約需 30–60 秒，請稍候，這不是當機）</div>`;
  let r = await api("/api/pref/start", {philosophy: p.philosophy});
  appendConv("sys", `已套用範例「${esc(p.label)}」並建立個人化先驗，將自動回答 9 題。`, "sys");
  let action = r.action, guard = 0;
  while (action && guard++ < 40) {
    if (action.type === "question") {
      const q = action.q;
      const ans = p.answers[q.dim_key] || p.answers._default;
      renderBelief(action.snapshot);
      appendConv("q", `<span class="tag tag-cover">第 ${q.step} 題 · ${esc(q.dim_label)}</span> ${esc(q.question)}`, "q");
      appendConv("a", esc(ans), "a");
      scrollConv();
      action = (await api("/api/pref/answer", {answer: ans})).action;
    } else if (action.type === "offer") {
      action = (await api("/api/pref/choose", {kind: action.kind, decision: "continue"})).action;
    } else if (action.type === "done") {
      onPrefDone(action.snapshot, action.reason);
      action = null;
    } else {
      action = null;
    }
  }
  scrollConv();
}

function initPref() {
  showStage("pref");
  $("conv").innerHTML = `
    <div class="welcome">
      <div class="welcome-h">👋 歡迎使用 ETF 偏好驅動投資組合</div>
      <p>本系統用「投資理念 ＋ 逐題問答」推估你對 <b>9 個 ETF 面向</b>的偏好，再自動建構並回測一個專屬投組，與市場基準 VT 對照。</p>
      <p><b>流程</b>：① <b>偏好問答</b>（回答幾個問題，右側即時更新偏好信念）→ ② <b>執行分析</b>（自動跑 DEA 篩選／最佳化／歷史回測）→ ③ <b>結果呈現</b>（投組權重、績效、vs VT）。</p>
      <p><b>作答建議</b>：用自然語句、<b>具體明確</b>地表達 —— 越重視的面向清楚說它對你多重要、會怎麼影響取捨；不在乎的也直接說願意妥協。<br>
      例如：「我很在意<b>低費用</b>和<b>分散</b>，報酬普通就好，但<b>很怕大跌</b>。」</p>
      <p class="welcome-tip">先在下方填上你的名稱與投資理念，按「開始問答」即可。</p>
    </div>`;
  renderBelief({phase:"coverage",n_covered:0,n_reasks:0,Sigma_alpha:0,tau:2.50,stop_progress:0,ranking:[],ci_note:""});
  $("input-area").innerHTML = `
    <div class="presets">
      <span class="presets-label">範例偏好一鍵帶入：</span>
      <button class="preset-btn" data-preset="income">💵 現金流／收入導向</button>
      <button class="preset-btn" data-preset="growth">📈 成長／報酬導向</button>
      <button class="preset-btn" data-preset="conservative">🛡️ 保守／抗跌</button>
    </div>
    <label class="field"><span>你的名稱（選填，會用在結果標題與資料夾名稱；留空則用 new_user）</span>
      <input id="uname" type="text" placeholder="例如 Jason" autocomplete="off"></label>
    <div class="role field-label">開場：你的投資理念（或直接點上方範例一鍵帶入）</div>
    <textarea id="philo" placeholder="請用幾句話描述您整體的 ETF 投資理念，以及最重視的幾個方向…"></textarea>
    <div class="row"><button class="btn" id="go">開始問答</button></div>
    <div class="hint">本地模型（BGE-M3 ＋ 9 個 1D BNN），不接生成式 LLM。</div>`;
  $("go").onclick = startSession;
  document.querySelectorAll(".preset-btn").forEach(b => { b.onclick = () => runPreset(b.dataset.preset); });
}

// ========== ② 執行分析 ==========
async function runPipeline() {
  $("run-btn").disabled = true;
  $("run-state").textContent = "啟動中…";
  const opts = {fetch: $("opt-fetch").checked, backtest: $("opt-backtest").checked, freq: $("opt-freq").value, name: userName};
  const res = await api("/api/run", opts);
  if (!res.started) { $("run-state").textContent = res.reason || "無法啟動"; $("run-btn").disabled = false; return; }
  $("run-state").textContent = "執行中…（可離開分頁，回來會繼續顯示）";
  if (statusTimer) clearInterval(statusTimer);
  statusTimer = setInterval(pollStatus, 1500);
}

async function pollStatus() {
  const s = await getJSON("/api/status");
  const el = $("run-log");
  el.textContent = s.log || "";
  el.scrollTop = el.scrollHeight;   // 自動跳到最後一行（tail，#3）
  if (s.state === "done") {
    clearInterval(statusTimer); statusTimer = null;
    $("run-state").textContent = "✅ 完成";
    $("run-btn").disabled = false;
    reached.results = true;
    await loadResults();
    showStage("results");
  } else if (s.state === "error") {
    clearInterval(statusTimer); statusTimer = null;
    $("run-state").textContent = "⚠️ 失敗：" + (s.error || "見下方記錄");
    $("run-btn").disabled = false;
  }
}

// ========== ③ 結果呈現（敘事式儀表板）==========
function fmt(v, unit) { return (v == null || isNaN(v)) ? "—" : (v.toFixed(unit === "%0" ? 0 : 2) + (unit && unit !== "" && unit !== "x" ? (unit === "%0" ? "%" : unit) : "")); }

function statCard(label, sysv, vtv, betterHigh, unit, hero) {
  let cls = hero ? "stat-card hero" : "stat-card";
  if (!hero && vtv != null && sysv != null) cls += (betterHigh ? sysv > vtv : sysv < vtv) ? " good" : " bad";
  const cmp = (!hero && vtv != null) ? `VT ${fmt(vtv, unit)}` : (hero ? "（事後偏好分數勝 VT 期數%）" : "");
  return `<div class="${cls}"><div class="k">${esc(label)}</div><div class="v">${fmt(sysv, unit)}</div><div class="cmp">${esc(cmp)}</div></div>`;
}

function renderSummary(m) {
  const box = $("dash-summary");
  if (!m || !m.system) { box.innerHTML = `<p class="muted">本次未產生回測摘要。</p>`; return; }
  const s = m.system, v = m.vt || {};
  box.innerHTML =
    statCard("偏好勝率 win_VT", m.win_vt, null, true, "%0", true) +
    statCard("年化報酬 CAGR", s.cagr, v.cagr, true, "%") +
    statCard("年化波動", s.vol, v.vol, false, "%") +
    statCard("Sharpe", s.sharpe, v.sharpe, true, "") +
    statCard("最大回撤 MaxDD", s.mdd, v.mdd, true, "%");
}

function renderPrefBars(weights) {
  const box = $("dash-pref-bars");
  if (!weights || !weights.length) { box.innerHTML = ""; return; }
  const max = Math.max(...weights.map(w => w.weight), 0.0001);
  const sorted = [...weights].sort((a, b) => b.weight - a.weight);
  box.innerHTML = sorted.map((w, i) => `
    <div class="bar-row">
      <div class="bar-label ${i === 0 ? "top" : ""}">${esc(w.label)}</div>
      <div class="track"><div class="fill ${i === 0 ? "top" : ""}" style="width:${(w.weight / max) * 100}%"></div></div>
      <div class="bar-val ${i === 0 ? "top" : ""}">${w.weight.toFixed(3)}</div>
    </div>`).join("");
}

function renderHoldings(holdings) {
  const box = $("dash-holdings");
  if (!holdings || !holdings.length) { box.innerHTML = `<p class="muted">未找到推薦投組權重。</p>`; return; }
  const max = Math.max(...holdings.map(h => h.weight), 0.0001);
  box.innerHTML = holdings.map(h => `
    <div class="hold-row">
      <div class="hold-etf">${esc(h.etf)}</div>
      <div class="hold-track"><div class="hold-fill" style="width:${(h.weight / max) * 100}%"></div></div>
      <div class="hold-w">${h.weight.toFixed(1)}%</div>
    </div>`).join("");
}

function imgBlock(url, caption) {
  if (!url) return "";
  return `<figure class="fig"><a href="${url}" target="_blank"><img loading="lazy" src="${url}" alt="${esc(caption)}"></a><figcaption>${esc(caption)}</figcaption></figure>`;
}

// 每張關鍵圖下方的簡短說明
const FIG_CAPS = {
  portfolio_performance: "投組淨值與回撤（各策略 vs VT/VOO）：上圖為累積淨值成長，下圖為每日回撤（drawdown）— 可直接看出大跌時系統的回撤深度與復原速度（含最大回撤）。",
  metrics_comparison: "關鍵指標長條對照：各策略 vs VT 的累積報酬 / 年化報酬 / 波動 / Sharpe / 最大回撤（偏好組合＝紅、VT＝藍、其餘＝灰）。",
  backtest_radar: "實現特徵雷達：系統（紅）vs VT（藍），9 維採投組實際實現特徵、跨策略相對位置；越外圈越好，抗跌＝全期最大回撤（與上方摘要一致）。",
  v6: "偏好分數樣本外勝率時序（V-6）：每個再平衡期，系統的事後偏好分數 vs VT / 等權 / 最大夏普；標題的 % 為系統勝過各對照組的期數比例。",
  main_radar: "主系統偏好雷達：本次推薦投組在 9 個偏好維度上的滿足度（單一截面）。",
  weight_evolution: "回測歷史投組權重演化：每次再平衡時各持股的權重，看投組如何隨時間調整（與你的偏好對應）。",
};

function figWide(url, title, capKey) {
  if (!url) return "";
  const desc = FIG_CAPS[capKey] || "";
  return `<figure class="fig-wide"><div class="fig-wide-title">${esc(title)}</div>
    <a href="${url}" target="_blank"><img loading="lazy" src="${url}" alt="${esc(title)}"></a>
    <figcaption class="fig-desc">${esc(desc)}</figcaption></figure>`;
}

function renderBacktest(fm) {
  const box = $("dash-backtest");
  const parts = [
    figWide(fm.portfolio_performance, "投組淨值與回撤 vs VT/VOO", "portfolio_performance"),
    figWide(fm.metrics_comparison, "關鍵指標對照 vs VT", "metrics_comparison"),
    figWide(fm.backtest_radar, "實現特徵雷達：系統 vs VT", "backtest_radar"),
    figWide(fm.v6, "偏好分數樣本外勝率（V-6）", "v6"),
  ].filter(Boolean).join("");
  box.innerHTML = parts || `<p class="muted">本次未產生回測圖。</p>`;
}

async function loadResults() {
  const r = await getJSON("/api/results");
  $("results-dir").textContent = "· " + (userName || (r.user_dir ? r.user_dir.split(/[\\/]/).pop() : ""));
  const d = r.dashboard || {};
  const fm = d.figures_map || {};
  renderSummary(d.metrics);
  renderPrefBars(d.weights);
  $("dash-main-radar").innerHTML = figWide(fm.main_radar, "主系統偏好雷達", "main_radar");
  renderHoldings(d.holdings);
  // #3：推薦投組區補上「回測歷史投組權重演化」圖
  $("dash-holdings").insertAdjacentHTML("beforeend",
    `<div style="margin-top:12px">${figWide(fm.weight_evolution, "回測歷史投組權重演化", "weight_evolution")}</div>`);
  renderBacktest(fm);

  // ④ 完整明細（收合）
  const byGroup = {};
  (r.figures || []).forEach(f => { (byGroup[f.group] = byGroup[f.group] || []).push(f); });
  let html = "";
  Object.keys(byGroup).sort().forEach(g => {
    html += `<div class="fig-group"><div class="fig-group-title">${esc(g)}</div><div class="fig-grid">`;
    byGroup[g].forEach(f => { html += imgBlock(f.url, f.name); });
    html += `</div></div>`;
  });
  $("figures").innerHTML = html || `<p class="muted">沒有其他圖檔。</p>`;
  $("reports").innerHTML = (r.reports || []).map(rep =>
    `<details class="report"><summary>${esc(rep.group)}/${esc(rep.name)}</summary><pre>${esc(rep.text)}</pre></details>`
  ).join("") || `<p class="muted">沒有找到報表。</p>`;
}

// ========== 綁定 ==========
function bind() {
  $("run-btn").onclick = runPipeline;
  $("restart").onclick = () => { location.reload(); };
  // 上方步驟列可點：偏好問答永遠可回看（含已跑完的權重）；執行/結果到達過即可回看（#5）
  const names = ["pref", "run", "results"];
  names.forEach((s, i) => {
    $("stepbar-" + (i + 1)).onclick = () => { if (reached[s]) showStage(s); };
  });
}

bind();
initPref();
