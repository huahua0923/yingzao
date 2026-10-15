# -*- coding: utf-8 -*-
"""把 **libs3d 已经建好、且已经过了它自己判据的** 地下一层搬进模型包，当分层里的 `B1` 节点。

★ 本脚本**不建几何**。地下一层的几何来自 libs3d 的交付件：
    `D:\\项目\\libs3d\\browser\\示例模型\\c006-v8-fd1-colored.glb`
  那是 libs3d 那条链自己建的（`build8.py` 的 `SHEETS` 第一行 `("地下1层","R",5,-1)`），
  层高 `BH=4200`、判据「并集体积 = 足迹面积 × 层高」100%、随交付页发布。
  cdut3d 这边**只做坐标搬运**（毫米→米、Z 朝上→模型包的 Y 朝上、局部原点 → 包原点）。

★★ 为什么不再自己建：本仓 `tools/build_basement.py`（已归档）曾从 DXF 现建过一层。两版相比：
    · 平面矩形逐边残差 **0.000 m**（87.90 × 56.70 m —— 两条链独立得出的原点口径一致）；
    · 但**轴号反了**：自建那版把图纸的 y 直接当模型 z，而模型实际的 z = **−本地 y**
      （实测：baseline `floor0.json` 的墙 y ∈ [−37.07, +46.62]，模型 floor0 的 z ∈ [−46.80, +37.20]）。
      镜像之后，「主块中心 vs 塔楼中心」那条判据**照样绿** —— 因为塔楼关于 x=0/z=0 对称。
    · 墙的水平截面并集 198.8 m² vs libs3d 的 107.6 m²（自建多 85%），层高还是 3.5 m 的**假设**。
  ⇒ 同一个量有两处实现，留一处；轴号则在本脚本里**用实测对齐表定死**（见 ③）。

★★ 判据四件套（§10.0.1）：
  ① 量交付件本身 —— 重读**写出的** GLB 数节点/面数/包围盒，不读内存中间量
  ② 量具写明     —— trimesh 包围盒；参照物 = 包内 `floor0`（gym3d 那条链建的 F1）
  ③ 盲区声明     —— 见 BLIND
  ④ 正对照必配   —— 轴号表（另外三种符号组合必须对不齐）+ 三条扰动（见 CONTROLS）

用法:
  python tools/pack_d1.py --merge-into <分层.glb> --merged-out <带B1.glb> [--meta out.json]
"""
import sys
import os
import re
import ast
import json
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(HERE)
A1 = os.path.join(CDUT, "a1")
sys.path.insert(0, A1)
import sheet_grid as SG       # noqa: E402

GYM = r"D:\项目\gym3d\gym3d"
PROF = os.path.join(GYM, "data", "buildings", "c006", "profile.json")
DXF = r"D:\项目\gym3d\材料\dxf_output\C006-第六教学楼（逸夫楼）.dxf"
LIBS3D = r"D:\项目\libs3d\c006"
LIBS3D_BUILD = os.path.join(LIBS3D, "build8.py")
LIBS3D_DELIV = r"D:\项目\libs3d\browser\示例模型"
LIBS3D_F1 = os.path.join(LIBS3D_DELIV, "c006-v8-f1-colored.glb")
LIBS3D_D1 = os.path.join(LIBS3D_DELIV, "c006-v8-fd1-colored.glb")

SHEET_TAG = "6-C-D1-"          # 认图幅用的房号 token，不按下标/位置写死
ALIGN_TOL_M = 0.5              # 轴号表/落位容差：两条链的墙厚与配对规则不同，给半米
FLOOR_TOL_M = 0.01             # 埋深容差：底面必须等于 libs3d 公布的 BH

