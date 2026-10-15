# -*- coding: utf-8 -*-
"""CAD 实体化第一步 —— 用 AutoCAD 的**真 headless 入口**批量闭合墙层多段线（§7.9.4 / §9.2 A2）。

本模块只负责**搬运**，不判对错（判对错是 `gates/J-07.9.4-01_wallclose.py` 的活）：
  ① 起一个干净工作目录（不动源件）
  ② **由 Python 按几何点名**要闭合的实体（首尾点距 ≤ TOL）
  ③ 落 `.scr`：一句一行、**括号同行闭合**、GBK 编码
  ④ `subprocess.run(绝对路径, cwd=工作目录, capture_output=True, timeout=…)`
  ⑤ **只认回执文件，不认退出码** —— 六态返回
  ⑥ 回读产出件，给出**同一把尺子**的前后闭合数

★★ 为什么「点名」放在 Python 而不是让 LISP 自己扫（第一版就是让 LISP 扫的，踩了两个坑）：
  · `_PEDIT` `_M` `_C` **真的能闭合**，但它是在**末点与首点之间加一段** ⇒ 盲扫会**新增几何**。
    实测 C006 墙层：58 条未闭合里，只有 12 条首尾本就重合，**23 条加出来 > 5 m、最长 46.4 m**
    ⇒ 一堵墙横拉过整栋楼。而本仓两条链**都会吃掉新增段**
    （`a1/generic_wall.py:59` 与 `libs3d/c006/wall_solid.py` 同款 `if e.closed … append([p[-1], p[0]])`）。
  · 多行 `while` 在 `.scr` 里**一次不进循环体**，而 rc 照样 0（静默失败）⇒ LISP 侧只写**一句话一行**。

★ 三条实测出来的入口纪律（都会静默失败，必须写进调用方式里）：
  1. **路径必须绝对**：`/i in.dxf /s job.scr` 相对路径 ⇒ rc=0、无产出物、无回执。
  2. **必须由 Python `subprocess` 启动**：同一份脚本从 git-bash 直接跑**挂死**（rc=124），
     从 Python 跑 3.3 s 就完。差别在启动环境，不在脚本。
  3. **stdout 是 UTF-16LE**，只当留档、不当判据。

用法（库）:
    import cad_close_walls as CC
    r = CC.close_walls(src_dxf, outdir, tol_mm=480.0, layer_prefix="4.2")
用法（命令行）: python tools/cad_close_walls.py <src.dxf> <outdir> [--tol 480] [--prefix 4.2]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time

import ezdxf

# ★ 六态沿用 `chain/chain.py` 的词汇（铁律 199 的加强版：崩了 / 挂死 / 静默成功 不许同形）
OK = "OK"
FAIL_RC = "FAIL_RC"
TIMEOUT = "TIMEOUT"
NO_ARTIFACT = "NO_ARTIFACT"
SKIP = "SKIP"

EXE = r"C:\Program Files\Autodesk\AutoCAD 2022\accoreconsole.exe"
TIMEOUT_S = 300

# ★ 默认容差 = 2 × 墙厚（C006 的 `4.2墙体` 名义墙厚 240）—— 见 `gauge()` 打印的台阶：
#   实测 C006 墙层的「首尾点距」只有三档：**0.0 mm ×12 条**、**300.0 mm ×1 条**、**≥14 499.5 mm ×4 条**。
#   中间那条 14.5 m 与 300 mm 之间差 48 倍 ⇒ TOL 落在 [300, 14499] 内取值，闭合条数**都是 13**。
#   ⇒ 这个数是**量出来的台阶**，不是拍的；判据会把整条台阶印出来。
DEFAULT_TOL_MM = 480.0


# ----------------------------------------------------------------- 尺子（判据与驱动共用一把）
def wall_polys(path, prefix):
    """墙层多段线 → [(handle, pts, closed_flag)]。**只按层名前缀认**，不写死全名。"""
    doc = ezdxf.readfile(path)
    out = []
    for e in doc.modelspace():
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer.startswith(prefix):
            out.append((str(e.dxf.handle), [(p[0], p[1]) for p in e.get_points()], bool(e.closed)))
    return out


def gap_mm(pts):
    """闭合会「新加的那一段」有多长 = 末点到首点的距离。"""
    return math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])


def pick_handles(ps, tol_mm):
    """该闭合谁：**未置闭合标志**、**顶点数 > 2**（2 顶点闭合是退化的反向重复）、**缺口 ≤ TOL**。

    ★ `len(pts) > 2` 这条不是可有可无：C006 有 **41 条 2 顶点未闭合多段线**（首尾距 240 mm~38.9 m），
      它们本是**单段墙线**，闭合只会把同一条线原样反向再记一遍 ⇒ 对链是纯噪声。
    """
    return [h for (h, pts, cl) in ps if not cl and len(pts) > 2 and gap_mm(pts) <= tol_mm]


def gauge(path, prefix):
    """★ 同一把尺子。两个「闭合」**分开记名**（铁律 174：同名的两个量必须死掉一个）：
       `flag` = DXF 的 closed 标志（AutoCAD 的语义，权威）
       `geom` = 首尾点重合 ≤ 1 µm（**几何**上确实圈上了）
    C006 墙层实测 flag=77 / geom=12 —— 两个数差 6 倍 ⇒ 混用会把「标志没置」与「真开口」搞混。
    """
    ps = wall_polys(path, prefix)
    return {"n": len(ps),
            "flag": sum(1 for _, _, c in ps if c),
            "geom": sum(1 for _, p, _ in ps if len(p) > 2 and gap_mm(p) < 1e-6)}


def gap_ladder(ps, tols):
    """容差台阶：每个 TOL 点名几条 —— 让「TOL 取多少」这件事**可见**，不是拍的。"""
    gaps = sorted(gap_mm(p) for _, p, c in ps if not c and len(p) > 2)
    return {("%g" % t): {"n": sum(1 for g in gaps if g <= t),
                         "gaps": [round(g, 1) for g in gaps if g <= t]} for t in tols}


# ----------------------------------------------------------------- 搬运
def write_scr(path, lines):
    """★ 一条一行、括号同行闭合；★ GBK（AutoCAD 2022 按系统代码页读 .scr，不是 UTF-8）。"""
    with open(path, "wb") as f:
        f.write(("\n".join(lines) + "\n").encode("gbk", "replace"))


def close_walls(src, outdir, tol_mm=DEFAULT_TOL_MM, prefix="4.2", exe=EXE, timeout=TIMEOUT_S):
    """跑一步。返回 dict（见模块 docstring 的六态）。

    ★ 好坏**各在自己目录**里跑由调用方负责（chain.py 首轮踩过的假绿：残留产物把坏输入顶成 OK）。
    """
    if not os.path.isfile(exe):
        return {"state": SKIP, "detail": "accoreconsole 不在盘上: %s" % exe}
    if not os.path.isfile(src):
        return {"state": SKIP, "detail": "源 DXF 不在盘上: %s" % src}
    # ★ 目录一律转绝对：cwd 会被设成 outdir，相对路径传进 /i /s 必然找不着（实测 rc=76 或静默 rc=0）
    outdir = os.path.abspath(outdir)
    os.makedirs(outdir, exist_ok=True)
    inp = os.path.join(outdir, "in.dxf")
    if os.path.abspath(src) != os.path.abspath(inp):
        shutil.copy2(src, inp)

    # ★ 本侧尺子**读不动源件**时不许把整步吞掉（铁律 199：「没量到」≠「失败」）：
    #   仍然把 accoreconsole 跑起来，让**入口自己的判词**成立；本侧读数记成 None，由判据去分开报。
    gauge_ok, before, hs = True, None, []
    try:
        ps = wall_polys(inp, prefix)
        hs = pick_handles(ps, tol_mm)
        before = gauge(inp, prefix)
    except Exception as e:
        gauge_ok = False
        before = {"err": "%s: %s" % (type(e).__name__, str(e)[:80])}

    lines = ['(setq nc 0)']
    for h in hs:
        lines.append('(command "_.PEDIT" (handent "%s") "_C" "")' % h)
        lines.append('(setq nc (1+ nc))')
    lines += ['(setq f (open "receipt.txt" "w"))',
              '(write-line (strcat "NC=" (itoa nc)) f)',
              '(write-line (strcat "NALL=" (itoa (sslength (ssget "X" (list (cons 0 "LWPOLYLINE") '
              '(cons 8 "%s*")))))) f)' % prefix,
              '(close f)',
              '(command "_.DXFOUT" (strcat (getvar "DWGPREFIX") "out.dxf") "16")']
    scr = os.path.join(outdir, "job.scr")
    write_scr(scr, lines)
    with open(os.path.join(outdir, "picked.txt"), "w", encoding="utf-8") as f:
        f.write("TOL=%g  点名 %d 条\n%s\n" % (tol_mm, len(hs), " ".join(hs)))

    # ★ 绝对路径 + Python 启动（见模块 docstring 的三条入口纪律）
    argv = [exe, "/i", inp, "/s", scr]
    t0 = time.time()
    try:
        p = subprocess.run(argv, cwd=outdir, capture_output=True, timeout=timeout)
        rc, so = p.returncode, (p.stdout or b"")
    except subprocess.TimeoutExpired:
        return {"state": TIMEOUT, "rc": None, "secs": round(time.time() - t0, 1),
                "before": before, "picked": len(hs),
                "detail": "超时 %ds 被终止（★ 与 rc≠0 分开报：挂死 ≠ 崩了）" % timeout}
    secs = round(time.time() - t0, 1)
    with open(os.path.join(outdir, "stdout.bin"), "wb") as f:
        f.write(so)                                  # UTF-16LE，只留档

    rcpt = os.path.join(outdir, "receipt.txt")
    odxf = os.path.join(outdir, "out.dxf")
    if rc != 0:
        return {"state": FAIL_RC, "rc": rc, "secs": secs, "before": before, "picked": len(hs),
                "detail": "rc=%d" % rc}
    if not os.path.exists(rcpt) or not os.path.exists(odxf):
        return {"state": NO_ARTIFACT, "rc": rc, "secs": secs, "before": before, "picked": len(hs),
                "detail": "rc=0 但没有回执/产出件（★ 静默成功，最危险的一类）"}
    kv = {}
    for ln in open(rcpt, encoding="utf-8", errors="replace").read().splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            kv[k.strip()] = v.strip()
    try:
        after = gauge(odxf, prefix)
    except Exception as e:
        after = {"err": "%s: %s" % (type(e).__name__, str(e)[:80])}
    return {"state": OK, "rc": rc, "secs": secs, "before": before, "after": after,
            "gauge_ok": gauge_ok,
            "picked": len(hs), "receipt": kv, "out_dxf": odxf, "in_dxf": inp,
            "receipt_delta": int(kv.get("NC", "-1")) if kv.get("NC", "-1").lstrip("-").isdigit() else None}


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("outdir")
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL_MM)
    ap.add_argument("--prefix", default="4.2")
    a = ap.parse_args()
    ps = wall_polys(a.src, a.prefix)
    print("容差台阶（未闭合且顶点>2 的缺口分布）:")
    for t, v in gap_ladder(ps, (0, 60, 240, 480, 1000, 2000, 5000, 10000, 50000)).items():
        print("  TOL=%-8s ⇒ 点名 %2d 条   %s" % (t, v["n"], v["gaps"][:6]))
    r = close_walls(a.src, a.outdir, a.tol, a.prefix)
    print("\nstate=%(state)s rc=%(rc)s %(secs)ss  点名 %(picked)s 条" % {"state": r["state"], "rc": r.get("rc"),
          "secs": r.get("secs"), "picked": r.get("picked")})
    if "before" in r:
        print("  闭合前:", r["before"], "→ 闭合后:", r.get("after", "没量到"))
    if r.get("receipt"):
        print("  回执:", r["receipt"])
    if r["state"] != OK:
        print("  detail:", r.get("detail"))
    return 0 if r["state"] == OK else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
