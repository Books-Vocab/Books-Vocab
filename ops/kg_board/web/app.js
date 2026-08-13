const revision=document.querySelector('meta[name="kg-app-revision"]').content;
const tabs=[...document.querySelectorAll('[data-tab]')];
let board=null,history=null,tree=null,tab="now",query="";
const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const shortSha=sha=>String(sha||"").slice(0,9);
const compactLabel=(value,max=32)=>{const text=String(value||"");return text.length>max?`${text.slice(0,max-1)}…`:text};

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
function blockedReason(row){
  const blocked=(board.dispatch_meta?.withheld_blocked||[]).find(item=>item?.id===row.id);
  return Array.isArray(blocked?.waiting_on)&&blocked.waiting_on.length?blocked.waiting_on.join("、"):"尚未取得可派工資格";
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
    ${board.blocked_ids.includes(row.id)?`<p class="blocked-reason"><strong>阻塞原因</strong> ${esc(blockedReason(row))}</p>`:""}
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
        <span class="ticket-meta"><span class="chip severity-${esc(row.severity)}">${esc(row.severity)}</span><span>${esc(statusOf(row))}</span>${board.blocked_ids.includes(row.id)?`<span class="chip blocked-chip">等 ${esc(blockedReason(row))}</span>`:""}</span>
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
const TREE_VIEW_RADIUS = 10;
const TREE_ZOOM_MIN = 70;
const TREE_ZOOM_MAX = 140;
const TREE_ZOOM_STEP = 10;
let treeZoom = 100;
function firstParentChain(sha,commits,limit=commits.size+1){
  const result=[],seen=new Set();let current=sha;
  while(current&&!seen.has(current)&&result.length<limit){
    seen.add(current);result.push(current);
    current=commits.get(current)?.parents?.[0]||null;
  }
  return result;
}
function pathToAncestor(start,target,commits,limit=128){
  if(!start)return [];
  const pending=[{sha:start,path:[]}],seen=new Set();
  while(pending.length){
    const item=pending.pop(),current=item.sha;
    if(!current||seen.has(current)||item.path.length>limit)continue;
    const path=[...item.path,current];
    if(current===target)return path;
    seen.add(current);
    const parents=commits.get(current)?.parents||[];
    for(let index=parents.length-1;index>=0;index--)pending.push({sha:parents[index],path});
  }
  return [];
}
function pathToAnyTarget(start,targets,commits,limit=commits.size+1){
  if(!start)return [];
  const pending=[{sha:start,path:[]}],seen=new Set();
  while(pending.length){
    const item=pending.pop(),current=item.sha;
    if(!current||seen.has(current)||item.path.length>limit)continue;
    const path=[...item.path,current];
    if(targets.has(current))return path;
    seen.add(current);
    const parents=commits.get(current)?.parents||[];
    for(let index=parents.length-1;index>=0;index--)pending.push({sha:parents[index],path});
  }
  return [];
}
function firstBranchPoint(mainHead,commits){
  const children=new Map();
  commits.forEach(row=>(row.parents||[]).forEach(parent=>{
    if(!children.has(parent))children.set(parent,new Set());
    children.get(parent).add(row.sha);
  }));
  for(const sha of firstParentChain(mainHead,commits)){
    if((children.get(sha)?.size||0)>1)return sha;
  }
  return null;
}
function treeViewport(tree,commits,refs){
  const mainRef=refs.find(ref=>ref.branch==="main"),mainHead=mainRef?.head;
  const mainline=firstParentChain(mainHead,commits);
  const branchSha=firstBranchPoint(mainHead,commits)||mainline[Math.min(TREE_VIEW_RADIUS,Math.max(0,mainline.length-1))]||mainHead;
  const branchIndex=Math.max(0,mainline.indexOf(branchSha));
  // The useful inspection window starts at the first branch and looks ten
  // commits toward its parents. Showing the newest mainline tail first made
  // the branch point invisible below a long, low-signal wall of commits.
  const mainlineWindow=mainline.slice(branchIndex,branchIndex+TREE_VIEW_RADIUS+1);
  const visible=new Set(mainlineWindow);
  const visibleBranches=new Set(["main"]);
  const branchAnchors=new Map();
  const branchPaths=new Map();
  const mainlineSet=new Set(mainline);
  const ticketRefs=refs.filter(ref=>ref.branch!=="main"&&(ref.tickets||[]).length);
  ticketRefs.forEach(ref=>{
    // Ticket-bearing refs are never hidden by the bounded mainline window.
    // Their full history remains lazy, but their recent divergent segment and
    // exact common ancestor are part of this tree projection.
    const path=pathToAnyTarget(ref.head,mainlineSet,commits);
    const branchPath=path.length?path.slice(0,TREE_VIEW_RADIUS+1):[ref.head].filter(sha=>commits.has(sha));
    const anchor=path.at(-1)||branchPath.at(-1)||ref.head;
    if(anchor)branchPath.push(...(branchPath.at(-1)===anchor?[]:[anchor]));
    visibleBranches.add(ref.branch);branchAnchors.set(ref.branch,anchor);branchPaths.set(ref.branch,branchPath);
    branchPath.forEach(sha=>visible.add(sha));
  });
  refs.forEach(ref=>{
    if(ref.branch==="main")return;
    if(ticketRefs.includes(ref))return;
    const path=pathToAnyTarget(ref.head,mainlineSet,commits);
    // Every branch remains represented; only its recent divergent segment is
    // bounded. Fully converged history is not loaded into the initial view.
    const branchPath=path.length?path.slice(0,TREE_VIEW_RADIUS+1):[ref.head].filter(sha=>commits.has(sha));
    const anchor=path.at(-1)||branchPath.at(-1)||ref.head;
    if(anchor)branchPath.push(...(branchPath.at(-1)===anchor?[]:[anchor]));
    visibleBranches.add(ref.branch);branchAnchors.set(ref.branch,anchor);branchPaths.set(ref.branch,branchPath);
    branchPath.forEach(sha=>visible.add(sha));
  });
  if(branchSha)visible.add(branchSha);
  return {
    commits:[...commits.values()].filter(row=>visible.has(row.sha)),
    refs:refs.filter(ref=>visibleBranches.has(ref.branch)),
    branchAnchors,
    branchPaths,
    ticketRefs,
    mainline,mainlineWindow,branchSha,total:tree.commits.length,
  };
}
function renderTreeZoom(){
  const input=document.getElementById("tree-zoom");
  const output=document.getElementById("tree-zoom-value");
  if(input){input.value=String(treeZoom);input.min=String(TREE_ZOOM_MIN);input.max=String(TREE_ZOOM_MAX);input.step=String(TREE_ZOOM_STEP);input.setAttribute("aria-valuetext",`${treeZoom}%`)}
  if(output)output.textContent=`${treeZoom}%`;
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
function heldTicketGroups(){
  const groups=new Map();
  (board?.board||[]).filter(row=>row.held).forEach(row=>{
    const branch=String(row.held?.branch||"未標定工作樹");
    if(!groups.has(branch))groups.set(branch,[]);
    groups.get(branch).push(row);
  });
  return [...groups.entries()];
}
function renderHeldTickets(){
  const mount=document.getElementById("tree-held-tickets");if(!mount)return;
  const groups=heldTicketGroups(),total=groups.reduce((count,[,rows])=>count+rows.length,0);
  if(!total){mount.innerHTML="";return;}
  mount.innerHTML=`<section class="tree-held-card" aria-labelledby="tree-held-title">
    <div class="tree-held-heading"><strong id="tree-held-title">目前認領中的票據</strong><span>${total} 張 · ${groups.length} 條工作樹</span></div>
    <div class="tree-held-groups">${groups.map(([branch,rows])=>`<div class="tree-held-group">
      <div class="tree-held-branch"><code title="${esc(branch)}">${esc(compactLabel(branch,48))}</code><span>${rows.length} 張</span></div>
      <div class="tree-held-list">${rows.map(row=>`<button type="button" class="tree-held-ticket" data-ticket-id="${esc(row.id)}"><code>${esc(row.id)}</code><span>${esc(row.brief||"尚未提供白話摘要")}</span></button>`).join("")}</div>
    </div>`).join("")}</div>
  </section>`;
  mount.querySelectorAll("[data-ticket-id]").forEach(node=>node.addEventListener("click",()=>selectTicket(node.dataset.ticketId)));
}
function renderTree(){
  const mount=document.getElementById("git-tree");
  const mobile=document.getElementById("tree-mobile-list");
  renderTreeZoom();
  if(!tree||!tree.commits?.length){
    mount.innerHTML='<p class="empty">目前沒有完整 Git tree mirror。</p>';
    if(mobile)mobile.innerHTML='<p class="empty">目前沒有可顯示的分支資料。</p>';
    document.getElementById("tree-state").textContent="資料不足";
    return;
  }
  const commits=new Map(tree.commits.map(row=>[row.sha,row]));
  const refs=tree.refs||[];
  const viewport=treeViewport(tree,commits,refs);
  const visibleCommits=new Map(viewport.commits.map(row=>[row.sha,row]));
  const positions=new Map();
  const branchLanes=new Map();
  viewport.refs.filter(ref=>ref.branch!=="main").forEach((ref,index)=>{
    branchLanes.set(ref.branch,index+1);
    const anchor=viewport.branchAnchors.get(ref.branch);
    if(anchor&&visibleCommits.has(anchor)&&!positions.has(anchor))positions.set(anchor,{lane:index+1});
  });
  const main=commits.get(refs.find(ref=>ref.branch==="main")?.head);
  if(main)viewport.mainline.forEach(sha=>{if(visibleCommits.has(sha))positions.set(sha,{lane:0});});
  viewport.branchPaths.forEach((path,branch)=>{
    const lane=branchLanes.get(branch);
    if(lane===undefined)return;
    path.forEach(sha=>{if(!viewport.mainlineWindow.includes(sha))positions.set(sha,{lane});});
  });
  [...visibleCommits.keys()].forEach((sha,index)=>{if(!positions.has(sha))positions.set(sha,{lane:(index%Math.max(1,viewport.refs.length+1))});});
  const windowRows=viewport.mainlineWindow.map(sha=>visibleCommits.get(sha)).filter(Boolean);
  const anchorRows=[...new Set(viewport.branchAnchors.values())].map(sha=>visibleCommits.get(sha)).filter(Boolean);
  const branchRow=visibleCommits.get(viewport.branchSha);
  const branchRows=[...viewport.branchPaths.values()].flatMap(path=>path.map(sha=>visibleCommits.get(sha)).filter(Boolean));
  const ordered=[],orderedSet=new Set();
  const appendRows=rows=>rows.forEach(row=>{if(row&&!orderedSet.has(row.sha)){orderedSet.add(row.sha);ordered.push(row);}});
  appendRows(branchRow?[branchRow]:[]);
  appendRows(anchorRows);
  appendRows(branchRows);
  appendRows(windowRows);
  const width=Math.max(520,(Math.max(0,...[...positions.values()].map(pos=>pos.lane))+1)*210);
  const height=Math.max(220,ordered.length*72+70);
  const renderedWidth=Math.round(width*treeZoom/100),renderedHeight=Math.round(height*treeZoom/100);
  const x=lane=>70+lane*190,y=index=>55+index*72;
  ordered.forEach((row,index)=>{positions.get(row.sha).y=y(index);});
  const edges=[];
  ordered.forEach(row=>{const from=positions.get(row.sha);(row.parents||[]).forEach(parentSha=>{const to=positions.get(parentSha);if(to)edges.push(`<path class="edge" d="M ${x(from.lane)} ${from.y} C ${x(from.lane)} ${from.y+28}, ${x(to.lane)} ${to.y-28}, ${x(to.lane)} ${to.y}"/>`);});});
  const labelsByAnchor=new Map();
  viewport.refs.forEach(ref=>{
    const branchPath=viewport.branchPaths.get(ref.branch)||[];
    const anchor=ref.branch==="main"?viewport.branchSha:(branchPath[0]||viewport.branchAnchors.get(ref.branch));
    if(!anchor||!positions.has(anchor))return;
    if(!labelsByAnchor.has(anchor))labelsByAnchor.set(anchor,[]);labelsByAnchor.get(anchor).push(ref);
  });
  const labels=[...labelsByAnchor.entries()].map(([anchor,anchorRefs])=>{
    const pos=positions.get(anchor);
    // Keep the ref row and its ticket buttons above the commit node.  A 22px
    // foreignObject plus a 24px gap prevents multiple refs at one anchor from
    // colliding with the node subject or with the next branch row.
    const labelTop=Math.max(18,pos.y-50-(anchorRefs.length-1)*28);
    return anchorRefs.map((ref,index)=>{
      const refState=ref.live_state&&ref.live_state!=="unknown"?ref.live_state:(ref.status||"unknown");
      const ticketList=ref.tickets||[];
      const tickets=ticketList.slice(0,3).map(ticket=>`<button class="tree-ticket" data-ticket-id="${esc(ticket.id)}">${esc(ticket.id)}</button>`).join("");
      const more=ticketList.length>3?`<span class="tree-ticket-more">+${ticketList.length-3}</span>`:"";
      const rowY=labelTop+index*28;
      return `<g class="ref-label"><text x="${x(pos.lane)+18}" y="${rowY}">${esc(compactLabel(ref.branch,24))} · ${esc(refState)}</text><foreignObject x="${x(pos.lane)+18}" y="${rowY+4}" width="190" height="22"><div xmlns="http://www.w3.org/1999/xhtml">${tickets}${more}</div></foreignObject></g>`;
    }).join("");
  }).join("");
  const nodes=ordered.map(row=>{
    const pos=positions.get(row.sha);const ref=viewport.refs.find(item=>item.head===row.sha||viewport.branchAnchors.get(item.branch)===row.sha);
    return `<g class="commit" tabindex="0" role="button" aria-label="${esc(shortSha(row.sha)+" "+row.subject)}" data-sha="${esc(row.sha)}" data-ref="${esc(ref?.branch||"")}" transform="translate(${x(pos.lane)} ${pos.y})"><circle r="9"></circle><text x="16" y="5">${esc(shortSha(row.sha))} · ${esc(compactLabel(row.subject,30))}</text></g>`;
  }).join("");
  mount.innerHTML=`<svg viewBox="0 0 ${width} ${height}" width="${renderedWidth}" height="${renderedHeight}" data-zoom="${treeZoom}" role="group" aria-label="主線第一個分支附近與所有工作分支的 Git 交付樹"><g class="edges">${edges.join("")}</g>${labels}${nodes}</svg>`;
  const viewportLabel=viewport.branchSha?`第一個分支 ${shortSha(viewport.branchSha)}`:"主線前段";
  const mainlineCount=windowRows.length;
  document.getElementById("tree-state").textContent=tree.complete?`主線緩衝 ${mainlineCount} · 所有分支 ${viewport.refs.length} · ${treeZoom}% · ${viewportLabel}`:`資料不完整 · 主線緩衝 ${mainlineCount} · 所有分支 ${viewport.refs.length} · ${treeZoom}%`;
  document.getElementById("tree-alert").textContent=tree.complete?"":`mirror 不完整：${tree.error||"存在缺失 parent/ref"}`;
  renderMobileTree(viewport,commits);
  mount.querySelectorAll(".commit").forEach(node=>{
    const show=()=>commitInspector(commits.get(node.dataset.sha),refs.find(ref=>ref.branch===node.dataset.ref));
    node.addEventListener("mouseenter",show);node.addEventListener("focus",show);node.addEventListener("click",show);
    node.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();show()}});
  });
  mount.querySelectorAll("[data-ticket-id]").forEach(node=>node.addEventListener("click",event=>{
    event.stopPropagation();selectTicket(node.dataset.ticketId);
  }));
}
function renderMobileTree(viewport,commits){
  const mount=document.getElementById("tree-mobile-list");if(!mount)return;
  const refs=viewport.refs||[];const rows=[];const seen=new Set();
  [...viewport.mainlineWindow,...viewport.branchAnchors.values()].forEach(sha=>{if(sha&&!seen.has(sha)&&commits.has(sha)){seen.add(sha);rows.push(commits.get(sha));}});
  const branches=refs.map(ref=>{const tickets=(ref.tickets||[]).slice(0,3).map(t=>`<button class="tree-ticket" data-ticket-id="${esc(t.id)}">${esc(t.id)}</button>`).join("");const more=(ref.tickets||[]).length>3?`<span class="tree-ticket-more">+${(ref.tickets||[]).length-3}</span>`:"";return `<span class="tree-mobile-branch"><strong>${esc(compactLabel(ref.branch,30))}</strong><span>${esc(ref.live_state&&ref.live_state!=="unknown"?ref.live_state:(ref.status||"unknown"))}</span>${tickets}${more}</span>`}).join("");
  mount.innerHTML=`<div class="tree-mobile-summary"><strong>主線緩衝與所有分支</strong><span>${rows.length} 個 commit · ${refs.length} 條分支</span></div><div class="tree-mobile-branches">${branches}</div><ol class="tree-mobile-commits">${rows.map(row=>`<li><button class="tree-mobile-commit" data-sha="${esc(row.sha)}"><code>${esc(shortSha(row.sha))}</code><span>${esc(row.subject)}</span></button></li>`).join("")}</ol>`;
  mount.querySelectorAll(".tree-mobile-commit").forEach(node=>node.addEventListener("click",()=>commitInspector(commits.get(node.dataset.sha),null)));
  mount.querySelectorAll("[data-ticket-id]").forEach(node=>node.addEventListener("click",event=>{event.stopPropagation();selectTicket(node.dataset.ticketId)}));
}
function selectTicket(id){
  const target=document.getElementById(`ticket-${CSS.escape(id)}`);
  if(!target){
    const known=board.board.some(row=>row.id===id);
    if(!known){
      if(history?.board?.some(row=>row.id===id)){tab="history";query="";render();return setTimeout(()=>selectTicket(id),0)}
      document.getElementById("tree-alert").textContent=`票號 ${id} 不在目前投影（可能已結案或鏡像尚未更新）`;
      return;
    }
    tab=board.blocked_ids.includes(id)?"blocked":board.dispatch_ids.includes(id)?"now":"all";query="";render();return setTimeout(()=>selectTicket(id),0);
  }
  const details=target.querySelector("details");if(details)details.open=true;target.scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"center"});target.classList.add("ticket-highlight");setTimeout(()=>target.classList.remove("ticket-highlight"),1200);
}
function render(){
  if(!board)return;
  renderMetrics();
  tabs.forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.tab===tab)));
  const visible=rows();
  document.getElementById("status").textContent=`${visible.length} 張票 · 唯讀`;
  document.getElementById("tickets").innerHTML=tab==="history"&&!history?"<p class=\"empty\">歷史資料載入中</p>":visible.length?visible.map(ticket).join(""):"<p class=\"empty\">這個篩選目前沒有票</p>";
  renderHeldTickets();
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
document.getElementById("tree-zoom").addEventListener("input",event=>{
  const next=Number(event.target.value);
  treeZoom=Math.max(TREE_ZOOM_MIN,Math.min(TREE_ZOOM_MAX,Number.isFinite(next)?next:100));
  renderTreeZoom();
  if(tree)renderTree();
});
const showLoadError=error=>{document.getElementById("trust-state").textContent="資料讀取錯誤";document.getElementById("trust-detail").textContent=error.message;document.getElementById("tree-alert").textContent=`看板資料讀取錯誤：${error.message}`};
renderTreeZoom();
load().catch(showLoadError);
setInterval(()=>load().catch(showLoadError),30000);
