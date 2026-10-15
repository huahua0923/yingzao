# -*- coding: utf-8 -*-
"""A1 **外部量判据（v2，2026-10-12 换参照物）**：图纸的 **`3轴线`**（人写的轴网定位线）上，
有没有**与它平行的模型墙**。

★ 为什么换参照物（见 memory `cdut3d-dim-gauge-references-walls-but-dims-chain-to-axis`）：
  旧版 v1 量「`DIMENSION` 的两个端点落不落在**模型墙**内」。**那是拿错了参照物** ——
  中国建筑图的尺寸是串在**轴线（网格线）**上的，不是墙边。逐层量顶点最近距离实测（C006）：

      图层       顶点数    端点到它的中位距离    <300 mm
      `3轴线`     828      **0 mm**           **84.5%**
      `4.2墙体`  28472      3300 mm             7.2%

  ⇒ v1 把一份**正确**的模型报成 7.2%。而且 `4.2墙体` 正是建墙链的**输入** ⇒ 拿它当参照物与
    交付件**同源**（铁律 192）。v2 的 `3轴线` 与建墙链独立：墙来自 `4.2墙体` 的线配对，
    轴线是**另一套人写的几何**。

★ 判据：`按段命中率 = 「与模型墙面**平行**、且距离 ≤ TOL」的轴线段数 / 轴线段总数`

★★ 这个「平行」两个字是**量出来的**，不是想出来的 —— 两个更简单的问法都被实测否掉了
   （2026-10-12，同一把尺同一份实现，见本轮探针记录）：

   问法①「轴线取样点落不落在墙足迹内」（按长度）：
        C006 = **33.6%**。★ 错因：轴线是**网格线**，本来大段走在房间/走廊上空 ⇒
        这个数随楼型乱跳（C109 墙密 = 80.7%），**没有跨栋含义**。

   问法②「轴线上有没有墙」（按条，不限方向）：
        C006 = 98.8% 看着很好，但**饱和**：把全部墙平移 700~2300 mm，命中率**一丝不变**
        （恒掉 3.2 点，是一整块**平台**）。★ 错因：轴线**横穿整栋楼**，会撞上大量与它
        **垂直**的墙 ⇒ 平行的墙挪走了，垂交的墙还钉在原处 ⇒ 判据量的根本不是墙位。

   ⇒ 所以必须加**方向**：只有**与轴线平行**的墙才算数。垂交的墙一概不认。

★ 正对照（必须配，否则判据没分辨力）：
  ① **合成样本**（拿真实墙面沿自身法向偏一下当"轴线"）：
     a. 偏 `SYN_NEAR_OFF`=120 mm（= 半墙厚，**压在墙上**）⇒ 必须 ≥99%（量得到）
     b. 偏 `SYN_FAR_OFF`=10 km（**飘出多图幅排版**）⇒ 必须 0%（不给任意几何发命中）
     ★★ 这条一度写成「**放开方向**（任何方向的墙都算）⇒ 命中率须 ≥95%」，**那是错的**：
       实测 C001 只有 90.8%、C105 只有 75.8% ⇒ 判据被报成"量具漏点"。回盘量了才明白 ——
       是**图纸本身**有「任何方向 300 mm 内都没有墙」的轴线（C001 漏点中位 1.3 m；
       C105 的图幅7 只有 11 段轴、全落在空处），**与尺子灵不灵无关**。
       拿"图纸里有没有无墙轴线"当正对照 = **把图纸的毛病算在尺子头上**。
       正对照必须是**给量具喂一个已知刺激**。「放开方向」现在只作**诊断**报出（见下表），不设阈值。
  ② `TOL` 收到 0 ⇒ 命中率必须**下降**（证明容差不是白给的）
  ③④ 把**轴线段沿自身法向**横挪 ±`BAY_DEFAULT`（**不是**全局平移 x/y）⇒ 命中率必须塌 ≥
     `MARGIN_MIN` 点 —— 这才证明「平行」这一刀真的量的是**墙位**。
     ★ 为什么不能拿全局 x/y 平移：沿 y 平移对**竖轴线**是「沿轴滑」，轴线还压在同一条竖线
       的墙面上 ⇒ 实测 C109 沿 y 只掉 10.0 点，**看着像尺子坏，其实是扰动选错了**。
     ★ 位移量必须**与柱网周期不同韵**：一次试点用 3000 mm（正好一个柱网跨度）⇒ 墙被整体挪到
       **隔壁轴线**上，等于没动；现取 `BAY_DEFAULT`（见下）并由 `--bay` 可调，
       **判据的判词看掉幅，不看绝对命中率**。
  四条都符合才算这条判据活着；**不响就作废，不给模型判词**（分不出「模型错」与「尺子坏」）。

用法: python dim_check.py <dxf> [--tol 300] [--bay 1730] [--ang 10] [--json out.json]

★ 量具盲区（必须声明）：
  ① 只认图层名**逐字为 `3轴线`** 的**直线实体**（LINE/LWPOLYLINE/POLYLINE）；
     名字不同 ⇒ 全盲报 0 条；轴号圈/轴号文字**不进分母**（见 `AXIS_TYPES`）。全库 99/105 份有此层。
  ② 命中率**不设绝对阈值**：轴线会外伸，也有**非结构轴线**（变形缝/楼梯附加轴）**本就不该有墙**
     ⇒ 一份**正确**的模型也达不到 100%。要设阈值须先量**全库分布**，现在没量 ⇒ 不臆造一个数。
     ★ 实测低基线多为**图纸原因**：C001 放开方向 90.8%、C105 75.8% —— 有轴线任何方向 300 mm
       内都没墙（C105 图幅7 的 11 段全在空处）；这类**不降级为"模型错"**。
  ②′ 合成正对照只验「量具会命中压墙的线」，**不验模型对不对**；模型对不对看 ③④ 的掉幅。
  ③ 平移正对照只沿 **±x/±y**；**旋转、整体缩放、墙厚/墙位微偏**不在扰动范围内。
  ④ 「有平行的墙」是**存在性**判据 —— 一条轴线上**有一处**平行的墙就算过，
     **墙断了一截、或整条墙只做了半根，它看不见**（那是别的判据，如墙线覆盖）。
  ⑤ 说不出「该有几条轴线」——`n_axis` 是**读到的**，不是应有的。
  ⑥ 轴线层与墙层若由**同一人同一遍**画错（整张图整体错位），两套几何一起错 ⇒ 本尺**测不出**。
  ⑦ 方向平行用**10°**夹角；圆弧墙、斜墙、异形柱的墙面会被这 10° 挡在外面（当"没墙"处理）。
"""
import sys
import os
import json
import math
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf
import numpy as np
import shapely
from shapely.geometry import LineString

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import generic_wall as GW   # noqa: E402

