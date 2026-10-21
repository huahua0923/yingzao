# -*- coding: utf-8 -*-
"""判据 J-10.8-01 —— **参照件**三维白模（出口门：拉伸出来的件必须**从网格量**得对，不是照抄声明）。

★ 本判据只管 `rebuild/05_build/c006_white.*` 这份**参照件**（`build.json` 里 `"role":"reference"`，
2026-10-13 用户裁定：Python 件的身份是**对照物/尺子**，不是正式交付件）。
**正式件**（用户在 SketchUp 里建的，放 `rebuild/06_su/`）**另立 `J-10.8-02`** —— 且**不共用这把尺子**：
本判据的参照物来自本仓自己的 `build.json`，拿它去量正式件就是同源盲区（铁律 137/187/192）。

判据（§10.8「从平面到三维」）：
  ① 件存在且能被**独立读回**（trimesh.load(GLB) 成功）；
  ② **总高**：从**文件**量得的 **Y 上界** ≈ `top_m` + 顶部附属（女儿墙/楼梯房/屋面附属用房，
     后者 = 墙高 + 顶板厚）—— 参照在件之外，
     专抓「单位写反/缩放错」；②b 另查 `z_max_main_m`（不含附属）≈ `top_m`
     （**2026-10-16 改口径**：楼梯已不建栏杆 ⇒ 主体顶一分不许冒，旧口径那「+ 梯栏杆高 0.9」作废）；
  ③ **逐层 z 区间**：网格实测 z 区间 ≈ 声明的 `[z0, z0+h]`，**且**每一类（含 `stair`）
     都必须落在 `[z0, z0+h]` 内、越出量 `z_extra_m` 必须为 0、越层致因 `z_extra_by` 必须为
     `None`（口径见下方「③ 的口径」，2026-10-16 改）；
  ④ **墙足迹面积**：每层矢量墙面积 vs 识别栅格墙面积，相对差 ≤ 25%；
  ⑤ **水密**：每层墙网格 watertight=True；
  ⑥ **楼板**：每层必须有楼板（n_slab ≥ 1）且楼板面积 > 墙面积（板 ⊃ 墙带）；
  ⑦ **门扇**：每层门扇块数 ≥ 1（有门块的楼层；块本身来自源件 `$DorLib2D$`）；
  ⑧ **顶部附属**：**逐件**核 —— `parapet_m > 0` ⇒ 女儿墙环带 ≥ 1；`roof_stair_m > 0`
     ⇒ 顶楼楼梯房 ≥ 1（两个高度各记**实际建出来的值**，没建就是 0）；
  ⑨ **竖井**：每层井壁环带 ≥ 1、井道内空 ≥ 1、内空面积 > 0（井道**贯穿楼板**，
     不是实心块）；且**守恒**：`A_wall + A_wall_cut_by_voids + 梯间清空 + 塌短边
     ≈ A_wall_uncarved`（「墙真少了多少」与「洞∩墙带」是两条独立路径，也必须相等；
     ★ 2026-10-19 之前这里用的是 `A_void` = 洞多边形**原始面积和**，不是墙的差值）；
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
     判法（2026-10-19 改）：拿**声明总高** `top_m+顶部附属` 当参照 —— 哪个轴的**上界**对上它，
     哪个轴就是高度轴，**必须且只能是 Y**；另两轴不许同时对上（同时对上 = 尺子分不开 ⇒ 红）。
     ★ 比上界不比尺寸：c006 有地下室 −3.5 m，y 尺寸 50.6 ≠ 47.12，但 y 上界 = 47.12。
     旧判法「Y 是三轴最小」在「进深 < 建筑高」的楼（c065：17.6 m 进深 vs 25.2 m 高）把真件顶红。
③ 的口径（2026-10-15 收口 · **2026-10-16 再改**，**不是放松阈值**）：`TOL_Z` 仍 0.05 m。
  ★ 2026-10-16 **为什么改**：用户令「就是只要踏步和平台就行，不要那么复杂」⇒ 楼梯**不再建栏杆**
    （`rebuild/tools/build3d.py::stair_steps` 已改成坐在本级高程上的踏步板、`_rail_*` 不再调用，
    整链已重跑）。件里没有栏杆了 ⇒ 旧口径（上界 = `z0 + h + 栏杆高`、越层只许 `stair` 越 0.9 m、
    越出量必须等于参数表 `栏杆高_白模`）当场把真件顶红（实测 44.0 ≠ 44.9 / 每层 0.0 ≠ 0.9）。
    **新口径 = 一分不许冒**：本层合法上界就是 `[z0, z0+h]`。三件事 ——
  · 声明侧不再补「栏杆那一份」：上界 = `z0 + h`；`z_max_main_m` ≈ `top_m`（②b 同步改）；
  · 越出量 `z_extra_m` 必须为 `0`（`abs(ex) > TOL_Z` 判红，`ex is None` 也判红）；
  · 越层致因 `z_extra_by` **必须是 `None`**（谁都不许冒头）；且 `z_by_class` 里**每一类**
    （含 `stair`，**不再有 stair 豁免**）都必须落在 `[z0, z0+h]` 内。
    ★ 最后这条是这次改动后本闸**剩下一半的价值**：光看聚合的 `z_extra_m`/`z_extra_by`，
    墙和梯一起冒头时它照样印 `0`/`None`、冒不出声 —— 逐类核才拦得住（C18 就是给这条配的
    正对照，务必保留）。
  · 栏杆若将来恢复：把 ②b / ③ 改回 `top_m + rail_m()` / `z0 + h + rail_m()` 即可；参数表
    `构件/楼梯/栏杆高_白模` 与 `rail_m()` 本判据**留着没删**（正对照 C18/C20 仍在用它取那 0.9）。
量具（写明）：`rebuild/tools/build3d.py` 产出的 `build.json` + **字节层**读回 `c006_white.glb`
  （struct+json 解析 glTF JSON chunk + 节点树矩阵，**不经 trimesh**）+ 纯文本读 `c006_white.obj`
  （见 ②/⑫）+ ⑪ 现读 `rebuild/01_cad/raw/*.dxf` 的图层名（ezdxf）；单位 = 违反条数；阈值 = 0。
  （**2026-10-16**：②b/③ 已**不再**读 `rebuild/构件库/参数.json` 的 `构件/楼梯/栏杆高_白模`
    —— 新口径要的就是「一分不许冒」，不拿任何栏杆高当参照；该参数表只剩正对照 C18/C20 在用。）
量具盲区（声明）：
  · **⑫ 用「尺寸对上声明总高的那个轴」认高度轴**（2026-10-19 改，c065 实测）：
    若某栋楼的平面某一维**恰好等于**声明总高（±0.05 m），这条就分不开 ⇒ 判红（不静默放行）。
    旧口径「Y 必须是三轴最小」已废 —— 它在进深 < 建筑高的楼（c065：17.6 m < 25.2 m）把真件顶红。
  · ③ 的「每一类都不许越」把 `stair` 整个类当**一个**主体看：只要楼梯这一类里**任何一块**
    （梯段/平台）冒到 `z0+h` 以上就都算在 `stair` 头上，**不分辨**是哪一块冒的
    （要分辨得再细分到 `stair_step`/`stair_landing` 这类子标签）。
    ★ 2026-10-16：楼梯已不建栏杆 ⇒ 不再有「栏杆按设计越 0.9 m」这个合法例外。
  · ③ 现口径**不再引用**参数表 `栏杆高_白模`（那个值标的是 **「假设」不是「规范」**，900 mm，
    区间 850–1100）—— 真件不许冒头，无需任何栏杆高当参照；该量只在正对照 C18/C20 里用。
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
  · C1 真件 ⇒ **放行**（2026-10-16 起：各层 z 实测 = 声明 `[z0, z0+h]`、**一分不冒**、
    墙面积对得上、每层有板有门有井、全水密）；
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
    对调后 ② 看到 y 上界 84 ≠ 声明总高、⑫ 看到「对上声明总高的轴」是 Z 不是 Y ⇒ 两条都该红。
  · C15 只把 **glb** 那份写成 Z 朝上（obj 不动）⇒ **必红**（证明两份尺子**各自**有声：
    只看一份的判据会被「另一份恰好对」蒙过去）。
  · C16 两份 bbox 都置 `None`（模拟导出器不给 min/max / 文件读不出）⇒ **必红**
    （「没量到」不许静默当绿）。
  · C17 某层 `z_extra_by` 改说 `wall`（= 复现「墙偷偷高了 0.9 m」）⇒ **必红**（③：致因必须为 None）；
  · C18 某层**墙**那一类的 z 顶抬到 `z0+h+0.9`，而 `z_measured`/`z_extra_m`/`z_extra_by`
    **一个都不动**（全还是「一分不冒」）⇒ **必红**（③ 逐类核是关键：只看聚合读数会静默绿）；
  · C19 某层 `z_extra_m` 谎报 1.05（`z_measured` 照旧）⇒ **必红**（③：越出量必须是 0）；
  · C20 某层**假装栏杆还在**（8 层 z 顶与 `z_by_class` 的 `stair` 抬到 `z0+h+0.9`、`z_extra_m`
    报 0.9、致因为 `stair`）⇒ **必红**（★ 2026-10-16 **语义反转**：改前「丢掉栏杆」是错的、
    现在「栏杆还在」才是错的；这条保证新口径**不是**「z 多少都行」，只是把合法上界从
    `z0+h+栏杆高` 收紧回 `z0+h`）。
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _verdict as VD                                            # noqa: E402
import _items as I                                               # noqa: E402
import building as _B                                            # noqa: E402

# ★ 2026-10-19（用户「错误要能在页面上指出来」）：件路径**只从** `_verdict.paths()` 来 ——
#   原来这里是 c006 的绝对路径，别的楼量不了。`--bid X` / `CDUT_BUILDING` / 默认 c006。
BID = VD.bid_from()
_P = VD.paths(BID)
OUT = _P["build"]
RAW = _P["raw"]
GLB = _P["glb"]
OBJ = _P["obj"]
META = _P["build_json"]
# ★ 参数表：③ 的参照物。**必须直接读它**，不许从 build.json 里转手拿
#   （两个估计器不能同源，铁律 018/174/192）。
PARAMS = _P["params"]
RUNDIR = os.path.join(HERE, "_out")
JSONOUT = os.path.join(RUNDIR, "J-10.8-01.%s.json" % BID)   # ★ 台账页要的三路读数之一（见 _dump）
_LOG = []
_STATE = {}   # ★ 本闸**实测**到的读数（就地赋值、不重算、不编数），供落 json

# ★ 盲区（逐字抄本文件 docstring「量具盲区（声明）」那一节，不许在这里新增或编造）
BLIND = [
    "⑫「Y 是最小轴」只在「平面跨度 > 建筑高」时有分辨力（本栋 129×84 m 平面 vs 50.5 m 高（−3.5 … 47.0，2026-10-16 层高回 4.0 m 后的读数））；瘦高建筑要另写",
    "⑫ 的 glb 读 accessors.min/max + 节点 matrix；导出器不给 min/max / 改用 TRS / 把旋转写进蒙皮 ⇒ 量不到 ⇒ 判红，不当绿",
    "⑫ 只判轴朝向，不判左右手/绕竖轴转向（转 180°、或 X/Y 互换水平镜像，照样过）",
    "③ 的「每一类都不许越」把 stair 整个类当一个主体看：楼梯里任一块（梯段/平台）冒到 z0+h 以上都算在 stair 头上，不分辨是哪一块冒的（要分辨得再细分到 stair_step/stair_landing 这类子标签）；2026-10-16 起楼梯已不建栏杆，不再有「栏杆按设计越 0.9 m」这个合法例外",
    "③ 现口径不再引用参数表 栏杆高_白模（那个值标的是「假设」不是「规范」，900 mm，区间 850–1100）—— 真件不许冒头，无需栏杆高当参照；该量只在正对照 C18/C20 里用",
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

    ★★ 2026-10-16 **当前判词口径不用它**：用户令「楼梯只要踏步和平台」⇒ 楼梯不再建栏杆，
       ②b/③ 已改成「一分不许冒」（上界 = `top_m` / `z0+h`、越出量必须 0、致因必须 None），
       不再拿任何栏杆高当参照。**函数留着不删** —— 栏杆若恢复，把 ②b/③ 改回
       `top_m + rail_m()` / `z0 + h + rail_m()` 即可。眼下它仍被正对照 **C18/C20** 调用
       （那两条要「模拟栏杆还在」⇒ 需要这个 0.9 的抬高量），故**不是**「读了但没人用」。

    为什么原本必须从参数表读（旧口径留下的理由）：`build.json` 的 `z_extra_m` 说「本层上界比声明高了 0.9」，
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


# ---------------- 判据清单（一条一个函数） ----------------
# ★ 每条 rNN 返回 `I.结果`；`结果.证据` 就是原来 `judge()` 里那一串违反原文（一字不改、顺序不改）。
#   `_quiet=True` 供正对照（C2…C22）批量调用时静默；`_quiet=False` 是 `CHECKS` 那一趟，逐条打印细节。
_GATE = "J-10.8-01"
_CTX = {}


def _inputs(m, boxes, raw):
    """CHECKS 调用（无参）时从 `_CTX` 取本轮真件读数；正对照调用时用传进来的变体。"""
    if m is None:
        m, boxes, raw = _CTX["m"], _CTX["boxes"], _CTX["raw"]
    return m, boxes or {}, raw


def _attach(m):
    return m.get("attach", {}) or {}


def _attach_h(m):
    """顶部附属高度：女儿墙 / 顶楼楼梯房 / 屋面附属用房 三者取 max（与原 ② 的同一行一致）。"""
    att = _attach(m)
    return max([float(att.get(k, 0.0))
                for k in ("parapet_m", "roof_stair_m", "roof_room_m")] or [0.0])


def _detail(编号, 实测, fails, _quiet):
    if not _quiet:
        log("  %s 细节：%s%s" % (编号, 实测,
                                ("（违反 %d 条）" % len(fails)) if fails else ""))


def r01_件存在(m=None, boxes=None, raw=RAW, _quiet=True):
    """① 件存在且能被独立读回（`trimesh.load` 那一步在 `_run()`；这里判件非空）。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    fails = []
    if not m["floors"]:
        fails.append("空件：无楼层")
    实测 = "%d 层" % len(m["floors"])
    if not _quiet:
        实测 = "%d 层 / trimesh 读回 %d 个几何体" % (len(m["floors"]), _CTX.get("n_geom") or 0)
    _detail("①", 实测, fails, _quiet)
    return I.结果(not fails, 实测, "；".join(fails) if fails else "件非空", 证据=fails,
                  参数=[I.参数("楼层数", "≥ 1", "05_build/build.json::floors",
                              实测, "先跑 rebuild/tools/build3d.py 生成非空 build.json，再重跑本闸")])


