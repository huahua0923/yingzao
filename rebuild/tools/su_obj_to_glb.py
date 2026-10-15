# -*- coding: utf-8 -*-
"""正式件 OBJ → GLB（**格式转换，不建几何**）：`06_su/c006_su.obj` → `06_su/c006_su.glb`。

为什么要有这一步（2026-10-14 用户裁定）：
  交付包里那件 `role=model` 原先走的是 **libs3d 逐层链**（11 层 × 3.6 m ⇒ 顶 39.72 m、
  无女儿墙 / 无顶楼楼梯房 / 无 7→8 台阶屋面），而 `manifest.json` 第 19 行却声明
  「塔楼 47.5 m …… 均按真实几何表示」—— **声明与件不符**。
  用户裁定：包内件换成 **SU 出的正式件**（三类顶部构件都在）。
  ★ 2026-10-15 用户令层高按 **3.5 m** 走 ⇒ 件顶 = 11×3.5 + 楼梯房 3.0 = **41.5 m**
    （原先 4.0 m 口径下是 47.0 m）。本文件**不写死这个数**，现读 `05_build/build.json`。

三件事**一律实测，不沿用记忆**（探针 `_scratch/probe_su_import.py` 的读数）：
  ① SU 的 OBJ 头写着 `# File units = millimeters`，但 **Blender 的导入器不认这行**
     —— 量到 EXT=[129300, 84000, 50500]，是毫米当米读 ⇒ 本脚本一律 **×0.001**。
  ② 导进来后高度落在 **Blender 的 Z**（−3500 → 41500 mm @3.5 m 口径）；glTF 要 Y 朝上 ⇒
     交给 Blender 的导出器做 Z→Y（`export_yup=True`），**不自己转顶点**。
  ③ 118861 个面里 **974 个是 n 边形**（最大 2665 顶点）。自己拿扇形三角化会把
     带洞/凹的墙面板和楼板画错 ⇒ **不自己三角化**，走 `wm.obj_import(use_split_groups=True)`
     （`render3d.py` 正在用的那把尺子），Blender 怎么切就怎么切。

节点结构（**为网页的分层面板而定**，见 demo/index.html:618 `buildLayers`）：
  顶层节点 = **层**：`floor0 … floor10`（= F1…F11，0 基）+ `B1`（地下 1 层）。
  层底下挂**类**子节点：`<层节点>__<类>`，类名取自 SU 的组名（WALL/COL/LIFT/SLAB/
  DOOR/STAIR/LINTEL/PARAPET/ROOF_STAIR/ROOF_STEP/ROOF，**十一类**）。
  ⇒ 页面按「顶层祖先」分层的那段代码**一行不用改**；类信息留在子节点名里，
     将来要按构件上色也还有口子。
     ★ 2026-10-15 更正：这串原先只写到 **9 类**（缺 `LINTEL` 门头墙 / `ROOF` 塔楼屋面板）
       —— 它只是**散文**，本文件真正的分类开关是下面那两条正则
       （`g Mesh<N> <组名> Model` 的组名解析，命不中就报错退出），
       所以散文过期**不丢件**；但它会误导读它的人以为只有 9 类（铁律 137：判据名单
       漏掉主体则永远绿）。同一批类名的**机器尺子**是 `gates/J-10.9-07_类闭合.py`，
       那边把「七处枚举口」逐处解析、并拿**真的缺过类的旧件**当正对照。

名字怎么来的：SU 导出的 `g` 行是 `g Mesh<N> <组名> Model`，而 Ruby 建组时写的是
  `"#{层名}_#{类}"`，非 ASCII 被 SU 剥掉 ⇒ 楼上是 `G_5__COL`，地下室是 `__1__WALL`
  （`地下1层` 三个汉字全没了）。**两条正则都不命中就报错退出**，不许静默丢件
  —— 静默丢一个 (层,类) 桶，症状与「本来就没有那一类构件」同形（铁律 137/158）。

两把尺子（铁律 187：基线与期望必须来自两次不同读数）：
  尺子一 = Blender 自己量的（Z 朝上、毫米）；
  尺子二 = **落盘后重新打开 GLB、直接读它自己的 JSON 块**里 POSITION 访问器的
           min/max（Y 朝上、米）。两把对不上就报错。

用法：python rebuild/tools/su_obj_to_glb.py
退出码：0 成功 · 1 判据不过 · 4 缺件（源 OBJ 或 Blender 不在）
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # D:\项目\cdut3d
SRC = os.path.join(ROOT, "06_su", "c006_su.obj")
OUT = os.path.join(ROOT, "06_su", "c006_su.glb")
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

# 期望值来自**另一条独立读数**（那一步是 build3d 自己的记账，本文件量的是 SU 导出的几何
#   ⇒ 两次读数不同源，铁律 187）：
#   平面 129.3 × 84.0 m（rebuild/构件清单.md §6，源件柱网推出，与件无关）；
#   高度**不写死** —— 从 `rebuild/05_build/build.json` 的 `basement_m` / `z_max_m` 现读。
#   ★ 2026-10-15：原先写死 `(-3500.0, 46999.996)`（= 11×4.0 + 楼梯房 3.0）。用户令层高改 3.5 m 后
#     件顶变成 41.5 m，而这两个数没跟着动 ⇒ 这一步会**报假红**（件是对的，期望值是旧的）。
#     层高这种「一个口径决定、下游好几处跟着变」的数，一律现读现算（铁律 018/103）。
EXP_PLAN_M = (129.3, 84.0)


def _exp_hi_mm():
    """(底, 顶) 毫米 —— 现读 build.json。读不到就**明确报错**，不悄悄退回常量。"""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "05_build", "build.json")
    b = json.load(open(p, encoding="utf-8"))
    return (-abs(float(b["basement_m"])) * 1000.0, float(b["z_max_m"]) * 1000.0)
MM = 0.001

BPY = r'''
import bpy, re, sys, mathutils
SRC, OUT = r"__SRC__", r"__OUT__"
MM = 0.001
RE_FLOOR = re.compile(r"G_(\d+)__([A-Z_]+)")
RE_BASE = re.compile(r"__(\d+)__([A-Z_]+)")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=SRC, use_split_groups=True)

ms = [o for o in bpy.data.objects if o.type == "MESH"]
polys_in = sum(len(o.data.polygons) for o in ms)
print("BLENDER_IN objects=%d polys=%d" % (len(ms), polys_in))

groups, unmatched = {}, []
for o in ms:
    m = RE_FLOOR.search(o.name)
    if m:
        node, cls = "floor%d" % (int(m.group(1)) - 1), m.group(2)
    else:
        m = RE_BASE.search(o.name)
        if not m:
            unmatched.append(o.name)
            continue
        node, cls = "B1", m.group(2)
    groups.setdefault((node, cls), []).append(o)

if unmatched:
    print("UNMATCHED n=%d 例=%s" % (len(unmatched), unmatched[:5]))
    sys.exit(3)

# 逐 (层,类) 合成一张网格 —— **不新增/不删顶点**，只把 SU 拆成 7130 个对象重新拼回。
# 用 from_pydata 而不是 bpy.ops.object.join()：无算子上下文依赖，且 n 边形原样保留。
def merge(objs, name):
    verts, faces = [], []
    for o in objs:
        base = len(verts)
        mw = o.matrix_world
        for v in o.data.vertices:
            co = mw @ v.co
            verts.append((co.x * MM, co.y * MM, co.z * MM))     # 毫米 -> 米，就这一处
        for p in o.data.polygons:
            faces.append(tuple(base + i for i in p.vertices))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    return me

NODES = ["B1"] + ["floor%d" % k for k in range(11)]
scene = bpy.context.scene.collection
empties = {}
for n in NODES:
    e = bpy.data.objects.new(n, None)          # 空物体 = 层节点（glTF 里就是父 node）
    scene.objects.link(e)
    empties[n] = e

polys_out = 0
for (node, cls), objs in sorted(groups.items()):
    nm = "%s__%s" % (node, cls)
    me = merge(objs, nm)
    polys_out += len(me.polygons)
    ob = bpy.data.objects.new(nm, me)
    scene.objects.link(ob)
    ob.parent = empties[node]

for o in ms:                                    # 原件退场（否则导出 7130 个节点）
    bpy.data.objects.remove(o, do_unlink=True)

print("BLENDER_GROUPS n=%d polys_in=%d polys_out=%d" % (len(groups), polys_in, polys_out))
print("BLENDER_NODES %s" % sorted(empties))
if polys_out != polys_in:
    print("POLY_LOSS in=%d out=%d" % (polys_in, polys_out))
    sys.exit(3)

mn = [1e9] * 3
mx = [-1e9] * 3
for o in bpy.data.objects:
    if o.type != "MESH":
        continue
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        for i in range(3):
            mn[i] = min(mn[i], w[i])
            mx[i] = max(mx[i], w[i])
print("BLENDER_BBOX_M min=%s max=%s" % ([round(v, 3) for v in mn], [round(v, 3) for v in mx]))

bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_yup=True, export_apply=True)
print("EXPORTED %s" % OUT)
'''


def glb_json(path):
    """直接读 GLB 的 JSON 块 —— 不借第三方库，读的就是**交付件自己**写下的数。"""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"glTF":
        raise ValueError("不是 GLB：%s" % path)
    off = 12                                     # magic(4) + version(4) + length(4)
    while off < len(data):
        clen, ctype = struct.unpack_from("<I4s", data, off)
        off += 8
        if ctype == b"JSON":
            return json.loads(data[off:off + clen].decode("utf-8"))
        off += clen
    raise ValueError("GLB 里没有 JSON 块")


def _sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    if not os.path.exists(SRC):
        print("★ 缺源件：%s" % SRC)
        return 4
    if not os.path.exists(BLENDER):
        print("★ Blender 不在：%s" % BLENDER)
        return 4

    bp = os.path.join(HERE, "_su_obj_to_glb.py")
    with open(bp, "w", encoding="utf-8", newline="\n") as f:
        f.write(BPY.replace("__SRC__", SRC).replace("__OUT__", OUT))

    r = subprocess.run([BLENDER, "-b", "-P", bp], capture_output=True, text=True)
    keep = ("BLENDER_IN", "BLENDER_GROUPS", "BLENDER_NODES", "BLENDER_BBOX_M",
            "EXPORTED", "UNMATCHED", "POLY_LOSS")
    for ln in (r.stdout or "").splitlines():
        if ln.startswith(keep):
            print(ln)
    if r.returncode != 0:
        print("★ Blender rc=%d" % r.returncode)
        for ln in (r.stderr or "").splitlines()[-15:]:
            print("   " + ln)
        return 1
    if not os.path.exists(OUT):
        print("★ 导出没落盘：%s" % OUT)
        return 1

    # ── 尺子二：重新打开落盘件，读它自己的 JSON 块 ─────────────────────
    g = glb_json(OUT)
    nodes = g.get("nodes", [])
    accs = g["accessors"]
    mn = [1e9] * 3
    mx = [-1e9] * 3
    bad_xform = []
    for nd in nodes:
        if any(k in nd for k in ("matrix", "translation", "rotation", "scale")):
            bad_xform.append(nd.get("name"))
        if "mesh" not in nd:
            continue
        for prim in g["meshes"][nd["mesh"]]["primitives"]:
            a = accs[prim["attributes"]["POSITION"]]
            for i in range(3):
                mn[i] = min(mn[i], a["min"][i])
                mx[i] = max(mx[i], a["max"][i])
    ext = [round(mx[i] - mn[i], 4) for i in range(3)]
    parents = sorted(nd["name"] for nd in nodes if "mesh" not in nd and nd.get("name"))
    kids = sum(1 for nd in nodes if "mesh" in nd)
    print("GLB nodes=%d  层节点=%d 个 %s  构件子节点=%d 个"
          % (len(nodes), len(parents), parents, kids))
    print("GLB BBOX_M min=%s max=%s  EXT=%s"
          % ([round(v, 3) for v in mn], [round(v, 3) for v in mx], ext))
    print("GLB bytes=%d  sha256=%s" % (os.path.getsize(OUT), _sha(OUT)))

    fails = []
    if bad_xform:
        fails.append("有节点带变换 %s ⇒ 下面的包围盒不是实测件的位置" % bad_xform[:3])
    # 朝向：glTF 是 Y 朝上 ⇒ 高度必须落在 **Y**，且高度（45.0 m @3.5 m 口径）是三轴里
    # **最小**的（平面 129.3 × 84.0）。这条与 render3d.py 的 ORIENT_FAIL 是同一个判据。
    if not (ext[1] < ext[0] and ext[1] < ext[2]):
        fails.append("高度不在 Y：EXT=%s ⇒ 整栋会躺倒" % ext)
    if abs(ext[0] - EXP_PLAN_M[0]) > 0.5 or abs(ext[2] - EXP_PLAN_M[1]) > 0.5:
        fails.append("平面尺寸对不上 %.1f×%.1f m（期望 %.1f×%.1f）"
                     % (ext[0], ext[2], EXP_PLAN_M[0], EXP_PLAN_M[1]))
    lo_exp, hi_exp = [v * MM for v in _exp_hi_mm()]
    if abs(mn[1] - lo_exp) > 0.05 or abs(mx[1] - hi_exp) > 0.05:
        fails.append("标高对不上 %.3f–%.3f m（期望 %.3f–%.3f）"
                     % (mn[1], mx[1], lo_exp, hi_exp))
    if sorted(parents) != sorted(["B1"] + ["floor%d" % k for k in range(11)]):
        fails.append("层节点名单不对：%s" % parents)
    if fails:
        print("★ 判据不过：")
        for x in fails:
            print("   - " + x)
        return 1
    print("PASS  %s  %.3f × %.3f × %.3f m（高 %.3f–%.3f）"
          % (os.path.basename(OUT), ext[0], ext[2], ext[1], mn[1], mx[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
