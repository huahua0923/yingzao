# -*- coding: utf-8 -*-
"""把 **AutoCAD 描出来的一层楼板**换进交付包的分层件里，替掉 `floor0` 里 libs3d 建的那块板。

★★ 这是一次**替换**，不是新建几何：
  · 板是 **AutoCAD 画的**（`_scratch/drive_acad_grid.py`：`-HATCH` 灌满 → `HATCHGENERATEBOUNDARY`
    描环 → `_.REGION` → `_.UNION` 塌成一块 → 描出外环），适配器 `_scratch/loops_to_prism.py`
    只搬数，拉伸成体是 **Blender** 做的（`tools/prism_blender.py`）；
  · 本脚本**一个字几何都不建**：它只做两件事 —— ① 从 libs3d 的件里**点名摘掉**那块板
    （按几何认，不按下标）；② 把 AutoCAD 那块板按**两条链各自的原点口径**平移进去。

★★ 坐标口径（从 libs3d 自己的源码读，不手打）：
  `libs3d/c006/build8.py`：
      SHEETS = [("地下1层","R",5,-1)] + [("%d层"%i,"L",i-1,i) for i in range(1,7)] + \
               [("7层","R",0,7)] + [("%d层"%i,"R",i-7,i) for i in range(8,12)]
      XB = {"L": 1013200.0, "R": 1482900.0};  Y0, Y1 = 47500.0, 135000.0
      def tr(s): return [-XB[s.col], -s.yb, s.z()]        # 逐层件 = (DXF − 该层图幅原点, 高度, ·)
  ⇒ **1 层在 L 列第 0 行**，它的局部原点 = (1013200, 47500)。而交付包搬这些件时套的是
    `pack_d1.xform`，其中的常量取自 **R 列**（`pack_d1.libs3d_d1_origin()` 读 SHEETS 第一行 = 地下1层 R5）
    —— 两个列原点差 470700 mm。★ 本脚本**不用**那个常量去推 DXF，而是按**该层自己的列**取原点。

★ 判据四件套（§10.0.1）：① 量**写出的** GLB ② 量具与参照物写明 ③ 盲区声明 ④ 正对照必配
用法:
  python tools/slab_into_floor.py --floors <分层.glb> --slab <板.glb> --slab-meta <板.meta.json>
                                  --out <换后.glb> [--meta out.json]
"""
import argparse
import ast
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import importlib.util                                                    # noqa: E402
_spec = importlib.util.spec_from_file_location("pack_d1", os.path.join(HERE, "pack_d1.py"))
p1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p1)

NODE = "floor0"                 # floorK ↔ 第 K+1 层 ⇒ 1 层 = floor0
SLAB_SHEET_LABEL = "1层"
ALIGN_TOL_M = 0.5               # 落位容差（两条链的板边界口径不同：一条齐外墙面、一条外扩）
CTRL_MIN_M = 5.0                # 轴号分辨力下限：错的符号组合必须差 ≥5 m
PLATE_MIN_M2 = 1000.0           # 「板」的判据之一：朝上水平面 >1000 m²
PLATE_THICK_MM = (50.0, 250.0)  # 「板」的判据之一：竖向跨度落在这一档
BASE_TOL_M = 0.02               # 「板」的判据之一：底面贴 ±0.000
IOU_MIN = 0.90                  # 新板与旧板（都投影成平面轮廓）的 IoU 下限 —— 同一栋楼的同一层
SWAP_TOL_M2 = 0.5               # 「换进去了没有」的面积容差：写出的板面积 vs 新板轮廓面积