AXIS_LAYERS = ("3轴线",)    # ★ 按图层名规则选（全库普查：只有这一个名字，99/105 份有）
# ★ 只认**直线实体**。实测（2026-10-12）：C011/C001/C105 的 `3轴线` 层里混着**轴号圈**
#   （CIRCLE，C011 有 114 个）与轴号文字（MTEXT）；取段函数会把每个圈炸成 11 条 507 mm 的弦
#   ⇒ 分母虚增上千条、命中率被稀释成个位数（C011 掉到 9.1%）。C006 的该层是**纯 LINE**，
#   所以只有那三块被污染。轴号圈不是轴线，不许进分母。
AXIS_TYPES = ("LINE", "LWPOLYLINE", "POLYLINE")
MIN_SEG_LEN = 50.0          # 短于此的轴线段不判（与墙线取样的阈值一致）
FACE_MIN_LEN = 500.0        # 只留长度 ≥ 此值的**墙面边**（短边是墙厚端头，不是墙面）
ANG_MAX = 10.0              # 「平行」= 方向夹角 ≤ 此值（度）
TOL_DEFAULT = 300.0         # 位置容差（mm）
BAY_DEFAULT = 1730.0        # ★ 正对照③④的位移量：**故意与柱网周期不同韵**（见 docstring）
MARGIN_MIN = 15.0           # 正对照③④：命中率至少要掉这么多点
SYN_NEAR_MIN = 99.0         # 正对照①a：合成正样本（压着墙的线）命中率下限
SYN_NEAR_OFF = 120.0        # 合成正样本沿法向的偏移 = 半个墙厚（240/2），必然在容差内
# ★ 合成负样本的偏移必须**飘出多图幅排版之外**：本库的 DXF 把同一栋楼的各图幅并排放在
#   同一 modelspace 里，图幅间距 ~50 m ⇒ 偏 50 m 会**正落在邻幅的同名墙上**。实测 C009 命中
#   7.5% / C011 12.5%（假命中）⇒ 抬高到 10 km，保证一条墙都不挨。
SYN_FAR_OFF = 1.0e7


