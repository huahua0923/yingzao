
import bpy, re, sys, mathutils
SRC, OUT = r"D:\项目\cdut3d\rebuild\06_su\c006_su.obj", r"D:\项目\cdut3d\rebuild\06_su\c006_su.glb"
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

NODES = ["B1", "floor0", "floor1", "floor2", "floor3", "floor4", "floor5", "floor6", "floor7", "floor8", "floor9", "floor10"]
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
