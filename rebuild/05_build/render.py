
import bpy, mathutils, sys
SRC, OUT, PREFIX = r"D:\项目\cdut3d\rebuild\05_build\c006_white.glb", r"D:\项目\cdut3d\rebuild\05_build", r"c006_"
bpy.ops.wm.read_factory_settings(use_empty=True)
if SRC.lower().endswith(".obj"):
    # ★ SU 的 OBJ 是 Y 朝上；Blender 的 OBJ 导入器默认按 Y-up 收进来并转成 Z-up。
    # ★★ 必须 use_split_groups=True：SU 只写 `g`（不写 `o`），实测不拆就是 1 个对象
    #    （OBJS n=1）⇒ 下面的按类上色表全失效、整件一个灰。拆开后组名即层名。
    bpy.ops.wm.obj_import(filepath=SRC, use_split_groups=True)
else:
    bpy.ops.import_scene.gltf(filepath=SRC)
_ms=[o for o in bpy.data.objects if o.type=='MESH']
print("OBJS n=%d names=%s" % (len(_ms), [o.name for o in _ms][:6]))
# ★ 按**构件**上色：白模一色时「竖井/台阶屋面/女儿墙」在图上根本认不出来，
#   用户看图时只能看到一团灰。颜色表与 build3d 的节点名一一对应。
TAGCOL={"wall":(0.62,0.62,0.64,1),"col":(0.20,0.35,0.75,1),"lift":(0.90,0.10,0.10,1),
        "slab":(0.86,0.86,0.86,1),"door":(0.95,0.55,0.05,1),"stair":(0.98,0.90,0.15,1),
        "roof_step7":(0.05,0.75,0.85,1),"parapet":(0.10,0.70,0.20,1),
        "roof_stair":(0.65,0.15,0.80,1),"roof":(0.30,0.30,0.32,1)}
def _ramp(t):
    st=[(0.11,0.25,0.33),(0.55,0.60,0.63),(0.87,0.76,0.52)]
    t=min(max(float(t),0.0),1.0); seg=t*(len(st)-1); i=min(int(seg),len(st)-2); f=seg-i
    return tuple(st[i][k]+(st[i+1][k]-st[i][k])*f for k in range(3))+(1,)
_mesh=[o for o in bpy.data.objects if o.type=='MESH']
# ★↓ 花括号必须写成双的 —— 这一整块是 str.format() 的模板，单个 `{` 会被当占位符吃掉
_idx={o.name:i for i,o in enumerate(sorted(_mesh,key=lambda o:o.name))}
# ★ 兜底上色：名字一个都不沾构件表时（交付包是**按层**命名的 `floor0..floor10`/`B1`），
#   全场一个灰 ⇒ 12 层糊成一坨、看不出层。此时按**名字排序后的下标**走冷暖渐变。
#   ★ 只对「命中不了任何构件键」的对象兜底 ⇒ 参照件/正式件（名字能命中）颜色一字不变。
_ramped=0
for o in _mesh:
    nm=o.name.lower(); hit=None
    for k in ("roof_step7","roof_stair","parapet","lift","slab","door","stair","col","wall","roof"):
        if k in nm: hit=k; break
    if hit is not None:
        o.color = TAGCOL.get(hit,(0.5,0.5,0.5,1))
    else:
        o.color = _ramp(_idx[o.name]/max(1,len(_mesh)-1)); _ramped+=1
print("RAMPED %d/%d" % (_ramped, len(_mesh)))
mng=[1e9]*3; mxg=[-1e9]*3
for o in bpy.data.objects:
    if o.type=='MESH':
        for c in o.bound_box:
            w=o.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                mng[i]=min(mng[i],w[i]); mxg[i]=max(mxg[i],w[i])
ext=[mxg[i]-mng[i] for i in range(3)]
# ★★ 朝向自检：件导进 Blender 后必须 **Z 朝上**（Blender 惯例）。glTF 文件本身是 Y 朝上，
#   Blender 导入时替我们转过来；**若出件又写成 Z 朝上，这个转换会把它转到 −Y 上**，
#   于是下面三张图全部对调（「正立面」画出的是俯视）却看着还挺像 —— 2026-10-13 真发生过。
#   高度（50.5 m）在三个尺寸里最小（平面 129×84 m）⇒ 用「Z 必须是三轴最小」当场拦下。
#   ★ 自检一律拿**整件**做（就是上面这段）：特写筛只改取景、不改朝向 ——
#     把筛写在自检前头，等于对「筛剩下的那一小块」自检，那道闸当场作废。
if not (ext[2] < ext[0] and ext[2] < ext[1]):
    print("ORIENT_FAIL", [round(v,2) for v in ext])
    sys.exit(2)
