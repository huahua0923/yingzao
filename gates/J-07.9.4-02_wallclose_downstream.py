# -*- coding: utf-8 -*-
"""判据 J-07.9.4-02：闭合这一步**接进链之后**，下游拿到的墙线**确实变了、且不是坏的**。

对应方案 §7.10「CAD 命令行实体化」行的**新出口门**：
  「把这一步**接进链**（作 stage 2 的一个步骤，产出 `out.dxf` 供下游消费），
    并证明**下游拿到的墙线确实变了且不是坏的**」。

★ 与 `J-07.9.4-01` 的分工（两条判据不许互相盖章）：
  · `-01` 量的是 **DXF 本身**：无损伤、有界、可重复（`wall_polys` / `gap_mm` / `cmp_polys`）。
  · `-02` 量的是 **链里的下游**：`a1/generic_wall.py` 的 `load_walls_and_cols()` + `wire()`。
    它**不重复** `-01` 的逐点比对 —— 那已经判过了。它问的是另一个问题：
    「那条新增段**走没走到下游**？到了之后**长出了什么**？」

★★ **本节真正的发现（也是这条判据存在的理由）**：
  闭合在 C006 上**确实被下游吃掉了**（墙线段数 +13 = 点名条数），但它
  **一块新墙身都没配出来**（`wire()` 的四边形数：定向 +0、盲扫也 +0）——
  新增段全部落进 `wire()` 第三条通路 **`residual`**（未配对的线，下游 buffer 成墙足迹）。
  于是「闭合的好坏」在下游就等价于**「残段涨了多少毫米」**：
    · 定向闭合（13 条缺口 ≤480 mm）⇒ 残段 **+300.0 mm**
    · 盲扫闭合（58 条全闭合）    ⇒ 残段 **+123 621.6 mm**（412×，几十堵墙横穿楼）
  ⇒ 这条判据的 B 条就架在这个数上，正对照①拿盲扫去撞它，**必须红**。

四件套（§10.0.1）：
  ① 量交付件本身 —— 量的是**下游函数的返回对象**（`segs / quads / residual`），不是日志、不是 rc
  ② 量具写明     —— `a1/generic_wall.py` 的 `load_walls_and_cols()` / `wire()`（链自己在用的那两个）
  ③ 盲区声明     —— 见下
  ④ 正对照必配   —— **四条**（①②③④，见下）

★★ **两口径（2026-10-12 补：链补上「剔踏步」之后才暴露）**：
  链的 `load_walls_and_cols()` 除「闭合段」外还做**第二道变换** —— 剔踏步
  （`a1/treads.py` → 冻结基线 `libs3d/c006/treadlib.py`）。实测：**过一手 AutoCAD 之后**，
  同 193 组踏步里**有 4 组的成员从 11 条变 12 条**（多剔 4 条），组数不变 ——
  病根是**精确同偏移的重线**在 1e-9 级浮点抖动下被并/拆（见盲区⑥）。
  ⇒ 本条把**两个口径**分开量，否则「闭合的功劳」会被第二道变换的抖动冒充：
    · **纯墙口径** = `load_walls_and_cols(dxf, drop_treads=False)`（只有闭合这一道变换）
    · **链口径**   = `load_walls_and_cols(dxf)`（链真正交付的那一个）
  A/B/C/D 全落**纯墙口径**（正对照③实测那里地板 = **0** ⇒ 可以精确等于、容差保持 nm 级）；
  链口径**照报并与纯墙口径对账**（A2），它的地板由正对照③当场量出（实测 −4 条 / −1917.653718 mm）。
  ★ 为什么不「链口径减地板」：地板 1917.65 mm **比信号（缺口合计 300 mm）还大**，
  相减之后 D 的容差会涨到 1917.65 mm（= 期望值的 6 倍）⇒ **D 当场失去分辨力**（铁律 137）。

★ 判据（全部为真才算过）：
  A. **纯墙口径：闭合真的走到下游**：`Δn_segs` == 点名条数，且 > 0
     ⇒ 那条新增段不是躺在 DXF 里没人读，它**确实走进了墙输入**。
  A2. **两口径对账（主语不许被悄悄换掉）**：`链口径 Δn_segs` == `纯墙口径 Δn_segs` − `Δ剔`，
     其中 `Δ剔` = 链口径比纯墙口径**多剔**的条数（前、后各量一次再作差）
     ⇒ 防「把剔踏步的抖动算成闭合的功劳」（铁律 196）。
  B. ★ **不是坏的（有界）**：纯墙口径 `0 ≤ Δ残段总长 ≤ 点名条数 × TOL`
     ⇒ 这一臂是正对照①唯一能撞红的地方（**412 倍**）。
  C. **增量逐条可指名**：**每一条**被点名多段线的**缺口段**（末点→首点）都必须能在
     闭合后的**纯墙口径**残段集合里按几何**找得到**（≤ `COORD_TOL_MM`）
     ⇒ 排除「总长碰巧相等、但多出来的是别的东西」。
  D. **两个独立来源同数**：期望缺口和（由**源 DXF 直接枚举**算出、**不经 AutoCAD**）
     与实测 `Δ残段总长` 吻合，容差 `max(噪声地板, 0.1% × 期望)`；
     **噪声地板由正对照③当场量出**（在 D 之前就量），不是拍的（铁律 103）。
  E. 有界：`state == OK`、耗时 < 预算、`out.dxf` 存在**且下游当场载得动**（`prepare()` 已保这一条）。

★ 正对照（不变红 = 判据没分辨力）：
  ① **盲扫撞 B**：`_PEDIT _M _C` 全闭合同一层 ⇒ B **必须红**（Δ残段远超上限）。
  ② **坏输入可分**：喂**存在但不是 DXF 的**文件 ⇒ 六态必须 **!= OK**（不许静默成功）。
  ③ **零刺激（TOL=−1）**：谁都不可能被点名 ⇒ **纯墙口径**必须报 `Δn_segs = 0`（地板为 0，
     这是 A/B/D 能「精确等于」的前提）；**链口径**的地板也当场量出来报（不判，只供 A2 对账）。
     ★ 它跑在 D 落判**之前**，因为 D 的容差要用它的读数。
  ④ **可重复**：同参数**另开一个目录**再跑一遍 ⇒ 下游读数**必须逐位相同**。

★ 盲区（必须声明，盲区内的否定判词不算证据）：
  ① **只走 `4.2墙体`**：`load_walls_and_cols` 的 `WALL_LAYERS` 是四个层名，本判据只喂 C006 的墙层；
     「别的层闭合了会怎样」不在射程内。
  ② **`residual` 的下游去向没量**：残段在 `score_cell` 里被 buffer 成墙足迹，
     「+300 mm 的足迹 vs +123.6 m 的足迹，最终模型差多少」**不在本判据射程内**（那是 §10.1）。
     本判据只证到「下游拿到的**中间量**确实变了、且增量可指名、有界」。
  ③ **四边形数在 C006 上无分辨力**：定向与盲扫都是 `+0` ⇒ 它是**并列读数不是判据**
     （铁律 137：判据有无分辨力必须喂确有缺陷的输入；这里喂了，它不动 ⇒ 不许当判据用）。
  ⑥ ★ **「剔踏步」在精确同偏移的重线上有 1e-9 级取舍抖动**（实测，`_scratch/probe_tread_roundtrip*.py`）：
     过一手 AutoCAD 后 `Δraw n_segs = +13`（闭合原样），但 `Δ剔 = +4`（4 组 11→12 条、组数 193 不变）。
     ⇒ 链口径的段数/残段**带着这 4 条的偏置**；本条只**量出来并对账**（A2），
     **不解释成对错** —— 判据不得改动冻结基线的取舍规则（那就是「臆造」）。
     ★ 也**不许**用坐标键做集合差来抓这 4 条（与盲区⑤同一个坑：过手后每个坐标都动 1.16e-9 mm）。
  ④ **单件单机**：只 C006 一份 DXF + 本机 AutoCAD 2022。换楼、换机器要重量。
  ⑤ ★ **不许用坐标哈希做集合差**：DXF 过一手 AutoCAD 会让**每个坐标**动 ~1.16e-9 mm
     （`-01` 的对照④实测），哈希键会把「每一条都变了」报成假新增 —— 本条盲区是
     **实测踩出来的**（`probe_downstream_close.py` 第二版曾用 `q.wkb` 印出 53.8% 的假新增）。
     ⇒ C 条改成「缺口段只有 ≤ 17 条，直接对残段集合做线性比对」，**根本不用键**。
  ⑥ **C006 的 41 条 2 顶点多段线**不在本判据里（它们不可能被点名，见 `-01` 的 E 条）。

用法: python J-07.9.4-02_wallclose_downstream.py          # 跑判据（约 4 min，起 5 次 AutoCAD）
     python J-07.9.4-02_wallclose_downstream.py --json o.json
"""
import os
import sys
import json
import time
import shutil
import tempfile
import argparse
import subprocess

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "a1"))
import cad_close_walls as CC          # noqa: E402
import generic_wall as GW             # noqa: E402  ★ 链自己在用的那两个函数
import stage2_prepare_dxf as S2       # noqa: E402