def r02_总高(m=None, boxes=None, raw=RAW, _quiet=True):
    """② 总高 + ②b 主体顶（docstring ② / ②b，两条原文顺序不变）。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    fails = []
    wb = boxes.get("glb")
    hb = None if wb is None else (wb[2], wb[3])          # 高度在 Y
    # ② 总高：文件 Y 上界 = 主体顶参数 + 顶部附属（女儿墙/楼梯房）——参照在件之外
    att_h = _attach_h(m)
    exp_tot = m["top_m"] + att_h
    if hb is None or abs(hb[1] - exp_tot) > TOL_Z:
        fails.append("总高：件 Y 上界=%s ≠ top_m+附属=%.1f"
                     % ("None（没量到）" if hb is None else "%.3f" % hb[1], exp_tot))
    # ②b 主体顶（不含附属）vs `top_m` —— 2026-10-16 改口径：一分不许冒
    if abs((m.get("z_max_main_m") or 0.0) - m["top_m"]) > TOL_Z:
        fails.append("主体顶 %s ≠ top_m=%.1f（楼梯已不建栏杆，主体顶一分不许冒）"
                     % (m.get("z_max_main_m"), m["top_m"]))
    实测 = "Y上界 %s / 声明 %.1f" % ("None" if hb is None else "%.3f" % hb[1], exp_tot)
    _detail("②", 实测, fails, _quiet)
    return I.结果(not fails, 实测, "；".join(fails) if fails else "对上了", 证据=fails,
                  参数=[
                      I.参数("Y 上界 vs top_m+顶部附属", "TOL_Z = %.2f m" % TOL_Z,
                             "05_build/build.json::top_m + attach.{parapet_m,roof_stair_m,roof_room_m}",
                             "None（没量到）" if hb is None else "%.3f（期望 %.1f）" % (hb[1], exp_tot),
                             "核对档案 top_m 与 attach 高度，重跑 rebuild/tools/build3d.py，再重跑本闸"),
                      I.参数("z_max_main_m vs top_m", "TOL_Z = %.2f m" % TOL_Z,
                             "05_build/build.json::z_max_main_m / top_m",
                             "%s / %.1f" % (m.get("z_max_main_m"), m["top_m"]),
                             "改档案 top_m 或 build3d.py 的主体高度，重跑 build3d 后再重跑本闸"),
                  ])


def r12_朝向(m=None, boxes=None, raw=RAW, _quiet=True):
    """⑫ 出件朝向 = Y 朝上（glb / obj 两份只认文件格式的读者，各自都必须有声）。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    fails = []
    exp_h = m["top_m"] + _attach_h(m)
    for lab in ("glb", "obj"):
        bb = boxes.get(lab)
        if bb is None:
            fails.append("⑫ %s：没量到 bbox（读不出/文件不在）⇒ 不许当绿" % lab)
            continue
        ext = (bb[1] - bb[0], bb[3] - bb[2], bb[5] - bb[4])
        # ★ 比的是**上界**不是尺寸：c006 有地下室 −3.5 m ⇒ y 尺寸 50.6，但 y 上界 47.12。
        up = (bb[1], bb[3], bb[5])
        hit = [i for i in range(3) if abs(up[i] - exp_h) <= TOL_Z]
        if hit != [1]:
            fails.append("⑫ %s 高度轴不是 Y：三轴上界 x=%.1f y=%.1f z=%.1f（尺寸 %.1f/%.1f/%.1f），"
                         "声明总高 %.3f 只该落在 Y 上（对上声明总高的轴 = %s）"
                         % ((lab,) + up + ext + (exp_h, hit or "无")))
    实测 = "glb %s / obj %s" % ("有" if boxes.get("glb") is not None else "没量到",
                               "有" if boxes.get("obj") is not None else "没量到")
    _detail("⑫", 实测, fails, _quiet)
    return I.结果(not fails, 实测,
                  "；".join(fails) if fails else "两份尺子都是 Y 朝上", 证据=fails,
                  参数=[
                      I.参数("高度轴", "声明总高 %.3f 只落在 Y（±TOL_Z = %.2f m）" % (exp_h, TOL_Z),
                             "05_build/*_white.glb 字节层 bbox + *_white.obj::v 行",
                             实测,
                             "查 rebuild/tools/build3d.py 出件旋转（glTF = +Y 朝上），重跑 build3d 后再重跑本闸"),
                      I.参数("声明总高（参照）", "= top_m + 顶部附属",
                             "05_build/build.json::top_m / attach",
                             "%.3f" % exp_h,
                             "先核档案 top_m/attach 是否对，再动出件旋转"),
                  ])


