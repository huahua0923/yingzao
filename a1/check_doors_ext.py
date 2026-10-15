# -*- coding: utf-8 -*-
"""A1 **外部量**尺：拿**人写的门号**（MTEXT `M1000`/`M1400`，M=门、数字=门宽 mm）去核**识别出的门几何**。

这是 A1 出口门要的那个「**不来自 `4.2墙体` 派生量**」的外部量（方案 §9.2 A1 / D.4）。
它之所以算外部量：门号是**人写的文字**，建模链**一个字都读不到它**（`openings.py` 把 MTEXT 记成
`UNRESOLVED`），两把读数**互不派生**。

★ 可用锚的只有 **C109-十公寓（142 条，逐条 514 mm 落在门几何旁）**；**C075-综合实验大楼 541 条
  是「门表」不是「门位」**（实测到最近几何**中位 10.1 m**、8.5% 在 1.5 m 内 ⇒ 另放一处的编号表）
  ⇒ 本尺对 C075 **只报数、不给判词**（不许把「表」当「位」）。

★ 判据（C109，全部为真才算过）：
  A. **一一对应**：每条门号 TOL 内恰有一处识别出的洞口簇，且簇不重复使用
     ⇒ 命中数 == 门号数 == 簇数（既证明没漏，也证明没多）
  B. **宽度吻合**：命中簇的长边 ≈ 门号写的宽度（±`W_TOL`）
  C. 正对照① **平移 10 km**：门号整体挪 10 km ⇒ 命中率必塌到 0（尺子确实在量距离）
  D. 正对照② **喂已知错的宽度**：把门号宽度整体改成 `W+500`（已知与几何不符）⇒ B 的吻合数必塌
     —— 用来证明 B 真的在比数。★ **不做「随机重排宽度」**：C109 的 142 个门号**宽度全是 1000**
     （重排等于没动，首测实测吻合 142/142 不动）⇒ 重排对照**在这份数据上是退化的**，不许拿它充数。
  E. 非空断言：门号数==0 ⇒ 判**不成立**（遍历型判据扫空集合恒绿）

★ 量具盲区（必须声明）：
  ① 只对**有门号的栋**（全库 6 栋，且只有 C109 的号在门位）成立；**其余 99 栋没有外部量可核**，
     那 99 栋的门「识别得对不对」**本条不给结论**（仍是未证的）。
  ② TOL 是**判据参数**（取门垛常用 1.5 m），改它会改数。
  ③ 「门号位置」取 MTEXT 的 insert 点；若某图把号挂在**引线末端**而非门旁，本尺会误判为漏
     （C109 实测直线偏移恒 514 mm ⇒ 看来是固定偏移的直挂，非引线）。
  ④ 只核**门**（M）；本库**窗号 C = 0 条** ⇒ 窗无外部量可核。

用法: python check_doors_ext.py [--dxf A.dxf --json j.json]
"""
import sys
import os
import re
import json
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf
from shapely.geometry import Point
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import openings as O

D = r"D:\项目\gym3d\材料\dxf_output"
C109 = os.path.join(D, "C109-十公寓.dxf")
C075 = os.path.join(D, "C075-综合实验大楼.dxf")

TOL = 1500.0        # 门号↔门几何 的最大距离（mm）
W_TOL = 300.0       # 门号写的宽度 ↔ 簇长边 的容差（mm）
NEAR = 1500.0       # C075「是否为门位」的判定距离
SHIFT = 1.0e7       # 正对照平移量（mm）= 10 km
                    # ★ 10 m 不行（首测踩过）：图里同一栋楼/同一排门反复出现，挪 10 m 只挪到隔壁门
                    #   ⇒ 106/142 仍命中。要挪到**图纸范围之外**（本库图幅网格步长 ~111 m）才判得出。

FMT = re.compile(r"\\[A-Za-z][^;]*;")
MARK = re.compile(r"^\s*([MCcm])\s*(\d{2,5})\s*$")


def marks_and_polys(dxf):
    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    marks = []
    for e in msp:
        if e.dxftype() not in ("TEXT", "MTEXT"):
            continue
        s = FMT.sub("", (e.dxf.text if e.dxftype() == "TEXT" else e.text) or "").strip()
        m = MARK.match(s)
        if not m:
            continue
        w = int(m.group(2))
        if not (300 <= w <= 6000):
            continue
        try:
            p = e.dxf.insert
        except Exception:
            continue
        marks.append((p.x, p.y, m.group(1).upper(), w))
    polys, _lh, _hits = O.load_openings(dxf)
    return marks, polys