SRC = r"D:\项目\gym3d\材料\dxf_output\C006-第六教学楼（逸夫楼）.dxf"
WORK = os.path.join(ROOT, "_out", "J-07.9.4-02")
TOL = 480.0
PREFIX = "4.2"
SEC_BUDGET = 180.0
# ★ 比对容差 = 1 nm：与 `-01` 同源（那边对照④量出往返浮点噪声 1.164e-09 mm）。这里只用于 C 条。
COORD_TOL_MM = 1e-6
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4


# ----------------------------------------------------------------- 尺子（链自己的那两个函数）
def measure(dxf, drop_treads=True):
    """下游读数：链自己在用的载入 + 配对。**不碰 DXF 层，只量返回对象**。

    `drop_treads` 选口径（见文件头「两口径」）：
      · `True`  = 链口径（交付口径，含「剔踏步」这第二道变换）
      · `False` = 纯墙口径（只有闭合这一道变换）—— A/B/C/D 用它，正对照③在那里实测地板为 0
    """
    segs, _cols, _lab = GW.load_walls_and_cols(dxf, drop_treads=drop_treads)
    quads, residual = GW.wire(segs)
    return {"n_segs": len(segs), "n_quads": len(quads),
            "resid_len": float(sum(s.length for s in residual)),
            "quad_area": float(sum(q.area for q in quads)),
            "residual": residual}