BLIND = [
    "**这层的几何不是本仓建的**：它来自 libs3d 的交付件，对错由 libs3d 那条链自己的判据背书"
    "（并集体积=足迹×层高 100%、IoU 98.8%）。本包**没有**独立复算过那两条 —— 本节只判"
    "「搬对了地方没有」。",
    "埋深 −4.2 m 取自 libs3d `build8.py` 的常量 `BH=4200`（DXF 里**一处标高文字都没有**，已实测）"
    "⇒ 那是 libs3d 的假设，本包只是沿用，**没有独立证据**。",
    "轴号（x 是否取反、z 是否取反）靠**与包内 floor0 的平面矩形对齐**定出来，参照物是 gym3d 那条链"
    "的 F1。四条边对齐到 ±0.5 m 之内、其余三种符号组合都差 9 m 以上 —— 所以这个判据对**轴号**有力，"
    "对**几米以内的平移误差**无力。",
    "libs3d 的 D1 件里不止墙，还含**楼板 / 门 / 电梯 / 楼梯平台**（它就是那一层的完整交付）；"
    "本节量的「平面矩形」是**整个件的包围盒**，与 `build_basement.py` 时代那个「墙线覆盖」"
    "**不是同一个量**，别拿来互相减。",
    "JJ 的参照物（包内 `floor0`）是 gym3d 的 F1，墙厚/配对规则与 libs3d 不同 ⇒ 0.5 m 容差"
    "就是给这个差异留的，不是给「搬歪了」留的。",
]

def _xlate(m, d):
    o = m.copy(); o.apply_translation(d); return o


def _scale_about(m, s, p):
    o = m.copy()
    o.apply_translation(-np.asarray(p, float))
    o.apply_scale(s)
    o.apply_translation(np.asarray(p, float))
    return o


def controls(d1, lib, pk, bh_m):
    """四条正对照。每条**点名它该红的是哪一条判据** —— 红了别的判据也算没触发。"""
    b = d1.bounds
    px = (float(b[0][0]) + float(b[1][0])) / 2.0
    pz = (float(b[0][2]) + float(b[1][2])) / 2.0
    y0 = float(b[0][1])
    return [
        ("平移 +8 m（x）", _xlate(d1, [8.0, 0.0, 0.0]), "J2",
         "右边界 64.65 + 8 = 72.65 > floor0 的 64.65"),
        ("抬高 3 m", _xlate(d1, [0.0, 3.0, 0.0]), "J1",
         "底面 −4.2 + 3 = −1.2 ≠ −4.2"),
        ("放大 5%（绕底面中心）", _scale_about(d1, 1.05, (px, y0, pz)), "J2",
         "深 56.70 × 1.05 = 59.5 m、宽 87.90 × 1.05 = 92.3 m ⇒ 右端越出 floor0"),
        # ★ 这条才是要害：把 x 的轴号取反重搬一遍，必须红。
        #   上一版「自建 B1」正是栽在这里，而当时的判据（比塔楼中心）看不见它。
        ("x 轴号取反（x− z+）", apply_T(load_mesh(LIBS3D_D1), xform(-1, 1, lib, pk)), "J2",
         "镜像后 x 落到 −105.7..−193.6 m ⇒ 整层甩出 floor0"),
    ]


# ---------------- libs3d 侧的常量：从它的源码里读，不手打 ----------------
def _const(src, name):
    """按**名字**从 `A, B, C = 1.0, 2.0, 3.0` 这种多重赋值里取值。

    ★ 不许写成 `BH\\s*=\\s*([0-9.]+)` —— 那会在 `H, SLAB_T, BH = 3600.0, 120.0, 4200.0`
      这一行上抓到 **3600.0**（层高 H），把层高报成 3.6 m 还看不出错。
      这里按逗号切开对齐名字与值，取到哪个名字就是哪个。
    """
    for m in re.finditer(r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*(?:[ \t]*,[ \t]*[A-Za-z_][A-Za-z0-9_]*)*)"
                         r"[ \t]*=[ \t]*(.+?)[ \t]*$", src, re.M):
        names = [t.strip() for t in m.group(1).split(",")]
        if name not in names:
            continue
        vals = [t.strip() for t in m.group(2).split(",")]
        if len(vals) != len(names):
            continue
        try:
            return float(ast.literal_eval(vals[names.index(name)]))
        except Exception:
            continue
    raise SystemExit("!! 从 %s 里按名字取不出常量 %s ⇒ 它的口径变了，不猜" % (LIBS3D_BUILD, name))


