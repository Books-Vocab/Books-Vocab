const csrf=document.querySelector('meta[name="kg-csrf"]').content;
const revision=document.querySelector('meta[name="kg-app-revision"]').content;
const tabs=[...document.querySelectorAll('[data-tab]')];
let data=null,tab="now",query="";
const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));

function metric(label,value){return `<div class="metric"><b>${value}</b><span>${label}</span></div>`}
function setTrust(freshness){
  const state=freshness.freshness_state||"unknown";
  const labels={current:"資料已追平",stale:"資料有落差",error:"資料讀取錯誤",unknown:"新鮮度未知"};
  document.getElementById("trust-state").textContent=labels[state]||labels.unknown;
  document.getElementById("trust-detail").textContent=
    `clone 落後 ${freshness.clone_behind_origin??"未知"} · 本機領先 ${freshness.local_ahead??"未知"} · app ${revision.slice(0,9)}`;
}
function rows(){
  const dispatchIds=new Set(data.dispatch_ids),blockedIds=new Set(data.blocked_ids),deferredIds=new Set(data.deferred_ids);
  const source=tab==="now"?data.board.filter(row=>dispatchIds.has(row.id)&&!deferredIds.has(row.id)):
    tab==="blocked"?data.board.filter(row=>blockedIds.has(row.id)):
    tab==="inflight"?data.board.filter(row=>row.held):data.board;
  const needle=query.trim().toLowerCase();
  return needle?source.filter(row=>`${row.id} ${row.brief} ${row.detail}`.toLowerCase().includes(needle)):source;
}
function ticket(row){
  return `<article class="ticket" data-id="${esc(row.id)}">
    <h2>${esc(row.id)} · ${esc(row.brief||"尚無摘要")}</h2>
    <div class="meta"><span>${esc(row.severity)}</span><span>${esc(row.stream)}</span><span>${row.held?"進行中":row.ready?"已梳理":"待梳理"}</span></div>
    <p>${esc(row.detail||"沒有更多說明")}</p>
    <div class="actions" aria-label="${esc(row.id)} 個人排序操作">
      <button type="button" data-action="pin">${row.pinned?"取消釘選":"釘選"}</button>
      <button type="button" data-action="rank">排序</button>
      <button type="button" data-action="snooze">${row.snoozed?"取消延後":"延後"}</button>
    </div>
  </article>`;
}
function render(){
  if(!data)return;
  const decision=data.counts.decision;
  document.getElementById("metrics").innerHTML=
    metric("可開始",decision.now)+metric("進行中",decision.inflight)+
    metric("被阻擋",decision.blocked)+metric("待梳理",decision.ungroomed);
  const history=data.counts.history;
  document.getElementById("history").textContent=`total ${history.total} · fixed ${history.fixed} · wont-fix ${history.wont_fix}`;
  tabs.forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.tab===tab)));
  const visible=rows();
  const deferred=decision.deferred;
  document.getElementById("status").textContent=tab==="now"&&deferred?
    `${visible.length} 張現在可見 · ${deferred} 張已延後（可在全部取消）`:`${visible.length} 張票`;
  document.getElementById("tickets").innerHTML=visible.length?visible.map(ticket).join(""):'<p class="empty">這裡目前沒有票</p>';
}
async function load(){
  const response=await fetch("/api/board",{cache:"no-store"});
  if(!response.ok)throw new Error(`board HTTP ${response.status}`);
  data=await response.json();setTrust(data.freshness);render();
}
async function postPriority(payload){
  const response=await fetch("/api/priority",{method:"POST",headers:{"Content-Type":"application/json","X-KG-CSRF":csrf},body:JSON.stringify(payload)});
  if(!response.ok)throw new Error((await response.json()).error||`write HTTP ${response.status}`);
  await load();
}
document.getElementById("tabs").addEventListener("click",event=>{
  const button=event.target.closest("[data-tab]");if(!button)return;tab=button.dataset.tab;render();
});
document.getElementById("search").addEventListener("input",event=>{query=event.target.value;render()});
document.getElementById("tickets").addEventListener("click",async event=>{
  const button=event.target.closest("[data-action]");if(!button)return;
  const row=data.board.find(item=>item.id===button.closest("[data-id]").dataset.id);if(!row)return;
  button.disabled=true;
  try{
    if(button.dataset.action==="pin")await postPriority({id:row.id,pinned:!row.pinned});
    if(button.dataset.action==="snooze")await postPriority({id:row.id,snooze_days:row.snoozed?0:7});
    if(button.dataset.action==="rank"){
      const value=window.prompt("排序數字（越小越前）",row.rank??"");
      if(value!==null&&value.trim()!=="")await postPriority({id:row.id,rank:Number(value)});
    }
  }catch(error){document.getElementById("status").textContent=error.message}finally{button.disabled=false}
});
load().catch(error=>{document.getElementById("trust-state").textContent="看板載入失敗";document.getElementById("trust-detail").textContent=error.message});
setInterval(load,30000);