def seg_dev(g, coords):
    """C 条的量具：两条 2 点线段的「端点互查」最大距离（mm）。不用哈什、不用键。"""
    return max(min(abs(p[0] - q[0]) + abs(p[1] - q[1]) for q in coords) for p in g)


def expected_from_source():
    """D 条的**独立来源**：直接从源 DXF 枚举该点名的缺口 → (条数, 缺口总长, 缺口段端点表)。
    ★ 这一路**不经过 AutoCAD**，与实测那条路唯一的共同点是「都读源 DXF 的几何」。"""
    ps = CC.wall_polys(SRC, PREFIX)
    hit = [p for (_h, p, c) in ps if not c and len(p) > 2 and CC.gap_mm(p) <= TOL]
    return len(hit), float(sum(CC.gap_mm(p) for p in hit)), [(p[-1], p[0]) for p in hit]


def nameable(gaps, residual, tol):
    """C 条：每条缺口段是否都在残段集合里找得到。返回 (找不到的条数, 最差偏差)。"""
    cs = [list(s.coords) for s in residual]
    miss, worst = 0, 0.0
    for g in gaps:
        d = min(seg_dev(g, c) for c in cs) if cs else float("inf")
        worst = max(worst, d)
        if d > tol:
            miss += 1
    return miss, worst