def _arr(geoms):
    """几何序列 → object ndarray（shapely 2.x 没有 `shapely.asarray`）。"""
    a = np.empty(len(geoms), dtype=object)
    for i, g in enumerate(geoms):
        a[i] = g
    return a


def seg_dir(coords):
    """线段单位方向向量（取首尾两点）。"""
    c = np.asarray(coords)
    d = c[-1] - c[0]
    n = float(np.hypot(d[0], d[1]))
    return d / n if n else d


def angle_deg(a, b):
    """两单位向量夹角（度），0~90°。"""
    c = min(1.0, abs(float(np.dot(a, b))))
    return math.degrees(math.acos(c))


def axis_segments(msp, layers=AXIS_LAYERS):
    """`3轴线` 上的**直线**实体（LINE/LWPOLYLINE/POLYLINE）取段，短于 `MIN_SEG_LEN` 的丢掉。

    ★ 轴号圈（CIRCLE/ARC）、轴号文字（MTEXT/TEXT）、填充（SOLID）**一律不进分母** —— 见 `AXIS_TYPES`。
    """
    segs = []
    for e in msp:
        try:
            if e.dxf.layer not in layers or e.dxftype() not in AXIS_TYPES:
                continue
        except Exception:
            continue
        GW.segs_of(e, segs)
    return [s for s in segs if s.length >= MIN_SEG_LEN]


def wall_faces(msp):
    """模型墙的**墙面线**：墙身四边形的长边 + 残段缓冲的边 + 柱边，只留长度 ≥ FACE_MIN_LEN 的。

    ★ 为什么不拿墙足迹多边形：**墙面**才有方向。墙足迹是一坨面，问「哪条边与轴线平行」
      得先有边。四边形的短边（= 墙厚端头 240 mm）在这里被 `FACE_MIN_LEN` 滤掉。
    ★ 只算**一次**（`wire()` 是这条链最贵的一步，C006 有 1.4 万条墙线 / 1.9 万块墙身）；
      平移正对照靠平移**墙**（或反向平移轴线），别再跑一遍。
    """
    ALLW, ALLC, _LAB = GW.load_walls_and_cols_msp(msp)
    quads, unp = GW.wire(ALLW)
    polys = [g for g in quads if g.is_valid and g.area > 1e3]
    polys += [s.buffer(GW.WALL_T / 2, cap_style=2, join_style=2) for s in unp if s.length >= 50]
    polys += list(ALLC)
    faces = []
    for g in polys:
        gs = g.geoms if hasattr(g, "geoms") else [g]
        for p in gs:
            if p.geom_type != "Polygon":
                continue
            cs = list(p.exterior.coords)
            for i in range(len(cs) - 1):
                x0, y0 = cs[i]
                x1, y1 = cs[i + 1]
                if math.hypot(x1 - x0, y1 - y0) >= FACE_MIN_LEN:
                    faces.append(LineString([(x0, y0), (x1, y1)]))
    return faces, len(polys)


def _load(path, cache):
    if path not in cache:
        msp = ezdxf.readfile(path).modelspace()
        faces, npoly = wall_faces(msp)
        segs = axis_segments(msp)
        from shapely import STRtree
        cache[path] = {"faces": _arr(faces),
                       "fdir": np.array([seg_dir(f.coords) for f in faces]) if faces
                               else np.zeros((0, 2)),
                       "segs": _arr(segs),
                       "sdir": np.array([seg_dir(s.coords) for s in segs]) if segs
                               else np.zeros((0, 2)),
                       "npoly": npoly,
                       "tree": STRtree(faces) if faces else None}
    return cache[path]


def _perp_offset(A, sdir, off):
    """把每条轴线段**沿自身法向**挪 `off` mm（± 号决定往哪边）。

    ★★ 正对照的扰动必须**垂直于被测量的那条线自身**，不能拿全局 x/y 平移 ——
      沿 y 平移对**竖轴线**是「沿轴滑」，轴线还压在同一条竖线的墙面上，永远命中 ⇒
      实测 C109 沿 y 只掉 10.0 点（<15），看着像「尺子坏」，其实是**扰动选错了**。
    """
    if not off:
        return A
    n = np.column_stack([-sdir[:, 1], sdir[:, 0]])      # 法向
    out = np.empty(len(A), dtype=object)
    for i in range(len(A)):
        out[i] = shapely.affinity.translate(A[i], xoff=off * float(n[i, 0]),
                                            yoff=off * float(n[i, 1]))
    return out


