# -*- coding: utf-8 -*-
r"""FreeCAD 的 OBJ → 网页用的 GLB（**替代 `su_obj_to_glb.py` 那一步**）。

输入 : <ROOT>/06_su/<NAME>_fc.obj      （contours_to_fc.py 出的合并件：毫米、Z 朝上、
                                       每 (层,类) 一段，段首 `o floorN__CLASS` / `o B1__CLASS`）
输出 : <ROOT>/06_su/<NAME>_fc.glb      （米、Y 朝上；顶层节点 = 层，子节点 = <层>__<类>）

与 SU 版的差别只有**解析入口**：
  · SU 的 OBJ 是 `g Mesh<N> G_<层>__<类> Model`（组名被 SU 剥过非 ASCII）；
  · FreeCAD 的 OBJ 是 `o <层>__<类>`（名字是我们在 contours_to_fc.py 里自己写的）。
  ⇒ 后面「按 (层,类) 合成一张网格 → 挂到层空节点 → ×0.001 → export_yup」**逐行同口径**。

★ 两把尺子（与 SU 版同一条，铁律 187）：
  尺子一 = Blender 量的（毫米、Z 朝上）；
  尺子二 = 落盘后重开 GLB、直接读它 JSON 块里 POSITION 访问器的 min/max（米、Y 朝上）。
  外加：平面尺寸现算自 `05_build/<NAME>_white.obj`，标高现读 `05_build/build.json`
  —— 两个**都不手打**（层高/层数改口径时这里不会留一个不动的数）。

★ 盲区：与 SU 版相同 —— 本脚本只量**包围盒 / 节点名 / 面数守恒**。件里面每面墙对不对，
  不归它管（J-09.2-A1* / J-10.9-* 的活）。

用法：python rebuild/tools/fc_obj_to_glb.py
退出码：0 成功 · 1 判据不过 · 4 缺件（源 OBJ 或 Blender 不在）
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # `-I` 不预置脚本目录
import building as B                                              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = B.ROOT
NAME = B.out_name()
SRC = os.path.join(ROOT, "06_su", "%s_fc.obj" % NAME)
OUT = os.path.join(ROOT, "06_su", "%s_fc.glb" % NAME)
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
MM = 0.001


def _plan_m():
    """从 white OBJ 顶点现算平面外轮廓 (x, y) 米。缺件 ⇒ 明确报错，不退回常量。"""
    p = os.path.join(ROOT, "05_build", "%s_white.obj" % NAME)
    if not os.path.exists(p):
        raise SystemExit("★ 缺 %s —— 先跑 build3d.py；本脚本不猜平面尺寸" % p)
    mn = [1e9] * 3
    mx = [-1e9] * 3
    seen = 0
    with open(p, encoding="utf-8") as f:
        for ln in f:
            if not ln.startswith("v "):
                continue
            q = [float(t) for t in ln.split()[1:4]]
            seen += 1
            for i in range(3):
                mn[i] = min(mn[i], q[i])
                mx[i] = max(mx[i], q[i])
    if not seen:
        raise SystemExit("★ %s 里一个顶点都没有" % p)
    return (mx[0] - mn[0], mx[2] - mn[2])


def _exp_hi_mm():
    p = os.path.join(ROOT, "05_build", "build.json")
    b = json.load(open(p, encoding="utf-8"))
    return (-abs(float(b["basement_m"])) * 1000.0, float(b["z_max_m"]) * 1000.0)


def _nodes():
    return ((["B1"] if B.profile().get("basement") else [])
            + ["floor%d" % k for k in range(len(B.floor_names()))])


BPY = r'''
import bpy, os, re, sys, mathutils
SRC, OUT = r"__SRC__", r"__OUT__"
MM = 0.001
RE_NODE = re.compile(r"^(B1|floor\d+)__([A-Z_]+)$")

bpy.ops.wm.read_factory_settings(use_empty=True)

# ★ 不走 `bpy.ops.wm.obj_import`：它默认按「OBJ 是 Y 朝上」再转一次轴
#   （实测把 Z 15..99 m 搬到 Y 上 ⇒ 整栋躺倒，与 SU 件方向不一致）。
#   自己逐行读 ⇒ 顶点坐标与 OBJ 里写的**一字不差**（只做 mm→m）。
#   SU 的 OBJ 之所以是 Y 朝上，是 SketchUp 的 OBJ 导出器转的，不是这边转的；
#   这里导出时 `export_yup=True` 做的正是同一件事（Blender Z-up → glTF Y-up）。
# ★ f 的顶点号是**全文件全局**的（OBJ 规范；contours_to_fc.py::merge_parts 正是按运行偏移
#   重编的）。按段各自从 1 数会把除第一段外全部读成越界 —— 导出器不报错，只说
#   `Mesh 'X' is not valid` 然后 `Primitives created: 0` 把件悄悄丢掉（88 段只剩 2 段）。
gverts = []                 # 全局顶点表（米）
groups = {}                 # name -> [vstart, vend, faces(全局 0 基)]
order = []
with open(SRC, "r", encoding="utf-8", errors="replace") as fh:
    cur = None
    for ln in fh:
        if ln.startswith("o "):
            cur = ln[2:].strip()
            if cur not in groups:
                groups[cur] = [len(gverts), len(gverts), []]
                order.append(cur)
        elif ln.startswith("v "):
            gverts.append(tuple(float(t) * MM for t in ln.split()[1:4]))
        elif ln.startswith("f "):
            groups[cur][2].append(tuple(int(t.split("/")[0]) - 1 for t in ln.split()[1:]))
for name in order:
    groups[name][1] = None      # 先占位，下面按「下一段起点」回填
for i, name in enumerate(order):
    groups[name][1] = groups[order[i + 1]][0] if i + 1 < len(order) else len(gverts)
print("BLENDER_IN objects=%d polys=%d verts=%d"
      % (len(groups), sum(len(g[2]) for g in groups.values()), len(gverts)))

by_node, unmatched, polys_in = {}, [], 0
for name in order:
    vstart, vend, fs = groups[name]
    polys_in += len(fs)
    oob = [i for f in fs for i in f if i < vstart or i >= vend]
    if oob:
        print("IDX_OOB %s vstart=%d vend=%d 例=%s" % (name, vstart, vend, oob[:5]))
        sys.exit(3)
    m = RE_NODE.match(name)
    if not m:
        unmatched.append(name)
        continue
    by_node.setdefault((m.group(1), m.group(2)), []).append((vstart, vend, fs))
if unmatched:
    print("UNMATCHED n=%d 例=%s" % (len(unmatched), unmatched[:5]))
    sys.exit(3)

NODES = __NODES__
scene = bpy.context.scene.collection
empties = {}
for n in NODES:
    e = bpy.data.objects.new(n, None)
    scene.objects.link(e)
    empties[n] = e

polys_out = 0
for (node, cls), chunks in sorted(by_node.items()):
    nm = "%s__%s" % (node, cls)
    verts, faces = [], []
    for vstart, vend, fs in chunks:
        base = len(verts)
        verts.extend(gverts[vstart:vend])
        faces.extend(tuple(base + (i - vstart) for i in f) for f in fs)
    me = bpy.data.meshes.new(nm)
    me.from_pydata(verts, [], faces)
    me.update()
    if len(me.polygons) != len(faces):
        print("MESH_LOSS %s faces=%d built=%d" % (nm, len(faces), len(me.polygons)))
        sys.exit(3)
    polys_out += len(me.polygons)
    ob = bpy.data.objects.new(nm, me)
    scene.objects.link(ob)
    ob.parent = empties[node]
    if os.environ.get("CDUT_FC_VERBOSE") == "1":
        print("OBJ %-22s polys=%d verts=%d users=%d"
              % (nm, len(me.polygons), len(me.vertices), len(ob.users_collection)))

# ★ `export_apply=True` 走**求值后的** depsgraph；刚建好的对象若不等它更新，
#   导出器会拿到空网格（实测：88 个节点全导出了，但只有 2 个带 mesh，
#   文件 1.0 MB vs 应有 10.5 MB，且不报错 —— 又一处「静默丢内容」）。
bpy.context.view_layer.update()

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
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"glTF":
        raise ValueError("不是 GLB：%s" % path)
    off = 12
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

    bp = os.path.join(HERE, "_fc_obj_to_glb.py")
    with open(bp, "w", encoding="utf-8", newline="\n") as f:
        f.write(BPY.replace("__SRC__", SRC).replace("__OUT__", OUT)
                   .replace("__NODES__", json.dumps(_nodes())))

    r = subprocess.run([BLENDER, "-b", "-P", bp], capture_output=True, text=True)
    keep = ("BLENDER_IN", "BLENDER_GROUPS", "BLENDER_NODES", "BLENDER_BBOX_M",
            "EXPORTED", "UNMATCHED", "POLY_LOSS", "MESH_LOSS")
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
    n_sec = sum(1 for ln in open(SRC, encoding="utf-8", errors="replace")
                if ln.startswith("o "))
    if kids != n_sec:
        # 「节点在、网格空」与「件少了几块」同形 ⇒ 拿文件里的段数当另一把尺子
        fails.append("带 mesh 的节点 %d 个 ≠ 源文件段数 %d 段 ⇒ 有段落被导成空节点" % (kids, n_sec))
    if bad_xform:
        fails.append("有节点带变换 %s ⇒ 下面的包围盒不是实测件的位置" % bad_xform[:3])
    plan = _plan_m()
    if abs(ext[0] - plan[0]) > 0.5 or abs(ext[2] - plan[1]) > 0.5:
        fails.append("平面尺寸对不上 %.1f×%.1f m（期望 %.1f×%.1f，取自 white OBJ）"
                     % (ext[0], ext[2], plan[0], plan[1]))
    lo_exp, hi_exp = [v * MM for v in _exp_hi_mm()]
    # ★★ 2026-10-17 C022 实测：原来这条判据写的是「高度必须是三轴里**最小**的那一轴」——
    #   那是 c006 的形状（50.5 m 高、129×84 平面），不是**所有楼**的形状。
    #   C022 是 47.5×26.9 平面、28.7 m 高 ⇒ 高度比进深还大，件完全正确却被判「会躺倒」。
    #   真正的判据是「高度落在 Y 上」：拿**期望高度**去比 Y 跨距；只在躺倒时
    #   （Y 跨距≈平面尺寸、Z 跨距≈高度）才报「躺倒」，其余交给下面的标高判据带数字报。
    _h_exp = hi_exp - lo_exp
    if abs((mx[1] - mn[1]) - _h_exp) > 0.05 and abs((mx[2] - mn[2]) - _h_exp) <= 0.05:
        fails.append("高度跑到了 Z 上：EXT=%s（高 %.1f m 在 Z）⇒ 整栋躺倒" % (ext, _h_exp))
    if abs(mn[1] - lo_exp) > 0.05 or abs(mx[1] - hi_exp) > 0.05:
        fails.append("标高对不上 %.3f–%.3f m（期望 %.3f–%.3f）"
                     % (mn[1], mx[1], lo_exp, hi_exp))
    if sorted(parents) != sorted(_nodes()):
        fails.append("层节点名单不对：%s（期望 %s）" % (parents, _nodes()))
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
