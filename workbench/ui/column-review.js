const $ = id => document.getElementById(id);
const state = {bid:"", blocks:null, floor:"", excludes:[], adds:[], q:"", addMode:false};
let toastTimer = null;

function esc(s){return String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function toast(text, kind=""){
  const el = $("toast"); el.textContent = text; el.className = "toast on " + kind;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.className = "toast", 2800);
}
function key(floor, cx, cy){return floor + "|" + Number(cx).toFixed(1) + "|" + Number(cy).toFixed(1);}
function centerOf(block){const b=block.bbox||[0,0,0,0];return [(b[0]+b[2])/2,(b[1]+b[3])/2];}

async function api(url, options){
  const response = await fetch(url, options || {cache:"no-store"});
  const data = await response.json().catch(() => ({}));
  if(!response.ok) throw new Error(data.error || ("HTTP " + response.status));
  return data;
}

function currentFloor(){
  return state.blocks?.floors?.find(f => f.name === state.floor) || null;
}

function isExcluded(block){
  const [cx,cy] = centerOf(block);
  const k = key(state.floor,cx,cy);
  return state.excludes.some(e => key(e.floor,e.center[0],e.center[1]) === k);
}

function renderFloorSelect(){
  const floors = state.blocks?.floors || [];
  $("floor").innerHTML = floors.map(f => `<option value="${esc(f.name)}">${esc(f.name)}</option>`).join("");
}

function renderPlan(){
  const floor = currentFloor();
  const svg = $("plan");
  if(!floor){svg.innerHTML='<text x="20" y="30" fill="#999">没有楼层数据</text>';return;}
  const blocks = floor.blocks || [];
  const walls = blocks.filter(b => b.layer === "WALL");
  const slabs = blocks.filter(b => b.layer === "SLAB");
  const cols = blocks.filter(b => b.layer === "COL");
  const boxes = [...walls,...slabs,...cols].filter(b => b.bbox);
  if(!boxes.length){svg.innerHTML='<text x="20" y="30" fill="#999">本层没有可绘制的构件</text>';return;}
  const x0=Math.min(...boxes.map(b=>b.bbox[0])), x1=Math.max(...boxes.map(b=>b.bbox[2]));
  const y0=Math.min(...boxes.map(b=>b.bbox[1])), y1=Math.max(...boxes.map(b=>b.bbox[3]));
  const pad = Math.max(400,(x1-x0)*0.03);
  const vx=x0-pad, vy=-(y1+pad), vw=(x1-x0)+pad*2, vh=(y1-y0)+pad*2;
  svg.setAttribute("viewBox",`${vx} ${vy} ${vw} ${vh}`);
  const polyRing = ring => {
    const pts=[]; for(let i=0;i<ring.length;i+=2) pts.push(`${ring[i]},${-ring[i+1]}`); return pts.join(" ");
  };
  const parts=[];
  for(const b of slabs) if(b.ring) parts.push(`<polygon points="${polyRing(b.ring)}" fill="#f7f8fa" stroke="#e6e8eb"/>`);
  for(const b of walls) if(b.ring) parts.push(`<polygon points="${polyRing(b.ring)}" fill="#cfd7df" stroke="#9aa7b2" stroke-width="8"/>`);
  for(const b of cols){
    const bb=b.bbox; if(!bb) continue;
    const off=isExcluded(b);
    parts.push(`<rect data-col="1" data-name="${esc(b.name||b.id)}" x="${bb[0]}" y="${-bb[3]}" width="${bb[2]-bb[0]}" height="${bb[3]-bb[1]}" rx="10" fill="${off?"#fff1f0":"#faad14"}" stroke="${off?"#ff4d4f":"#ad6800"}" stroke-width="12" style="cursor:pointer"/>`);
  }
  for(const a of state.adds.filter(x=>x.floor===state.floor)){
    const w=Number(a.size_mm?.[0]||600), d=Number(a.size_mm?.[1]||600), [cx,cy]=a.center;
    parts.push(`<rect x="${cx-w/2}" y="${-(cy+d/2)}" width="${w}" height="${d}" rx="10" fill="#f6ffed" stroke="#52c41a" stroke-width="14"/>`);
  }
  svg.innerHTML=parts.join("");
  $("plan-sub").textContent=`${state.floor} · ${walls.length} 段墙 · ${cols.length} 根柱 · ${state.excludes.filter(e=>e.floor===state.floor).length} 根排除 · ${state.adds.filter(a=>a.floor===state.floor).length} 根新增`;
  renderRows();
}

