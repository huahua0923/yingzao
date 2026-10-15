# -*- coding: utf-8 -*-
"""判据 J-10.8-01 —— **参照件**三维白模（出口门：拉伸出来的件必须**从网格量**得对，不是照抄声明）。

★ 本判据只管 `rebuild/05_build/c006_white.*` 这份**参照件**（`build.json` 里 `"role":"reference"`，
2026-10-13 用户裁定：Python 件的身份是**对照物/尺子**，不是正式交付件）。
**正式件**（用户在 SketchUp 里建的，放 `rebuild/06_su/`）**另立 `J-10.8-02`** —— 且**不共用这把尺子**：
本判据的参照物来自本仓自己的 `build.json`，拿它去量正式件就是同源盲区（铁律 137/187/192）。

判据（§10.8「从平面到三维」）：
  ① 件存在且能被**独立读回**（trimesh.load(GLB) 成功）；
  ② **总高**：从**文件**量得的 **Y 上界** ≈ `top_m` + 顶部附属（女儿墙/楼梯房）—— 参照在件之外，
     专抓「单位写反/缩放错」；②b 另查 `z_max_main_m`（不含附属）≈ `top_m` **+ 梯栏杆高**
     （栏杆长在梯段上、高出到达层完成面 ⇒ **那 0.9 m 是声明漏了，不是件错**）；
  ③ **逐层 z 区间**：网格实测 z 区间 ≈ 声明的 `[z0, z0+h+栏杆高]`，**且**越层只许
     `stair` 一类越、越出的量必须等于参数表 `楼梯/栏杆高_白模`、其余每类都必须落在
     `[z0, z0+h]` 内（口径见下方「③ 的口径」，2026-10-15 收口）；
  ④ **墙足迹面积**：每层矢量墙面积 vs 识别栅格墙面积，相对差 ≤ 25%；
  ⑤ **水密**：每层墙网格 watertight=True；
  ⑥ **楼板**：每层必须有楼板（n_slab ≥ 1）且楼板面积 > 墙面积（板 ⊃ 墙带）；
  ⑦ **门扇**：每层门扇块数 ≥ 1（有门块的楼层；块本身来自源件 `$DorLib2D$`）；
  ⑧ **顶部附属**：声明了附属高 ⇒ 女儿墙环带 ≥ 1 且顶楼楼梯房 ≥ 1（件真进了场景）；
  ⑨ **竖井**（新增）：每层井壁环带 ≥ 1、井道内空 ≥ 1、内空面积 > 0（井道**贯穿楼板**，
     不是实心块）；且**守恒**：`A_wall + A_void ≈ A_wall_uncarved`（抠洞前那一块整块都是墙，
     实测在墙带内占比 1.00 ⇒ 抠掉的只能是内空那一份）；
  ⑩ **7→8 台阶屋面**（新增）：声明了 `roof_step7_m2` ⇒ 件数 ≥ 1，且该面积 ≈
     `A_slab(7层) − A_slab(8层)`（两个数独立记录，互为参照）；
  ⑪ **窗 = 无 的反证**（新增）：件里声明「源件无窗图层」⇒ 现读 12 层源件图层名，
     出现含「窗/WINDOW/GLAZ」的图层即红（= 那句声明过期了）。
  ⑫ **出件朝向 = Y 朝上**（新增，2026-10-13）：glTF 规范是 **+Y 朝上**。本判据**不**用
     trimesh 量朝向 —— trimesh 就是**写出这个文件的那个人**，它读写同一套内部坐标，
     它「读得回」永远为真 ⇒ 它看不见自己的朝向错。改用**两个只认文件格式的读者**：
     ① `glb`：字节层解析 GLB 的 JSON chunk，**从 `scenes[].nodes` 往下走节点树、累积
        `matrix`**，再把 `meshes[].primitives[].attributes.POSITION` 指到的 accessor 的
        `min/max` 那 8 个角点变换过去 —— 文件里的朝向 = **顶点 × 节点矩阵**，两样都要读；
     ② `obj`：纯文本读 `v x y z` 行（trimesh 的 OBJ 导出把旋转**烘进顶点**，与 GLB 走的是
        两条完全不同的路径 ⇒ 互为独立尺子）。**两份都必须 Y 朝上**，任一份没量到也判红。
     判法：高度必须落在 **Y** 上（三轴里 Y 的尺寸最小）。
③ 的口径（2026-10-15 收口，**不是放松阈值**）：`TOL_Z` 仍 0.05 m。改成三件事 ——
  · 声明侧补全：本层合法的上界是 `z0 + h + 栏杆高`（栏杆长在梯段上、越过到达层完成面）；
  · 越出量**取自参数表** `构件/楼梯/栏杆高_白模`（**直接读 `rebuild/构件库/参数.json`**，
    不从 `build.json` 转手拿 —— 与 `z_extra_m` 构成两个独立读数）；参数表读不到 / 单位不是 mm
    ⇒ 判红（**不退回裸 `z0+h` 当绿**）；
  · 越层**只许 `stair` 一类**：`z_extra_by` 必须是 `stair`，且 `z_by_class` 里除 `stair` 外
    **每一类**都必须落在 `[z0, z0+h]` 内。★ 最后这条是关键 —— 光看聚合的 `z_extra_by`，
    墙和梯一起冒头时它照样印 `stair`（C17/C18 就是给这两条配的正对照）。
量具（写明）：`rebuild/tools/build3d.py` 产出的 `build.json` + **字节层**读回 `c006_white.glb`
  （struct+json 解析 glTF JSON chunk + 节点树矩阵，**不经 trimesh**）+ 纯文本读 `c006_white.obj`
  （见 ②/⑫）+ ⑪ 现读 `rebuild/01_cad/raw/*.dxf` 的图层名（ezdxf）+ ②b/③ 现读
  `rebuild/构件库/参数.json` 的 `构件/楼梯/栏杆高_白模`；单位 = 违反条数；阈值 = 0。
量具盲区（声明）：
  · **⑫ 的「Y 是最小轴」这条**只在「平面跨度 > 建筑高」时才有分辨力（本栋 129×84 m
    平面 vs 45 m 高（−3.5 … 41.5）⇒ 成立）。换成平面比高度还小的瘦高建筑，这条要另写。
  · ③ 的「越层只许 stair」把 `stair` 整个类当**一个**主体看：只要楼梯这一类里**任何一块**
    （梯段/平台/栏杆）冒到 `z0+h` 以上就都算在 `stair` 头上。今天实测只有栏杆冒 0.9 m；
    **不分辨**是栏杆冒的还是梯段本身冒的（要分辨得再细分到 `stair_rail` 这类子标签）。
  · ③ 引用的 `栏杆高_白模` 在参数表里标的是 **「假设」不是「规范」**（900 mm，区间 850–1100）。
    判据只核「件与这个假设值一致」，**不核这个假设值本身对不对**。
  · ⑫ 的 glb 读的是 `accessors.min/max`（规范要求 POSITION 必须给）**+ 节点 `matrix`**。
    导出器若不给 min/max、或改用 TRS（`rotation/translation/scale`）、或把旋转写进**蒙皮**，
    读者量不到 ⇒ `None` ⇒ 判红并写明「没量到」，**不静默当绿**。
  · ⑫ 只判**轴朝向**，不判**左右手/绕竖轴的转向**（转 180°、或 X/Y 互换成水平镜像，照样过）。
  · 量**墙 + 柱 + 楼板 + 门扇 + 楼梯 + 竖井井壁 + 台阶屋面 + 女儿墙 + 顶楼楼梯房**九样。
    **仍未入**：一楼入口独立雨篷（源件与 2024 影像都查过、判定不存在 ⇒ 不是漏建）；
    **窗**只由 ⑪ 反证「图层里没有」，**不查**窗是否画在墙层上（若画在 `4.2墙体` 里，⑪ 全盲）。
  · 面积比的是**矢量足迹**（mm²/1e6）vs **栅格口径**识别面积 —— 两把尺子系统性不同源，
    故给 25% 宽容差，不追求相等（相等反而说明有一处是抄的）。
  · **楼板是推导量**：由墙带闭运算桥洞口后填洞取外轮廓（源图无板）⇒ 内天井/中庭会被当成楼面；
    判据只查「有板且 ≥ 墙面积」，**不查板轮廓对不对**（没有独立参照）。
  · **门扇高 2.1 / 楼梯踏高 / 井壁厚 150 / 女儿墙 / 楼梯房** 是**假设值**（源图只有平面）
    ⇒ 判据只查「块数 ≥ 1」与守恒式，不查这些尺寸。
  · 只认 z 轴高度与 XY 足迹；对**朝向/曲面/洞口位置**不判。
正对照（必配，每一条都必须按预期变红）：
  · C1 真件 ⇒ **放行**（各层 z 实测 = 声明 + 梯栏杆那一份、越层只 stair、墙面积对得上、
    每层有板有门有井、全水密）；
  · C2 **单位写反**（把每层 z 实测乘 0.001，= 复现本会话真踩过的「mm 拉伸后再缩」煎饼坑）
    ⇒ **必红**（网格总高 0.047 m ≠ `top_m` + 附属；**跟着参数表走**，不再写死 47.0 m）；
  · C3 少一层（抹掉 11层、z_max 降到 40）⇒ **必红**；
  · C4 某层墙面积改成识别值的 1.5 倍 ⇒ **必红**；
  · C5 空件（无楼层）⇒ **必红**；
  · C6 某层楼板面积清零 ⇒ **必红**（板判据有分辨力）；
  · C7 某层楼板面积改成小于墙面积 ⇒ **必红**；
  · C8 女儿墙件数清零（声明了附属却没入场景）⇒ **必红**；
  · C9 把某层 `A_wall_uncarved_m2` 改成 `A_wall_m2`（假装没井）⇒ **必红**（守恒式有分辨力）；
  · C10 某层井壁件数清零 ⇒ **必红**；
  · C11 `roof_step7` 件数清零 ⇒ **必红**；
  · C12 `roof_step7_m2` 改成 slab(7)−slab(8) 的 2 倍 ⇒ **必红**；
  · C13 往源件图层里塞一个 `4.9窗户`（**当场写临时副本**，不动原件）⇒ **必红**（⑪ 有分辨力）；
  · C14 把 y/z 对调（= 复现 2026-10-13 修前那份「高度写在 Z 上」的件）⇒ **必红**（⑫ 有分辨力）。
    注意 C14 **不是**把两个 min/max 直接对调就完事：修前那份的 y 是**进深** 84 m（不是高度），
    对调后 ② 看到 y 上界 84 ≠ 声明总高、⑫ 看到 Y 不再是三轴最小 ⇒ 两条都该红。
  · C15 只把 **glb** 那份写成 Z 朝上（obj 不动）⇒ **必红**（证明两份尺子**各自**有声：
    只看一份的判据会被「另一份恰好对」蒙过去）。
  · C16 两份 bbox 都置 `None`（模拟导出器不给 min/max / 文件读不出）⇒ **必红**
    （「没量到」不许静默当绿）。
  · C17 某层 `z_extra_by` 改说 `wall`（= 复现「墙偷偷高了 0.9 m」冒充栏杆）⇒ **必红**（③ⓑ）；
  · C18 某层**墙**那一类的 z 顶也抬到 `z0+h+栏杆高`，而 `z_measured`/`z_extra_m`/`z_extra_by`
    **一个都不动**（全还是「stair 越 0.9」）⇒ **必红**（③ⓒ 是关键：只看聚合读数会静默绿）；
  · C19 某层 `z_extra_m` 谎报 1.05（与参数表那个数对不上，`z_measured` 照旧）⇒ **必红**（③ⓐ）；
  · C20 某层**把梯栏杆整条丢掉**（z 顶退回 `z0+h`、越层量 0、致因 None、stair 也不再冒头）
    ⇒ **必红**（★ 这条保证 ③ 改口径**只**给「栏杆按设计越层」开口子，没变成「z 多少都行」）。
  二十条里**任一条不按预期** ⇒ 判据没分辨力，作废。
三态：OK / FAIL / SKIP（件或 build.json 不在 · 跑不动）。SKIP 不算过、也不假报成 FAIL。
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import struct
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

OUT = r"D:\项目\cdut3d\rebuild\05_build"
RAW = r"D:\项目\cdut3d\rebuild\01_cad\raw"
GLB = os.path.join(OUT, "c006_white.glb")
OBJ = os.path.join(OUT, "c006_white.obj")
META = os.path.join(OUT, "build.json")
# ★ 参数表：③ 的参照物。**必须直接读它**，不许从 build.json 里转手拿
#   （两个估计器不能同源，铁律 018/174/192）。
PARAMS = r"D:\项目\cdut3d\rebuild\构件库\参数.json"
RUNDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
JSONOUT = os.path.join(RUNDIR, "J-10.8-01.json")   # ★ 台账页要的三路读数之一（见 _dump）
_LOG = []
_STATE = {}   # ★ 本闸**实测**到的读数（就地赋值、不重算、不编数），供落 json

# ★ 盲区（逐字抄本文件 docstring「量具盲区（声明）」那一节，不许在这里新增或编造）
BLIND = [
    "⑫「Y 是最小轴」只在「平面跨度 > 建筑高」时有分辨力（本栋 129×84 m 平面 vs 45 m 高（−3.5 … 41.5））；瘦高建筑要另写",
    "⑫ 的 glb 读 accessors.min/max + 节点 matrix；导出器不给 min/max / 改用 TRS / 把旋转写进蒙皮 ⇒ 量不到 ⇒ 判红，不当绿",
    "⑫ 只判轴朝向，不判左右手/绕竖轴转向（转 180°、或 X/Y 互换水平镜像，照样过）",
    "③ 的「越层只许 stair」把 stair 整个类当一个主体看：楼梯里任一块（梯段/平台/栏杆）冒到 z0+h 以上都算在 stair 头上；不分辨是栏杆冒的还是梯段本身冒的（要分辨得再细分到 stair_rail 这类子标签）",
    "③ 引用的 栏杆高_白模 在参数表里标的是「假设」不是「规范」（900 mm，区间 850–1100）；判据只核件与这个假设值一致，不核这个假设值本身对不对",
    "量墙/柱/楼板/门扇/楼梯/竖井井壁/台阶屋面/女儿墙/顶楼楼梯房九样；一楼入口雨篷未入；窗只由 ⑪ 反证图层，不查窗是否画在墙层上",
    "面积比的是矢量足迹 vs 栅格口径识别面积，两把尺子系统性不同源 ⇒ 给 25% 宽容差，不追求相等",
    "楼板是推导量（墙带闭运算桥洞口后填洞取外轮廓），内天井/中庭会被当成楼面；只查「有板且 ≥ 墙面积」，不查板轮廓",
    "门扇高 2.1 / 楼梯踏高 / 井壁厚 150 / 女儿墙 / 楼梯房 是假设值 ⇒ 只查块数 ≥ 1 与守恒式，不查尺寸",
    "只认 z 轴高度与 XY 足迹；对朝向/曲面/洞口位置不判",
]

TOL_Z = 0.05        # m
TOL_AREA = 0.25     # 相对
TOL_CONS = 0.5      # m²：抠洞守恒式
TOL_ROOF = 0.02     # 相对：台阶屋面 vs 两板之差
WIN_HINT = ("窗", "WINDOW", "GLAZ", "WIND_")


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


def _mat4(a):
    """glTF 的 `matrix` 是**列主序** 16 个数 → 返回行主序 4×4（numpy）。"""
    import numpy as _np
    return _np.array(a, dtype=float).reshape(4, 4).T


def wire_bbox(glb=GLB):
    """**字节层**读 GLB，返回**世界坐标**（= 规范读者看到的）bbox `(x0,x1,y0,y1,z0,z1)`。

    只认 glTF 规范：从 `scenes[].nodes` 往下走节点树，**把每个节点的 `matrix` 累积**，
    再把 `meshes[].primitives[].attributes.POSITION` 指到的 accessor 的 `min/max`
    那 8 个角点变换过去求并集。
    ★ 第一版**漏了节点矩阵**：trimesh 的 `Scene.apply_transform` 是把旋转写进**节点的 matrix**
      （顶点数据一个字节没动），于是第一版读到的是**未旋转的局部坐标** ⇒ 明明已经修好了，
      判据却报「不是 Y 朝上」。**文件里的朝向 = 顶点 × 节点矩阵**，两样都要读。
    ★ 为什么不用 trimesh：trimesh 就是**写出这个件的人**，它读回的是自己的内部坐标，
      「读得回」恒真 ⇒ 它看不见自己的朝向错（同源参照物）。
    读不到 ⇒ 返回 **None**（不许静默当绿）：无 glTF 头 / 解析失败 / 走了 TRS 节点（本件没有，
    真出现就是本尺子量不了）/ 有 POSITION 却**没给 min/max**（规范要求必须给）。
    """
    try:
        import numpy as np
        with open(glb, "rb") as f:
            b = f.read()
        if b[:4] != b"glTF":
            return None
        ln = struct.unpack("<I", b[12:16])[0]           # JSON chunk 长度
        j = json.loads(b[20:20 + ln].decode("utf-8"))
        acc, nodes = j.get("accessors") or [], j.get("nodes") or []
        sc = (j.get("scenes") or [{}])[j.get("scene", 0)] or {}
        roots = sc.get("nodes") or list(range(len(nodes)))
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        n = [0]

        def walk(idx, M, depth=0):
            if depth > 64:
                raise ValueError("节点树太深/有环")
            nd = nodes[idx]
            if any(k in nd for k in ("rotation", "translation", "scale")):
                raise ValueError("TRS 节点：本尺子只认 matrix")
            if nd.get("matrix"):
                M = M @ _mat4(nd["matrix"])
            mi = nd.get("mesh")
            if mi is not None:
                for prim in (j["meshes"][mi].get("primitives") or []):
                    ai = (prim.get("attributes") or {}).get("POSITION")
                    if ai is None or not (0 <= ai < len(acc)):
                        continue
                    mn, mx = acc[ai].get("min"), acc[ai].get("max")
                    if not mn or not mx or len(mn) < 3 or len(mx) < 3:
                        raise ValueError("POSITION 未给 min/max")
                    c = np.array([[mx[0] if i & 1 else mn[0],
                                   mx[1] if i & 2 else mn[1],
                                   mx[2] if i & 4 else mn[2]] for i in range(8)])
                    w = c @ M[:3, :3].T + M[:3, 3]
                    for i in range(3):
                        lo[i] = min(lo[i], float(w[:, i].min()))
                        hi[i] = max(hi[i], float(w[:, i].max()))
                    n[0] += 1
            for ch in (nd.get("children") or []):
                walk(ch, M, depth + 1)

        for r in roots:
            walk(r, np.eye(4))
        return None if n[0] == 0 else (lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])
    except Exception:
        return None


def obj_bbox(obj):
    """**纯文本**读 OBJ 的 `v x y z` 行求 bbox（零依赖、零坐标变换的第二个读者）。

    OBJ 没有正式上轴，但 SU / Blender 的默认导入是 Y-up ⇒ 这里量的是「导入后是不是正的」。
    读不到（没有 v 行 / 打不开）⇒ None。
    """
    try:
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        n = 0
        with open(obj, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.startswith("v "):
                    continue
                p = line.split()
                if len(p) < 4:
                    continue
                for i in range(3):
                    v = float(p[1 + i])
                    lo[i] = min(lo[i], v)
                    hi[i] = max(hi[i], v)
                n += 1
        return None if n == 0 else (lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])
    except Exception:
        return None


_RAIL = []   # 记忆：一趟只读一次参数表


def rail_m():
    """★ **独立读数**：从参数表读梯栏杆高，返回 m（读不到 / 单位不是 mm ⇒ None）。

    为什么必须从参数表读：`build.json` 的 `z_extra_m` 说「本层上界比声明高了 0.9」，
    参数表说「栏杆高 900 mm」—— 这是**两个文件里的两个数**，且各自独立记录。
    若把它换成「从 `z_measured` 现算」，那就成了拿一个估计器去核它自己：恒真（铁律 018/174）。
    读不到 ⇒ None ⇒ 判据按「没量到」判红，**不静默当绿**（铁律 199）。
    """
    if not _RAIL:
        try:
            with open(PARAMS, encoding="utf-8") as f:
                p = json.load(f)
            v = p["构件"]["楼梯"]["栏杆高_白模"]
            if v.get("单位") != "mm":
                log("  ★ 参数表 栏杆高_白模 的单位是 %r（不是 mm）⇒ 越层那一份无从核" % (v.get("单位"),))
                _RAIL.append(None)
            else:
                _RAIL.append(round(float(v["值"]) / 1000.0, 6))
        except Exception as e:
            log("  ★ 参数表读不到（%s）：%r ⇒ 越层那一份无从核" % (PARAMS, e))
            _RAIL.append(None)
    return _RAIL[0]


def judge(m, boxes, raw=RAW):
    """返回违反串列表（空 = 合格）。

    `boxes` = `{"glb": bbox6 或 None, "obj": bbox6 或 None}` —— **两份不同的尺子**量同一个件：
    `glb` 走 glTF 节点树（顶点 × 矩阵），`obj` 是纯文本 v 行。两者都要**Y 朝上**。
    ★ 高度取 **Y**（glTF 规范 +Y 朝上），不是 z —— 这是 2026-10-13 那处朝向坑的落点。
    """
    fails = []
    boxes = boxes or {}
    wb = boxes.get("glb")
    hb = None if wb is None else (wb[2], wb[3])          # 高度在 Y
    # ② 总高：文件 Y 上界 = 主体顶参数 + 顶部附属（女儿墙/楼梯房）——参照在件之外
    att = m.get("attach", {}) or {}
    att_h = max([float(att.get(k, 0.0)) for k in ("parapet_m", "roof_stair_m")] or [0.0])
    exp_tot = m["top_m"] + att_h
    if hb is None or abs(hb[1] - exp_tot) > TOL_Z:
        fails.append("总高：件 Y 上界=%s ≠ top_m+附属=%.1f"
                     % ("None（没量到）" if hb is None else "%.3f" % hb[1], exp_tot))
    # ②b 主体顶（不含附属）vs `top_m` **+ 梯栏杆高**
    # ★ 2026-10-15：栏杆**按设计越过上层楼面**（它长在梯段上、高出到达层的完成面），
    #   所以主体顶的正确声明是 `top_m + 栏杆高`，不是 `top_m`。
    #   栏杆高取自**参数表**（独立读数）；读不到 ⇒ 判红，不退回裸 `top_m` 当绿。
    _rail = rail_m()
    if _rail is None:
        fails.append("主体顶无从核：读不到参数表 `楼梯/栏杆高_白模`")
    elif abs((m.get("z_max_main_m") or 0.0) - (m["top_m"] + _rail)) > TOL_Z:
        fails.append("主体顶 %s ≠ top_m=%.1f + 梯栏杆 %.3f = %.3f"
                     % (m.get("z_max_main_m"), m["top_m"], _rail, m["top_m"] + _rail))
    # ⑫ 出件朝向：高度必须在 **Y** 上（glTF 规范 / SU·Blender 默认导入口径）。与 ② 是两件事：
    #   ② 问「最上面那个 y 对不对」，⑫ 问「y 到底是不是高度轴」。修前那份（高度写在 Z 上）
    #   两条都红；而**用 trimesh 量**时两条都看不见（同源）。
    for lab in ("glb", "obj"):
        bb = boxes.get(lab)
        if bb is None:
            fails.append("⑫ %s：没量到 bbox（读不出/文件不在）⇒ 不许当绿" % lab)
            continue
        ext = (bb[1] - bb[0], bb[3] - bb[2], bb[5] - bb[4])
        if not (ext[1] < ext[0] and ext[1] < ext[2]):
            fails.append("⑫ %s 不是 Y 朝上：三轴尺寸 x=%.1f y=%.1f z=%.1f，高度应在 Y（三轴最小）"
                         % ((lab,) + ext))
    # ③ 逐层 z 区间（2026-10-15 改：**声明补上「越层」那一份，但口子只对梯栏杆开**）
    #    改前：写死 [z0, z0+h] ⇒ 梯栏杆按设计越层 0.9 m 被报成 12 条「件错」，而聚合读数
    #    分不出「栏杆越层」与「墙偷偷高了 0.9 m」—— 两条长得一模一样（铁律 137/158）。
    #    改后**不是放阈值**（TOL_Z 仍 0.05），而是把声明补全 + 加三道约束：
    #      ⓐ 越出量 `z_extra_m` == 参数表 `栏杆高_白模`（两个文件的独立读数，铁律 018/174）
    #      ⓑ 越层致因 `z_extra_by` 必须是 `stair`
    #      ⓒ `z_by_class` 里**除 stair 外每一类**都不得越过 [z0, z0+h] ⇒ 墙/柱/板/井高了照样红
    #    ⓒ 是关键：光看聚合的 `z_extra_by`，墙和梯一起冒头时它照样印 `stair`。
    _r3 = rail_m()
    for r in m["floors"]:
        z0_, h_ = r["z0"], r["h"]
        ztop = z0_ + h_
        zm = r.get("z_measured")
        fl = r["floor"]
        if not zm:
            fails.append("%s 没有 z_measured" % fl)
            continue
        zbc = r.get("z_by_class")
        if zbc is None:
            fails.append("%s 缺 z_by_class（只有聚合 z 读数 ⇒ 分不出「栏杆越层」与「墙偷偷高了」，"
                         "不许当绿）" % fl)
            continue
        if _r3 is None:
            fails.append("%s：读不到参数表 `楼梯/栏杆高_白模` ⇒ 越层那一份无从核" % fl)
            continue
        if abs(zm[0] - z0_) > TOL_Z:
            fails.append("%s z 底 %s ≠ 声明 %.1f" % (fl, zm[0], z0_))
        if abs(zm[1] - (ztop + _r3)) > TOL_Z:
            fails.append("%s z 顶 %s ≠ 声明顶 %.1f + 梯栏杆 %.3f = %.3f"
                         % (fl, zm[1], ztop, _r3, ztop + _r3))
        ex = r.get("z_extra_m")
        if ex is None or abs(ex - _r3) > TOL_Z:
            fails.append("%s z_extra_m=%s ≠ 参数表 栏杆高_白模=%.3f"
                         % (fl, ex, _r3))
        if r.get("z_extra_by") != "stair":
            fails.append("%s 越层致因 z_extra_by=%s（只许 stair）" % (fl, r.get("z_extra_by")))
        for tg, zz in sorted(zbc.items()):
            if tg == "stair" or not zz:
                continue
            if zz[1] > ztop + TOL_Z or zz[0] < z0_ - TOL_Z:
                fails.append("%s 类 %s z=[%s,%s] 越过声明 [%.1f,%.1f]（只有 stair 可以越）"
                             % (fl, tg, zz[0], zz[1], z0_, ztop))
    # ④ 墙足迹面积 vs 识别
    for r in m["floors"]:
        rec = r.get("A_wall_recognized_m2") or 0
        if rec > 0 and abs(r["A_wall_m2"] - rec) / rec > TOL_AREA:
            fails.append("%s 墙面积 %.1f vs 识别 %.1f 相对差>%.0f%%"
                         % (r["floor"], r["A_wall_m2"], rec, TOL_AREA * 100))
    # ⑤ 水密
    for r in m["floors"]:
        if not r.get("watertight_wall"):
            fails.append("%s 墙网格不水密" % r["floor"])
    # ⑥ 楼板：每层有板，且板面积 > 墙面积
    for r in m["floors"]:
        ns = r.get("n_slab", 0) or 0
        asl = r.get("A_slab_m2") or 0
        if ns < 1 or asl <= 0:
            fails.append("%s 无楼板（n_slab=%s, A=%s）" % (r["floor"], ns, asl))
        elif asl <= (r.get("A_wall_m2") or 0):
            fails.append("%s 楼板 %.1f ≤ 墙 %.1f（板应盖住墙带）" % (r["floor"], asl, r.get("A_wall_m2") or 0))
    # ⑦ 门扇：源件有门线的楼层，门扇块数 ≥ 1
    for r in m["floors"]:
        if (r.get("n_door_block") or 0) > 0 and (r.get("n_door_leaf") or 0) < 1:
            fails.append("%s 门扇块数 0（源件有门线却未出扇）" % r["floor"])
    # ⑧ 顶部附属：声明了就得真进场景
    if att_h > 0 and (int(att.get("n_parapet", 0)) < 1 or int(att.get("n_roof_stair", 0)) < 1):
        fails.append("顶部附属声明 %.1f m 但件未入（女儿墙 %s / 楼梯房 %s）"
                     % (att_h, att.get("n_parapet"), att.get("n_roof_stair")))
    # ⑨ 竖井：环带 + 内空都在，且守恒 A_wall + A_void ≈ A_wall_uncarved
    for r in m["floors"]:
        nl = r.get("n_lift", 0) or 0
        nv = r.get("n_lift_void", 0) or 0
        av = r.get("A_lift_void_m2") or 0.0
        if nl < 1 or nv < 1 or av <= 0:
            fails.append("%s 竖井缺失（井壁 %s / 内空 %s / 内空面积 %s）"
                         % (r["floor"], nl, nv, av))
        else:
            u = r.get("A_wall_uncarved_m2")
            if u is None:
                fails.append("%s 缺 A_wall_uncarved_m2（守恒式无从核）" % r["floor"])
            elif abs((r.get("A_wall_m2") or 0.0) + av - u) > TOL_CONS:
                fails.append("%s 抠洞守恒破：墙 %.2f + 空 %.2f ≠ 抠前 %.2f"
                             % (r["floor"], r.get("A_wall_m2") or 0.0, av, u))
    # ⑩ 7→8 台阶屋面：**参照物是「两层楼板之差」**，不是那句声明本身。
    #   ★ 第一版把判据写成 `if 声明了才查` ⇒ 把声明清零就整条跳过、正对照 C11 当场放行。
    #     声明不是一个可以被自己证伪的参照物（铁律 137/192）——改成：板差说这儿有台阶，
    #     件就必须有对应的屋面，且面积要对得上。
    at = m.get("attach", {}) or {}
    ars = float(at.get("roof_step7_m2") or 0.0)
    nrs = int(at.get("n_roof_step7") or 0)
    sl = {r["floor"]: (r.get("A_slab_m2") or 0.0) for r in m["floors"]}
    ref = sl.get("7层", 0.0) - sl.get("8层", 0.0)
    if ref > 1.0:
        if nrs < 1 or ars <= 0:
            fails.append("slab(7)−slab(8)=%.1f m² 说明有台阶，却没有台阶屋面（%d 块/%.1f m²）"
                         % (ref, nrs, ars))
        elif abs(ars - ref) / ref > TOL_ROOF:
            fails.append("台阶屋面 %.1f ≠ slab(7)−slab(8) %.1f（独立两数打架）" % (ars, ref))
    # ⑪ 窗 = 无 的反证：现读源件图层名
    wins = window_layers(raw)
    if wins is None:
        fails.append("⑪ 源件图层读不到（没量到 ⇒ 不许当绿）")
    elif wins:
        fails.append("声明「源件无窗图层」，但源件里有 %s" % wins)
    if not m["floors"]:
        fails.append("空件：无楼层")
    return fails


def window_layers(raw=RAW):
    """现读 12 层源件的图层名，返回含「窗」类字样的图层（无 ⇒ 空表；读不到 ⇒ None）。"""
    try:
        import ezdxf
    except Exception:
        return None
    if not os.path.isdir(raw):
        return None
    names = set()
    nfile = 0
    for fn in os.listdir(raw):
        if not fn.lower().endswith(".dxf"):
            continue
        p = os.path.join(raw, fn)
        try:
            for l in ezdxf.readfile(p).layers:
                names.add(str(l.dxf.name))
            nfile += 1
        except Exception:
            continue
    if nfile == 0:
        return None
    return sorted(n for n in names
                  if any(h in n.upper() for h in WIN_HINT))


def main():
    """★ 唯一出口：所有 `return <rc>` 都经这里 —— 先由 `_run()` 算 rc，再落 json，再返回。

    口径与改前**完全一致**：`_run()` 就是原来的 `main()` 正文，一个判定都没动、rc 也没动；
    这里只是把「落 json」这一步**挂在唯一出口上**（早退的 SKIP 路径也照样落 json）。
    """
    rc = _run()
    _dump(rc)
    return rc


def _dump(rc):
    """★ 为什么落 json：判据台账页 `demo/sys.html`（生成器 `tools/build_sys_page.py`）对每条
    判据取**三路独立读数** —— ① 本 json 的 `pass`、② `run.txt` 的 `rc=`、③ `run.txt` 的判词行。
    本闸原先**只落 run.txt**（`_write()`）⇒ 页上「顶层字段」一节恒空（缺的就是这一路）。
    读数**只用脚本已经算出来的量**（`_STATE`，各处就地赋值），一个都不编；`blind` 抄 docstring
    已声明的盲区。落盘口径照仓内样例 `gates/J-10.2-02_floorshift.py`：utf-8 + ensure_ascii=False。
    """
    cf, ct = _STATE.pop("_ctrl_fired", 0), _STATE.pop("_ctrl_total", 0)
    rec = {"pass": rc == 0, "rc": rc}
    rec.update(_STATE)                       # 本闸实测读数（顺序即赋值顺序）
    rec["controls_fired"] = "%d/%d" % (cf, ct)   # 正对照触发数（本闸的分辨力证据）
    rec["blind"] = BLIND
    os.makedirs(RUNDIR, exist_ok=True)
    with open(JSONOUT, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    print("  写出:", JSONOUT)


def _run():
    if not os.path.exists(META):
        log("SKIP：%s 不在（先跑 rebuild/tools/build3d.py）" % META)
        _write()
        return 4
    m = json.load(open(META, encoding="utf-8"))
    # ★ 就地记读数：这些量本闸本来就要读到，落 json 只是**把它印出来**，不另起炉灶
    _STATE["n_floors"] = len(m["floors"])
    _STATE["top_m"] = m["top_m"]
    _STATE["attach"] = m.get("attach")

    boxes = {"glb": None, "obj": None}
    if os.path.exists(GLB):
        import trimesh
        s = trimesh.load(GLB)            # ① 「件能被读回」——但这把尺子**看不见朝向**（见 ⑫）
        boxes["glb"] = wire_bbox(GLB)    # ★ 朝向用**字节层**读者量（不经 trimesh，且要过节点矩阵）
        boxes["obj"] = obj_bbox(OBJ)     # ★ 第二个读者：纯文本 v 行（trimesh 的 OBJ 导出把旋转写进顶点）
        # ★ 记两把尺子各自量到的 Y 上界（= 高度轴上的实测顶），一个是字节层 glb、一个是纯文本 obj
        _STATE["y_upper_glb"] = None if boxes["glb"] is None else round(boxes["glb"][3], 3)
        _STATE["y_upper_obj"] = None if boxes["obj"] is None else round(boxes["obj"][3], 3)
        for lab in ("glb", "obj"):
            bb = boxes[lab]
            if bb is None:
                log("★ %s：读不到 bbox（路径变了/格式变了）⇒ ⑫ 按「没量到」判红" % lab)
            else:
                log("网格读回：trimesh 读到节点 %d；**文件里**(%s) 三轴尺寸 x=%.3f y=%.3f z=%.3f m"
                    "（规范 +Y 朝上 ⇒ 高度必须是 Y，实测 Y 上界 %.3f）"
                    % (len(s.geometry), lab, bb[1] - bb[0], bb[3] - bb[2], bb[5] - bb[4], bb[3]))
    else:
        log("SKIP：%s 不在" % GLB)
        _write()
        return 4

    wins11 = window_layers(RAW)
    _STATE["window_layers_11"] = wins11        # ★ ⑪ 现读源件图层名的结果（None = 没量到）
    log("⑪ 源件窗图层反证：读到含「窗」字样的图层 = %s"
        "（`[]` = 与「源件无窗」一致；`None` = 没量到 ⇒ 判红，不许当绿）" % (wins11,))

    ok = True
    f1 = judge(m, boxes)
    _STATE["c1_fails"] = len(f1)               # ★ 真件上的违反条数（0 = 放行）
    log("C1 真件：违反 %d 条 ⇒ %s" % (len(f1), "放行" if not f1 else "★红了 " + "; ".join(f1[:3])))
    ok = ok and not f1

    def ctl(name, fn, raw=RAW):
        nonlocal ok
        mm, ww = copy.deepcopy(m), copy.deepcopy(boxes)
        # fn 可改 mm 就地，也可**返回**新的 boxes 字典（文件 bbox 在件侧，不在 mm 里）
        r = fn(mm, ww)
        if isinstance(r, dict):
            ww = r
        fs = judge(mm, ww, raw)
        fired = len(fs) > 0
        # ★ 记正对照触发数（本闸分辨力的证据）：每条正对照都经这里，逐条计数不重算
        _STATE["_ctrl_total"] = _STATE.get("_ctrl_total", 0) + 1
        if fired:
            _STATE["_ctrl_fired"] = _STATE.get("_ctrl_fired", 0) + 1
        ok = ok and fired
        log("  %-22s → %s（违反 %d 条）%s" % (name, "✔红" if fired else "★放行了", len(fs),
                                            "" if not fired else fs[0]))
        return fs

    log("\n---- 正对照（每一条都必须按预期变红）----")

    def c2(mm, ww):
        for r in mm["floors"]:
            r["z_measured"] = [v * 0.001 for v in r["z_measured"]]
        mm["z_max_m"] *= 0.001
        # 复现煎饼（整件缩到 mm 级）
        return {k: (None if v is None else tuple(x * 0.001 for x in v)) for k, v in ww.items()}
    ctl("C2 单位写反(煎饼 47mm)", c2)

    def c3(mm, ww):
        mm["floors"] = [r for r in mm["floors"] if r["floor"] != "11层"]
        mm["z_max_m"] = 40.0
        return {k: (None if v is None else (v[0], v[1], v[2], 40.0, v[4], v[5]))
                for k, v in ww.items()}
    ctl("C3 少一层(11层)", c3)

    def c4(mm, zz):
        for r in mm["floors"]:
            if r["floor"] == "8层":
                r["A_wall_m2"] = round(r["A_wall_recognized_m2"] * 1.5, 2)
    ctl("C4 墙面积×1.5", c4)

    def c5(mm, zz):
        mm["floors"] = []
    ctl("C5 空件", c5)

    def c6(mm, zz):
        for r in mm["floors"]:
            if r["floor"] == "8层":
                r["A_slab_m2"] = 0.0
    ctl("C6 楼板清零", c6)

    def c7(mm, zz):
        for r in mm["floors"]:
            if r["floor"] == "8层":
                r["A_slab_m2"] = round((r["A_wall_m2"] or 1.0) * 0.5, 2)
    ctl("C7 楼板<墙", c7)

    def c8(mm, zz):
        mm["attach"]["n_parapet"] = 0
    ctl("C8 附属未入", c8)

    def c9(mm, zz):
        for r in mm["floors"]:
            if r["floor"] == "8层":
                r["A_wall_uncarved_m2"] = r["A_wall_m2"]        # 假装没抠过井
    ctl("C9 守恒式(假装没井)", c9)

    def c10(mm, zz):
        for r in mm["floors"]:
            if r["floor"] == "8层":
                r["n_lift"] = 0
    ctl("C10 井壁件数清零", c10)

    def c11(mm, zz):
        mm["attach"]["n_roof_step7"] = 0
        mm["attach"]["roof_step7_m2"] = 0.0
    ctl("C11 台阶屋面未入", c11)

    def c12(mm, zz):
        sl = {r["floor"]: r.get("A_slab_m2") or 0.0 for r in mm["floors"]}
        mm["attach"]["roof_step7_m2"] = round((sl["7层"] - sl["8层"]) * 2.0, 2)
    ctl("C12 台阶屋面×2", c12)

    def c14(mm, ww):
        # 复现 2026-10-13 修前那份：高度写在 Z、进深写在 Y（把 y/z 成对换回去）
        return {k: (None if v is None else (v[0], v[1], v[4], v[5], v[2], v[3]))
                for k, v in ww.items()}
    ctl("C14 件写成 Z 朝上", c14)

    def c15(mm, ww):
        # 只有 GLB 那份被写成 Z 朝上（两份尺子必须**各自**有声 —— 单看一份就可能全绿）
        return {k: (None if v is None else
                    ((v[0], v[1], v[4], v[5], v[2], v[3]) if k == "glb" else v))
                for k, v in ww.items()}
    ctl("C15 只有 GLB 写反", c15)

    def c16(mm, ww):
        # 读不到（模拟导出器不给 min/max / 文件缺失）⇒ 必须红，不许静默当绿
        return {k: None for k in ww}
    ctl("C16 bbox 没量到", c16)

    # ---- ③ 的三条新口径，各配一条正对照（2026-10-15 收口）----

    def c17(mm, zz):
        # 越层致因说成 `wall`（=「墙偷偷高了 0.9 m」冒充栏杆），其余读数一个不动
        for r in mm["floors"]:
            if r["floor"] == "8层":
                r["z_extra_by"] = "wall"
    ctl("C17 致因改说 wall", c17)

    def c18(mm, zz):
        # ★ 最关键的一条：**墙**那一类也冒到 `z0+h+栏杆高`，而聚合读数
        #   （`z_measured` / `z_extra_m` / `z_extra_by`）**一个都不动** —— 全都还是
        #   「stair 越 0.9」。只有 ③ⓒ 逐类核才拦得住 ⇒ 没有这条就静默绿（铁律 137/158）。
        rail = rail_m() or 0.0
        for r in mm["floors"]:
            if r["floor"] == "8层":
                r["z_by_class"]["wall"] = [r["z0"], round(r["z0"] + r["h"] + rail, 3)]
    ctl("C18 墙也冒到栏杆高", c18)

    def c19(mm, zz):
        # 越层量与参数表那个数对不上（`z_measured` 照旧 ⇒ ③ⓑ 仍过，只有 ③ⓐ 该响）
        for r in mm["floors"]:
            if r["floor"] == "8层":
                r["z_extra_m"] = 1.05
    ctl("C19 越层量谎报 1.05", c19)

    def c20(mm, zz):
        # ★ 把梯栏杆**整条丢掉**：件退回改口径之前的样子（z 顶 = z0+h、越层量 0、
        #   致因 None、stair 那一类也不再冒头）。这条若放行，就等于把 ③ 改成了
        #   「z 多少都行」—— 那才是真正的「放松阈值」。
        for r in mm["floors"]:
            if r["floor"] == "8层":
                r["z_measured"] = [r["z0"], round(r["z0"] + r["h"], 3)]
                r["z_extra_m"] = 0.0
                r["z_extra_by"] = None
                r["z_by_class"]["stair"] = [r["z0"], round(r["z0"] + r["h"], 3)]
    ctl("C20 梯栏杆被丢掉", c20)

    # C13 往源件图层里塞一个窗层 —— **写临时副本**，原件一个字节都不动
    tmp = tempfile.mkdtemp(prefix="j10801_")
    try:
        import ezdxf
        src = None
        for fn in sorted(os.listdir(RAW)):
            if fn.lower().endswith(".dxf"):
                src = os.path.join(RAW, fn)
                break
        if src:
            doc = ezdxf.readfile(src)
            doc.layers.add("4.9窗户")
            doc.saveas(os.path.join(tmp, os.path.basename(src)))
            fs13 = ctl("C13 源件多出窗图层", lambda mm, zz: None, raw=tmp)
            # ★ 红的原因必须是「源件里真有窗层」，不能是「源件读不到」——
            #   两者都变红，若不点明原因，这条正对照就是在量错东西还全绿（铁律 137/197）。
            if not any("源件里有" in x for x in fs13):
                log("      ★ 原因不对：应报「源件里有」，实报 %s" % (fs13[:1] or "无"))
                ok = False
            else:
                log("      原因核对 ✔（红在「源件里有 [4.9窗户]」，不是「读不到」）")
        else:
            log("  C13 源件多出窗图层         → ★跳过（raw 里没有 dxf）")
            ok = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    log("\n===== 判词 =====")
    log("J-10.8-01 总判 :", "PASS" if ok else "FAIL")
    _write()
    return 0 if ok else 1


def _write():
    os.makedirs(RUNDIR, exist_ok=True)
    with open(os.path.join(RUNDIR, "J-10.8-01.run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")


if __name__ == "__main__":
    sys.exit(main())