def r03_逐层z(m=None, boxes=None, raw=RAW, _quiet=True):
    """③ 逐层 z 区间 —— 2026-10-16 改口径：一分不许冒（每一类都不许越）。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    fails = []
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
            fails.append("%s 缺 z_by_class（只有聚合 z 读数 ⇒ 分不出是哪一类冒了头，"
                         "不许当绿）" % fl)
            continue
        if abs(zm[0] - z0_) > TOL_Z:
            fails.append("%s z 底 %s ≠ 声明 %.1f" % (fl, zm[0], z0_))
        if abs(zm[1] - ztop) > TOL_Z:
            fails.append("%s z 顶 %s ≠ 声明顶 %.1f（楼梯已不建栏杆，一分不许冒）"
                         % (fl, zm[1], ztop))
        ex = r.get("z_extra_m")
        if ex is None or abs(ex) > TOL_Z:
            fails.append("%s z_extra_m=%s ≠ 0（楼梯已不建栏杆，越出量必须是 0）" % (fl, ex))
        if r.get("z_extra_by") is not None:
            fails.append("%s 越层致因 z_extra_by=%s（楼梯已不建栏杆 ⇒ 谁都不许冒头）"
                         % (fl, r.get("z_extra_by")))
        for tg, zz in sorted(zbc.items()):
            if not zz:
                continue
            if zz[1] > ztop + TOL_Z or zz[0] < z0_ - TOL_Z:
                fails.append("%s 类 %s z=[%s,%s] 越过声明 [%.1f,%.1f]（每一类都不许越）"
                             % (fl, tg, zz[0], zz[1], z0_, ztop))
    实测 = "%d 层" % len(m["floors"])
    _detail("③", 实测, fails, _quiet)
    return I.结果(not fails, 实测,
                  "；".join(fails) if fails else "逐类均在 [z0, z0+h] 内", 证据=fails,
                  参数=[
                      I.参数("逐层 z 底/顶", "TOL_Z = %.2f m" % TOL_Z,
                             "05_build/build.json::floors[].z0 / h / z_measured",
                             "%d 条违反" % len(fails),
                             "改档案 z0/h 或重跑 rebuild/tools/build3d.py 的逐层拉伸，再重跑本闸"),
                      I.参数("z_extra_m", "= 0（|x| ≤ TOL_Z = %.2f m）" % TOL_Z,
                             "05_build/build.json::floors[].z_extra_m",
                             "%d 条违反" % len(fails),
                             "查 build3d.py 里越层的梯段/平台/墙顶，重跑 build3d 后再重跑本闸"),
                      I.参数("z_extra_by", "None（谁都不许冒头）",
                             "05_build/build.json::floors[].z_extra_by",
                             "%d 条违反" % len(fails),
                             "先消除越层构件，再让致因为 None，重跑 build3d 后重跑本闸"),
                      I.参数("z_by_class（逐类）", "每类 ⊆ [z0, z0+h]（±%.2f m）" % TOL_Z,
                             "05_build/build.json::floors[].z_by_class",
                             "%d 条违反" % len(fails),
                             "逐类查超高的构件类别，改 build3d.py 后重跑本闸"),
                  ])


def r04_墙面积(m=None, boxes=None, raw=RAW, _quiet=True):
    """④ 墙足迹面积 vs 识别（比的是**抠洞前** `A_wall_uncarved_m2`，相对差 ≤ 25%）。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    fails = []
    for r in m["floors"]:
        rec = r.get("A_wall_recognized_m2") or 0
        unc = r.get("A_wall_uncarved_m2")
        if rec <= 0:
            continue
        if unc is None:
            fails.append("%s 缺 A_wall_uncarved_m2（④ 只能比抠洞前的墙面积，不能拿抠后的顶上）"
                         % r["floor"])
        elif abs(unc - rec) / rec > TOL_AREA:
            fails.append("%s 墙面积(抠前) %.1f vs 识别 %.1f 相对差>%.0f%%"
                         % (r["floor"], unc, rec, TOL_AREA * 100))
    实测 = "%d 层" % len(m["floors"])
    _detail("④", 实测, fails, _quiet)
    return I.结果(not fails, 实测,
                  "；".join(fails) if fails else "相对差均 ≤ %.0f%%" % (TOL_AREA * 100),
                  证据=fails,
                  参数=[I.参数("墙面积相对差", "TOL_AREA = %.0f%%" % (TOL_AREA * 100),
                              "05_build/build.json::floors[].A_wall_uncarved_m2 / A_wall_recognized_m2（识别栅格）",
                              "%d 条违反" % len(fails),
                              "核对 01_cad/raw 墙体图层与识别栅格，重跑 rebuild/tools/build3d.py 后再重跑本闸")])


