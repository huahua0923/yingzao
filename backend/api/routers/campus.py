# -*- coding: utf-8 -*-
"""校区地形数据域的路由（真地形 DTM + 真影像正射 → 一份带贴图的 GLB）。

三条 GET，**全是只读** —— 所以都不挂 `ComputeDep`：这一屏只是把一份已经建好的
交付件拿出来看，不写盘、不跑命令。（本仓规矩：「能不能写」只由
`deps.exec_denied_reason` 一处判；这里既然没有写口，就不该挂一个执行面闸门装样子。）

★ 这条读取面的全部边界（铁律 12）：**请求方给不出路径，只能给出键。**
  三条路由里，前两条的键是常量、路径完全由服务端算出来；第三条带参数，
  但它的键必须**先在数据层的 `blocks[].crop` 里查到条目**，路径才从条目里出来。
  换句话说即使请求方递进来一个 `../../x.png`，它也不在那份名单里 ⇒ 404。
  这不是"顺手加的校验"，是这条面唯一的实现。

★ 为什么产物在 `_scratch/` 下（如实，不是设计）：构建器与数据层导出器都还在
  `_scratch/_campus3d/campus-terrain/`，交付件也跟着留在那儿。
  `settings.resolved_campus_dir` 是这条依赖的**唯一**出口 —— 服务器上 `_scratch`
  不存在，这三条路由就回 404 并**明说找的是哪个目录**，而不是白屏。

★ 为什么 JSON 走 `FileResponse` 而不是 `json.loads` 再 `ok(...)`：
  信封会重新序列化一遍，浮点的写法会变（`4.800000000000001` 这类），
  于是**服务端发出去的字节**与**盘上那份交付件**不再是同一份东西了。
  数据层是"一次带时刻的测量"（铁律 50），不该在传输途中被重新表达一次。
  代价是这一条路由的错误体不是本仓信封形状 —— 前端因此用**裸 fetch** 读它，
  并对 `r.ok` 分支（见 `views/campus.js`）。
"""
import json

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ..authz import require_cap
from ..deps import SettingsDep
from ..responses import ERR_UPSTREAM, ApiError, not_found

# ★ 权限（2026-10-01 批次 2）：**全校区口径** —— 这五条回的是"整个校区"的那一份
#   地形 / 影像 / 建筑场景 / 洞底截图，**逐栋过滤在这里没有实现对象**：
#   `viewdata` 是一棵整体场景树，切开就画不出来了。
#
#   ★ 这是一次**决定，不是默认**：用户的原始要求就是"所有建筑放上去，平常看到
#     一个个实体的建筑就可以了"—— 校区外形是给所有人看的；真正要挡的是**进到楼
#     里面**之后的每层功能与使用单位（那些走 `/api/buildings/{name}*` 与
#     `/api/rooms*`，那两条有范围细闸）。
#   ⇒ 所以"只覆盖 c006 的普通人也能看到全部建筑轮廓"是我们**选的**，不是漏的。
#     反过来说：哪天往 `viewdata` 里加"点一下弹出这栋楼的用途"，这条口径就作废了
#     —— 那时必须逐栋过滤，而这句注释就是那个信号。
#   ★ `/campus/hole/{name}` 的 `name` 是**裁切文件名**，不是楼号（数据层
#     `blocks[].crop` 里查得到才服务）—— 所以它这条**不许**用 `scope_param="name"`：
#     拿文件名当空间树节点，结果是一会儿全拒一会儿全放，取决于文件名长得像不像楼号。
router = APIRouter(tags=["campus"], dependencies=[Depends(require_cap("view"))])

VIEWDATA_NAME = "campus_terrain_viewdata.json"
GLB_NAME = "campus_terrain.glb"
# ── 建筑层（派生物，与上面两份交付件**并排**放在同一个目录里）──────────────
# ★ 为什么是**两个文件、三条路由**而不是往地形 GLB 里塞：
#   `campus_terrain.glb` 是**交付件**（真 DTM + 真正射，只读、不许再生成）；
#   建筑层是**派生物**（渠东 1:500 实测轮廓 × 实测屋顶高挤出来的体块）。
#   两者的来源、判据版本、更新节奏都不同。混进一个 GLB 之后，
#   "这份文件变了"就再也分不出是地形换了还是楼换了（本仓见 `criterion_version`
#   与 `viewdata_version` 必须分开印的同一条理由：两把尺子合成一个数就失去分辨力）。
BUILDINGS_GLB_NAME = "campus_buildings.glb"
BUILDINGS_JSON_NAME = "campus_buildings_viewdata.json"