def run(path, tol=TOL_DEFAULT, perp=0.0, cache=None, ang=ANG_MAX):
    """量一份 DXF：返回 {dxf, n_axis, n_wall_face, hit_axis, rate_axis}。

    ★ 扰动实现：**把轴线段沿自身法向挪 `perp`**（等价于把墙横向挪），不必重建 STRtree。
    """
    if cache is None:
        cache = {}
    c = _load(path, cache)
    if c["tree"] is None:
        return None
    if not len(c["segs"]):
        return {"dxf": os.path.basename(path), "n_axis": 0, "n_wall_face": len(c["faces"]),
                "hit_axis": 0, "rate_axis": 0.0}
    A = _perp_offset(c["segs"], c["sdir"], perp)
    ii, jj = c["tree"].query(A, predicate="dwithin", distance=tol)   # 只有恰好邻近的成对
    hit = set()
    for a, f in zip(ii.tolist(), jj.tolist()):
        if angle_deg(c["sdir"][a], c["fdir"][f]) <= ang:
            hit.add(a)                     # ★ 必须**平行**才算 —— 垂交的墙一概不认
    n = len(hit)
    return {"dxf": os.path.basename(path), "n_axis": len(A), "n_wall_face": len(c["faces"]),
            "hit_axis": n, "rate_axis": (100.0 * n / len(A)) if len(A) else 0.0}


def _synth(path, off, cache, tol=TOL_DEFAULT, n=200):
    """**合成轴线**：拿真实墙面当"墙"，把**最长的 n 条墙面**沿自身法向偏 `off` 当"轴线"。

    这才是正对照该有的形状 —— 给量具喂一个**已知刺激**：偏 120 mm（= 半墙厚，压在墙上）
    必须命中，偏 50 m（飘到天上）必须一条都不命中。★ 它验的是**量具的响应**，
      与「这份图纸的轴线上有没有墙」无关；拿后者当正对照是**把图纸的毛病算在尺子头上**。
    """
    c = _load(path, cache)
    faces, fdir = c["faces"], c["fdir"]
    k = min(n, len(faces))
    if k == 0:
        return None
    order = sorted(range(len(faces)), key=lambda i: -faces[i].length)[:k]   # 取最长的（方向最稳）
    lines = [shapely.affinity.translate(faces[i], xoff=off * (-float(fdir[i][1])),
                                        yoff=off * float(fdir[i][0])) for i in order]
    A = _arr(lines)
    ii, jj = c["tree"].query(A, predicate="dwithin", distance=tol)
    hit = set()
    for a, f in zip(ii.tolist(), jj.tolist()):
        if angle_deg(fdir[order[a]], c["fdir"][f]) <= ANG_MAX:
            hit.add(a)
    return 100.0 * len(hit) / k


