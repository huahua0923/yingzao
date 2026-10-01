# -*- coding: utf-8 -*-
"""标准 GLB 生成器：只消费标准 floor JSON（不重新解析 DXF）。

⚠️ DATA / OUT 只是**独立运行的兜底默认值**（沿用理化楼时期的命名，勿据此判断用途）。
真正的输出路径由调用方覆盖 —— 见 backend/web/run_step.py:104-109：
  · 批次楼：bsg.DATA=data/buildings/<name>，bsg.OUT=<name>-building.glb
  · 注册表楼(理化楼)：bsg.DATA=data，bsg.OUT=lihua-building.glb
单独运行本模块会写到 OUT 默认值指向的 data/lihua-building.glb。

每层：楼板(挖楼梯井洞) + 三段墙(窗带挖窗洞) + 玻璃 + 门板 + 结构柱 + 台阶/室内楼梯 + 房间色块；
顶层：中央屋面板 + 女儿墙（outline 内缩，外皮与外墙齐）+ 翼楼屋面女儿墙（JSON 内 type=parapet 墙段）。
"""
import json
import os
import sys

import numpy as np
import shapely

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))    # backend/
from shapely.geometry import Polygon, Point, box
from shapely.ops import unary_union

from glb_common import MeshBuilder, g2, C_WALL, C_SLAB, C_ROOF, C_STAIR, C_DOOR, C_COLUMN, C_FRAME
from paths import DATA as _DATA
# ⚠ 别名必须避开 `OUT`：本模块 34 行把 `OUT` 定义成**导出文件名**（理化楼时期遗留的
# 命名），`from recognizer import outline as OUT` 会被那行覆盖成字符串 —— 于是
# `OUTLINE.floor_outline(floor)` 报 "'str' object has no attribute 'floor_outline'"。
from recognizer import outline as OUTLINE

# 窗心到墙多边形的最大距离（米），超过就不算「这个窗长在这面墙上」。
# 取 0.15：校区墙厚 0.12~0.35，窗心到墙面的距离 ≤ 半墙厚 ≈0.175，
# 而邻墙至少在半个开间之外 —— 这个阈值能容浮点误差、又排除邻墙。
NOTCH_TOL = 0.15

DATA = str(_DATA)                             # 兜底默认，调用方覆盖（run_step.py:104-109）
OUT = os.path.join(DATA, "lihua-building.glb")  # 同上；名称为理化楼时期遗留，非用途说明
ROOM_PAD = 0.05   # 房间色块贴在楼板顶上方，避免与楼板 z-fighting

# 合成窗（DXF 无窗、facade_windows 沿外墙等距生成的窗）是否导出进 GLB。
# 置 True 把 synthetic 窗开洞 + 贴玻璃 + 铝合金窗框导出。与 building.html 的
# 「窗户」开关同口径——真实窗（非 synthetic）始终导出。
INCLUDE_SYNTHETIC_WINDOWS = True

# 要从模型里**剔除**的楼层号（原始 0 基：0=一楼）。默认空 = 全建，行为与从前一致。
# 用途：某些楼的某层不想要（如 c009 第九教学楼的一楼）。
# 注意两点：
#   1. 只影响**导出**，floors/floor*.json 一个字节都不动 —— 想恢复只需清空本键；
#   2. 剩下的楼层会**重新落到地面**（z 按保留后的序号重排），不会悬空。
#      因此本键只适合踢掉**最底下若干层**；踢中间层会让上面的楼层塌下来。
SKIP_FLOORS = set()

# 碎渣墙下限（m²）：双线配对时产生的碎片多边形，面积小于该值的墙**不导出**。
# 实测（2026-09-11）c018 3340 面墙里 2478 面 < 0.1m²，占 74%、吞掉 90% 的顶点；
# c046 55%/82%、c116 48%/70%。抽顶点最多的一面看：包围盒 0.34×0.10m、面积
# 0.03m² 却写了 66 个顶点 —— 不是墙，是配对的渣。它们三角化后按三角数平方地
# 吃面数，是交付件 3.5 倍膨胀的主因。
# 取 0.05：真墙里最细的一截（0.1m 厚 × 0.5m 长）也有 0.05m²，正好卡在下限。
# **只影响 GLB 导出**，floors/floor*.json 不动；改回 0.0 即恢复全导。
MIN_WALL_AREA = 0.05

# 按面配色（`wall_side_color`）：侧面中点沿外法向探多远判内外、以及「离轮廓边界多近
# 就算外皮」的容差。后者专门吸收「轮廓照图读、墙靠配对」在梳齿凹口处的对不齐，
# 量级取一个墙厚（库内最大 0.24 的一半）。改动前先看 `wall_side_color` 的注释。
FACE_PROBE = 0.06
FACE_EDGE_GAP = 0.12

# ★ 批调开关 `GYM3D_SIDECOLOR` 定义在 `glb_common.py`（那里才是消费方：`_extrude_ring`
#   / `_ring_block` 按它决定走批调还是老路）。本文件只负责提供带 `.batch()` 的对象。


def hex_to_rgb(h):
    h = (h or "#888888").lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def build_gable_roof(b, outline, roof_y, col):
    """双坡屋顶（苏式坡顶）：沿长轴设脊，两侧坡面下到两檐，两端山墙三角封口。"""
    import numpy as np
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    w, d = maxx - minx, maxy - miny
    if w < 0.5 or d < 0.5:
        return
    rise = min(w, d) * 0.42
    horiz = w >= d
    cy = (miny + maxy) / 2
    cx = (minx + maxx) / 2

    def V(a):
        return (a[0], a[2], -a[1])   # (x, localY, height) → 世界 (x, height, -localY)

    def tri(a, b2, c):
        A = b.v(*V(a), col)
        B = b.v(*V(b2), col)
        C = b.v(*V(c), col)
        pa, pb, pc = np.asarray(V(a)), np.asarray(V(b2)), np.asarray(V(c))
        n = np.cross(pb - pa, pc - pa)
        L = float(np.linalg.norm(n))
        if L < 1e-9:
            n = np.array([0.0, 1.0, 0.0])
        else:
            n = n / L
            if n[1] < 0:
                n = -n
        b.tri_f(A, B, C, n.tolist(), col)

    if horiz:
        tri([minx, miny, roof_y], [maxx, miny, roof_y], [maxx, cy, roof_y + rise])
        tri([minx, miny, roof_y], [maxx, cy, roof_y + rise], [minx, cy, roof_y + rise])
        tri([minx, cy, roof_y + rise], [maxx, cy, roof_y + rise], [maxx, maxy, roof_y])
        tri([minx, cy, roof_y + rise], [maxx, maxy, roof_y], [minx, maxy, roof_y])
        tri([minx, miny, roof_y], [minx, cy, roof_y + rise], [minx, maxy, roof_y])
        tri([maxx, miny, roof_y], [maxx, maxy, roof_y], [maxx, cy, roof_y + rise])
    else:
        tri([minx, miny, roof_y], [minx, maxy, roof_y], [cx, maxy, roof_y + rise])
        tri([minx, miny, roof_y], [cx, maxy, roof_y + rise], [cx, miny, roof_y + rise])
        tri([cx, miny, roof_y + rise], [cx, maxy, roof_y + rise], [maxx, maxy, roof_y])
        tri([cx, miny, roof_y + rise], [maxx, maxy, roof_y], [maxx, miny, roof_y])
        tri([minx, miny, roof_y], [cx, miny, roof_y + rise], [maxx, miny, roof_y])
        tri([minx, maxy, roof_y], [maxx, maxy, roof_y], [cx, maxy, roof_y + rise])


def load_floors():
    """读取 floors/floorN.json（剔除 SKIP_FLOORS），按层号升序。

    起点取**实际存在的最小层号**，不再从 0 起数、遇到缺号就 break。为什么必须改：
    「图 ≠ 层」的楼（c009 第 0 张图是学术报告厅自己的图，已并进 1/2 层）里 floor0.json
    是不该存在的；而旧写法第一个文件就缺号 → 整个 while 立刻中断 → 一层都读不到 →
    GLB 直接 SystemExit（报「未找到 floors/floor*.json」，看着像文件没了，其实是循环断了）。
    缺号只告警不阻断：真正的「楼层集合」由 recognize 写盘决定，不靠命名连续性推断。
    """
    pairs = []
    fdir = os.path.join(DATA, "floors")
    for fn in os.listdir(fdir) if os.path.isdir(fdir) else []:
        if not (fn.startswith("floor") and fn.endswith(".json")):
            continue
        num = fn[5:-5]
        if num.isdigit() and int(num) not in SKIP_FLOORS:
            pairs.append((int(num), os.path.join(fdir, fn)))
    pairs.sort()
    if pairs:
        nums = [n for n, _ in pairs]
        if nums != list(range(nums[0], nums[0] + len(nums))):
            print(f"   ⚠ 楼层号不连续: {nums}（按现有文件继续，缺口不自动补）")
    floors = []
    for _n, path in pairs:
        with open(path, encoding="utf-8") as f:
            floors.append(json.load(f))
    if not floors:
        raise SystemExit(f"未找到 floors/floor*.json（或全被 skip_floors={sorted(SKIP_FLOORS)} 跳过）")
    return floors