# ----------------------------------------------------------------- 正对照
def control_zero(tmp, base_raw, base_ch):
    """③ 零刺激：TOL=−1 ⇒ `gap_mm(p) <= -1` 恒假 ⇒ 谁也点不上名。
    返回 (是否触发, 纯墙口径地板 mm, 判词, 链口径读数 dict)。
    ★ 跑在 D 落判之前，D 的容差用**纯墙口径**的地板（实测应为 0）；
      链口径的地板同时量出来（只报不判，供 A2 对账）。"""
    r = S2.prepare(SRC, os.path.join(tmp, "zero"), -1.0, PREFIX)
    if r["state"] != S2.OK:
        return (False, 0.0,
                "零刺激没跑成（state=%s, detail=%s）" % (r["state"], str(r.get("detail"))[:60]),
                {})
    Mr = measure(r["out_dxf"], drop_treads=False)      # 纯墙口径
    Mc = measure(r["out_dxf"])                          # 链口径
    f_seg_r = Mr["n_segs"] - base_raw["n_segs"]
    f_res_r = Mr["resid_len"] - base_raw["resid_len"]
    f_seg_c = Mc["n_segs"] - base_ch["n_segs"]
    f_res_c = Mc["resid_len"] - base_ch["resid_len"]
    floor = abs(f_res_r)
    # ★ 牙：纯墙口径必须**逐位不动**（段数 0、残段 0）——这是 A/B/D「精确等于」的前提。
    ok = (r["picked"] == 0 and f_seg_r == 0 and abs(f_res_r) <= 1e-6)
    msg = ("点名 %d 条 ⇒ 纯墙口径 Δ段数 %+d、Δ残段 %+.6f mm ⇒ 地板 %.6f mm %s"
           "／链口径 Δ段数 %+d、Δ残段 %+.6f mm（只报）"
           % (r["picked"], f_seg_r, f_res_r, floor, "✓" if ok else "✗", f_seg_c, f_res_c))
    return bool(ok), floor, msg, {"chain_d_segs": int(f_seg_c), "chain_d_resid": float(f_res_c),
                                  "raw_d_segs": int(f_seg_r), "raw_d_resid": float(f_res_r)}


