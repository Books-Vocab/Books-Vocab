const revision=document.querySelector('meta[name="kg-app-revision"]').content;
const tabs=[...document.querySelectorAll('[data-tab]')];
let board=null,history=null,tree=null,scopeMatrix=null,tab="now",query="";
let scopeZoom=100,scopeDensity=34,scopeOccupiedOnly=false;
let scopeSelection={kind:null,filePath:null,columnId:null};
let treeSelection={kind:null,branch:null,sha:null,boundaryId:null,boundaryKind:null,parent:null};
const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const shortSha=sha=>String(sha||"").slice(0,9);
const compactLabel=(value,max=32)=>{const text=String(value||"");return text.length>max?`${text.slice(0,max-1)}…`:text};
const compactBranchLabel=(value,max=17)=>compactLabel(String(value||"").replace(/^(?:feat|debug)\//,""),max);
function formatDiffStat(row){
  const insertions=Number.isInteger(row?.insertions)&&row.insertions>=0?row.insertions:null;
  const deletions=Number.isInteger(row?.deletions)&&row.deletions>=0?row.deletions:null;
  if(insertions===null&&deletions===null)return "未提供";
  return `+${insertions===null?"—":insertions} / −${deletions===null?"—":deletions}`;
}

function setTrust(freshness){
  const state=freshness.freshness_state||"unknown";
  const labels={current:"資料已追平",stale:"資料有落差",error:"資料讀取錯誤",unknown:"新鮮度未知"};
  const treeLabels={current:"已追平",stale:"有落差",error:"錯誤",unknown:"未知"};
  const treeState=freshness.git_tree_state||"unknown";
  const treeStateLabel=treeLabels[treeState]||treeState;
  const treeAgeLabel=freshness.git_tree_age==null?"未知":`${freshness.git_tree_age}s`;
  const dirtyState=freshness.worktree_status_state||"unknown";
  const dirtyStateLabel=treeLabels[dirtyState]||dirtyState;
  const dirtyAgeLabel=freshness.worktree_status_age==null?"未知":`${freshness.worktree_status_age}s`;
  document.getElementById("trust-state").textContent=labels[state]||labels.unknown;
  document.getElementById("trust-detail").textContent=
    `tree ${treeStateLabel} · dirty ${dirtyStateLabel} ${dirtyAgeLabel} · mirror ${treeAgeLabel} · app ${revision.slice(0,9)}`;
}
function statusOf(row){
  const labels={held:"進行中","needs-grooming":"待梳理","dependency-blocked":"依賴阻塞",dispatchable:"可派工","contract-not-ready":"契約未就緒",queued:"已入列"};
  const terminal={fixed:"已修復","wont-fix":"不修"};
  return labels[row.decision]||terminal[row.status]||"未分類";
}
function blockedReason(row){
  const blocked=(board.dispatch_meta?.withheld_blocked||[]).find(item=>item?.id===row.id);
  return Array.isArray(blocked?.waiting_on)&&blocked.waiting_on.length?blocked.waiting_on.join("、"):"尚未取得可派工資格";
}
function scopeOperationLabel(operation){return operation==="add"?"新增":"修改"}
function scopeDetail(scope){
  if(scope&&Array.isArray(scope.files))return `<ul class="scope-detail-list">${scope.files.map(file=>`<li><span class="scope-operation scope-operation-${esc(file.operation)}">${file.operation==="add"?"+":"~"}</span><code>${esc(file.path)}</code></li>`).join("")}</ul>`;
  if(typeof scope==="string"&&scope.trim())return esc(scope);
  return "Scope 未知（尚未宣告實際檔案範圍）";
}
function dirtyStateOf(worktree){
  if(worktree?.dirty===true)return "dirty";
  if(worktree?.dirty===false)return "clean";
  return "unknown";
}
function copyButton(value,label="複製"){
  const text=String(value||"");
  if(!text)return "";
  return `<button type="button" class="copy-button" data-copy-value="${esc(text)}" data-copy-kind="value">${esc(label)}</button>`;
}
async function copyValue(value,button){
  const text=String(value||"");if(!text||!button)return false;
  let copied=false;
  try{
    if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(text);copied=true;}
  }catch(_error){copied=false;}
  if(!copied){
    const input=document.createElement("textarea");input.value=text;input.setAttribute("readonly","");input.style.position="fixed";input.style.opacity="0";document.body.appendChild(input);input.select();
    try{copied=document.execCommand("copy");}catch(_error){copied=false;}input.remove();
  }
  const original=button.dataset.copyLabel||button.textContent;
  button.dataset.copyLabel=original;button.textContent=copied?"已複製":"複製失敗";button.dataset.copyState=copied?"copied":"failed";
  window.setTimeout(()=>{if(button.isConnected){button.textContent=original;button.dataset.copyState="";}},1200);
  return copied;
}
function bindCopyButtons(root=document){
  root.querySelectorAll(".copy-button").forEach(button=>{
    if(button.dataset.copyBound==="true")return;
    button.dataset.copyBound="true";
    button.addEventListener("click",event=>{
      event.stopPropagation();
      copyValue(button.dataset.copyValue,button);
    });
  });
}
function renderScopeControls(){
  const zoom=document.getElementById("scope-zoom"),zoomOutput=document.getElementById("scope-zoom-value");
  const density=document.getElementById("scope-density"),densityOutput=document.getElementById("scope-density-value");
  const occupied=document.getElementById("scope-occupied-only");
  if(zoom){zoom.value=String(scopeZoom);zoom.setAttribute("aria-valuetext",`${scopeZoom}%`);}
  if(zoomOutput)zoomOutput.textContent=`${scopeZoom}%`;
  if(density){density.value=String(scopeDensity);density.setAttribute("aria-valuetext",`${scopeDensity}px`);}
  if(densityOutput)densityOutput.textContent=`${scopeDensity}px`;
  if(occupied)occupied.checked=scopeOccupiedOnly;
  const fullscreenZoom=document.getElementById("scope-fullscreen-zoom");
  if(fullscreenZoom)fullscreenZoom.textContent=`${scopeZoom}%`;
}
function applyScopeGeometry(mount){
  if(!mount)return;
  mount.style.setProperty("--scope-scale",String(scopeZoom/100));
  mount.style.setProperty("--scope-font-size","11px");
  mount.style.setProperty("--scope-column-width","190px");
  mount.style.setProperty("--scope-file-width","220px");
  mount.style.setProperty("--scope-head-height","128px");
  mount.style.setProperty("--scope-row-height",`${scopeDensity}px`);
}
function scopeColumns(){
  if(!scopeMatrix)return [];
  return [
    ...(scopeMatrix.worktrees||[]).map(worktree=>({type:"worktree",id:worktree.id,worktree})),
    ...(scopeMatrix.queued_tickets||[]).map(ticket=>({type:"ticket",id:ticket.id,ticket})),
  ];
}
function scopeColumnById(columnId){
  return scopeColumns().find(column=>column.id===columnId)||null;
}
function scopeCellById(filePath,columnId){
  const file=(scopeMatrix?.files||[]).find(row=>row.path===filePath);
  if(!file)return null;
  return (file.cells||[]).find(cell=>(cell.column_type==="worktree"?cell.worktree_id:cell.ticket_id)===columnId)||null;
}
function scopeFieldMarkup(label,value){
  return '<dt>'+esc(label)+'</dt><dd>'+(value||"—")+'</dd>';
}
function scopeSourceListMarkup(values){
  const items=(Array.isArray(values)?values:[]).filter(value=>value!==null&&value!==undefined&&String(value)!=="");
  return items.length?items.map(value=>'<code>'+esc(value)+'</code>').join("<br>"):"—";
}
function scopeSourceMarkup(column){
  if(!column)return "";
  if(column.type==="worktree"){
    const worktree=column.worktree||{},agent=worktree.agent||{};
    return scopeFieldMarkup("branch",'<code>'+esc(worktree.branch||"—")+'</code>'+copyButton(worktree.branch,"複製"))+
      scopeFieldMarkup("agent_title",'<code>'+esc(agent.title||"—")+'</code>'+copyButton(agent.title,"複製"))+
      scopeFieldMarkup("agent_status",esc(agent.status||"unknown"))+
      scopeFieldMarkup("worktree",'<code>'+esc(worktree.path||"—")+'</code>'+copyButton(worktree.path,"複製"))+
      scopeFieldMarkup("host",esc(worktree.host||"—"))+
      scopeFieldMarkup("thread",'<code>'+esc(agent.thread_id||"—")+'</code>'+copyButton(agent.thread_id,"複製"))+
      scopeFieldMarkup("kind",esc(worktree.kind||"—"))+
      scopeFieldMarkup("tickets",esc((worktree.ticket_ids||[]).join(", ")))+
      scopeFieldMarkup("state",esc(worktree.state||"active"))+
      scopeFieldMarkup("scope",esc(worktree.scope_status||"unknown"))+
      scopeFieldMarkup("dirty",esc(dirtyStateOf(worktree)))+
      scopeFieldMarkup("dirty_file_count",esc(Number.isInteger(worktree.dirty_file_count)?worktree.dirty_file_count:"—"))+
      scopeFieldMarkup("dirty_files",scopeSourceListMarkup(worktree.dirty_files));
  }
  const ticket=column.ticket||{},collision=ticket.collision||null;
  return scopeFieldMarkup("id",'<code>'+esc(ticket.id||column.id)+'</code>'+copyButton(ticket.id||column.id,"複製"))+
    scopeFieldMarkup("type","queued")+
    scopeFieldMarkup("state",esc(ticket.state||"queued"))+
    scopeFieldMarkup("scope",esc(ticket.scope_status||"unknown"))+
    scopeFieldMarkup("collision",esc(collision?collision.status:"—"))+
    scopeFieldMarkup("with_worktrees",esc((collision?.with_worktrees||[]).join(", ")))+
    scopeFieldMarkup("paths",esc((collision?.paths||[]).join(", ")));
}
function renderScopeInspector(){
  const inspector=document.getElementById("scope-inspector");
  if(!inspector)return;
  const selection=scopeSelection;
  if(!selection.kind){
    inspector.hidden=true;
    inspector.innerHTML="";
    return;
  }
  const fields=[];
  if(selection.filePath){
    fields.push(scopeFieldMarkup("file_path",'<code>'+esc(selection.filePath)+'</code>'+copyButton(selection.filePath,"複製")));
  }
  if(selection.columnId){
    const column=scopeColumnById(selection.columnId);
    fields.push(scopeFieldMarkup("column_id",'<code>'+esc(selection.columnId)+'</code>'+copyButton(selection.columnId,"複製")));
    fields.push(scopeFieldMarkup("column_type",esc(column?.type||"unknown")));
    fields.push(scopeSourceMarkup(column));
    if(selection.kind==="cell"){
      const cell=scopeCellById(selection.filePath,selection.columnId);
      fields.push(scopeFieldMarkup("operation",esc((cell?.operations||[cell?.operation]).filter(Boolean).join(", "))));
      fields.push(scopeFieldMarkup("state",esc(cell?.state||"empty")));
      fields.push(scopeFieldMarkup("collision",esc(cell?.collision===true?"true":"false")));
    }
  }
  inspector.innerHTML='<span class="eyebrow">MATRIX INSPECTOR</span><dl class="detail-grid">'+fields.join("")+'</dl>';
  inspector.hidden=false;
  bindCopyButtons(inspector);
}
function applyScopeSelection(mount){
  if(!mount)return;
  mount.querySelectorAll(".scope-row-selected,.scope-file-selected,.scope-column-selected,.scope-cell-selected").forEach(node=>{
    node.classList.remove("scope-row-selected","scope-file-selected","scope-column-selected","scope-cell-selected");
  });
  if(scopeSelection.filePath){
    mount.querySelectorAll('[data-file-path="'+CSS.escape(scopeSelection.filePath)+'"]').forEach(node=>{
      if(node.matches("tr"))node.classList.add("scope-row-selected");
      if(node.matches(".scope-file-name"))node.classList.add("scope-file-selected");
    });
  }
  if(scopeSelection.columnId){
    mount.querySelectorAll('[data-column-id="'+CSS.escape(scopeSelection.columnId)+'"]').forEach(node=>node.classList.add("scope-column-selected"));
  }
  if(scopeSelection.kind==="cell"&&scopeSelection.filePath&&scopeSelection.columnId){
    const cell=mount.querySelector('[data-file-path="'+CSS.escape(scopeSelection.filePath)+'"][data-column-id="'+CSS.escape(scopeSelection.columnId)+'"]');
    cell?.classList.add("scope-cell-selected");
  }
}
function setScopeSelection(next,mount=document.getElementById("scope-matrix-wrap")){
  scopeSelection={
    kind:next?.kind||null,
    filePath:next?.filePath||null,
    columnId:next?.columnId||null,
  };
  new Set([mount,document.getElementById("scope-matrix-wrap"),scopeFullscreenCanvas?.()]).forEach(target=>applyScopeSelection(target));
  renderScopeInspector();
}
function scopeSelectionFromNode(node){
  if(node.matches(".scope-file-name"))return {kind:"file",filePath:node.dataset.filePath};
  if(node.matches(".scope-column-head"))return {kind:"column",columnId:node.dataset.columnId};
  if(node.matches(".scope-cell,.scope-empty-cell"))return {kind:"cell",filePath:node.dataset.filePath,columnId:node.dataset.columnId};
  return null;
}
function bindScopeSelection(mount){
  if(!mount)return;
  mount.querySelectorAll(".scope-file-name,.scope-column-head,.scope-cell,.scope-empty-cell").forEach(node=>{
    if(node.dataset.selectionBound==="true")return;
    node.dataset.selectionBound="true";
    const select=event=>{
      if(event.target.closest(".copy-button"))return;
      const next=scopeSelectionFromNode(node);
      if(next)setScopeSelection(next,mount);
    };
    node.addEventListener("click",select);
    node.addEventListener("keydown",event=>{
      if(event.key!=="Enter"&&event.key!==" ")return;
      event.preventDefault();
      select(event);
    });
  });
}
function restoreScopeSelection(mount){
  if(!scopeSelection.kind){
    renderScopeInspector();
    return;
  }
  const fileExists=!scopeSelection.filePath||(scopeMatrix?.files||[]).some(file=>file.path===scopeSelection.filePath);
  const columnExists=!scopeSelection.columnId||!!scopeColumnById(scopeSelection.columnId);
  const cellExists=scopeSelection.kind!=="cell"||!!scopeCellById(scopeSelection.filePath,scopeSelection.columnId);
  if(!fileExists||!columnExists||!cellExists){
    scopeSelection={kind:null,filePath:null,columnId:null};
  }
  new Set([mount,document.getElementById("scope-matrix-wrap"),scopeFullscreenCanvas?.()]).forEach(target=>applyScopeSelection(target));
  renderScopeInspector();
}
function fitScopeMatrix(){
  const wrap=document.getElementById("scope-matrix-wrap"),table=wrap?.querySelector(".scope-matrix");
  if(!wrap||!table||!wrap.clientWidth)return false;
  const available=Math.max(1,wrap.clientWidth-24);
  const currentScale=Math.max(.01,scopeZoom/100);
  const baseWidth=Math.max(1,table.scrollWidth/currentScale);
  const candidate=Math.floor((available/baseWidth)*100/10)*10;
  scopeZoom=Math.max(80,Math.min(140,candidate));
  renderScopeControls();
  renderScopeMatrixPrimary();
  return true;
}
function renderScopeMatrixPrimary(){
  const mount=document.getElementById("scope-matrix-wrap");
  if(!mount)return;
  renderScopeControls();
  applyScopeGeometry(mount);
  if(!scopeMatrix){mount.innerHTML='<p class="empty">檔案矩陣載入中</p>';scopeSelection={kind:null,filePath:null,columnId:null};refreshScopeFullscreen();renderScopeInspector();return}
  const worktrees=scopeMatrix.worktrees||[];
  const queuedTickets=scopeMatrix.queued_tickets||[];
  const allFiles=scopeMatrix.files||[];
  const files=scopeOccupiedOnly?allFiles.filter(file=>(file.cells||[]).length>0):allFiles;
  const columns=[
    ...worktrees.map(worktree=>({type:"worktree",id:worktree.id,worktree})),
    ...queuedTickets.map(ticket=>({type:"ticket",id:ticket.id,ticket})),
  ];
  if(!columns.length){mount.innerHTML='<p class="empty">—</p>';scopeSelection={kind:null,filePath:null,columnId:null};refreshScopeFullscreen();renderScopeInspector();return}
  const field=(label,value)=>'<div><dt>'+esc(label)+'</dt><dd>'+(value||"—")+'</dd></div>';
  const headers=columns.map(column=>{
    if(column.type==="worktree"){
      const worktree=column.worktree;
      const agent=worktree.agent||{};
      const unknown=worktree.scope_status==="unknown";
      const branch=worktree.branch?'<code>'+esc(worktree.branch)+'</code>'+copyButton(worktree.branch,"複製"):"—";
      const thread=agent.thread_id?'<code>'+esc(agent.thread_id)+'</code>'+copyButton(agent.thread_id,"複製"):"—";
      const title=agent.title?'<code>'+esc(agent.title)+'</code>'+copyButton(agent.title,"複製"):"—";
      const dirtyCount=Number.isInteger(worktree.dirty_file_count)?String(worktree.dirty_file_count):"—";
      return '<th scope="col" class="scope-column-head scope-column-worktree scope-worktree-'+esc(worktree.kind)+(unknown?" scope-column-scope-unknown":"")+'" data-column-id="'+esc(column.id)+'" data-column-type="worktree" tabindex="0"><div class="scope-column-identity"><strong>worktree</strong>'+copyButton(worktree.id,"複製 ID")+'</div><dl class="scope-column-fields">'+field("branch",branch)+field("agent_title",title)+field("agent_status",esc(agent.status||"unknown"))+field("kind",esc(worktree.kind))+field("thread",thread)+field("state",esc(worktree.state||"active"))+field("scope",unknown?"unknown":"known")+field("dirty",esc(dirtyStateOf(worktree)))+field("dirty_file_count",esc(dirtyCount))+'</dl></th>';
    }
    const ticket=column.ticket;
    const collision=ticket.collision||null;
    const unknown=ticket.scope_status==="unknown";
    const collisionValue=collision?collision.status+(collision.with_worktrees?.length?" · "+collision.with_worktrees.join(", "):""):"—";
    const collisionPaths=collision?.paths?.length?collision.paths.join(", "):"—";
    return '<th scope="col" class="scope-column-head scope-column-ticket'+(collision?.status==="hard"?" scope-column-collision":"")+(unknown?" scope-column-scope-unknown":"")+'" data-column-id="'+esc(column.id)+'" data-column-type="ticket" tabindex="0"><div class="scope-column-identity"><strong>ticket</strong>'+copyButton(ticket.id,"複製 ID")+'</div><dl class="scope-column-fields">'+field("id",'<code>'+esc(ticket.id)+'</code>')+field("type","queued")+field("state",esc(ticket.state||"queued"))+field("scope",unknown?"unknown":"known")+field("collision",esc(collisionValue))+field("paths",esc(collisionPaths))+'</dl></th>';
  }).join("");
  const body=files.map(file=>{
    const cells=new Map((file.cells||[]).map(cell=>[cell.column_type==="worktree"?cell.worktree_id:cell.ticket_id,cell]));
    return '<tr data-file-path="'+esc(file.path)+'"><th scope="row" class="scope-file-name" data-file-path="'+esc(file.path)+'" tabindex="0"><code title="'+esc(file.path)+'">'+esc(file.path)+'</code>'+copyButton(file.path,"複製")+'</th>'+columns.map(column=>{
      const cell=cells.get(column.id);
      if(!cell)return '<td class="scope-empty-cell" data-file-path="'+esc(file.path)+'" data-column-id="'+esc(column.id)+'" data-column-type="'+esc(column.type)+'" tabindex="0" role="gridcell" aria-label="'+esc(file.path)+' · '+esc(column.id)+' · empty">·</td>';
      const collision=cell.collision===true;
      const operations=Array.isArray(cell.operations)&&cell.operations.length?cell.operations:[cell.operation];
      const symbol=operations.map(operation=>operation==="add"?"+":"~").join("");
      const label=column.id+" · "+cell.state+" · "+operations.map(scopeOperationLabel).join(" / ")+(collision?" · collision":"");
      const worktreeKind=column.type==="worktree"?" scope-worktree-"+esc(column.worktree.kind):"";
      return '<td class="scope-cell scope-cell-'+esc(cell.state)+' scope-cell-'+esc(column.type)+worktreeKind+' scope-operation-'+esc(cell.operation)+(collision?" scope-cell-collision":"")+'" data-file-path="'+esc(file.path)+'" data-column-id="'+esc(column.id)+'" data-column-type="'+esc(column.type)+'" tabindex="0" role="gridcell" title="'+esc(label)+'" aria-label="'+esc(label)+'"><span>'+esc(symbol)+'</span></td>';
    }).join("")+'</tr>';
  }).join("");
  mount.innerHTML='<table class="scope-matrix" aria-label="檔案佔用矩陣"><thead><tr class="scope-header-row"><th scope="col" class="scope-file-head" tabindex="0">path</th>'+headers+'</tr></thead><tbody>'+body+'</tbody></table>';
  bindCopyButtons(mount);
  applyScopeGeometry(mount);
  refreshScopeFullscreen();
  bindScopeSelection(mount);
  restoreScopeSelection(mount);
}
function rows(){
  const blocked=new Set(board.blocked_ids);
  const source=tab==="now"?board.board.filter(row=>board.dispatch_ids.includes(row.id)):
    tab==="blocked"?board.board.filter(row=>blocked.has(row.id)):
    tab==="inflight"?board.board.filter(row=>row.held):
    tab==="ungroomed"?board.board.filter(row=>row.decision==="needs-grooming"):
    tab==="contract"?board.board.filter(row=>row.decision==="contract-not-ready"):
    tab==="history"?(history?.board||[]):board.board;
  const needle=query.trim().toLowerCase();
  return needle?source.filter(row=>`${row.id} ${row.brief} ${row.detail}`.toLowerCase().includes(needle)):source;
}
function detailBody(row){
  return `<div class="meta"><span>${esc(row.stream)}</span><span>${esc(statusOf(row))}</span><span>${esc(row.held?.branch||"尚未掛入 worktree")}</span><span>${esc(row.area||"未標定")}</span></div>
    ${board.blocked_ids.includes(row.id)?`<p class="blocked-reason"><strong>阻塞原因</strong> ${esc(blockedReason(row))}</p>`:""}
    <p>${esc(row.detail||"沒有更多技術說明")}</p>
    <dl class="detail-grid">
      <dt>Scope</dt><dd>${scopeDetail(row.scope)}</dd>
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
const TREE_VIEW_RADIUS = 10;
const TREE_ZOOM_MIN = 70;
const TREE_ZOOM_MAX = 140;
const TREE_ZOOM_STEP = 10;
const TREE_LANE_WIDTH = 124;
const TREE_LANE_WIDTH_MIN = 104;
const TREE_LANE_WIDTH_MAX = 224;
const TREE_LANE_WIDTH_STEP = 4;
const TREE_ROW_HEIGHT = 44;
const TREE_HEADER_HEIGHT = 66;
const TREE_PADDING_X = 30;
const TREE_FULLSCREEN_MIN_SCALE = 0.25;
const TREE_FULLSCREEN_MAX_SCALE = 4;
const TREE_FULLSCREEN_ZOOM_FACTOR = 1.18;
let treeZoom = 100;
let treeLaneWidth = TREE_LANE_WIDTH;
let treeBaseWidth = 0;
let treeFitInitialized = false;
let treeRenderContext = null;
const treeFullscreen = {
  open: false,
  scale: 1,
  x: 0,
  y: 0,
  pointers: new Map(),
  drag: null,
  pinch: null,
  suppressClick: false,
  previousFocus: null,
  nativeFullscreen: false,
};
function firstParentChain(sha,commits,limit=commits.size+1){
  const result=[],seen=new Set();let current=sha;
  while(current&&!seen.has(current)&&result.length<limit){
    seen.add(current);result.push(current);
    current=commits.get(current)?.parents?.[0]||null;
  }
  return result;
}
function reachableCommitSet(sha,commits,limit=commits.size+1){
  const result=new Set(),pending=sha?[sha]:[];
  while(pending.length&&result.size<limit){
    const current=pending.pop();
    if(!current||result.has(current))continue;
    result.add(current);
    (commits.get(current)?.parents||[]).forEach(parent=>pending.push(parent));
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
  const snapshotIncomplete=tree.complete!==true;
  const mainline=firstParentChain(mainHead,commits),mainReachableSet=reachableCommitSet(mainHead,commits);
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
  const mainlineSet=mainReachableSet;
  const ticketRefs=refs.filter(ref=>ref.branch!=="main"&&(ref.tickets||[]).length);
  const addBranch=ref=>{
    const projection=projectBranchPath(ref,mainlineSet,commits);
    const {path,anchor,truncated,detached}=projection;
    visibleBranches.add(ref.branch);branchAnchors.set(ref.branch,anchor);branchPaths.set(ref.branch,path);
    // A missing parent/ref in a bounded or incomplete mirror is not proof that
    // the branch is detached. Keep the source status and let the boundary
    // marker plus Inspector carry the incomplete-topology evidence.
    if(detached&&!snapshotIncomplete)branchDetached.add(ref.branch);
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
  const laneInput=document.getElementById("tree-lane-spacing");
  const laneOutput=document.getElementById("tree-lane-spacing-value");
  if(laneInput){laneInput.value=String(treeLaneWidth);laneInput.min=String(TREE_LANE_WIDTH_MIN);laneInput.max=String(TREE_LANE_WIDTH_MAX);laneInput.step=String(TREE_LANE_WIDTH_STEP);laneInput.setAttribute("aria-valuetext",`${treeLaneWidth}px`)}
  if(laneOutput)laneOutput.textContent=`${treeLaneWidth}px`;
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
function treeDisplayState(ref){
  return treeRenderContext?.viewport?.branchDetached?.has(ref.branch)?"未連接":treeStateOf(ref);
}
function treeStateClass(value){
  return String(value||"unknown").toLowerCase().replace(/[^a-z0-9_-]+/g,"-");
}
function renderBranchIndex(viewport){
  const mount=document.getElementById("branch-index");
  if(!mount)return;
  const refs=viewport.refs||[];
  const field=(label,value)=>'<div><dt>'+esc(label)+'</dt><dd>'+(value||"—")+'</dd></div>';
  const items=refs.map(ref=>{
    const detached=viewport.branchDetached?.has(ref.branch),state=detached?"未連接":treeStateOf(ref),stateClass=detached?"detached":treeStateClass(treeStateOf(ref));
    const worktree=treeWorktreeForBranch(ref.branch),agent=worktree?.agent||{};
    const tickets=(ref.tickets||[]).map(ticket=>'<button type="button" class="branch-index-ticket tree-ticket" data-ticket-id="'+esc(ticket.id)+'">'+esc(ticket.id)+'</button>').join("");
    const path=worktree?.path||ref.path;
    const pathMarkup=path?'<code>'+esc(path)+'</code>'+copyButton(path,"複製"):"—";
    const branchButton='<button type="button" class="branch-index-select" data-branch="'+esc(ref.branch)+'" aria-label="選取分支 '+esc(ref.branch)+'"><code>'+esc(ref.branch)+'</code></button>';
    return '<article class="branch-index-item state-'+esc(stateClass)+'" data-branch="'+esc(ref.branch)+'"><div class="branch-index-heading">'+branchButton+copyButton(ref.branch,"複製")+'</div><dl class="branch-index-fields">'+field("head",'<code>'+esc(ref.head||"—")+'</code>')+field("state",esc(state))+field("agent_title",'<code>'+esc(agent.title||"—")+'</code>')+field("agent_status",esc(agent.status||"unknown"))+field("thread",'<code>'+esc(agent.thread_id||"—")+'</code>'+copyButton(agent.thread_id,"複製"))+field("worktree",pathMarkup)+field("host",esc(worktree?.host||ref.host||"—"))+field("tickets",tickets)+'</dl></article>';
  }).join("");
  mount.innerHTML=items||'<p class="empty">—</p>';
  bindCopyButtons(mount);
  mount.querySelectorAll("[data-ticket-id]").forEach(node=>node.addEventListener("click",event=>{
    event.stopPropagation();
    selectTicket(node.dataset.ticketId);
  }));
  mount.querySelectorAll(".branch-index-select").forEach(node=>{
    const ref=refs.find(item=>item.branch===node.dataset.branch);
    bindBranchNode(node,ref);
  });
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
function routeCrossLaneEdge(from,to,x,y){
  const startX=x(from.lane),startY=y(from.row),endX=x(to.lane),endY=y(to.row);
  return `M ${endX} ${endY} H ${startX} V ${startY}`;
}
function edgePath(from,to,x,y){
  if(from.lane===to.lane)return `M ${x(from.lane)} ${y(from.row)} V ${y(to.row)}`;
  return routeCrossLaneEdge(from,to,x,y);
}
function treeRefsForCommit(row,ref){
  const names=new Set(Array.isArray(row?.refs)?row.refs:[]);
  if(ref?.branch)names.add(ref.branch);
  return [...names];
}
function treeWorktreeForBranch(branch){
  return (scopeMatrix?.worktrees||[]).find(worktree=>worktree.branch===branch)||null;
}
function renderCommitInspector(row,ref,branchOverride){
  const inspector=document.getElementById("commit-inspector");
  if(!inspector||!row)return;
  const branches=treeRefsForCommit(row,ref);
  const refs=branches.length?branches.map(branch=>"<code>"+esc(branch)+"</code>").join("<br>"):"—";
  const paths=branches.map(branch=>treeWorktreeForBranch(branch)?.path||treeRenderContext?.refs.find(item=>item.branch===branch)?.path).filter(Boolean);
  const worktrees=paths.length?paths.map(path=>"<code>"+esc(path)+"</code>").join("<br>"):"—";
  const parents=Array.isArray(row.parents)&&row.parents.length?scopeSourceListMarkup(row.parents):"root";
  inspector.innerHTML='<span class="eyebrow">COMMIT INSPECTOR</span><dl class="detail-grid">'+
    scopeFieldMarkup("sha",'<code>'+esc(row.sha)+'</code>'+copyButton(row.sha,"複製"))+
    scopeFieldMarkup("subject",'<span>'+esc(row.subject||"—")+'</span>'+copyButton(row.subject,"複製"))+
    scopeFieldMarkup("author",esc(row.author||"—"))+
    scopeFieldMarkup("committer",esc(row.committer||"—"))+
    scopeFieldMarkup("authored_at",esc(row.authored_at||"—"))+
    scopeFieldMarkup("committed_at",esc(row.committed_at||"—"))+
    scopeFieldMarkup("parents",parents)+
    scopeFieldMarkup("refs",refs)+
    scopeFieldMarkup("branch",esc(branches.join(", ")||"—"))+
    scopeFieldMarkup("worktree",worktrees)+
    scopeFieldMarkup("diff_stat",esc(formatDiffStat(row)))+
    scopeFieldMarkup("files",scopeSourceListMarkup(row.files))+
    '</dl>';
  inspector.hidden=false;
  bindCopyButtons(inspector);
}
function renderBranchInspector(ref){
  const inspector=document.getElementById("commit-inspector");
  if(!inspector||!ref)return;
  const worktree=treeWorktreeForBranch(ref.branch),agent=worktree?.agent||{};
  const dirtyFiles=worktree?.dirty_files||ref.dirty_files||[];
  inspector.innerHTML='<span class="eyebrow">BRANCH INSPECTOR</span><dl class="detail-grid">'+
    scopeFieldMarkup("branch",'<code>'+esc(ref.branch)+'</code>'+copyButton(ref.branch,"複製"))+
    scopeFieldMarkup("state",esc(treeDisplayState(ref)))+
    scopeFieldMarkup("head",'<code>'+esc(ref.head||"—")+'</code>'+copyButton(ref.head,"複製"))+
    scopeFieldMarkup("base",'<code>'+esc(ref.base||"—")+'</code>')+
    scopeFieldMarkup("base_sha",'<code>'+esc(ref.base_sha||"—")+'</code>'+copyButton(ref.base_sha,"複製"))+
    scopeFieldMarkup("worktree",'<code>'+esc(worktree?.path||ref.path||"—")+'</code>'+copyButton(worktree?.path||ref.path,"複製"))+
    scopeFieldMarkup("host",esc(worktree?.host||ref.host||"—"))+
    scopeFieldMarkup("thread",'<code>'+esc(agent.thread_id||"—")+'</code>'+copyButton(agent.thread_id,"複製"))+
    scopeFieldMarkup("agent_title",'<code>'+esc(agent.title||"—")+'</code>'+copyButton(agent.title,"複製"))+
    scopeFieldMarkup("agent_status",esc(agent.status||"unknown"))+
    scopeFieldMarkup("integration_owner",esc(ref.integration_owner||"—"))+
    scopeFieldMarkup("worktree_present",esc(typeof (worktree?.worktree_present??ref.worktree_present)==="boolean"?String(worktree?.worktree_present??ref.worktree_present):"—"))+
    scopeFieldMarkup("dirty",esc(dirtyStateOf(worktree||ref)))+
    scopeFieldMarkup("dirty_file_count",esc(Number.isInteger(worktree?.dirty_file_count)?worktree.dirty_file_count:(Number.isInteger(ref.dirty_file_count)?ref.dirty_file_count:"—")))+
    scopeFieldMarkup("dirty_files",scopeSourceListMarkup(dirtyFiles))+
    scopeFieldMarkup("tickets",esc((ref.tickets||[]).map(ticket=>ticket.id).join(", ")||"—"))+
    '</dl>';
  inspector.hidden=false;
  bindCopyButtons(inspector);
}
function renderBoundaryInspector(data){
  const inspector=document.getElementById("commit-inspector");
  if(!inspector)return;
  inspector.innerHTML='<span class="eyebrow">GRAPH BOUNDARY INSPECTOR</span><dl class="detail-grid">'+
    scopeFieldMarkup("boundary_id",'<code>'+esc(data.boundaryId||"—")+'</code>'+copyButton(data.boundaryId,"複製"))+
    scopeFieldMarkup("kind",esc(data.boundaryKind||data.kind||"—"))+
    scopeFieldMarkup("branch",esc(data.branch||"—"))+
    scopeFieldMarkup("at_commit",'<code>'+esc(data.sha||"—")+'</code>'+copyButton(data.sha,"複製"))+
    scopeFieldMarkup("missing_parent",'<code>'+esc(data.parent||"—")+'</code>'+copyButton(data.parent,"複製"))+
    scopeFieldMarkup("parent_in_graph","false")+
    scopeFieldMarkup("truncated",esc(data.boundaryKind==="branch_truncation"?"true":"false"))+
    '</dl>';
  inspector.hidden=false;
  bindCopyButtons(inspector);
}
function renderTreeInspector(){
  const inspector=document.getElementById("commit-inspector");
  if(!inspector)return;
  if(!treeSelection.kind){
    inspector.hidden=true;
    inspector.innerHTML="";
    return;
  }
  if(treeSelection.kind==="commit"){
    const row=treeRenderContext?.commits.get(treeSelection.sha);
    const ref=treeRenderContext?.refs.find(item=>item.branch===treeSelection.branch);
    if(row){renderCommitInspector(row,ref,treeSelection.branch);return}
  }else if(treeSelection.kind==="branch"){
    const ref=treeRenderContext?.refs.find(item=>item.branch===treeSelection.branch);
    if(ref){renderBranchInspector(ref);return}
  }else if(treeSelection.kind==="boundary"){
    renderBoundaryInspector(treeSelection);
    return;
  }
  treeSelection={kind:null,branch:null,sha:null,boundaryId:null,boundaryKind:null,parent:null};
  inspector.hidden=true;
  inspector.innerHTML="";
}
function applyTreeSelection(){
  const root=document;
  root.querySelectorAll(".tree-selected,.tree-related,.tree-edge-selected,.tree-branch-selected,.tree-boundary-selected").forEach(node=>{
    node.classList.remove("tree-selected","tree-related","tree-edge-selected","tree-branch-selected","tree-boundary-selected");
  });
  if(!treeSelection.kind){
    renderTreeInspector();
    return;
  }
  if(treeSelection.kind==="branch"){
    const branch=treeSelection.branch;
    root.querySelectorAll('[data-branch="'+CSS.escape(branch)+'"]').forEach(node=>node.classList.add("tree-branch-selected"));
    root.querySelectorAll(".tree-lane-guide").forEach(node=>{
      if(node.dataset.branch===branch)node.classList.add("tree-branch-selected");
    });
    const branchShas=new Set(treeRenderContext?.viewport.branchPaths.get(branch)||[]);
    const ref=treeRenderContext?.refs.find(item=>item.branch===branch);
    if(ref)branchShas.add(ref.head);
    root.querySelectorAll(".commit,.tree-mobile-commit").forEach(node=>{
      const branches=(node.dataset.branches||"").split(" ").filter(Boolean);
      if(branches.includes(branch))node.classList.add("tree-related");
    });
    root.querySelectorAll(".edge[data-from-sha][data-to-sha]").forEach(node=>{
      if(branchShas.has(node.dataset.fromSha)||branchShas.has(node.dataset.toSha))node.classList.add("tree-edge-selected");
    });
  }else if(treeSelection.kind==="commit"){
    const sha=treeSelection.sha;
    const row=treeRenderContext?.commits.get(sha);
    const parentSet=new Set(row?.parents||[]);
    root.querySelectorAll('.commit[data-sha="'+CSS.escape(sha)+'"],.tree-mobile-commit[data-sha="'+CSS.escape(sha)+'"]').forEach(node=>node.classList.add("tree-selected"));
    parentSet.forEach(parent=>{
      root.querySelectorAll('.commit[data-sha="'+CSS.escape(parent)+'"],.tree-mobile-commit[data-sha="'+CSS.escape(parent)+'"]').forEach(node=>node.classList.add("tree-related"));
    });
    root.querySelectorAll(".edge[data-from-sha][data-to-sha]").forEach(node=>{
      if(node.dataset.fromSha===sha||parentSet.has(node.dataset.toSha))node.classList.add("tree-edge-selected");
    });
  }else if(treeSelection.kind==="boundary"){
    root.querySelectorAll('.tree-boundary[data-boundary-id="'+CSS.escape(treeSelection.boundaryId||"")+'"]').forEach(node=>node.classList.add("tree-boundary-selected","tree-selected"));
  }
  renderTreeInspector();
}
function setTreeSelection(next){
  treeSelection={
    kind:next?.kind||null,
    branch:next?.branch||null,
    sha:next?.sha||null,
    boundaryId:next?.boundaryId||null,
    boundaryKind:next?.boundaryKind||null,
    parent:next?.parent||null,
  };
  applyTreeSelection();
}
function selectBoundary(node){
  setTreeSelection({
    kind:"boundary",
    boundaryId:node.dataset.boundaryId,
    branch:node.dataset.boundaryBranch,
    sha:node.dataset.boundarySha,
    parent:node.dataset.boundaryParent,
    boundaryKind:node.dataset.boundaryKind,
  });
}
function bindTreeSelection(node,choose){
  if(!node||node.dataset.selectionBound==="true")return;
  node.dataset.selectionBound="true";
  node.addEventListener("click",event=>{
    if(event.target.closest(".copy-button,.tree-ticket"))return;
    choose(event);
  });
  node.addEventListener("keydown",event=>{
    if(event.key!=="Enter"&&event.key!==" ")return;
    event.preventDefault();
    choose(event);
  });
}
function bindCommitNode(node,row,ref,meta={}){
  if(!row)return;
  const branch=ref?.branch||node.dataset.ref||(node.dataset.branches||"").split(" ")[0]||null;
  bindTreeSelection(node,()=>setTreeSelection({kind:"commit",sha:row.sha,branch}));
}
function bindBranchNode(node,ref){
  if(!ref)return;
  bindTreeSelection(node,()=>setTreeSelection({kind:"branch",branch:ref.branch}));
}
function bindRenderedTreeNodes(mount,context){
  if(!mount||!context)return;
  const {commits,refs}=context;
  mount.querySelectorAll(".commit").forEach(node=>{
    const row=commits.get(node.dataset.sha);
    bindCommitNode(node,row,refs.find(ref=>ref.branch===node.dataset.ref));
  });
  mount.querySelectorAll(".lane-header").forEach(node=>{
    const ref=refs.find(item=>item.branch===node.dataset.branch);
    bindBranchNode(node,ref);
  });
  mount.querySelectorAll(".tree-boundary").forEach(node=>{
    bindTreeSelection(node,()=>selectBoundary(node));
  });
}
function restoreTreeSelection(){
  if(!treeSelection.kind){
    renderTreeInspector();
    return;
  }
  const context=treeRenderContext;
  const valid=treeSelection.kind==="branch"
    ?!!context?.refs.some(ref=>ref.branch===treeSelection.branch)
    :treeSelection.kind==="commit"
      ?!!context?.commits.has(treeSelection.sha)
    :!!document.querySelector('#git-tree .tree-boundary[data-boundary-id="'+CSS.escape(treeSelection.boundaryId||"")+'"]');
  if(!valid)treeSelection={kind:null,branch:null,sha:null,boundaryId:null,boundaryKind:null,parent:null};
  applyTreeSelection();
}

const scopeFullscreen={open:false,scale:1,previousFocus:null};
function scopeFullscreenCanvas(){return document.getElementById("scope-fullscreen-canvas")}
function scopeFullscreenTable(){return scopeFullscreenCanvas()?.querySelector(".scope-matrix")||null}
function clampScopeFullscreenScale(value){return Math.max(.5,Math.min(2.5,value))}
function applyScopeFullscreenTransform(){
  const canvas=scopeFullscreenCanvas(),table=scopeFullscreenTable();if(!canvas||!table)return;
  table.style.transform=`scale(${scopeFullscreen.scale})`;
  table.style.transformOrigin="top left";
  table.style.width=`${100/scopeFullscreen.scale}%`;
  const output=document.getElementById("scope-fullscreen-zoom");
  if(output)output.textContent=`${Math.round(scopeFullscreen.scale*100)}%`;
}
function refreshScopeFullscreen(){
  if(!scopeFullscreen.open)return;
  const source=document.getElementById("scope-matrix-wrap"),canvas=scopeFullscreenCanvas();
  if(!source||!canvas)return;
  canvas.innerHTML=source.innerHTML;
  canvas.querySelectorAll("[data-selection-bound],[data-copy-bound]").forEach(node=>{
    delete node.dataset.selectionBound;
    delete node.dataset.copyBound;
  });
  bindCopyButtons(canvas);
  applyScopeGeometry(canvas);
  bindScopeSelection(canvas);
  restoreScopeSelection(canvas);
  applyScopeFullscreenTransform();
}
function fitScopeFullscreen(){
  const canvas=scopeFullscreenCanvas(),table=scopeFullscreenTable();if(!canvas||!table)return false;
  const width=Math.max(1,table.scrollWidth),available=Math.max(1,canvas.clientWidth-24);
  scopeFullscreen.scale=clampScopeFullscreenScale(Math.min(1,available/width));
  applyScopeFullscreenTransform();
  return true;
}
function resetScopeFullscreen(){scopeFullscreen.scale=1;applyScopeFullscreenTransform()}
function openScopeFullscreen(){
  const viewer=document.getElementById("scope-fullscreen-viewer"),source=document.getElementById("scope-matrix-wrap");
  if(!viewer||!source?.querySelector(".scope-matrix"))return;
  scopeFullscreen.open=true;scopeFullscreen.previousFocus=document.activeElement;scopeFullscreen.scale=1;
  viewer.hidden=false;viewer.setAttribute("aria-hidden","false");document.body.classList.add("scope-fullscreen-open");
  refreshScopeFullscreen();
  requestAnimationFrame(()=>{fitScopeFullscreen();document.getElementById("scope-fullscreen-close")?.focus()});
}
function closeScopeFullscreen(options={}){
  const viewer=document.getElementById("scope-fullscreen-viewer"),previousFocus=scopeFullscreen.previousFocus;
  scopeFullscreen.open=false;scopeFullscreen.scale=1;
  if(viewer){viewer.hidden=true;viewer.setAttribute("aria-hidden","true")}
  document.body.classList.remove("scope-fullscreen-open");
  if(options.restoreFocus!==false)previousFocus?.focus?.();
}
function fullscreenCanvas(){return document.getElementById("tree-fullscreen-canvas")}
function fullscreenSvg(){return fullscreenCanvas()?.querySelector("svg")||null}
function clampTreeFullscreenScale(value){return Math.max(TREE_FULLSCREEN_MIN_SCALE,Math.min(TREE_FULLSCREEN_MAX_SCALE,value))}
function fullscreenCanvasPoint(clientX,clientY){
  const canvas=fullscreenCanvas(),rect=canvas?.getBoundingClientRect();
  if(!rect)return {x:0,y:0};
  return {x:clientX-rect.left,y:clientY-rect.top};
}
function fullscreenSvgSize(svg){
  const width=Number(svg?.getAttribute("width")),height=Number(svg?.getAttribute("height"));
  if(Number.isFinite(width)&&width>0&&Number.isFinite(height)&&height>0)return {width,height};
  const viewBox=(svg?.getAttribute("viewBox")||"").trim().split(/\s+/).map(Number);
  return {width:viewBox[2]||1,height:viewBox[3]||1};
}
function applyTreeFullscreenTransform(){
  const svg=fullscreenSvg();if(!svg)return;
  const {width,height}=fullscreenSvgSize(svg);
  svg.style.width=`${Math.max(1,Math.round(width*treeFullscreen.scale))}px`;
  svg.style.height=`${Math.max(1,Math.round(height*treeFullscreen.scale))}px`;
  svg.style.left=`${Math.round(treeFullscreen.x)}px`;
  svg.style.top=`${Math.round(treeFullscreen.y)}px`;
  svg.style.transform="none";
  const output=document.getElementById("tree-fullscreen-zoom");
  if(output)output.textContent=`${Math.round(treeFullscreen.scale*100)}%`;
}
function refreshTreeFullscreen(){
  if(!treeFullscreen.open)return;
  const source=document.getElementById("git-tree"),canvas=fullscreenCanvas();
  if(!source||!canvas)return;
  canvas.innerHTML=source.innerHTML;
  canvas.querySelectorAll("[data-selection-bound],[data-copy-bound]").forEach(node=>{
    delete node.dataset.selectionBound;
    delete node.dataset.copyBound;
  });
  const svg=canvas.querySelector("svg");
  if(!svg){canvas.classList.add("is-empty");return}
  canvas.classList.remove("is-empty");
  svg.classList.add("tree-fullscreen-svg");
  bindRenderedTreeNodes(canvas,treeRenderContext);
  applyTreeFullscreenTransform();
}
function zoomTreeFullscreenAt(nextScale,clientX,clientY){
  const svg=fullscreenSvg();if(!svg)return;
  const point=fullscreenCanvasPoint(clientX??window.innerWidth/2,clientY??window.innerHeight/2);
  const previousScale=treeFullscreen.scale;
  const scale=clampTreeFullscreenScale(nextScale);
  const contentX=(point.x-treeFullscreen.x)/previousScale;
  const contentY=(point.y-treeFullscreen.y)/previousScale;
  treeFullscreen.scale=scale;
  treeFullscreen.x=point.x-contentX*scale;
  treeFullscreen.y=point.y-contentY*scale;
  applyTreeFullscreenTransform();
}
function zoomTreeFullscreen(factor,clientX,clientY){zoomTreeFullscreenAt(treeFullscreen.scale*factor,clientX,clientY)}
function fitTreeFullscreen(){
  const canvas=fullscreenCanvas(),svg=fullscreenSvg();if(!canvas||!svg)return false;
  const {width,height}=fullscreenSvgSize(svg);
  const scale=clampTreeFullscreenScale(Math.min((canvas.clientWidth-32)/width,(canvas.clientHeight-32)/height));
  treeFullscreen.scale=scale;
  treeFullscreen.x=Math.round((canvas.clientWidth-width*scale)/2);
  treeFullscreen.y=Math.round((canvas.clientHeight-height*scale)/2);
  applyTreeFullscreenTransform();
  return true;
}
function resetTreeFullscreen(){
  treeFullscreen.scale=1;treeFullscreen.x=24;treeFullscreen.y=24;applyTreeFullscreenTransform();
}
function treePointerDistance(left,right){return Math.hypot(right.x-left.x,right.y-left.y)}
function treePointerCenter(left,right){return {x:(left.x+right.x)/2,y:(left.y+right.y)/2}}
function beginTreeFullscreenPinch(){
  const points=[...treeFullscreen.pointers.values()];if(points.length<2)return;
  const center=treePointerCenter(points[0],points[1]),point=fullscreenCanvasPoint(center.x,center.y);
  treeFullscreen.pinch={
    distance:Math.max(1,treePointerDistance(points[0],points[1])),
    scale:treeFullscreen.scale,
    contentX:(point.x-treeFullscreen.x)/treeFullscreen.scale,
    contentY:(point.y-treeFullscreen.y)/treeFullscreen.scale,
  };
  treeFullscreen.drag=null;
}
function handleTreeFullscreenPointerDown(event){
  if(event.pointerType==="mouse"&&event.button!==0)return;
  const canvas=fullscreenCanvas();if(!canvas)return;
  canvas.setPointerCapture?.(event.pointerId);
  treeFullscreen.pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});
  if(treeFullscreen.pointers.size===1){
    treeFullscreen.drag={startX:event.clientX,startY:event.clientY,originX:treeFullscreen.x,originY:treeFullscreen.y,moved:false};
  }else if(treeFullscreen.pointers.size===2){beginTreeFullscreenPinch()}
  event.preventDefault();
}
function handleTreeFullscreenPointerMove(event){
  const point=treeFullscreen.pointers.get(event.pointerId);if(!point)return;
  point.x=event.clientX;point.y=event.clientY;
  if(treeFullscreen.pointers.size>=2&&treeFullscreen.pinch){
    const points=[...treeFullscreen.pointers.values()],center=treePointerCenter(points[0],points[1]);
    const distance=Math.max(1,treePointerDistance(points[0],points[1]));
    const scale=clampTreeFullscreenScale(treeFullscreen.pinch.scale*distance/treeFullscreen.pinch.distance);
    const canvasPoint=fullscreenCanvasPoint(center.x,center.y);
    treeFullscreen.scale=scale;
    treeFullscreen.x=canvasPoint.x-treeFullscreen.pinch.contentX*scale;
    treeFullscreen.y=canvasPoint.y-treeFullscreen.pinch.contentY*scale;
    applyTreeFullscreenTransform();event.preventDefault();return;
  }
  if(!treeFullscreen.drag)return;
  const dx=event.clientX-treeFullscreen.drag.startX,dy=event.clientY-treeFullscreen.drag.startY;
  if(Math.abs(dx)>4||Math.abs(dy)>4)treeFullscreen.drag.moved=true;
  treeFullscreen.x=treeFullscreen.drag.originX+dx;treeFullscreen.y=treeFullscreen.drag.originY+dy;
  applyTreeFullscreenTransform();event.preventDefault();
}
function finishTreeFullscreenPointer(event){
  const canvas=fullscreenCanvas();
  if(canvas?.hasPointerCapture?.(event.pointerId))canvas.releasePointerCapture(event.pointerId);
  if(treeFullscreen.drag?.moved){
    treeFullscreen.suppressClick=true;
    window.setTimeout(()=>{treeFullscreen.suppressClick=false},0);
  }
  treeFullscreen.pointers.delete(event.pointerId);
  treeFullscreen.pinch=null;
  if(treeFullscreen.pointers.size===1){
    const remaining=[...treeFullscreen.pointers.values()][0];
    treeFullscreen.drag={startX:remaining.x,startY:remaining.y,originX:treeFullscreen.x,originY:treeFullscreen.y,moved:false};
  }else treeFullscreen.drag=null;
}
function handleTreeFullscreenWheel(event){
  event.preventDefault();
  zoomTreeFullscreen(event.deltaY<0?TREE_FULLSCREEN_ZOOM_FACTOR:1/TREE_FULLSCREEN_ZOOM_FACTOR,event.clientX,event.clientY);
}
function handleTreeFullscreenKeydown(event){
  if(event.key==="Escape"){event.preventDefault();closeTreeFullscreen();return}
  if(event.key==="+"||event.key==="="){event.preventDefault();zoomTreeFullscreen(TREE_FULLSCREEN_ZOOM_FACTOR);return}
  if(event.key==="-"){event.preventDefault();zoomTreeFullscreen(1/TREE_FULLSCREEN_ZOOM_FACTOR);return}
  if(event.key==="0"){event.preventDefault();fitTreeFullscreen()}
}
function openTreeFullscreen(){
  const viewer=document.getElementById("tree-fullscreen-viewer"),source=document.getElementById("git-tree");
  if(!viewer||!source?.querySelector("svg"))return;
  treeFullscreen.open=true;treeFullscreen.previousFocus=document.activeElement;
  treeFullscreen.scale=1;treeFullscreen.x=0;treeFullscreen.y=0;treeFullscreen.pointers.clear();treeFullscreen.drag=null;treeFullscreen.pinch=null;
  viewer.hidden=false;viewer.setAttribute("aria-hidden","false");document.body.classList.add("tree-fullscreen-open");
  refreshTreeFullscreen();
  try{
    if(typeof viewer.requestFullscreen==="function"){
      treeFullscreen.nativeFullscreen=true;
      const request=viewer.requestFullscreen();
      request?.catch(()=>{treeFullscreen.nativeFullscreen=false});
    }
  }catch(_error){treeFullscreen.nativeFullscreen=false}
  requestAnimationFrame(()=>{fitTreeFullscreen();document.getElementById("tree-fullscreen-close")?.focus()});
}
function closeTreeFullscreen(options={}){
  const viewer=document.getElementById("tree-fullscreen-viewer"),previousFocus=treeFullscreen.previousFocus,native=treeFullscreen.nativeFullscreen;
  treeFullscreen.open=false;treeFullscreen.nativeFullscreen=false;treeFullscreen.pointers.clear();treeFullscreen.drag=null;treeFullscreen.pinch=null;
  if(viewer){viewer.hidden=true;viewer.setAttribute("aria-hidden","true")}
  document.body.classList.remove("tree-fullscreen-open");
  if(native&&document.fullscreenElement===viewer){try{const exit=document.exitFullscreen?.();exit?.catch?.(()=>{})}catch(_error){}}
  if(options.restoreFocus!==false)previousFocus?.focus?.();
}
function renderTree(){
  const mount=document.getElementById("git-tree");
  const mobile=document.getElementById("tree-mobile-list");
  renderTreeZoom();
  if(!tree||!tree.commits?.length){
    treeBaseWidth=0;
    treeRenderContext=null;
    treeSelection={kind:null,branch:null,sha:null,boundaryId:null,boundaryKind:null,parent:null};
    // Keep the one-shot fit/manual-zoom decision across a transient empty
    // mirror; a refresh must not erase an explicit user zoom choice.
    mount.innerHTML='<p class="empty">目前沒有完整 Git tree mirror。</p>';
    renderBranchIndex({refs:[]});
    if(mobile)mobile.innerHTML='<p class="empty">目前沒有可顯示的分支資料。</p>';
    renderTreeInspector();
    if(treeFullscreen.open)closeTreeFullscreen({restoreFocus:false});
    return;
  }
  const commits=new Map(tree.commits.map(row=>[row.sha,row]));
  const refs=tree.refs||[];
  const viewport=treeViewport(tree,commits,refs);
  treeRenderContext={commits,refs,viewport,positions:null};
  const visibleCommits=new Map(viewport.commits.map(row=>[row.sha,row]));
  const layout=treeLayout(viewport,visibleCommits);
  const {branchLanes,positions,ordered}=layout;
  treeRenderContext.positions=positions;
  const maxLane=Math.max(0,...branchLanes.values());
  const width=Math.max(680,TREE_PADDING_X*2+(maxLane+1)*treeLaneWidth);
  treeBaseWidth=width;
  const height=Math.max(260,TREE_HEADER_HEIGHT+(layout.rowCount+1)*TREE_ROW_HEIGHT);
  const renderedWidth=Math.round(width*treeZoom/100),renderedHeight=Math.round(height*treeZoom/100);
  const x=lane=>TREE_PADDING_X+lane*treeLaneWidth;
  const y=row=>TREE_HEADER_HEIGHT+row*TREE_ROW_HEIGHT;
  const graphEdges=[];
  ordered.forEach(row=>{
    const from=positions.get(row.sha);
    (row.parents||[]).forEach(parentSha=>{
      const to=positions.get(parentSha);
      if(to)graphEdges.push({from,to,fromSha:row.sha,toSha:parentSha});
    });
  });
  const edges=graphEdges.map(edge=>{
    return `<path class="edge" data-from-sha="${esc(edge.fromSha)}" data-to-sha="${esc(edge.toSha)}" d="${edgePath(edge.from,edge.to,x,y)}"/>`;
  });
  const branchBoundaryByFrom=new Map([...viewport.branchTruncations.values()].map(record=>[record.from,record]));
  const boundaryByLane=new Map();
  ordered.forEach(row=>{
    const pos=positions.get(row.sha),firstParent=row.parents?.[0];
    if(!pos||!firstParent||positions.has(firstParent))return;
    const previous=boundaryByLane.get(pos.lane);
    if(!previous||pos.row>previous.pos.row)boundaryByLane.set(pos.lane,{row,pos,branchBoundary:branchBoundaryByFrom.get(row.sha)});
  });
  const parentBoundaryMarkers=[...boundaryByLane.values()].sort((left,right)=>left.pos.row-right.pos.row||left.pos.lane-right.pos.lane).map(({row,pos,branchBoundary})=>{
    const branch=branchBoundary
      ? [...viewport.branchTruncations.entries()].find(([,record])=>record.from===row.sha)?.[0]
      : [...branchLanes.entries()].find(([,lane])=>lane===pos.lane)?.[0]||"main";
    const boundaryKind=branchBoundary?"branch_truncation":"parent_outside_window";
    const boundaryId=`boundary:${branch}:${row.sha}:${row.parents[0]}`;
    const markerY=y(pos.row)+Math.round(TREE_ROW_HEIGHT*.48);
    return `<g class="tree-boundary" tabindex="0" role="button" aria-label="圖面邊界" data-boundary-id="${esc(boundaryId)}" data-boundary-kind="${esc(boundaryKind)}" data-boundary-branch="${esc(branch)}" data-boundary-sha="${esc(row.sha)}" data-boundary-parent="${esc(row.parents[0])}"><path class="edge edge-parent-missing${branchBoundary?" edge-truncated":""}" d="M ${x(pos.lane)} ${y(pos.row)} V ${markerY}"><title>boundary</title></path><circle class="tree-parent-endpoint" cx="${x(pos.lane)}" cy="${markerY}" r="4"><title>boundary</title></circle><text class="tree-truncation" x="${x(pos.lane)+7}" y="${markerY+4}" aria-hidden="true">⋯</text></g>`;
  }).join("");
  const laneGuides=[...branchLanes.entries()].map(([branch,lane])=>`<line class="tree-lane-guide${branch==="main"?" main":""}" data-branch="${esc(branch)}" x1="${x(lane)}" y1="${TREE_HEADER_HEIGHT-14}" x2="${x(lane)}" y2="${height-18}"/>`).join("");
  const laneHeaders=viewport.refs.map(ref=>{
    const lane=branchLanes.get(ref.branch);if(lane===undefined)return "";
    const state=treeStateOf(ref);
    const detached=viewport.branchDetached.has(ref.branch),stateLabel=detached?"未連接":state;
    const detachedLabel=detached?`<text class="lane-state" x="14" y="31">${esc(stateLabel)}</text>`:"";
    const headerX=lane===0?0:x(lane)-52;
    return `<g class="lane-header state-${esc(treeStateClass(state))}${detached?" detached":""}" transform="translate(${headerX} 12)" tabindex="0" role="button" aria-label="分支 ${esc(ref.branch)}，工作樹 ${esc(ref.path||"未提供")}" data-branch="${esc(ref.branch)}" data-branch-label="${esc(ref.branch)}" data-state="${esc(stateLabel)}"><title>${esc(ref.branch)} · ${esc(stateLabel)}</title><circle class="lane-dot" cx="5" cy="12" r="3"></circle><text class="tree-lane-label" x="14" y="16">${esc(compactBranchLabel(ref.branch))}</text>${detachedLabel}</g>`;
  }).join("");
  const commitBranches=new Map();
  const addCommitBranch=(sha,branch)=>{
    if(!sha||!branch)return;
    if(!commitBranches.has(sha))commitBranches.set(sha,new Set());
    commitBranches.get(sha).add(branch);
  };
  viewport.mainlineWindow.forEach(sha=>addCommitBranch(sha,"main"));
  viewport.branchPaths.forEach((path,branch)=>path.forEach(sha=>addCommitBranch(sha,branch)));
  viewport.refs.forEach(ref=>addCommitBranch(ref.head,ref.branch));
  visibleCommits.forEach(row=>(row.refs||[]).forEach(branch=>addCommitBranch(row.sha,branch)));
  const nodes=ordered.map(row=>{
    const pos=positions.get(row.sha);const ref=viewport.refs.find(item=>item.head===row.sha);
    const head=ref?" head":"";
    const branches=[...(commitBranches.get(row.sha)||[])];
    return `<g class="commit${head}${ref?.branch==="main"?" main":""}" tabindex="0" role="button" aria-label="${esc(shortSha(row.sha)+" "+row.subject)}" data-sha="${esc(row.sha)}" data-ref="${esc(ref?.branch||"")}" data-branches="${esc(branches.join(" "))}" transform="translate(${x(pos.lane)} ${y(pos.row)})"><title>${esc(shortSha(row.sha)+" · "+row.subject)}</title><circle r="${head?8:6}"></circle></g>`;
  }).join("");
  mount.innerHTML=`<svg viewBox="0 0 ${width} ${height}" width="${renderedWidth}" height="${renderedHeight}" data-zoom="${treeZoom}" role="group" aria-label="主線第一個分支附近與所有工作分支的 Git 交付樹"><g class="lane-guides">${laneGuides}</g><g class="lane-headers">${laneHeaders}</g><g class="edges">${edges.join("")}${parentBoundaryMarkers}</g>${nodes}</svg>`;
  // Incomplete parent/ref state is represented by the boundary marker and its
  // structured Inspector fields; the global freshness badge remains the single
  // provenance indicator for the snapshot.
  document.getElementById("tree-alert").textContent="";
  renderBranchIndex(viewport);
  renderMobileTree(viewport,commits,commitBranches);
  bindRenderedTreeNodes(mount,treeRenderContext);
  refreshTreeFullscreen();
  restoreTreeSelection();
}
function renderMobileTree(viewport,commits,commitBranches=new Map()){
  const mount=document.getElementById("tree-mobile-list");if(!mount)return;
  const refs=viewport.refs||[];const rows=[];const seen=new Set();
  const mobileShas=[...viewport.mainlineWindow,...refs.map(ref=>ref.head),...[...viewport.branchPaths.values()].flat(),...viewport.branchAnchors.values(),...viewport.commits.map(row=>row.sha)];
  mobileShas.forEach(sha=>{if(sha&&!seen.has(sha)&&commits.has(sha)){seen.add(sha);rows.push(commits.get(sha));}});
  const branches=refs.map(ref=>{const detached=viewport.branchDetached.has(ref.branch),stateLabel=detached?"未連接":treeStateOf(ref);const tickets=(ref.tickets||[]).slice(0,3).map(t=>`<button type="button" class="tree-ticket" data-ticket-id="${esc(t.id)}">${esc(t.id)}</button>`).join("");const more=(ref.tickets||[]).length>3?`<span class="tree-ticket-more">+${(ref.tickets||[]).length-3}</span>`:"";return `<div class="tree-mobile-branch${detached?" detached":""}"><button type="button" class="tree-mobile-branch-name" data-branch="${esc(ref.branch)}" data-state="${esc(stateLabel)}" aria-label="分支 ${esc(ref.branch)}，工作樹 ${esc(ref.path||"未提供")}"><code>${esc(compactLabel(ref.branch,30))}</code></button><span>${esc(stateLabel)}</span>${tickets}${more}</div>`}).join("");
  mount.innerHTML=`<div class="tree-mobile-branches">${branches}</div><ol class="tree-mobile-commits">${rows.map(row=>`<li><button type="button" class="tree-mobile-commit" data-sha="${esc(row.sha)}" data-branches="${esc([...(commitBranches.get(row.sha)||[])].join(" "))}"><code>${esc(shortSha(row.sha))}</code><span>${esc(row.subject)}</span></button></li>`).join("")}</ol>`;
  mount.querySelectorAll(".tree-mobile-commit").forEach(node=>bindCommitNode(node,commits.get(node.dataset.sha),null));
  mount.querySelectorAll(".tree-mobile-branch-name").forEach(node=>bindBranchNode(node,refs.find(ref=>ref.branch===node.dataset.branch)));
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
  renderScopeMatrixPrimary();
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
let loadInFlight=false;
let loadQueued=false;
async function load(){
  if(loadInFlight){loadQueued=true;return}
  loadInFlight=true;
  try{
    const [boardResponse,treeResponse,scopeResponse]=await Promise.all([fetch("/api/board",{cache:"no-store"}),fetch("/api/git-tree",{cache:"no-store"}),fetch("/api/scope-matrix",{cache:"no-store"})]);
    if(!boardResponse.ok)throw new Error(`board HTTP ${boardResponse.status}`);
    if(!treeResponse.ok)throw new Error(`git tree HTTP ${treeResponse.status}`);
    if(!scopeResponse.ok)throw new Error(`scope matrix HTTP ${scopeResponse.status}`);
    board=await boardResponse.json();tree=await treeResponse.json();scopeMatrix=await scopeResponse.json();setTrust(board.freshness);render();renderTree();
    if(!treeFitInitialized&&treeBaseWidth)treeFitInitialized=fitTreeZoom();
  }finally{
    loadInFlight=false;
    if(loadQueued){loadQueued=false;queueMicrotask(()=>load().catch(showLoadError))}
  }
}
document.getElementById("tabs").addEventListener("click",async event=>{const button=event.target.closest("[data-tab]");if(!button)return;tab=button.dataset.tab;render();if(tab==="history"){try{await loadHistory();render()}catch(error){document.getElementById("status").textContent=error.message}}});
document.getElementById("search").addEventListener("input",event=>{query=event.target.value;render()});
const scopeZoomInput=document.getElementById("scope-zoom");
if(scopeZoomInput)scopeZoomInput.addEventListener("input",event=>{
  const next=Number(event.target.value);scopeZoom=Math.max(80,Math.min(140,Number.isFinite(next)?next:100));renderScopeControls();
  if(scopeMatrix)renderScopeMatrixPrimary();
});
const scopeDensityInput=document.getElementById("scope-density");
if(scopeDensityInput)scopeDensityInput.addEventListener("input",event=>{
  const next=Number(event.target.value);scopeDensity=Math.max(28,Math.min(54,Number.isFinite(next)?next:34));renderScopeControls();
  if(scopeMatrix)renderScopeMatrixPrimary();
});
const scopeOccupiedInput=document.getElementById("scope-occupied-only");
if(scopeOccupiedInput)scopeOccupiedInput.addEventListener("change",event=>{scopeOccupiedOnly=event.target.checked;if(scopeMatrix)renderScopeMatrixPrimary()});
document.getElementById("scope-fit")?.addEventListener("click",()=>{fitScopeMatrix()});
document.getElementById("scope-reset")?.addEventListener("click",()=>{scopeZoom=100;scopeDensity=34;scopeOccupiedOnly=false;renderScopeControls();if(scopeMatrix)renderScopeMatrixPrimary()});
document.getElementById("scope-fullscreen")?.addEventListener("click",openScopeFullscreen);
document.getElementById("scope-fullscreen-close")?.addEventListener("click",()=>closeScopeFullscreen());
document.getElementById("scope-fullscreen-fit")?.addEventListener("click",fitScopeFullscreen);
document.getElementById("scope-fullscreen-reset")?.addEventListener("click",resetScopeFullscreen);
document.getElementById("scope-fullscreen-zoom-in")?.addEventListener("click",()=>{scopeFullscreen.scale=clampScopeFullscreenScale(scopeFullscreen.scale*1.18);applyScopeFullscreenTransform()});
document.getElementById("scope-fullscreen-zoom-out")?.addEventListener("click",()=>{scopeFullscreen.scale=clampScopeFullscreenScale(scopeFullscreen.scale/1.18);applyScopeFullscreenTransform()});
document.getElementById("scope-fullscreen-canvas")?.addEventListener("wheel",event=>{if(!scopeFullscreen.open)return;event.preventDefault();scopeFullscreen.scale=clampScopeFullscreenScale(scopeFullscreen.scale*(event.deltaY<0?1.1:.9));applyScopeFullscreenTransform()},{passive:false});
document.addEventListener("keydown",event=>{if(event.key!=="Escape")return;if(scopeFullscreen.open)closeScopeFullscreen();else if(treeFullscreen.open)closeTreeFullscreen()});
document.getElementById("tree-zoom").addEventListener("input",event=>{
  cancelTreeAutoFit();
  const next=Number(event.target.value);
  treeZoom=Math.max(TREE_ZOOM_MIN,Math.min(TREE_ZOOM_MAX,Number.isFinite(next)?next:100));
  renderTreeZoom();
  if(tree)renderTree();
});
const laneSpacingInput=document.getElementById("tree-lane-spacing");
if(laneSpacingInput)laneSpacingInput.addEventListener("input",event=>{
  cancelTreeAutoFit();
  const next=Number(event.target.value);
  treeLaneWidth=Math.max(TREE_LANE_WIDTH_MIN,Math.min(TREE_LANE_WIDTH_MAX,Number.isFinite(next)?next:TREE_LANE_WIDTH));
  renderTreeZoom();
  if(tree)renderTree();
});
document.getElementById("tree-fit").addEventListener("click",()=>{cancelTreeAutoFit();fitTreeZoom()});
document.getElementById("tree-reset").addEventListener("click",()=>{cancelTreeAutoFit();treeZoom=100;treeLaneWidth=TREE_LANE_WIDTH;if(tree)renderTree();else renderTreeZoom()});
document.getElementById("tree-fullscreen").addEventListener("click",openTreeFullscreen);
document.getElementById("tree-fullscreen-close").addEventListener("click",()=>closeTreeFullscreen());
document.getElementById("tree-fullscreen-fit").addEventListener("click",fitTreeFullscreen);
document.getElementById("tree-fullscreen-reset").addEventListener("click",resetTreeFullscreen);
document.getElementById("tree-fullscreen-zoom-in").addEventListener("click",()=>zoomTreeFullscreen(TREE_FULLSCREEN_ZOOM_FACTOR));
document.getElementById("tree-fullscreen-zoom-out").addEventListener("click",()=>zoomTreeFullscreen(1/TREE_FULLSCREEN_ZOOM_FACTOR));
const fullscreenCanvasNode=fullscreenCanvas();
fullscreenCanvasNode.addEventListener("pointerdown",handleTreeFullscreenPointerDown);
fullscreenCanvasNode.addEventListener("pointermove",handleTreeFullscreenPointerMove);
fullscreenCanvasNode.addEventListener("pointerup",finishTreeFullscreenPointer);
fullscreenCanvasNode.addEventListener("pointercancel",finishTreeFullscreenPointer);
fullscreenCanvasNode.addEventListener("wheel",handleTreeFullscreenWheel,{passive:false});
fullscreenCanvasNode.addEventListener("keydown",handleTreeFullscreenKeydown);
fullscreenCanvasNode.addEventListener("click",event=>{
  if(!treeFullscreen.suppressClick)return;
  event.preventDefault();event.stopPropagation();treeFullscreen.suppressClick=false;
},{capture:true});
document.addEventListener("fullscreenchange",()=>{
  if(treeFullscreen.open&&treeFullscreen.nativeFullscreen&&!document.fullscreenElement)closeTreeFullscreen({restoreFocus:false});
});
const showLoadError=error=>{document.getElementById("trust-state").textContent="資料讀取錯誤";document.getElementById("trust-detail").textContent=error.message;document.getElementById("tree-alert").textContent=`看板資料讀取錯誤：${error.message}`};
const LIVE_RELOAD_DELAY_MS=25;
let liveReloadTimer=null;
let liveEvents=null;
let liveStreamConnected=false;
function scheduleLiveReload(){
  if(liveReloadTimer!==null)clearTimeout(liveReloadTimer);
  liveReloadTimer=setTimeout(()=>{liveReloadTimer=null;load().catch(showLoadError)},LIVE_RELOAD_DELAY_MS);
}
let liveFallbackTimer=null;
function clearLiveFallbackTimer(){
  if(liveFallbackTimer===null)return;
  clearTimeout(liveFallbackTimer);liveFallbackTimer=null;
}
function scheduleLiveFallback(){
  if(liveFallbackTimer!==null)return;
  const delay=700+Math.floor(Math.random()*200);
  liveFallbackTimer=setTimeout(async()=>{
    liveFallbackTimer=null;
    if(liveStreamConnected){return}
    if(!loadInFlight){try{await load()}catch(error){showLoadError(error)}}
    scheduleLiveFallback();
  },delay);
}
function connectLiveEvents(){
  if(typeof EventSource==="undefined")return;
  liveEvents=new EventSource("/api/events");
  liveEvents.addEventListener("open",()=>{liveStreamConnected=true;clearLiveFallbackTimer();scheduleLiveReload()});
  liveEvents.addEventListener("error",()=>{liveStreamConnected=false;scheduleLiveFallback()});
  liveEvents.addEventListener("snapshot",scheduleLiveReload);
}
renderTreeZoom();
connectLiveEvents();
load().catch(showLoadError);
scheduleLiveFallback();
