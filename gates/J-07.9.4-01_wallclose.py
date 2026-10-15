# -*- coding: utf-8 -*-
"""判据 J-07.9.4-01：**专业软件接进链的第一件真活** —— 用 AutoCAD headless 批量闭合墙层多段线。

对应方案 **§7.9.4 结论 2**（「现成的第一件活」）。
★ 编号为什么不是 `J-09.2-A2`：§9.2 的 **A2 是「平台功能」**（选楼栋/跑链/出料账/打包），
  与本节不是一回事 ⇒ 取**判据所属章节** §7.9.4 编号，免得读的人把它当成平台功能的判据。
四件套（§10.0.1）：
  ① 量交付件本身  —— 量的是 `accoreconsole` **过出来的那份 DXF**，不是脚本、不是日志
  ② 量具写明      —— `tools/cad_close_walls.py` 的 `wall_polys / gap_mm / pick_handles / gauge`
  ③ 盲区声明      —— 见下
  ④ 正对照必配    —— **四条**（E/F/G/H，见下）

★ 判据（全部为真才算过）：
  A. **两个独立读器同数**：AutoCAD 自己 `ssget` 数出的墙层条数（回执 `NALL`）
     == ezdxf 数出的条数 ⇒ 「这一层有几条」不是单一来源。
  B. **闭合真发生且三个数对得上**：`后.flag − 前.flag` == Python 点名条数 == 回执 `NC`。
  C. ★ **无损伤**（这条是本节的重点，见下「为什么」）：
     · 未点名的多段线：顶点序列**逐点全等**；
     · 点名的：**顶点数不变、顶点坐标不变**，只有 `closed` 由 0 变 1；
     · 新增段总长 ≤ 点名条数 × TOL（有界）。
  D. 有界时间 + 回执齐全：状态 == OK，且耗时 < 预算。
  E. 正对照① **合成样本喂尺子**：植入已知的 3 闭合 / 2 首尾重合但标志未置（诱饵）/ 1 缺口 100 mm /
     1 缺口 50 m / 1 条两顶点 ⇒ 尺子必须报 `n=8 / flag=3 / geom=2`（`geom` 只数两条诱饵），
     且 TOL=480 点名 3 条、TOL=60 点名 2 条、两顶点那条**永远不点名**。
  F. 正对照② **坏输入可分**：喂**存在但不是 DXF 的**文件 ⇒ 状态必须 != OK（不许静默成功）。
  G. 正对照③ **本判据的 C 条有牙**：用**盲扫**（`_PEDIT` `_M` `_C`，不带几何筛选）过一遍同一层
     ⇒ C 的「新增段总长 ≤ 点名 × TOL」**必须红** ⇒ 证明 C 逮得住坏做法，不是一句安慰话。
  H. 正对照④ **纯往返定容差**：零闭合、只让 AutoCAD 过一手 ⇒ 量出的浮点噪声**必须** ≤ `COORD_TOL_MM`
     ⇒ C 条的容差是从这条对照来的，不是拍的。

★★ **为什么有 C 这条（本节的由来）**：
  方案 §7.9.4 写的第一件活是「C006 墙线 454 条里只有 126 条闭合」⇒ 盲扫闭合。两处实测都不成立：
    · **那个数就不是墙线**：454/126 是**全文件** LWPOLYLINE（其中 `Defpoints` 一项 246 条、0 闭合）；
      墙层 `4.2墙体` 自己只有 **135 条、77 闭合**（`_scratch/probe_closure.py` 复现）。
    · **盲扫会拆楼**：`PEDIT Close` 是「在末点与首点间**加一段**」⇒ 58 条未闭合里只有 12 条首尾本就重合，
      **23 条加出来 > 5 m、最长 46.4 m**（`_scratch/probe_cad_damage.py`）——
      而本仓两条链（`a1/generic_wall.py:59`、`libs3d/c006/wall_solid.py`）**都会吃掉新增段**。
  ⇒ 于是「闭合率 77→135」这个漂亮的数**不是白得的**；判据必须能量出代价，而不是只数闭合。

★ 盲区（必须声明，盲区内的否定判词不算证据）：
  ① **只量 `LWPOLYLINE`**。`4.2墙体` 层还混着 LINE 12396 / INSERT 754 / ARC 54 / CIRCLE 70 ——
     它们**一条都不在分母里**；本判据对「线画成 LINE 而不是多段线」全盲。
  ② **`flag` 是标志不是几何**。C006 墙层实测 `flag=77` 而 `geom=12`（差 6 倍）；
     混用两者会把「标志没置」当成「真开口」。判据只用 `flag`，`geom` 只作并列读数。
  ③ **TOL 是台阶上的取值**，不是从规范推的。实测缺口只有三档（0.0 × 12 / 300.0 × 1 / ≥14499.5 × 4），
     TOL ∈ [300, 14499] 结果都一样 = 13 条 ⇒ 默认 480 落在这个平台期**中间**；但**换一栋楼要重量台阶**。
  ④ **本判据不管闭合了有什么用**。它能证的只有「这一步可重复、有界、无损伤」；
     「闭合后的模型更对」不在本判据射程内（那是 §10.1 的活）。
  ⑤ **单机单件**：只在 C006 一份 DXF + 本机 AutoCAD 2022 上量过；换机器/换版本要重量。
  ⑥ **rc 在本入口上没有裁判资格**（§7.9.4 烟测）：脚本层失败一律 rc=0 或挂死 ⇒ 本判据只认**回执文件**。

用法: python J-07.9.4-01_wallclose.py            # 跑判据（约 28 s）
     python J-07.9.4-01_wallclose.py --json o.json
"""
import os
import sys
import json
import time
import argparse
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cad_close_walls as CC      # noqa: E402

