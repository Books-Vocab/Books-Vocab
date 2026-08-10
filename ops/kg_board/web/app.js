const revision=document.querySelector('meta[name="kg-app-revision"]').content;
const tabs=[...document.querySelectorAll('[data-tab]')];
let board=null,history=null,tree=null,tab="now",query="";
const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const shortSha=sha=>String(sha||"").slice(0,9);

function metric(label,value){return `<div class="metric"><b>${esc(value)}</b><span>${esc(label)}</span></div>`}
function setTrust(freshness){
  const state=freshness.freshness_state||"unknown";
  const labels={current:"資料已追平",stale:"資料有落差",error:"資料讀取錯誤",unknown:"新鮮度未知"};
  const treeState=freshness.git_tree_state||"unknown";
  document.getElementById("trust-state").textContent=labels[state]||labels.unknown;
  document.getElementById("trust-detail").textContent=
    `tree ${treeState} · mirror ${freshness.git_tree_age??"未知"}s · app ${revision.slice(0,9)}`;
}
function statusOf(row){
  if(row.held)return "進行中";
  if(!row.ready)return "待梳理";
  if(board.blocked_ids.includes(row.id))return "阻塞";
  return "可派工";
}
function rows(){
  const blocked=new Set(board.blocked_ids);
  const source=tab==="now"?board.board.filter(row=>board.dispatch_ids.includes(row.id)):
    tab==="blocked"?board.board.filter(row=>blocked.has(row.id)):
    tab==="inflight"?board.board.filter(row=>row.held):
    tab==="ungroomed"?board.board.filter(row=>!row.ready):
    tab==="history"?(history?.board||[]):board.board;
  const needle=query.trim().toLowerCase();
  return needle?source.filter(row=>`${row.id} ${row.brief} ${row.detail}`.toLowerCase().includes(needle)):source;
}
function detailBody(row){
  return `<div class="meta"><span>${esc(row.stream)}</span><span>${esc(row.held?.branch||"尚未掛入 worktree")}</span><span>${esc(row.area||"未標定")}</span></div>
    <p>${esc(row.detail||"沒有更多技術說明")}</p>
    <dl class="detail-grid">
      <dt>Scope</dt><dd>${esc(row.scope||"—")}</dd>
      <dt>Plan</dt><dd>${esc(row.plan||"—")}</dd>
      <dt>Fix site</dt><dd><code>${esc(row.fix_site||"—")}</code></dd>
      <dt>Acceptance</dt><dd>${esc(row.acceptance||"—")}</dd>
    </dl>`;
}
function ticket(row){
  return `<article class="ticket" id="ticket-${esc(row.id)}" data-id="${esc(row.id)}">
    <details data-ticket-details="${esc(row.id)}" data-inline="${row.status?"true":"false"}">
      <summary>
        <span class="ticket-title"><code>${esc(row.id)}</code><span>${esc(row.brief||"尚未提供白話摘要")}</span></span>
        <span class="ticket-meta"><span class="chip severity-${esc(row.severity)}">${esc(row.severity)}</span><span>${esc(statusOf(row))}</span></span>
      </summary>
      <div class="ticket-body">${row.status?detailBody(row):'<p class="loading-detail">展開後載入詳細資料…</p>'}</div>
    </details>
  </article>`;
}
async function hydrateTicket(details){
  const body=details.querySelector(".ticket-body");
  if(!details.open||details.dataset.loaded||details.dataset.inline==="true"||!body)return;
  details.dataset.loaded="loading";
  try{
    const response=await fetch(`/api/ticket/${encodeURIComponent(details.dataset.ticketDetails)}`,{cache:"no-store"});
    if(!response.ok)throw new Error(`ticket HTTP ${response.status}`);
    const payload=await response.json();
    if(!payload.ticket)throw new Error(payload.error||"ticket not found");
    body.innerHTML=detailBody(payload.ticket);details.dataset.loaded="true";
  }catch(error){body.innerHTML=`<p class="empty">詳細資料載入失敗：${esc(error.message)}</p>`;details.dataset.loaded="error";}
}
function renderMetrics(){
  const decision=board.counts.decision;
  document.getElementById("metrics").innerHTML=
    metric("可派工",decision.now)+metric("進行中",decision.inflight)+
    metric("被阻塞",decision.blocked)+metric("未梳理",decision.ungroomed)+
    metric("歷史完成",board.counts.history.fixed+board.counts.history.wont_fix);
}
function commitAncestors(sha,commits,seen=new Set()){
  if(!sha||seen.has(sha))return [];
  seen.add(sha);
  const row=commits.get(sha);if(!row)return [sha];
  return [sha,...(row.parents||[]).flatMap(parent=>commitAncestors(parent,commits,seen))];
}
function commitInspector(row,ref){
  const files=(row.files||[]).map(file=>`<li><code>${esc(file)}</code></li>`).join("")||"<li>沒有檔案統計</li>";
  document.getElementById("commit-inspector").innerHTML=`
    <span class="eyebrow">COMMIT INSPECTOR</span>
    <h3>${esc(shortSha(row.sha))} · ${esc(row.subject)}</h3>
    <p>${esc(row.sha)}</p>
    <dl class="detail-grid">
      <dt>Author</dt><dd>${esc(row.author||"—")}</dd>
      <dt>Committed</dt><dd>${esc(row.committed_at||"—")}</dd>
      <dt>Parent</dt><dd><code>${esc((row.parents||[]).map(shortSha).join(", ")||"root")}</code></dd>
      <dt>Branch</dt><dd><code>${esc((row.refs||[]).join(", ")||ref?.branch||"—")}</code></dd>
      <dt>Diff stat</dt><dd>+${esc(row.insertions??0)} / −${esc(row.deletions??0)}</dd>
    </dl>
    <ul class="file-list">${files}</ul>`;
}
function renderTree(){
  const mount=document.getElementById("git-tree");
  if(!tree||!tree.commits?.length){
    mount.innerHTML='<p class="empty">目前沒有完整 Git tree mirror。</p>';
    document.getElementById("tree-state").textContent="資料不足";
    return;
  }
  const commits=new Map(tree.commits.map(row=>[row.sha,row]));
  const refs=tree.refs||[];
  const lanes=new Map([['main',0],...refs.map((ref,index)=>[ref.branch,index+1])]);
  const positions=new Map();
  const laneRefs=new Map();
  refs.forEach((ref,index)=>{
    const chain=commitAncestors(ref.head,commits);
    chain.forEach(sha=>{if(!positions.has(sha))positions.set(sha,{lane:index+1});});
    laneRefs.set(ref.branch,index+1);
  });
  const main=commits.get(refs.find(ref=>ref.branch==="main")?.head);
  if(main)commitAncestors(main.sha,commits).forEach(sha=>{if(!positions.has(sha))positions.set(sha,{lane:0});});
  [...commits.keys()].forEach((sha,index)=>{if(!positions.has(sha))positions.set(sha,{lane:(index%Math.max(1,refs.length+1))});});
  const ordered=[...commits.values()].sort((a,b)=>(a.committed_at||a.sha).localeCompare(b.committed_at||b.sha));
  const width=Math.max(520,(Math.max(0,...[...positions.values()].map(pos=>pos.lane))+1)*210);
  const height=Math.max(220,ordered.length*72+70);
  const x=lane=>70+lane*190,y=index=>55+index*72;
  ordered.forEach((row,index)=>{positions.get(row.sha).y=y(index);});
  const edges=[];
  ordered.forEach(row=>{const from=positions.get(row.sha);(row.parents||[]).forEach(parentSha=>{const to=positions.get(parentSha);if(to)edges.push(`<path class="edge" d="M ${x(from.lane)} ${from.y} C ${x(from.lane)} ${from.y+28}, ${x(to.lane)} ${to.y-28}, ${x(to.lane)} ${to.y}"/>`);});});
  const labels=refs.map(ref=>{
    const pos=positions.get(ref.head);if(!pos)return "";
    const tickets=(ref.tickets||[]).map(ticket=>`<button class="tree-ticket" data-ticket-id="${esc(ticket.id)}">${esc(ticket.id)}</button>`).join("");
    return `<g class="ref-label"><text x="${x(pos.lane)+18}" y="${pos.y-16}">${esc(ref.branch)} · ${esc(ref.live_state||ref.status||"unknown")}</text><foreignObject x="${x(pos.lane)+18}" y="${pos.y-9}" width="190" height="30"><div xmlns="http://www.w3.org/1999/xhtml">${tickets}</div></foreignObject></g>`;
  }).join("");
  const nodes=ordered.map(row=>{
    const pos=positions.get(row.sha);const ref=refs.find(item=>item.head===row.sha);
    return `<g class="commit" tabindex="0" role="button" data-sha="${esc(row.sha)}" data-ref="${esc(ref?.branch||"")}" transform="translate(${x(pos.lane)} ${pos.y})"><circle r="9"></circle><text x="16" y="5">${esc(shortSha(row.sha))} · ${esc(row.subject)}</text></g>`;
  }).join("");
  mount.innerHTML=`<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="所有可達 commit 的 Git graph"><g class="edges">${edges.join("")}</g>${labels}${nodes}</svg>`;
  document.getElementById("tree-state").textContent=tree.complete?`${ordered.length} commits`:`不完整 · ${ordered.length} commits`;
  document.getElementById("tree-alert").textContent=tree.complete?"":`mirror 不完整：${tree.error||"存在缺失 parent/ref"}`;
  mount.querySelectorAll(".commit").forEach(node=>{
    const show=()=>commitInspector(commits.get(node.dataset.sha),refs.find(ref=>ref.branch===node.dataset.ref));
    node.addEventListener("mouseenter",show);node.addEventListener("focus",show);node.addEventListener("click",show);
  });
  mount.querySelectorAll("[data-ticket-id]").forEach(node=>node.addEventListener("click",event=>{
    event.stopPropagation();const target=document.getElementById(`ticket-${node.dataset.ticketId}`);if(!target)return;
    target.querySelector("details").open=true;target.scrollIntoView({behavior:"smooth",block:"center"});
  }));
}
function render(){
  if(!board)return;
  renderMetrics();
  tabs.forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.tab===tab)));
  const visible=rows();
  document.getElementById("status").textContent=`${visible.length} 張票 · 唯讀`;
  document.getElementById("tickets").innerHTML=tab==="history"&&!history?"<p class=\"empty\">歷史資料載入中</p>":visible.length?visible.map(ticket).join(""):"<p class=\"empty\">這個篩選目前沒有票</p>";
  document.querySelectorAll("[data-ticket-details]").forEach(details=>details.addEventListener("toggle",()=>hydrateTicket(details)));
}
async function loadHistory(){
  if(history)return;
  const response=await fetch("/api/history",{cache:"no-store"});
  if(!response.ok)throw new Error(`history HTTP ${response.status}`);
  history=await response.json();
}
async function load(){
  const [boardResponse,treeResponse]=await Promise.all([fetch("/api/board",{cache:"no-store"}),fetch("/api/git-tree",{cache:"no-store"})]);
  if(!boardResponse.ok)throw new Error(`board HTTP ${boardResponse.status}`);
  if(!treeResponse.ok)throw new Error(`git tree HTTP ${treeResponse.status}`);
  board=await boardResponse.json();tree=await treeResponse.json();setTrust(board.freshness);render();renderTree();
}
document.getElementById("tabs").addEventListener("click",async event=>{const button=event.target.closest("[data-tab]");if(!button)return;tab=button.dataset.tab;render();if(tab==="history"){try{await loadHistory();render()}catch(error){document.getElementById("status").textContent=error.message}}});
document.getElementById("search").addEventListener("input",event=>{query=event.target.value;render()});
load().catch(error=>{document.getElementById("trust-state").textContent="看板載入失敗";document.getElementById("trust-detail").textContent=error.message;document.getElementById("tree-alert").textContent=error.message});
setInterval(load,30000);
