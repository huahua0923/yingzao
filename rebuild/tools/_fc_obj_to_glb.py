
import bpy, os, re, sys, mathutils
SRC, OUT = r"D:\项目\cdut3d\rebuild\c054\06_su\c054_fc.obj", r"D:\项目\cdut3d\rebuild\c054\06_su\c054_fc.glb"
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

NODES = ["floor0", "floor1", "floor2", "floor3", "floor4", "floor5"]
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
