# -*- coding: utf-8 -*-
import sys
import bpy
from mathutils import Vector, Matrix
GLB = r"D:\gym3d\data\lihua-building.glb"
OUT = r"D:\gym3d\data\_south_verify.png"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
bpy.context.view_layer.update()
mn = mx = None
for obj in bpy.data.objects:
    if obj.type != "MESH": continue
    for corner in obj.bound_box:
        w = obj.matrix_world @ Vector(corner)
        mn = w if mn is None else Vector((min(mn.x,w.x),min(mn.y,w.y),min(mn.z,w.z)))
        mx = w if mx is None else Vector((max(mx.x,w.x),max(mx.y,w.y),max(mx.z,w.z)))
center = (mn+mx)/2; size = mx-mn
print("bounds center", center, "size", size)
# 平涂
for mat in bpy.data.materials:
    if not mat.use_nodes: continue
    nt = mat.node_tree; out=None; vcol=None
    for n in nt.nodes:
        if n.type=="OUTPUT_MATERIAL": out=n
        elif n.type in ("VERTEX_COLOR","ATTRIBUTE"): vcol=n
    if out is None: continue
    for inp in out.inputs:
        for l in list(inp.links): nt.links.remove(l)
    em = nt.nodes.new(type="ShaderNodeEmission"); em.inputs["Strength"].default_value=1.0
    if vcol is not None: nt.links.new(vcol.outputs["Color"], em.inputs["Color"])
    else: em.inputs["Color"].default_value=(0.8,0.8,0.8,1)
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
# 南立面相机：在 -Y 朝 +Y 看
cam_data = bpy.data.cameras.new("Cam"); cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.collection.objects.link(cam)
dist = max(size.x,size.y,size.z)*3.0
cam.location = Vector((center.x, center.y - dist, center.z))
f = (center - cam.location).normalized()
u = Vector((0,0,1)); r = f.cross(u); r.normalize(); u2 = r.cross(f).normalize()
m = Matrix((r,u2,-f)).transposed(); cam.rotation_euler = m.to_euler()
cam_data.type="ORTHO"; cam_data.ortho_scale = max(size.z, size.x/ (1920/1080))*1.18
bpy.context.scene.camera = cam
scene = bpy.context.scene
try: scene.view_settings.view_transform="Standard"
except: pass
scene.render.engine="BLENDER_EEVEE"
scene.render.resolution_x=1920; scene.render.resolution_y=1080
scene.render.image_settings.file_format="PNG"; scene.render.filepath=OUT
scene.eevee.taa_render_samples=64
bpy.ops.render.render(write_still=True)
print("saved", OUT)
