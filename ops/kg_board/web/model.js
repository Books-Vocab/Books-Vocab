const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const labels={dispatchable:{label:"可派工",className:"dispatch",explain:"現在可以安全取得"},held:{label:"進行中",className:"held",explain:"已有 active worktree 認領"},"dependency-blocked":{label:"依賴阻塞",className:"blocked",explain:"blocked_by 仍有未解票"},"needs-grooming":{label:"待梳理",className:"grooming",explain:"CLI list --ungroomed 的直接結果"},"contract-not-ready":{label:"契約未就緒",className:"contract",explain:"已有方向，但 preflight／baseline 不足"},queued:{label:"已入列（生命週期）",className:"queued",explain:"已梳理但尚未 active；此數字會與其他卡重疊"}};
function renderLive(payload){
  const live=payload.live||{},counts=live.counts||{},decision=counts.decision||{},summary=document.getElementById("live-summary");
  const values=[
    ["dispatchable",decision.now||0],
    ["held",decision.inflight||0],
    ["dependency-blocked",decision.blocked||0],
    ["needs-grooming",decision.ungroomed||0],
    ["contract-not-ready",decision.contract_not_ready||0],
    ["queued",decision.queued||0],
  ];
  summary.innerHTML=values.map(([key,value])=>{const item=labels[key];return `<div class="live-card ${item.className}"><strong>${esc(value)}</strong><span>${esc(item.label)}</span><small>${esc(item.explain)}</small></div>`}).join("");
  const audit=live.scope_audit||{},scopeMount=document.getElementById("scope-audit");
  const unknown=Number(audit.unresolved_legacy_text||0)+Number(audit.unresolved_missing||0);
  scopeMount.innerHTML=`<div><strong>Scope audit</strong><p>未結案 ${esc(audit.unresolved||0)} 張：結構化 ${esc(audit.unresolved_structured||0)}、legacy 文字 ${esc(audit.unresolved_legacy_text||0)}、缺值 ${esc(audit.unresolved_missing||0)}。</p></div><p class="${unknown?"warning":""}">${unknown?`目前有 ${unknown} 張未結案票的檔案範圍未知；它們進入 Scope 回填債，不會被猜成碰撞。`:"所有未結案票都有可機讀 Scope。"}</p>`;
  document.getElementById("live-source").textContent=`未結案 ${counts.unresolved||0} · SHA ${String(payload.source?.clone_head||"unknown").slice(0,9)}`;
}
function renderFlow(payload){
  const flow=payload.flow||{};
  document.getElementById("flow-main").innerHTML=(flow.main_path||[]).map(node=>`<div class="flow-node"><strong>${esc(node.chinese)}</strong><span>${esc(node.english)}</span></div>`).join("");
  document.getElementById("flow-branches").innerHTML=(flow.branches||[]).map(branch=>`<article class="flow-branch"><strong>${esc(branch.label)}</strong><p>${esc(branch.when)}</p><code>回到：${esc(branch.returns_to)}</code></article>`).join("");
}
function renderTerms(payload){
  const rows=(payload.terms||[]).map(term=>`<tr><td class="term-english">${esc(term.english)}</td><td class="term-chinese">${esc(term.chinese)}</td><td>${esc(term.definition)}</td><td class="term-rule">${esc(term.rule)}</td></tr>`).join("");
  document.getElementById("terms").innerHTML=`<table class="terms-table"><thead><tr><th>English</th><th>中文</th><th>定義</th><th>判定規則</th></tr></thead><tbody>${rows}</tbody></table>`;
}
async function load(){
  const response=await fetch("/api/model",{cache:"no-store"});
  if(!response.ok)throw new Error(`model HTTP ${response.status}`);
  const payload=await response.json();
  renderLive(payload);renderFlow(payload);renderTerms(payload);
  const freshness=payload.freshness||{};
  document.getElementById("model-trust").textContent=freshness.freshness_state==="current"?"資料已追平":`資料${freshness.freshness_state||"未知"}`;
  document.getElementById("source-note").textContent=`Schema ${payload.schema||"unknown"} · 票面讀取 ${payload.source?.entries_read_at||"unknown"} · backlog CLI：${payload.source?.backlog_cli||"unknown"}`;
}
const showError=error=>{document.getElementById("model-trust").textContent="資料讀取錯誤";document.getElementById("live-summary").innerHTML=`<p class="empty">${esc(error.message)}</p>`};
load().catch(showError);setInterval(()=>load().catch(showError),30000);
