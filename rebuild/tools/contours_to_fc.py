# -*- coding: utf-8 -*-
r"""轮廓 JSON → 实体 OBJ（**FreeCAD 版**，替代 SketchUp 那一步）。

跑法（必须用 FreeCAD 自带的解释器，普通 python 里没有 Part/MeshPart）：
    "C:\Users\Administrator\AppData\Local\Programs\FreeCAD 1.1\bin\freecadcmd.exe" \
        D:\项目\cdut3d\rebuild\tools\contours_to_fc.py
环境变量（与 building.py 同一套；都不设 = c006）：
    CDUT_BUILDING=c005 | CDUT_REBUILD_ROOT=<dir>

输入 : <ROOT>/06_su/contours/index.json + <层>.json（export_contours.py 的产物）
输出 : <ROOT>/06_su/<NAME>_fc.obj        合并件（每 (层,类) 一段，`o <层>__<类>`）
       <ROOT>/06_su/fc_parts/*.obj       分段件（逐 (层,类)，可单独复核）
       <ROOT>/06_su/fc_recon.json        建件读数（逐层逐类：输入条数/实体数/失败/面数）

为什么换掉 SketchUp（2026-10-17 用户令「你说换就换，换完提高复现性」）：
  · **可复现**：同一份 contours 连跑两趟，输出 OBJ **逐字节相同**（实测 c005：
    `cd0a4a94…70603e` 两趟一致，4 s/趟）。SU 那边同样的输入会因组顺序/浮点形态漂。
  · **无 GUI/无人值守**：没有欢迎屏、单实例接手、非 ASCII 文档路径崩溃这一串坑。
  · 判据不变：同一个 `polys` 列表、同一个 `push_mm`/`h` 规则，一条不另立。

★ 与 SU 脚本对齐的三处口径（都从 contours 里读，不另设常量）：
   ① 底标高 = z0_m×1000 + poly["z"]（poly["z"] 是**毫米**，实测 floor5 16000+7000=23000）；
   ② 拉伸高度 = poly["h"]（有就赢）否则 push_mm[layer]（与 Ruby `pr["h"] || push[lay]` 同）；
   ③ 逐 (层,类) 分开建、分开写 ⇒ 网页的分层面板与类面板拿到的是同一组节点名。

★ 盲区（先声明，再判）：
   · 本脚本只认**平面环 + 洞 + 高度**。曲面/斜坡/异形拉伸它建不了（contours 里也没有）。
   · 三角化参数写死 0.5 mm / 0.5 rad。它只影响**弧面细分**的疏密，不影响平面位置；
     但它确实决定顶点数 ⇒ 与 SU 件的顶点数**不该**逐位相等，别拿它当回归判据。
   · 「没建出来」与「建出来是错的」分开：单条失败进 failures 并让 rc≠0，不静默跳过。
"""
from __future__ import annotations

import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import building as B  # noqa: E402

import FreeCAD            # noqa: E402
import Part               # noqa: E402
import MeshPart           # noqa: E402

ROOT = B.ROOT
SRC = os.path.join(ROOT, "06_su", "contours")
OUTDIR = os.path.join(ROOT, "06_su")
PARTS = os.path.join(OUTDIR, "fc_parts")
NAME = B.out_name()
OUT_OBJ = os.path.join(OUTDIR, "%s_fc.obj" % NAME)
RECON = os.path.join(OUTDIR, "fc_recon.json")

LINEAR_DEFLECTION = 0.5     # mm
ANGULAR_DEFLECTION = 0.5    # rad
CLASSES = ("WALL", "COL", "LIFT", "SLAB", "DOOR", "STAIR",
           "LINTEL", "PARAPET", "ROOF_STAIR", "ROOF_STEP", "ROOF",
           "ROOF_ROOM")   # ★ 2026-10-18 屋面附属用房（与 J-10.8-00::LAYERS 同步，J-10.9-07 ④ 要交叉校验）