def judge(path, tol=TOL_DEFAULT, bay=BAY_DEFAULT, ang=ANG_MAX, cache=None):
    """跑四个条件并判。返回 {"dxf","results","n_axis","rate_axis","margin_x","margin_y","ok","notes"}。

    ★ 命令行与 A1 出口门**共用这一份**，避免两处各写一遍判词（铁律 174：同名的两个量必须死掉一个）。
    """
    if cache is None:
        cache = {}
    conds = (("tol", tol, 0.0, ang), ("free_ang", tol, 0.0, 90.0), ("tol0", 0.0, 0.0, ang),
             ("perp_p", tol, bay, ang), ("perp_n", tol, -bay, ang))
    results = {}
    for key, t, pp, ag in conds:
        r = run(path, t, pp, cache, ang=ag)
        if r is None:
            return {"dxf": os.path.basename(path), "ok": False, "results": {},
                    "notes": ["没有墙 ⇒ 无法判"]}
        results[key] = r
    base, free, zero = results["tol"], results["free_ang"], results["tol0"]
    pp, pn = results["perp_p"], results["perp_n"]
    syn_near = _synth(path, SYN_NEAR_OFF, cache, tol)
    syn_far = _synth(path, SYN_FAR_OFF, cache, tol)
    notes, ok = [], True
    if base["n_axis"] == 0:
        notes.append("✗ 正对照①不成立：一条 `3轴线` 都没读到 ⇒ 否定判词不算证据（盲区①）"); ok = False
    elif syn_near is None or syn_near < SYN_NEAR_MIN:
        notes.append("✗ 正对照①a不成立：合成正样本（墙面偏 %.0f mm）只命中 %s%%（须 ≥%.0f）"
                     " ⇒ 量具漏点" % (SYN_NEAR_OFF, "—" if syn_near is None else "%.1f" % syn_near,
                                     SYN_NEAR_MIN)); ok = False
    elif syn_far > 0.0:
        notes.append("✗ 正对照①b不成立：合成负样本（墙面偏 %.0f mm）竟命中 %.1f%%（须 0）"
                     % (SYN_FAR_OFF, syn_far)); ok = False
    else:
        notes.append("✓ 正对照①a/b（合成样本：压墙 %.0f%% / 飘 10 km %.0f%%）"
                     % (syn_near, syn_far))
    if base["n_axis"] > 0 and zero["rate_axis"] >= base["rate_axis"] - 1e-9:
        notes.append("✗ 正对照②不成立：TOL=0 命中率没下降 ⇒ 容差没起作用"); ok = False
    else:
        notes.append("✓ 正对照②（TOL=0 ⇒ %.1f%% < %.1f%%）" % (zero["rate_axis"], base["rate_axis"]))
    # ★ 正对照③④：把轴线段**沿自身法向**横挪 ⟹ 墙位若量不出来，这两条必不响
    mp = base["rate_axis"] - pp["rate_axis"]
    mn = base["rate_axis"] - pn["rate_axis"]
    for nm, m in (("③法向 +%.0f" % bay, mp), ("④法向 −%.0f" % bay, mn)):
        if m >= MARGIN_MIN:
            notes.append("✓ 正对照%s mm（横挪 ⇒ 掉 %.1f 点）" % (nm, m))
        else:
            notes.append("✗ 正对照%s mm 不成立：只掉 %.1f 点（<%.1f） ⇒ 墙位横移量不出来"
                         % (nm, m, MARGIN_MIN))
            ok = False
    return {"dxf": os.path.basename(path), "tol": tol, "bay": bay, "ang": ang,
            "reference": "3轴线", "results": results,
            "n_axis": base["n_axis"], "rate_axis": base["rate_axis"],
            "syn_near": syn_near, "syn_far": syn_far,
            "margin_pos": mp, "margin_neg": mn, "ok": ok, "notes": notes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--tol", type=float, default=TOL_DEFAULT)
    ap.add_argument("--bay", type=float, default=BAY_DEFAULT,
                    help="正对照③④的位移量（mm），故意与柱网周期不同韵，别填整千整百")
    ap.add_argument("--ang", type=float, default=ANG_MAX)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if not os.path.isfile(a.dxf):
        print("MISSING:", a.dxf); return 2
    print("DXF:", os.path.basename(a.dxf), "  TOL=%.0f mm  ANG≤%.0f°  参照物=`3轴线`"
          % (a.tol, a.ang))
    j = judge(a.dxf, a.tol, a.bay, a.ang)
    print("%-22s %8s %10s" % ("条件", "轴线(段)", "平行命中%"))
    lab = {"tol": "TOL=%.0f 且平行" % a.tol, "free_ang": "TOL=%.0f 放开方向" % a.tol,
           "tol0": "TOL=0", "perp_p": "法向横挪 +%.0fmm" % a.bay,
           "perp_n": "法向横挪 −%.0fmm" % a.bay}
    for key in ("tol", "free_ang", "tol0", "perp_p", "perp_n"):
        r = j["results"].get(key)
        if r is None:
            print("  !! 没有墙 ⇒ 无法判"); return 3
        print("%-22s %8d %10.1f" % (lab[key], r["n_axis"], r["rate_axis"]))
    for n in j["notes"]:
        print("  " + n)
    if j["ok"]:
        print("\n★ 结论：%d 段轴线里 %d 段有**平行的模型墙**，命中率 %.1f%%"
              "（盲区②：轴线外伸 + 非结构轴线 ⇒ 正确模型也不用 100%%）"
              % (j["n_axis"], j["results"]["tol"]["hit_axis"], j["rate_axis"]))
    else:
        print("\n★ 判据作废：正对照没全响 ⇒ 分不出「模型错」与「尺子坏」，不给模型判词")
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        with open(a.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"dxf": a.dxf, "tol": a.tol, "bay": a.bay, "ang": a.ang,
                       "reference": "3轴线", "n_axis": j["n_axis"], "rate_axis": j["rate_axis"],
                       "margin_pos": j["margin_pos"], "margin_neg": j["margin_neg"],
                       "results": j["results"], "pass": j["ok"]},
                      f, ensure_ascii=False, indent=1)
        print("写出:", a.json)
    return 0 if j["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
