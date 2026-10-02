# -*- coding: utf-8 -*-
"""缺陷标注台：你在图上框出哪里不对，我读 JSON 去修。

为什么需要这个
--------------
现成的 compare.html 只能**看**（左源图 / 右识别并排），你没法把「这里不对」传给我。
我这边就只能靠猜 —— 这一轮我已经猜错过两次（"add_box 是热点"、"c084 是平方级"）。
所以补上这条通道：你指，我改。

怎么用
------
    python annotate_defects.py          # 起服务，浏览器开 http://127.0.0.1:8150/
    python annotate_defects.py --dump   # 不开浏览器，直接把已存标注打到终端

在图上**按住拖动**画一个框 → 弹小窗选类型、写一句人话 → 保存。
存到 `_qa/annotations.json`。我读那个文件。

安全
----
只**读** data/ 下的 PNG；只**写** _qa/annotations.json 一个文件。
不碰 GLB、不碰 floors/、不碰任何识别产物。
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = int(os.environ.get("GYM3D_ANNOTATE_PORT", "8150"))
HOST = "127.0.0.1"
STORE = os.path.join(ROOT, "_qa", "annotations.json")
QA_DIR = os.path.dirname(STORE)                       # _qa
# 对照图目录的**所有者是 scan_defects.py**，本文件只读它（产物目录一目录一所有者：
# 这里绝不写、不删，否则两个脚本会互相覆盖对方的结论）。
SHOT_DIR = os.path.join(QA_DIR, "defect_shots")

# 缺陷类型。key 进 JSON，label 给人看。
TYPES = [
    ("wall_missing", "墙缺（图里有、模型没有）"),
    ("wall_blob", "墙糊了（多面墙粘成一坨实心块）"),
    ("wall_wrong", "墙位置/形状不对"),
    ("wall_extra", "墙多（模型有、图里没有）"),
    ("floor_misalign", "楼层错位 / 悬空 / 穿模"),
    ("outline_wrong", "整栋轮廓不对"),
    ("door", "门不对（缺 / 多 / 位置）"),
    ("window", "窗不对（缺 / 多 / 位置）"),
    ("stair", "楼梯不对（缺 / 位置 / 形状）"),
    ("other", "其他（在备注里写）"),
]


def building_list():
    """列出有对照图的楼。判据：data/buildings 下有 profile.json。"""
    from paths import BUILDINGS
    out = []
    for d in sorted(os.listdir(BUILDINGS)):
        p = os.path.join(BUILDINGS, d)
        if not (os.path.isdir(p) and os.path.exists(os.path.join(p, "profile.json"))):
            continue
        title = d
        try:
            with open(os.path.join(p, "profile.json"), encoding="utf-8") as f:
                title = json.load(f).get("title") or d
        except Exception:                                        # noqa: BLE001
            pass
        floors = []
        src, rec = os.path.join(p, "dxf_plan"), os.path.join(p, "dxf_plan_recog")
        if os.path.isdir(src):
            for fn in sorted(os.listdir(src)):
                if fn.startswith("floor") and fn.endswith(".png"):
                    F = fn[5:-4]
                    recog = os.path.join(rec, fn)
                    floors.append({"f": F, "src": True, "recog": os.path.exists(recog)})
        out.append({"name": d, "title": title, "floors": floors})
    return out


def load_ann():
    if not os.path.exists(STORE):
        return []
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                            # noqa: BLE001
        return []


def save_ann(items):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE)          # 原子替换，写一半断电不会毁掉已有标注


PAGE = r"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>缺陷标注台</title><style>
*{box-sizing:border-box}
body{font:13px/1.5 system-ui,"Microsoft YaHei",sans-serif;background:#11151a;color:#dfe4ea;margin:0;height:100vh;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:12px;padding:8px 14px;background:#1a1f26;border-bottom:1px solid #2b323b;flex:0 0 auto}
header b{font-size:14px;font-weight:600}
header .hint{color:#7d8794;font-size:12px}
main{flex:1;display:flex;min-height:0}
#side{width:230px;flex:0 0 auto;overflow:auto;background:#161b21;border-right:1px solid #2b323b;padding:6px}
.bld{padding:5px 8px;border-radius:5px;cursor:pointer;display:flex;justify-content:space-between;gap:6px}
.bld:hover{background:#222a33}
.bld.on{background:#2b3d55;color:#fff}
.bld .t{color:#8d97a3;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:110px}
.bld .n{background:#3a4551;border-radius:9px;padding:0 6px;font-size:11px;min-width:18px;text-align:center}
.bld.on .n{background:#4a6fa5}
#mid{flex:1;display:flex;flex-direction:column;min-width:0}
#floors{display:flex;gap:4px;padding:6px 10px;background:#161b21;border-bottom:1px solid #2b323b;flex-wrap:wrap;flex:0 0 auto}
.fb{padding:3px 10px;border-radius:4px;background:#232a32;cursor:pointer;font-size:12px}
.fb:hover{background:#2c353f}
.fb.on{background:#3a6ea5;color:#fff}
#stage{flex:1;overflow:auto;padding:10px;min-height:0}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.side{position:relative;background:#fff;border-radius:5px;line-height:0}
.side .tag{position:absolute;top:6px;left:6px;z-index:3;background:rgba(20,24,30,.86);color:#fff;font:600 11px/1.6 system-ui;padding:2px 8px;border-radius:4px;line-height:1.6}
.side .tag .zz{color:#9fd0ff;margin-left:6px;font-weight:600}
/* 视口：滚轮缩放、滚动条平移。scrollbar-gutter:stable 让滚动槽常驻，
   否则「放大→出滚动条→内容变窄→不出滚动条」会自激抖动。 */
.vp{overflow:auto;scrollbar-gutter:stable;height:min(60vh,640px);border-radius:5px;background:#fff}
.wrap{position:relative;width:100%;line-height:0}
.wrap img{width:100%;display:block;user-select:none;-webkit-user-drag:none}
.wrap .layer{position:absolute;inset:0;cursor:crosshair}
.bx{position:absolute;border:2px solid #ff5c5c;background:rgba(255,92,92,.18);border-radius:2px}
.bx.done{border-style:solid;background:rgba(255,92,92,.10)}
.bx .idx{position:absolute;top:-1px;left:-1px;background:#ff5c5c;color:#fff;font:600 10px/1.5 system-ui;padding:0 4px;border-radius:2px}
#pop{position:fixed;z-index:50;background:#1e252d;border:1px solid #3c4753;border-radius:7px;padding:10px;width:290px;box-shadow:0 8px 28px rgba(0,0,0,.5);display:none}
#pop .ttl{font-weight:600;margin-bottom:6px;font-size:12px;color:#9fb0c2}
#pop select,#pop textarea{width:100%;background:#141a20;color:#e6ebf1;border:1px solid #3c4753;border-radius:5px;padding:5px;font:inherit;font-size:12px}
#pop textarea{height:56px;resize:vertical;margin-top:6px}
#pop .row{display:flex;gap:6px;margin-top:8px}
#pop button{flex:1;padding:6px;border-radius:5px;border:0;cursor:pointer;font:inherit;font-weight:600}
#pop .ok{background:#3a6ea5;color:#fff}
#pop .del{background:#5a2b2b;color:#ffd9d9}
#pop .cx{background:#2b323b;color:#c3ccd6}
#list{width:290px;flex:0 0 auto;overflow:auto;background:#161b21;border-left:1px solid #2b323b;padding:8px}
#list h3{margin:0 0 8px;font-size:12px;color:#8d97a3;font-weight:600}
.an{background:#1e252d;border:1px solid #2b323b;border-radius:6px;padding:7px 8px;margin-bottom:6px;font-size:12px}
.an b{color:#ff8f8f}
.an .w{color:#9fb0c2;font-size:11px;margin-top:2px;word-break:break-word;white-space:pre-wrap}
.an .m{color:#6d7784;font-size:10px;margin-top:3px}
.an button{float:right;background:transparent;border:0;color:#7d8794;cursor:pointer;font-size:14px;line-height:1;padding:0 2px}
.an button:hover{color:#ff8f8f}
#tools{display:flex;gap:8px;align-items:center;padding:6px 10px;background:#161b21;border-top:1px solid #2b323b;flex:0 0 auto;font-size:12px}
#tools button{background:#2b3d55;color:#dbe6f2;border:0;padding:5px 12px;border-radius:5px;cursor:pointer;font:inherit}
#tools button:hover{background:#3a5578}
#tools .st{color:#7d8794}
</style></head><body>
<header><b>缺陷标注台</b>
  <span class="hint">在图上<b style="color:#ff8f8f">按住拖动画框</b> → 选类型 + 写一句 → 保存。左右两栏都能画。</span>
  <span id="stat" class="hint"></span>
  <a href="/defects" style="margin-left:auto;color:#9fd0ff;text-decoration:none;
     border:1px solid #3c4753;border-radius:5px;padding:3px 10px;font-weight:600">机器缺陷总表 →</a>
</header>
<main>
  <div id="side"></div>
  <div id="mid">
    <div id="floors"></div>
    <div id="stage"></div>
    <div id="tools">
      <button onclick="clearAll()">清空当前层标注</button>
      <button onclick="window.open('/dump','_blank')">看全部标注 JSON</button>
      <span class="st" id="tip"></span>
    </div>
  </div>
  <div id="list"><h3>本层标注</h3><div id="items"></div></div>
</main>
<div id="pop">
  <div class="ttl" id="popTtl">标注</div>
  <select id="popType"></select>
  <textarea id="popNote" placeholder="用一句话说：这里应该是什么 / 实际错成什么"></textarea>
  <div class="row">
    <button class="ok" onclick="savePop()">保存</button>
    <button class="cx" onclick="closePop()">取消</button>
  </div>
</div>
<script>
var MAN=[],CUR=null,CURF=null,PENDING=null,EDIT=null,ANN=[];

function api(u,o){return fetch(u,o).then(function(r){return r.json()});}

function boot(){
  document.addEventListener('mousemove',onMove);
  document.addEventListener('mouseup',onUp);
  api('/api/manifest').then(function(m){
    MAN=m.buildings; ANN=m.annotations||[];
    var h='';
    for(var i=0;i<MAN.length;i++){
      var b=MAN[i],n=countOf(b.name);
      h+='<div class="bld" data-n="'+b.name+'" onclick="pick(\''+b.name+'\')"><span>'+b.name+
         '</span><span class="t">'+esc(b.title)+'</span><span class="n">'+(n||'')+'</span></div>';
    }
    document.getElementById('side').innerHTML=h;
    var t=''; for(var i=0;i<TPS.length;i++) t+='<option value="'+TPS[i][0]+'">'+TPS[i][1]+'</option>';
    document.getElementById('popType').innerHTML=t;
    var withF=null;
    for(var i=0;i<MAN.length;i++) if(MAN[i].floors.length){withF=MAN[i];break;}
    if(withF) pick(withF.name);
    render();
  });
}
function countOf(n){var c=0;for(var i=0;i<ANN.length;i++) if(ANN[i].building===n)c++;return c;}

function pick(n){
  CUR=n;
  var els=document.querySelectorAll('.bld');
  for(var i=0;i<els.length;i++) els[i].classList.toggle('on',els[i].getAttribute('data-n')===n);
  var b=null; for(var i=0;i<MAN.length;i++) if(MAN[i].name===n) b=MAN[i];
  var h='';
  for(var i=0;i<b.floors.length;i++){
    var f=b.floors[i];
    if(!f.recog) continue;
    h+='<div class="fb" data-f="'+f.f+'" onclick="pickF(\''+f.f+'\')">'+(parseInt(f.f,10)+1)+'层</div>';
  }
  document.getElementById('floors').innerHTML=h;
  CURF=null;
  if(b.floors.length){ for(var i=0;i<b.floors.length;i++){ if(b.floors[i].recog){ pickF(b.floors[i].f); break; } } }
  render();
}

function pickF(f){
  CURF=f;
  var els=document.querySelectorAll('.fb');
  for(var i=0;i<els.length;i++) els[i].classList.toggle('on',els[i].getAttribute('data-f')===f);
  var st=document.getElementById('stage');
  // 服务端只认 <楼>/<src|recog>/floor<N>.png 这个形状，文件名不能省 floor 前缀
  var fn='floor'+f+'.png';
  var uSrc='/img/'+CUR+'/src/'+fn, uRec='/img/'+CUR+'/recog/'+fn;
  st.innerHTML='<div class="pair">'+
    '<div class="side"><span class="tag">A 源图纸（真值）<b class="zz">100%</b></span>'+
      '<div class="vp"><div class="wrap"><img src="'+uSrc+'">'+
        '<div class="layer" data-k="src"></div></div></div></div>'+
    '<div class="side"><span class="tag">B 识别结果<b class="zz">100%</b></span>'+
      '<div class="vp"><div class="wrap"><img src="'+uRec+'">'+
        '<div class="layer" data-k="recog"></div></div></div></div>'+
  '</div>';
  var ls=st.querySelectorAll('.layer');
  for(var i=0;i<ls.length;i++) wire(ls[i]);
  render();
}

// 在图上拖动 = 画框。
// 拖动状态与 mousemove/mouseup 都放在**模块级、只注册一次** —— 早先写在 wire() 里，
// 每切一层就多挂一对 document 监听，拖一次会画出 N 个框。
var DRAG=null;
function wire(el){
  el.addEventListener('mousedown',function(e){
    e.preventDefault();
    var r=el.getBoundingClientRect();
    var box=document.createElement('div'); box.className='bx';
    el.appendChild(box); closePop();
    DRAG={el:el,box:box,x:e.clientX-r.left,y:e.clientY-r.top,w:r.width,h:r.height};
  });
  var vp=el.closest('.vp');
  if(vp){
    // passive:false —— 必须能 preventDefault，否则滚轮会连带滚整页
    vp.addEventListener('wheel',onWheel,{passive:false});
    vp.addEventListener('dblclick',function(){ setZoom(vp,1,null,null); });
  }
}

// 滚轮缩放：以**指针所在点**为锚，缩完该点在屏幕上不动。
// 框存的是百分比，图层随 .wrap 一起缩放，所以缩放后框自动对齐，无需换算。
var ZMIN=0.5, ZMAX=8, ZSTEP=1.15;
function setZoom(vp,z,ax,ay){
  var wrap=vp.querySelector('.wrap');
  if(!wrap) return;
  z=Math.max(ZMIN,Math.min(ZMAX,z));
  var vr=vp.getBoundingClientRect(), wr=wrap.getBoundingClientRect();
  var cw=wr.width,ch=wr.height;
  // 锚点处的「内容百分比」——缩放前后这个百分比要停在同一个屏幕位置
  var fx=cw?(vp.scrollLeft+(ax==null?vr.width/2:ax))/cw:0;
  var fy=ch?(vp.scrollTop +(ay==null?vr.height/2:ay))/ch:0;
  wrap.style.width=(z*100)+'%';
  var wr2=wrap.getBoundingClientRect(), cw2=wr2.width, ch2=wr2.height;
  var mx=(ax==null?vr.width/2:ax), my=(ay==null?vr.height/2:ay);
  vp.scrollLeft=fx*cw2-mx;
  vp.scrollTop =fy*ch2-my;
  wrap.setAttribute('data-z',z);
  var zz=vp.parentNode.querySelector('.tag .zz');
  if(zz) zz.textContent=Math.round(z*100)+'%';
}
function onWheel(e){
  e.preventDefault();
  // 拖框过程中不许缩放：起点 d.x/d.y 是按按下那一刻的图层尺寸算的，
  // 中途缩放会让起点与当前图层对不上，画出来的框会跳。
  if(DRAG) return;
  var vp=e.currentTarget, r=vp.getBoundingClientRect();
  var wrap=vp.querySelector('.wrap');
  var z=parseFloat(wrap.getAttribute('data-z'))||1;
  setZoom(vp, e.deltaY<0 ? z*ZSTEP : z/ZSTEP, e.clientX-r.left, e.clientY-r.top);
}
// 框一律用百分比定位，**草稿也不例外**。用 px 的话，框在图上不会随
// .wrap 缩放而移动 —— 滚轮一放大，框就留在原地跑偏（实测 2.66 倍下能偏出半个屏）。
function place(el,n){
  el.style.left=(n.x0*100)+'%'; el.style.top=(n.y0*100)+'%';
  el.style.width=((n.x1-n.x0)*100)+'%'; el.style.height=((n.y1-n.y0)*100)+'%';
}
function onMove(e){
  var d=DRAG; if(!d) return;
  var r=d.el.getBoundingClientRect();
  var x=e.clientX-r.left, y=e.clientY-r.top;
  var x0=Math.max(0,Math.min(d.x,x)), x1=Math.min(d.w,Math.max(d.x,x));
  var y0=Math.max(0,Math.min(d.y,y)), y1=Math.min(d.h,Math.max(d.y,y));
  d.n={x0:x0/d.w,y0:y0/d.h,x1:x1/d.w,y1:y1/d.h};
  place(d.box,d.n);
}
function onUp(){
  var d=DRAG; if(!d) return;
  DRAG=null;
  var n=d.n, w=n?(n.x1-n.x0):0, h=n?(n.y1-n.y0):0;
  // 太小的框多半是误点，不是标注意图 —— 丢掉
  if(!n||w<0.004||h<0.004){
    if(d.box.parentNode) d.box.parentNode.removeChild(d.box);
    return;
  }
  PENDING={building:CUR,f:CURF,kind:d.el.getAttribute('data-k'),box:n,_node:d.box};
  openPop(null);
}

function openPop(a){
  EDIT=a||null;
  var p=document.getElementById('pop');
  document.getElementById('popTtl').textContent = a ? '改这条标注' : '新标注';
  document.getElementById('popType').value = a?a.type:'wall_missing';
  document.getElementById('popNote').value = a?a.note:'';
  var x = PENDING && PENDING._node ? PENDING._node.getBoundingClientRect() : {right:400,bottom:300};
  p.style.display='block';
  p.style.left=Math.min(window.innerWidth-305, Math.max(8,x.right-40))+'px';
  p.style.top=Math.min(window.innerHeight-230, Math.max(8,x.bottom+8))+'px';
  document.getElementById('popNote').focus();
}
function closePop(){
  document.getElementById('pop').style.display='none';
  // 没保存就关掉的草稿框必须连节点一起删。否则它会留在图上，且因为不带 .done
  // 而躲过 render() 的清理 —— 变成一个「看着像标注、其实库里没有」的幽灵框。
  // 保存路径不受影响：savePop 在调这里之前已把 _node 置空。
  if(PENDING&&PENDING._node&&PENDING._node.parentNode)
    PENDING._node.parentNode.removeChild(PENDING._node);
  PENDING=null;EDIT=null;
}

function savePop(){
  var t=document.getElementById('popType').value;
  var n=document.getElementById('popNote').value.trim();
  var rec;
  if(EDIT){
    rec=EDIT; rec.type=t; rec.note=n;
  }else{
    if(!PENDING) return;
    rec={building:PENDING.building,f:PENDING.f,kind:PENDING.kind,type:t,note:n,
         box:PENDING.box,ts:new Date().toISOString().slice(0,19)};
    if(PENDING._node){PENDING._node.classList.add('done');PENDING._node=null;}
  }
  api('/api/annotations',{method:'POST',headers:{'Content-Type':'application/json'},
                          body:JSON.stringify({item:rec})}).then(function(r){
    ANN=r.items; closePop(); render(); refreshCounts();
  });
}

function del(ts,b,f){
  api('/api/annotations/delete',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ts:ts,building:b,f:f})}).then(function(r){ANN=r.items;render();refreshCounts();});
}
function clearAll(){
  if(!CUR||CURF===null) return;
  if(!confirm('删掉 '+CUR+' '+(parseInt(CURF,10)+1)+'层 的全部标注？')) return;
  api('/api/annotations/delete',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({building:CUR,f:CURF})}).then(function(r){ANN=r.items;render();refreshCounts();pickF(CURF);});
}
function refreshCounts(){
  var els=document.querySelectorAll('.bld');
  for(var i=0;i<els.length;i++){
    var n=els[i].getAttribute('data-n');
    els[i].querySelector('.n').textContent=countOf(n)||'';
  }
  document.getElementById('stat').textContent='共 '+ANN.length+' 条标注';
}

var TPS=[];
function render(){
  var box=document.getElementById('items');
  var tps={}; for(var i=0;i<TPS.length;i++) tps[TPS[i][0]]=TPS[i][1];
  var out='';
  for(var i=0;i<ANN.length;i++){
    var a=ANN[i];
    if(a.building!==CUR||a.f!==CURF) continue;
    out+='<div class="an"><button onclick="del(\''+a.ts+'\',\''+a.building+'\',\''+a.f+'\')">&times;</button>'+
         '<b>'+esc(tps[a.type]||a.type)+'</b>'+
         '<div class="w">'+esc(a.note||'（没写备注）')+'</div>'+
         '<div class="m">'+(a.kind==='src'?'标在源图':'标在识别图')+' · '+a.ts+'</div></div>';
  }
  box.innerHTML=out||'<div style="color:#6d7784;font-size:12px">这一层还没有标注</div>';
  // 把已存的框画回图上
  var st=document.getElementById('stage');
  if(!st.querySelector('.pair')) return;
  var layers=st.querySelectorAll('.layer');
  for(var i=0;i<layers.length;i++){
    var k=layers[i].getAttribute('data-k');
    var keep=layers[i].querySelectorAll('.bx.done');
    for(var j=0;j<keep.length;j++) keep[j].parentNode.removeChild(keep[j]);
    for(var j=0;j<ANN.length;j++){
      var a=ANN[j];
      if(a.building!==CUR||a.f!==CURF||a.kind!==k) continue;
      var d=document.createElement('div'); d.className='bx done';
      place(d,a.box);   // 百分比定位：图会随窗口/滚轮缩放，像素框会跑偏
      layers[i].appendChild(d);
    }
  }
}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}

// 类型表从服务端取，避免两边写两份对不上
fetch('/api/types').then(function(r){return r.json()}).then(function(t){TPS=t;boot();});
</script></body></html>"""