SRC = r"D:\项目\gym3d\材料\dxf_output\C006-第六教学楼（逸夫楼）.dxf"
WORK = os.path.join(ROOT, "_out", "J-07.9.4-01")
TOL = 480.0
PREFIX = "4.2"
SEC_BUDGET = 120.0
# ★ 坐标比对容差 = 1 nm。**不是拍的**：正对照④（不做任何闭合、纯走一遍 DXF 往返）量出
#   AutoCAD 过一手会引入 ~1.16e-9 mm 的浮点噪声 ⇒ 容差必须在这之上，又远在任何图纸长度之下。
COORD_TOL_MM = 1e-6
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4


def max_dev(a_path, b_path):
    """两条件逐点比，返回最大偏差（mm）。纯往返也非零，见 COORD_TOL_MM 的由来。"""
    A, B = CC.wall_polys(a_path, PREFIX), CC.wall_polys(b_path, PREFIX)
    d = 0.0
    for (ha, pa, _), (hb, pb, _) in zip(A, B):
        if ha != hb or len(pa) != len(pb):
            return float("inf")
        for (x, y), (u, v) in zip(pa, pb):
            d = max(d, abs(x - u), abs(y - v))
    return d


def cmp_polys(a_path, b_path, picked):
    """C 条的量具：逐条比顶点。返回 (未点名是否有差, 点名的是否只有标志变, 新增段总长, 明细)。"""
    A = CC.wall_polys(a_path, PREFIX)
    B = CC.wall_polys(b_path, PREFIX)
    if len(A) != len(B):
        return False, False, None, "条数变了 %d → %d（不是同一批，停止比较）" % (len(A), len(B))
    bad_free, bad_picked, added = [], [], 0.0
    for (ha, pa, ca), (hb, pb, cb) in zip(A, B):
        if ha != hb or len(pa) != len(pb):
            bad_free.append(ha)
            continue
        dev = max(max(abs(x - u), abs(y - v)) for (x, y), (u, v) in zip(pa, pb))
        if ha in picked:
            if dev > COORD_TOL_MM or not (cb and not ca):  # 点名的：坐标必须不变，且只许 未闭合→闭合
                bad_picked.append((ha, dev, ca, cb))
            added += CC.gap_mm(pa)
        elif dev > COORD_TOL_MM or ca != cb:               # 未点名的：一个字节都不该动
            bad_free.append((ha, dev, ca, cb))
    return (not bad_free), (not bad_picked), added, {"bad_free": bad_free[:5], "bad_picked": bad_picked[:5]}


