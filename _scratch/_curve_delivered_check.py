# -*- coding: utf-8 -*-
# 已套X区间裁剪(与 classify._in_x_range 同口径)
"""「弧形墙识别出来了吗」直接体检(只读, 不写任何文件)。

前面用『我自己的探测器点被盖住多少』证明不了什么(曲墙可能本来就是外墙环的一部分)。
这里直接量**交付模型**: 把图纸墙层上的弧要素半径 >= 2m 按 0.25m 采样, 逐点判到楼层、
转本地坐标, 再看该点是否落在该层交付 walls 的 0.25m 邻域内。落在里面 = 模型里有这堵弧墙。

输出: 每栋 弧墙总长 / 被交付模型盖住的长度 / 覆盖率, 并列出漏得最多的层。
采样点落在建筑轮廓外(场地弧/图纸装饰弧)的, 记为「域外」单列, 不计入覆盖率分母。
"""
import json, os, sys, math, glob

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
import ezdxf
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from shapely.prepared import prep

from run_building import load_profile
from backend.recognizer.profile import floor_of, to_local
from backend.recognizer.classify import _seg_radius, CURVE_MIN_R
from backend.recognizer.profile import in_floor_x_range

ROOT = r"D:\gym3d\data\buildings"
STEP_M = 0.25
TOL_M = 0.25
FROZEN = {"c006", "c009", "c103", "c104"}


def _ent_cx(e):
    """实体 X 包围盒中心(mm); 取不到返回 None。与 classify._in_x_range 同口径。"""
    t = e.dxftype()
    try:
        if t == "LINE":
            xs = [float(e.dxf.start.x), float(e.dxf.end.x)]
        elif t == "ARC":
            xs = [float(q[0]) for q in e.flattening(50.0)]
        elif t == "LWPOLYLINE":
            xs = [float(q[0]) for q in e.get_points("xyseb")]
        elif t == "POLYLINE":
            xs = [float(v.dxf.location.x) for v in e.vertices]
        else:
            return None
    except Exception:  # noqa: BLE001
        return None
    return (min(xs) + max(xs)) / 2.0 if xs else None


def curve_points_mm(p):
    """墙层上「弧墙」的采样点(mm) + 其他墙层弧长。

    离散步长必须取 1mm 而不是 250mm: ezdxf 的 flattening 以 segments=4 为**下限**,
    对 c072 那种半径 215m 的缓弧(弦 35m、矢高 0.7m), 250mm 容差下 4 段就达标,
    一条 35m 的弧只落到 5 个点上 —— 采样点间距被拉成 8m, 覆盖率统计会失真。
    这里把整条折线按 1mm 离散, 再用「与原始直线弦的偏离 > 1mm」筛出真正的弧点
    (直线段上的点与弦重合, 被剔除), 得到的就是弧上均匀密点。
    返回 (点列, 其他墙层上的弧长mm)。
    """
    from ezdxf.path import make_path
    from shapely.geometry import LineString
    out = []
    other = 0          # 其他「含『墙』字图层」上的弧长(mm) —— 普查口径, 生产不用
    doc = ezdxf.readfile(p.dxf)
    for e in doc.modelspace():
        if e.dxf.layer != p.wall_layer:
            if "墙" in e.dxf.layer:
                t2 = e.dxftype()
                if t2 == "ARC" and e.dxf.radius >= CURVE_MIN_R * 1000.0:
                    other += int((e.dxf.radius * math.radians(
                        (e.dxf.end_angle - e.dxf.start_angle) % 360 or 360)))
            continue
        t = e.dxftype()
        _cx = _ent_cx(e)
        if _cx is not None and not in_floor_x_range(p, _cx):
            continue          # 识别器看不到的远场/夹缝内容, 不算分母
        if t == "ARC":
            if e.dxf.radius < CURVE_MIN_R * 1000.0:
                continue
            prev = None
            for q in e.flattening(1.0):
                q = (float(q[0]), float(q[1]))
                d = 0.0 if prev is None else math.hypot(q[0] - prev[0], q[1] - prev[1])
                out.append((q[0], q[1], d))
                prev = q
            continue
        if t != "LWPOLYLINE":
            continue
        pts = list(e.get_points("xyseb"))
        if len(pts) < 2:
            continue
        curved = False
        for i in range(len(pts) - 1):
            b = pts[i][4] if len(pts[i]) > 4 else 0.0
            r = _seg_radius((pts[i][0], pts[i][1]), (pts[i + 1][0], pts[i + 1][1]), b)
            if r is not None and r >= CURVE_MIN_R * 1000.0:
                curved = True
                break
        if not curved:
            continue
        chords = LineString([(float(a), float(b)) for a, b in
                             [(q[0], q[1]) for q in pts]])
        try:
            flat = [(float(q.x), float(q.y)) for q in make_path(e).flattening(1.0)]
        except Exception:  # noqa: BLE001
            continue
        prev = None
        for q in flat:
            if chords.distance(Point(q)) <= 1.0:     # 与直线弦重合 = 直线段上的点
                prev = None                          # 断开, 不跨直线段累加长度
                continue
            d = 0.0 if prev is None else math.hypot(q[0] - prev[0], q[1] - prev[1])
            out.append((q[0], q[1], d))              # d = 到同一条弧上前一个点的距离(mm)
            prev = q
    return out, other