DEF_PAGE = r"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>机器缺陷总表</title><style>
*{box-sizing:border-box}
body{font:13px/1.5 system-ui,"Microsoft YaHei",sans-serif;background:#11151a;color:#dfe4ea;margin:0;padding:14px}
a{color:#9fd0ff}
h1{font-size:16px;margin:0 0 4px}
h2{font-size:13px;margin:18px 0 8px;color:#a9b6c4;border-left:3px solid #3a6ea5;padding-left:8px}
.sub{color:#7d8794;font-size:12px;margin-bottom:10px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border:1px solid #2b323b;padding:4px 8px;text-align:left;vertical-align:top}
th{background:#1a1f26;color:#9fb0c2;position:sticky;top:0;z-index:2}
tr.r:hover{background:#1b2129}
.pill{display:inline-block;padding:0 6px;border-radius:9px;font:600 11px/1.6 system-ui}
.E{background:#5a2020;color:#ffc9c9}.W{background:#4a3a12;color:#ffe0a3}
.b{color:#9fd0ff;cursor:pointer;text-decoration:underline}
.msg{color:#b9c4d0;max-width:640px}
.shots{margin-top:12px;display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:10px}
.shot{background:#fff;border-radius:6px;padding:4px}
.shot img{width:100%;display:block;border-radius:4px}
.shot .cap{color:#e6ebf1;background:#1a1f26;font:600 11px/1.8 system-ui;padding:1px 7px;border-radius:4px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}
.bar input,.bar select{background:#141a20;color:#e6ebf1;border:1px solid #3c4753;border-radius:5px;padding:4px 7px;font:inherit;font-size:12px}
.bar label{color:#8d97a3;font-size:12px}
</style></head><body>
<h1>机器缺陷总表 <span class="sub" style="font-weight:400">scan_defects.py 只读产出</span></h1>
<div class="sub">这些是<b>程序按判据算出来的</b>，与你手画的标注互不覆盖：标注在
  <a href="/">缺陷标注台</a>，机器结论在 <code>_qa/defects.json</code>。
  对照图是世界坐标里直出的（不含标定误差），点楼层名看大图。</div>
<div class="bar">
  <label>楼 <select id="fb"><option value="">全部</option></select></label>
  <label>级别 <select id="sv"><option value="">全部</option><option>ERROR</option><option>WARN</option></select></label>
  <label>码 <select id="cd"><option value="">全部</option></select></label>
  <label><input id="q" placeholder="搜房号 / 关键字" size="22"></label>
  <span id="cnt" class="sub"></span>
</div>
<table><thead><tr><th>楼</th><th>层</th><th>码</th><th>级别</th><th>说明</th></tr></thead>
<tbody id="tb"></tbody></table>
<h2>对照图</h2>
<div class="shots" id="shots"></div>
<script>
var RECS=[],SHOTS=[],B=[],S=[],C=[];
function q(s){return document.getElementById(s)}
function esc(t){return String(t==null?'':t).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function load(){
  fetch('/api/defects').then(function(r){return r.json()}).then(function(j){
    RECS=j.records||[];SHOTS=j.shots||[];
    B=[];C=[];var seen={};
    RECS.forEach(function(r){ if(B.indexOf(r.building)<0)B.push(r.building);
      if(!seen[r.code]){seen[r.code]=1;C.push(r.code)} });
    B.sort();C.sort();
    C.sort(function(a,b){return (a[0]==='D'?0:1)-(b[0]==='D'?0:1)||a.localeCompare(b)});
    q('fb').innerHTML='<option value="">全部</option>'+B.map(function(x){return '<option>'+x+'</option>'}).join('');
    q('cd').innerHTML='<option value="">全部</option>'+C.map(function(x){return '<option>'+x+'</option>'}).join('');
    q('shots').innerHTML=SHOTS.map(function(f){
      var n=f.replace('.png','');var m=n.match(/^(.*)_F(\d+)$/);
      return '<div class="shot"><img loading="lazy" src="/shots/'+encodeURIComponent(f)+'">'+
        '<div class="cap">'+esc(m?m[1]+' 第'+m[2]+'层':n)+'</div></div>'}).join('');
    render();
  });
}
function render(){
  var b=q('fb').value,s=q('sv').value,c=q('cd').value,t=q('q').value.trim();
  var rows=RECS.filter(function(r){
    if(b&&r.building!==b)return false; if(s&&r.sev!==s)return false;
    if(c&&r.code!==c)return false;
    if(t&&JSON.stringify(r).indexOf(t)<0)return false; return true});
  q('cnt').textContent='显示 '+rows.length+' / '+RECS.length+' 条';
  q('tb').innerHTML=rows.slice(0,600).map(function(r){
    var f=r.floor==null?'<span class="sub">全楼</span>':'<span class="b" data-b="'+esc(r.building)+'" data-f="'+r.floor+'">F'+r.floor+'</span>';
    return '<tr class="r"><td>'+esc(r.building)+'</td><td>'+f+'</td><td>'+esc(r.code)+'</td>'+
      '<td><span class="pill '+(r.sev==='ERROR'?'E':'W')+'">'+esc(r.sev)+'</span></td>'+
      '<td class="msg">'+esc(r.msg)+'</td></tr>'}).join('');
  Array.prototype.forEach.call(document.querySelectorAll('.b'),function(el){
    el.onclick=function(){
      var f=el.dataset.b+'_F'+el.dataset.f+'.png';
      var img=document.querySelector('.shots img[src*="'+f+'"]');
      if(img){img.scrollIntoView({block:'center'});img.style.outline='3px solid #ff5c5c';
        setTimeout(function(){img.style.outline=''},2500)}
      else{var n=document.querySelector('.shot .cap');alert('该层没有对照图（无 ERROR 命中或未跑 --shots）')}
    };
  });
}
['fb','sv','cd'].forEach(function(i){q(i).onchange=render});
q('q').oninput=render;
load();
</script></body></html>
"""


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        pass                                   # 静音，别刷屏

    def _send(self, code, body, ctype, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 默认 no-store：/img/ 是磁盘上的 PNG，楼层重渲后浏览器可能拿启发式缓存复用旧图
        # （2026-09-12 用户就撞上了这个 —— 8150 显示的是三天前的识别结果）；
        # HTML 也是模块级常量，重启后同样不该被缓存挡住。调用方仍可用 extra 覆盖。
        self.send_header("Cache-Control", "no-store, must-revalidate")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if p == "/api/types":
            return self._json(TYPES)
        if p == "/api/manifest":
            return self._json({"buildings": building_list(), "annotations": load_ann()})
        if p == "/dump":
            return self._send(200, json.dumps(load_ann(), ensure_ascii=False, indent=2),
                              "application/json; charset=utf-8")
        # ---- 机器缺陷（scan_defects.py 的产物），**只读**，与人工标注互不覆盖 ----
        if p == "/defects":
            return self._send(200, DEF_PAGE, "text/html; charset=utf-8")
        if p == "/api/defects":
            recs, shots = [], []
            fp = os.path.join(QA_DIR, "defects.json")
            if os.path.exists(fp):
                try:
                    with open(fp, encoding="utf-8") as fh:
                        recs = [r for r in json.load(fh) if r.get("sev") != "INFO"]
                except Exception:                                    # noqa: BLE001
                    recs = []
            if os.path.isdir(SHOT_DIR):
                shots = sorted(x for x in os.listdir(SHOT_DIR) if x.endswith(".png"))
            return self._json({"records": recs, "shots": shots,
                               "generated": recs and "见 _qa/defect_summary.md" or "尚未扫描"})
        if p.startswith("/shots/"):
            fn = p[7:]
            # 防目录穿越：只允许 <楼>_F<层>.png 这一种形状
            if "/" in fn or "\\" in fn or ".." in fn or not fn.endswith(".png"):
                return self._send(404, "bad name", "text/plain")
            fp = os.path.join(SHOT_DIR, fn)
            if not os.path.exists(fp):
                return self._send(404, "missing", "text/plain")
            with open(fp, "rb") as f:
                return self._send(200, f.read(), "image/png")
        if p.startswith("/img/"):
            parts = p[5:].split("/")
            if len(parts) != 3:
                return self._send(404, "bad path", "text/plain")
            name, kind, fn = parts
            sub = "dxf_plan" if kind == "src" else "dxf_plan_recog"
            if not (fn.endswith(".png") and fn.startswith("floor")):
                return self._send(404, "bad name", "text/plain")
            # 防目录穿越：只允许 楼名/floorN.png 这种形状
            if "/" in name or "\\" in name or ".." in name or ".." in fn:
                return self._send(404, "bad name", "text/plain")
            fp = os.path.join(ROOT, "data", "buildings", name, sub, fn)
            if not os.path.exists(fp):
                return self._send(404, "missing", "text/plain")
            with open(fp, "rb") as f:
                return self._send(200, f.read(), "image/png")
        return self._send(404, "not found", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:                                        # noqa: BLE001
            return self._json({"error": "bad json"}, 400)
        p = self.path.split("?")[0]
        items = load_ann()

        if p == "/api/annotations":
            it = body.get("item") or {}
            if not it.get("building") or "box" not in it:
                return self._json({"error": "缺 building/box"}, 400)
            it.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
            same = [i for i in items if i.get("ts") == it["ts"]
                    and i.get("building") == it["building"] and i.get("f") == it.get("f")]
            if same:
                same[0].update(it)
            else:
                items.append(it)
            save_ann(items)
            print("  + %s f%s %s  %s" % (it["building"], it.get("f"), it.get("type"),
                                         (it.get("note") or "")[:40]), flush=True)
            return self._json({"items": items})

        if p == "/api/annotations/delete":
            ts, b, f = body.get("ts"), body.get("building"), body.get("f")
            if ts:
                items = [i for i in items
                         if not (i.get("ts") == ts and i.get("building") == b and i.get("f") == f)]
            else:
                items = [i for i in items
                         if not (i.get("building") == b and i.get("f") == f)]
            save_ann(items)
            return self._json({"items": items})

        return self._json({"error": "not found"}, 404)


def main():
    if "--dump" in sys.argv:
        for a in load_ann():
            print("%-6s f%-3s %-14s %-22s %s" % (a.get("building"), a.get("f"),
                                                 a.get("type"), (a.get("note") or "")[:22],
                                                 a.get("ts")))
        print("共 %d 条，存于 %s" % (len(load_ann()), STORE))
        return

    srv = ThreadingHTTPServer((HOST, PORT), H)
    print("缺陷标注台已启动 -> http://%s:%d/" % (HOST, PORT))
    print("标注存到: %s" % STORE)
    print("读标注（不开浏览器）: python annotate_defects.py --dump")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。标注在 %s" % STORE)


if __name__ == "__main__":
    main()
