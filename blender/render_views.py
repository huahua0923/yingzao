# -*- coding: utf-8 -*-
"""
Blender 无头渲染：建筑立面图 / 顶视图 / 轴测图

用法:
  blender -b -P render_views.py -- --glb <in.glb> --out <out.png> --view front

  --view 取值: front(正立面) | side(侧立面) | top(顶视图/平面) | iso(轴测)

依赖: Blender >= 4.0 (自带 bpy + glTF 导入器)，无需额外包。
"""
import math
import sys

import bpy
from mathutils import Vector, Matrix

DEFAULTS = {
    "glb": r"D:\gym3d\data\lihua-walls.glb",
    "out": r"D:\gym3d\data\lihua-front.png",
    "view": "front",
    "res": "1920x1080",
}


def parse_args():
    args = dict(DEFAULTS)
    argv = sys.argv
    if "--" not in argv:
        return args
    rest = argv[argv.index("--") + 1:]
    i = 0
    while i < len(rest):
        k = rest[i]
        if k in ("--glb", "--out", "--view", "--res", "--zoom") and i + 1 < len(rest):
            args[k[2:]] = rest[i + 1]
            i += 2
        elif k == "--flat":
            args["flat"] = True
            i += 1
        else:
            i += 1
    return args


def scene_bounds():
    """所有 MESH 对象的世界包围盒，返回 (center, size) 两个 Vector。"""
    bpy.context.view_layer.update()
    mn = mx = None
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            w = obj.matrix_world @ Vector(corner)
            if mn is None:
                mn = Vector(w)
                mx = Vector(w)
            else:
                mn.x = min(mn.x, w.x)
                mn.y = min(mn.y, w.y)
                mn.z = min(mn.z, w.z)
                mx.x = max(mx.x, w.x)
                mx.y = max(mx.y, w.y)
                mx.z = max(mx.z, w.z)
    if mn is None:
        raise RuntimeError("场景里没有 MESH 对象，导入失败？")
    return (mn + mx) / 2.0, mx - mn


def make_flat():
    """把每个材质改成自发光平涂：面片颜色 = 顶点色，无光照，所见即 GLB 顶点色。

    用于几何验证（墙厚 / 门洞 / 门扇 / 过梁是否真的挖穿、对齐），
    避开太阳光 + Standard 变换把红砖 #a4533d 洗成桃色 (240,176,160) 的干扰。
    """
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        nt = mat.node_tree
        out = None
        vcol = None
        for n in nt.nodes:
            if n.type == "OUTPUT_MATERIAL":
                out = n
            elif n.type in ("VERTEX_COLOR", "ATTRIBUTE"):
                vcol = n
        if out is None:
            continue
        for inp in out.inputs:
            for l in list(inp.links):
                nt.links.remove(l)
        em = nt.nodes.new(type="ShaderNodeEmission")
        em.inputs["Strength"].default_value = 1.0
        if vcol is not None:
            nt.links.new(vcol.outputs["Color"], em.inputs["Color"])
        else:
            em.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1.0)
        nt.links.new(em.outputs["Emission"], out.inputs["Surface"])


def setup_lighting(light_dir):
    """太阳光从相机侧打光 + 淡蓝天空背景，让被渲染立面被照亮而非阴影。"""
    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 4.0
    sun_data.angle = math.radians(2)
    sun = bpy.data.objects.new("Sun", sun_data)
    # 太阳的 -Z 轴指向光行进方向 light_dir（光从反方向射来）
    sun.rotation_euler = light_dir.to_track_quat("-Z", "Y").to_euler()
    bpy.context.collection.objects.link(sun)

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.55, 0.68, 0.85, 1.0)  # 淡蓝天空
        bg.inputs["Strength"].default_value = 0.6
    bpy.context.scene.world = world


def _look_at(cam, forward, up):
    """把相机对准 forward（相机 -Z 朝前）、up 指向画面上方，返回正交基 (right, up, forward)。

    手动构造旋转矩阵，避免 to_track_quat 在 up 与 forward 平行（顶视图朝下看）时退化。
    """
    f = forward.normalized()
    u = up.normalized()
    r = f.cross(u)
    if r.length < 1e-6:
        r = Vector((1.0, 0.0, 0.0))
    r.normalize()
    u2 = r.cross(f).normalized()
    # 相机局部 +X=right / +Y=up / -Z=forward → 世界_from_局部 的列 = [right, up, -forward]
    m = Matrix((r, u2, -f)).transposed()
    cam.rotation_euler = m.to_euler()
    return r, u2, f