# ── 纵览驾驶舱用得到的三份（2026-10-01）──────────────────────────────────
# ★ `campus_ortho.jpg` 是**从 `campus_terrain.glb` 的材质里原样取出来的**那一张
#   （`export_ortho_image.py`：真图 1021719 字节 = GLB 内 bufferView 去掉 1 字节
#   对齐补位）。之所以是"取出来"而不是"重新降采样一份原始正射"：重采样得到的是
#   **另一张图**，二维底图与三维场景会差几个像素，而屏幕两边看上去都"在"。
#   取出来则让二维底图和三维场景**按构造**是同一张影像。
#   旁边的 `campus_ortho.json` 记着它的来源指纹与 ENU→像素的换算式（含方向凭据），
#   前端读那一份就够，不必自己再推一次（抄一次就有两个来源，见铁律 018）。
ORTHO_IMG_NAME = "campus_ortho.jpg"
ORTHO_SIDECAR_NAME = "campus_ortho.json"
# ★ 体块层：213 个 LOD1 体块（`poly_en` 是**绝对** EPSG:4544），高度 = 实测
#   DSM(0.25 m) − DTM(1.6 m)。与上面 341 条的 `buildings` 层**不是同一份东西**：
#   那一份只有 `ring` 没有坐标（几何在 GLB 里），这一份带坐标、能被前端直接建面。
LOD1_NAME = "campus_lod1_blocks.json"
# ★ 轮廓侧车（2026-10-01 新建）：341 条**真建筑轮廓**，带坐标。
#
#   为什么要有它：上面那条 `lod1` 是 DSM − DTM 挤出来的派生物 —— 实测它的中位底面积
#   131 m²、中位高 4.2 m，小块的压在马路/绿化带/转盘/工地上，**不是楼的轮廓**
#   （只有约 13 个 663~2450 m²、12~72 m 的大块真的描在楼上）。本页一度拿它当"建筑轮廓"
#   画在屏幕上，而屏幕上的判词写着"轮廓压在楼上" —— **判词与数据不符**。
#
#   这一份是从**生成 `campus_buildings.glb` 的同一份输入**（渠东 1:500 的
#   `shape_jmd.npz`）把有序外环取回来、按 viewdata 的 `ring` 号逐栋对上生成的
#   （`build_outlines_json.py`）。四条判据全过：341/341 环解析到、逐栋 shoelace 面积
#   与 viewdata 逐位相符、包围盒与**已交付 GLB** 的 POSITION 差 0.0004 m、绕向统一成 CCW。
#   ⇒ 它画的楼与三维场景里的楼**按构造是同一批**。
#
#   ★ 它**只覆盖渠东那一片**（bbox 见文件内的 `bbox_en`，1392 × 1644 m）。
#     实测：六教 / 理工宾馆 / 八教 / 综合实验楼这四栋都在 bbox 之内，但
#     **一条轮廓都没有**（最近的一条分别距 122 / 65 / 90 / 87 m）。这不是坐标错位 ——
#     是那张 1:500 图本身没画这几栋。**屏幕上必须带这一句**，否则读的人会以为
#     "图上没轮廓 = 那里没有房子"。
OUTLINES_NAME = "campus_outlines.json"

# 只放这几种出去。**不放 .py** —— 那个目录里躺着构建器与探针的源码
# （同 `serve_campus_view.py:33-36` 的取舍；那条面退役时这条要接着守）。
_ALLOWED_EXT = {".json", ".glb", ".png"}


def _here(cfg: SettingsDep, name: str):
    """目录里的一个文件 → FileResponse；不在就 404，**并把找过的目录报出来**。

    ★ 「目录不在本机」与「目录在、文件没有」是两个不同的 404，理由不同、
      补救办法也不同（一个是产物没跟着部署，一个是产物被挪走了）。
      只回一句"没有"会让这两种情况在屏幕上长得一模一样（铁律 16）。
    """
    d = cfg.resolved_campus_dir
    if not d.is_dir():
        raise not_found("地形产物目录不在本机", dir=str(d),
                        hint="部件在服务器上吗？要用它就把 GYM3D_CAMPUS_DIR 指到产物所在地")
    path = d / name
    if not path.is_file():
        raise not_found("地形产物目录里没有这个文件", dir=str(d), name=name)
    return path


