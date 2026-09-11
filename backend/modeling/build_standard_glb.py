# -*- coding: utf-8 -*-
"""标准 GLB 生成器：只消费标准 floor JSON（不重新解析 DXF）。

⚠️ DATA / OUT 只是**独立运行的兜底默认值**（沿用理化楼时期的命名，勿据此判断用途）。
真正的输出路径由调用方覆盖 —— 见 backend/web/run_step.py:104-109：
  · 批次楼：bsg.DATA=data/buildings/<name>，bsg.OUT=<name>-building.glb
  · 注册表楼(理化楼)：bsg.DATA=data，bsg.OUT=lihua-building.glb
单独运行本模块会写到 OUT 默认值指向的 data/lihua-building.glb。

每层：楼板(挖楼梯井洞) + 三段墙(窗带挖窗洞) + 玻璃 + 门板 + 结构柱 + 台阶/室内楼梯 + 房间色块；
顶层：中央屋面板 + 女儿墙（outline 外扩）+ 翼楼屋面女儿墙（JSON 内 type=parapet 墙段）。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shapely.geometry import Polygon, Point, box
from shapely.ops import unary_union

# 窗心到墙多边形的最大距离（米），超过就不算「这个窗长在这面墙上」。
# 取 0.15：校区墙厚 0.12~0.35，窗心到墙面的距离 ≤ 半墙厚 ≈0.175，
# 而邻墙至少在半个开间之外 —— 这个阈值能容浮点误差、又排除邻墙。
NOTCH_TOL = 0.15

from glb_common import MeshBuilder, g2, C_WALL, C_SLAB, C_ROOF, C_STAIR, C_DOOR, C_COLUMN, C_FRAME

DATA = r"D:\gym3d\data"                       # 兜底默认，调用方覆盖（run_step.py:104-109）
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
    floors = []
    F = 0
    while True:
        path = os.path.join(DATA, "floors", f"floor{F}.json")
        if not os.path.exists(path):
            break
        if F not in SKIP_FLOORS:
            with open(path, encoding="utf-8") as f:
                floors.append(json.load(f))
        F += 1
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


def build_walls(b, floor, z, S, wall_col, inner_col, roof_col):
    """三段墙 + 玻璃。每片墙（已合并，含中庭洞）分别三段挤 + 窗洞；
    外墙用 facade 色、内墙用 inner 色，女儿墙贴本层楼板标高 roof_col。"""
    walls = floor["walls"]
    parapet = [w for w in walls if w["type"] == "parapet"]
    solid = [w for w in walls if w["type"] != "parapet"]

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
        col = wall_col if w["type"] == "outer" else inner_col
        poly = Polygon(w["poly"], [h for h in (w.get("holes") or []) if len(h) >= 4])
        if poly.area < MIN_WALL_AREA:
            dropped += 1          # 配对碎渣，见 MIN_WALL_AREA 注释
            continue
        wb = poly.bounds
        win_poly = poly
        for (pt, pb), notch in zip(win_pts, notches):
            if _bbox_hit(wb, pb) and poly.distance(pt) <= NOTCH_TOL:
                win_poly = win_poly.difference(notch)
        b.add_region(poly, w0, sill_top, col)
        b.add_region(win_poly, sill_top, win_top, col)
        b.add_region(poly, win_top, wall_top, col)
    for win in wins:
        b.add_glass(win, w0, S)
        b.add_frame(win, w0, S, C_FRAME)

    # 翼楼屋面女儿墙（轮廓外真实墙段，贴本层楼板标高 z）
    for w in parapet:
        pp = Polygon(w["poly"])
        if pp.area < MIN_WALL_AREA:
            dropped += 1
            continue
        b.add_region(pp, z, z + w["height"], roof_col)
    return dropped


def build_slab(b, floor, z, S):
    slab = Polygon(floor["outline"])
    if floor["floor"] > 0:
        for s in floor["stairwells"]:
            slab = slab.difference(box(s["x0"], s["yBot"], s["x1"], s["yTop"]))
    b.add_slab(slab, z, S["slab_t"])


def build_rooms(b, floor, z, S):
    for r in floor["rooms"]:
        b.add_region(Polygon(r["poly"]), z + S["slab_t"], z + S["slab_t"] + ROOM_PAD, C_SLAB)


def build_columns(b, floor, z, S):
    h = S["wall_h"]
    for c in floor["columns"]:
        b.add_box(c["x"], z + S["slab_t"] + h / 2, -c["y"], c["w"], h, c["d"], 0.0, C_COLUMN)


def build_doors(b, floor, z, S, wall_col, inner_col, door_col):
    t = S["door_panel_t"]
    w0 = z + S["slab_t"]
    wall_top = w0 + S["wall_h"]
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
            col = wall_col if d.get("outer") else inner_col
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
            b.add_region(lintel, door_top, wall_top, col)


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
        elif (s["x1"] - s["x0"]) >= TWO_FLIGHT_W:
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
                   key=lambda i: wells[i]["x0"] + wells[i]["x1"])
    zoff = {i: (k % 2) * midH for k, i in enumerate(order)}

    for idx, s in enumerate(wells):
        W = s["x1"] - s["x0"]
        D = s["yTop"] - s["yBot"]
        N = max(2, s["steps"])
        cx = (s["x0"] + s["x1"]) / 2
        stype = s.get("type") or "double"
        flights = s.get("flights") or []
        ld = min(1.2, D * 0.3)
        base = z + zoff.get(idx, 0.0)

        def flight(xc, fw, yStart, yEnd, zBase, nsteps=N, r=None):
            r = h / (2 * N) if r is None else r
            tread = (yEnd - yStart) / nsteps
            for i in range(nsteps):
                yC = yStart + (i + 0.5) * tread
                b.add_box(xc, zBase + i * r + r / 2, -yC, fw, r, tread, 0.0, C_STAIR)

        def fcx(f):
            return (f["x0"] + f["x1"]) / 2

        def fw(f):
            return f["x1"] - f["x0"]

        if modes[idx] == "half":
            # 半层跑：默认 r = h/(2N) 恰好把这一跑送到 base + 半层高
            flight(cx, W, s["yBot"], s["yTop"], base, nsteps=N)
            continue

        if modes[idx] == "split":
            # 宽直跑井：自己折返成两跑。半宽先上到半层，另半宽接上到顶，
            # 两跑各 N 步 → 踢面 h/(2N)，与 double 同构，满层覆盖。
            flightW = W / 2
            flight(cx - flightW / 2, flightW, s["yBot"], s["yTop"], base)
            flight(cx + flightW / 2, flightW, s["yTop"], s["yBot"], base + midH)
            b.add_box(cx, base + midH - S["stair_landing"] / 2,
                      -(s["yTop"] - ld / 2), W, S["stair_landing"], ld,
                      0.0, C_STAIR)
            continue

        if stype == "bifurcated" and len(flights) >= 3:
            # 双分式：中跑（宽）先上到平台，平台后分左右两窄跑反向各上半层高
            k = len(flights) // 2
            mid = flights[k]
            sides = [f for i, f in enumerate(flights) if i != k]
            flight(fcx(mid), fw(mid), s["yBot"], s["yTop"], z)
            for f in sides:
                flight(fcx(f), fw(f), s["yTop"], s["yBot"], z + midH)
            b.add_box(cx, z + midH - S["stair_landing"] / 2, -(s["yTop"] - ld / 2),
                      W, S["stair_landing"], ld, 0.0, C_STAIR)
        elif stype == "straight":
            # 直跑：单跑全宽，一层高内 N 步从 z 到 z+h
            flight(cx, W, s["yBot"], s["yTop"], z, nsteps=N, r=h / N)
        else:  # double（双跑平行，默认）
            if len(flights) >= 2:
                flight(fcx(flights[0]), fw(flights[0]), s["yBot"], s["yTop"], z)
                flight(fcx(flights[-1]), fw(flights[-1]), s["yTop"], s["yBot"], z + midH)
            else:
                flightW = W / 2
                flight(cx - flightW / 2, flightW, s["yBot"], s["yTop"], z)
                flight(cx + flightW / 2, flightW, s["yTop"], s["yBot"], z + midH)
            b.add_box(cx, z + midH - S["stair_landing"] / 2, -(s["yTop"] - ld / 2),
                      W, S["stair_landing"], ld, 0.0, C_STAIR)


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
        build_slab(b, floor, z, S)
        build_rooms(b, floor, z, S)
        dropped = build_walls(b, floor, z, S, wall_col, inner_col, roof_col)
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

    # 中央屋顶：苏式坡顶 or 平顶 + 女儿墙（标高在顶层墙顶 = (top+1)*floor_h）
    top_floor = floors[-1]                 # 顶层 = 保留层里的最后一层
    roof_y = len(floors) * S["floor_h"]    # 同样按保留层数算标高
    if st.get("roofType") == "gable":
        build_gable_roof(b, top_floor["outline"], roof_y, roof_col)
    else:
        b.add_slab(Polygon(top_floor["outline"]), roof_y, S["roof_t"], roof_col)
        b.add_parapet(Polygon(top_floor["outline"]), roof_y, S, parapet_col)
    # 翼楼屋面楼板：阶梯结构下翼楼屋面 = 下一层满 footprint − 顶层中央主体，
    # 标高在顶层楼板底部（= 下一层顶部 = top*floor_h），与翼楼屋面女儿墙同标高。
    # 翼楼屋面同样要一圈女儿墙（「四层楼顶缺女儿墙」根因——此前只铺板不围女儿墙）。
    for wr in top_floor.get("roof", {}).get("wingRoof", []):
        wing_poly = Polygon(wr)
        b.add_slab(wing_poly, top * S["floor_h"], S["roof_t"], roof_col)
        b.add_parapet(wing_poly, top * S["floor_h"], S, parapet_col)

    mesh = b.export_glb(OUT)
    print(f"[standard] 三角形={len(b.faces)} 顶点={len(b.verts)} "
          f"总窗={total_windows} 剔除碎渣墙={total_dropped}")
    print("已导出:", OUT)
    lo, hi = mesh.bounds
    print("bbox:", [round(x, 2) for x in lo], "->", [round(x, 2) for x in hi])


if __name__ == "__main__":
    main()