def build_synthetic(path):
    """E 条的已知刺激。★ 每个数都是**植入**的，不是量出来的 —— 尺子必须报回一模一样的数。"""
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (1000, 0), (1000, 1000), (0, 1000)], close=True, dxfattribs={"layer": "4.2墙体"})
    msp.add_lwpolyline([(2000, 0), (3000, 0), (3000, 1000), (2000, 1000)], close=True, dxfattribs={"layer": "4.2墙体"})
    msp.add_lwpolyline([(4000, 0), (5000, 0), (5000, 1000), (4000, 1000)], close=True, dxfattribs={"layer": "4.2墙体"})
    # 诱饵 D1/D2：首尾点**重合**（几何闭合）但 **标志未置** ⇒ 只能被 `geom` 数到，不能被 `flag` 数到
    for x0 in (6000, 8000):
        msp.add_lwpolyline([(x0, 0), (x0 + 1000, 0), (x0 + 1000, 1000), (x0, 1000), (x0, 0)],
                           close=False, dxfattribs={"layer": "4.2墙体"})
    # U1：缺口**正好 100 mm**（TOL=480 该点名、TOL=60 不该）
    msp.add_lwpolyline([(0, 5000), (1000, 5000), (1000, 6000), (0, 6000), (0, 5100)],
                       close=False, dxfattribs={"layer": "4.2墙体"})
    # U2：缺口**正好 50 m**（哪个 TOL 都不该点名）
    msp.add_lwpolyline([(0, 8000), (1000, 8000), (1000, 9000), (0, 9000), (0, 58000)],
                       close=False, dxfattribs={"layer": "4.2墙体"})
    # S1：两顶点未闭合（顶点数 = 2 ⇒ 闭合是退化的反向重复，**永远不点名**）
    msp.add_lwpolyline([(0, 20000), (30000, 20000)], close=False, dxfattribs={"layer": "4.2墙体"})
    # 干扰：别的层不许进分母
    msp.add_lwpolyline([(0, 30000), (1000, 30000), (1000, 31000)], close=True, dxfattribs={"layer": "Defpoints"})
    doc.saveas(path)


def control_gauge(tmp):
    """E：合成样本 ⇒ 尺子必须报回植入的数。"""
    p = os.path.join(tmp, "syn.dxf")
    build_synthetic(p)
    ps = CC.wall_polys(p, PREFIX)
    g = CC.gauge(p, PREFIX)
    want = {"n": 8, "flag": 3, "geom": 2}     # 8 条墙层（别的层那条不算）；geom 只数 D1/D2 两条诱饵
    got_ok = (g == want)
    p480 = CC.pick_handles(ps, 480.0)
    p60 = CC.pick_handles(ps, 60.0)
    two = [h for h, pp, c in ps if len(pp) == 2]
    ok = got_ok and len(p480) == 3 and len(p60) == 2 and not any(h in p480 for h in two)
    return ok, ("植入 n=8/flag=3/geom=2 ⇒ 实报 %s；TOL480 点名 %d（须 3）、TOL60 点名 %d（须 2）；"
                "两顶点那条被点名=%s（须 False）"
                % (g, len(p480), len(p60), any(h in p480 for h in two)))


def control_bad_input(tmp):
    """F：坏输入 ⇒ 状态必须 != OK。

    ★ 这里喂的是**存在但不是 DXF 的文件**，不是「路径不存在」——后者在 `close_walls` 里被前置检查拦成
      SKIP（「缺件」），压根到不了 accoreconsole，测的是我们的 if，不是那个入口。
      （§10.0.5 第 19 条：刺激要喂到被测的那一层。）
    """
    p = os.path.join(tmp, "garbage.dxf")
    with open(p, "wb") as f:
        f.write(b"this is not a dxf\n")
    r = CC.close_walls(p, os.path.join(tmp, "bad"), TOL, PREFIX)
    return r["state"] != CC.OK, "喂非 DXF 文件 ⇒ state=%s rc=%s（须 != OK）" % (r["state"], r.get("rc"))