def r05_水密(m=None, boxes=None, raw=RAW, _quiet=True):
    """⑤ 水密：每层墙网格 watertight=True。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    fails = []
    for r in m["floors"]:
        if not r.get("watertight_wall"):
            fails.append("%s 墙网格不水密" % r["floor"])
    实测 = "%d/%d 层水密" % (sum(1 for r in m["floors"] if r.get("watertight_wall")),
                             len(m["floors"]))
    _detail("⑤", 实测, fails, _quiet)
    return I.结果(not fails, 实测, "；".join(fails) if fails else "全部水密", 证据=fails,
                  参数=[I.参数("水密层数", "全部层 watertight_wall = True",
                              "05_build/build.json::floors[].watertight_wall",
                              实测,
                              "查 rebuild/tools/build3d.py 的墙网格封口，重跑 build3d 后再重跑本闸")])


def r06_楼板(m=None, boxes=None, raw=RAW, _quiet=True):
    """⑥ 楼板：每层必须有楼板（n_slab ≥ 1）且楼板面积 > 墙面积。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    fails = []
    for r in m["floors"]:
        ns = r.get("n_slab", 0) or 0
        asl = r.get("A_slab_m2") or 0
        if ns < 1 or asl <= 0:
            fails.append("%s 无楼板（n_slab=%s, A=%s）" % (r["floor"], ns, asl))
        elif asl <= (r.get("A_wall_m2") or 0):
            fails.append("%s 楼板 %.1f ≤ 墙 %.1f（板应盖住墙带）" % (r["floor"], asl, r.get("A_wall_m2") or 0))
    实测 = "%d 层" % len(m["floors"])
    _detail("⑥", 实测, fails, _quiet)
    return I.结果(not fails, 实测, "；".join(fails) if fails else "每层有板且板 ⊃ 墙带",
                  证据=fails,
                  参数=[I.参数("楼板", "n_slab ≥ 1 且 A_slab_m2 > A_wall_m2",
                              "05_build/build.json::floors[].n_slab / A_slab_m2 / A_wall_m2",
                              "%d 条违反" % len(fails),
                              "查 rebuild/tools/build3d.py 的楼板闭运算填充，重跑 build3d 后再重跑本闸")])