def check(name, floors_dir=None):
    d = os.path.join(ROOT, name)
    fdir = floors_dir or os.path.join(d, "floors")
    fp0 = os.path.join(fdir, "floor0.json")
    if not os.path.exists(fp0):
        return name, "无楼层JSON", None
    p = load_profile(name)
    pts, other = curve_points_mm(p)
    if len(pts) < 8:
        return name, None, (other / 1000.0)
    # 逐层准备「交付墙几何」。「真墙」按**细度**判: 薄墙条带满足 2*面积/周长 = 等效厚度,
    # <= THIN_T 才是墙。用面积阈值会误杀长条外墙环(200m×0.24m = 48㎡ 却被当 blob)。
    # blob 楼(整层被 2~15 块巨多边形铺满)能把任何点都盖住, 那种覆盖不算识别, 单列。
    THIN_T = 0.6
    geoms, geoms_all = {}, {}
    for fp in sorted(glob.glob(os.path.join(fdir, "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        polys, thin = [], []
        for w in fl.get("walls", []):
            try:
                # 必须带上 holes: 外墙是「足迹 + 室内洞」的 0.30m 环带, 忽略洞会把
                # 薄环当成填满整层的方块(→ 误判成 blob, 白白说曲墙没识别)。
                G = Polygon(w["poly"], w.get("holes") or [])
                if not G.is_valid or G.is_empty:
                    continue
                polys.append(G)
                per = G.length
                if per > 0 and 2.0 * G.area / per <= THIN_T:
                    thin.append(G)
            except Exception:  # noqa: BLE001
                pass
        if polys:
            geoms_all[F] = prep(unary_union(polys).buffer(TOL_M))
        if thin:
            geoms[F] = prep(unary_union(thin).buffer(TOL_M))
    if not geoms_all:
        return name, "无墙几何", (other / 1000.0)
    # 轮廓(判是否域外)
    outlines = {}
    for fp in sorted(glob.glob(os.path.join(fdir, "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        if fl.get("outline") and len(fl["outline"]) >= 3:
            O = Polygon(fl["outline"])
            if O.is_valid and not O.is_empty:
                outlines[F] = prep(O.buffer(1.0))

    tot = hit = blob_only = outside = orph = 0        # 全部按弧长(mm)加权, 不按点数
    per_floor = {}
    for (x, y, d) in pts:
        try:
            F = int(round(floor_of(p, x, y)))
        except Exception:  # noqa: BLE001
            orph += d
            continue
        if F not in geoms_all:
            orph += d
            continue
        lx, ly = to_local(p, x, y, F)
        tot += d
        if F in outlines and not outlines[F].contains(Point(lx, ly)):
            outside += d          # 该点在建筑轮廓外: 场地弧/装饰弧, 不计分母
            continue
        k = per_floor.setdefault(F, [0.0, 0.0])
        k[1] += d
        pt = Point(lx, ly)
        if F in geoms and geoms[F].contains(pt):
            hit += d
            k[0] += d
        elif geoms_all[F].contains(pt):
            blob_only += d        # 只被 blob 盖住 = 没识别成墙
    ins = tot - outside
    return name, (tot, ins, outside, orph, hit, blob_only, other), per_floor



def main():
    names = sys.argv[1:] or ["c006", "c009", "c041", "c072", "c073", "c103", "c104"]
    print("== 交付模型里的弧墙体检 (弧半径 >= %.1fm; 1mm 离散采样; 长度加权) ==" % CURVE_MIN_R)
    print("   「墙层」= profile 指定的生产墙层(生产只用它); 「他层」= 图层名含『墙』但非生产层")
    print("   「识别成墙」判据: 落在等效厚度 <=0.6m 的墙条带 0.25m 邻域内(blob 巨多边形不算)")
    print("%-7s %-9s %-9s %-8s %-9s %-9s %-9s %s"
          % ("楼", "弧长(墙层)", "弧长(他层)", "域内", "识别成墙", "仅blob盖", "域外/未定位", "漏得最多的层"))
    for nm in names:
        name, data, pf = check(nm)
        if data is None:
            print("%-7s  无曲墙(墙层上半径>=%.1fm 的弧)" % (name, CURVE_MIN_R))
            continue
        if isinstance(data, str):
            print("%-7s %s" % (name, data))
            continue
        tot, ins, outside, orph, hit, blob_only, other = data
        cov = 100.0 * hit / ins if ins else 0.0
        bad = sorted(((100.0 * (v[1] - v[0]) / v[1], f, v) for f, v in pf.items()
                      if v[1] >= 3000.0), reverse=True)[:2]     # 只看弧长 >=3m 的层
        bstr = ", ".join("F%d 漏%.0f%%(%.1fm)" % (f, pct, v[1] * pct / 100.0 / 1000.0)
                         for pct, f, v in bad if pct > 5) or "无(全 >=95%)"
        tag = "  [冻结, 只报不改]" if name in FROZEN else ""
        mm = lambda v: v / 1000.0
        print("%-7s %-9.0f %-9.0f %-8.0f %-9.1f%% %-9.0f %-9.0f %s%s"
              % (name, mm(tot), other / 1000.0, mm(ins), cov,
                 mm(blob_only), mm(outside + orph), bstr, tag))
    print("\n注: 「识别成墙」= 采样点落在面积<10㎡ 的墙多边形 0.25m 邻域内(真墙);")
    print("    「仅blob盖」= 只被巨多边形(整层 blob)盖住, 不算识别;  「域外/未定位」已从分母剔除。")
    print("\n(更正: 普查报告的 3851m 是「图层名含『墙』的全部图层」口径, 生产只用 profile 墙层, 见上两列)")


if __name__ == "__main__":
    main()