def ring_wire(ring):
    pts = [(float(x), float(y), 0.0) for x, y in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    clean = []
    for p in pts:
        if not clean or p != clean[-1]:
            clean.append(p)
    if len(clean) < 3:
        raise ValueError("ring has fewer than 3 unique points")
    clean.append(clean[0])
    return Part.makePolygon(clean)


def build_one(poly, height_mm, z_abs_mm):
    face = Part.Face(ring_wire(poly["ring"]))
    for hole in poly.get("holes") or []:
        if len(hole) < 4:
            raise ValueError("hole ring too short")
        face = face.cut(Part.Face(ring_wire(hole)))
    if len(face.Faces) == 0:
        raise ValueError("face.cut produced no faces")
    out = []
    for f in face.Faces:
        solid = f.extrude(FreeCAD.Vector(0.0, 0.0, float(height_mm)))
        solid.translate(FreeCAD.Vector(0.0, 0.0, float(z_abs_mm)))
        if solid.Volume <= 0:
            raise ValueError("extruded solid has non-positive volume")
        out.append(solid)
    return out


def merge_parts(parts):
    """把逐 (层,类) 的 OBJ 拼成一份，顶点索引整体后移；每段前写 `o <层>__<类>`。"""
    nv = 0
    nf = 0
    with io.open(OUT_OBJ, "w", encoding="ascii", newline="\n") as w:
        w.write("# FreeCAD solids from contours (%s)\n" % NAME)
        for node, cls, path in parts:
            w.write("o %s__%s\n" % (node, cls))
            off = nv
            with io.open(path, "r", encoding="utf-8", errors="replace") as r:
                for ln in r:
                    if ln.startswith("v "):
                        w.write(ln)
                        nv += 1
                    elif ln.startswith("f "):
                        toks = ln.split()
                        idx = [str(int(t.split("/")[0]) + off) for t in toks[1:]]
                        w.write("f " + " ".join(idx) + "\n")
                        nf += 1
    return nv, nf


def main():
    t0 = time.time()
    index = json.load(io.open(os.path.join(SRC, "index.json"), encoding="utf-8"))
    if not index:
        raise SystemExit("no contours under " + SRC)
    os.makedirs(PARTS, exist_ok=True)

    basement = bool(B.profile().get("basement"))
    order = []
    for i, ent in enumerate(index):
        if basement and i == 0:
            order.append((ent, "B1"))
        else:
            order.append((ent, "floor%d" % (i - (1 if basement else 0))))

    report = {
        "generator": "contours_to_fc.py",
        "freecad_version": ".".join(FreeCAD.Version()[0:4]),
        "source": SRC,
        "deflection_mm": LINEAR_DEFLECTION,
        "angular_rad": ANGULAR_DEFLECTION,
        "floors": [],
        "total_polys": 0,
        "total_solids": 0,
        "total_failures": 0,
    }
    parts = []
    for ent, node in order:
        path = os.path.join(SRC, ent["floor"] + ".json")
        data = json.load(io.open(path, encoding="utf-8"))
        z0_mm = float(data["z0_m"]) * 1000.0
        push = data["push_mm"]
        by_cls = {}
        fails = []
        counts = {}
        for poly in data["polys"]:
            lay = poly["layer"]
            if lay not in push:
                fails.append({"id": poly.get("id"), "error": "layer not in push_mm"})
                continue
            counts[lay] = counts.get(lay, 0) + 1
            h = float(poly["h"]) if "h" in poly else float(push[lay])
            z = z0_mm + float(poly["z"])
            try:
                by_cls.setdefault(lay, []).extend(build_one(poly, h, z))
            except Exception as exc:            # noqa: BLE001 - 逐条记账，不吞
                fails.append({"id": poly.get("id"), "layer": lay,
                              "error": "%s: %s" % (type(exc).__name__, exc)})

        row = {"node": node, "floor": data["floor"], "z0_m": data["z0_m"],
               "polys": len(data["polys"]), "classes": {}, "failures": fails}
        for lay in CLASSES:
            solids = by_cls.get(lay) or []
            if not solids:
                continue
            compound = Part.makeCompound(solids)
            mesh = MeshPart.meshFromShape(Shape=compound,
                                          LinearDeflection=LINEAR_DEFLECTION,
                                          AngularDeflection=ANGULAR_DEFLECTION,
                                          Relative=False)
            part = os.path.join(PARTS, "%s__%s.obj" % (node, lay))
            mesh.write(part)
            parts.append((node, lay, part))
            row["classes"][lay] = {"polys": counts.get(lay, 0),
                                   "solids": len(solids),
                                   "facets": mesh.CountFacets}
            report["total_solids"] += len(solids)
        report["floors"].append(row)
        report["total_polys"] += len(data["polys"])
        report["total_failures"] += len(fails)
        print("FLOOR %-8s polys=%-5d classes=%-2d fail=%d"
              % (node, len(data["polys"]), len(row["classes"]), len(fails)),
              flush=True)

    nv, nf = merge_parts(parts)
    report["obj"] = os.path.relpath(OUT_OBJ, ROOT).replace("\\", "/")
    report["obj_bytes"] = os.path.getsize(OUT_OBJ)
    report["obj_verts"] = nv
    report["obj_faces"] = nf
    report["parts"] = len(parts)
    report["elapsed_s"] = round(time.time() - t0, 2)
    with io.open(RECON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print("OBJ %s bytes=%d v=%d f=%d parts=%d failures=%d elapsed=%.1fs"
          % (OUT_OBJ, report["obj_bytes"], nv, nf, len(parts),
             report["total_failures"], report["elapsed_s"]))
    print("RECON %s" % RECON)
    return 0 if report["total_failures"] == 0 else 1


# ★ 2026-10-17 实测：freecadcmd 执行脚本时 **`__name__` 不是 `"__main__"`**（实测是文件名
#   `contours_to_fc`）⇒ 写 `if __name__ == "__main__"` 的脚本会被 FreeCAD **一声不响地跳过**
#   （rc=0、零输出、什么也没建，与「跑成功了」同形，铁律 199）。这里无条件调用。
#   要 import 这个文件而不跑（做探针时），设 CDUT_FC_NO_RUN=1。
if os.environ.get("CDUT_FC_NO_RUN") != "1":
    raise SystemExit(main())