def r07_门扇(m=None, boxes=None, raw=RAW, _quiet=True):
    """⑦ 门扇：源件有门线的楼层，门扇块数 ≥ 1。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    fails = []
    for r in m["floors"]:
        if (r.get("n_door_block") or 0) > 0 and (r.get("n_door_leaf") or 0) < 1:
            fails.append("%s 门扇块数 0（源件有门线却未出扇）" % r["floor"])
    实测 = "%d 层有门线" % sum(1 for r in m["floors"] if (r.get("n_door_block") or 0) > 0)
    _detail("⑦", 实测, fails, _quiet)
    return I.结果(not fails, 实测, "；".join(fails) if fails else "有门线的层都出了扇",
                  证据=fails,
                  参数=[I.参数("门扇块数", "有门线（n_door_block>0）⇒ n_door_leaf ≥ 1",
                              "01_cad/raw/*.dxf::$DorLib2D$ 门块 + 05_build/build.json::floors[].n_door_leaf",
                              "%d 条违反" % len(fails),
                              "查源件门块是否读入、build3d.py 是否出扇，重跑 build3d 后再重跑本闸")])


def r08_附属(m=None, boxes=None, raw=RAW, _quiet=True):
    """⑧ 顶部附属：**逐件**核 —— 声明了这个高度就得有这一件（两条独立判据）。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    fails = []
    att = _attach(m)
    _pm = float(att.get("parapet_m") or 0.0)
    _sm = float(att.get("roof_stair_m") or 0.0)
    if _pm > 0 and int(att.get("n_parapet", 0) or 0) < 1:
        fails.append("女儿墙声明 %.1f m 但件未入（n_parapet=%s）" % (_pm, att.get("n_parapet")))
    if _sm > 0 and int(att.get("n_roof_stair", 0) or 0) < 1:
        fails.append("顶楼楼梯房声明 %.1f m 但件未入（n_roof_stair=%s）"
                     % (_sm, att.get("n_roof_stair")))
    实测 = "女儿墙 %.1f / 梯房 %.1f" % (_pm, _sm)
    _detail("⑧", 实测, fails, _quiet)
    return I.结果(not fails, 实测, "；".join(fails) if fails else "声明的都入了件",
                  证据=fails,
                  参数=[
                      I.参数("女儿墙件数", "parapet_m > 0 ⇒ n_parapet ≥ 1",
                             "05_build/build.json::attach.parapet_m / n_parapet",
                             "%s / %s" % (_pm, att.get("n_parapet")),
                             "核对档案 attach.parapet_m 或让 build3d.py 把女儿墙入场景，重跑本闸"),
                      I.参数("顶楼楼梯房件数", "roof_stair_m > 0 ⇒ n_roof_stair ≥ 1",
                             "05_build/build.json::attach.roof_stair_m / n_roof_stair",
                             "%s / %s" % (_sm, att.get("n_roof_stair")),
                             "核对档案 attach.roof_stair_m 或让 build3d.py 把楼梯房入场景，重跑本闸"),
                  ])


def r09_竖井(m=None, boxes=None, raw=RAW, _quiet=True):
    """⑨ 竖井：环带 + 内空都在，且守恒 A_wall + 墙内实扣 + 梯间清空 + 塌短边 ≈ A_wall_uncarved。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    fails = []
    _sc = {}
    for _z in (m.get("stair_clear") or []):
        if isinstance(_z, dict):
            _sc[_z.get("层")] = _z
    checked = 0
    import building as _B
    roof_plans = set((_B.profile().get("roof_plans") or {}).keys())
    for r in m["floors"]:
        if r.get("floor") in roof_plans:
            # 屋面平面层不是普通楼层，井道/梯间守恒不在这里套。
            continue
        nl = r.get("n_lift", 0) or 0
        nv = r.get("n_lift_void", 0) or 0
        av = r.get("A_lift_void_m2") or 0.0
        # ★ n_lift 是电梯井壁件数，不是每栋楼都有电梯。
        #   没有井道内空的楼层不参与本条；有内空时才核守恒。
        if nv < 1 or av <= 0:
            continue
        checked += 1
        u = r.get("A_wall_uncarved_m2")
        if u is None:
            fails.append("%s 缺 A_wall_uncarved_m2（守恒式无从核）" % r["floor"])
            continue
        _z = _sc.get(r["floor"])
        _s = None if _z is None else _z.get("墙带扣掉_m2")
        if _s is None:
            fails.append("%s 缺 `stair_clear[].墙带扣掉_m2`（②梯间清空那一刀的账，守恒式无从核）"
                         % r["floor"])
            continue
        _t = (_z.get("塌墙带") or {}).get("塌短边面积_m2") or 0.0
        # ★ 三把尺子分开量：墙内实扣（②）/ 洞∩墙带（③）/ 洞总面积和（上界）
        _cut = r.get("A_wall_cut_by_voids_m2")
        _inw = r.get("A_void_in_wall_m2")
        _raw = r.get("A_void_raw_m2", av)
        if _cut is None or _inw is None:
            fails.append("%s 缺 A_wall_cut_by_voids_m2 / A_void_in_wall_m2"
                         "（旧口径 `A_lift_void_m2` 是原始面积和，不能顶替）" % r["floor"])
            continue
        if abs(_cut - _inw) > TOL_CONS:
            fails.append("%s 井+门洞口径不合：墙实际少了 %.2f，落在墙内的洞 %.2f（差 %+.2f）"
                         % (r["floor"], _cut, _inw, _cut - _inw))
        if _inw > _raw + TOL_CONS:
            fails.append("%s 落在墙内的洞 %.2f > 洞总面积 %.2f（不可能）"
                         % (r["floor"], _inw, _raw))
        _lhs = (r.get("A_wall_m2") or 0.0) + _cut + _s + _t
        if abs(_lhs - u) > TOL_CONS:
            fails.append("%s 抠洞守恒破：墙 %.2f + 洞(墙内实扣) %.2f + 梯间清空 %.2f + 塌短边 %.2f"
                         " = %.2f ≠ 抠前 %.2f"
                         % (r["floor"], r.get("A_wall_m2") or 0.0, _cut, _s, _t, _lhs, u))
    实测 = "%d 层有井道内空" % checked
    if checked == 0:
        return I.结果(True, 实测, "本楼源件无井道内空，⑨不适用",
                      参数=[I.参数("井道内空", "有内空才核；无内空不要求有电梯井",
                                   "05_build/build.json::floors[].n_lift_void / A_lift_void_m2",
                                   "0 层", "本楼确实没有井道内空")])
    _detail("⑨", 实测, fails, _quiet)
    return I.结果(not fails, 实测, "；".join(fails) if fails else "井在内空在，守恒成立",
                  证据=fails,
                  参数=[
                      I.参数("井道内空", "参与核的层：n_lift_void ≥ 1 且 A_lift_void_m2 > 0；n_lift 可为 0",
                             "05_build/build.json::floors[].n_lift / n_lift_void / A_lift_void_m2",
                             实测,
                             "无电梯楼不因 n_lift=0 判红；有内空但守恒破才查 build3d"),
                      I.参数("墙内实扣 vs 洞∩墙带",
                             "|A_wall_cut_by_voids_m2 − A_void_in_wall_m2| ≤ TOL_CONS = %.1f m²" % TOL_CONS,
                             "05_build/build.json::floors[].A_wall_cut_by_voids_m2 / A_void_in_wall_m2",
                             "%d 条违反" % len(fails),
                             "核 build3d.py 的洞与墙带求交那一步，重跑 build3d 后再重跑本闸"),
                      I.参数("抠洞守恒",
                             "|A_wall + A_wall_cut_by_voids + 墙带扣掉 + 塌短边 − A_wall_uncarved| ≤ TOL_CONS = %.1f m²"
                             % TOL_CONS,
                             "05_build/build.json::floors[].A_wall_m2 / A_wall_uncarved_m2"
                             " + stair_clear[].墙带扣掉_m2 / 塌墙带.塌短边面积_m2",
                             "%d 条违反" % len(fails),
                             "核 build.json 各面积账与 stair_clear，重跑 build3d 后再重跑本闸"),
                  ])


def r10_台阶屋面(m=None, boxes=None, raw=RAW, _quiet=True):
    """⑩ 7→8 台阶屋面：参照物是「两层楼板之差」，不是那句声明本身。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    import building as _B
    if "7层" in (_B.profile().get("roof_plans") or {}):
        return I.结果(True, "7层是屋面平面", "档案声明 7层为屋面平面，不存在 7→8 台阶屋面",
                      参数=[I.参数("台阶屋面", "roof_plans 含 7层 ⇒ 本条不适用",
                                   "rebuild/构件库/楼栋.json::roof_plans",
                                   "不适用", "不需要补 7→8 台阶屋面")])
    fails = []
    at = _attach(m)
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
    实测 = "slab(7)-slab(8)=%.1f / 屋面 %.1f" % (ref, ars)
    _detail("⑩", 实测, fails, _quiet)
    return I.结果(not fails, 实测, "；".join(fails) if fails else "与两板之差对得上",
                  证据=fails,
                  参数=[I.参数("台阶屋面面积", "TOL_ROOF = %.0f%%（ref > 1.0 m² 才判）" % (TOL_ROOF * 100),
                              "05_build/build.json::attach.roof_step7_m2 / n_roof_step7"
                              " vs floors[7层/8层].A_slab_m2",
                              实测,
                              "核对档案 roof_step7_m2 与 7/8 层楼板读数，重跑 build3d 后再重跑本闸")])