function renderRows(){
  const floor = currentFloor();
  if(!floor){$("rows").innerHTML='<div class="empty">没有楼层数据</div>';return;}
  const q=state.q.trim().toLowerCase();
  const cols=(floor.blocks||[]).filter(b=>b.layer==="COL").filter(b=>{
    if(!q) return true; const [cx,cy]=centerOf(b);
    return `${b.name||b.id} ${cx.toFixed(0)} ${cy.toFixed(0)}`.toLowerCase().includes(q);
  });
  const rows=cols.map(b=>{
    const [cx,cy]=centerOf(b), off=isExcluded(b);
    return `<button class="row ${off?"off":""}" data-name="${esc(b.name||b.id)}">
      <i class="dot"></i><span><b>${esc(b.name||b.id)}</b><small>${cx.toFixed(0)}, ${cy.toFixed(0)}</small></span>
      <em>${off?"排除":"保留"}</em></button>`;
  });
  for(const a of state.adds.filter(x=>x.floor===state.floor)){
    if(q && !`人工新增 ${a.center[0].toFixed(0)} ${a.center[1].toFixed(0)}`.toLowerCase().includes(q)) continue;
    rows.push(`<button class="row add" data-add="${esc(a.id)}"><i class="dot"></i><span><b>${esc(a.id)}</b><small>${a.center[0].toFixed(0)}, ${a.center[1].toFixed(0)} · ${a.size_mm[0]}×${a.size_mm[1]}</small></span><em>新增</em></button>`);
  }
  $("rows").innerHTML=rows.join("") || '<div class="empty">没有匹配的柱</div>';
  $("count").textContent=`${cols.length} 根检测柱 · ${state.excludes.filter(e=>e.floor===state.floor).length} 根排除`;
}

function toggleColumn(name){
  const floor=currentFloor(); if(!floor) return;
  const block=(floor.blocks||[]).find(b=>b.layer==="COL" && (b.name||b.id)===name);
  if(!block) return;
  const [cx,cy]=centerOf(block), k=key(state.floor,cx,cy);
  const idx=state.excludes.findIndex(e=>key(e.floor,e.center[0],e.center[1])===k);
  if(idx>=0) state.excludes.splice(idx,1);
  else state.excludes.push({floor:state.floor,center:[cx,cy],name:name,reason:"人工复核"});
  renderPlan();
}

function removeAdd(id){
  state.adds=state.adds.filter(a=>a.id!==id); renderPlan();
}

function addColumn(evt){
  if(!state.addMode) return;
  const svg=$("plan"), pt=svg.createSVGPoint();
  pt.x=evt.clientX; pt.y=evt.clientY;
  const p=pt.matrixTransform(svg.getScreenCTM().inverse());
  const w=Math.max(100,Number($("addW").value)||600), d=Math.max(100,Number($("addD").value)||600);
  state.adds.push({id:`人工-${state.floor}-${Math.round(p.x)}-${Math.round(-p.y)}`,floor:state.floor,
    center:[Math.round(p.x*10)/10,Math.round(-p.y*10)/10],size_mm:[w,d],reason:"人工补充"});
  renderPlan();
}

async function loadBlocks(){
  state.blocks=await api(`/packs/cdut-main/${encodeURIComponent(state.bid)}/meta/blocks.json`);
  const floors=state.blocks.floors||[];
  state.floor=floors.some(f=>f.name===state.floor)?state.floor:(floors[0]?.name||"");
  renderFloorSelect(); $("floor").value=state.floor; renderPlan();
}

async function loadAdjustments(){
  const data=await api(`/api/column-adjustments?bid=${encodeURIComponent(state.bid)}`);
  state.excludes=data.exclude||[]; state.adds=data.add||[];
  renderPlan();
}

async function boot(){
  let list=[];
  try{list=await api("/building-status.json");}catch(_e){list={buildings:[]};}
  const buildings=list.buildings||[];
  $("bid").innerHTML=buildings.map(b=>`<option value="${esc(b.id)}">${esc(b.id+" "+(b.title||""))}</option>`).join("");
  const q=new URLSearchParams(location.search);
  const want=q.get("bid");
  if(want && buildings.some(b=>b.id===want)) state.bid=want;
  else state.bid=buildings[0]?.id||"c001";
  $("bid").value=state.bid;
  $("back").href="/admin#/b/"+encodeURIComponent(state.bid);
  try{await loadBlocks();await loadAdjustments();}
  catch(e){toast(e.message,"bad");$("rows").innerHTML=`<div class="empty">${esc(e.message)}</div>`;}
}

$("bid").addEventListener("change", async e=>{
  state.bid=e.target.value; $("back").href="/admin#/b/"+encodeURIComponent(state.bid);
  try{await loadBlocks();await loadAdjustments();}catch(err){toast(err.message,"bad");}
});
$("floor").addEventListener("change", e=>{state.floor=e.target.value;renderPlan();});
$("search").addEventListener("input", e=>{state.q=e.target.value;renderRows();});
$("addMode").addEventListener("change", e=>{state.addMode=e.target.checked;$("plan").style.cursor=e.target.checked?"copy":"crosshair";});
$("plan").addEventListener("click", e=>{
  const add=e.target.closest("[data-add]"); if(add){removeAdd(add.dataset.add);return;}
  const col=e.target.closest("[data-col]"); if(col){toggleColumn(col.dataset.name);return;}
  addColumn(e);
});
$("rows").addEventListener("click", e=>{
  const add=e.target.closest("[data-add]"); if(add){removeAdd(add.dataset.add);return;}
  const row=e.target.closest("[data-name]"); if(row) toggleColumn(row.dataset.name);
});
$("save").addEventListener("click", async ()=>{
  try{
    const data=await api("/api/column-adjustments/save",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({bid:state.bid,exclude:state.excludes,add:state.adds})});
    state.excludes=data.exclude||[];state.adds=data.add||[];
    toast("已保存。下一步：从「建件」重跑该楼。","ok");renderPlan();
  }catch(e){toast("保存失败："+e.message,"bad");}
});
boot();
