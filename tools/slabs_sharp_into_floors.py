# -*- coding: utf-8 -*-
"""把 `tools/slab_sharp.py` 算出的**直角楼板**（`_gen/slab_prisms.json`）换进交付包分层件的
**2~11 层**（节点 `floor1..floor10`）。

★ 落点（用户判词 2026-10-13「楼板在直角处，还是有圆角」）：
  1 层的板在 `demo/build_pack.py` 的 ②.55 已换成 AutoCAD 描的那块（`tools/slab_into_floor.py`）；
  **2~11 层仍是 libs3d v7 的 `s_` 板**，其轮廓出自 `build7.py:324` `_pn.buffer(r).buffer(-r)`
  —— 两次都吃 shapely 默认 `join_style=round` ⇒ 形态学闭运算把**凹角磨成弧**（凸角不受影响）。
  `tools/slab_sharp.py` 已从 **v8 墙实体**重取底面、**不做任何闭运算** ⇒ 本脚本只负责搬它。

★★ **两个坐标系，实测**（这是本脚本唯一容易搞错的地方）：

  墙件族 `libs3d/c006/c006_v8_f<k>_wall.glb`（`slab_sharp.py` 的输入）是 **Z-up**：
      f1  x  −145..129155  y(plan)  −205..83795  z(标高)       0.. 3600
      f8  x 41230..87730   y(plan) 25475..48515  z(标高)   25200..28800
  交付件族 `libs3d/browser/示例模型/c006-v8-f<k>-colored.glb`（`floors_from_libs3d.py` 的输入）
  是 **Y-up**（glTF），两者恰好差 glTF 那条 **(x, y, z) → (x, z, −y)**：
      f1  x  −145..129155  y(标高)       0.. 3720  z  −83795..205      ← z = −(墙件的 plan y)
  而 `pack_d1.xform` 把平移放在 **index 2**、高度放在 **index 1** ⇒ 它要的是 **Y-up**。
  ⇒ **prism 必须先换轴再套 `xform`**（见 `build_prism_mm`）；直接喂 Z-up 的 prism 实测轴号表
    四种组合全差 87~129 m（板面积却对得上 0.07% —— 症状长得像「搬错地方」而不是「轴反了」）。

  换轴后 `xform(sx=+1, sz=+1)` 就是对的（实测：f1 换轴 ×0.001 后 x −64.48 ⇒ −64.625..64.675，
  z +36.996 ⇒ −46.799..37.201，与包内 `floor0` 逐位吻合）—— 与 `tools/floors_from_libs3d.py:179`
  **同一个函数、同一口径**（铁律 196：不许另写一份变换）。
  轴号 (sx, sz) 仍由**轴号表**在包内定出（与 `slab_into_floor` 同一把尺子），**不读任何 meta**，
  并且 10 层必须**同解** —— 不同解就说明框的假设坏了。

★ 与 `tools/slab_into_floor.py` 的分工：那条换 `floor0`（1 层，AutoCAD 链）；
  本脚本换 `floor1..floor10`（2~11 层，libs3d 墙实体重取）。两者**互不重叠**。
  ★ 量具一律**复用** `slab_into_floor`（`find_plates`/`horiz_areas`/`footprint`/`rect`/
    `node_mesh`/`save_scene`）—— 同一个量不许有两个实现（铁律 174）。

★ 拉伸用 `trimesh.creation.extrude_polygon`（**不是** Blender）：prism 表 **holes 全 0**、
  轮廓只需保真不需要布尔，earcut 三角化的**边界顶点一个不改**（只加内部对角线）；
  代价是复杂多边形可能三角化失败 ⇒ 本脚本对每一件自检 **watertight + split=1 + 体积 = 轮廓面积×厚**，
  不过就停并打出 Blender 命令（`tools/prism_blender.py` 那条路仍然可用）。

★★ **轮廓有点接触，必须先 mitre 闭一下**（`CLOSE_MM = 0.5 mm`，见 `build_prism_mm`）：
  环里有**重复顶点**（实测第 2 层 60 个、第 5 层 56 个、第 7 层 9 个；第 3/4/8~11 层 1~3 个），
  即平面某两块只在**一点**相接。拉伸后可水密、体积也对，但两块**只共顶点不共边** ⇒
  `split()` 把**一块板读成 5~16 块**（第 2 层 14 块 = 5241.13+641.61+6.82+0.44+…），
  下游 `find_plates` 只认最大那块 ⇒ 判词报「板少了 650 m²」——**症状长得像几何坏了，
  其实是分块**。用 **mitre**（`join_style=2`）闭 0.5 mm 即并掉，实测面积变化 ≤1e-3 mm²。
  ★ 必须是 mitre：round join 正是本任务要修的那个错法（`build7.py:324`）。

★ 判据四件套（§10.0.1）：① 量**写出的** GLB ② 量具与参照物写明 ③ 盲区声明 ④ 正对照必配
用法:
  python tools/slabs_sharp_into_floors.py --floors <分层.glb> --prisms 过程/_gen/slab_prisms.json
                                          --out <换后.glb> [--meta out.json]
"""
import argparse
import importlib.util
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import numpy as np                                                       # noqa: E402
import trimesh                                                           # noqa: E402
from shapely.geometry import Polygon                                     # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sif = _load("slab_into_floor", os.path.join(HERE, "slab_into_floor.py"))
p1 = sif.p1

