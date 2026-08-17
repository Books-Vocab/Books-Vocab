const revision=document.querySelector('meta[name="kg-app-revision"]').content;
const tabs=[...document.querySelectorAll('[data-tab]')];
let board=null,history=null,tree=null,tab="now",query="";
const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const shortSha=sha=>String(sha||"").slice(0,9);
const compactLabel=(value,max=32)=>{const text=String(value||"");return text.length>max?`${text.slice(0,max-1)}…`:text};
const compactBranchLabel=(value,max=17)=>compactLabel(String(value||"").replace(/^(?:feat|debug)\//,""),max);

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
const TREE_LANE_WIDTH = 124;
const TREE_ROW_HEIGHT = 44;
const TREE_HEADER_HEIGHT = 66;
const TREE_PADDING_X = 30;
let treeZoom = 100;
let treeBaseWidth = 0;
let treeFitInitialized = false;
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
function projectBranchPath(ref,mainlineSet,commits){
  const fullPath=pathToAnyTarget(ref.head,mainlineSet,commits);
  if(!fullPath.length){
    return {path:commits.has(ref.head)?[ref.head]:[],anchor:null,truncated:false,detached:true};
  }
  const path=fullPath.slice(0,TREE_VIEW_RADIUS+1);
  return {path,anchor:fullPath.at(-1),truncated:path.length<fullPath.length,detached:false};
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
  const branchTruncations=new Map();
  const branchDetached=new Set();
  const mainlineSet=new Set(mainline);
  const ticketRefs=refs.filter(ref=>ref.branch!=="main"&&(ref.tickets||[]).length);
  const addBranch=ref=>{
    const projection=projectBranchPath(ref,mainlineSet,commits);
    const {path,anchor,truncated,detached}=projection;
    visibleBranches.add(ref.branch);branchAnchors.set(ref.branch,anchor);branchPaths.set(ref.branch,path);
    if(detached)branchDetached.add(ref.branch);
    if(truncated&&path.at(-1))branchTruncations.set(ref.branch,{from:path.at(-1),to:anchor});
    if(anchor&&commits.has(anchor))visible.add(anchor);
    path.forEach(sha=>visible.add(sha));
  };
  // Ticket-bearing refs are never hidden by the bounded mainline window.
  // Their full history remains lazy, but their recent divergent segment and
  // exact common ancestor are part of this tree projection.
  ticketRefs.forEach(addBranch);
  refs.forEach(ref=>{
    if(ref.branch==="main")return;
    if(ticketRefs.includes(ref))return;
    // Every branch remains represented; only its recent divergent segment is
    // bounded. Fully converged history is not loaded into the initial view.
    addBranch(ref);
  });
  if(branchSha)visible.add(branchSha);
  return {
    commits:[...commits.values()].filter(row=>visible.has(row.sha)),
    refs:refs.filter(ref=>visibleBranches.has(ref.branch)),
    branchAnchors,
    branchPaths,
    branchTruncations,
    branchDetached,
    ticketRefs,
    mainline,mainlineWindow,branchSha,branchIndex,total:tree.commits.length,
  };
}
function renderTreeZoom(){
  const input=document.getElementById("tree-zoom");
  const output=document.getElementById("tree-zoom-value");
  if(input){input.value=String(treeZoom);input.min=String(TREE_ZOOM_MIN);input.max=String(TREE_ZOOM_MAX);input.step=String(TREE_ZOOM_STEP);input.setAttribute("aria-valuetext",`${treeZoom}%`)}
  if(output)output.textContent=`${treeZoom}%`;
}
function fitTreeZoom(){
  const mount=document.getElementById("git-tree");
  if(!treeBaseWidth||!mount?.clientWidth)return false;
  const available=Math.max(1,mount.clientWidth-24);
  const candidate=Math.floor((available/treeBaseWidth)*100/TREE_ZOOM_STEP)*TREE_ZOOM_STEP;
  treeZoom=Math.max(TREE_ZOOM_MIN,Math.min(100,candidate));
  renderTree();
  return true;
}
function cancelTreeAutoFit(){treeFitInitialized=true}
function treeStateOf(ref){
  return ref.live_state&&ref.live_state!=="unknown"?ref.live_state:(ref.status||"unknown");
}
function treeStateClass(value){
  return String(value||"unknown").toLowerCase().replace(/[^a-z0-9_-]+/g,"-");
}
function renderTreeLegend(viewport){
  const mount=document.getElementById("tree-legend");
  if(!mount)return;
  mount.innerHTML=(viewport.refs||[]).map(ref=>{
    const state=treeStateOf(ref);
    const tickets=(ref.tickets||[]).map(ticket=>`<button type="button" class="tree-ticket" data-ticket-id="${esc(ticket.id)}">${esc(ticket.id)}</button>`).join("");
    return `<article class="tree-legend-item state-${esc(treeStateClass(state))}">
      <span class="tree-legend-swatch" aria-hidden="true"></span>
      <div class="tree-legend-copy">
        <div class="tree-legend-heading"><strong title="${esc(ref.branch)}">${esc(compactLabel(ref.branch,34))}</strong><span>${esc(state)}</span></div>
        ${tickets?`<div class="tree-legend-tickets" aria-label="${esc(ref.branch)} 的票據">${tickets}</div>`:""}
      </div>
    </article>`;
  }).join("");
  mount.querySelectorAll("[data-ticket-id]").forEach(node=>node.addEventListener("click",event=>{
    event.stopPropagation();selectTicket(node.dataset.ticketId);
  }));
}
function treeLayout(viewport,visibleCommits){
  const branchLanes=new Map([["main",0]]);
  viewport.refs.filter(ref=>ref.branch!=="main").forEach((ref,index)=>branchLanes.set(ref.branch,index+1));
  const mainlineRanks=new Map(viewport.mainline.map((sha,index)=>[sha,index-viewport.branchIndex]));
  const mainlineSet=new Set(viewport.mainline),hints=new Map(),lanes=new Map();
  const setHint=(sha,value)=>{
    if(mainlineSet.has(sha)||!hints.has(sha)){hints.set(sha,value);return;}
    hints.set(sha,Math.min(hints.get(sha),value));
  };
  viewport.mainlineWindow.forEach((sha,index)=>{
    if(visibleCommits.has(sha)){hints.set(sha,index);lanes.set(sha,0)}
  });
  viewport.mainline.forEach(sha=>{
    if(visibleCommits.has(sha)){setHint(sha,mainlineRanks.get(sha)??0);lanes.set(sha,0)}
  });
  viewport.branchPaths.forEach((path,branch)=>{
    const lane=branchLanes.get(branch);if(lane===undefined||!path.length)return;
    const branchAnchor=viewport.branchAnchors.get(branch);
    const anchor=branchAnchor??path.at(-1),anchorRank=hints.get(anchor)??mainlineRanks.get(anchor)??0;
    const anchorInPath=branchAnchor!==null&&branchAnchor!==undefined&&path.includes(branchAnchor);
    path.forEach((sha,index)=>{
      if(!visibleCommits.has(sha))return;
      if(!lanes.has(sha))lanes.set(sha,lane);
      const hint=anchorInPath?anchorRank-(path.length-1-index):index;
      setHint(sha,hint);
    });
  });
  viewport.refs.filter(ref=>ref.branch!=="main").forEach(ref=>{
    const lane=branchLanes.get(ref.branch);
    if(lane===undefined||!visibleCommits.has(ref.head))return;
    if(!lanes.has(ref.head))lanes.set(ref.head,lane);
    setHint(ref.head,0);
  });
  visibleCommits.forEach((row,sha)=>{
    lanes.set(sha,lanes.get(sha)??0);setHint(sha,hints.get(sha)??0);
  });
  const ranks=new Map([...visibleCommits.keys()].map(sha=>[sha,hints.get(sha)??0]));
  const rows=[...visibleCommits.values()];
  for(let pass=0;pass<=rows.length;pass++){
    let changed=false;
    rows.forEach(row=>{
      const childRank=ranks.get(row.sha)??0;
      (row.parents||[]).forEach(parentSha=>{
        if(!ranks.has(parentSha))return;
        const required=childRank+1;
        if((ranks.get(parentSha)??0)<required){ranks.set(parentSha,required);changed=true}
      });
    });
    if(!changed)break;
  }
  const rankValues=[...new Set(ranks.values())].sort((left,right)=>left-right),rankIndex=new Map(rankValues.map((rank,index)=>[rank,index]));
  const normalizedRanks=new Map([...ranks.entries()].map(([sha,rank])=>[sha,rankIndex.get(rank)??0]));
  const minRank=Math.min(0,...normalizedRanks.values()),maxRank=Math.max(0,...normalizedRanks.values());
  const positions=new Map([...visibleCommits.keys()].map(sha=>[sha,{lane:lanes.get(sha)??0,row:(normalizedRanks.get(sha)??0)-minRank}]));
  const ordered=[...visibleCommits.values()].sort((left,right)=>{
    const a=positions.get(left.sha),b=positions.get(right.sha);
    return a.row-b.row||a.lane-b.lane||left.sha.localeCompare(right.sha);
  });
  return {branchLanes,positions,ordered,minRank,maxRank,rowCount:maxRank-minRank+1};
}
function edgePath(from,to,x,y){
  if(from.lane===to.lane)return `M ${x(from.lane)} ${y(from.row)} V ${y(to.row)}`;
  return `M ${x(from.lane)} ${y(from.row)} V ${y(to.row)} H ${x(to.lane)}`;
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
    treeBaseWidth=0;
    treeFitInitialized=false;
    mount.innerHTML='<p class="empty">目前沒有完整 Git tree mirror。</p>';
    renderTreeLegend({refs:[]});
    if(mobile)mobile.innerHTML='<p class="empty">目前沒有可顯示的分支資料。</p>';
    document.getElementById("tree-state").textContent="資料不足";
    return;
  }
  const commits=new Map(tree.commits.map(row=>[row.sha,row]));
  const refs=tree.refs||[];
  const viewport=treeViewport(tree,commits,refs);
  const visibleCommits=new Map(viewport.commits.map(row=>[row.sha,row]));
  const layout=treeLayout(viewport,visibleCommits);
  const {branchLanes,positions,ordered}=layout;
  const maxLane=Math.max(0,...branchLanes.values());
  const width=Math.max(680,TREE_PADDING_X*2+(maxLane+1)*TREE_LANE_WIDTH);
  treeBaseWidth=width;
  const height=Math.max(260,TREE_HEADER_HEIGHT+(layout.rowCount+1)*TREE_ROW_HEIGHT);
  const renderedWidth=Math.round(width*treeZoom/100),renderedHeight=Math.round(height*treeZoom/100);
  const x=lane=>TREE_PADDING_X+lane*TREE_LANE_WIDTH;
  const y=row=>TREE_HEADER_HEIGHT+row*TREE_ROW_HEIGHT;
  const edges=[];
  ordered.forEach(row=>{
    const from=positions.get(row.sha);
    (row.parents||[]).forEach(parentSha=>{
      const to=positions.get(parentSha);
      if(to)edges.push(`<path class="edge" d="${edgePath(from,to,x,y)}"/>`);
    });
  });
  const truncationMarkers=[...viewport.branchTruncations.values()].map(record=>{
    const pos=positions.get(record.from),row=visibleCommits.get(record.from);
    if(!pos||!row||(row.parents||[]).some(parentSha=>positions.has(parentSha)))return "";
    const markerY=y(pos.row)+Math.round(TREE_ROW_HEIGHT*.48);
    return `<path class="edge edge-truncated" d="M ${x(pos.lane)} ${y(pos.row)} V ${markerY}"><title>此分支中間歷史已省略</title></path><text class="tree-truncation" x="${x(pos.lane)+7}" y="${markerY+4}" aria-label="此分支中間歷史已省略">⋯</text>`;
  }).join("");
  const laneGuides=[...branchLanes.entries()].map(([branch,lane])=>`<line class="tree-lane-guide${branch==="main"?" main":""}" x1="${x(lane)}" y1="${TREE_HEADER_HEIGHT-14}" x2="${x(lane)}" y2="${height-18}"/>`).join("");
  const laneHeaders=viewport.refs.map(ref=>{
    const lane=branchLanes.get(ref.branch);if(lane===undefined)return "";
    const state=treeStateOf(ref);
    const detached=viewport.branchDetached.has(ref.branch),stateLabel=detached?"未連接":state;
    const detachedLabel=detached?`<text class="lane-state" x="14" y="31">${esc(stateLabel)}</text>`:"";
    const headerX=lane===0?0:x(lane)-52;
    return `<g class="lane-header state-${esc(treeStateClass(state))}${detached?" detached":""}" transform="translate(${headerX} 12)"><circle class="lane-dot" cx="5" cy="12" r="3"></circle><text x="14" y="16">${esc(compactBranchLabel(ref.branch))}</text>${detachedLabel}</g>`;
  }).join("");
  const nodes=ordered.map(row=>{
    const pos=positions.get(row.sha);const ref=viewport.refs.find(item=>item.head===row.sha);
    const head=ref?" head":"";
    return `<g class="commit${head}${ref?.branch==="main"?" main":""}" tabindex="0" role="button" aria-label="${esc(shortSha(row.sha)+" "+row.subject)}" data-sha="${esc(row.sha)}" data-ref="${esc(ref?.branch||"")}" transform="translate(${x(pos.lane)} ${y(pos.row)})"><title>${esc(shortSha(row.sha)+" · "+row.subject)}</title><circle r="${head?8:6}"></circle></g>`;
  }).join("");
  mount.innerHTML=`<svg viewBox="0 0 ${width} ${height}" width="${renderedWidth}" height="${renderedHeight}" data-zoom="${treeZoom}" role="group" aria-label="主線第一個分支附近與所有工作分支的 Git 交付樹"><g class="lane-guides">${laneGuides}</g><g class="lane-headers">${laneHeaders}</g><g class="edges">${edges.join("")}${truncationMarkers}</g>${nodes}</svg>`;
  const viewportLabel=viewport.branchSha?`第一個分支 ${shortSha(viewport.branchSha)}`:"主線前段";
  const mainlineCount=viewport.mainlineWindow.length;
  document.getElementById("tree-state").textContent=tree.complete?`主線緩衝 ${mainlineCount} · 所有分支 ${viewport.refs.length} · ${treeZoom}% · ${viewportLabel}`:`資料不完整 · 主線緩衝 ${mainlineCount} · 所有分支 ${viewport.refs.length} · ${treeZoom}%`;
  document.getElementById("tree-alert").textContent=tree.complete?"":`mirror 不完整：${tree.error||"存在缺失 parent/ref"}`;
  renderTreeLegend(viewport);
  renderMobileTree(viewport,commits);
  mount.querySelectorAll(".commit").forEach(node=>{
    const show=()=>commitInspector(commits.get(node.dataset.sha),refs.find(ref=>ref.branch===node.dataset.ref));
    node.addEventListener("mouseenter",show);node.addEventListener("focus",show);node.addEventListener("click",show);
    node.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();show()}});
  });
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
  if(!treeFitInitialized&&treeBaseWidth)treeFitInitialized=fitTreeZoom();
}
document.getElementById("tabs").addEventListener("click",async event=>{const button=event.target.closest("[data-tab]");if(!button)return;tab=button.dataset.tab;render();if(tab==="history"){try{await loadHistory();render()}catch(error){document.getElementById("status").textContent=error.message}}});
document.getElementById("search").addEventListener("input",event=>{query=event.target.value;render()});
document.getElementById("tree-zoom").addEventListener("input",event=>{
  cancelTreeAutoFit();
  const next=Number(event.target.value);
  treeZoom=Math.max(TREE_ZOOM_MIN,Math.min(TREE_ZOOM_MAX,Number.isFinite(next)?next:100));
  renderTreeZoom();
  if(tree)renderTree();
});
document.getElementById("tree-fit").addEventListener("click",()=>{cancelTreeAutoFit();fitTreeZoom()});
document.getElementById("tree-reset").addEventListener("click",()=>{cancelTreeAutoFit();treeZoom=100;if(tree)renderTree();else renderTreeZoom()});
const showLoadError=error=>{document.getElementById("trust-state").textContent="資料讀取錯誤";document.getElementById("trust-detail").textContent=error.message;document.getElementById("tree-alert").textContent=`看板資料讀取錯誤：${error.message}`};
renderTreeZoom();
load().catch(showLoadError);
setInterval(()=>load().catch(showLoadError),30000);