@router.get("/campus/viewdata")
def campus_viewdata(cfg: SettingsDep) -> FileResponse:
    """数据层（v2）：尺寸/网格/顶点口径的高程/洞格清单/交付件指纹。

    这一份是**消费端唯一被允许拿高程的地方**：交付件 POSITION 的 `min.y = 0`
    是哨兵（构建器 `nan_to_num(verts, nan=0.0)` 把每个 NoData 顶点写在了 y=0），
    真地面在 449.5~500.8 m。谁拿包围盒当地面，谁就把相机和探针放到地面以下 463 m。
    """
    return FileResponse(str(_here(cfg, VIEWDATA_NAME)), media_type="application/json")


@router.get("/campus/model.glb")
def campus_model(cfg: SettingsDep) -> FileResponse:
    """交付件：一份自含贴图的 GLB（正射已烘进材质，无外部依赖）。

    Starlette 默认带 etag/last-modified ⇒ 8 MB 的体量在重复访问时走 304。
    前端**另有一次真正的一致性核对**：拿回来的字节数要比对数据层记的
    `glb.bytes`，不符就报错而不是照画 —— 数据层那句是**记录**，不是**复测**。
    """
    return FileResponse(str(_here(cfg, GLB_NAME)), media_type="model/gltf-binary")


@router.get("/campus/buildings.glb")
def campus_buildings_model(cfg: SettingsDep) -> FileResponse:
    """建筑层：渠东 1:500 实测地形图上的建筑轮廓 × 实测屋顶高（nDSM = DSM − DTM）。

    ★ 与 `campus_terrain.glb` **共用同一个 ENU 系**：顶点 = `(E-e0, 高程, n1-N)`。
      但 `e0` / `n1` **不写死在这条路由里** —— 它们是数据层里的数，消费端从
      `campus_buildings_viewdata.json` 现读。写死就会在两份产物各自换版本那天
      静默错位，而屏幕上只是"楼整体偏了一点"，看不出是坐标系的事。

    ★ 这一层**没有高程估出来的东西**：轮廓是实测画的，高度是实测的差值。
      所以它敢报"这栋多高"，而任何形状推测都不许冒充这句话。

    文件不在就 404 并把目录报出来（`_here` 的两级 404）——
    **这一层还没建出来**与**这一层是空的**必须在屏幕上分得开（铁律 16）。
    """
    return FileResponse(str(_here(cfg, BUILDINGS_GLB_NAME)), media_type="model/gltf-binary")


@router.get("/campus/buildings.json")
def campus_buildings_viewdata(cfg: SettingsDep) -> FileResponse:
    """建筑层的数据层：每栋的实测高度/轮廓/底面积、色阶、以及它**自己**的判据版本。

    走 `FileResponse` 而不是 `json.loads` + `ok(...)` 的理由与 `/campus/viewdata`
    逐条相同：信封会重新序列化，浮点写法会变，发出去的字节就不再是盘上那一份。
    而且建筑层里的坐标是要**跟地形对齐**的，被重新表达一次就等于换了个基准。
    """
    return FileResponse(str(_here(cfg, BUILDINGS_JSON_NAME)), media_type="application/json")


@router.get("/campus/ortho.jpg")
def campus_ortho_image(cfg: SettingsDep) -> FileResponse:
    """纵览底图：校区正射影像（0.8 m/px，2562×2538，与三维场景同一张）。

    ★ 这条路由的键是**常量**，路径完全由服务端算出来 —— 与 `/campus/hole/{name}`
      那条带参数的**不是一类**。所以它不经过 `_ALLOWED_EXT`：那个名单守的是
      "请求方递进来的名字"，而这里根本没有请求方给的名字。
      （这也是为什么 `.jpg` **没有**被加进 `_ALLOWED_EXT` —— 加进去等于给
      `hole` 那条参数化的路由开了一个新扩展名，那不是这里想做的事。）
    """
    return FileResponse(str(_here(cfg, ORTHO_IMG_NAME)), media_type="image/jpeg")


@router.get("/campus/ortho.json")
def campus_ortho_sidecar(cfg: SettingsDep) -> FileResponse:
    """底图的侧车：来源指纹（GLB/图各一个 sha256[:12]）、帧、m/px、
    `col=(E-e0)/m_per_px, row=(n1-N)/m_per_px`（原点在**西北**）以及**方向凭据**。

    走 `FileResponse` 的理由与其余几条逐条相同：这份 JSON 里的坐标是要跟三维
    对齐的，被信封重新序列化一次就等于换了个基准。
    """
    return FileResponse(str(_here(cfg, ORTHO_SIDECAR_NAME)), media_type="application/json")


