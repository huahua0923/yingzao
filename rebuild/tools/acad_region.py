# -*- coding: utf-8 -*-
"""让 **AutoCAD 自己**把一层平面里的闭合区域全描出来（墙体带 / 房间 / 天井），
  我的代码只做一件事：拿回 AutoCAD 描出的环，量 `面积 / 周长` 判断**厚薄**。

★ 为什么这样做（依据 memory `cdut3d-geometry-from-tools-code-only-verifies`）：
  几何由工具出。上一轮失败的正是「自己配对双线、自己闭运算」。
  这里一行配对都不写 —— 闭合边界由 AutoCAD 的 HATCH 边界引擎找，
  我拿到的每条环，顶点就是 AutoCAD 画出来的顶点。

★ 判厚薄的判据（唯一一处「我的算法」，且只输出一个比较结果）：
  环的**等截面宽度** `w = 2*A/P`（A=面积，P=周长）。墙带是长条：A≈t·L、P≈2L ⇒ w≈t≈240 mm；
  房间是方块：w≈边长/2≈数米。**两档差一个量级**，用 w < 600 mm 判墙。
  这条判据对「多段墙连成一张大网」也成立（网仍是细长的，w 不涨）。

★ 印出 w 的直方图 —— 若两峰分不开，说明判据没有分辨力，当场看得见。

输出：`rebuild/02_cad_geom/<层名>.json`
  { "name":..., "seeds":n, "loops":[{ "w":.., "A":.., "P":.., "kind":"wall|open",
      "pts":[[x,y,bulge],...], "closed":true }, ...] }
用法：
  python rebuild/tools/acad_region.py --floor 8层
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import subprocess
import sys

import ezdxf
from ezdxf.addons import Importer

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "01_cad", "raw")
OUT = os.path.join(ROOT, "02_cad_geom")
WORK = os.path.join(ROOT, "_work")

ACAD = r"C:\Program Files\Autodesk\AutoCAD 2022\acad.exe"
WALL_LAYER = "4.2墙体"
GEOM = ("LINE", "LWPOLYLINE", "ARC", "CIRCLE")

WALL_MAX = 600.0          # 等截面宽度低于此 ⇒ 判墙（mm）
SEED_OFF = 60.0           # 从墙线中点往两侧偏这么多打种子（mm）
SEED_GRID = 250.0         # 种子去重的栅格（mm）
HPGAPTOL = 300.0          # HATCH 补缝容差（mm）；大了会把门洞跨过去


# ---------------------------------------------------------------- 三条入口纪律
def write_scr(path, lines):
    """括号闸 + GBK 写盘（照抄 `_scratch/acad.py`，一行不省）。"""
    d = 0
    for i, ln in enumerate(lines, 1):
        code = ln.split(";")[0]
        d += code.count("(") - code.count(")")
        if d < 0:
            raise AssertionError("第 %d 行后括号为负：%s" % (i, ln))
    if d != 0:
        raise AssertionError("末行括号深度 %d ≠ 0 —— .scr 会被读器吃掉" % d)
    with open(path, "wb") as f:
        f.write(("\n".join(lines) + "\n").encode("gbk", "replace"))


# ---------------------------------------------------------------- 搬墙线 + 打种子
def load_wall(path):
    doc = ezdxf.readfile(path)
    lines = []
    n_pl = 0
    for e in doc.modelspace():
        if e.dxf.layer != WALL_LAYER:
            continue
        t = e.dxftype()
        if t not in GEOM:
            continue
        if t == "LWPOLYLINE":
            n_pl += 1
        if t in ("LINE", "ARC", "CIRCLE"):
            a = e.dxf.start if t == "LINE" else e.dxf.center
            b = e.dxf.end if t == "LINE" else None
            if t == "LINE":
                lines.append(((a.x, a.y), (b.x, b.y)))
            elif t == "ARC":
                r = e.dxf.radius
                m = e.dxf.start_angle * math.pi / 180
                n = e.dxf.end_angle * math.pi / 180
                lines.append(((a.x + r * math.cos(m), a.y + r * math.sin(m)),
                              (a.x + r * math.cos(n), a.y + r * math.sin(n))))
            elif t == "CIRCLE":
                c = (a.x, a.y)
                lines.append((c, (c[0] + e.dxf.radius, c[1])))
        elif t == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            for k in range(len(pts) - 1):
                lines.append((pts[k], pts[k + 1]))
    return lines, n_pl


def seeds_from(lines):
    """每条线取中点、往法向两侧各偏 SEED_OFF ⇒ 至少一颗落在墙带里。栅格去重。"""
    seen = set()
    out = []
    for (ax, ay), (bx, by) in lines:
        mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        if L < 1.0:
            continue
        nx, ny = -dy / L, dx / L
        for s in (+SEED_OFF, -SEED_OFF):
            x, y = mx + s * nx, my + s * ny
            k = (int(round(x / SEED_GRID)), int(round(y / SEED_GRID)))
            if k in seen:
                continue
            seen.add(k)
            out.append((x, y))
    return out


def transport(floor, work, lines):
    """把墙层几何搬进工作 DXF（Importer，连块定义一起）。"""
    src = ezdxf.readfile(os.path.join(RAW, floor + ".dxf"))
    out = ezdxf.new("R2013", setup=True)
    imp = Importer(src, out)
    n = 0
    for e in src.modelspace():
        if e.dxf.layer == WALL_LAYER and e.dxftype() in GEOM:
            imp.import_entity(e)
            n += 1
    imp.finalize()
    os.makedirs(work, exist_ok=True)
    p = os.path.join(work, "w.dxf")
    out.saveas(p)
    return p, n


# ---------------------------------------------------------------- 驱动 AutoCAD
def drive(work, seeds):
    # 种子以 lisp 常量表注入（每颗一行太长会超行宽，折成多行 —— 括号闸会校验）
    defs = ['(setq SEEDS (list'] + [
        '  (list %.2f %.2f)' % (x, y) for x, y in seeds] + [']))']

    L = ['(setvar "FILEDIA" 0)', '(setvar "CMDDIA" 0)',
         '(setvar "CLAYER" "0")', '(setvar "OSMODE" 0)',
         '(vl-load-com)',
         '(setq f (open "s.txt" "w"))',
         '(setvar "HPNAME" "SOLID")', '(setvar "HPSCALE" 1.0)',
         '(setvar "HPGAPTOL" %.1f)' % HPGAPTOL,
         '(setvar "HPISLANDDETECTION" 0)',
         '(setvar "HPLAYER" "0")',
         '(command "_.ZOOM" "_E")',
         '(setq nfail 0 nmade 0 k 0)'] + defs + [
         # 逐点：造一条 hatch → 立刻描它的边界 → 立刻删掉它（任何时刻最多 1 条 hatch）
         '(while (< k (length SEEDS))',
         '  (setq p (nth k SEEDS))',
         '  (vl-catch-all-apply (function (lambda () (command "_.-HATCH" p ""))))',
         '  (setq hs (ssget "_X" (list (cons 0 "HATCH"))))',
         '  (if hs',
         '    (progn',
         '      (setq nmade (1+ nmade))',
         '      (vl-catch-all-apply (function (lambda ()',
         '        (command "_.HATCHGENERATEBOUNDARY" (ssname hs 0) ""))))',
         '      (command "_.ERASE" hs ""))',
         '    (setq nfail (1+ nfail)))',
         '  (setq k (1+ k)))',
         '(write-line (strcat "seeds=" (itoa (length SEEDS)) " made=" (itoa nmade)',
         '  " fail=" (itoa nfail)) f)',
         '(setq pl (ssget "_X" (list (cons 0 "LWPOLYLINE"))))',
         '(write-line (strcat "plines=" (itoa (if pl (sslength pl) 0))) f)',
         '(write-line "DONE" f)', '(close f)',
         '(command "_.DXFOUT" (strcat (getvar "DWGPREFIX") "regions" ".dxf") "16")',
         '(command "_.QUIT" "_Y")']

    scr = os.path.join(work, "s.scr")
    write_scr(scr, L)
    try:
        subprocess.run([ACAD, "/i", os.path.join(work, "w.dxf"), "/b", scr],
                       cwd=work, capture_output=True, timeout=3600)
        rc = 0
    except subprocess.TimeoutExpired:
        rc = 124
    s = os.path.join(work, "s.txt")
    return rc, (open(s, encoding="utf-8", errors="replace").read()
                if os.path.exists(s) else "")


# ---------------------------------------------------------------- 读回 + 量
def poly_metrics(pts):
    """闭合多段线（含 bulge）的面积与周长。带符号面积取绝对值（AutoCAD 口径）。"""
    A = 0.0
    P = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0, b0 = pts[i]
        x1, y1, _ = pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        chord = math.hypot(dx, dy)
        P += chord
        A += x0 * y1 - x1 * y0
        if abs(b0) > 1e-12:
            theta = 4.0 * math.atan(b0)          # 弧转角
            if abs(theta) > 1e-9:
                r = chord / (2.0 * math.sin(abs(theta) / 2.0))
                P += abs(r * theta) - chord
    return abs(A) / 2.0, P


def read_loops(path):
    doc = ezdxf.readfile(path)
    loops = []
    for e in doc.modelspace():
        if e.dxftype() != "LWPOLYLINE":
            continue
        raw = list(e.get_points("xyseb"))
        pts = [[float(p[0]), float(p[1]), float(p[4])] for p in raw]
        if len(pts) < 3:
            continue
        A, P = poly_metrics(pts)
        if P < 1e-9:
            continue
        loops.append({"A": A, "P": P, "w": 2.0 * A / P, "pts": pts})
    return loops


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--floor", required=True)
    ap.add_argument("--wall-max", type=float, default=WALL_MAX)
    a = ap.parse_args()

    work = os.path.join(WORK, a.floor)
    os.makedirs(work, exist_ok=True)
    lines, n_pl = load_wall(os.path.join(RAW, a.floor + ".dxf"))
    print("墙层线段 %d 条（其中 LWPOLYLINE %d 条）" % (len(lines), n_pl))
    seeds = seeds_from(lines)
    print("种子 %d 颗" % len(seeds))

    p, n = transport(a.floor, work, lines)
    print("搬进工作 DXF：%d 条 → %s" % (n, p))

    rc, receipt = drive(work, seeds)
    print("acad rc=%d" % rc)
    print("---- 回执 ----")
    print(receipt.strip() or "（空 —— 说明脚本没跑到底）")

    reg = os.path.join(work, "regions.dxf")
    if not os.path.exists(reg):
        print("★ 没量到：没有 regions.dxf")
        return 4
    loops = read_loops(reg)
    print("取回闭合环 %d 条" % len(loops))

    # 厚薄判据 + 直方图（分辨力当场可见）
    hist = collections.Counter()
    walls = 0
    for lp in loops:
        w = lp["w"]
        b = int(w // 100) * 100
        hist[min(b, 5000)] += 1
        lp["kind"] = "wall" if w < a.wall_max else "open"
        lp["w"] = round(w, 1)
        lp["A"] = round(lp["A"], 1)
        lp["P"] = round(lp["P"], 1)
        if lp["kind"] == "wall":
            walls += 1
    print("等截面宽度 w=2A/P 直方图（100 mm 一档，末档>=5000）:")
    for k in sorted(hist):
        print("  %5s..%5s : %s" % (k, k + 100, "#" * min(hist[k], 80)))

    A_wall = sum(lp["A"] for lp in loops if lp["kind"] == "wall")
    A_open = sum(lp["A"] for lp in loops if lp["kind"] == "open")
    print("判墙 %d 条（面积 %.3f m²）/ 判空 %d 条（%.3f m²）"
          % (walls, A_wall / 1e6, len(loops) - walls, A_open / 1e6))
    if walls == 0:
        print("★ 没量到：一条墙都没判出来 —— 判据或种子有问题，不许当结论")
        return 4

    os.makedirs(OUT, exist_ok=True)
    meta = {"name": a.floor, "seeds": len(seeds), "loops": len(loops),
            "walls": walls, "wall_max": a.wall_max,
            "area_wall_m2": round(A_wall / 1e6, 3),
            "area_open_m2": round(A_open / 1e6, 3),
            "data": loops}
    with open(os.path.join(OUT, a.floor + ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("写 %s.json" % os.path.join(OUT, a.floor))
    return 0


if __name__ == "__main__":
    sys.exit(main())