N_FLOOR = 11
FIRST_K = 2                     # 1 层（floor0）归 slab_into_floor.py；本脚本从 2 层起
ALIGN_TOL_M = sif.ALIGN_TOL_M
CTRL_MIN_M = sif.CTRL_MIN_M
SWAP_TOL_M2 = sif.SWAP_TOL_M2
ELEV_TOL_M = 0.30               # 板底标高 vs 节点包围盒底面：两处**独立**读数，给 0.3 m
VOL_TOL = 1.0e-3                # 拉伸件自检：|体积 − 轮廓面积×厚| 的相对容差
CLOSE_MM = 0.5                  # ★ 轮廓的 **mitre** 闭运算半径(mm)：只并点接触，见 build_prism_mm

BLIND = [
    "★ 本脚本**不判板画得对不对**：轮廓出自 `tools/slab_sharp.py`（从 libs3d **v8 墙实体**的平面"
    "投影取外环），它的正确性锚在那条链自己的判据（漏出量：thr=1 m² ⇒ 11 层 ≤0.008 m²）与"
    "`_gen/slab_sharp_report.json` 上。本节只判「**搬对了地方没有**」。",
    "★ **「换轴」是本脚本最容易错的一步**：prism 出自 Z-up 的墙件，`pack_d1.xform` 要 Y-up。"
    "这一步**没有独立判据**，它靠轴号表在数值上背书（错了就四组全不落）。若哪天墙件族的朝向变了，"
    "症状是轴号表全红（分辨力为 0）——那是这条前提的哨兵，不是几何坏了。",
    "★ 本脚本**不判 1 层**：`floor0` 归 `tools/slab_into_floor.py`（AutoCAD 链），本步只把它抄过去，"
    "并在写盘后只判它「面数 + bbox 一个字节没动」。",
    "★ **塔楼板下限**：`PLATE_MIN_M2`=1000 m² 是 1 层（7678 m²）语境下定的；8~11 层的板实测 "
    "**913.67 m²**，按 1000 卡整层认不到（实跑过）。本脚本按层取 `min(1000, 0.5×该层轮廓面积)`，"
    "1~7 层因此**仍走原阈值**。",
    "**颜色是借来的**：新板顶点色抄**被摘掉的旧板**的中位色（本脚本不发明配色）。颜色不进任何判据。",
    "★ **新板必须先焊顶点**，理由与 `tools/slab_into_floor.py` 同：不焊则写出的文件被默认口径重读时"
    "板会碎（实测 1163 个连通分量 vs 焊后 1298）。本脚本在并进去之前 `merge_vertices()`。",
    "★ 量「写出的件」一律显式 `process=True`（与 `slab_into_floor.py` 同口径）。",
    "★ **只量包围盒四边**：板**里面**的东西（洞的位置、斜撑、开洞尺寸）这四条全盲。",
    "★ **点接触并掉多少是量过的，不是假设的**：轮廓环里的重复顶点实测第 2 层 60 个、第 5 层 56 个、"
    "第 7 层 9 个；mitre 闭 0.5 mm 后 10 层全部 split=1、面积变化 ≤1e-3 mm²。"
    "但若哪天轮廓的点接触**宽于 1 mm**，0.5 mm 就并不掉 ⇒ 症状是自检 split≠1 直接停（会响），"
    "**不是**静默少 650 m²（铁律 199：把「没量到」与「坏了」分开）。",
]