@router.get("/campus/lod1.json")
def campus_lod1(cfg: SettingsDep) -> FileResponse:
    """体块层：213 个 LOD1 体块，每个带 `poly_en`（绝对 EPSG:4544 的 [E,N] 数组）、
    实测高度 `h_roof_m`、底面积与质心。

    ★ 这一层是**派生物**（DSM − DTM 挤出来的体块），不是实测轮廓图上的建筑。
      它敢报"这块多高"，但**不许**被当成"这是几号楼" —— 体块与楼栋之间目前
      没有任何在盘上成立的对应关系（人工锚点是后来的事）。

    ★★ 而且它**连"是不是一栋楼"都答不了**（2026-10-01 实测）：中位底面积 131 m²、
      中位高 4.2 m，最小的那批压在马路 / 绿化带 / 转盘 / 工地围挡上。要画建筑轮廓
      请用 `/campus/outlines.json`。这一条留着是因为**别的消费端可能还在用它报"高度"**
      （高度那一半是真的），不是因为它能当轮廓。
    """
    return FileResponse(str(_here(cfg, LOD1_NAME)), media_type="application/json")


@router.get("/campus/outlines.json")
def campus_outlines(cfg: SettingsDep) -> FileResponse:
    """建筑轮廓侧车：341 条**真楼轮廓**（`poly_en` 是绝对 EPSG:4544），
    逐条带实测底面积、屋顶高、高度口径、地面中位高程、是否落在 NoData 洞上。

    ★ 与 `/campus/buildings.json`（viewdata）同源：那份有**数**没有**坐标**
      （几何在 GLB 里，整块 mesh 拾取不到逐栋），这一份有坐标。两者按 `ring` 号一一对应。

    ★ 与 `/campus/lod1.json` **不是同一样东西**：那一份是 DSM − DTM 派生物块，
      这一份是 1:500 图上描的实测轮廓。**两者都叫"块"，但只有这一份是楼。**

    ★ 覆盖范围是**局部**的（渠东那一片，1392 × 1644 m）。图外的楼这一份里没有 ——
      这是原图的覆盖，不是本层的缺陷。前端必须把这句话印在屏幕上。

    走 `FileResponse` 的理由与其余几条逐条相同：这份 JSON 里的坐标是要跟三维
    对齐的，被信封重新序列化一次就等于换了个基准。
    """
    return FileResponse(str(_here(cfg, OUTLINES_NAME)), media_type="application/json")


@router.get("/campus/hole/{name}")
def campus_hole(name: str, cfg: SettingsDep) -> FileResponse:
    """洞底截图（"这块 NoData 底下盖着什么"的实物照）。

    ★ 键必须在数据层的 `blocks[].crop` 里查到条目 —— 路径是从**条目**里出来的，
      不是从请求里。名单现读现算，不缓存：数据层换了洞、截图也就跟着换，
      缓存会让"名单已经变了而这一条还在放行旧的"悄悄发生。
    """
    d = cfg.resolved_campus_dir
    vd = _here(cfg, VIEWDATA_NAME)
    try:
        man = json.loads(vd.read_bytes().decode("utf-8"))
    except (OSError, ValueError) as e:
        # 数据层在盘上但读不出来：这是**我们这边**的产物坏了，不是调用方给错了键。
        # 所以不能用 404（那会把矛头指向请求方），用 503 并说清是数据层的问题。
        # 与上面 `_serve` 那条 404/409 不许合并是同一个道理（铁律 29：谁的错只有一处出处）。
        raise ApiError(503, ERR_UPSTREAM,
                       "数据层读不出来，这一屏的洞层与高程都不可信",
                       {"file": VIEWDATA_NAME, "err": type(e).__name__}) from e

    allowed = [b.get("crop") for b in (man.get("interior_holes", {}).get("blocks") or [])]
    allowed = [c for c in allowed if isinstance(c, str)]
    if name not in allowed:
        raise not_found("数据层的洞清单里没有这张截图", name=name, allowed=allowed)

    # 纵深防御：上面那条名单是真正的边界；这一条只是保证「即使名单将来被写脏，
    # 也不会有一个带分隔符的名字走到 d / name 上」。
    if name != name.replace("\\", "/").split("/")[-1] or ":" in name or ".." in name:
        raise not_found("名字里有路径分隔符", name=name)

    path = d / name
    if path.suffix.lower() not in _ALLOWED_EXT:
        raise not_found("这个扩展名不在这条面的名单里", name=name)
    if not path.is_file():
        raise not_found("数据层点了名，但盘上没有这个文件", dir=str(d), name=name)
    return FileResponse(str(path), media_type="image/png")
