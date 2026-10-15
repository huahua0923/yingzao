# -*- coding: utf-8 -*-
"""把三维白模渲染成图（Blender 无头 · Workbench 引擎，不需要 GPU）。
出：05_build/c006_iso.png（轴测）· c006_front.png（正立面）· c006_top.png（俯视）。
用法：python rebuild/tools/render3d.py
      python rebuild/tools/render3d.py --obj rebuild/06_su/c006_su.obj --out rebuild/06_su

特写（构件库对照页用，2026-10-15 加）：
      python rebuild/tools/render3d.py --obj rebuild/06_su/c006_su.obj --out rebuild/06_su \
             --only door --box 76600,53800,0,79600,56800,4200 --tag door --figure
      · `--only <串>`  只留节点名含该串的件（与上色表同一套名字）
      · `--box  x0,y0,z0,x1,y1,z1`  只留与该盒相交的件，相机也框到该盒 —— **源图 mm 坐标**，
        内部 /1000 换 Blender 米；给错窗口的表现是「出图全空」而不是报错，所以每趟都印
        `BOX keep/del` 与 `FRAME ctr=… size=…` 供核对（铁律 199：别让「没框到」与「本来就没有」同形）。
      · `--tag <名>`  输出前缀变 `closeup_<名>_`，**不覆盖**正式件那三张 `c006_{iso,front,top}.png`。

★ 2026-10-13：加 `--obj/--out` 是为了让**正式件（SU 出的）和参照件走同一把尺子**。
  绝不能只因为「SU 自己导出的」就另写一个渲染器绕开这里的朝向自检 ——
  SU 的 OBJ 实测是 **Y 朝上**（`# File units = millimeters`，高度落在 Y），
  而下面的自检要的正是「高度必须是三轴最小」；绕开它，那三张图会**整体对调还看着挺像**。
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "05_build")
GLB = os.path.join(OUT, "c006_white.glb")
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

BPY = r'''
import bpy, mathutils, sys
SRC, OUT, PREFIX = r"{src}", r"{out}", r"{prefix}"
bpy.ops.wm.read_factory_settings(use_empty=True)
if SRC.lower().endswith(".obj"):
    # ★ SU 的 OBJ 是 Y 朝上；Blender 的 OBJ 导入器默认按 Y-up 收进来并转成 Z-up。
    # ★★ 必须 use_split_groups=True：SU 只写 `g`（不写 `o`），实测不拆就是 1 个对象
    #    （OBJS n=1）⇒ 下面的按类上色表全失效、整件一个灰。拆开后组名即层名。
    bpy.ops.wm.obj_import(filepath=SRC, use_split_groups=True)
else:
    bpy.ops.import_scene.gltf(filepath=SRC)
_ms=[o for o in bpy.data.objects if o.type=='MESH']
print("OBJS n=%d names=%s" % (len(_ms), [o.name for o in _ms][:6]))
# ★ 按**构件**上色：白模一色时「竖井/台阶屋面/女儿墙」在图上根本认不出来，
#   用户看图时只能看到一团灰。颜色表与 build3d 的节点名一一对应。
TAGCOL={{"wall":(0.62,0.62,0.64,1),"col":(0.20,0.35,0.75,1),"lift":(0.90,0.10,0.10,1),
        "slab":(0.86,0.86,0.86,1),"door":(0.95,0.55,0.05,1),"stair":(0.98,0.90,0.15,1),
        "roof_step7":(0.05,0.75,0.85,1),"parapet":(0.10,0.70,0.20,1),
        "roof_stair":(0.65,0.15,0.80,1),"roof":(0.30,0.30,0.32,1)}}
def _ramp(t):
    st=[(0.11,0.25,0.33),(0.55,0.60,0.63),(0.87,0.76,0.52)]
    t=min(max(float(t),0.0),1.0); seg=t*(len(st)-1); i=min(int(seg),len(st)-2); f=seg-i
    return tuple(st[i][k]+(st[i+1][k]-st[i][k])*f for k in range(3))+(1,)
_mesh=[o for o in bpy.data.objects if o.type=='MESH']
# ★↓ 花括号必须写成双的 —— 这一整块是 str.format() 的模板，单个 `{{` 会被当占位符吃掉
_idx={{o.name:i for i,o in enumerate(sorted(_mesh,key=lambda o:o.name))}}
# ★ 兜底上色：名字一个都不沾构件表时（交付包是**按层**命名的 `floor0..floor10`/`B1`），
#   全场一个灰 ⇒ 12 层糊成一坨、看不出层。此时按**名字排序后的下标**走冷暖渐变。
#   ★ 只对「命中不了任何构件键」的对象兜底 ⇒ 参照件/正式件（名字能命中）颜色一字不变。
_ramped=0
for o in _mesh:
    nm=o.name.lower(); hit=None
    for k in ("roof_step7","roof_stair","parapet","lift","slab","door","stair","col","wall","roof"):
        if k in nm: hit=k; break
    if hit is not None:
        o.color = TAGCOL.get(hit,(0.5,0.5,0.5,1))
    else:
        o.color = _ramp(_idx[o.name]/max(1,len(_mesh)-1)); _ramped+=1
print("RAMPED %d/%d" % (_ramped, len(_mesh)))
mng=[1e9]*3; mxg=[-1e9]*3
for o in bpy.data.objects:
    if o.type=='MESH':
        for c in o.bound_box:
            w=o.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                mng[i]=min(mng[i],w[i]); mxg[i]=max(mxg[i],w[i])
ext=[mxg[i]-mng[i] for i in range(3)]
# ★★ 朝向自检：件导进 Blender 后必须 **Z 朝上**（Blender 惯例）。glTF 文件本身是 Y 朝上，
#   Blender 导入时替我们转过来；**若出件又写成 Z 朝上，这个转换会把它转到 −Y 上**，
#   于是下面三张图全部对调（「正立面」画出的是俯视）却看着还挺像 —— 2026-10-13 真发生过。
#   高度（50.5 m）在三个尺寸里最小（平面 129×84 m）⇒ 用「Z 必须是三轴最小」当场拦下。
#   ★ 自检一律拿**整件**做（就是上面这段）：特写筛只改取景、不改朝向 ——
#     把筛写在自检前头，等于对「筛剩下的那一小块」自检，那道闸当场作废。
if not (ext[2] < ext[0] and ext[2] < ext[1]):
    print("ORIENT_FAIL", [round(v,2) for v in ext])
    sys.exit(2)
print("ORIENT_OK", [round(v,2) for v in ext])
# ---- 特写（构件库对照页用）：--only 按节点名留件，--box 只留与该盒相交的件 ----
_only = r"{only}"
if _only:
    # ★ 逗号清单，例如 `--only wall,door,slab`：一个词留不住「墙＋门」这个主角组合，
    #   而只要门不要墙，就看不见「门上面那个洞」本身。
    _keys=[k.strip().lower() for k in _only.split(",") if k.strip()]
    _rm=[o for o in list(bpy.data.objects) if o.type=='MESH'
         and not any(k in o.name.lower() for k in _keys)]
    for o in _rm:
        bpy.data.objects.remove(o, do_unlink=True)
    print("ONLY keys=%s keep %d del %d" % (_keys,
          len([o for o in bpy.data.objects if o.type=='MESH']), len(_rm)))
_box = {box}
if _box:
    # ★ --box 一律按**源图 mm** 给；件自己是毫米还是米，由**实测尺寸**推，不写死：
    #   实测 SU 的 OBJ 进来就是 mm（ext=[129300, 84000, 50500]），而 GLB 那条路是米。
    #   写死一边，另一条路就会「出图全空」，且与「这里本来就没东西」同形（铁律 199）。
    _k = 1.0 if max(ext) > 1000.0 else 0.001
    _box = tuple(v * _k for v in _box)
    print("UNIT k=%.4f ext=%s" % (_k, [round(v,1) for v in ext]))
    _rm=[]
    for o in [o for o in bpy.data.objects if o.type=='MESH']:
        _bb=[o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
        if (max(p[0] for p in _bb) < _box[0] or min(p[0] for p in _bb) > _box[3]
                or max(p[1] for p in _bb) < _box[1] or min(p[1] for p in _bb) > _box[4]
                or max(p[2] for p in _bb) < _box[2] or min(p[2] for p in _bb) > _box[5]):
            _rm.append(o)
    for o in _rm:
        bpy.data.objects.remove(o, do_unlink=True)
    print("BOX keep %d del %d" % (len([o for o in bpy.data.objects if o.type=='MESH']), len(_rm)))
mn=[1e9]*3; mx=[-1e9]*3
for o in bpy.data.objects:
    if o.type=='MESH':
        for c in o.bound_box:
            w=o.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                mn[i]=min(mn[i],w[i]); mx[i]=max(mx[i],w[i])
if _box:
    ctr=mathutils.Vector([(_box[0]+_box[3])/2.0,(_box[1]+_box[4])/2.0,(_box[2]+_box[5])/2.0])
    size=max(_box[3]-_box[0],_box[4]-_box[1],_box[5]-_box[2])
else:
    ctr=mathutils.Vector([(mn[i]+mx[i])/2 for i in range(3)])
    size=max(mx[i]-mn[i] for i in range(3))
print("FRAME ctr=%s size=%.2f" % ([round(v,2) for v in ctr], size))
cd=bpy.data.cameras.new('c'); cam=bpy.data.objects.new('c',cd)
bpy.context.scene.collection.objects.link(cam); bpy.context.scene.camera=cam
cd.type='ORTHO'; cd.ortho_scale=size*1.15; cd.clip_end=size*10
sc=bpy.context.scene
sc.render.engine='BLENDER_WORKBENCH'
sc.display.shading.light='STUDIO'; sc.display.shading.color_type='OBJECT'
sc.display.shading.show_shadows=True
sc.render.resolution_x=1600; sc.render.resolution_y=1100
sc.render.image_settings.file_format='PNG'
views={{"iso":(0.9,-1.0,0.65),"front":(0.0,-1.0,0.0),"top":(0.0,-0.001,1.0)}}
for name,dirv in views.items():
    d=mathutils.Vector(dirv).normalized()*size*3.0
    cam.location=ctr+d
    cam.rotation_euler=(ctr-cam.location).normalized().to_track_quat('-Z','Y').to_euler()
    sc.render.filepath=OUT+"\\"+PREFIX+name+".png"
    bpy.ops.render.render(write_still=True)
    print("WROTE", sc.render.filepath)
'''


def _font(px):
    """中文字要用系统字体，PIL 的默认点阵字画不出汉字（会变一串豆腐块）。"""
    from PIL import ImageFont
    for f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(f):
            try:
                return ImageFont.truetype(f, px)
            except Exception:
                pass
    return ImageFont.load_default()


def to_figure(png, src, sha):
    """把尺子出的**透明底**图合成成品图：浅底 ＋ 落款条（数一律现算）。

    ★ 必须**显式开关**才做：正式件那三张是 RGBA、背景透明，而
      `gates/J-10.8-03_views.py` 正是靠 `alpha>8` 切前景的 —— 默认就合成，等于把那道判据废了。
    """
    from PIL import Image, ImageDraw
    im = Image.open(png).convert("RGBA")
    w, h = im.size
    # ★ 按**内容的 alpha 外接矩形**裁一刀：正立面只有 129×43.9 m，铺在 1600×1100 的画布上
    #   有一半是空地面 —— 不裁的话落款条离建筑老远，图看着像没画满。
    #   ★ 裁的是**等比例**的边，建筑本身不变形；且裁的是本函数自己合成的成品，不碰渲染件。
    bb = im.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
    if bb:
        pad = int(0.035 * max(bb[2] - bb[0], bb[3] - bb[1]))
        im = im.crop((max(0, bb[0] - pad), max(0, bb[1] - pad),
                      min(w, bb[2] + pad), min(h, bb[3] + pad)))
        w, h = im.size
    bg = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(bg)
    for y in range(h):                      # 上浅下略深的渐变：给体积感，不抢几何
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)],
               fill=(int(250 - 24 * t), int(250 - 20 * t), int(252 - 14 * t)))
    bg.paste(im, (0, 0), im)                # 用 alpha 当蒙版
    bar = 92
    cv = Image.new("RGB", (w, h + bar), (246, 246, 248))
    cv.paste(bg, (0, 0))
    dd = ImageDraw.Draw(cv)
    dd.line([(0, h), (w, h)], fill=(146, 152, 162), width=2)
    f = _font(24)
    dd.text((26, h + 10), "%s ｜ 源件 %s" % (os.path.basename(png), os.path.basename(src)),
            fill=(48, 54, 64), font=f)
    # ★ 印的必须是**这张落盘文件**的尺寸，不是合成本函数时用的内容尺寸 ——
    #   内容高 h 与落款条高 bar 是两个数，只印 h 会让读者量一次就被推翻
    #   （2026-10-14 实测：三张各差 92 = bar，落款写 1600×1014 而文件是 1600×1106）。
    #   所以取 cv.size，让读数只有一个来源（铁律 174）。
    fw, fh = cv.size
    dd.text((26, h + 44), "sha256 %s ｜ %d×%d ｜ %s ｜ Blender Workbench 正交 · 不含原始影像"
            % (sha[:16], fw, fh, time.strftime("%Y-%m-%d %H:%M")), fill=(96, 102, 112), font=f)
    cv.save(png)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    av = sys.argv[1:]
    src = av[av.index("--obj") + 1] if "--obj" in av else GLB
    # ★ 必须绝对路径：Blender 是**子进程**，相对路径不由 Python 的 cwd 决定 ——
    #   实测给 `rebuild/06_su` 时 Blender 打印 WROTE 却一张 PNG 都没落在那里。
    out = os.path.abspath(av[av.index("--out") + 1] if "--out" in av else OUT)
    # 缺省（参照件）时前缀仍是 c006_，文件名与既有产物完全一致，一个字不变
    only = av[av.index("--only") + 1] if "--only" in av else ""
    tag = av[av.index("--tag") + 1] if "--tag" in av else ""
    # ★ --box 用**源图 mm 坐标** x0,y0,z0,x1,y1,z1（与构件清单/构件库同一套读数），
    #   原样交给 Blender，由那边按**实测尺寸**决定还要不要缩 —— 实测 SU 的 OBJ 进来就是 mm，
    #   而 GLB 那条路是米；此处写死一边，另一边就会「出图全空」。
    box = None
    if "--box" in av:
        try:
            v6 = [float(x) for x in av[av.index("--box") + 1].split(",")]
        except ValueError:
            v6 = []
        if len(v6) != 6:
            print("★ --box 要 6 个数：x0,y0,z0,x1,y1,z1（mm）")
            return 4
        box = tuple(v6)
    prefix = ("closeup_%s_" % tag if tag
              else ("c006_su_" if "c006_su" in os.path.basename(src) else "c006_"))
    os.makedirs(out, exist_ok=True)
    if not os.path.exists(BLENDER):
        print("★ Blender 不在，停")
        return 4
    if not os.path.exists(src):
        print("★ 件不在：%s" % src)
        return 4
    print("SRC=%s  OUT=%s  PREFIX=%s  ONLY=%s  BOX=%s"
          % (src, out, prefix, only or "-", box or "-"))
    bp = os.path.join(out, "render.py")
    with open(bp, "w", encoding="utf-8", newline="\n") as f:
        f.write(BPY.format(src=src, out=out, prefix=prefix, only=only, box=repr(box)))
    r = subprocess.run([BLENDER, "-b", "-P", bp], capture_output=True, text=True)
    bad = None
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("ORIENT_FAIL"):
            bad = ln
        elif ln.startswith(("WROTE", "ORIENT_OK", "OBJS", "RAMPED", "ONLY", "BOX", "FRAME")):
            print(ln)
    if bad:
        print("★ %s ⇒ 件朝向不对（高度不在 Z），三张图会全部对调 ⇒ 不出图" % bad)
        return 1
    if r.returncode == 0 and "--figure" in av:
        sha = sha256_of(src)
        for name in ("iso", "front", "top"):
            to_figure(os.path.join(out, prefix + name + ".png"), src, sha)
        print("FIGURE 已合成浅底＋落款条 ×3（默认不开；正式件那三张必须保持透明底）")
    print("rc=%d" % r.returncode)
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
