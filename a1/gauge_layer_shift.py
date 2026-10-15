# -*- coding: utf-8 -*-
"""量 **逐层水平错位**（「层错位」）—— 直接读**交付件 GLB**，不读任何中间快照/预存缺陷表。

为什么单独一支：
  · 方案 §10.0.5 第 6 条同形 —— 交付件与它的判据必须**同作用域**。
  · 本仓 c006 的「层错位 6.7 m / 9.5 m」是从 **gym3d 仓的预存缺陷表**（`QC.defect_of`）读来的，
    而交付包的楼上部分**已经换成 libs3d 逐层件** ⇒ 那张表**未必还适用**（铁律 187：基线不许取旧读数）。
    本尺就地在**交付件本身**上重算，两者是两次独立读数。

量什么：每个顶层楼层节点（`B1` / `floor0..floorN`）的水平**包围盒中心**（取全部 POSITION 访问器的
  `min`/`max`，按节点世界变换烘成立方体 8 角后取包围盒）⇒ 逐层比 **相邻两层** 的中心水平位移。

★ 量具盲区（必须声明，盲区内的判词不算证据）：
  ① **包围盒中心 ≠ 墙质心**：楼梯间/电梯井/雨棚若偏在一侧，会把中心拽走；本尺**分不出**
     「真的错位」与「本层轮廓本来就不同」。⇒ 必须**同时看 `span_x/span_y`**：两层的跨度对不上时，
     位移读数**不可比**，本尺会把它标 `[轮廓不同]` 而不是当缺陷。
  ② 只量**水平**位移；竖向（层高）不在本尺内。
  ③ 只认**顶层节点**是楼层、其下是几何 —— 节点树改了（如多包一层 group）本尺会数错层数，
     故先断言「顶层节点数 == 层数」，不符即拒判。
  ④ 本尺**不给**「模型对不对」的结论，只给「相邻层中心差多少 mm」。

正对照（`--pos`）：把第 4 层节点整体在 X 上平移 `SHIFT_M` 米，同一把尺必须**报到那个数**
  （误差 ≤ 1 mm）。不响 ⇒ 本尺对错位无分辨力，否定判词不算证据。

用法: python gauge_layer_shift.py <glb> [--pos] [--json out.json]
"""
import sys
import os
import json
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
from pygltflib import GLTF2


def _node_bbox(g, ni):
    """节点子树的世界包围盒 (minx,miny,minz,maxx,maxy,maxz)。几何已烘进世界坐标时矩阵为单位。"""
    n = g.nodes[ni]
    mn = [float("inf")] * 3
    mx = [float("-inf")] * 3
    mi = n.mesh
    if mi is not None:
        for prim in g.meshes[mi].primitives:
            acc = g.accessors[prim.attributes.POSITION]
            if acc.min is None or acc.max is None:
                continue
            for k in range(3):
                mn[k] = min(mn[k], float(acc.min[k]))
                mx[k] = max(mx[k], float(acc.max[k]))
    for c in (n.children or []):
        cmn, cmx = _node_bbox(g, c)
        for k in range(3):
            mn[k] = min(mn[k], cmn[k])
            mx[k] = max(mx[k], cmx[k])
    return mn, mx


def measure(path, shift_floor=None, shift_m=0.0):
    """返回逐层 {node, c[3], span[3]} —— 单位毫米。
    ★ GLB 单位是米。★ 竖直轴**由数据定**（见 `vertical_axis`），不写死。"""
    g = GLTF2().load(path)
    roots = list(g.scenes[g.scene or 0].nodes)
    rows = []
    for i in roots:
        n = g.nodes[i]
        mn, mx = _node_bbox(g, i)
        if mn[0] == float("inf"):
            continue
        c = [(mn[k] + mx[k]) / 2.0 for k in range(3)]
        if shift_floor is not None and str(n.name) == shift_floor:
            c[0] += shift_m                # GLB 单位=m（★ 这里已是米，别再乘 1000）
        rows.append({"node": str(n.name),
                     "c_mm": [round(v * 1000.0, 1) for v in c],
                     "span_mm": [round((mx[k] - mn[k]) * 1000.0, 1) for k in range(3)]})
    rows.sort(key=lambda r: (0 if r["node"] == "B1" else int(r["node"].replace("floor", "")) + 1))
    return rows