BLIND = [
    "★ 本脚本**不判板画得对不对**：板的几何出自 AutoCAD 那条链（`_scratch/drive_acad_grid.py`），"
    "它的正确性锚在 `unionM2`（AutoCAD 用 ActiveX 量的面域面积）与 `loops_to_prism.py` 的锚点选取上，"
    "见 `demo/_gen/c006-f1-slab.meta.json`。本节只判「**搬对了地方没有**」。",
    "★ 两版板的边界**口径不同**（实测）：新板四边齐外墙**面**（每条边向内 240 mm 都找得到配对线），"
    "旧板四边各外扩 180 mm。所以两者**边距**不是误差，是口径；轴号表给 0.5 m 容差就是给这个差异留的。",
    "轴号（x 是否取反、z 是否取反）靠**与旧板的平面矩形 + 轮廓 IoU** 定出；四条边在容差内、"
    "其余三种符号组合都差 ≥5 m ⇒ 对**轴号**有力。对**几米以内的平移**无力（那由两条链的原点口径定）。",
    "★ 摘板**按几何认**（贴底 + 竖向跨度 50~250 mm + 上下水平面 >1000 m² 且相等）。"
    "若 libs3d 那条链改成把板与墙并成一个实体，本判据会一个都认不出 ⇒ 届时 rc=4「没量到」，不猜。",
    "**颜色是借来的**：新板的顶点色抄**被摘掉的那块旧板**的颜色（本脚本不发明配色）。"
    "颜色不进任何判据。",
    "★ **新板必须先焊顶点**：Blender 那份件的顶点是按面拆开导出的（顶盖/底盖/各侧面各一组）。"
    "不焊就直接并进去，写出的文件被**默认读法**重读时板会碎成 337 面、朝下面积读成 0（实测："
    "连通分量 1163 个）。焊完两种读法一致（849 / 1298 个分量，都恰好认出 1 块 7678.102 m²、1336 面）。"
    "→ 量「写出的件」一律显式写 `process=True`。",
    "本步只动 `floor0`。其余 10 层 + B1 只判「一个字节没动」（节点名、面数、包围盒），"
    "**不判它们本身对不对**。",
]


# ---------------- libs3d 侧：只读它的源码取常量（不 import、不执行它） ----------------
def _ev(n, env):
    """**不给它任何执行能力**的表达式求值：常量 / 元组 / 列表 / `+`·`-`·`%` /
    `[…] for i in range(a, b)` 这一种列表推导。认不出来就抛 ⇒ 调用方 rc=4「不猜」。

    ★ 为什么不直接 eval/compile：那是把 libs3d 的源码当程序跑。这个文件是**冻结基线**、
      又是本仓每轮都要读的口径来源，没必要为几个常量开执行口子。
    """
    if isinstance(n, ast.Constant):
        return n.value
    if isinstance(n, ast.Tuple):
        return tuple(_ev(e, env) for e in n.elts)
    if isinstance(n, ast.List):
        return [_ev(e, env) for e in n.elts]
    if isinstance(n, ast.Dict):
        return {_ev(k, env): _ev(v, env) for k, v in zip(n.keys, n.values)}
    if isinstance(n, ast.Name):
        if n.id in env:
            return env[n.id]
        raise ValueError("自由变量 %s（只允许循环变量）" % n.id)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
        return -_ev(n.operand, env)
    if isinstance(n, ast.BinOp):
        l, r = _ev(n.left, env), _ev(n.right, env)
        if isinstance(n.op, ast.Add):
            return l + r
        if isinstance(n.op, ast.Sub):
            return l - r
        if isinstance(n.op, ast.Mod):
            if not (isinstance(l, str) and l.count("%") == 1 and l[l.index("%") + 1:l.index("%") + 2] in "dsf"):
                raise ValueError("不认这个 %% 模板 %r" % (l,))
            return l % r
        raise ValueError("不认这个二元运算 %s" % type(n.op).__name__)
    if isinstance(n, ast.ListComp):
        if len(n.generators) != 1 or n.generators[0].ifs:
            raise ValueError("列表推导只认单层无 if")
        g = n.generators[0]
        if not isinstance(g.iter, ast.Call) or getattr(g.iter.func, "id", None) != "range":
            raise ValueError("列表推导只认 range(...)")
        if not isinstance(g.target, ast.Name) or len(g.iter.args) != 2:
            raise ValueError("列表推导只认 `… for i in range(a, b)` 单名循环变量")
        lo, hi = (_ev(x, env) for x in g.iter.args)
        return [_ev(n.elt, dict(env, **{g.target.id: i})) for i in range(lo, hi)]
    raise ValueError("不认这个表达式节点 %s" % type(n).__name__)