print("ORIENT_OK", [round(v,2) for v in ext])
# ---- 特写（构件库对照页用）：--only 按节点名留件，--box 只留与该盒相交的件 ----
_only = r""
if _only:
    # ★ 逗号清单，例如 `--only wall,door,slab`：一个词留不住「墙＋门」这个主角组合，
    #   而只要门不要墙，就看不见「门上面那个洞」本身。
    _keys=[k.strip().lower() for k in _only.split(",") if k.strip()]
    _rm=[o for o in list(bpy.data.objects) if o.type=='MESH'
         and not any(k in o.name.lower() for k in _keys)]
    for o in _rm:
        bpy.data.objects.remove(o, do_unlink=True)
    print("ONLY keys=%s keep %d del %d" % (_keys,
          len([o for o in bpy.data.objects if o.type=='MESH']), len(_rm)))
_box = None
if _box:
    # ★ --box 一律按**源图 mm** 给；件自己是毫米还是米，由**实测尺寸**推，不写死：
    #   实测 SU 的 OBJ 进来就是 mm（ext=[129300, 84000, 50500]），而 GLB 那条路是米。
    #   写死一边，另一条路就会「出图全空」，且与「这里本来就没东西」同形（铁律 199）。
    _k = 1.0 if max(ext) > 1000.0 else 0.001
    _box = tuple(v * _k for v in _box)
    print("UNIT k=%.4f ext=%s" % (_k, [round(v,1) for v in ext]))
    _rm=[]
    for o in [o for o in bpy.data.objects if o.type=='MESH']:
        _bb=[o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
        if (max(p[0] for p in _bb) < _box[0] or min(p[0] for p in _bb) > _box[3]
                or max(p[1] for p in _bb) < _box[1] or min(p[1] for p in _bb) > _box[4]
                or max(p[2] for p in _bb) < _box[2] or min(p[2] for p in _bb) > _box[5]):
            _rm.append(o)
    for o in _rm:
        bpy.data.objects.remove(o, do_unlink=True)
    print("BOX keep %d del %d" % (len([o for o in bpy.data.objects if o.type=='MESH']), len(_rm)))
mn=[1e9]*3; mx=[-1e9]*3
for o in bpy.data.objects:
    if o.type=='MESH':
        for c in o.bound_box:
            w=o.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                mn[i]=min(mn[i],w[i]); mx[i]=max(mx[i],w[i])
if _box:
    ctr=mathutils.Vector([(_box[0]+_box[3])/2.0,(_box[1]+_box[4])/2.0,(_box[2]+_box[5])/2.0])
    size=max(_box[3]-_box[0],_box[4]-_box[1],_box[5]-_box[2])
else:
    ctr=mathutils.Vector([(mn[i]+mx[i])/2 for i in range(3)])
    size=max(mx[i]-mn[i] for i in range(3))
print("FRAME ctr=%s size=%.2f" % ([round(v,2) for v in ctr], size))
cd=bpy.data.cameras.new('c'); cam=bpy.data.objects.new('c',cd)
bpy.context.scene.collection.objects.link(cam); bpy.context.scene.camera=cam
cd.type='ORTHO'; cd.ortho_scale=size*1.15; cd.clip_end=size*10
sc=bpy.context.scene
sc.render.engine='BLENDER_WORKBENCH'
sc.display.shading.light='STUDIO'; sc.display.shading.color_type='OBJECT'
sc.display.shading.show_shadows=True
sc.render.resolution_x=1600; sc.render.resolution_y=1100
sc.render.image_settings.file_format='PNG'
views={"iso":(0.9,-1.0,0.65),"front":(0.0,-1.0,0.0),"top":(0.0,-0.001,1.0)}
for name,dirv in views.items():
    d=mathutils.Vector(dirv).normalized()*size*3.0
    cam.location=ctr+d
    cam.rotation_euler=(ctr-cam.location).normalized().to_track_quat('-Z','Y').to_euler()
    sc.render.filepath=OUT+"\\"+PREFIX+name+".png"
    bpy.ops.render.render(write_still=True)
    print("WROTE", sc.render.filepath)