def make_camera(view, center, size, aspect):
    """创建相机并对准包围盒中心，返回 (camera, forward, up) 供打光复用。

    Blender 导入 glTF 会把 Y-up 转成 Z-up（glTF (x,y,z) → Blender (x,z,y)）：
      Blender +Z = 高（原 glTF +Y）、+Y = 南（原 glTF +Z，南立面 5 扇门在此侧）、+X = 东。
    故  front = 南立面（相机在 +Y 朝 -Y 看）、side = 东立面（+X）、top = 顶视（+Z 朝下）。
    旧代码 front 放在 -Y（拍到北立面，无门），是「南立面看不到门」的根因。
    """
    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam)

    pad = 1.18
    dist = max(size.x, size.y, size.z) * 3.0

    if view == "front":   # 南立面（门所在面）：相机在南侧 -Y 朝 +Y 看，上 = +Z（高）
        # 注：Blender glTF 导入是 Y-up→Z-up 且 z 反向，即 glTF(x,y,z)→Blender(x,-z,y)，
        # 故 Blender +Y=北、-Y=南。南立面（5 扇门）在 -Y 侧，相机须放 -Y 朝 +Y 看。
        cam.location = Vector((center.x, center.y - dist, center.z))
        up = Vector((0, 0, 1))
        vert, horiz = size.z, size.x
        cam_data.type = "ORTHO"
    elif view == "side":  # 东立面：+X 朝 -X 看，上 = +Z（高）
        cam.location = Vector((center.x + dist, center.y, center.z))
        up = Vector((0, 0, 1))
        vert, horiz = size.z, size.y
        cam_data.type = "ORTHO"
    elif view == "top":   # 顶视/平面：+Z 朝下看，上 = -Y（北）
        cam.location = Vector((center.x, center.y, center.z + dist))
        up = Vector((0, -1, 0))
        vert, horiz = size.y, size.x
        cam_data.type = "ORTHO"
    elif view == "iso":   # 轴测：东南上方
        cam.location = Vector(
            (center.x + size.x * 1.5, center.y + size.y * 1.5, center.z + size.z * 1.2)
        )
        up = Vector((0, 0, 1))
        cam_data.type = "PERSP"
        cam_data.lens = 35
    else:
        raise ValueError(f"未知 --view: {view}")

    forward = (center - cam.location).normalized()
    _look_at(cam, forward, up)

    if cam_data.type == "ORTHO":
        cam_data.ortho_scale = max(vert, horiz / aspect) * pad

    bpy.context.scene.camera = cam
    return cam, forward, up


def main():
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=args["glb"])

    center, size = scene_bounds()
    print(
        f"[bounds] center=({center.x:.2f},{center.y:.2f},{center.z:.2f}) "
        f"size=({size.x:.2f},{size.y:.2f},{size.z:.2f})"
    )

    if args.get("flat"):
        make_flat()

    # 局部放大：--zoom x0,y0,z0,x1,y1,z1（Blender 世界坐标），覆盖 center/size 聚焦某区域
    if args.get("zoom"):
        zx0, zy0, zz0, zx1, zy1, zz1 = (float(v) for v in args["zoom"].split(","))
        center = Vector(((zx0 + zx1) / 2, (zy0 + zy1) / 2, (zz0 + zz1) / 2))
        size = Vector((zx1 - zx0, zy1 - zy0, zz1 - zz0))
        print(f"[zoom] center=({center.x:.2f},{center.y:.2f},{center.z:.2f}) "
              f"size=({size.x:.2f},{size.y:.2f},{size.z:.2f})")

    rx, ry = (int(v) for v in args["res"].split("x"))
    cam, forward, up = make_camera(args["view"], center, size, rx / ry)

    side = forward.cross(up)
    if side.length < 1e-6:
        side = Vector((1, 0, 0))
    side.normalize()
    # 光从相机侧前上方射来，带一点侧偏让墙体有明暗层次
    light_dir = (forward - 0.6 * up + 0.35 * side).normalized()
    setup_lighting(light_dir)

    scene = bpy.context.scene
    try:
        scene.view_settings.view_transform = "Standard"  # 白色保持亮，不被 AgX 压灰
    except Exception:
        pass

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = rx
    scene.render.resolution_y = ry
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = args["out"]
    scene.eevee.taa_render_samples = 64

    bpy.ops.render.render(write_still=True)
    print(f"[view_transform] {scene.view_settings.view_transform}")
    print(f"[render] saved {args['out']}")


if __name__ == "__main__":
    main()
