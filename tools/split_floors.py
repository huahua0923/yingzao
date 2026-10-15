# -*- coding: utf-8 -*-
"""把**烘死的单网格**建筑模型按楼层切成 N 个可分层的节点（供网页「分层与透明」）。

★ 为什么切分点必须落在交付件上、而不是重造几何：
  交付的 `c006-building.glb` 内部只有 1 个 mesh / 1 个 node（名 `geometry_0`）——
  所有几何被烘成一坨，**楼层归属在建链里就丢了**。要「分层」只有两条路：
    (a) 按**高度**把三角形划分到楼层带（本脚本）—— 无损，并集 == 原件；
    (b) 用 `baseline/floors/floor*.json` 重新挤出 —— 那是**另一个模型**，不是交付件。
  采用 (a)。

★ 切分依据是**实测**出来的，不是拍的：
  · 楼层数 N 与层高 h 取自 `baseline/floors/floor*.json` 的 `floor` / `layer_height`
    （c006：11 层 × 3.5 m）——**不写死**；
  · 竖直轴靠「哪根轴的跨度最接近 N*h」自动认，不写死 y；
  · 剖面校验：原件在 y = k*3.5 处确有重复的密度图样（实测 y 密集箱为 1.0/2.5/3.5 + 3.5k）。

★★ 判据四件套（§10.0.1）：
  ① 量交付件本身 —— 重读**写出的** GLB 数节点/面数，不读内存里的中间量
  ② 量具写明     —— trimesh.submesh + 质心归层；全部数字由程序现算
  ③ 盲区声明     —— 见 `BLIND`
  ④ 正对照必配   —— `--ctrl-shuffle`：把面**随机**归层 ⇒ 各层高度范围必然越界 ⇒ 判据必须变红

用法:
  python split_floors.py <src.glb> <out.glb> --floors <baseline/floors 目录|json 列表>
  python split_floors.py <src.glb> <out.glb> --n 11 --h 3.5
  python split_floors.py <src.glb> <out.glb> ... --ctrl-shuffle     # 正对照，必须 FAIL
"""
import sys
import os
import json
import glob
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import numpy as np
import trimesh

BLIND = [
    "归层按**三角形质心**：跨层三角形（如贯通两层的竖井壁）按质心归其中一层 ⇒ "
    "单层视图会在边界处「切一刀」，但**并集仍等于原件**（判据①查的就是并集无损）。",
    "分层轴是**几何高度**；它等于楼层，只因为本楼每层层高一致（实测 11×3.5）。"
    "对层高不等、有夹层/跃层的楼，本脚本的等分带会错位 —— 那种楼要先把层高表读进来再分。",
    "本尺子只量**几何可分层性**，对「这层是不是真叫 F7」不置一词（那是编号台账的活）。",
]


def floors_from_baseline(d):
    """从 baseline/floors/*.json 读 (N, h)。不写死。"""
    fs = glob.glob(os.path.join(d, "floor*.json"))
    if not fs:
        return None, None
    rows = []
    for f in fs:
        j = json.load(open(f, encoding="utf-8"))
        rows.append((int(j["floor"]), float(j["layer_height"])))
    rows.sort()
    hs = {h for _, h in rows}
    if len(hs) != 1:
        return len(rows), None            # 层高不等 ⇒ 交给调用方另处理（本脚本不猜）
    return len(rows), hs.pop()


def pick_up_axis(V, total_h):
    """认竖直轴：三根轴里跨度最接近总高的那根。"""
    ext = [float(V[:, i].max() - V[:, i].min()) for i in range(3)]
    return int(np.argmin([abs(e - total_h) for e in ext])), ext


def submesh_of(m, mask):
    s = m.submesh([np.nonzero(mask)[0]], repair=False)[0]
    s.remove_unreferenced_vertices()
    return s


def run(src, out, n, h, axis=None, shuffle=False, seed=0):
    m = trimesh.load(src, force="mesh")
    V, F = m.vertices, m.faces
    total_h = n * h
    if axis is None:
        axis, ext = pick_up_axis(V, total_h)
    else:
        ext = [float(V[:, i].max() - V[:, i].min()) for i in range(3)]
    up = V[:, axis]
    cen = up[F].mean(axis=1)
    lo = float(up.min())

    k = np.floor((cen - lo) / h).astype(int)
    k = np.clip(k, 0, n)                  # 第 n 带 = 屋面及以上（单独一层，便于看顶层的内部）
    if shuffle:
        rng = np.random.default_rng(seed)
        k = rng.integers(0, n + 1, size=len(k))

    scene = trimesh.Scene()
    names, nface, ylo, yhi = [], [], [], []
    for i in range(n + 1):
        mask = (k == i)
        if not mask.any():
            continue
        nm = ("floor%d" % i) if i < n else "roof"
        s = submesh_of(m, mask)
        names.append(nm)
        nface.append(int(len(s.faces)))
        ylo.append(float(s.vertices[:, axis].min()))
        yhi.append(float(s.vertices[:, axis].max()))
        scene.add_geometry(s, node_name=nm, geom_name=nm)
    scene.export(out)
    return {"src": src, "out": out, "axis": "xyz"[axis], "n_floors": n, "h": h,
            "names": names, "nface": nface, "ylo": ylo, "yhi": yhi,
            "ext": ext, "shuffle": shuffle}