_LOG = []


def log(s):
    _LOG.append(s)
    print(s)


# ---------------- 量具（复用 sif；只加一个「按标高找板」的入口） ----------------
def node_of(k):
    return "floor%d" % (k - 1)


def min_up_for(area_want_m2):
    """该层的「板」下限：1~7 层仍走 `slab_into_floor.PLATE_MIN_M2`，塔楼层按轮廓面积放宽。"""
    return min(sif.PLATE_MIN_M2, 0.5 * area_want_m2)


def read_prisms(path):
    d = json.load(open(path, encoding="utf-8"))
    if d.get("units") != "m":
        raise SystemExit("!! %s 的 units=%r（本脚本只认 'm'）⇒ 不猜" % (path, d.get("units")))
    out = {}
    for s in d["solids"]:
        if s.get("holes"):
            raise SystemExit("!! %s 带洞（%d 个）⇒ trimesh 拉伸这条路不适用，"
                             "请走 tools/prism_blender.py" % (s["name"], len(s["holes"])))
        k = int(s["name"].split(".")[0].lstrip("f"))
        out[k] = {"name": s["name"], "poly_m": [(float(p[0]), float(p[1])) for p in s["poly"]],
                  "z0": float(s["z0"]), "z1": float(s["z1"])}
    for k in range(FIRST_K, N_FLOOR + 1):
        if k not in out:
            raise SystemExit("!! prism 表里没有第 %d 层（%s 里只有 %s）⇒ 不猜"
                             % (k, path, sorted(out)))
    return out


def build_prism_mm(rec):
    """规范棱柱（**米**，Z-up）→ **Y-up** 的 mm 实体（`pack_d1.xform` 要的口径）。

    返回 (mesh, 轮廓面积 m²)。Z-up→Y-up 用 glTF 那条 `(x, y, z) → (x, z, −y)`，见模块 docstring。
    """
    sh = [(x * 1000.0, y * 1000.0) for x, y in rec["poly_m"]]
    if len(sh) > 1 and sh[0] == sh[-1]:
        sh = sh[:-1]
    pg = Polygon(sh)
    if not pg.is_valid:
        pg = pg.buffer(0)
    # ★★ 轮廓有**点接触**：环里有**重复顶点**（实测 1~60 个：第 2 层 1063/1123、第 5 层 868/924），
    #   即两块平面只在**一个点**上相接。拉伸后这两块只共**一个顶点**、不共**边** ⇒
    #   `split()`（按面-面共边分解）把**一块板**读成 5~16 块（实跑：第 2 层 14 块，面积分给
    #   5241.13+641.61+6.82+0.44+…；第 5/6 层 16 块。第 3/4/8~11 层无点接触 ⇒ split=1，一向全绿）
    #   ⇒ 下游 `find_plates` 只看见最大那块，报「板少了 650 m²」。
    #   处置：**mitre**（`join_style=2`，不是 round）闭 `CLOSE_MM`，只并掉亚毫米的点接触。
    #   实测（`_scratch/probe_sharp.py`）0.5 mm 闭 ⇒ 10 层全部 split=1，面积变化 ≤1e-3 mm²
    #   （1e-9 m²，对 SWAP_TOL_M2=0.5 m² 可忽略）。
    #   ★ 这里**必须**是 mitre：round join 正是本任务要修的那个错法（`build7.py:324`）。
    pg = pg.buffer(CLOSE_MM, join_style=2, mitre_limit=5.0).buffer(
        -CLOSE_MM, join_style=2, mitre_limit=5.0)
    if pg.geom_type != "Polygon":
        raise SystemExit("!! 第 %s 层轮廓 mitre 闭 %s mm 后成了 %s（应仍是单个 Polygon）⇒ 不猜"
                         % (rec["name"], CLOSE_MM, pg.geom_type))
    h = (rec["z1"] - rec["z0"]) * 1000.0
    m = trimesh.creation.extrude_polygon(pg, h)             # 沿 +z 拉，z 是**标高**
    m.apply_translation([0.0, 0.0, rec["z0"] * 1000.0])
    m.merge_vertices()
    V = np.asarray(m.vertices, float)                       # ★ Z-up → Y-up
    m.vertices = np.column_stack([V[:, 0], V[:, 2], -V[:, 1]])
    want = pg.area * h
    n_split = len(m.split(only_watertight=False))
    if not (m.is_watertight and n_split == 1 and want > 0
            and abs(abs(float(m.volume)) - want) <= VOL_TOL * want):
        raise SystemExit("!! 第 %s 层拉伸件自检不过（watertight=%s split=%d 体积 %.3f vs "
                         "轮廓×厚 %.3f）⇒ earcut 三角化失败；改走 "
                         "`blender -b --python tools/prism_blender.py`"
                         % (rec["name"], m.is_watertight, n_split, float(m.volume), want))
    return m, pg.area / 1.0e6