def libs3d_d1_origin():
    src = open(LIBS3D_BUILD, encoding="utf-8").read()
    mX = re.search(r"^XB\s*=\s*(\{[^}]*\})", src, re.M)
    mY = re.search(r"^Y0,\s*Y1\s*=\s*([0-9.]+),\s*([0-9.]+)", src, re.M)
    mS = re.search(r"SHEETS\s*=\s*\[\(" + re.escape('"地下1层"') +
                   r",\s*\"([LR])\",\s*(\d+),\s*(-?\d+)\)\]", src, re.M)
    if not (mX and mY and mS):
        raise SystemExit("!! 从 libs3d 的 build8.py 里读不出 XB / Y0,Y1 / SHEETS 第一行 ⇒ "
                         "它的口径变了，本脚本的前提不成立，不猜")
    try:
        XB = ast.literal_eval(mX.group(1))
    except Exception:
        raise SystemExit("!! XB 解析失败：%r" % mX.group(1))
    y0, y1 = _const(src, "Y0"), _const(src, "Y1")
    col, row, k = mS.group(1), int(mS.group(2)), int(mS.group(3))
    if col not in XB:
        raise SystemExit("!! SHEETS 里的列 %r 不在 XB 里" % col)
    return {"col": col, "row": row, "k": k, "x_mm": float(XB[col]),
            "y_mm": y0 + row * y1, "bh_mm": _const(src, "BH"),
            "h_mm": _const(src, "H"), "src": LIBS3D_BUILD}


# ---------------- cdut3d 侧的原点：按 to_local 的逐层口径现算 ----------------
def _frames(msp):
    return SG.classify(SG.merge_pairs(SG.collect_frames(msp, SG.find_frame_layer(msp, None))))[1]


def detect_d1(msp):
    hit = None
    for c in _frames(msp):
        x0, y0, x1, y1 = c["bbox"]
        n = 0
        for e in msp:
            if e.dxftype() not in ("TEXT", "MTEXT"):
                continue
            s = (e.dxf.text if e.dxftype() == "TEXT" else e.text) or ""
            if SHEET_TAG in s and x0 <= e.dxf.insert.x <= x1 and y0 <= e.dxf.insert.y <= y1:
                n += 1
        if n:
            if hit is not None:
                raise SystemExit("!! 有 >1 张图幅带 %s 房号，本脚本不猜" % SHEET_TAG)
            hit = (c, n)
    if hit is None:
        raise SystemExit("!! 没找到带 %s 房号的图幅" % SHEET_TAG)
    return hit[0], hit[1]


def frame_delta(prof, frames):
    """`to_local` 的口径：floor_plans[i] = (图框中心x, 图框中心y − DELTA)。DELTA 须为常数。"""
    deltas = []
    for fp in prof["floor_plans"]:
        cand = [c for c in frames if abs((c["bbox"][0] + c["bbox"][2]) / 2 - fp[0]) < 1.0]
        if not cand:
            raise SystemExit("!! floor_plans 的 x 中心对不上任何图框")
        c = min(cand, key=lambda c: abs((c["bbox"][1] + c["bbox"][3]) / 2 - fp[1]))
        deltas.append((c["bbox"][1] + c["bbox"][3]) / 2 - fp[1])
    d = np.array(deltas)
    if d.std() > 1.0:
        raise SystemExit("!! 「图框中心y − plan_y中心」在 %d 层上不是常数（std=%.1f mm）"
                         "⇒ to_local 口径变了" % (len(deltas), d.std()))
    return float(d.mean())


def pack_d1_origin():
    import ezdxf
    prof = json.load(open(PROF, encoding="utf-8"))
    msp = ezdxf.readfile(DXF).modelspace()
    frames = _frames(msp)
    box, ntag = detect_d1(msp)
    delta = frame_delta(prof, frames)
    cx = (box["bbox"][0] + box["bbox"][2]) / 2.0
    cy = (box["bbox"][1] + box["bbox"][3]) / 2.0
    return {"ox": cx, "oy": cy - delta, "delta_mm": delta, "ntag": ntag,
            "frame_bbox": [float(v) for v in box["bbox"]]}


# ---------------- 搬运 ----------------
def load_mesh(path):
    g = trimesh.load(path)
    if isinstance(g, trimesh.Scene):
        try:
            return g.to_geometry()
        except Exception:
            return g.dump(concatenate=True)
    return g


def node_mesh(path, node):
    g = trimesh.load(path)
    if not isinstance(g, trimesh.Scene) or node not in g.geometry:
        raise SystemExit("!! %s 里没有节点 %s" % (path, node))
    m = g.geometry[node].copy()
    for ent in g.graph.nodes_geometry:
        if ent[1] == node:
            m.apply_transform(g.graph.get(ent[0])[0]); break
    return m


