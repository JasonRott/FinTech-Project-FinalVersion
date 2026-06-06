"use strict";
const $ = (id) => document.getElementById(id);
let lastSnap = null;
let statusTimer = null;

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
  const r = role === "q" ? "顧問" : role === "a" ? "您" : "系統";
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
        <button class="btn-ghost" id="stop">結束問答</button>
      </div>`;
    $("send").onclick = submitAnswer;
    $("stop").onclick = () => choose(lastSnap && lastSnap.phase==="reask" ? "T2":"T1", "stop");
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
  const philo = ($("philo") || {}).value || "";
  appendConv("a", esc(philo) || "（未填理念）", "a");
  $("input-area").innerHTML = `<div class="hint">建立個人化先驗中…（首次載入模型可能需數秒）</div>`;
  const res = await api("/api/pref/start", {philosophy: philo});
  appendConv("sys", "已依您的理念建立個人化先驗。", "sys");
  renderAction(res.action);
}

function initPref() {
  showStage("pref");
  $("conv").innerHTML = "";
  renderBelief({phase:"coverage",n_covered:0,n_reasks:0,Sigma_alpha:0,tau:2.50,stop_progress:0,ranking:[],ci_note:""});
  $("input-area").innerHTML = `
    <div class="guide"><b>作答方式</b>　請盡量<b>具體、明確</b>表達偏好：越重視的面向清楚強調，越不在乎的也請說出願意妥協。</div>
    <div class="role" style="margin-bottom:4px">開場</div>
    <textarea id="philo" placeholder="請用幾句話描述您整體的 ETF 投資理念，以及最重視的幾個方向…"></textarea>
    <div class="row"><button class="btn" id="go">開始問答</button></div>
    <div class="hint">本地模型（BGE-M3 + 9 個 1D BNN），不接生成式 LLM。</div>`;
  $("go").onclick = startSession;
}

// ========== ② 執行分析 ==========
async function runPipeline() {
  $("run-btn").disabled = true;
  $("run-state").textContent = "啟動中…";
  const opts = {fetch: $("opt-fetch").checked, backtest: $("opt-backtest").checked, freq: $("opt-freq").value};
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

// ========== ③ 結果呈現 ==========
async function loadResults() {
  const r = await getJSON("/api/results");
  $("results-dir").textContent = r.user_dir ? ("· " + r.user_dir) : "";
  const byGroup = {};
  (r.figures || []).forEach(f => { (byGroup[f.group] = byGroup[f.group] || []).push(f); });
  let html = "";
  Object.keys(byGroup).sort().forEach(g => {
    html += `<div class="fig-group"><div class="fig-group-title">${esc(g)}</div><div class="fig-grid">`;
    byGroup[g].forEach(f => {
      html += `<figure class="fig"><a href="${f.url}" target="_blank"><img loading="lazy" src="${f.url}" alt="${esc(f.name)}"></a>
               <figcaption>${esc(f.name)}</figcaption></figure>`;
    });
    html += `</div></div>`;
  });
  $("figures").innerHTML = html || `<p class="muted">沒有找到圖檔。</p>`;
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
  $("tab-fig").onclick = () => { $("view-fig").hidden=false; $("view-rep").hidden=true;
    $("tab-fig").classList.add("active"); $("tab-rep").classList.remove("active"); };
  $("tab-rep").onclick = () => { $("view-fig").hidden=true; $("view-rep").hidden=false;
    $("tab-rep").classList.add("active"); $("tab-fig").classList.remove("active"); };
}

bind();
initPref();