def r11_窗(m=None, boxes=None, raw=RAW, _quiet=True):
    """⑪ 窗 = 无 的反证：现读源件图层名。"""
    m, boxes, raw = _inputs(m, boxes, raw)
    fails = []
    wins = window_layers(raw)
    if wins is None:
        fails.append("⑪ 源件图层读不到（没量到 ⇒ 不许当绿）")
    elif wins:
        fails.append("声明「源件无窗图层」，但源件里有 %s" % wins)
    实测 = "窗图层 %s" % (wins,)
    _detail("⑪", 实测, fails, _quiet)
    return I.结果(not fails, 实测,
                  "；".join(fails) if fails else "源件无窗图层（反证成立）", 证据=fails,
                  参数=[I.参数("窗图层数", "= 0（声明「源件无窗图层」）",
                              "01_cad/raw/*.dxf::图层名（含 窗/WINDOW/GLAZ/WIND_）",
                              实测,
                              "改档案「无窗」声明或清理源件多出的窗图层，再重跑本闸")])


# ★ 拼接顺序 = 原 `judge()` 里各段的**原文出现顺序**（② → ②b → ⑫ → ③ → … → 空件），
#   一行都不许换位（`_STATE["fails"]` 与页面 item 的顺序就靠它）。
_JUDGE_ORDER = (
    ("②", r02_总高),
    ("⑫", r12_朝向),
    ("③", r03_逐层z),
    ("④", r04_墙面积),
    ("⑤", r05_水密),
    ("⑥", r06_楼板),
    ("⑦", r07_门扇),
    ("⑧", r08_附属),
    ("⑨", r09_竖井),
    ("⑩", r10_台阶屋面),
    ("⑪", r11_窗),
    ("①", r01_件存在),
)


def judge_parts(m, boxes, raw=RAW):
    """每条规则 **一个**函数；返回 [(编号, 结果), …]（`结果.证据` = 原来那串违反原文）。"""
    return [(n, fn(m, boxes, raw)) for n, fn in _JUDGE_ORDER]


def judge(m, boxes, raw=RAW):
    """返回违反串列表（空 = 合格）。★ 对外签名与改前**完全一致**，既有调用者不用改。

    `boxes` = `{"glb": bbox6 或 None, "obj": bbox6 或 None}` —— 两份不同的尺子量同一个件：
    `glb` 走 glTF 节点树（顶点 × 矩阵），`obj` 是纯文本 v 行。两者都要**Y 朝上**。
    ★ 高度取 **Y**（glTF 规范 +Y 朝上），不是 z —— 这是 2026-10-13 那处朝向坑的落点。
    """
    return [x for _n, r in judge_parts(m, boxes, raw) for x in r.证据]


def c01(): return r01_件存在(_quiet=False)
def c02(): return r02_总高(_quiet=False)
def c03(): return r03_逐层z(_quiet=False)
def c04(): return r04_墙面积(_quiet=False)
def c05(): return r05_水密(_quiet=False)
def c06(): return r06_楼板(_quiet=False)
def c07(): return r07_门扇(_quiet=False)
def c08(): return r08_附属(_quiet=False)
def c09(): return r09_竖井(_quiet=False)
def c10(): return r10_台阶屋面(_quiet=False)
def c11(): return r11_窗(_quiet=False)
def c12(): return r12_朝向(_quiet=False)


def c13_正对照():
    """★ 2026-10-19：正对照失灵必须**顶红**（改前 `ok` 是并入 rc 的）。
    拆成清单后若只让 ①–⑫ 定 rc，正对照放行就只剩一行字 ⇒ 判据没有分辨力也照样 PASS。"""
    if "_ctrl_total" not in _STATE:
        raise I.没量到("正对照没跑起来（没有一条进入判据）")
    fired = int(_STATE.get("_ctrl_fired", 0))
    total = int(_STATE["_ctrl_total"])
    skipped = int(_STATE.get("_ctrl_skipped", 0))
    ok = bool(_STATE.get("controls_ok", False))
    return I.结果(ok, "%d/%d 触发 / 跳过 %d" % (fired, total, skipped),
                  "全部按预期" if ok else
                  "★ 有正对照放行 ⇒ 判据没有分辨力，本闸的绿不作数",
                  参数=[
                      I.参数("正对照触发数", "= 总数 %d" % total,
                             "本闸正对照用例表", "%d" % fired,
                             "有对照被放行 ⇒ 先看该对照的输入是否退化，别动判据阈值"),
                      I.参数("跳过数", "仅限本楼缺参照物，且必须逐条打印原因",
                             "本闸正对照用例表", "%d" % skipped,
                             "跳过不是通过；但本楼没有该参照物时也不得算红"),
                  ])