def control_blind(tmp, base):
    """① 盲扫（`_PEDIT _M _C` 全部未闭合多段线）⇒ B 条必须红。
    ★ 与 B 条**同口径**（纯墙口径）才谈得上「撞红 B」；链口径的地板在这里不参与。"""
    out = os.path.join(tmp, "blind")
    os.makedirs(out, exist_ok=True)
    inp = os.path.join(out, "in.dxf")
    shutil.copy2(SRC, inp)
    ps = CC.wall_polys(inp, PREFIX)
    hs = [h for (h, _p, c) in ps if not c]                    # 全点名，不筛几何
    lines = ['(setq nc 0)']
    for h in hs:
        lines += ['(command "_.PEDIT" (handent "%s") "_C" "")' % h, '(setq nc (1+ nc))']
    lines += ['(setq f (open "receipt.txt" "w"))',
              '(write-line (strcat "NC=" (itoa nc)) f)', '(close f)',
              '(command "_.DXFOUT" (strcat (getvar "DWGPREFIX") "out.dxf") "16")']
    CC.write_scr(os.path.join(out, "job.scr"), lines)
    try:
        p = subprocess.run([CC.EXE, "/i", inp, "/s", os.path.join(out, "job.scr")],
                           cwd=out, capture_output=True, timeout=CC.TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, "盲扫挂死（★ 与崩了分开报）", {}
    odxf = os.path.join(out, "out.dxf")
    if p.returncode != 0 or not os.path.exists(odxf):
        return False, "盲扫没跑出产出件（rc=%s）⇒ 这条对照无从落判" % p.returncode, {}
    M = measure(odxf, drop_treads=False)               # ★ 与 B 条同口径
    d_res = M["resid_len"] - base["resid_len"]
    lim = len(hs) * TOL
    ok = d_res > lim
    detail = {"picked": len(hs), "d_segs": int(M["n_segs"] - base["n_segs"]),
              "d_resid": float(d_res)}
    return bool(ok), ("盲扫点名 %d 条 ⇒ Δ段数 %+d、Δ残段 %+.1f mm（B 条上限 %.0f）⇒ %s"
                      % (len(hs), detail["d_segs"], d_res, lim,
                         "B 必红 ✓" if ok else "★ B 没红，判据没牙 ✗")), detail


def control_bad_input(tmp):
    """② 坏输入可分：喂**存在但不是 DXF 的**文件（喂不存在的路径会被前置检查拦成 SKIP，测的是我们的 if）。"""
    bad = os.path.join(tmp, "not_a_dxf.dxf")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("这不是 DXF，只是一段文本。\n")
    r = S2.prepare(bad, os.path.join(tmp, "bad"), TOL, PREFIX)
    ok = r["state"] != S2.OK
    return bool(ok), ("状态 = %s ⇒ %s" % (r["state"], "可分 ✓" if ok else "★ 静默成功 ✗"))


# ----------------------------------------------------------------- tee
def _Tee(*paths):
    class T:
        def __init__(self, *ps):
            self.fs = [open(p, "w", encoding="utf-8") for p in ps]

        def write(self, s):
            for f in self.fs:
                f.write(s)

        def flush(self):
            for f in self.fs:
                f.flush()
    return T(*paths)


def _run(a):
    t_all = time.time()
    if not os.path.isfile(SRC):
        print("★ 没量到：源 DXF 不在盘上 ⇒ %s" % SRC)
        return RC_NOGAUGE
    os.makedirs(WORK, exist_ok=True)
    fails = []

    print("== 跑一步（stage 2）：闭合 + **当场被下游载入一次**（TOL=%g，层 `%s`） ==" % (TOL, PREFIX))
    r = S2.prepare(SRC, os.path.join(WORK, "run"), TOL, PREFIX)
    print("  state=%s rc=%s %.1fs 点名 %s 条 回执=%s"
          % (r["state"], r.get("rc"), r.get("secs", 0), r.get("picked"), r.get("receipt")))
    if r["state"] != S2.OK:
        print("  detail:", r.get("detail"))
        print("\n★ 判词：**没量到**（不是判红）—— 这一步没跑出可比的前后两份件，A~E 无从落判")
        return RC_NOGAUGE
    picked = r["picked"]
    n_exp, sum_exp, gaps = expected_from_source()

    print("\n== 量下游（链自己在用的 load_walls_and_cols + wire） ==")
    A = measure(r["in_dxf"])                            # 链口径
    B = measure(r["out_dxf"])
    A_raw = measure(r["in_dxf"], drop_treads=False)     # 纯墙口径（只有闭合这一道变换）
    B_raw = measure(r["out_dxf"], drop_treads=False)
    d_seg, d_res = B_raw["n_segs"] - A_raw["n_segs"], B_raw["resid_len"] - A_raw["resid_len"]
    d_quad = B_raw["n_quads"] - A_raw["n_quads"]
    d_seg_ch, d_res_ch = B["n_segs"] - A["n_segs"], B["resid_len"] - A["resid_len"]
    drop_before = A_raw["n_segs"] - A["n_segs"]         # 原件被剔的踏步线条数
    drop_after = B_raw["n_segs"] - B["n_segs"]          # 闭合件被剔的踏步线条数
    d_drop = drop_after - drop_before                   # ★ 第二道变换自身动了多少条
    print("  %-16s %16s %16s %12s" % ("量（纯墙口径）", "原始", "闭合后", "差"))
    for k, lab in (("n_segs", "墙线段数"), ("n_quads", "墙身四边形"),
                   ("resid_len", "残段总长 mm"), ("quad_area", "四边形面积 mm²")):
        print("  %-16s %16.1f %16.1f %+12.1f" % (lab, A_raw[k], B_raw[k], B_raw[k] - A_raw[k]))
    print("  %-16s %16s %16s %+12d" % ("剔踏步（第二道）", drop_before, drop_after, d_drop))
    print("  链口径（交付那一份）：Δ段数 %+d、Δ残段 %+.6f mm　⇒ 含第二道变换的偏置 %d 条"
          % (d_seg_ch, d_res_ch, d_drop))

    print("\n== 正对照③ 先行：零刺激定噪声地板（D 的容差要用它） ==")
    tmp = tempfile.mkdtemp(prefix="j02ctl_")
    c3, floor, d3, zero_ch = control_zero(tmp, A_raw, A)
    print("  ", "✓" if c3 else "✗", d3)

    print("\n== A. 纯墙口径：闭合真的走到下游（新增段走进了墙输入） ==")
    okA = (d_seg == picked and picked > 0)
    print("  Δ墙线段数 = %+d，点名 %d 条 ⇒ %s" % (d_seg, picked, "✓" if okA else "✗"))
    if not okA:
        fails.append("A 新增段没走到下游")

    print("\n== A2. 两口径对账（主语不许被换掉） ==")
    okA2 = (d_seg_ch == d_seg - d_drop)
    print("  链口径 Δ段数 %+d ；纯墙口径 Δ段数 %+d − Δ剔 %+d = %+d ⇒ %s"
          % (d_seg_ch, d_seg, d_drop, d_seg - d_drop, "✓" if okA2 else "✗"))
    if not okA2:
        fails.append("A2 两口径对不上账")

    print("\n== B. ★ 不是坏的（有界，纯墙口径） ==")
    lim = picked * TOL
    okB = (0.0 <= d_res <= lim)
    print("  Δ残段总长 = %+.1f mm，允许区间 [0, 点名×TOL = %.0f] ⇒ %s" % (d_res, lim, "✓" if okB else "✗"))
    print("  并列读数（**不是判据**，见盲区③：定向/盲扫都是 +0 ⇒ 无分辨力）：Δ墙身四边形 = %+d" % d_quad)
    print("  并列读数（**不是判据**）：链口径 Δ残段 = %+.1f mm（差额即第二道变换：%+.1f mm）"
          % (d_res_ch, d_res_ch - d_res))
    if not okB:
        fails.append("B 残段增量越界")

    print("\n== C. 增量逐条可指名（缺口段必须能在残段里找到） ==")
    miss, worst = nameable(gaps, B_raw["residual"], COORD_TOL_MM)
    okC = (miss == 0)
    print("  缺口段 %d 条，找不到的 %d 条，最差偏差 %.3e mm（容差 %.0e mm）⇒ %s"
          % (len(gaps), miss, worst, COORD_TOL_MM, "✓" if okC else "✗"))
    if not okC:
        fails.append("C 有增量指不出名")

    print("\n== D. 两个独立来源同数（源 DXF 直接枚举 vs 实测下游，纯墙口径） ==")
    tolD = max(floor, 1e-3 * sum_exp)
    okD = abs(d_res - sum_exp) <= tolD
    print("  独立枚举：点名 %d 条、缺口合计 %.1f mm   ／   实测 Δ残段 %.1f mm" % (n_exp, sum_exp, d_res))
    if n_exp != picked:
        print("  ★ 两路点名条数不一致（%d vs %d）⇒ 没量到，停止落判" % (n_exp, picked))
        shutil.rmtree(tmp, ignore_errors=True)
        return RC_NOGAUGE
    print("  偏差 %.6f mm ≤ 容差 %.6f mm（= max(噪声地板 %.6f, 0.1%%×期望 %.6f)）⇒ %s"
          % (abs(d_res - sum_exp), tolD, floor, 1e-3 * sum_exp, "✓" if okD else "✗"))
    if not okD:
        fails.append("D 两路不同数")

    print("\n== E. 有界（时间 + 产出件 + 下游载得动） ==")
    okE = (r["state"] == S2.OK and (r.get("secs") or 1e9) < SEC_BUDGET
           and os.path.exists(r["out_dxf"]) and bool(r.get("downstream")))
    print("  %.1fs < %.0fs  产出件在盘=%s  下游载得动=%s  %s"
          % (r.get("secs", -1), SEC_BUDGET, os.path.exists(r["out_dxf"]),
             r.get("downstream"), "✓" if okE else "✗"))
    if not okE:
        fails.append("E 时间/产出件")

    print("\n== 其余正对照 ==")
    c1, d1, blind = control_blind(tmp, A_raw)
    print("  ① 盲扫必撞红 B     :", "✓" if c1 else "✗", d1)
    c2, d2 = control_bad_input(tmp)
    print("  ② 坏输入可分       :", "✓" if c2 else "✗", d2)
    print("  ③ 零刺激（TOL=−1） :", "✓" if c3 else "✗", d3)
    r2 = S2.prepare(SRC, os.path.join(WORK, "run2"), TOL, PREFIX)
    if r2["state"] == S2.OK:
        B2 = measure(r2["out_dxf"], drop_treads=False)      # ★ 与 A/B/D 同口径
        same = (B2["n_segs"] == B_raw["n_segs"] and B2["n_quads"] == B_raw["n_quads"]
                and abs(B2["resid_len"] - B_raw["resid_len"]) <= 1e-6)
        c4 = bool(same)
        d4 = ("第二遍 Δ段数 %+d、Δ残段 %+.6f mm ⇒ %s"
              % (B2["n_segs"] - A_raw["n_segs"], B2["resid_len"] - A_raw["resid_len"],
                 "逐位相同 ✓" if same else "★ 两遍不一样 ✗"))
    else:
        c4, d4 = False, "第二遍没跑成（state=%s）" % r2["state"]
    print("  ④ 可重复           :", "✓" if c4 else "✗", d4)
    shutil.rmtree(tmp, ignore_errors=True)
    for c, tag in ((c1, "C1"), (c2, "C2"), (c3, "C3"), (c4, "C4")):
        if not c:
            fails.append("对照%s 未触发" % tag)

    print("\n===== 判词 =====")
    rc = RC_FAIL if fails else RC_PASS
    if fails:
        print("  FAIL  rc=1   未过项:", fails)
    else:
        print("  PASS  rc=0   A/A2/B/C/D/E 全绿，四条正对照全触发")
    print("  用时 %.1fs" % (time.time() - t_all))
    if a.json:
        os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
        json.dump({"pass": rc == 0,
                   "run": {k: r.get(k) for k in ("state", "rc", "secs", "picked", "receipt")},
                   # ★ 交付口径 = 链口径（含剔踏步）；判据口径 = 纯墙口径。两份都写，别让读的人猜。
                   "downstream_raw": {
                       "before": {k: A_raw[k] for k in ("n_segs", "n_quads", "resid_len", "quad_area")},
                       "after": {k: B_raw[k] for k in ("n_segs", "n_quads", "resid_len", "quad_area")},
                       "d_segs": int(d_seg), "d_resid": float(d_res), "d_quads": int(d_quad),
                       "dropped_before": int(drop_before), "dropped_after": int(drop_after),
                       "d_dropped": int(d_drop)},
                   "downstream_chain": {
                       "before": {k: A[k] for k in ("n_segs", "n_quads", "resid_len", "quad_area")},
                       "after": {k: B[k] for k in ("n_segs", "n_quads", "resid_len", "quad_area")},
                       "d_segs": int(d_seg_ch), "d_resid": float(d_res_ch)},
                   "expected_from_source": {"n": int(n_exp), "gap_sum": float(sum_exp)},
                   "tolerance_D": {"noise_floor": float(floor), "used": float(tolD)},
                   "zero_stimulus": zero_ch,
                   "blind": blind,
                   # ★ 演示页要的那个倍数：**盲扫 Δ残段 ÷ 定向 Δ残段**。
                   #   分母是「定向闭合在下游留下的痕迹」，不是「缺口合计」—— 两者数值上撞巧
                   #   很接近（都在 300 附近），但含义完全不同；混用会把 412 倍印成 1 倍（本页踩过）。
                   "ratio_blind_over_targeted": float(blind["d_resid"] / d_res) if d_res else None,
                   "controls": {"blind_caught_by_B": bool(c1), "bad_input": bool(c2),
                                "zero_stimulus": bool(c3), "repeatable": bool(c4)},
                   "fails": fails}, open(a.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("  写出:", a.json)
    return rc


def main():
    ap = argparse.ArgumentParser()
    # ★ 默认落**正规名**（理由同 `-01`；`-03` 会读本件的 json 做跨判据互证 ⇒
    #   本件不写 json 就等于让 `-03` 去核**上一趟**的数）。
    ap.add_argument("--json",
                    default=os.path.join(HERE, "_out", "J-07.9.4-02.json"))
    a = ap.parse_args()
    os.makedirs(os.path.join(HERE, "_out"), exist_ok=True)
    tee = _Tee(os.path.join(HERE, "_out", "J-07.9.4-02.run.txt"))
    old = sys.stdout
    sys.stdout = tee
    try:
        rc = _run(a)
    finally:
        sys.stdout = old
        tee.flush()
        for f in tee.fs:
            f.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