def is_plate(c, base_y, min_up_m2):
    """「板」的判据与 `slab_into_floor.find_plates` **逐字同源**，只把「贴底」与「面积下限」参数化。"""
    return (abs(float(c.bounds[0][1]) - base_y) <= sif.BASE_TOL_M
            and sif.PLATE_THICK_MM[0] / 1000.0
            < float(c.bounds[1][1] - c.bounds[0][1]) < sif.PLATE_THICK_MM[1] / 1000.0
            and sif.horiz_areas(c)[0] > min_up_m2
            and abs(sif.horiz_areas(c)[0] - sif.horiz_areas(c)[1]) < 1.0)


def axis_pick(prism_mm, r_old, lib, pk, extra=(0.0, 0.0)):
    """四种轴号组合各搬一次，量与**旧板**平面矩形四边的最大残差。返回 (胜出组, 全表, 分辨力)。"""
    rows = []
    for sx in (1, -1):
        for sz in (1, -1):
            T = np.array(p1.xform(sx, sz, lib, pk), float)
            T[0, 3] += extra[0]
            T[2, 3] += extra[1]
            m = p1.apply_T(prism_mm, T)
            r = sif.rect(m)
            e = max(abs(r["x"][0] - r_old["x"][0]), abs(r["x"][1] - r_old["x"][1]),
                    abs(r["z"][0] - r_old["z"][0]), abs(r["z"][1] - r_old["z"][1]))
            rows.append({"sx": sx, "sz": sz, "edge_err_m": round(e, 3), "T": T, "mesh": m})
    good = [r for r in rows if r["edge_err_m"] <= ALIGN_TOL_M]
    if len(good) != 1:
        return None, rows, 0.0
    pick = good[0]
    margin = min(r["edge_err_m"] for r in rows if r is not pick) - pick["edge_err_m"]
    return pick, rows, margin


def judge_swapped(m, base_y, min_up_m2, want_m2, old_m2):
    """写出的件里，板必须是**新板**：面积对上轮廓、且与旧板差得开。缺一条就分不出「换了」与「没生效」。"""
    pl = sif.find_plates(m, base_y=base_y, min_up_m2=min_up_m2)
    if len(pl) != 1:
        return False, None, "板不是恰好 1 块（%d）" % len(pl)
    ar = pl[0]["up_m2"]
    if abs(ar - want_m2) > SWAP_TOL_M2:
        return False, ar, "板面积 %.3f ≠ 新板轮廓 %.3f（差 %.3f）" % (ar, want_m2, ar - want_m2)
    if abs(ar - old_m2) <= SWAP_TOL_M2:
        return False, ar, "板面积与旧板相同（%.3f）⇒ 等于没换" % ar
    return True, ar, ""


# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--floors", required=True)
    ap.add_argument("--prisms", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", default=None)
    a = ap.parse_args()

    for p in (a.floors, a.prisms, p1.LIBS3D_BUILD):
        if not os.path.exists(p):
            print("!! 缺输入 %s ⇒ SKIP(rc=4)" % p)
            return 4

    rec = read_prisms(a.prisms)
    lib, pk = p1.libs3d_d1_origin(), p1.pack_d1_origin()
    floors = trimesh.load(a.floors)
    names_in = sorted(floors.geometry.keys())
    log("slabs_sharp_into_floors · 换 2~11 层的板（输入 %d 个节点：%s）" % (len(names_in), names_in))

    out_meshes = {n: floors.geometry[n].copy() for n in names_in}
    per, fails, picks = [], [], []
    for k in range(FIRST_K, N_FLOOR + 1):
        node = node_of(k)
        if node not in floors.geometry:
            print("!! 分层件里没有节点 %s ⇒ SKIP(rc=4)" % node)
            return 4
        m0 = sif.node_mesh(floors, node)
        prism_mm, area_want = build_prism_mm(rec[k])
        min_up = min_up_for(area_want)
        base_y = rec[k]["z0"]                                # 板底标高（slab_sharp 从 v7 `s_` 带抄的）
        bmin = float(m0.bounds[0][1])                        # 该节点自己的底面（**另一处读数**）
        log("-" * 78)
        log("第 %d 层 (%s)  板底标高 %.3f m（prism）vs 节点底面 %.3f m（bbox）｜差 %.3f m"
            % (k, node, base_y, bmin, abs(base_y - bmin)))
        if abs(base_y - bmin) > ELEV_TOL_M:
            fails.append("第 %d 层：板底 %.3f 与节点底面 %.3f 差 %.3f m > %.2f ⇒ 两处读数不一致"
                         % (k, base_y, bmin, abs(base_y - bmin), ELEV_TOL_M))
            continue

        pl = sif.find_plates(m0, base_y=base_y, min_up_m2=min_up)
        if len(pl) != 1:
            print("!! %s 里按几何认出 %d 块板（应恰好 1，下限 %.1f m²）⇒ 没量到，不猜"
                  % (node, len(pl), min_up))
            for q in pl:
                print("     up=%.3f m² span=%.3f faces=%d" % (q["up_m2"], q["span_m"], q["faces"]))
            return 4
        old = pl[0]
        r_old = sif.rect(old["mesh"])

        pick, rows, margin = axis_pick(prism_mm, r_old, lib, pk)
        log("  轴号表      %s" % "  ".join(
            "x%s z%s %7.3f" % ("+" if r["sx"] > 0 else "−", "+" if r["sz"] > 0 else "−", r["edge_err_m"])
            for r in rows))
        log("  旧板 %.3f m² · 新板轮廓 %.3f m²（面积差不进判据：两条链边界口径本来就不同）"
            % (old["up_m2"], area_want))
        if pick is None:
            fails.append("第 %d 层：轴号定不下来（容差内组合 %d 个）⇒ 落地偏了"
                         % (k, sum(1 for r in rows if r["edge_err_m"] <= ALIGN_TOL_M)))
            continue
        if margin < CTRL_MIN_M:
            fails.append("第 %d 层：轴号分辨力只有 %.3f m（<%.1f）⇒ 这条判据没牙"
                         % (k, margin, CTRL_MIN_M))
            continue
        log("  ⇒ 定死 x%s z%s（其余组合最近 %.3f m ⇒ 分辨力 %.3f m）"
            % ("+" if pick["sx"] > 0 else "−", "+" if pick["sz"] > 0 else "−",
               min(r["edge_err_m"] for r in rows if r is not pick), margin))
        picks.append((k, pick["sx"], pick["sz"]))

        # 颜色借旧板的：本脚本不发明配色
        col = None
        try:
            vc = np.asarray(old["mesh"].visual.vertex_colors)
            col = np.median(vc[:, :3], axis=0).astype(np.uint8)
        except Exception:
            pass
        new = pick["mesh"].copy()
        new.merge_vertices()                                 # ★ 先焊顶点，见 BLIND
        if col is not None:
            new.visual.vertex_colors = np.tile(np.concatenate([col, [255]]), (len(new.vertices), 1))

        comps = m0.split(only_watertight=False)              # ★ 只拆一次，下面复用
        keep = [c for c in comps if not is_plate(c, base_y, min_up)]
        n_rm = len(comps) - len(keep)
        if n_rm != 1:
            fails.append("第 %d 层：摘掉的分量 %d 个（应恰好 1）" % (k, n_rm))
            continue
        merged = trimesh.util.concatenate(keep + [new])
        if len(merged.faces) != len(m0.faces) - old["faces"] + len(new.faces):
            fails.append("第 %d 层：面数守恒不成立" % k)
            continue
        out_meshes[node] = merged
        log("  替换        摘 %d 块 · 新板 %d 面 · 合并 %d 面（原 %d）"
            % (n_rm, len(new.faces), len(merged.faces), len(m0.faces)))
        per.append({"floor": k, "node": node, "base_y_m": round(base_y, 3),
                    "old_up_m2": round(old["up_m2"], 3), "new_outline_m2": round(area_want, 3),
                    "min_up_m2": round(min_up, 1),
                    "axis": {"x": pick["sx"], "z": pick["sz"]}, "margin_m": round(margin, 3),
                    "old_faces": old["faces"], "new_faces": int(len(new.faces)),
                    "color": None if col is None else [int(v) for v in col]})

    # 10 层必须**同解**：不同解 = 「同框 + 换轴」这条前提坏了
    axes = {(sx, sz) for _k, sx, sz in picks}
    if len(axes) > 1:
        fails.append("2~11 层的轴号不是同解：%s ⇒ 「同框 + 换轴」这条前提坏了" % sorted(axes))
    elif axes:
        log("-" * 78)
        log("轴号同解   : x%s z%s（%d 层全一致）"
            % ("+" if list(axes)[0][0] > 0 else "−", "+" if list(axes)[0][1] > 0 else "−", len(picks)))

    if fails:
        log("-" * 78)
        log("★ 前面有 %d 条不成立 ⇒ **不写产物**（写了就是一个看起来修好的坏件）" % len(fails))
        for x in fails:
            log("  ✗ " + x)
        return 1

    # ---- 写盘 + 重读核（只读盘上那一份，不读内存中间量）----
    sif.save_scene({n: out_meshes[n] for n in names_in}, a.out)
    chk = trimesh.load(a.out, force="scene", process=True)
    names = sorted(chk.geometry.keys())
    if names != names_in:
        log("!! 写出的节点名单对不上：%s" % names)
        return 1
    log("-" * 78)
    log("重读核     : 节点 %d 个 %s" % (len(names), names))

    n_ok = 0
    for e in per:
        ok, ar, why = judge_swapped(sif.node_mesh(chk, e["node"]), e["base_y_m"], e["min_up_m2"],
                                    e["new_outline_m2"], e["old_up_m2"])
        log("  第 %-2d 层 %-8s 板面积 %-9s（该 = %8.3f，旧 %8.3f）%s"
            % (e["floor"], e["node"], "—" if ar is None else "%.3f" % ar,
               e["new_outline_m2"], e["old_up_m2"], "✓" if ok else "✗ " + why))
        if ok:
            n_ok += 1
        else:
            fails.append("J-已换 第 %d 层：%s" % (e["floor"], why))

    # 没换的节点（floor0 / B1 / …）逐位未动
    touched_names = {node_of(k) for k in range(FIRST_K, N_FLOOR + 1)}
    lost = []
    for n in names:
        if n in touched_names:
            continue
        mi, mo = floors.geometry[n], chk.geometry[n]
        if int(len(mi.faces)) != int(len(mo.faces)):
            lost.append("%s 面数 %d≠%d" % (n, len(mi.faces), len(mo.faces)))
        elif not np.allclose(np.asarray(mi.bounds, float), np.asarray(mo.bounds, float), atol=1e-9):
            lost.append("%s bbox 变了" % n)
    untouched = sorted(set(names) - touched_names)
    log("  未动的 %d 个节点 %s %s" % (len(untouched), untouched, "✓" if not lost else "✗ %s" % lost))
    if lost:
        fails.append("J-未动：%s" % lost)

    # ---- 正对照：每条点名它该红哪条判据 ----
    ctrl = []
    base_fails = list(fails)

    def ctl(nm, got, want):
        new = [x for x in got if x not in base_fails]
        ok = bool(new) and all(any(w in x for x in new) for w in want)
        ctrl.append({"name": nm, "expect": want, "n_new": len(new), "ok": bool(ok)})
        log("  对照 %-24s → %s（新增 %d 条，要 %s）" % (nm, "✔红" if ok else "✘没红", len(new), want))
        if not ok:
            fails.append("对照「%s」该红而没红" % nm)

    # C2：把某一层的板整体平移 +8 m ⇒ 轴号表四种组合一个都落不进容差
    e0 = per[0]
    k2 = e0["floor"]
    r2 = sif.rect(sif.find_plates(sif.node_mesh(floors, e0["node"]), base_y=e0["base_y_m"],
                                  min_up_m2=e0["min_up_m2"])[0]["mesh"])
    pk2, _rows2, _mg = axis_pick(build_prism_mm(rec[k2])[0], r2, lib, pk, extra=(8.0, 0.0))
    ctl("轴号：板整体 +8 m", ["轴号定不下来"] if pk2 is None else [], ["轴号定不下来"])
    # C3：拿**没换**的原件冒充产物 ⇒ 面积等于旧板 ⇒ 该红「等于没换」
    ok3, _a3, _w3 = judge_swapped(sif.node_mesh(floors, e0["node"]), e0["base_y_m"], e0["min_up_m2"],
                                  e0["new_outline_m2"], e0["old_up_m2"])
    ctl("原件冒充产物", [] if ok3 else ["等于没换"], ["等于没换"])

    okj = not fails
    log("-" * 78)
    log("slabs_sharp_into_floors 总判 : %s（换了 %d/%d 层）"
        % ("PASS" if okj else "FAIL（%d 条）" % len(fails), n_ok, len(per)))
    for x in fails:
        log("  ✗ " + x)
    if len(touched_names) != len(per):
        log("  （注意：%d 层没能换，见上面各层的判词）" % (len(touched_names) - len(per)))

    if a.meta:
        meta = {
            "schema": "cdut3d-slabs-sharp/1",
            "prisms": a.prisms, "floors_in": a.floors, "out": a.out,
            "chain": "tools/slab_sharp.py（libs3d v8 墙实体 → 平面投影并集 → 取外环，**无闭运算**）"
                     " → 本脚本 extrude + **Z-up→Y-up 换轴** → pack_d1.xform 搬进包",
            "why": "build7.py:324 `_pn.buffer(r).buffer(-r)` 两次吃默认 join_style=round ⇒ "
                   "形态学闭运算把**凹角磨成弧**（凸角不受影响）—— 用户判词「楼板在直角处还是有圆角」",
            "frame": {"prism_source": "libs3d/c006/c006_v8_f<k>_wall.glb —— **Z-up**（index2=标高）",
                      "pack_target": "libs3d/browser/示例模型/c006-v8-f<k>-colored.glb —— **Y-up**（glTF）",
                      "conversion": "(x, y, z) → (x, z, −y)（glTF yup）；实测 f1 z −83795..205 = −(墙件 plan y）",
                      "transform": "pack_d1.xform(sx, sz, lib, pk)，与 tools/floors_from_libs3d.py:179 同源"},
            "axis": None if not axes else {"x": list(axes)[0][0], "z": list(axes)[0][1]},
            "axis_same_for_all_floors": len(axes) <= 1,
            "per_floor": per,
            "untouched_nodes": untouched,
            "judge": {"n_swapped": n_ok, "pass": bool(okj)},
            "controls": ctrl,
            "blind_spots": BLIND,
        }
        os.makedirs(os.path.dirname(os.path.abspath(a.meta)), exist_ok=True)
        open(a.meta, "wb").write(
            json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8").replace(b"\r\n", b"\n"))
        log("meta       : %s" % a.meta)
    return 0 if okj else 1


if __name__ == "__main__":
    sys.exit(main())