def libs3d_sheets():
    """按 **AST** 取 `SHEETS` / `XB` / `Y0,Y1` 三个赋值，用上面那个无执行能力的求值器算。

    ★ 不 import build8（那会跑整条 libs3d 链、清掉它的基线产物）；也不手打常量。
    """
    src_path = p1.LIBS3D_BUILD
    tree = ast.parse(open(src_path, encoding="utf-8").read())
    got = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if isinstance(tgt, ast.Name) and tgt.id in ("SHEETS", "XB"):
            try:
                got[tgt.id] = _ev(node.value, {})
            except Exception as e:
                raise SystemExit("!! %s 里的 %s 读不出来（%s）⇒ 它的口径变了，不猜"
                                 % (src_path, tgt.id, e))
        if isinstance(tgt, ast.Tuple) and [getattr(e, "id", None) for e in tgt.elts] == ["Y0", "Y1"]:
            got["Y0Y1"] = ast.literal_eval(node.value)
    for k in ("SHEETS", "XB", "Y0Y1"):
        if k not in got:
            raise SystemExit("!! 从 %s 里读不出 %s ⇒ 它的口径变了，不猜" % (src_path, k))
    return got


def sheet_origin_of(label):
    """某层图幅在 DXF 世界里的原点 (x_mm, y_mm) —— 该层自己的列与行，不是别层的。"""
    g = libs3d_sheets()
    XB, (Y0, Y1) = g["XB"], g["Y0Y1"]
    hit = [s for s in g["SHEETS"] if s[0] == label]
    if len(hit) != 1:
        raise SystemExit("!! SHEETS 里叫 %r 的图幅有 %d 个 ⇒ 不猜" % (label, len(hit)))
    _, col, row, _k = hit[0]
    if col not in XB:
        raise SystemExit("!! 图幅 %r 的列 %r 不在 XB 里" % (label, col))
    return {"col": col, "row": row, "x_mm": float(XB[col]), "y_mm": float(Y0) + row * float(Y1),
            "sheets": g["SHEETS"], "src": p1.LIBS3D_BUILD}


# ---------------- 几何量具 ----------------
def horiz_areas(m, v=1):
    """朝上 / 朝下 水平面的投影面积（m²）。"""
    tr, nr = m.triangles, m.face_normals
    sel = np.abs(nr[:, v]) > 0.9
    proj = np.abs((tr[:, 1, 0] - tr[:, 0, 0]) * (tr[:, 2, 2] - tr[:, 0, 2])
                  - (tr[:, 1, 2] - tr[:, 0, 2]) * (tr[:, 2, 0] - tr[:, 0, 0])) / 2.0
    up = float(proj[sel & (nr[:, v] > 0)].sum())
    dn = float(proj[sel & (nr[:, v] < 0)].sum())
    return up, dn


def find_plates(m, base_y=0.0, min_up_m2=PLATE_MIN_M2):
    """按**几何**点名「板」：贴底（`base_y`，默认 ±0.000）+ 竖向跨度在档 + 上下水平面 >`min_up_m2` 且相等。

    ★ 两个 2026-10-14 为 `tools/slabs_sharp_into_floors.py` 加的**可选**参数（默认值 ⇒ 1 层行为逐字不变）：
      · `base_y`：包里的分层件是**按标高**摞的（`floor1`=2 层，板底在 **+3.6 m**，不是 ±0.000），
        所以 2~11 层要按自己的标高找板。
      · `min_up_m2`：`PLATE_MIN_M2`=1000 m² 是 **1 层（7678 m²）**语境下定的；塔楼（8~11 层）的板
        实测只有 **913.67 m²**，按 1000 卡会**整层认不到板**（实跑过：floor7 认到 0 块）。
    """
    out = []
    for c in m.split(only_watertight=False):
        b = c.bounds
        span = float(b[1][1] - b[0][1])
        if abs(float(b[0][1]) - base_y) > BASE_TOL_M:
            continue
        if not (PLATE_THICK_MM[0] / 1000.0 < span < PLATE_THICK_MM[1] / 1000.0):
            continue
        up, dn = horiz_areas(c)
        if up > min_up_m2 and abs(up - dn) < 1.0:
            out.append({"mesh": c, "up_m2": up, "dn_m2": dn, "span_m": span,
                        "faces": int(len(c.faces)), "bounds": b})
    return out