def vertical_axis(rows):
    """竖直轴 = 逐层**单调、步长≈层高**的那一轴（由数据定，不写死 Y）。
    ★ 这条就是本尺上一版栽的地方：写死 Y 当水平，把「层高 3.6 m」读成了「层错位 3.6 m」。"""
    if len(rows) < 4:
        return None
    best, bestv = None, -1.0
    for k in range(3):
        d = [rows[i]["c_mm"][k] - rows[i - 1]["c_mm"][k] for i in range(1, len(rows))]
        if min(d) <= 0:                     # 必须单调增
            continue
        mean = sum(d) / len(d)
        spread = max(d) - min(d)
        score = mean / (1.0 + spread)       # 步长均匀且大者胜
        if mean > 500.0 and score > bestv:
            best, bestv = k, score
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--pos", action="store_true", help="正对照：把 floor4 在 X 上平移 SHIFT_M")
    ap.add_argument("--shift-floor", default="floor4")
    ap.add_argument("--shift-m", type=float, default=6.7)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if not os.path.isfile(a.glb):
        print("MISSING:", a.glb); return 2

    rows = measure(a.glb)
    n_root = len(GLTF2().load(a.glb).scenes[0].nodes)
    print("件:", os.path.basename(a.glb))
    print("顶层节点 %d == 量到 %d 层 ⇒ %s" % (n_root, len(rows), "✓" if n_root == len(rows) else "✗ 拒判（盲区③）"))
    if n_root != len(rows):
        return 3
    v = vertical_axis(rows)
    AX = "XYZ"
    if v is None:
        print("!! 定不出竖直轴（层数不足或数据不合）⇒ 拒判"); return 4
    H = [k for k in range(3) if k != v]
    print("竖直轴由数据定为 **%s**（逐层单调、步长≈层高）⇒ 水平面 = %s%s\n"
          % (AX[v], AX[H[0]], AX[H[1]]))
    print("%-8s %10s %10s %10s | %10s %10s %10s" %
          ("层", "c%s(m)" % AX[0], "c%s(m)" % AX[1], "c%s(m)" % AX[2],
           "跨%s(m)" % AX[0], "跨%s(m)" % AX[1], "跨%s(m)" % AX[2]))
    for r in rows:
        print("%-8s %10.3f %10.3f %10.3f | %10.3f %10.3f %10.3f" %
              (r["node"], r["c_mm"][0] / 1000, r["c_mm"][1] / 1000, r["c_mm"][2] / 1000,
               r["span_mm"][0] / 1000, r["span_mm"][1] / 1000, r["span_mm"][2] / 1000))
    print("\n== 相邻层**水平**中心位移（%s%s 面；竖直轴 %s 已排除）==" % (AX[H[0]], AX[H[1]], AX[v]))
    worst = None
    for i in range(1, len(rows)):
        p, c = rows[i - 1], rows[i]
        d = ((c["c_mm"][H[0]] - p["c_mm"][H[0]]) ** 2
             + (c["c_mm"][H[1]] - p["c_mm"][H[1]]) ** 2) ** 0.5
        dsp = [abs(c["span_mm"][k] - p["span_mm"][k]) for k in H]
        tag = ""
        if max(dsp) > 1000.0:        # 水平跨度差 >1 m ⇒ 轮廓本来就不同，中心不可比
            tag = "  [轮廓不同 跨%s差%.2fm 跨%s差%.2fm ⇒ 不可比]" % (
                AX[H[0]], dsp[0] / 1000.0, AX[H[1]], dsp[1] / 1000.0)
        print("   %-8s → %-8s  %8.1f mm%s" % (p["node"], c["node"], d, tag))
        if tag == "" and (worst is None or d > worst[0]):
            worst = (d, p["node"], c["node"])
    print("\n   可比对里最大的那对:", ("**%s→%s %.1f mm**" % (worst[1], worst[2], worst[0])) if worst else "无可比对")

    pos_ok = None
    if a.pos:
        r2 = measure(a.glb, a.shift_floor, a.shift_m)
        m1 = {r["node"]: r for r in rows}
        m2 = {r["node"]: r for r in r2}
        got = m2[a.shift_floor]["c_mm"][0] - m1[a.shift_floor]["c_mm"][0]
        want = a.shift_m * 1000.0
        pos_ok = abs(got - want) <= 1.0
        print("\n== 正对照（把 %s 整体在 %s 上平移 %.1f m）==" % (a.shift_floor, AX[0], a.shift_m))
        print("   读数 %+.1f mm / 期望 %+.1f mm ⇒ %s" % (got, want, "✓ 报到了" if pos_ok else "✗ 没报到"))

    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"glb": a.glb, "n_nodes": n_root, "vertical_axis": v, "rows": rows,
                   "pos_ok": pos_ok, "shift_m": a.shift_m if a.pos else None},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