CHECKS = [
    ("①", "件存在且能被独立读回", c01),
    ("②", "总高：Y 上界 = top_m + 顶部附属（含 ②b 主体顶）", c02),
    ("③", "逐层 z 区间：每一类都不许越（一分不冒）", c03),
    ("④", "墙足迹面积 vs 识别（相对差 ≤ 25%）", c04),
    ("⑤", "水密：每层墙网格 watertight", c05),
    ("⑥", "楼板：每层有板且板面积 > 墙面积", c06),
    ("⑦", "门扇：源件有门线的楼层门扇块数 ≥ 1", c07),
    ("⑧", "顶部附属：声明了高度就得有这一件", c08),
    ("⑨", "竖井：井壁 + 内空在，且抠洞守恒", c09),
    ("⑩", "7→8 台阶屋面 ≈ 两板之差", c10),
    ("⑪", "窗 = 无 的反证：源件图层名", c11),
    ("⑫", "出件朝向 = Y 朝上（glb + obj 两份尺子）", c12),
    ("⑬", "正对照全部按预期（本闸的分辨力）", c13_正对照),
]


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
    # ★ `rep.items` = 判据清单的逐条结果（`I.跑` 交出）；早退路径没有它时退回 `fails` 原文。
    items_ = _STATE.pop("items", None)
    # ★ 三态（铁律 199）：rc==4 是「没量到」⇒ pass=None，不许写成 False 或 True。
    pass_ = None if rc == 4 else (rc == 0)
    rec = {"pass": pass_, "rc": rc}
    rec.update(_STATE)                       # 本闸实测读数（顺序即赋值顺序）
    if items_ is not None:
        rec["items"] = items_                # ★ 判据清单的逐条结果（I.跑 交出）
    rec["controls_fired"] = "%d/%d" % (cf, ct)   # 正对照触发数（本闸的分辨力证据）
    rec["blind"] = BLIND
    os.makedirs(RUNDIR, exist_ok=True)
    with open(JSONOUT, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    print("  写出:", JSONOUT)
    # ★ 2026-10-19：同一份读数再经统一出口落一份（矩阵只读这一份）。items 用判据清单
    #   逐条交出的结果，不从散文里再解析一遍（铁律 174：同一个量不许有两个估计器）。
    VD.emit("J-10.8-01", BID, pass_, rc, _LOG, blind=BLIND,
            files={"build_json": META, "glb": GLB, "obj": OBJ,
                   "raw": RAW, "params": PARAMS},
            extra=dict(_STATE),
            # ★ 判据清单的逐条结果（`I.跑` 交出）；`rep` 没跑到时退回原口径的 `fails` 原文。
            items=items_ if items_ is not None
            else VD.items_from_strings("J-10.8-01", _STATE.get("fails") or []))


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
    # ★ 每条规则一个函数：`judge_parts()` 返回 [(编号, 结果), …]，`judge()` 只是把各条
    #   `结果.证据` 按原顺序拼起来（对外签名与行为不变）。
    parts_list = judge_parts(m, boxes)
    f1 = [x for _n, r in parts_list for x in r.证据]
    _STATE["c1_fails"] = len(f1)               # ★ 真件上的违反条数（0 = 放行）
    _STATE["fails"] = list(f1)                 # ★ 原文留给 verdict.items（页面要点名哪一条）
    log("C1 真件：违反 %d 条 ⇒ %s" % (len(f1), "放行" if not f1 else "★红了 " + "; ".join(f1[:3])))
    # ★ 2026-10-19：正对照不许再钉死 c006 的层名。矩阵要跑 67 栋，别的楼没有 8层/11层
    #   ⇒ 原来一半正对照变成「打空」（不触发 ⇒ 判成放行 ⇒ 整闸冤枉红），C12 更是直接
    #   `KeyError: '7层'` 崩在落 verdict 之前（铁律 199：崩了 ≠ 没量到 ≠ 通过）。
    #   改成：落点层取本楼**真有的**那一层；只有「7→8 台阶」这条确实依赖两层层名，
    #   缺层就**明说跳过**——既不许静默当通过，也不许算成红。
    _FLOORS = [r["floor"] for r in m["floors"]]
    TGT = "8层" if "8层" in _FLOORS else (_FLOORS[-1] if _FLOORS else None)
    TOP = "11层" if "11层" in _FLOORS else (_FLOORS[-1] if _FLOORS else None)

    def ctl(name, fn, raw=RAW, need=()):
        nonlocal ok
        miss_need = [x for x in need if x not in _FLOORS]
        if miss_need:
            _STATE["_ctrl_skipped"] = _STATE.get("_ctrl_skipped", 0) + 1
            log("  %-22s → 跳过（本楼没有 %s）" % (name, "、".join(miss_need)))
            return []
        mm, ww = copy.deepcopy(m), copy.deepcopy(boxes)
        # fn 可改 mm 就地，也可**返回**新的 boxes 字典（文件 bbox 在件侧，不在 mm 里）
        # 返回 `"SKIP"` = 本楼没有这条正对照的参照物 ⇒ 跳过（不算红、不算通过）
        r = fn(mm, ww)
        if r == "SKIP":
            _STATE["_ctrl_skipped"] = _STATE.get("_ctrl_skipped", 0) + 1
            log("  %-22s → 跳过（本楼没有这条的参照物）" % name)
            return []
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
        mm["floors"] = [r for r in mm["floors"] if r["floor"] != TOP]
        mm["z_max_m"] = 40.0
        return {k: (None if v is None else (v[0], v[1], v[2], 40.0, v[4], v[5]))
                for k, v in ww.items()}
    ctl("C3 少一层(11层)", c3)

    def c4(mm, zz):
        for r in mm["floors"]:
            if r["floor"] == TGT:
                # ★ 2026-10-19：④ 改比「抠前」之后，要撬动的字段也跟着改成
                #   `A_wall_uncarved_m2`（撬 `A_wall_m2` 只会把 ⑥ 的「板≤墙」撬响，
                #   ④ 本身没被测到 —— 正对照必须打在被测的那个量上，铁律 137）。
                r["A_wall_uncarved_m2"] = round(r["A_wall_recognized_m2"] * 1.5, 2)
    ctl("C4 墙面积(抠前)×1.5", c4)

    def c5(mm, zz):
        mm["floors"] = []
    ctl("C5 空件", c5)

    def c6(mm, zz):
        for r in mm["floors"]:
            if r["floor"] == TGT:
                r["A_slab_m2"] = 0.0
    ctl("C6 楼板清零", c6)

    def c7(mm, zz):
        for r in mm["floors"]:
            if r["floor"] == TGT:
                r["A_slab_m2"] = round((r["A_wall_m2"] or 1.0) * 0.5, 2)
    ctl("C7 楼板<墙", c7)

    def c8(mm, zz):
        mm["attach"]["n_parapet"] = 0
    ctl("C8 附属未入", c8)

    def c9(mm, zz):
        for r in mm["floors"]:
            if ((r.get("n_lift_void") or 0) > 0
                    and (r.get("A_lift_void_m2") or 0) > 0):
                r["A_wall_uncarved_m2"] = r["A_wall_m2"]        # 假装没抠过井
                return None
        return "SKIP"
    ctl("C9 守恒式(假装没井)", c9)

    def c10(mm, zz):
        # ⑨ 已不再要求每层都有电梯井壁；这里改测“洞∩墙带 vs 墙内实扣”。
        for r in mm["floors"]:
            if (r.get("n_lift_void") or 0) > 0 and (r.get("A_lift_void_m2") or 0) > 0:
                r["A_void_in_wall_m2"] = (r.get("A_wall_cut_by_voids_m2") or 0) + 1.0
                return None
        return "SKIP"
    ctl("C10 井+门洞口径差 1 m²", c10)

    def _step_ref(mm):
        """7→8 台阶的参照物：两层楼板之差（本楼没有这两层就当没有台阶）。"""
        sl = {r["floor"]: (r.get("A_slab_m2") or 0.0) for r in mm["floors"]}
        return sl.get("7层", 0.0) - sl.get("8层", 0.0)

    def c11(mm, zz):
        if "7层" in (_B.profile().get("roof_plans") or {}):
            return "SKIP"
        if _step_ref(mm) <= 1.0:
            return "SKIP"          # 本楼板差说这儿没有台阶 ⇒ 清不清零都不该红
        mm["attach"]["n_roof_step7"] = 0
        mm["attach"]["roof_step7_m2"] = 0.0
    ctl("C11 台阶屋面未入", c11)

    def c12(mm, zz):
        if "7层" in (_B.profile().get("roof_plans") or {}):
            return "SKIP"
        sl = {r["floor"]: r.get("A_slab_m2") or 0.0 for r in mm["floors"]}
        if sl.get("7层") is None or sl.get("8层") is None:
            return "SKIP"
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
            if r["floor"] == TGT:
                r["z_extra_by"] = "wall"
    ctl("C17 致因改说 wall", c17)

    def c18(mm, zz):
        # ★ 最关键的一条（2026-10-16 起更是**唯一**拦得住的一条）：**墙**那一类冒到
        #   `z0+h+0.9`，而聚合读数（`z_measured` / `z_extra_m` / `z_extra_by`）**一个都不动**
        #   —— 全都还是「一分不冒」。**已无 stair 豁免**，每一类都要落在 [z0, z0+h]，
        #   只有 ③ⓒ 逐类核拦得住 ⇒ 没有这条就静默绿（铁律 137/158）。
        #   那 0.9 用 rail_m() 取（= 栏杆高，本判据里它仅剩的活口）。
        rail = rail_m() or 0.0
        for r in mm["floors"]:
            if r["floor"] == TGT:
                r["z_by_class"]["wall"] = [r["z0"], round(r["z0"] + r["h"] + rail, 3)]
    ctl("C18 墙也冒到栏杆高", c18)

    def c19(mm, zz):
        # 越出量非 0（`z_measured` 照旧 ⇒ 只有 ③「越出量必须是 0」该响）
        for r in mm["floors"]:
            if r["floor"] == TGT:
                r["z_extra_m"] = 1.05
    ctl("C19 越层量谎报 1.05", c19)

    def c20(mm, zz):
        # ★ 2026-10-16 **语义反转**：改前这条是「把梯栏杆整条丢掉」（旧口径下丢掉=错、
        #   因此必红）；现在**没有栏杆才是对的** ⇒ 改成「**假装栏杆还在**」：8 层 z 顶
        #   （和 `z_by_class` 里 `stair` 那一类）抬到 `z0+h+0.9`、`z_extra_m` 报 0.9、
        #   越层致因说回 `stair`。这条必须红（落在 ③：z 顶 ≠ z0+h、z_extra_m ≠ 0、
        #   致因非 None、stair 那一类越界）。若放行，就等于把 ③ 改成「z 多少都行」——
        #   那才是真正的「放松阈值」。
        rail = rail_m() or 0.0
        for r in mm["floors"]:
            if r["floor"] == TGT:
                zt = round(r["z0"] + r["h"] + rail, 3)
                r["z_measured"] = [r["z0"], zt]
                r["z_extra_m"] = rail
                r["z_extra_by"] = "stair"
                r["z_by_class"]["stair"] = [r["z0"], zt]
    ctl("C20 某层假装栏杆还在（顶抬 0.9）", c20)

    def c21(mm, zz):
        # ★ 2026-10-17 新加（⑨ 补进 ②梯间清空 那一项时的**分辨力证据**）：
        #   ③ 那一项**也是从同一份 `build.json` 读的** ⇒ 不喂坏输入就证不出它有分辨力
        #   （铁律 137：判据的名单一漏主体就永远绿；铁律 192：禁止自来证）。
        #   把 8 层的 `墙带扣掉_m2` 抹成 0（=假装那一刀没动墙带）⇒ 守恒式必须当场破。
        # ★ 打第一条**真扣过墙带**的账（别的楼未必有 8层，也可能 8层没梯）
        with_void = {
            r["floor"] for r in mm["floors"]
            if ((r.get("n_lift_void") or 0) > 0
                and (r.get("A_lift_void_m2") or 0.0) > 0)
        }
        for z in [x for x in (mm.get("stair_clear") or [])
                  if x.get("层") in with_void
                  and (x.get("墙带扣掉_m2") or 0.0) > 0][:1]:
            z["墙带扣掉_m2"] = 0.0
            return None
        return "SKIP"
    ctl("C21 梯间账清零", c21)

    def c22(mm, zz):
        # ★ 「账**缺**了」与「账**不平**」必须分成两态（铁律 199）：整条 `stair_clear` 拿掉，
        #   判词必须是「缺 stair_clear[].墙带扣掉_m2」而不是静默当 0、也不是报守恒破。
        mm.pop("stair_clear", None)
    ctl("C22 梯间账整条缺失", c22)

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
    log("J-10.8-01 正对照 :", "PASS" if ok else "FAIL")
    # ★ 判据清单：①–⑫ 各一条函数，逐行打印、汇总、定 rc（`I.跑`）。真件读数只算一遍
    #   （`parts_list`），不再从散文里解析第二遍（铁律 174）。
    _CTX.clear()
    _CTX.update(parts=dict(parts_list), m=m, boxes=boxes, raw=RAW,
                n_geom=len(s.geometry))
    _STATE["controls_ok"] = ok                 # ★ ⑬ 读它：正对照失灵必须顶红
    rep = I.跑(_GATE, CHECKS, log=log, 宽=26,
               fix_of=lambda rule: VD.fix_of(_GATE, rule))
    _STATE["items"] = rep.items                # ★ 塞进本闸 JSON 的 "items" 键（见 `_dump`）
    _write()
    return rep.rc


def _write():
    os.makedirs(RUNDIR, exist_ok=True)
    with open(os.path.join(RUNDIR, "J-10.8-01.run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")


if __name__ == "__main__":
    sys.exit(main())