def footprint(m, which="bottom"):
    """平面轮廓：把该件**朝下（或朝上）的水平三角**并起来（精确并集，不是栅格）。"""
    tr, nr = m.triangles, m.face_normals
    sel = (np.abs(nr[:, 1]) > 0.999) & ((nr[:, 1] < 0) if which == "bottom" else (nr[:, 1] > 0))
    polys = []
    for t in tr[sel]:
        try:
            p = Polygon([(t[0][0], t[0][2]), (t[1][0], t[1][2]), (t[2][0], t[2][2])])
            if p.is_valid and p.area > 0:
                polys.append(p.buffer(0))
        except Exception:
            continue
    if not polys:
        return None
    return unary_union(polys)


def rect(m):
    b = m.bounds
    return {"x": (float(b[0][0]), float(b[1][0])), "z": (float(b[0][2]), float(b[1][2])),
            "y": (float(b[0][1]), float(b[1][1]))}


def node_mesh(scene, node):
    """取节点几何。★ 这两个 GLB 的**几何已在包坐标里**（实测 floor0 x −64.625..64.675）。

    ★ 不能走 `scene.graph`：trimesh 把 GLB 节点名截成了 `f`/`B`、且图与 `world` 断了链
      （`graph.get` 直接抛 `No path from world->f`）。所以图上的变换**读不到也不该用** ——
      用 `pack_d1.node_mesh` 会当场抛。
    """
    if node not in scene.geometry:
        raise SystemExit("!! %s 里没有节点 %s" % (scene, node))
    return scene.geometry[node].copy()


def save_scene(meshes, out):
    """把 {节点名: 网格} 原样写成一个 GLB —— 每个件都**不带**节点变换（坐标已在顶点里）。"""
    sc = trimesh.Scene()
    for name, m in meshes.items():
        sc.add_geometry(m.copy(), node_name=name, geom_name=name)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    sc.export(out)


# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--floors", required=True)
    ap.add_argument("--slab", required=True)
    ap.add_argument("--slab-meta", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", default=None)
    a = ap.parse_args()

    for p in (a.floors, a.slab, a.slab_meta, p1.LIBS3D_BUILD):
        if not os.path.exists(p):
            print("!! 缺输入 %s" % p); return 2
    sm = json.load(open(a.slab_meta, encoding="utf-8"))
    ox_s, oy_s = [float(v) for v in sm["origin_mm"]]        # 板自己的 DXF 原点（适配器写的）

    # ---- ① 原点口径：该层**自己的**图幅原点 + 交付包搬 libs3d 件时用的那个常量 ----
    sh = sheet_origin_of(SLAB_SHEET_LABEL)
    lib = p1.libs3d_d1_origin()
    pk = p1.pack_d1_origin()
    Tpack = p1.xform(1, 1, lib, pk)
    dx, dz = float(Tpack[0, 3]), float(Tpack[2, 3])
    print("板原点(该层图幅): %s 列第 %d 行  (%.0f, %.0f) mm   ← %s"
          % (sh["col"], sh["row"], sh["x_mm"], sh["y_mm"], os.path.basename(sh["src"])))
    print("包侧常量       : 由 pack_d1.xform 给出  dx=%+.3f dz=%+.3f m"
          "（该常量取自 **R 列**，见 pack_d1.libs3d_d1_origin 的 SHEETS 第一行）" % (dx, dz))
    print("板自己的原点   : (%.1f, %.1f) mm   ← %s" % (ox_s, oy_s, os.path.basename(a.slab_meta)))

    # ---- ② 读出旧板（在包坐标里），它是本次要摘掉的件、也是轴号表的参照物 ----
    floors = trimesh.load(a.floors)
    f0 = node_mesh(floors, NODE)
    plates = find_plates(f0)
    if len(plates) != 1:
        print("!! 在 %s 里按几何认出 %d 块板（应恰好 1）⇒ 没量到，不猜" % (NODE, len(plates)))
        for q in plates:
            print("     up=%.3f m² span=%.3f faces=%d" % (q["up_m2"], q["span_m"], q["faces"]))
        return 4
    old = plates[0]
    r_old = rect(old["mesh"])
    fp_old = footprint(old["mesh"])
    print("\n旧板(%s)  : 朝上 %.3f m² · 竖向 %.3f..%.3f · 面 %d · 平面 x %.3f..%.3f  z %.3f..%.3f"
          % (NODE, old["up_m2"], old["bounds"][0][1], old["bounds"][1][1], old["faces"],
             r_old["x"][0], r_old["x"][1], r_old["z"][0], r_old["z"][1]))

    # ---- ③ 新板 + 四种轴号组合的落位表 ----
    g = trimesh.load(a.slab)
    slab = g.to_geometry() if isinstance(g, trimesh.Scene) else g
    T = np.eye(4)
    def cand(sx, sz, extra=(0.0, 0.0)):
        """按 (x 轴号, z 轴号) 把新板搬进来；`extra` 是给正对照人为加偏。"""
        M = np.eye(4)
        M[0, 0], M[2, 2] = sx, sz
        M[0, 3] = sx * (ox_s - sh["x_mm"]) / 1000.0 + dx + extra[0]
        M[2, 3] = sz * (sh["y_mm"] - oy_s) / 1000.0 + dz + extra[1]
        return M, p1.apply_T(slab, M)

    rows = []
    for sx in (1, -1):
        for sz in (1, -1):
            M, mesh = cand(sx, sz)
            r = rect(mesh)
            err = max(abs(r["x"][0] - r_old["x"][0]), abs(r["x"][1] - r_old["x"][1]),
                      abs(r["z"][0] - r_old["z"][0]), abs(r["z"][1] - r_old["z"][1]))
            rows.append({"sx": sx, "sz": sz, "mesh": mesh, "rect": r,
                         "edge_err_m": round(err, 3), "T": M})
    print("\n轴号表（新板按四种符号组合搬进来，量与**旧板**平面矩形四边的最大残差）")
    for r in rows:
        print("   x%s z%s   四边最大残差 %8.3f m   %s"
              % ("+" if r["sx"] > 0 else "−", "+" if r["sz"] > 0 else "−", r["edge_err_m"],
                 "✓ 在容差内" if r["edge_err_m"] <= ALIGN_TOL_M else "✗"))
    good = [r for r in rows if r["edge_err_m"] <= ALIGN_TOL_M]
    fails = []
    if len(good) != 1:
        print("!! 轴号定不下来（在容差内的组合有 %d 个）⇒ 不猜，停" % len(good)); return 1
    pick = good[0]
    others = [r["edge_err_m"] for r in rows if r is not pick]
    margin = min(others) - pick["edge_err_m"]
    print("   ⇒ 定死 x%s z%s（其余组合最近 %.3f m ⇒ 分辨力 %.3f m）"
          % ("+" if pick["sx"] > 0 else "−", "+" if pick["sz"] > 0 else "−", min(others), margin))
    if margin < CTRL_MIN_M:
        print("!! 分辨力只有 %.3f m（<%.1f m）⇒ 这条轴号判据没牙，不采信" % (margin, CTRL_MIN_M))
        return 1
    new = pick["mesh"]
    r_new = pick["rect"]
    fp_new = footprint(new)
    inter = fp_new.intersection(fp_old).area
    uni = fp_new.union(fp_old).area
    iou = inter / uni
    print("\n新板       : 平面 x %.3f..%.3f (%.3f)  z %.3f..%.3f (%.3f)  y %.3f..%.3f"
          % (r_new["x"][0], r_new["x"][1], r_new["x"][1] - r_new["x"][0],
             r_new["z"][0], r_new["z"][1], r_new["z"][1] - r_new["z"][0],
             r_new["y"][0], r_new["y"][1]))
    inset = max(r_new["x"][0] - r_old["x"][0], r_old["x"][1] - r_new["x"][1])   # 两条链的边界口径差
    print("逐边差(新−旧): x 低 %+.3f 高 %+.3f · z 低 %+.3f 高 %+.3f  ⇒ 四边各内收 %.3f m"
          % (r_new["x"][0] - r_old["x"][0], r_new["x"][1] - r_old["x"][1],
             r_new["z"][0] - r_old["z"][0], r_new["z"][1] - r_old["z"][1], inset))
    print("轮廓 IoU   : %.4f（平面并集上量的，两条链的板**是同一层**的判据）" % iou)
    if iou < IOU_MIN:
        fails.append("IoU %.4f < %.2f ⇒ 两块板不是同一层的同一栋" % (iou, IOU_MIN))

    # ---- ④ 替换：摘旧板、加新板、其余分量原样保留 ----
    comps = f0.split(only_watertight=False)                   # ★ 只拆一次，下面都复用这一份

    def is_plate(c):
        return (abs(float(c.bounds[0][1])) <= BASE_TOL_M
                and PLATE_THICK_MM[0] / 1000.0 < float(c.bounds[1][1] - c.bounds[0][1])
                < PLATE_THICK_MM[1] / 1000.0
                and horiz_areas(c)[0] > PLATE_MIN_M2
                and abs(horiz_areas(c)[0] - horiz_areas(c)[1]) < 1.0)

    keep = [c for c in comps if not is_plate(c)]
    n_removed = len(comps) - len(keep)
    if n_removed != 1:
        print("!! 摘掉的分量是 %d 个（应恰好 1）⇒ 不写产物" % n_removed); return 1
    # ★ 颜色借旧板的：本脚本不发明配色
    col = None
    try:
        vc = np.asarray(old["mesh"].visual.vertex_colors)
        col = np.median(vc[:, :3], axis=0).astype(np.uint8)
    except Exception:
        pass
    slab_c = new.copy()
    # ★ 焊顶点：Blender 那份件的顶点是**按面拆开**导出的（顶盖/底盖/各侧面各一组），
    #   不焊的话写出的文件被**默认口径**重读时板会碎成 337 面、朝下面积读成 0
    #   （实测：1163 个连通分量 vs 显式 process=True 的 1298 个）。原件是 trimesh 自己
    #   生成的、顶点本来就共享 ⇒ 必须在这一侧补齐，否则「写出的件」与「原件」不同口径。
    slab_c.merge_vertices()
    if col is not None:
        slab_c.visual.vertex_colors = np.tile(np.concatenate([col, [255]]), (len(slab_c.vertices), 1))
    merged = trimesh.util.concatenate(keep + [slab_c])
    print("\n替换       : 摘掉 %d 个分量（板）· 保留 %d 个 · 新板面 %d · %s 合并后面 %d（原 %d）"
          % (n_removed, len(keep), len(slab_c.faces), NODE, len(merged.faces), len(f0.faces)))
    if len(merged.faces) != len(f0.faces) - old["faces"] + len(slab_c.faces):
        fails.append("面数守恒不成立")

    # ---- ⑤ 写盘 + 重读核（不读内存中间量）----
    out_meshes = {}
    for name in sorted(floors.geometry.keys()):
        out_meshes[name] = merged if name == NODE else floors.geometry[name].copy()
    save_scene(out_meshes, a.out)

    chk = trimesh.load(a.out, force="scene", process=True)   # ★ 显式 process=True：两个进程重读结果一致
    names = sorted(chk.geometry.keys())
    if names != sorted(out_meshes.keys()):
        print("!! 写出的节点名单对不上：%s" % names); return 1
    chk0 = node_mesh(chk, NODE)
    pl2 = find_plates(chk0)
    if len(pl2) != 1:
        print("!! 重读后 `%s` 里的板不是恰好 1 块（%d 块）⇒ 写盘这一关没过" % (NODE, len(pl2))); return 1
    print("重读核     : 节点 %d 个 %s" % (len(names), names))

    # ★ 判据 J-已换：写的那个件里，板必须是**新板** —— 面积等于 AutoCAD 那条链给的轮廓面积，
    #   且与旧板差得开。这两条缺一条，就分不出「换了」与「换了但没生效」。
    def judge_swapped(m):
        p = find_plates(m)
        if len(p) != 1:
            return False, None, "板不是恰好 1 块"
        a = p[0]["up_m2"]
        if abs(a - fp_new.area) > SWAP_TOL_M2:
            return False, a, "板面积 %.3f ≠ 新板轮廓 %.3f（差 %.3f）" % (a, fp_new.area, a - fp_new.area)
        if abs(a - old["up_m2"]) <= SWAP_TOL_M2:
            return False, a, "板面积与旧板相同（%.3f）⇒ 等于没换" % a
        return True, a, ""

    ok5, a_out, why5 = judge_swapped(chk0)
    print("             新板朝上 %.3f m²（该 = AutoCAD 链给的轮廓面积 %.3f；旧板 %.3f）· 面 %d"
          % (pl2[0]["up_m2"], fp_new.area, old["up_m2"], pl2[0]["faces"]))
    if not ok5:
        fails.append("J-已换: %s" % why5)
    # 其余层一个字节没动
    lost = []
    for name in names:
        if name == NODE:
            continue
        m_in = floors.geometry[name]
        m_out = chk.geometry[name]
        if int(len(m_in.faces)) != int(len(m_out.faces)):
            lost.append("%s 面数 %d≠%d" % (name, len(m_in.faces), len(m_out.faces)))
        elif not np.allclose(np.asarray(m_in.bounds, float), np.asarray(m_out.bounds, float), atol=1e-9):
            lost.append("%s bbox 变了" % name)
    print("             其余 %d 个节点（面数 + bbox 逐位）%s"
          % (len(names) - 1, "✓ 未动" if not lost else "✗ %s" % lost))
    if lost:
        fails.append("J-未动:其他层被动了 %s" % lost)

    # ---- 正对照：每条点名它该红哪条判据 ----
    ctrl = []

    def _axis_ok(cand_mesh):
        r = rect(cand_mesh)
        e = max(abs(r["x"][0] - r_old["x"][0]), abs(r["x"][1] - r_old["x"][1]),
                abs(r["z"][0] - r_old["z"][0]), abs(r["z"][1] - r_old["z"][1]))
        return e <= ALIGN_TOL_M, e

    for nm, mm, exp in [
        ("平移 +8 m（x）", p1._xlate(new, [8.0, 0.0, 0.0]), "轴号表：容差内组合变 0 个"),
        ("x 轴号取反重搬", cand(-pick["sx"], pick["sz"])[1], "轴号表：容差内组合变 0 个"),
    ]:
        ok, e = _axis_ok(mm)
        fired = not ok
        ctrl.append({"name": nm, "expect_judge": exp, "edge_err_m": round(e, 3),
                     "fired": bool(fired), "ok": bool(fired)})
        print("正对照     : %-16s 该红 %-22s 实红 %s（四边残差 %.3f m）"
              % (nm, exp, "✓" if fired else "✗ 没红", e))
        if not fired:
            fails.append("对照「%s」该红而没红" % nm)

    # 对照③：**摘了板却没加新板**（漏了后半步）⇒「写的件里板是新板」这条判据该红
    ok3, a3, why3 = judge_swapped(trimesh.util.concatenate(keep))
    ctrl.append({"name": "摘了旧板、忘了加新板", "expect_judge": "写的件里认不到板",
                 "plate_area_m2": None if a3 is None else round(a3, 3),
                 "fired": bool(not ok3), "ok": bool(not ok3)})
    print("正对照     : %-16s 该红 %-22s 实红 %s（%s）"
          % ("只摘不加", "写的件里认不到板", "✓" if not ok3 else "✗ 没红", why3 or "认到了板"))
    if ok3:
        fails.append("对照「只摘不加」该红而没红")

    # 对照④：拿**没换**的原件冒充产物 ⇒ 板面积 == 旧板 ⇒ 该红「等于没换」
    ok4, a4, why4 = judge_swapped(f0)
    ctrl.append({"name": "未替换的原件冒充产物", "expect_judge": "板面积与旧板相同 ⇒ 等于没换",
                 "plate_area_m2": round(a4, 3), "fired": bool(not ok4), "ok": bool(not ok4)})
    print("正对照     : %-16s 该红 %-22s 实红 %s（板 %.3f m²；%s）"
          % ("原件冒充产物", "板面积与旧板相同", "✓" if not ok4 else "✗ 没红", a4, why4 or "判成了换过"))
    if ok4:
        fails.append("对照「原件冒充产物」该红而没红")

    okj = not fails
    print("\n判词       :", "PASS" if okj else "FAIL %s" % fails[:3])

    meta = {
        "schema": "cdut3d-slabswap/1",
        "node": NODE, "sheet_label": SLAB_SHEET_LABEL,
        "new_slab": {"file": a.slab, "meta": a.slab_meta,
                     "chain": "AutoCAD -HATCH 灌满 → HATCHGENERATEBOUNDARY 描环 → REGION → UNION → 描外环；"
                              "适配器只搬数；Blender 拉伸成体",
                     "dxf_origin_mm": [ox_s, oy_s], "expect_m2": sm.get("expect_m2"),
                     "outline_area_m2": sm.get("outline_area_m2"), "outline_verts": sm.get("outline_verts"),
                     "thickness_m": [sm.get("z0"), sm.get("z1")]},
        "old_slab": {"what": "libs3d/c006 那条链建的 1 层板（同一件里一个独立连通分量）",
                     "up_m2": round(old["up_m2"], 3), "span_m": round(old["span_m"], 4),
                     "faces": old["faces"],
                     "plan_x_m": [round(v, 3) for v in r_old["x"]],
                     "plan_z_m": [round(v, 3) for v in r_old["z"]]},
        "transform": {"axis_sign": {"x": pick["sx"], "z": pick["sz"]},
                      "dx_m": round(float(pick["T"][0, 3]), 3), "dz_m": round(float(pick["T"][2, 3]), 3),
                      "how": "新板 = DXF 世界坐标 → 该层图幅原点(%s 列第 %d 行) → 与 libs3d 逐层件**同一个** "
                             "pack_d1.xform 常量。纯平移 + y 取反，无镜像。"
                             % (sh["col"], sh["row"]),
                      "sheet_origin_mm": [sh["x_mm"], sh["y_mm"]],
                      "pack_const_m": [round(dx, 3), round(dz, 3)],
                      "why_not_R_column": "★ 交付包搬 libs3d 件用的常量取自 **R 列**（pack_d1 读 SHEETS 第一行"
                                          "= 地下1层 R5）；1 层在 **L 列**。两列原点差 %.0f mm ⇒ 直接套那个常量"
                                          "会把板搬歪 470 m（实测过）。"
                                          % (abs(1482900.0 - 1013200.0))},
        "axis_table": [{"sx": r["sx"], "sz": r["sz"], "edge_err_m": r["edge_err_m"]} for r in rows],
        "margin_m": round(margin, 3),
        "edge_inset_m": round(inset, 4),
        "iou_new_vs_old": round(float(iou), 4),
        "faces": {"floor0_in": int(len(f0.faces)), "old_plate": old["faces"],
                  "new_plate": int(len(slab_c.faces)), "floor0_out": int(len(merged.faces))},
        "edge_caliber_note": "两版板边界口径不同（实测）：新板四边比旧板各内收 %.3f m；"
                             "新板那条边界落在墙的**面**上（见 过程/_scratch/probe_slab_edges.py："
                             "每条边向内 240 mm 都找得到配对墙线）。" % inset,
        "color": {"source": "借用被摘掉的旧板顶点色（中位数）", "rgb": None if col is None else [int(v) for v in col],
                  "in_any_judge": False},
        "slab_welded": True,
        "judge": {"axis_table_unique": True, "resolution_m": round(margin, 3),
                  "face_conservation": len(merged.faces) == len(f0.faces) - old["faces"] + len(slab_c.faces),
                  "other_nodes_untouched": not lost, "iou_ok": bool(iou >= IOU_MIN),
                  "reload_plate_unique": len(pl2) == 1, "pass": bool(okj)},
        "controls": ctrl,
        "blind_spots": BLIND,
    }
    if a.meta:
        os.makedirs(os.path.dirname(os.path.abspath(a.meta)), exist_ok=True)
        data = json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8").replace(b"\r\n", b"\n")
        open(a.meta, "wb").write(data)
        print("meta       :", a.meta)
    return 0 if okj else 1


if __name__ == "__main__":
    sys.exit(main())
