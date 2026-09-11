# -*- coding: utf-8 -*-
"""c041 曲墙配对 干跑(只读, 不写任何文件)。

两件事:
  A) 惰性证明: 开关关闭时 rebuild_floor 的输出必须与打补丁前逐字节一致(取宿舍若干层)
  B) c041: 分别算「关闭/开启 pair_curved」两种内墙, 报墙数/覆盖/门贴墙/曲墙覆盖率

曲墙覆盖率 = 图纸上「弧要素离散出的点」有多少被新墙几何盖住(容差 0.25m):
  - 从 classify 结果里挑出「含弧点」的墙折线(弧离散点是 0.25m 密点, 用它做判据)
  - 这些点的长度 = 曲墙总长(应与普查 c041≈167m 同量级)
  - buffer 0.25m 后与「新内墙 ∪ 现有外墙」求交, 有交的点即被盖住
"""
import json, os, sys, shutil, importlib.util

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
import ezdxf
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union

import _wall_thin_batch as B
from backend.recognizer import geometry as G

REC = r"D:\gym3d\backend\recognizer"
ROOT = r"D:\gym3d\data\buildings"
sys.path[:0] = [REC]


TMP_OLD = os.path.join(REC, "_wtb_old_tmp.py")


def load_old():
    """把打补丁前的 _wall_thin_batch 当独立模块加载(临时复制成 .py, 否则无 loader)。"""
    P = os.path.join(REC, ".orig_engine", "_wall_thin_batch.py.before_paircurved")
    src = open(P, encoding="utf-8").read()
    open(TMP_OLD, "w", encoding="utf-8", newline="").write(src)
    spec = importlib.util.spec_from_file_location("_wtb_old_tmp", TMP_OLD)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_wtb_old_tmp"] = m
    spec.loader.exec_module(m)
    return m


def raw_by_floor(p):
    doc = ezdxf.readfile(p.dxf)
    walls_dxf, doors, stairs, cols = B.classify.classify(doc.modelspace(), p)
    out = {}
    for w in walls_dxf:
        cx = sum(a for a, b in w) / len(w)
        cy = sum(b for a, b in w) / len(w)
        F = int(round(B.floor_of(p, cx, cy)))
        out.setdefault(F, []).append(
            [(float(a), float(b)) for a, b in [B.to_local(p, a, b, F) for a, b in w]])
    return out


def curve_points(raws):
    """从该层墙折线里挑出弧离散点(密点段)。返回点列表。"""
    pts = []
    for w in raws:
        for i in range(len(w) - 1):
            d = ((w[i + 1][0] - w[i][0]) ** 2 + (w[i + 1][1] - w[i][1]) ** 2) ** 0.5
            if d < 0.32:          # 弧离散步长 0.25m; 直墙段远大于此
                pts.append((w[i][0], w[i][1]))
    return pts


def curve_cover_pts(pts, geom, tol=0.25):
    """pts 里被 geom(容差 tol) 盖住的比例 + 曲墙总长估计。"""
    if not pts:
        return None
    hit = 0
    for x, y in pts:
        if geom is not None and geom.distance(Point(x, y)) <= tol:
            hit += 1
    return 100.0 * hit / len(pts), len(pts) * 0.25


# ---------------- A) 惰性证明 ----------------
OLD = load_old()


def inert_check(names):
    print("== A) 惰性证明(开关关闭: 新 rebuild_floor 必须与旧版逐字节一致) ==")
    allok = True
    for nm in names:
        p = B.load_profile(nm)
        assert getattr(p, "pair_curved", False) is False, "%s 不该开 pair_curved" % nm
        raws = raw_by_floor(p)
        for F in sorted(raws):
            fp = os.path.join(ROOT, nm, "floors", "floor%d.json" % F)
            if not os.path.exists(fp):
                continue
            fl = json.load(open(fp, encoding="utf-8"))
            try:
                a = B.rebuild_floor(fl, p, raws[F], F)
                b = OLD.rebuild_floor(fl, p, raws[F], F)
            except Exception as e:  # noqa: BLE001
                print("  %s F%d 异常 %s" % (nm, F, str(e)[:60]))
                allok = False
                continue
            same = json.dumps(a, sort_keys=True, ensure_ascii=False) == \
                json.dumps(b, sort_keys=True, ensure_ascii=False)
            if not same:
                allok = False
                print("  %s F%d 不一致!" % (nm, F))
            else:
                n = len(a[0]) if a else 0
                print("  %s F%-2d 一致(内墙 %d 条)" % (nm, F, n))
    print("  结论: %s\n" % ("全部逐字节一致 ✓" if allok else "存在不一致 ✗"))
    return allok


# ---------------- B) c041 干跑 ----------------
NAME = "c041"
inert_check(os.environ.get("INERT_BUILDINGS", "c019,c054").split(","))

print("== B) %s 曲墙配对干跑(只读) ==" % NAME)
p = B.load_profile(NAME)
raws = raw_by_floor(p)
# c041 轮廓里外墙环自带洞 = 建筑内区
census_curve_mm = 167.0     # 普查: c041 曲墙总长 ≈ 167m

print("%-5s %-24s %-24s %-13s %s" %
      ("层", "关闭 pair_curved", "开启 pair_curved", "曲墙长度", "覆盖率 关->开"))
for F in sorted(raws):
    fp = os.path.join(ROOT, NAME, "floors", "floor%d.json" % F)
    if not os.path.exists(fp):
        continue
    fl = json.load(open(fp, encoding="utf-8"))
    ol = Polygon(fl["outline"])
    if not ol.is_valid or ol.area < 1:
        print("%-5d 轮廓无效, 跳过" % F)
        continue

    outer = [w for w in fl["walls"] if w["type"] != "inner"]
    outerU = unary_union([Polygon(w["poly"]) for w in outer]) if outer else None

    p.pair_curved = False
    off, _ = B.rebuild_floor(fl, p, raws.get(F, []), F)
    p.pair_curved = True
    on, rshare = B.rebuild_floor(fl, p, raws.get(F, []), F)

    ok_off = B.verify_floor(fl, off, ol, ol.area) if off else None
    ok_on = B.verify_floor(fl, on, ol, ol.area) if on else None

    # 曲墙覆盖率必须「关/开」两侧对比才算证明: 曲墙若本来就是外墙, 关闭时也已盖住。
    def cover(walls):
        U = unary_union([Polygon(w["poly"]) for w in (walls or [])]) if walls else None
        if outerU is not None and U is not None and not U.is_empty:
            U = unary_union([U, outerU])
        elif outerU is not None:
            U = outerU
        return U

    cpts = curve_points(raws.get(F, []))
    cc_off = curve_cover_pts(cpts, cover(off))
    cc_on = curve_cover_pts(cpts, cover(on))

    fmt = lambda r: ("n=%d cov=%.0f%% big=%d d=%.0f%% ov=%.1f%%" % (r[1], r[2], r[3], r[4], r[5])) if r else "-"
    print("%-5d %-24s %-24s %-13s %s -> %s" %
          (F, fmt(ok_off), fmt(ok_on),
           ("%.0fm" % (cc_on[1] * 0.25)) if cc_on else "无",
           ("%.0f%%" % cc_off[0]) if cc_off else "-",
           ("%.0f%%" % cc_on[0]) if cc_on else "-"))

print("\n(c041 普查曲墙总长 ≈ %.0fm; 曲墙长度按 0.25m/步长估算)" % census_curve_mm)
if os.path.exists(TMP_OLD):
    os.remove(TMP_OLD)
print("(本脚本只读, 未写任何数据文件; 临时模块已删除)")