def control_roundtrip(tmp):
    """★ 正对照④ **纯往返基线**：不做任何闭合，只让 AutoCAD 过一手 ⇒ C 条的容差从哪来。"""
    d = os.path.join(tmp, "rt")
    os.makedirs(d, exist_ok=True)
    import shutil
    shutil.copy2(SRC, os.path.join(d, "in.dxf"))
    CC.write_scr(os.path.join(d, "job.scr"), [
        '(setq f (open "receipt.txt" "w"))',
        '(write-line "NC=0" f)',
        '(close f)',
        '(command "_.DXFOUT" (strcat (getvar "DWGPREFIX") "out.dxf") "16")'])
    import subprocess
    try:
        p = subprocess.run([CC.EXE, "/i", os.path.join(d, "in.dxf"), "/s", os.path.join(d, "job.scr")],
                           cwd=d, capture_output=True, timeout=CC.TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, "纯往返挂死 —— 这条对照本身没量到"
    odxf = os.path.join(d, "out.dxf")
    if p.returncode != 0 or not os.path.exists(odxf):
        return False, "纯往返没产出件（rc=%s）" % p.returncode
    dev = max_dev(SRC, odxf)
    return bool(dev <= COORD_TOL_MM), ("纯往返（零闭合）最大坐标偏差 %.3e mm ⇒ 容差 %.0e mm 有据" % (dev, COORD_TOL_MM))


def control_blind(tmp):
    """G：盲扫（不筛选）⇒ C 条必须红。"""
    d = os.path.join(tmp, "blind")
    os.makedirs(d, exist_ok=True)
    import shutil
    shutil.copy2(SRC, os.path.join(d, "in.dxf"))
    CC.write_scr(os.path.join(d, "job.scr"), [
        '(setq ss (ssget "X" (list (cons 0 "LWPOLYLINE") (cons 8 "4.2*"))))',
        '(command "_.PEDIT" "_M" ss "" "_C" "")',
        '(setq f (open "receipt.txt" "w"))',
        '(write-line "NC=blind" f)',
        '(close f)',
        '(command "_.DXFOUT" (strcat (getvar "DWGPREFIX") "out.dxf") "16")'])
    import subprocess
    t0 = time.time()
    try:
        p = subprocess.run([CC.EXE, "/i", os.path.join(d, "in.dxf"), "/s", os.path.join(d, "job.scr")],
                           cwd=d, capture_output=True, timeout=CC.TIMEOUT_S)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        return False, "盲扫挂死（超时）—— 这条对照本身没量到"
    odxf = os.path.join(d, "out.dxf")
    if rc != 0 or not os.path.exists(odxf):
        return False, "盲扫没产出件（rc=%s）—— 对照没量到" % rc
    # 用 C 的尺子量盲扫产出件：拿「零点名」当前提，任何新增段都算超限
    A = CC.wall_polys(SRC, PREFIX)
    B = CC.wall_polys(odxf, PREFIX)
    added, worst = 0.0, 0.0
    for (ha, pa, ca), (hb, pb, cb) in zip(A, B):
        if len(pa) == len(pb) and not ca and cb:
            l = CC.gap_mm(pa)
            added += l
            worst = max(worst, l)
    lim = 13 * TOL                      # 正确做法的上限（点名 13 × TOL）
    return added > lim, ("盲扫新增段总长 %.1f mm（上限 %.1f = 13×TOL）、单条最长 %.1f mm ⇒ 超限=%s"
                         % (added, lim, worst, added > lim))


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
    fails, unmeasured = [], []

    print("== 跑一步：AccoreConsole 点名闭合（TOL=%g mm，层前缀 `%s`） ==" % (TOL, PREFIX))
    r = CC.close_walls(SRC, os.path.join(WORK, "run"), TOL, PREFIX)
    print("  state=%s rc=%s %.1fs 点名 %s 条  回执=%s"
          % (r["state"], r.get("rc"), r.get("secs", 0), r.get("picked"), r.get("receipt")))
    if r["state"] != CC.OK:
        print("  detail:", r.get("detail"))
        print("\n★ 判词：**没量到**（不是判红）—— 这一步没跑出可比的前后两份件，A/B/C/D 四条无从落判")
        return RC_NOGAUGE

    before, after = r["before"], r["after"]
    picked = set()
    pk = os.path.join(WORK, "run", "picked.txt")
    if os.path.exists(pk):
        picked = set(open(pk, encoding="utf-8").read().split("\n")[1].split())

    print("\n== A. 两个独立读器同数（AutoCAD ssget vs ezdxf） ==")
    nall = r["receipt"].get("NALL")
    okA = (nall is not None and int(nall) == before["n"])
    print("  AutoCAD 回执 NALL=%s   ezdxf=%d   %s" % (nall, before["n"], "✓" if okA else "✗"))
    if not okA:
        fails.append("A 两读器不同数")

    print("\n== B. 闭合真发生，三个数对得上 ==")
    d_flag = after["flag"] - before["flag"]
    nc = r.get("receipt_delta")
    okB = (d_flag == len(picked) == nc and d_flag > 0)
    print("  flag %d → %d（Δ=%d）  点名 %d  回执 NC=%s   %s"
          % (before["flag"], after["flag"], d_flag, len(picked), nc, "✓" if okB else "✗"))
    print("  并列读数（不判）：geom %d → %d（`geom` = 首尾点真的重合，见盲区②）"
          % (before["geom"], after["geom"]))
    if not okB:
        fails.append("B 三个数对不上")

    print("\n== C. ★ 无损伤（新增段有界；未点名的逐点全等） ==")
    ok_free, ok_pick, added, det = cmp_polys(r["in_dxf"], r["out_dxf"], picked)
    added = float(added)          # ★ np.float64 不是 JSON 能序列化的（本轮被这个咬过一次）
    lim = len(picked) * TOL
    okC = bool(ok_free and ok_pick and added <= lim)
    print("  未点名逐点全等=%s  点名的只动标志=%s  新增段总长=%.1f mm（上限 %d）  %s"
          % (ok_free, ok_pick, added, lim, "✓" if okC else "✗"))
    if det["bad_free"]:
        print("    未点名却变了的:", det["bad_free"])
    if det["bad_picked"]:
        print("    点名的动作越界:", det["bad_picked"])
    if not okC:
        fails.append("C 有损伤")

    print("\n== D. 有界时间 + 回执齐全 ==")
    okD = (r["state"] == CC.OK and (r.get("secs") or 1e9) < SEC_BUDGET
           and os.path.exists(r["out_dxf"]))
    print("  %.1fs < %.0fs  产出件在盘=%s  %s"
          % (r.get("secs", -1), SEC_BUDGET, os.path.exists(r["out_dxf"]), "✓" if okD else "✗"))
    if not okD:
        fails.append("D 时间/产出件")

    print("\n== 正对照（不变红 = 判据没分辨力） ==")
    with tempfile.TemporaryDirectory(prefix="a2ctl_") as tmp:
        c1, d1 = control_gauge(tmp);  print("  ① 合成样本喂尺子   :", "✓" if c1 else "✗", d1)
        c2, d2 = control_bad_input(tmp); print("  ② 坏输入可分       :", "✓" if c2 else "✗", d2)
        c3, d3 = control_blind(tmp);  print("  ③ 盲扫必被 C 逮住  :", "✓" if c3 else "✗", d3)
        c4, d4 = control_roundtrip(tmp); print("  ④ 纯往返定容差     :", "✓" if c4 else "✗", d4)
    for c, tag in ((c1, "C1"), (c2, "C2"), (c3, "C3"), (c4, "C4")):
        if not c:
            fails.append("对照%s 未触发" % tag)

    print("\n===== 判词 =====")
    rc = RC_FAIL if fails else RC_PASS
    if fails:
        print("  FAIL  rc=1   未过项:", fails)
    else:
        print("  PASS  rc=0   A/B/C/D 全绿，四条正对照全触发")
    print("  用时 %.1fs" % (time.time() - t_all))
    if a.json:
        os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
        json.dump({"pass": rc == 0, "run": {k: r.get(k) for k in
                   ("state", "rc", "secs", "picked", "before", "after", "receipt")},
                   "picked": sorted(picked), "added_mm": added,
                   "controls": {"gauge_synth": bool(c1), "bad_input": bool(c2),
                                "blind_caught": bool(c3), "roundtrip": bool(c4)},
                   "fails": fails}, open(a.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("  写出:", a.json)
    return rc


def main():
    ap = argparse.ArgumentParser()
    # ★ 默认落**正规名**（`gates/_out/<判据号>.json`），与其余 8 条闸一致。
    #   旧默认 `None` ⇒ 不显式传就**一个 json 都不写**，盘上那份是上一趟的 ⇒ 页面把
    #   两个不同趟的读数当「三读互证」用（铁律「旧文件不是今天的答案」）。
    ap.add_argument("--json",
                    default=os.path.join(HERE, "_out", "J-07.9.4-01.json"))
    a = ap.parse_args()
    os.makedirs(os.path.join(HERE, "_out"), exist_ok=True)
    tee = _Tee(os.path.join(HERE, "_out", "J-07.9.4-01.run.txt"))
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