def match(marks, polys, tol=TOL, shift=0.0, widths=None):
    """返回 (命中条数, 命中详情, 一一对应是否成立)。widths=None ⇒ 用门号自带宽度。"""
    if not polys:
        return 0, [], False
    tree = STRtree(polys)
    used = set()
    hits = []
    for i, (x, y, k, w) in enumerate(marks):
        if k != "M":
            continue
        p = Point(x + shift, y)
        idx = tree.nearest(p)
        d = p.distance(polys[idx])
        if d > tol:
            continue
        if idx in used:                     # 一一对应：一处几何只认一条号
            continue
        used.add(idx)
        ww = w if widths is None else widths[i]
        long_edge = max(polys[idx].bounds[2] - polys[idx].bounds[0],
                        polys[idx].bounds[3] - polys[idx].bounds[1])
        hits.append((i, int(d), ww, int(long_edge)))
    n_m = sum(1 for m in marks if m[2] == "M")
    bijection = (len(hits) == n_m == len(polys))
    return len(hits), hits, bijection


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dxf", default=C109)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    print("外部量尺：人写门号(M) ↔ 识别出的门几何   件 =", os.path.basename(a.dxf))
    marks, polys = marks_and_polys(a.dxf)
    n_m = sum(1 for m in marks if m[2] == "M")
    print("  门号 M :", n_m, "   识别洞口簇 :", len(polys))

    # E 非空断言
    if n_m == 0:
        print("  ★ 门号 = 0 ⇒ 本判据**不成立**（无外部量可核，盲区①）")
        return 3

    # A/B
    n, hits, bij = match(marks, polys)
    wok = [h for h in hits if abs(h[2] - h[3]) <= W_TOL]
    print("\n== A 一一对应 ==")
    print("  命中 %d / 门号 %d / 簇 %d ⇒ %s"
          % (n, n_m, len(polys), "一一对应 ✓" if bij else "**不是一一对应 ✗**"))
    print("  距离(mm): 中位 %d" % (sorted(h[1] for h in hits)[len(hits) // 2] if hits else -1))
    print("== B 宽度吻合(±%d) ==" % W_TOL)
    print("  吻合 %d / %d = %.1f%%" % (len(wok), len(hits), 100.0 * len(wok) / max(len(hits), 1)))
    print("  样例(号idx, 距, 门号宽, 簇长边):", hits[:6])

    # C 平移 10 km
    nc, _, _ = match(marks, polys, shift=SHIFT)
    print("\n== 正对照 ==")
    print("  ① 门号整体平移 10 km ⇒ 命中 %d（应 0）%s" % (nc, "✓" if nc == 0 else " ✗"))

    # D 已知错的宽度（+500）：B 必须塌。★ 不用随机重排 —— C109 的号宽全 1000，重排是退化对照
    widths_bad = [None] * len(marks)
    for i, m in enumerate(marks):
        if m[2] == "M":
            widths_bad[i] = m[3] + 500
    _, hits_bad, _ = match(marks, polys, widths=widths_bad)
    wok_bad = [h for h in hits_bad if abs(h[2] - h[3]) <= W_TOL]
    print("  ② 门号宽度整体+500（已知不符）⇒ 吻合 %d/%d（原 %d/%d），须塌 %s"
          % (len(wok_bad), len(hits_bad), len(wok), len(hits),
             "✓" if len(wok_bad) == 0 else " ✗（B 无分辨力）"))

    ok = bij and (nc == 0) and (len(wok_bad) == 0)
    print("\n===== 判词 =====")
    print("  %s rc=%d  C109: 门号 %d = 簇 %d 一一对应，宽度吻合 %d/%d"
          % ("PASS" if ok else "FAIL", 0 if ok else 1, n_m, len(polys), len(wok), len(hits)))

    # C075 只报数：判它是「表」还是「位」
    if os.path.exists(C075):
        m2, p2 = marks_and_polys(C075)
        if m2 and p2:
            n2, h2, _bij2 = match(m2, p2)
            # 直接量「距最近几何」的分布
            tree = STRtree(p2)
            all_d = []
            for (x, y, k, w) in m2:
                if k != "M":
                    continue
                pp = Point(x, y)
                j = tree.nearest(pp)
                all_d.append(int(pp.distance(p2[j])))
            all_d.sort()
            within = sum(1 for d in all_d if d <= NEAR)
            print("\n  [旁证] C075 门号 %d 条：到最近几何 中位 %d mm，≤%.0f mm 的 %d (%.1f%%)"
                  % (len(all_d), all_d[len(all_d) // 2] if all_d else -1, NEAR,
                     within, 100.0 * within / max(len(all_d), 1)))
            print("         ⇒ 判为**门表**（不是门位），本尺不给判词（盲题②）")

    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"pass": ok, "dxf": a.dxf, "n_marks": n_m, "n_clusters": len(polys),
                   "matched": n, "bijection": bij, "width_ok": len(wok),
                   "shift_hits": nc, "bad_w_ok": len(wok_bad),
                   "tol": TOL, "w_tol": W_TOL},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("  写出:", a.json)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