def load_spec():
    path = os.path.join(DATA, "spec.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    # 兜底（与 building.html DEFAULT_SPEC 一致）
    return {
        "floor_h": 4.2, "slab_t": 0.2, "wall_h": 4.0,
        "outer_wall_t": 0.30, "inner_wall_t": 0.24,
        "door_h": 2.1, "door_panel_t": 0.05,
        "column_w": 0.5, "column_d": 0.5,
        "win_sill": 0.9, "win_h": 1.5, "win_w": 2.0, "win_spacing": 6.5,
        "win_in_depth": 0.40, "win_out": 0.06, "glass_t": 0.04, "win_frame_t": 0.06,
        "win_margin": 1.5, "win_min_seg": 3.5, "win_min_run": 2.0,
        "roof_t": 0.2, "parapet_h": 0.9, "parapet_t": 0.5,
        "stair_landing": 0.15,
    }


def window_notch(win, S):
    """窗洞 2D 凹口：沿墙方向 w 宽，横跨 -win_out(外) ~ +win_in_depth(内)。"""
    half = win["w"] / 2
    out, inD = S["win_out"], S["win_in_depth"]
    dx, dy = win["dx"], win["dy"]
    nx, ny = win["nx"], win["ny"]
    return Polygon([
        (win["x"] + dx * half - nx * out, win["y"] + dy * half - ny * out),
        (win["x"] - dx * half - nx * out, win["y"] - dy * half - ny * out),
        (win["x"] - dx * half + nx * inD, win["y"] - dy * half + ny * inD),
        (win["x"] + dx * half + nx * inD, win["y"] + dy * half + ny * inD),
    ])


def _bbox_hit(a, b):
    """两个包围盒是否相交（(minx,miny,maxx,maxy)）。"""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


class _FaceSideColor:
    """按**面的朝向**给墙的侧面配色（= SU「材质贴在面的一侧上」，不按构件类型）。

    SU 的规矩：材质是按面上的一侧贴的，同一面墙朝外那张面是外墙涂料、朝内那张面
    是室内乳胶漆 —— 「墙」在几何上没有外墙/内墙之分，只有「这张面朝哪」。
    照搬过来：侧面中点沿**外法向**探 `probe` 米，落在轮廓外 → 外墙色；落在轮廓内
    且**离轮廓边界比 `gap` 还远** → 室内色（详见下面为什么要有 gap）。

    为什么不能继续用 `w["type"]` 上色：type 是识别期的**归属分类**，不是这堵墙两侧
    各自的朝向。type=="outer" 的整条墙刷外墙色，等于把朝室内那面也刷成红砖。

    **为什么要有 `gap`（判据的二级）**：轮廓是**照图读的**、墙是**配对出来的**，两者
    在梳齿凹口处对不齐 —— ny27 北侧 6 个凹口，图上轮廓是斜着收进的线
    `(5.670,3.482)→(6.008,2.617)→(6.825,2.282)`，而配对出的墙是直条
    `y[2.162,2.282]`，外皮差 0.03~0.09m。只用「探针在轮廓外」这一条，那面真外皮会
    整片判成室内色（实测光 ny27 F0 就有 4 张外皮这样，北立面变成斑驳的米白）。
    「一张面离轮廓边界不到一个墙厚」= 它就是外皮（`gap=FACE_EDGE_GAP=0.12`≈库内最大
    墙厚 0.24 的一半），这一条把凹口那几面救回来，同时离边界 0.21m 以上的室内面
    仍然判成室内 —— 实测两极是 0.034（外皮）与 0.214（室内面），中间留了一倍余量。

    **为什么要批调 + 记忆**（2026-09-13）：`_b_prof.py` 实测 c017 里这个判定被调
    **139,104 次 = 7.09s / 17.06s = 41.6%**，是全楼最大的单一热点。而那 ~51µs/次 里，
    GEOS 谓词本身只占一半 —— `Point` 构造 3.55s + shapely 装饰器派发 2.19s 是
    **逐次调用的固定开销**，跟判几个点无关。批调把这两块摊掉：
    `_scratch/_sidecolor_vec_probe.py` 实测 c017 21.5×、c054 27.7×、ny27 19.0×，
    **且三个楼逐点比对颜色全等**（判据是逐点，不是"没报错"）。

    ★ 批的粒度只能是**环**：一层楼的墙共用一套闭包（同一份 ref/bnd），一个环 3~68 段。
      「按整层批」更快（21~35×）但要把上色推迟到整层建完，而那会改顶点/面的发射顺序
      ⇒ 交付字节变，不值当。「环」这一级单独只有 4.1~8.1×（47~70% 的环 ≤4 段，
      固定开销吃掉大半），所以再加一层记忆：`build_walls` 对**同一个 `poly` 挤出三次**
      （墙裙 w0→sill_top、窗间 sill_top→win_top、过梁 win_top→wall_top），三次的环、段、
      法向**逐位相同** ⇒ 颜色必然相同，实测 66% 的调用是这种重复。

    记忆键是实参数组的**字节**，不是四舍五入后的近似：字节全同 ⇔ 探针点逐位相同
    ⇔ GEOS 结果逐位相同。反向不成立也不要紧（`-0.0`/`0.0` 会各存一份）——
    漏命中只是少省一点，**永远不会给出错答案**。
    """

    #: 与 `glb_common.MeshBuilder._extrude_ring` / `_ring_block` 的接口契约：
    #: 两者在 `col_fn` 有 `.batch()` 时改成整环批调，实参顺序 (lx0,ly0,lx1,ly1,nx,ny)。
    #: 改这里的签名必须同时改那两处（它们互为镜像，见 `_ring_block` 的注释）。
    __slots__ = ("_ref", "_bnd", "_probe", "_gap",
                 "_wall", "_inner", "_wall_u8", "_inner_u8", "_cache")

    def __init__(self, ref, bnd, probe, gap, wall_col, inner_col):
        self._ref, self._bnd = ref, bnd
        self._probe, self._gap = probe, gap
        # 标量回退口返回的就是这两个列表**本身**（与改动前逐字相同）
        self._wall, self._inner = wall_col, inner_col
        self._wall_u8 = np.asarray(wall_col, dtype=np.uint8)
        self._inner_u8 = np.asarray(inner_col, dtype=np.uint8)
        self._cache = {}

    def __call__(self, lx0, ly0, lx1, ly1, nx, ny):
        """单点判定（`GYM3D_SIDECOLOR=0` 的回退路，语义与旧闭包逐字相同）。"""
        if self._ref is None:
            return self._inner
        p = Point(0.5 * (lx0 + lx1) + nx * self._probe,
                  0.5 * (ly0 + ly1) + ny * self._probe)
        if self._ref.contains(p) and self._bnd.distance(p) > self._gap:
            return self._inner
        return self._wall

    def batch(self, A):
        """A: (m,6) float64 的 `(lx0,ly0,lx1,ly1,nx,ny)` → (m,3) uint8。

        只在批调路被调用（`glb_common.SIDECOLOR_BATCH`）；关掉时调用方直接走
        `__call__`，本方法不会被看见 —— 开关不在这一层判，免得两处漂移。
        """
        m = len(A)
        if m == 0:
            return np.empty((0, 3), dtype=np.uint8)
        key = A.tobytes()
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        C = self._compute(A)
        self._cache[key] = C
        return C

    def _compute(self, A):
        m = len(A)
        if self._ref is None:
            return np.tile(self._inner_u8, (m, 1))
        lx0, ly0, lx1, ly1, nx, ny = (A[:, i] for i in range(6))
        # ★ 与 `__call__` 逐字同序的算点式（同结合顺序、无 FMA 收缩），
        #   浮点结果逐位相同 —— 这不是"等价变形"，是同一串 IEEE754 运算。
        px = 0.5 * (lx0 + lx1) + nx * self._probe
        py = 0.5 * (ly0 + ly1) + ny * self._probe
        inside = shapely.contains_xy(self._ref, px, py)
        # 距离只对在轮廓内的点有影响（标量那边靠 `and` 短路），但整批算一次比
        # 「先筛再算」再起一次 GEOS 调用便宜，且结果与短路版逐位相同。
        dist = shapely.distance(self._bnd, shapely.points(px, py))
        return np.where((inside & (dist > self._gap))[:, None],
                        self._inner_u8, self._wall_u8)


def wall_side_color(ol, wall_col, inner_col, probe=FACE_PROBE, gap=FACE_EDGE_GAP):
    """建一个 `_FaceSideColor`（判据与用法见该类注释）。

    `ref` 是**外扩 0.02m** 的轮廓（用来判"在不在里面"，容一点配对误差），
    `bnd` 是**原轮廓**的边界（用来量"离边界多远"）—— 两者刻意不是同一个几何。
    """
    ref = ol.buffer(0.02) if ol is not None and not ol.is_empty else None
    bnd = ol.boundary if ref is not None else None
    return _FaceSideColor(ref, bnd, probe, gap, wall_col, inner_col)


# 中间屋面女儿墙的最小暴露面积（㎡）。小于它的「暴露面」是两块轮廓边界微错位
# 产生的碎屑，不值得围着立一圈墙。
ROOF_MIN_AREA = 2.0

# 檐口/雨棚板外挑（米）与最小面积（㎡）：自由柱（上方无楼层）的凸包外扩这么多作屋檐板。
# 1.5m 依据：c085/c079/c083 的檐廊进深 2.7~3.2m、柱距 3.0~4.2m，柱心到檐口边实测 1.2~1.6m。
EAVE_OVERHANG = 1.5
EAVE_MIN_AREA = 4.0


def _outline_band(poly, th):
    """轮廓整体内缩 `th` 再挖掉内环 → 闭合的一圈实体环（`add_parapet` 的同款做法）。

    内缩用 mitre(join_style=2) + mitre_limit=2.0：给 mitre_limit 是**必须**的，
    GEOS 默认上限 5.0 遇到锐角会把角点沿角平分线甩出好几米（c018 翼楼屋面实测）；
    取 2.0 让 90° 楼角保持**尖角**（取 1.0 会把每个直角都倒角，楼一圈全是缺口），
    同时把锐角尖刺压到 ≤0.74m。与 `MeshBuilder.add_parapet` 同一口径，两处不能一个
    用 mitre 一个用默认。

    比 2×th 还窄的条带内缩即消失 → 退化成整块：宁可压满，也**绝不外挑**
    （外挑会凭空长出建筑 bbox，立面图上沿口比外墙外皮鼓出半米 —— 2026-09-12 查实）。
    """
    if poly is None or poly.is_empty:
        return poly
    inner = poly.buffer(-th, join_style=2, mitre_limit=2.0)
    if inner.is_empty or inner.area <= 0:
        return poly
    return poly.difference(inner).buffer(0)


# ★ 2026-09-30 「屋顶层平面带」的**体量轮廓**（≠ 它的平面轮廓）
#
# 实测（c006）：F6 是裙楼的**屋顶层平面**（图纸 7 层 = 裙房屋面），它的 `outline` =
# 5380.6㎡（整块裙房平面），可它这一带**立着的体量**只有塔楼 913.1㎡。下游两处把
# `outline` 当成体量用，于是同一张裙房屋面被**铺了两遍**：
#   · `build_slab(below_outline=...)` 的 `_extra = below_outline - slab`
#       → 在 z=24.5（F7 标高）凭空多出 **4467.6㎡** 的板
#   · 第一个女儿墙环 `extra = f_lo - f_hi`
#       → 同一标高多出 **275.5㎡** 女儿墙（`_c006_roof_layers.txt` 实测）
# 而 21.0（F6 标高）那张才是真裙房屋面（4473.1㎡ 屋面 + 塔楼那块楼板），
# 塔楼自己的屋面在 38.5（916.4㎡）。**三条独立证据**：F6 rooms=0（全栋唯一）、
# 图上 F7 房号是 `6-C-08-xx`（第 8 层 ⇒ 裙房到 6 层、顶在 21.0）、
# 塔楼外 21.2~24.5 之间只有 186 件 / 17.7m³（没有第 7 层裙房）。
#
# 判据（三条**同时**成立才认作屋顶层平面带；全库 92 栋实测**只命中 c006 F6 一处**，
# 见 `_scratch/_fleet_zeroroom_census.txt`）：
#   ① 本带**一个房间都没有** —— 可居住楼层不会这样，屋顶平面图不落房间；
#      （单看这一条会误伤 20 栋：c037/c074/c075/c005 是整栋房间没识别出来）
#   ② 平面轮廓与**下一带重合**（本带没有新增任何占地）—— 容差 2%；
#   ③ 上一带轮廓**远小于**本带（≤60%）—— 上面只剩下塔楼。
# ⇒ 这样的带，它的**体量** = `outline(k) ∩ outline(k+1)`（真正往上延续的那部分）。
ROOFPLAN_SAME_TOL = 0.02
ROOFPLAN_UP_MAX = 0.60


def _band_mass_outline_raw(floors, k):
    """第 k 带的**体量**轮廓（只按平面图判，未剔屋面补块）—— 对外请用 `band_mass_outline`。

    只给两个消费者用：`build_slab(below_outline=)` 与「下层露出屋面」的女儿墙环。
    两处问的都是同一件事 —— 「**下一带的体量**伸到哪里」。
    """
    fp = OUTLINE.floor_outline(floors[k]) if 0 <= k < len(floors) else None
    if fp is None or fp.is_empty or fp.area <= 0 or k + 1 >= len(floors):
        return fp
    if floors[k].get("rooms"):                              # ① 有房间 ⇒ 真楼层
        return fp
    up = OUTLINE.floor_outline(floors[k + 1])
    if up is None or up.is_empty or up.area <= 0:
        return fp
    if up.area / fp.area > ROOFPLAN_UP_MAX:                 # ③ 上一带不小 ⇒ 不是
        return fp
    # ② 与**下一带**重合 —— 本条是承重条，且它**必须有下一带**才能问：
    #    「这一带是下面那一带的屋顶平面图」的前提就是存在"下面那一带"。
    #    底部带（k=0）没有下一带，它自己就是建筑的底块 ⇒ 轮廓即占地，无从修正。
    #    （自证实测：漏掉这条 k>0 会多动 6 栋 —— c053 会删掉 5394㎡ 的板、
    #      c020 删 1379㎡、c012f1 删 397㎡，全是真屋顶。）
    if k <= 0:
        return fp
    dn = OUTLINE.floor_outline(floors[k - 1])
    if dn is None or dn.is_empty or dn.area <= 0:
        return fp
    if abs(fp.area - dn.area) / max(fp.area, dn.area) > ROOFPLAN_SAME_TOL:
        return fp
    _m = fp.intersection(up).buffer(0)
    if _m.is_empty or _m.area <= 0:
        return fp
    print("    ⚠ 屋顶层平面带 F%s：平面 %.1f㎡ 是**屋顶平面**、体量只有 %.1f㎡"
          "（与上一带重合部分）⇒ 按体量出板/女儿墙"
          % (floors[k].get("floor"), fp.area, _m.area))
    return _m


# ★ 2026-09-30 `roof_rooms` 的补块**不是本带的体量** —— 它是**下面体量的顶**。
#
# 判例（用户原话）：「后面那个八角楼顶子也不对」。
# `recognizer/floor.py` 会把 `profile.roof_rooms[k]` 里那些房号的**面**并进第 k 带的
# `outline`：c006 八角厅是 1~4 层的实体体量，它的楼顶**就是 5 层（F4）的楼板**，
# 而 5 层图上没有这一块（图纸面积表 4 层 5880.48 → 5 层 5350.10，差的 530.4㎡ 正是
# 八角厅那块）⇒ 按 4 层报告厅房号 `6-C-04-05` 的面补进来。
# 这块面**不是第 k 带的体量**：它的标高就在第 k 带自己的楼面（z_k）上，第 k 带自己的
# 板已经把它铺成屋面色了。可下游两处都拿 `outline` 当体量用 ⇒ 同一块面在**下一个**
# 标高 z_{k+1} 又铺一遍（c006 实测：z=17.5 多出 283.5㎡ 板 + 0.9m 高的一圈女儿墙）。
# 这正是 profile 自己 `_note_outline_unify` 早就写下的那条禁忌 ——
# 「把 5 层也统一进来 …会让**6 层楼板也铺到八角厅屋面上**，等于把露台封死」：
# 当年把 `outline_unify_floors` 清空了，可 `below_outline` 这条路上它又回来了。
#
# ⇒ 体量 = `outline(k) − 补块`。全库 92 栋**只有 c006 的 profile 有 roof_rooms**，
#   作用面可证为 {c006 F4} 一处（`_scratch/_band_sweep_{before,after}.json` 逐带比对：
#   99 栋 459 带里变动的**恰好**是 c006:k=4，5633.9 → 5350.4㎡）。
#
# ⚠ 代价（写在这里、不埋着）：剔掉补块后，第 5 带**仍会**出 2.14㎡ 的板与女儿墙 ——
#   那不是八角厅，是 `outline_4` 与 `outline_5` 两条等长轮廓之间的**识别噪声**
#   （26 片发丝，最长 20m×0.05m，散布全楼外沿，离八角厅最近 16.3m）。
#   它在本次改动**之前就存在**（藏在那 285.7㎡ 里），本次一动没动，`ROOF_MIN_AREA`
#   的阈值也没动 —— 要收它得另立一条判据，而那条会动到全库每一带，不混在这一刀里。
ROOF_PATCH_CACHE = {}


def _roof_patch_faces(floor_no):
    """第 `floor_no` 带的**屋面补块**（`profile.roof_rooms` 里那些房号的面）。

    来源与 `recognizer/floor.py` **同一份、同一个房号**（补块是那里并进 outline 的，
    这里不另立口径）。取不到就 `None` 并**出声** —— 安静地不剔等于把幻影板悄悄放回来。
    """
    key = (DATA, floor_no)
    if key in ROOF_PATCH_CACHE:
        return ROOF_PATCH_CACHE[key]
    out = None
    rr = {}
    try:
        with open(os.path.join(DATA, "profile.json"), encoding="utf-8") as f:
            rr = json.load(f).get("roof_rooms") or {}
    except (OSError, ValueError) as e:
        print("    ⚠ 读不到 profile.json（%s）⇒ roof_rooms 补块没剔" % e)
    nums = rr.get(floor_no) or rr.get(str(floor_no)) or []
    if nums:
        try:
            with open(os.path.join(DATA, "rooms.json"), encoding="utf-8") as f:
                rooms = json.load(f)
        except (OSError, ValueError) as e:
            print("    ⚠ 读不到 rooms.json（%s）⇒ roof_rooms 补块没剔" % e)
            rooms = []
        polys = []
        for rn in nums:
            hit = [r for r in rooms if str(r.get("number")) == str(rn)]
            if not hit:
                print("    ⚠ roof_rooms F%s：房号 %s 在 rooms.json 里找不到 ⇒ 补块没剔"
                      "（体量可能偏大）" % (floor_no, rn))
                continue
            b = hit[0].get("boundary") or hit[0].get("poly") or []
            if len(b) < 3:
                print("    ⚠ roof_rooms F%s：房号 %s 没有 boundary ⇒ 补块没剔"
                      % (floor_no, rn))
                continue
            p = Polygon(b)
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty:
                polys.append(p)
        if polys:
            out = unary_union(polys).buffer(0)
    ROOF_PATCH_CACHE[key] = out
    return out


def _strip_roof_patches(floors, k, mass):
    """从第 k 带的体量里剔掉 `roof_rooms` 补块（上面那段注释的落点）。"""
    if mass is None or mass.is_empty or not (0 <= k < len(floors)):
        return mass
    patch = _roof_patch_faces(floors[k].get("floor"))
    if patch is None or patch.is_empty:
        return mass
    hit = mass.intersection(patch).buffer(0)
    if hit.is_empty or hit.area < ROOF_MIN_AREA:
        return mass
    out = mass.difference(patch).buffer(0)
    print("    ⚠ 屋面补块 F%s：平面的 %.1f㎡ 是**下面体量的顶**（roof_rooms）"
          "⇒ 不算本带体量（%.1f → %.1f㎡）"
          % (floors[k].get("floor"), hit.area, mass.area, out.area))
    return out


def band_mass_outline(floors, k):
    """第 k 带的**体量**轮廓 = 上面的原始结果 **再剔掉屋面补块**。

    两处消费者都要的是「下一带的体量伸到哪里」：补块是**下面体量的顶**、
    不是本带的体量（见上方注释），所以两条路都必须走这一层。
    """
    return _strip_roof_patches(floors, k, _band_mass_outline_raw(floors, k))


def build_walls(b, floor, z, S, wall_col, inner_col, roof_col, parapet_col=None):
    """三段墙 + 玻璃。每片墙（已合并，含中庭洞）分别三段挤 + 窗洞。

    颜色**按面**定（`wall_side_color`）：朝建筑外的侧面 = facade，朝内的 = inner，
    不按 `w["type"]` 整条刷一个色。上下盖仍按墙类（藏在楼板/屋面板之间、看不见）。
    女儿墙贴本层楼板标高 parapet_col（压顶色）—— 但它的**外侧**面同样按朝向取 facade。

    `parapet_col` 缺省回落 `roof_col`（只是给仓外旧调用点留的兼容位）。
    生产调用点**必须显式给** `style.parapet`：`su_spec_floors` 的类别表是**按 cap
    颜色**反推类别的（`("parapet","屋顶","女儿墙")` vs `("roof","屋顶","屋面")`），
    给成 roof_col 会让这圈墙落进「屋面」二级组 —— 用户在 SU 里点「隐藏女儿墙」时
    它不跟着藏（静默失效），且与 `_sub_names` 的这条设计相悖：「屋面 slab / 女儿墙
    同类别时必须靠二级组分开，否则 SU 合并共面面会把被盖住的那块整个删掉」。"""
    walls = floor["walls"]
    parapet = [w for w in walls if w["type"] == "parapet"]
    solid = [w for w in walls if w["type"] != "parapet"]

    ol = OUTLINE.floor_outline(floor)
    side_col = wall_side_color(ol, wall_col, inner_col)

    w0 = z + S["slab_t"]
    sill_top = w0 + S["win_sill"]
    win_top = sill_top + S["win_h"]
    wall_top = w0 + S["wall_h"]

    wins = [w for w in floor["windows"] if INCLUDE_SYNTHETIC_WINDOWS or not w.get("synthetic")]

    # 窗洞**按几何**挂到墙上，不靠 win["wallId"] == wall["id"]。
    # 原写法在这里踩了两重坑：
    #   1. 墙重配（薄墙化）后整栋墙被换成不带 id 的新 dict，`w["id"]` 直接 KeyError ——
    #      实测 49 栋里 41 栋一开窗就崩，这才是窗户从没进过交付件的真因；
    #   2. 即便不崩，id 也大面积对不上（c043 有 48 个窗匹配失败）。
    # 而 window_notch 只用窗自己的 x/y/dx/dy/nx/ny/w，本就自足。
    #
    # 判据用「**窗心落在墙上**」而不是「凹口与墙相交」：
    # 凹口往室内伸 win_in_depth=0.40，比墙厚还大，用相交判会误伤 0.4m 内的邻墙
    # （多挖墙 + 布尔运算量爆炸，实测 c019 卡死 >7 分钟）。窗心到墙面的距离
    # 只取决于墙厚（≤0.175），阈值 0.15 既容得下浮点误差又排除得了邻墙。
    # 凹口只挖中间那段墙（下段墙裙、上段过梁保持实心）。
    win_pts = []
    notches = []
    for win in wins:
        half = win["w"] / 2.0
        win_pts.append((Point(win["x"], win["y"]),
                        (win["x"] - half, win["y"] - half,
                         win["x"] + half, win["y"] + half)))
        notches.append(window_notch(win, S))

    dropped = 0
    for w in solid:
        poly = Polygon(w["poly"], [h for h in (w.get("holes") or []) if len(h) >= 4])
        if poly.area < MIN_WALL_AREA:
            dropped += 1          # 配对碎渣，见 MIN_WALL_AREA 注释
            continue
        # 上下盖的色只影响「从上往下看墙顶」的极窄一圈（墙顶被楼板/屋面板盖住），
        # 但露天的女儿墙顶看得见，故按墙类给：外墙盖给外墙色，其余给室内色。
        cap = wall_col if w["type"] == "outer" else inner_col
        wb = poly.bounds
        win_poly = poly
        for (pt, pb), notch in zip(win_pts, notches):
            if _bbox_hit(wb, pb) and poly.distance(pt) <= NOTCH_TOL:
                # ⚠️ 兜底（2026-09-15 c104 实测）：墙 poly / 窗洞 notch 只要有一个**自交非法**，
                #    `difference` 就抛 `GEOSException: TopologyException: side location conflict`
                #    （c104 在 (-45.60, 12.88) 炸的），整栋 GLB 直接不出。这里先 `buffer(0)`
                #    清洗再相减；再失败就跳过这扇窗的洞（宁可少一个窗洞，不能整栋不出模型）。
                try:
                    win_poly = win_poly.difference(notch)
                except Exception:  # noqa: BLE001  GEOSException / 拓扑冲突
                    try:
                        win_poly = win_poly.buffer(0).difference(notch.buffer(0))
                    except Exception:  # noqa: BLE001
                        continue
        b.add_region(poly, w0, sill_top, cap, col_side=side_col)
        b.add_region(win_poly, sill_top, win_top, cap, col_side=side_col)
        b.add_region(poly, win_top, wall_top, cap, col_side=side_col)
    for win in wins:
        b.add_glass(win, w0, S)
        b.add_frame(win, w0, S, C_FRAME)

    # 翼楼屋面女儿墙（轮廓外真实墙段，贴本层楼板标高 z）：侧面同样按朝向——
    # 朝外那张面就是立面的一部分，不该整段刷成屋面色；顶面用 parapet_col（压顶）。
    pc = parapet_col if parapet_col is not None else roof_col
    for w in parapet:
        # **带洞**：退台屋面的女儿墙是「屋面外缘 − 内缩 t」的环带，中间是塔楼/上层主体。
        # 只给 exterior 就等于把整块屋面填成实心板（GLB 会长出一块盖住整个裙楼屋面的板，
        # SU 同源同错）。普通墙的 `Polygon(w["poly"])` 不动 —— 那是既有行为，改它会
        # 把 48 栋现交付件里带中庭洞的墙挖开，超出本次改动面。
        pp = Polygon(w["poly"], w.get("holes") or [])
        if pp.area < MIN_WALL_AREA:
            dropped += 1
            continue
        b.add_region(pp, z, z + w["height"], pc, col_side=side_col)
    return dropped


def shaft_holes(floor):
    """楼板上要挖的**竖井洞**：楼梯井 + 电梯井，产出统一的 `(x0, yBot, x1, yTop)`。

    楼梯井用 `stairwells[i]["shaft"]`（识别期已经扩到墙的井道），**不是** `x0/x1/yBot/yTop`
    （那只是踏步包围盒）。用后者会把井口盖掉一半：实测 c027 顶层该层只识别到「到达」
    的那一跑（3.6×2.5），按包围盒挖洞后西侧半口井是实心板，从上往下看就是个盖子。
    旧数据没有 `shaft` 键时回退到包围盒（与改造前逐位等价）。

    电梯井（`elevators`）在原实现里**没有消费者** —— 识别得再准，模型上也是个实心盖子。
    它的键是 `x0/y0/x1/y1`（本地米，与楼梯井同坐标系），这里只做键名映射，坐标不动。
    """
    for s in floor.get("stairwells") or []:
        h = s.get("shaft") or s
        yield h["x0"], h["yBot"], h["x1"], h["yTop"]
    for e in floor.get("elevators") or []:
        yield e["x0"], e["y0"], e["x1"], e["y1"]


def build_slab(b, floor, z, S, up_outline=None, roof_col=None, split_roof=True,
               below_outline=None):
    """楼板 + 竖井洞（楼梯井 + 电梯井，见 `shaft_holes`）。

    `floor > 0` 才挖：首层楼板是地面（楼梯从它起步、电梯底坑在它下面），不挖。

    ★ 井洞必须**完全落在楼板内**（2026-09-14 c006 实测）：`shaft` 是「踏步盒四向扩到墙」，
    走廊开口那一侧会一路扩到**走廊对面的墙**上（c006 F1 中央两口楼梯间：踏步盒 23.7㎡ →
    shaft 35.6㎡），扩出来的洞跨过楼板轮廓边界后，`difference` 就只剩「楼板边上缺一大块」，
    从上往下看正是「被啃掉一角的大坑」。判据 = 洞与轮廓的差集面积；超限就退回该井的
    **踏步盒**（图上门真实画出来的范围），绝不把洞开到楼板外。
    """
    slab = OUTLINE.floor_outline(floor)      # 多块楼层（双塔/双翼）两块都要铺板
    if floor["floor"] > 0:
        for s in floor.get("stairwells") or []:
            h = s.get("shaft") or s
            hole = box(h["x0"], h["yBot"], h["x1"], h["yTop"])
            if hole.difference(slab).area > 0.01:
                hole = box(s["x0"], s["yBot"], s["x1"], s["yTop"])
            slab = slab.difference(hole)
        for e in floor.get("elevators") or []:
            hole = box(e["x0"], e["y0"], e["x1"], e["y1"])
            if hole.difference(slab).area > 0.01:
                continue                       # 电梯井出楼板：宁可不开洞，也不啃楼板边
            slab = slab.difference(hole)
    # ★ 中庭开洞：通高中庭的楼层楼板挖穿（房号见 profile.atrium_rooms → floors.atrium_holes）
    for _h in floor.get("atrium_holes") or []:
        if len(_h) >= 3:
            _p = Polygon(_h)
            if not _p.is_valid:
                _p = _p.buffer(0)
            if not _p.is_empty:
                slab = slab.difference(_p)
    # ★ 面层按「上面有没有楼层」**同标高切开**（用户判据 2026-09-15）：
    #   「中间是楼板，因为上面还有楼层；其他是屋顶，因为上面没有楼层」。
    # 切法：本层楼板 ∩ 上层轮廓 = 楼板色（C_SLAB）；差集 = 屋面色（roof_col）。
    # 两块**同一标高、同厚度**（z 起、slab_t 厚），不是叠一层薄片 —— 那样会在交界处留台阶/缝，
    # 用户明确要求「不和中间隔开」。首层不切（`i==0` 传 split_roof=False）：首层楼板就是地面，
    # 露出来的那块是室外场地，不是屋面。
    #
    # ★★ 2026-09-16 用户判据「**每层的楼板是怎么生成的**」—— 本层标高上的这块板不只是
    #   "本层的楼面"，它还要**盖住下层露出来的那部分**（下层 footprint − 本层 footprint），
    #   那部分正是下层的**屋面**（退台/群房/裙楼的顶）。不加这一块，从上往下看就是个洞
    #   （用户原话：「两翼的楼顶也没有了」「屋顶没有」）。
    #   口径：先挖本层的井洞（洞只在本层 footprint 内），**再**并上下层露出来的那块 ——
    #   顺序不能反，否则下层的井洞会被挖到露出来的屋面上。
    if below_outline is not None and not below_outline.is_empty:
        _extra = below_outline.difference(slab).buffer(0)
        if not _extra.is_empty and _extra.area >= ROOF_MIN_AREA:
            slab = slab.union(_extra).buffer(0)
    if split_roof and roof_col is not None and up_outline is not None and not up_outline.is_empty:
        covered = slab.intersection(up_outline).buffer(0)
        exposed = slab.difference(up_outline).buffer(0)
        # 逐块出：交/差会产生 MultiPolygon（覆盖区被井洞切成几块），整块丢给 add_slab 会让
        # SU 侧「一块板 = 2 面」的件数校验对不上（实测 faces_bad）。这里拆成单块各出一件。
        for _poly, _col in ((covered, None), (exposed, roof_col)):
            if _poly is None or _poly.is_empty:
                continue
            _parts = [_poly] if _poly.geom_type == "Polygon" else \
                [g for g in getattr(_poly, "geoms", []) if g.geom_type == "Polygon"]
            for _g in _parts:
                if _g.is_empty or _g.area <= 1e-6:
                    continue
                # ⚠️ `col=None` 会走进 add_slab 的默认参数判定并触发
                #    `ValueError: setting an array element with a sequence`
                #    （全库 45/45 栋一起挂在这里），覆盖区必须走"不传颜色"的那条调用。
                if _col is None:
                    b.add_slab(_g, z, S["slab_t"])
                else:
                    b.add_slab(_g, z, S["slab_t"], _col)
    else:
        b.add_slab(slab, z, S["slab_t"])


def build_rooms(b, floor, z, S):
    # 中庭开洞处的房间是**空间**（图上登记了面积，但没有楼板）→ 不铺地垫
    _skip = set()
    for _h in floor.get("atrium_holes") or []:
        _skip.add(tuple(round(v, 2) for v in (Polygon(_h).centroid.x, Polygon(_h).centroid.y)))
    for r in floor["rooms"]:
        _c = Polygon(r["poly"]).centroid
        if (round(_c.x, 2), round(_c.y, 2)) in _skip:
            continue
        b.add_region(Polygon(r["poly"]), z + S["slab_t"], z + S["slab_t"] + ROOM_PAD, C_SLAB)


def build_columns(b, floor, z, S):
    h = S["wall_h"]
    for c in floor["columns"]:
        b.add_box(c["x"], z + S["slab_t"] + h / 2, -c["y"], c["w"], h, c["d"], 0.0, C_COLUMN)


def build_doors(b, floor, z, S, wall_col, inner_col, door_col):
    t = S["door_panel_t"]
    w0 = z + S["slab_t"]
    wall_top = w0 + S["wall_h"]
    # 过梁也是墙（门洞上补回的那截），侧面同样按朝向配色——与 build_walls 同一判据。
    side_col = wall_side_color(OUTLINE.floor_outline(floor), wall_col, inner_col)
    for d in floor["doors"]:
        h = d.get("h", S["door_h"])
        cy = w0 + h / 2
        if d["horiz"]:
            b.add_box(d["x"], cy, -d["y"], d["w"], h, t, 0.0, door_col)
        else:
            b.add_box(d["x"], cy, -d["y"], t, h, d["w"], 0.0, door_col)
        # 门头过梁：门洞在 wall.poly 里是挖穿到墙顶的 gap（floor.py「门=gap」），
        # 这里在门顶以上补回墙，使门洞只到门高、其上有墙。
        # 过梁厚度必须 = 墙厚（外 0.30 / 内 0.24），居中在门中心线 d.x/d.y 上——
        # 不能用 bx0..by1（那是 door_depth=0.5m 的门洞盒，比墙厚宽，会把梁撑宽凸出墙外）。
        door_top = w0 + h
        if door_top < wall_top:
            col = wall_col if d.get("outer") else inner_col   # 只作过梁顶/底盖色

            wall_t = S["outer_wall_t"] if d.get("outer") else S["inner_wall_t"]
            half = d["w"] / 2
            ht = wall_t / 2
            if d["horiz"]:
                lintel = Polygon([
                    (d["x"] - half, d["y"] - ht), (d["x"] + half, d["y"] - ht),
                    (d["x"] + half, d["y"] + ht), (d["x"] - half, d["y"] + ht),
                ])
            else:
                lintel = Polygon([
                    (d["x"] - ht, d["y"] - half), (d["x"] + ht, d["y"] - half),
                    (d["x"] + ht, d["y"] + half), (d["x"] - ht, d["y"] + half),
                ])
            b.add_region(lintel, door_top, wall_top, col, col_side=side_col)


def build_entry_stairs(b, floor, z):
    for i, s in enumerate(floor["stairs"]):
        top = 0.60 - i * 0.15
        back = s["nosing"] - 0.30
        depth = s["nosing"] - back
        b.add_box(0.0, z + top - 0.075, -(back + depth / 2), 2 * s["hw"], 0.15, depth, 0.0, C_STAIR)


# 楼梯踢面高的合规区间（m）。GB 50352 对公共建筑取 0.13~0.175，
# 这里放宽到 0.215 —— 只用来判「这口井该怎么画」，不做合规审查。
RISER_MIN, RISER_MAX = 0.12, 0.215
# 梯段净宽下限（m），GB 50352 公共建筑 ≥1.05。一口井要能塞下两跑，
# 至少得有 2×1.05 = 2.10 m 的横向净宽 —— 这条把「直跑井」劈成两类，见下。
# W_TOL 是给识别误差留的余量：c027 那口实测 2.0999999999999996（差 1 个 ULP）
# 就被 `>=` 判成了窄井。双线配对出来的宽度本来就有厘米级误差，卡死在 2.10
# 是拿浮点表示当判据。数据集里真窄井是 1.30（c103）/1.50（c114），
# 离 2.05 还差半米多，5 cm 余量不会把这两种搞混。
MIN_FLIGHT_W = 1.05
W_TOL = 0.05
TWO_FLIGHT_W = 2 * MIN_FLIGHT_W - W_TOL


def _frame(s):
    """井的「跑向局部系」：把东西向井（`axis="y"`）翻成以跑向为纵轴。

    整段楼梯渲染代码只为「跑沿 y」写；井的走向由识别阶段给出（`stairs.wells_of`
    的 `axis`）。这里统一成 `{W 净宽, c 净宽中心, r0/r1 跑长两端, perp()}`，
    发射盒子时再由 `_stair_box` 按 `rot` 转回世界系。缺 `axis` 的旧数据按
    `"x"`（跑沿 y）处理 —— 与改造前逐位等价。
    """
    rot = (s.get("axis") or "x") == "y"
    if rot:
        return {"rot": True, "W": s["yTop"] - s["yBot"], "r0": s["x0"], "r1": s["x1"],
                "c": (s["yBot"] + s["yTop"]) / 2, "perp": _perp_y}
    return {"rot": False, "W": s["x1"] - s["x0"], "r0": s["yBot"], "r1": s["yTop"],
            "c": (s["x0"] + s["x1"]) / 2, "perp": _perp_x}


def _perp_x(f):
    return (f["x0"], f["x1"])


def _perp_y(f):
    """东西向井里，跑的净宽范围是 y（`stairs.wells_of` 给的 flights 带完整方框）。"""
    return (f.get("y0", f["x0"]), f.get("y1", f["x1"]))




def stair_modes(wells, h):
    """给每口井定一个画法：full（一层高跑满）/ split（井内分两跑）/ half（半层跑）。

    背景：实测 c103 踢面 0.323、c114 0.383、c022 0.420 —— 陡得离谱。
    根因不是踏步数错，是 **double 梯被降级识别成「直跑」井**，渲染时按整层高
    一跑画到底，踢面自然翻倍。真实情况分两种，**井宽**是判据：

      · 窄（< 2.10 m）：塞不下两跑，只能是**镜像一对井各跑半层**里的那一口
        —— c103 两口 1.30 m 井镜像在 x=±15.86、c114 两口 1.50 m 井在 ±2.68。
        这类标 half，由 build_indoor_stairs 交替落 z / z+半层高，两口合一满层。
        必须**成对**：该层 half 井数为奇数就说明孪生井没识别出来，全部退回
        full —— 宁可留一口陡但爬满整层的楼梯，也不要一口爬到半层就断头。

      · 宽（≥ 2.10 m）：井内本就塞得下两跑（c027 的 2.10 m、c022 的 2.70 m），
        是 detect_stairwells 没把它拆成两条 flights。标 split，在**自己的
        脚印内**折返：半宽上到半层、另半宽接着上到顶，梯面 0.1615 / 0.21，
        满层覆盖，不依赖任何孪生井。

      · double/bifurcated 不动：步数本来就是「每跑」步数，两跑已经把层高分掉，
        没有可折的余地，硬折会把合规双跑压成半层。这类仍偏陡的（c009-F1
        双跑6步 → 0.35、c025/c028-F1F2 双跑8步 → 0.263）是**提取阶段步数
        偏少**，属数据缺陷，不在渲染层硬掰。

    折半后仍越界的一律 full：真的步数错认，不硬掰。
    """
    modes = []
    for s in wells:
        if (s.get("type") or "double") != "straight":
            modes.append("full")         # 双跑/双分已自带两跑
            continue
        n = max(2, s.get("steps") or 0)
        r = h / n                        # 直跑：一跑爬满整层
        if RISER_MIN <= r <= RISER_MAX:
            modes.append("full")         # 本来合规
        elif not (RISER_MIN <= r / 2 <= RISER_MAX):
            modes.append("full")         # 折半也不合规 → 步数错认，不掰
        elif _frame(s)["W"] >= TWO_FLIGHT_W:
            modes.append("split")        # 井够宽，自己就能折返
        else:
            modes.append("half")         # 窄井，靠孪生井补另外半层
    if sum(1 for m in modes if m == "half") % 2:
        modes = ["full" if m == "half" else m for m in modes]
    return modes


def build_indoor_stairs(b, floor, z, S, is_top):
    """室内楼梯按选型渲染：double=双跑平行 | bifurcated=双分式平行 | straight=直跑。
    各跑用实测 x0/x1 定位（flights 由 detect_stairwells 聚类得到）。
    顶层（无上层楼板）不画任何楼梯——楼梯井只剩楼板洞（下一层楼梯的到达点）。

    画法由 stair_modes 定（full / split / half）：
      · half 井按 x 中心排序后**交替**落在 z 与 z+半层高，镜像的一对井正好
        一个上、一个接上，连成完整的一层。选哪口先上取决于从哪边进走廊，
        数据里读不出来；交替是最省事的自洽解（错也只是上下颠倒，不会出现
        两口井都只爬到半层就断掉）。
      · split 井在自己脚印内折返（半宽上、半宽续），独自就能跑满一层。
    """
    if is_top:
        return
    h = S["floor_h"]
    midH = h / 2
    wells = floor["stairwells"]
    modes = stair_modes(wells, h)
    order = sorted((i for i, m in enumerate(modes) if m == "half"),
                   key=lambda i: _frame(wells[i])["c"])
    zoff = {i: (k % 2) * midH for k, i in enumerate(order)}

    for idx, s in enumerate(wells):
        fr = _frame(s)
        rot = fr["rot"]
        W = fr["W"]                        # 净宽（垂直跑向）
        N = max(2, s["steps"])
        cx = fr["c"]                       # 净宽中心
        runs = (fr["r0"], fr["r1"])        # 跑长两端
        stype = s.get("type") or "double"
        flights = s.get("flights") or []
        ld = min(1.2, (runs[1] - runs[0]) * 0.3)
        base = z + zoff.get(idx, 0.0)

        def emit(xc, run_pos, zc, w, dep, rise):
            """踏步/平台盒子。`rot=False` 跑沿 y（原样）；`rot=True` 跑沿 x，x/y 互换。"""
            if rot:
                b.add_box(run_pos, zc, -xc, dep, rise, w, 0.0, C_STAIR)
            else:
                b.add_box(xc, zc, -run_pos, w, rise, dep, 0.0, C_STAIR)

        def flight(xc, fw, yStart, yEnd, zBase, nsteps=N, r=None):
            r = h / (2 * N) if r is None else r
            tread = (yEnd - yStart) / nsteps
            for i in range(nsteps):
                emit(xc, yStart + (i + 0.5) * tread, zBase + i * r + r / 2, fw, tread, r)

        def fcx(f):
            p0, p1 = fr["perp"](f)
            return (p0 + p1) / 2

        def fw(f):
            p0, p1 = fr["perp"](f)
            return p1 - p0

        if modes[idx] == "half":
            # 半层跑：默认 r = h/(2N) 恰好把这一跑送到 base + 半层高
            flight(cx, W, runs[0], runs[1], base, nsteps=N)
            continue

        if modes[idx] == "split":
            # 宽直跑井：自己折返成两跑。半宽先上到半层，另半宽接上到顶，
            # 两跑各 N 步 → 踢面 h/(2N)，与 double 同构，满层覆盖。
            flightW = W / 2
            flight(cx - flightW / 2, flightW, runs[0], runs[1], base)
            flight(cx + flightW / 2, flightW, runs[1], runs[0], base + midH)
            emit(cx, runs[1] - ld / 2, base + midH - S["stair_landing"] / 2,
                 W, ld, S["stair_landing"])
            continue

        if stype == "bifurcated" and len(flights) >= 3:
            # 双分式：中跑（宽）先上到平台，平台后分左右两窄跑反向各上半层高
            k = len(flights) // 2
            mid = flights[k]
            sides = [f for i, f in enumerate(flights) if i != k]
            flight(fcx(mid), fw(mid), runs[0], runs[1], z)
            for f in sides:
                flight(fcx(f), fw(f), runs[1], runs[0], z + midH)
            emit(cx, runs[1] - ld / 2, z + midH - S["stair_landing"] / 2,
                 W, ld, S["stair_landing"])
        elif stype == "straight":
            # 直跑：单跑全宽，一层高内 N 步从 z 到 z+h
            flight(cx, W, runs[0], runs[1], z, nsteps=N, r=h / N)
        else:  # double（双跑平行，默认）
            if len(flights) >= 2:
                flight(fcx(flights[0]), fw(flights[0]), runs[0], runs[1], z)
                flight(fcx(flights[-1]), fw(flights[-1]), runs[1], runs[0], z + midH)
            else:
                flightW = W / 2
                flight(cx - flightW / 2, flightW, runs[0], runs[1], z)
                flight(cx + flightW / 2, flightW, runs[1], runs[0], z + midH)
            emit(cx, runs[1] - ld / 2, z + midH - S["stair_landing"] / 2,
                 W, ld, S["stair_landing"])


def main():
    S = load_spec()
    floors = load_floors()
    b = MeshBuilder()

    st = S.get("style", {})
    wall_col = hex_to_rgb(st.get("facade"))
    inner_col = hex_to_rgb(st.get("inner"))
    roof_col = hex_to_rgb(st.get("roof"))
    parapet_col = hex_to_rgb(st.get("parapet") or st.get("roof"))
    door_col = hex_to_rgb(st.get("door") or "#8a5a38")

    top = max(f["floor"] for f in floors)
    total_windows = 0
    total_dropped = 0
    # z 按**保留后的序号** i 排，不按原始层号 F —— 这样 skip_floors 踢掉底层后，
    # 剩下的楼层落到地面而不是悬空。不跳层时 i==F，与从前逐位等价。
    for i, floor in enumerate(floors):
        F = floor["floor"]
        z = i * S["floor_h"]
        is_top = (F == top)
        # 上层轮廓：给 build_slab 把「上面还有楼层」的那块楼板与「上面没楼层」的屋面同标高切开
        _up = (OUTLINE.floor_outline(floors[i + 1])
               if i + 1 < len(floors) else None)
        # 顶层没有"上一层轮廓"可用来切面层 → 拿**本层自己的轮廓**当"覆盖区"：
        # 于是本层楼面＝楼板色、并进来的"下层露出部分"＝屋面色（2026-09-16 板生成口径）。
        _up_or_self = _up if (_up is not None and not _up.is_empty) else OUTLINE.floor_outline(floor)
        # ★ 下层的**体量**轮廓（不是它的平面轮廓）—— 见 `band_mass_outline`。
        #   屋顶层平面带的 outline 是那张屋顶平面图的范围，拿它当"下层露出来的屋面"
        #   会在本层标高把整块裙房屋面**再铺一遍**（c006 F7 实测 4467.6㎡）。
        _down = (band_mass_outline(floors, i - 1) if i > 0 else None)
        build_slab(b, floor, z, S, up_outline=_up_or_self, roof_col=roof_col,
                   split_roof=(i > 0), below_outline=_down)
        build_rooms(b, floor, z, S)
        dropped = build_walls(b, floor, z, S, wall_col, inner_col, roof_col, parapet_col)
        total_dropped += dropped
        build_doors(b, floor, z, S, wall_col, inner_col, door_col)
        build_columns(b, floor, z, S)
        if i == 0:
            build_entry_stairs(b, floor, z)   # 台阶跟最底保留层走
        build_indoor_stairs(b, floor, z, S, is_top)
        total_windows += len([w for w in floor["windows"] if INCLUDE_SYNTHETIC_WINDOWS or not w.get("synthetic")])
        print(f"floor {F}: 墙={len(floor['walls'])}"
              + (f"(剔渣{dropped})" if dropped else "")
              + f" 窗={len(floor['windows'])} "
              f"门={len(floor['doors'])} 柱={len(floor['columns'])} "
              f"房间={len(floor['rooms'])}" + (" 屋顶=有" if is_top else ""))

    # 中间屋面（裙楼屋面 / 退台屋面）的女儿墙 —— 2026-09-14 补，此前**只有顶层**会
    # add_parapet（下面那段），于是 c006 的裙楼屋面（图纸 7层 = F6）成了一张没有边缘
    # 的光板：图纸上那圈线一条都没建，`_dxf_audit` 报 47.9% 漏墙。
    # 实测那圈线**就是下一层的外墙线**（F6 的 3792 个漏点里 89.1% 距 F5 墙 ≤0.4m，
    # 98.7% ≤1.0m）—— 女儿墙本来就立在下一层外墙线上，是常规做法，不是识别漏了，
    # 所以这一改**不碰识别**，纯建模侧。
    # 判据：本层 footprint 中**不被上一层覆盖**的部分 = 本层暴露的屋面。
    # 只取「本层轮廓那一圈」∩「暴露区」：直接用整圈的话，上一层与本层平齐的那段
    # 也会立一道多余矮墙（退台楼常见）。标高同顶层口径 —— 与本层楼板同底起。
    #
    # ⚠ **退让守卫**：识别侧的 `recognize.add_terrace_parapets` 也会给同一块退台屋面
    # 出 `type=="parapet"` 的墙（`build_walls` 里建），两者同标高同位置 ⇒ 一起出就是
    # **两圈墙**。本层 walls 里已有 parapet 数据时就跳过，改由 `build_walls` 建。
    # 49 栋里目前只有重出过的楼会有；其余 48 栋走这段程序化，**行为逐字节不变**。
    # ★★ 2026-09-16 用户判据：「有的柱子上方就是一个屋檐，类似于亭子」「空柱子上面」——
    #   本层的某个位置**上面什么楼层都没有**（不管是上一层还是更上层），却立着本层的柱：
    #   那这根柱不是露台上的构件，而是**檐廊/雨棚/亭子柱**，柱顶必须有屋檐板。
    #   实测（全库 49 栋普查 510 根）：
    #     c085 F2 36 根（南侧檐廊，包围盒 16×14m）、c079/c083 各 36 根、c084/c086 各 34 根、
    #     c080 68 根、c103 F0 62 根 + F4 138 根（单层附楼屋面 + 退台屋面）、c006/c009/c026/c027/c116 少量。
    #   没有这条时，模型里就是一根根悬空的柱子（用户看到的"空柱子上面"），
    #   而屋顶体检也正好报「F0 屋面 1724㎡ / F4 屋面 4585㎡ 无女儿墙」——同一件事的两面。
    #   判据（不按楼号）：柱心**不在"其上方所有楼层轮廓的并集"里**（容差 0.4m）＝自由柱；
    #   自由柱 ≥2 根 → 用它们的凸包外扩 EAVE_OVERHANG 作檐口板，标高放在**本层顶**
    #   ((i+1)×floor_h)，并沿板边立女儿墙（屋檐口本来就有）。
    #   与"露台"的区别：露台上没有柱（纯平板 + 女儿墙，走上面那段 `_outline_band`）。
    # ★★ 2026-09-16 下半场改法（取代同日早先那版"按自由柱补檐口板"）：用户点出
    #   「**每层的楼板是怎么生成的**」—— 正确的口径是**每层标高上的板盖住下层露出来的部分**
    #   （见 `build_slab` 的 below_outline），所以"下层露出来的屋面"已经随本层楼板一起出了，
    #   这里只需给它的**外缘**立一圈女儿墙（沿下层轮廓外缘，标高=本层标高）。
    #   实测好处：不再依赖"该处有没有柱"（c085 檐廊有柱、c072/c073 退台没柱，两种都要出屋面），
    #   也不会像按柱凸包那样在 c103 帧错位时把整块巨大板甩出来（那块是错的，已删）。
    n_low_roof = 0
    for i in range(1, len(floors)):
        # f_lo = **下层的体量**轮廓（同 `_down`，见 `band_mass_outline`）—— 用平面轮廓
        # 会沿着那张屋顶平面图的整圈外缘再立一道女儿墙（c006 F7 实测 275.5㎡）。
        f_lo = band_mass_outline(floors, i - 1)
        f_hi = OUTLINE.floor_outline(floors[i])
        if f_lo is None or f_lo.is_empty:
            continue
        extra = f_lo if (f_hi is None or f_hi.is_empty) else f_lo.difference(f_hi).buffer(0)
        if extra.is_empty or extra.area < ROOF_MIN_AREA:
            continue
        ring = _outline_band(f_lo, S["parapet_t"]).intersection(extra)
        if ring.is_empty:
            continue
        z = i * S["floor_h"]
        b.add_region(ring, z, z + S["parapet_h"], parapet_col,
                     col_side=wall_side_color(f_lo, wall_col, inner_col))
        n_low_roof += 1
        print("    下层露出屋面 %.1f㎡ @F%d 顶（z=%.1f）+ 女儿墙"
              % (extra.area, floors[i - 1]["floor"], z))

    for i, fl_i in enumerate(floors[:-1]):
        fp = OUTLINE.floor_outline(fl_i)
        if fp is None or fp.is_empty or fp.area <= 0:
            continue
        up = OUTLINE.floor_outline(floors[i + 1])
        exposed = fp if (up is None or up.is_empty) else fp.difference(up).buffer(0)
        if exposed.is_empty or exposed.area < ROOF_MIN_AREA:
            continue
        # ★ 2026-09-15 修「屋顶缺边」（用户判例：屋顶没有[女儿墙]）：原来只要本层 walls 里
        #   有**任意一段** type=parapet 就整层跳过补环 —— 但识别侧那几段往往只盖住暴露屋面的
        #   10~59%（实测 c006 F6 裙楼屋面 4468㎡ 只盖 10%、c034 F3 645㎡ 盖 16%、c072 F2 287㎡
        #   盖 11% …全库 13 栋 18 处），剩下的边就**没有女儿墙**。
        #   现在改成：把已有女儿墙（缓冲 0.35m）从暴露区里减掉，**只给没盖到的那部分补环**。
        _pars = [Polygon(w["poly"]) for w in (fl_i.get("walls") or [])
                 if w.get("type") == "parapet" and w.get("poly")]
        if _pars:
            _cov = unary_union([p if p.is_valid else p.buffer(0) for p in _pars]).buffer(0.35)
            _resid = exposed.difference(_cov).buffer(0)
            if _resid.is_empty or _resid.area < ROOF_MIN_AREA:
                continue
            exposed = _resid
        ring = _outline_band(fp, S["parapet_t"]).intersection(exposed)
        if ring.is_empty:
            continue
        y0 = i * S["floor_h"]
        # 朝外那张面是立面的延续，按面配色（与顶层中央女儿墙、build_walls 同一口径）。
        b.add_region(ring, y0, y0 + S["parapet_h"], parapet_col,
                     col_side=wall_side_color(fp, wall_col, inner_col))

    # 中央屋顶：苏式坡顶 or 平顶 + 女儿墙（标高在顶层墙顶 = (top+1)*floor_h）
    top_floor = floors[-1]                 # 顶层 = 保留层里的最后一层
    roof_y = len(floors) * S["floor_h"]    # 同样按保留层数算标高
    top_ol = OUTLINE.floor_outline(top_floor)
    if st.get("roofType") == "gable":
        build_gable_roof(b, top_ol, roof_y, roof_col)
    else:
        b.add_slab(top_ol, roof_y, S["roof_t"], roof_col)
        # 中央女儿墙同样按面配色：朝外那张面是立面的延续。与 build_walls 翼楼那圈同一口径。
        b.add_parapet(top_ol, roof_y, S, parapet_col,
                      col_side=wall_side_color(top_ol, wall_col, inner_col))
    # 翼楼屋面楼板：阶梯结构下翼楼屋面 = 下一层满 footprint − 顶层中央主体，
    # 标高在顶层楼板底部（= 下一层顶部 = top*floor_h），与翼楼屋面女儿墙同标高。
    # 翼楼屋面同样要一圈女儿墙（「四层楼顶缺女儿墙」根因——此前只铺板不围女儿墙）。
    for wr in top_floor.get("roof", {}).get("wingRoof", []):
        wing_poly = Polygon(wr)
        b.add_slab(wing_poly, top * S["floor_h"], S["roof_t"], roof_col)
        b.add_parapet(wing_poly, top * S["floor_h"], S, parapet_col,
                      col_side=wall_side_color(wing_poly, wall_col, inner_col))

    mesh = b.export_glb(OUT)
    print(f"[standard] 三角形={len(b.faces)} 顶点={len(b.verts)} "
          f"总窗={total_windows} 剔除碎渣墙={total_dropped}")
    print("已导出:", OUT)
    lo, hi = mesh.bounds
    print("bbox:", [round(x, 2) for x in lo], "->", [round(x, 2) for x in hi])


if __name__ == "__main__":
    main()
