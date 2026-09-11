# -*- coding: utf-8 -*-
"""临时：近景渲染南立面一扇门（世界坐标 z≈3.83），检查门洞/过梁/门扇。"""
import math
import bpy
from mathutils import Vector

glb = r"D:\gym3d\data\lihua-building.glb"
out = r"D:\gym3d\data\lihua-door-closeup.png"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)

# 门组中心：本地 y=-3.83 → 世界 z=3.83，第一层门高 0~2.4，中心高 1.2
target = Vector((0.0, 1.2, 3.83))
# 相机从南侧外（z 正方向）看向门，斜一点带侧面，能看清门扇厚度
cam_pos = target + Vector((2.5, 0.6, 7.0))

cam_data = bpy.data.cameras.new("Cam")
cam_data.type = "PERSP"
cam_data.lens = 50
cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.collection.objects.link(cam)
cam.location = cam_pos
cam.rotation_euler = (cam_pos - target).to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

# 太阳光 + 天空（复用 render_views 的打光思路）
sun_data = bpy.data.lights.new("Sun", type="SUN")
sun_data.energy = 4.0
sun = bpy.data.objects.new("Sun", sun_data)
bpy.context.collection.objects.link(sun)
forward = (target - cam_pos).normalized()
sun.rotation_euler = (forward - Vector((0, 0.6, 0)) - Vector((0.35, 0, 0))).normalized().to_track_quat("-Z", "Y").to_euler()

world = bpy.data.worlds.new("World")
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg is not None:
    bg.inputs["Color"].default_value = (0.55, 0.68, 0.85, 1.0)
    bg.inputs["Strength"].default_value = 0.6
bpy.context.scene.world = world

try:
    bpy.context.scene.view_settings.view_transform = "Standard"
except Exception:
    pass

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1280
scene.render.resolution_y = 960
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = out
scene.eevee.taa_render_samples = 64
bpy.ops.render.render(write_still=True)
print("[render] saved", out)
