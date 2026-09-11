# -*- coding: utf-8 -*-
"""GLB 减面验证：导入 → Limited Dissolve（共面合并）→ Decimate → 导出，对比体积。

用法: blender -b -P decimate_test.py -- <in.glb> <out.glb> <ratio>
"""
import math
import os
import sys

import bpy

argv = sys.argv
inp = argv[argv.index("--") + 1]
out = argv[argv.index("--") + 2]
ratio = float(argv[argv.index("--") + 3])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=inp)

obj = next(o for o in bpy.data.objects if o.type == "MESH")
print(f"[before] verts={len(obj.data.vertices)} tris={len(obj.data.polygons)}")

bpy.context.view_layer.objects.active = obj
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")

# 1) 共面合并（墙是平盒，可大量去冗余面）
try:
    bpy.ops.mesh.dissolve_limited(angle_limit=math.radians(0.5))
    print(f"[dissolve] verts={len(obj.data.vertices)} tris={len(obj.data.polygons)}")
except Exception as e:
    print(f"[dissolve] skipped: {e}")

# 2) 按比例减面
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.decimate(ratio=ratio)
print(f"[decimate {ratio}] verts={len(obj.data.vertices)} tris={len(obj.data.polygons)}")
bpy.ops.object.mode_set(mode="OBJECT")

bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")

in_size = os.path.getsize(inp)
out_size = os.path.getsize(out)
print(f"[size] {os.path.basename(inp)} = {in_size/1e6:.1f} MB")
print(f"[size] {os.path.basename(out)} = {out_size/1e6:.1f} MB  ({100*out_size/in_size:.0f}%)")
