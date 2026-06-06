"use strict";
const $ = (id) => document.getElementById(id);
let lastSnap = null;

async function api(path, body) {
  const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"},
                              body: JSON.stringify(body || {})});
  return r.json();
}
function esc(s){return (s==null?"":String(s)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}

function scrollConv(){
  // 等版面重排（輸入框長高後）再捲到底，確保看得到最新訊息
  requestAnimationFrame(() => { const c = $("conv"); if (c) c.scrollTop = c.scrollHeight; });
}

function appendConv(role, html, cls) {
  const d = document.createElement("div");
  d.className = "msg " + (cls || role);
  const r = role === "q" ? "顧問" : role === "a" ? "您" : "系統";
  d.innerHTML = `<div class="role">${r}</div><div class="bubble">${html}</div>`;
  const c = $("conv"); c.appendChild(d); c.scrollTop = c.scrollHeight;
  return d;
}

// ---------- 信念面板 ----------
function renderBelief(s) {
  if (!s) return;
  lastSnap = s;
  $("phase-badge").textContent = s.phase === "reask" ? "重新確認中" : (s.n_covered>=9 ? "完整覆蓋" : "覆蓋中");
  $("phase-badge").className = "badge " + (s.phase==="reask" ? "badge-reask" : "badge-cover");
  $("sigma-val").textContent = s.Sigma_alpha.toFixed(2);
  $("tau-val").textContent = s.tau.toFixed(2);
  $("sigma-fill").style.width = Math.round(s.stop_progress*100) + "%";
  $("cover-val").textContent = `覆蓋 ${s.n_covered}/9`;
  $("reask-val").textContent = s.n_reasks ? `重問 ${s.n_reasks}` : "";

  const bars = $("bars"); bars.innerHTML = "";
  s.ranking.forEach((row, i) => {
    const ew = row.Ew, lo = row.ci90[0], hi = row.ci90[1], top = i===0;
    const div = document.createElement("div");
    div.className = "bar-row";
    div.innerHTML = `
      <div class="bar-label ${top?"top":""}" title="${esc(row.dim_label)}">${esc(row.dim_label)}</div>
      <div class="track">
        <div class="ci-band" style="left:${lo*100}%;width:${Math.max((hi-lo)*100,0)}%"></div>
        <div class="ci-cap" style="left:${lo*100}%"></div>
        <div class="ci-cap" style="left:${hi*100}%"></div>
        <div class="fill ${top?"top":""}" style="width:${ew*100}%"></div>
      </div>
      <div class="bar-val ${top?"top":""}">${ew.toFixed(3)}</div>`;
    bars.appendChild(div);
  });

  $("pending").innerHTML = (s.pending_conflicts && s.pending_conflicts.length)
    ? `待確認：` + s.pending_conflicts.map(x=>`<span class="chip">${esc(x)}</span>`).join("")
    : "";
  $("ci-note").textContent = s.ci_note || "";
}

// ---------- 流程 ----------
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
        <button class="btn-ghost" id="stop">結束訪談</button>
      </div>`;
    $("send").onclick = submitAnswer;
    $("stop").onclick = () => renderFinal(lastSnap, "您主動結束");
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
    renderFinal(action.snapshot, action.reason);
  }
  scrollConv();   // 版面定案後再捲到底（修「答完沒自動到最下面」）
}

async function submitAnswer() {
  const t = $("ans"); if (!t) return;
  const text = t.value.trim(); if (!text) { t.focus(); return; }
  appendConv("a", esc(text), "a");
  $("input-area").innerHTML = `<div class="hint">推論中…（本地 BNN MC-dropout）</div>`;
  const res = await api("/api/answer", {answer: text});
  const lt = res.last_turn;
  if (lt) {
    let fb = `推估強度 μ=<span class="hi">${lt.mu.toFixed(2)}</span> · 相關度 gate=${lt.gate_rel.toFixed(2)}`;
    if (lt.gate_rel <= 0.8) fb += ` <span class="warn">⚠ 可能離題，已降權</span>`;
    if (lt.flagged_for_reask) fb += `<br><span class="warn">↳ 與您開場理念有些出入，已記下、稍後再確認一次。</span>`;
    if (lt.is_reask) {
      const r = lt.revision;
      const note = Math.abs(r) < 0.05 ? `<span class="good">與先前一致，估計穩定</span>`
                 : (r < 0 ? `已下修此面向估計（Δ${r.toFixed(2)}）` : `已上修此面向估計（Δ+${r.toFixed(2)}）`);
      fb += `<br>↳ 重新確認：${note}（修正，非重複計分）`;
    }
    appendConv("sys", `<div class="fb">${fb}</div>`, "sys");
  }
  renderAction(res.action);
}

async function choose(kind, decision) {
  const res = await api("/api/choose", {kind, decision});
  renderAction(res.action);
}

function renderFinal(s, reason) {
  renderBelief(s);
  $("phase-badge").textContent = "已完成"; $("phase-badge").className = "badge badge-done";
  const rows = s.ranking.map(r =>
    `<tr><td>${r.rank}.</td><td>${esc(r.dim_label)}</td><td><b>${r.Ew.toFixed(3)}</b></td>
     <td>90%CI [${r.ci90[0].toFixed(2)}, ${r.ci90[1].toFixed(2)}]</td></tr>`).join("");
  let cav = `<div class="caveat">CI 可信度：${esc(s.ci_note)}`;
  if (s.n_covered < 9) cav += `<br>※ 早停（排序模式）：排序通常已穩定，完整量級與可信 CI 需覆蓋完 9 面向。`;
  cav += `<br>※ 自由打字屬自然語氣，語言→強度天花板約 spearman 0.45–0.47（結構性，非錯誤）。</div>`;
  const concl = `<div class="final">
      <h3>您的 ETF 偏好權重（總和=1）</h3>
      <div class="reason">${esc(reason)}　Σα=${s.Sigma_alpha.toFixed(2)}　CI 校準 M=${s.ci_M}</div>
      <table>${rows}</table>${cav}
      <div class="row"><button class="btn" id="again">重新開始</button></div></div>`;
  const hist = $("conv") ? $("conv").innerHTML : "";
  document.querySelector(".conv-panel").innerHTML = `
    <div class="tabbar">
      <button class="tab active" id="tabC">📊 結論</button>
      <button class="tab" id="tabH">💬 對話內容</button>
    </div>
    <div id="viewC" class="view">${concl}</div>
    <div id="viewH" class="view" hidden>${hist}</div>`;
  $("tabC").onclick = () => { $("viewC").hidden = false; $("viewH").hidden = true;
    $("tabC").classList.add("active"); $("tabH").classList.remove("active"); };
  $("tabH").onclick = () => { $("viewC").hidden = true; $("viewH").hidden = false;
    $("tabH").classList.add("active"); $("tabC").classList.remove("active");
    $("viewH").scrollTop = $("viewH").scrollHeight; };
  $("again").onclick = init;
}

// ---------- 開場 ----------
function resetPanel() {
  document.querySelector(".conv-panel").innerHTML =
    `<div id="conv" class="conv"></div><div id="input-area" class="input-area"></div>`;
}

function init() {
  resetPanel();
  $("conv").innerHTML = "";
  renderBelief({phase:"coverage",n_covered:0,n_reasks:0,Sigma_alpha:0.0,tau:2.50,stop_progress:0,
                ranking:[],pending_conflicts:[],ci_note:""});
  $("input-area").innerHTML = `
    <div class="guide">
      <b>作答方式</b>　請盡量<b>具體、明確</b>地表達您的偏好：<br>
      ・對您越重視的面向：清楚強調它對您有多重要、會如何影響您的選擇與取捨。<br>
      ・對您越不在乎的面向：也請明確說出您願意妥協、不太在意。
    </div>
    <div class="role" style="margin-bottom:4px">開場</div>
    <textarea id="philo" placeholder="請用幾句話描述您整體的 ETF 投資理念，以及您最重視的幾個方向…"></textarea>
    <div class="row"><button class="btn" id="go">開始訪談</button></div>
    <div class="hint">首次啟動會載入本地模型（BGE-M3 + 9 個 1D BNN），請稍候數秒。不連網、不接生成式 LLM。</div>`;
  $("go").onclick = startSession;
}

async function startSession() {
  const philo = ($("philo") || {}).value || "";
  appendConv("a", esc(philo) || "（未填理念）", "a");
  $("input-area").innerHTML = `<div class="hint">建立個人化先驗中…（載入模型可能需數秒）</div>`;
  const res = await api("/api/start", {philosophy: philo});
  appendConv("sys", "已依您的理念建立個人化先驗。", "sys");
  renderAction(res.action);
}

init();
