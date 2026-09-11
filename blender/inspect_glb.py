# -*- coding: utf-8 -*-
"""导入 GLB 并 dump 结构：对象名 / 类型 / 顶点数 / 三角数 / 材质 / 顶点色。

用法: blender -b -P inspect_glb.py -- <glb路径>
"""
import sys

import bpy

path = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)

print(f"=== {path} ===")
total_v = total_t = 0
n_obj = 0
for o in bpy.data.objects:
    if o.type == "MESH":
        n_obj += 1
        m = o.data
        mats = [mat.name for mat in m.materials] if m.materials else []
        has_vcol = len(m.color_attributes) > 0
        vc_names = [a.name for a in m.color_attributes]
        total_v += len(m.vertices)
        total_t += len(m.polygons)
        print(f"MESH '{o.name}'  verts={len(m.vertices)}  tris={len(m.polygons)}  "
              f"mats={mats}  vcol={has_vcol}{vc_names if has_vcol else ''}")
    else:
        print(f"{o.type} '{o.name}'")
print(f"[合计] 对象={n_obj} 顶点={total_v} 三角={total_t}")