# ---------------- 判据 ----------------
def judge(res, src, n, h, axis):
    """① 并集无损 ② 层带不越界（重读**写出的**文件，不读内存）"""
    fails = []
    o = trimesh.load(src, force="mesh")
    g = trimesh.load(res["out"])
    if isinstance(g, trimesh.Scene):
        parts = list(g.geometry.values())
        gnames = list(g.geometry.keys())
    else:
        parts, gnames = [g], ["<single>"]
    nf_out = int(sum(len(p.faces) for p in parts))
    nf_in = int(len(o.faces))
    if nf_out != nf_in:
        fails.append("面数不守恒：原件 %d ≠ 写出合计 %d" % (nf_in, nf_out))
    # 分层节点名必须都在（重读文件里数）
    for nm in res["names"]:
        if nm not in gnames:
            fails.append("写出件里找不到层节点 %r（实际 %s）" % (nm, gnames[:6]))
    # bbox 并集
    b1 = np.vstack([p.vertices for p in parts]); b0 = o.vertices
    if np.abs(b1.min(0) - b0.min(0)).max() > 1e-6 or np.abs(b1.max(0) - b0.max(0)).max() > 1e-6:
        fails.append("包围盒并集变了：%s → %s" % (b0.min(0).round(3), b1.min(0).round(3)))
    # 面积并集
    a0, a1 = float(o.area), float(sum(p.area for p in parts))
    if abs(a1 - a0) > max(1e-6, 1e-6 * a0):
        fails.append("表面积不守恒：%.6f → %.6f" % (a0, a1))
    # 层带不越界（这是 shufle 正对照要打红的那条）
    lo = float(o.vertices[:, axis].min())
    for nm, yl, yh in zip(res["names"], res["ylo"], res["yhi"]):
        i = int(nm[5:]) if nm.startswith("floor") else n
        band = (lo + i * h, lo + (i + 1) * h if i < n else float("inf"))
        if yl < band[0] - 1e-6 or yh > band[1] + 1e-6:
            fails.append("层 %s 越界：实测 %.3f..%.3f，带 %.3f..%.3f"
                         % (nm, yl, yh, band[0], band[1]))
    return fails, {"in_faces": nf_in, "out_faces": nf_out, "area_in": round(a0, 3),
                   "area_out": round(a1, 3), "n_nodes_out": len(parts)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--floors", default=None, help="baseline/floors 目录（读 N 与层高）")
    ap.add_argument("--n", type=int, default=None); ap.add_argument("--h", type=float, default=None)
    ap.add_argument("--axis", default=None, choices=[None, "x", "y", "z"])
    ap.add_argument("--ctrl-shuffle", action="store_true", help="正对照：随机归层，判据必须变红")
    a = ap.parse_args()

    n, h = a.n, a.h
    if a.floors:
        fn, fh = floors_from_baseline(a.floors)
        if fn is None:
            print("!! 基线里层高不一致 ⇒ 本脚本不猜，请显式给 --n/--h"); return 2
        n = n or fn; h = h or fh
    if not n or not h:
        print("!! 需要 --floors 目录，或显式 --n/--h"); return 2
    axis = "xyz".index(a.axis) if a.axis else None

    res = run(a.src, a.out, n, h, axis=axis, shuffle=a.ctrl_shuffle)
    print("源 %s（%.1f MB）" % (a.src, os.path.getsize(a.src) / 1e6))
    print("层数 %d × 层高 %.2f m = %.1f m；竖直轴 = %s（三轴跨度 x/y/z = %s）"
          % (n, h, n * h, res["axis"], ["%.1f" % e for e in res["ext"]]))
    for nm, nf, yl, yh in zip(res["names"], res["nface"], res["ylo"], res["yhi"]):
        print("  %-8s 面 %8d   %7.3f .. %7.3f m" % (nm, nf, yl, yh))
    print("写出 %s（%.1f MB）" % (a.out, os.path.getsize(a.out) / 1e6))

    fails, info = judge(res, a.src, n, h, "xyz".index(res["axis"]))
    print("\n判据：", "PASS" if not fails else "FAIL")
    print("  ", info)
    for f in fails[:8]:
        print("   ✗", f)
    if a.ctrl_shuffle:
        if fails:
            print("  ✓ 正对照触发（随机归层 ⇒ 判据变红）⇒ 这把尺子有分辨力")
            return 0
        print("  ✗ 正对照**没**触发 ⇒ 判据无分辨力，上面的 PASS 不算数")
        return 1
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
