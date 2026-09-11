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
    """列出有对照图的楼。判据与 run_batch 一致：data/buildings 下有 profile.json。"""
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
.side{position:relative;background:#fff;border-radius:5px;overflow:hidden;line-height:0}
.side .tag{position:absolute;top:6px;left:6px;z-index:3;background:rgba(20,24,30,.86);color:#fff;font:600 11px/1.6 system-ui;padding:2px 8px;border-radius:4px;line-height:1.6}
.side img{width:100%;display:block;user-select:none;-webkit-user-drag:none}
.side .layer{position:absolute;inset:0;cursor:crosshair}
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
  <span id="stat" class="hint"></span></header>
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
    '<div class="side"><span class="tag">A 源图纸（真值）</span>'+
      '<img src="'+uSrc+'"><div class="layer" data-k="src"></div></div>'+
    '<div class="side"><span class="tag">B 识别结果</span>'+
      '<img src="'+uRec+'"><div class="layer" data-k="recog"></div></div>'+
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
}
function onMove(e){
  var d=DRAG; if(!d) return;
  var r=d.el.getBoundingClientRect();
  var x=e.clientX-r.left, y=e.clientY-r.top;
  var x0=Math.max(0,Math.min(d.x,x)), x1=Math.min(d.w,Math.max(d.x,x));
  var y0=Math.max(0,Math.min(d.y,y)), y1=Math.min(d.h,Math.max(d.y,y));
  d.box.style.left=x0+'px'; d.box.style.top=y0+'px';
  d.box.style.width=Math.max(0,x1-x0)+'px'; d.box.style.height=Math.max(0,y1-y0)+'px';
  d.n={x0:x0/d.w,y0:y0/d.h,x1:x1/d.w,y1:y1/d.h};
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
function closePop(){document.getElementById('pop').style.display='none';PENDING=null;EDIT=null;}

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
      // 用百分比定位：图会随窗口缩放，像素框会跑偏
      d.style.left=(a.box.x0*100)+'%'; d.style.top=(a.box.y0*100)+'%';
      d.style.width=((a.box.x1-a.box.x0)*100)+'%'; d.style.height=((a.box.y1-a.box.y0)*100)+'%';
      layers[i].appendChild(d);
    }
  }
}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}

// 类型表从服务端取，避免两边写两份对不上
fetch('/api/types').then(function(r){return r.json()}).then(function(t){TPS=t;boot();});
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        pass                                   # 静音，别刷屏

    def _send(self, code, body, ctype, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
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
