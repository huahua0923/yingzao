# -*- coding: utf-8 -*-
"""「底面 → 拉伸成体」—— 这一步**交给 Blender 做**，本仓不手搓几何。

为什么换掉手搓（用户判词 2026-10-12/13「楼板直角处，还是有圆角」「换个成熟的做法」）：
  · 旧路是 `shapely.buffer(r).buffer(-r)` 做形态学闭运算 ⇒ `buffer()` 的 `join_style` 默认
    **round** ⇒ 凹角被圆盘结构元切成圆弧（`demo/arcfix/measure.json` a1 臂：52 个直角
    全变弧、弧长 19541.5 mm）。改成 `mitre` 也不稳：尖角上 GEOS 会返回**无效几何**
    （libgeos/geos#856）⇒ 那是把病换个样子。
  · Blender 的拉伸是**精确布尔**：底面是折线就还是折线，直角就是直角；洞口由
    `triangle_fill` 在**同一次**填面里处理，不产生相邻块之间的缝。

本脚本**只做一件事**：读一份**规范化棱柱表**（与任何上游链无关的中间格式），
逐个底面拉伸，写成一个 GLB。**它不知道 DXF、不知道墙、不知道层** —— 那些由适配器去做。
这样「用哪个专业工具建」与「底面从哪来」是两件事，可以各自替换
（Blender / SketchUp / 3ds Max 换成谁，本脚本换掉即可，适配器不动）。

规范化棱柱表（`--in`）：
  { "units": "m",
    "solids": [ { "name": "floor0/slab",
                  "poly":  [[x,y], ...],            # 外环，顺时针/逆时针都行
                  "holes": [[[x,y], ...], ...],     # 可选；每项一个内环
                  "z0": 0.0, "z1": 0.12 } ] }

用法（**必须用 Blender 无头跑**，本文件不能被 CPython import）：
  blender -b --python tools/prism_blender.py -- --in _gen/solid_input.json --out _gen/solid.glb
"""
import json
import sys

import bmesh
import bpy

# Blender 传给脚本的参数在 `--` 之后
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _arg(flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


SRC = _arg("--in")
OUT = _arg("--out")


def reset():
    """空场景：保证「跑出来的面数」只由输入决定，不受启动文件影响。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def prism(poly, holes, z0, z1):
    """一个底面 → 一个实体。返回建好的 object；底面退化（<3 点 / 零面积）返回 None。"""
    if len(poly) < 3:
        return None
    bm = bmesh.new()

    def loop(pts):
        vs = [bm.verts.new((float(p[0]), float(p[1]), float(z0))) for p in pts]
        bm.edges.new(vs + [vs[0]]) if len(vs) == 2 else None
        if len(vs) > 2:
            for i in range(len(vs)):
                bm.edges.new((vs[i], vs[(i + 1) % len(vs)]))
        return vs

    v_out = loop(poly)
    for h in (holes or []):
        loop(h)
    bm.verts.index_update()
    bm.edges.index_update()

    caps = []
    if not holes:
        # 无洞 ⇒ 直接一个 n 边形。**这是保住直角的关键**：不做三角剖分就不引入新角。
        f = bm.faces.new(v_out)
        caps = [f]
    else:
        # 有洞 ⇒ 用 Blender 自己的填面（它会同时吃外环与内环，填出带洞的盖）
        res = bmesh.ops.triangle_fill(bm, edges=list(bm.edges), use_beauty=True,
                                      use_dissolve=False)
        caps = [g for g in res.get("geom", []) if isinstance(g, bmesh.types.BMFace)]
        if not caps:
            bm.free()
            return None

    ret = bmesh.ops.extrude_face_region(bm, geom=caps)
    moved = [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=moved, vec=(0.0, 0.0, float(z1) - float(z0)))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

    me = bpy.data.meshes.new("prism")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("prism", me)
    bpy.context.collection.objects.link(ob)
    return ob


def main():
    spec = json.load(open(SRC, encoding="utf-8"))
    if spec.get("units") != "m":
        raise SystemExit("★ 只吃 units=m 的表（实测单位错会让整栋差 1000 倍：%r）" % spec.get("units"))
    reset()

    n_in = n_out = n_degen = 0
    for s in spec["solids"]:
        n_in += 1
        ob = prism(s["poly"], s.get("holes") or [], s["z0"], s["z1"])
        if ob is None:
            n_degen += 1
            continue
        ob.name = s.get("name") or ("solid%d" % n_out)
        n_out += 1

    bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB",
                              export_yup=True, export_apply=True)
    print("PRISM-OK solids_in=%d solids_out=%d degenerate=%d -> %s" % (n_in, n_out, n_degen, OUT))


main()