def xform(sx, sz, lib, pk):
    """libs3d 局部(mm, Z上) → 模型包(米, Y上)。平移由两条链各自的原点口径之差给出，不做拟合。"""
    T = np.eye(4)
    T[0, 0] = sx * 0.001
    T[1, 1] = 0.001
    T[2, 2] = sz * 0.001
    T[0, 3] = (lib["x_mm"] - pk["ox"]) / 1000.0
    T[2, 3] = (pk["oy"] - lib["y_mm"]) / 1000.0
    return T


def apply_T(m, T):
    o = m.copy(); o.apply_transform(T); return o


def plan_rect(m):
    b = m.bounds
    return {"x": (float(b[0][0]), float(b[1][0])), "y": (float(b[0][1]), float(b[1][1])),
            "z": (float(b[0][2]), float(b[1][2]))}


def edge_err(a, b):
    return max(abs(a["x"][0] - b["x"][0]), abs(a["x"][1] - b["x"][1]),
               abs(a["z"][0] - b["z"][0]), abs(a["z"][1] - b["z"][1]))


def judge(m, f0, bh_m):
    """J1 埋深（底面 = −BH 且不高过 ±0.000）· J2 平面矩形必须落在 floor0 之内"""
    b = plan_rect(m)
    fails = []
    if abs(b["y"][0] + bh_m) > FLOOR_TOL_M:
        fails.append("J1:底面 %.3f m ≠ −BH(%.3f)（差 %.3f）" % (b["y"][0], -bh_m, abs(b["y"][0] + bh_m)))
    if b["y"][1] > FLOOR_TOL_M:
        fails.append("J1:顶面 %.3f m 高过 ±0.000" % b["y"][1])
    for ax in ("x", "z"):
        lo, hi = b[ax]
        rlo, rhi = f0[ax]
        if lo < rlo - ALIGN_TOL_M or hi > rhi + ALIGN_TOL_M:
            fails.append("J2:平面 %s %.3f..%.3f 越出 floor0 的 %.3f..%.3f" % (ax, lo, hi, rlo, rhi))
    return fails, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge-into", required=True)
    ap.add_argument("--merged-out", required=True)
    ap.add_argument("--meta", default=None)
    a = ap.parse_args()

    for p in (LIBS3D_BUILD, LIBS3D_F1, LIBS3D_D1, DXF, PROF, a.merge_into):
        if not os.path.exists(p):
            print("!! 缺输入 %s" % p); return 2

    lib = libs3d_d1_origin()
    pk = pack_d1_origin()
    print("libs3d 侧: 地下1层 第 %s 列第 %d 行  原点 (%.0f, %.0f) mm  层高 H=%.1f / 地下 BH=%.1f mm  ← %s"
          % (lib["col"], lib["row"], lib["x_mm"], lib["y_mm"], lib["h_mm"], lib["bh_mm"],
             os.path.basename(lib["src"])))
    print("cdut3d 侧: D1 图幅 bbox x %.0f..%.0f y %.0f..%.0f  房号 %s×%d  原点 (%.0f, %.0f) mm"
          "（图框中心y − plan_y中心 = %.1f 在 11 层上一致）"
          % (pk["frame_bbox"][0], pk["frame_bbox"][2], pk["frame_bbox"][1], pk["frame_bbox"][3],
             SHEET_TAG, pk["ntag"], pk["ox"], pk["oy"], pk["delta_mm"]))

    f0m = node_mesh(a.merge_into, "floor0")
    f0 = plan_rect(f0m)
    print("参照物   : 包内 floor0（gym3d 链） 平面 x %.2f..%.2f  z %.2f..%.2f"
          % (f0["x"][0], f0["x"][1], f0["z"][0], f0["z"][1]))

    # ---- ③ 轴号：搬 libs3d 的 F1 进来，四条边都要落到 floor0 上；只有一种符号组合做得到 ----
    f1 = load_mesh(LIBS3D_F1)
    table = []
    print("\n轴号表   : 把 libs3d 的 F1 按四种符号组合搬进来，量它与包内 floor0 的四边残差")
    for sx in (1, -1):
        for sz in (1, -1):
            r = plan_rect(apply_T(f1, xform(sx, sz, lib, pk)))
            e = edge_err(r, f0)
            table.append({"sx": sx, "sz": sz, "edge_err_m": round(e, 3)})
            print("   x%s z%s   四边最大残差 %7.3f m   %s"
                  % ("+" if sx > 0 else "−", "+" if sz > 0 else "−", e,
                     "✓ 对齐" if e <= ALIGN_TOL_M else "✗"))
    good = [t for t in table if t["edge_err_m"] <= ALIGN_TOL_M]
    if len(good) != 1:
        print("!! 轴号定不下来（对齐的符号组合有 %d 个）⇒ 不猜，停" % len(good))
        return 1
    sx, sz = good[0]["sx"], good[0]["sz"]
    others = [t["edge_err_m"] for t in table if t is not good[0]]
    print("   ⇒ 定死 x%s z%s（其余组合残差最小 %.3f m ⇒ 分辨力 %.3f m）"
          % ("+" if sx > 0 else "−", "+" if sz > 0 else "−", min(others), min(others) - good[0]["edge_err_m"]))

    T = xform(sx, sz, lib, pk)
    d1 = apply_T(load_mesh(LIBS3D_D1), T)
    bh_m = lib["bh_mm"] / 1000.0
    print("\n搬运量   : Δ=(%.3f, %.3f) m  ×0.001  x%s z%s   (BH=%.3f m)"
          % (T[0, 3], T[2, 3], "+" if sx > 0 else "−", "+" if sz > 0 else "−", bh_m))

    fails, b = judge(d1, f0, bh_m)
    j1 = not any("J1" in f for f in fails)
    j2 = not any("J2" in f for f in fails)
    print("J1 埋深  : %.3f .. %.3f m（底面须 = −%.3f）%s" % (b["y"][0], b["y"][1], bh_m, "✓" if j1 else "✗"))
    print("J2 落位  : 平面 x %.3f..%.3f (%.2f m)  z %.3f..%.3f (%.2f m)  %s"
          % (b["x"][0], b["x"][1], b["x"][1] - b["x"][0], b["z"][0], b["z"][1], b["z"][1] - b["z"][0],
             "✓ 落在 floor0 内" if j2 else "✗"))

    ctrl = []
    for name, cm, expect, why in controls(d1, lib, pk, bh_m):
        cf, _ = judge(cm, f0, bh_m)
        got = sorted({f[:2] for f in cf})
        ok = expect in got
        ctrl.append({"name": name, "expect_judge": expect, "expect_why": why,
                     "fired_judges": got, "ok": bool(ok)})
        print("正对照   : %-20s 该红 %s  实红 %-10s %s"
              % (name, expect, ",".join(got) or "无", "✓" if ok else "✗ 没红到点子上"))
        if not ok:
            fails.append("对照「%s」该红 %s 而实红 %s ⇒ 那条判据无分辨力"
                         % (name, expect, ",".join(got) or "无"))

    okj = j1 and j2 and not fails
    print("判词     :", "PASS" if okj else "FAIL %s" % fails[:2])
    if not okj:
        return 1

    # ---- 并入 + 重读核 ----
    sc = trimesh.load(a.merge_into)
    names_before = sorted(sc.geometry.keys())
    sc.add_geometry(d1, node_name="B1", geom_name="B1")
    sc.export(a.merged_out)
    chk = trimesh.load(a.merged_out)
    gn = sorted(chk.geometry.keys())
    okn = ("B1" in gn) and set(names_before) <= set(gn)
    cb = plan_rect(node_mesh(a.merged_out, "B1"))
    okb = abs(cb["y"][0] - b["y"][0]) < 1e-3 and abs(cb["y"][1] - b["y"][1]) < 1e-3
    if not (okn and okb):
        print("!! 并入后重读核不过：节点 %s / 竖向 %s" % (okn, okb)); return 1
    print("并入     : 节点 %d ⇒ %d ; B1 竖向 %.3f..%.3f（重读文件核）✓"
          % (len(names_before), len(gn), cb["y"][0], cb["y"][1]))

    meta = {
        "schema": "cdut3d-basement/2",
        "node": "B1",
        "source": {"kind": "libs3d 交付件", "file": LIBS3D_D1,
                   "role": "原样搬入，cdut3d 不建几何",
                   "libs3d_chain": os.path.basename(LIBS3D_BUILD),
                   "libs3d_origin_mm": [lib["x_mm"], lib["y_mm"]]},
        "transform": {"axis_sign": {"x": sx, "z": sz}, "scale": 0.001,
                      "dx_m": round(float(T[0, 3]), 3), "dz_m": round(float(T[2, 3]), 3),
                      "how": "平移 = 两条链各自原点口径之差（不是拟合）；轴号由 F1↔floor0 四边对齐定死",
                      "cdut3d_origin_mm": [round(pk["ox"], 1), round(pk["oy"], 1)]},
        "axis_table": table,
        "elevation": {"lo_m": round(b["y"][0], 3), "hi_m": round(b["y"][1], 3),
                      "bbox_span_m": round(b["y"][1] - b["y"][0], 3),
                      "floor_m": round(b["y"][0], 3),
                      "bh_source": "libs3d build8.py 的 BH=%.0f mm（该链的假设，本包沿用）" % lib["bh_mm"],
                      # ★ 别把 bbox_span_m 当层高读：它俩在这件上差 0.6 m，而块里同时摆着 BH。
                      "bbox_span_is_not_floor_height":
                          "bbox_span_m=%.1f 是**这件的竖向跨度**（底 −4.2 是楼板底，顶 −0.6 是墙顶）；"
                          "libs3d 的 D1 件里**没有 ±0.000 那层地面楼板** ⇒ 它比层高 BH=%.1f 少了 0.6 m。"
                          "层高看 libs3d 的 BH，不看这个跨度。"
                          % (b["y"][1] - b["y"][0], lib["bh_mm"] / 1000.0)},
        "plan": {"x_m": [round(b["x"][0], 3), round(b["x"][1], 3)],
                 "z_m": [round(b["z"][0], 3), round(b["z"][1], 3)],
                 "w_m": round(b["x"][1] - b["x"][0], 3), "d_m": round(b["z"][1] - b["z"][0], 3)},
        "faces": int(len(d1.faces)),
        "reference": {"floor0_plan": {"x_m": [round(v, 3) for v in f0["x"]],
                                      "z_m": [round(v, 3) for v in f0["z"]]},
                      "note": "floor0 是 gym3d 那条链建的 F1；两条链不同源，因此留 %.1f m 容差" % ALIGN_TOL_M},
        "judge": {"J1_elevation": j1, "J2_inside_floor0": j2, "pass": bool(okj)},
        "controls": ctrl,
        "blind_spots": BLIND,
        "accepted": {
            "by": "用户裁定 2026-10-12 —— 「11 层，接受 4 米」",
            "n_floors_above_ground": 11,
            "storey_height_m": 4.0,
            "target_roof_m": 44.0,
            "evidence": "两条**互相独立**的读数，结论一致：① **层数**——图纸集 12 格逐格给房号层码，"
                        "地上 = 01..11、地下 = D1，一图一层、唯一、无缺号、无重号，这是**枚举**不是推断"
                        "（_scratch/dxf_floor_codes.py）；② **层高**——2024 倾斜摄影 DSM 实测裙房屋面 "
                        "27.92 m ÷ 7 层 = 3.99 m，塔楼屋面 47.57 m = 7×4.0 + 4×4.0 = 44.0 m 屋面，"
                        "余 3.6 m 是女儿墙+「成都理工大学」屋顶招牌（DSM 记的是**最高面**）。",
            "floor_count_visual_check": "外立面照独立数过一遍（_scratch/floor_columns.py）：逐**单列**取黄度"
                        "剖面数腰线，正脸各列 12~17 条 vs 天空列 2~4 条 ⇒ 尺子**有**分辨力、伪证器会动；"
                        "但正脸**每层有两条横线**（窗台/空调板）且上层透视压扁 ⇒ 这张照片**分不开 11 与 12**，"
                        "它印证「十来个」，定数仍以图纸集为准。",
            "does_not_move": "★ 这条**不改** meta/layering.json 的 floor_h_m=3.5 —— 那是**已交付 gym3d 网格自己**"
                             "的等分带高（39.4/11≈3.58），无损并集判据要求带贴着交付件切，属于「量这件几何」；"
                             "4.0 是**设计口径**，属于「这楼该多高」。两者不是一回事，别互相覆盖。"
                             "两条冻结基线**都不动**：libs3d/c006/build3.py（H=3600 mm）与 gym3d 的 c006 GLB。",
            "consequence": "⇒ 换链后新网格的**地上**目标高度 = 11 × 4.0 = **44.0 m**。"
                           "现两条链的地上各是 39.40 m（gym3d）与 39.72 m（libs3d），**都短约 4.3 m** —— "
                           "这是换链要修的那个量，其它（平面外框 129.3×84.0 m）两条链已经一致。",
        },
        "basement_levels": {
            "found_in_source": 1,
            "room_codes": ["6-C-D1-01", "6-C-D1-02"],
            "how_counted": "图纸集 12 格**全部占满**（99.7% 实体落在格内）；地下那格（R 列第 5 行）房号只有 D1；"
                           "全文件按类型扫文本 1137 条，`D2` **零命中**（_scratch/dxf_text_census.py、"
                           "_scratch/dxf_floor_codes.py）。",
            "unknown_because": "本判据只证「**源图里**地下只画了一层」，证不了「实物只有一层」——"
                               "若 B2 图另在某册、或本册就没出，此处**看不见缺失**。",
            "open": "★ 用户 2026-10-12 说「地下室还有一层」。**源图里没有第二层地下的图可依**："
                    "R5 那格只有 2 条房号、877 段墙、占地 87.5 × 56.3 m（比全楼 128.9 × 83.6 m 小，"
                    "像**局部**地下平面）。本仓**不臆造 B2 几何**。两条路：补 B2 图，或只按标高留带不建几何。",
        },
        "open_decisions": [
            "★ **那「约 4 m 的竖向差」是记法，不是几何**（2026-10-12 实测改正）："
            "gym3d 那 11 层是**地上**（层高 3.5 m，重读 GLB 实测 y 0.00→39.40 m）；"
            "libs3d 那 43.8 m = **地上 39.6 + 地下 4.2**（重读它自己的 GLB：f11 z 36000→39720 mm，"
            "fd1 z −4200→−600 mm）—— 含地下。**同口径比**：地上两条链是 39.40 vs 39.72，"
            "只差 **0.32 m**；平面外框两条链完全一致（129.3 × 84.0 m）。"
            "原文拿**地上**的 39.4 去比**含地下**的 43.8，那 4 m 就是地下室本身。",
            "⇒ 两条链的**地上**高度本来就是同一个数（差 0.32 m），所以「把 11 层换成 libs3d 的」"
            "不再是层高之争，剩下的是口径统一（3.5 vs 3.6 m）这件小事。"
            "但 2024 倾斜摄影 DSM 实测（基准 = 贴着楼的铺装面 464.66 m，四个独立估计跨度 0.69 m）"
            "量到 c006 **裙房屋面 27.9 m、塔楼屋面 47.5 m、台阶 19.6 m**（台阶与基准无关）"
            "—— ⇒ **3.5 与 3.6 都偏小**，7 层裙房 27.9 m 反推层高 ≈ 4.0 m。"
            "读数见 `_scratch/dsm_ground_c006.py` 与 `_scratch/dsm_roofs_c006.py` 的落盘。"
            "`meta/layering.json` 里的标高表只对 gym3d 那 11 层成立，"
            "B1 的 −4.2 m 用的是 libs3d 的口径 —— 读者别把两者当成同一把尺子量出来的。",
        ],
        "supersedes": {
            "what": "tools/build_basement.py（已归档到 _archive/pack-before-libs3d-D1/）",
            "why": "同层两处实现；自建那版墙足迹 198.8 m² vs libs3d 的 107.6 m²（多 85%），"
                   "层高取的是 3.5 m 的假设",
            "axis_bug": "自建那版把图纸 y 直接当模型 z（模型实际的 z = −本地 y）⇒ 整层镜像；"
                        "塔楼关于 z=0 对称，所以「主块中心 vs 塔楼中心」那条判据看不见它",
            "residual": "平面矩形逐边残差 0.000 m（两条链独立得出的原点口径一致）"},
    }
    if a.meta:
        os.makedirs(os.path.dirname(a.meta), exist_ok=True)
        data = json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8").replace(b"\r\n", b"\n")
        open(a.meta, "wb").write(data)
        print("写出     :", a.meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
