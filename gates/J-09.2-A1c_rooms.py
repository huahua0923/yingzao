# -*- coding: utf-8 -*-
"""判据 J-09.2-A1c：**房间台账（人写的房间号+面积）能按空间配对抽出来**，且配对闸有分辨力。

对应方案 §9.2 轨A·A1「逐类构件覆盖率」之外的第 4 类，也是 §10.1「房间/面积：按列算的面积 vs
台账/图纸面积，逐层对账」的**参考侧**。四件套（§10.0.1）：
  ① 量交付件本身 —— 现场读 DXF、现场收文字、现场配对；不读任何中间日志/快照
  ② 量具写明      —— `a1/rooms.py`（collect/join）+ `a1/batch_rooms.py`（全库扫）
  ③ 盲区声明      —— 见下
  ④ 正对照必配    —— **四条**（B/C/D/F）

★ 背景：房间属性在本库**是独立图层**（不同于门/窗/梯/板/梁 —— 那些连层都没有）：
  `6房间号`(97 份/13432) · `5面积`(98/12982) · `8房间用途`(31) · `7使用单位`(49)。
  房间号与面积**成对摆放**（实测「号→最近面积」距几乎恒定：C006 全 650 / C109 全 750 / C001 中位 807 mm）。

★ 判据（全部为真才算过）：
  A. **台账覆盖率**：全库 ≥ `COV_MIN`(=85%) 的栋能抽出 ≥1 行房间（实测 **91/105 = 86.7%**）
  B. **正对照 C109 三个独立计数相等**：房间号条数 == 面积文字条数 == 配对成功行数 == 141，
     且**拒配数 == 0**。（★ 三个数各自来自**分开收集的清单**，不是一个数抄三遍 —— 铁律 174）
  C. **对照①（打乱输入的位置）**：把全部面积文字的坐标整体推 **10 km**（推出图幅网格，步长 ~111 m）
     再配对 ⇒ 配到行数必须**塌到 0**（证明「配对是按位置来的」，不是按顺序/按名字）
  D. **对照②（把闸拿掉，喂已知错的刺激）**：同一份 C001 图，把配对距离闸从 1500 放到 1e9（= 无闸）
     ⇒ **用途/单位**的配到数必须**显著上升**（实测会从 25 涨到几十）—— 证明那道闸**确实在拦人**。
     ★ 这道闸是本轮**自己抓出来的缺陷**：C001 有一条 `7使用单位` 文字距房间号 **479.6 m**（跨 ≈4 个图幅），
       不加闸时会被**无声**贴到 78 个房间上（一个凭空的事实）
  E. **非空断言**：扫到的 DXF 数 == 0 ⇒ 判**不成立**（遍历型判据扫空集合会恒绿）
  F. **交叉印证**：C006 房间号里的层段必须 == `{01..11, D1}`（12 层）。此参照**与 A1 读的不是同一个来源**
     （那条是图幅房号层码 + DSM 层高印证的「11 层 + D1」裁定）⇒ 两条读数互不派生

★ 盲区（必须声明，盲区内的否定判词不算证据）：
  ① 只认 `rooms.*_LAYERS` 列出的层名 —— 台账画在别的层（如 `0`）全盲。「某栋 0 行」只等于**层名对不上**，
     **不**等于「这栋没有台账」。
  ② **「抽出 N 行」≠「这 N 行对」**：配对是**近邻**，闸内仍可能配错而无声；面积是**人写数**，本身可能写错。
     ⇒ 本条**只给覆盖率与配对数**，**不给「台账正确」结论**；也**不判**面积与「按列算的面积」吻不吻合
     （模型侧还没建，那一步本条**不假装做了**）。
  ③ **拒配是两类混在一个数里**：`n_far` 同时含「该图根本没有面积文字」与「有、但都超出配对距离」。
     本条**分开报**两项，但分母都写在输出里。
  ④ 只覆盖 `--dir` 里的 *.dxf；参数（层名表/TOL）与 `rooms.py` 同源，改那边会改这里的数。

用法: python gates/J-09.2-A1c_rooms.py            # 全库扫（~2 min）
     python gates/J-09.2-A1c_rooms.py --quick     # 只跑样板（~20 s）
     python gates/J-09.2-A1c_rooms.py --json gates/_out/J-09.2-A1c.json
"""
import sys
import os
import glob
import json
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
A1 = os.path.join(ROOT, "a1")
sys.path.insert(0, A1)
import rooms as R                    # noqa: E402
import batch_rooms as BR             # noqa: E402

DXF_DIR = r"D:\项目\gym3d\材料\dxf_output"
QUICK = ["C006-第六教学楼（逸夫楼）", "C009-第九教学楼", "C075-综合实验大楼",
         "C109-十公寓", "C001-砚湖图书馆", "C054-银杏园1号公寓"]
C109 = os.path.join(DXF_DIR, "C109-十公寓.dxf")
C001 = os.path.join(DXF_DIR, "C001-砚湖图书馆.dxf")
C006 = os.path.join(DXF_DIR, "C006-第六教学楼（逸夫楼）.dxf")
N_C109_ROOMS = 141          # 实测锚点（三个独立计数都等于它；见 B 的注释）
C006_FLOORS = {"01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "D1"}
SHIFT = 1.0e7               # 10 km：跨出图幅网格（步长 ~111 m）。10 m 不够 —— 同栋/邻房仍会撞上（铁律：对照须跨出重复结构）
COV_MIN = 85.0
UNBOUND_TOL = 1.0e9         # D 对照：= 把闸拿掉


def shifted(pools, dx, dy=0.0):
    """C 对照：只动**位置**，一个字都不改（证明配对靠位置）。"""
    out = dict(pools)
    out["areas"] = [(s, (p[0] + dx, p[1] + dy)) for s, p in pools["areas"]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DXF_DIR)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--json", default=os.path.join(HERE, "_out", "J-09.2-A1c.json"))
    a = ap.parse_args()

    fails = []
    print("判据 J-09.2-A1c  房间台账（房间号+面积+用途+单位）空间配对")
    print("  DXF 目录:", a.dir)

    # ---- A 覆盖率 ----
    if a.quick:
        files = [os.path.join(a.dir, n + ".dxf") for n in QUICK]
        print("\n== A 台账覆盖率（--quick：样板 %d 块，非全库）==" % len(files))
        full = False
    else:
        files = sorted(glob.glob(os.path.join(a.dir, "*.dxf")))
        print("\n== A 台账覆盖率（全库）==")
        full = True
    if not files:
        print("  ★ 扫到 0 份 DXF ⇒ 判据**不成立**（E 非空断言）")
        return 3                              # E
    n_hit = 0
    seen = []
    for f in files:
        r = BR.one(f)
        if "err" in r:
            print("   !! %s %s" % (r["dxf"][:40], r["err"])); continue
        seen.append(r)
        if r["stats"]["n_joined"] > 0:
            n_hit += 1
        print("   %-42s 行 %5d / 号 %5d / 层 %2d" %
              (r["dxf"][:42], r["stats"]["n_joined"], r["stats"]["n_id"], r["stats"]["n_floor"]))
    cov = 100.0 * n_hit / max(len(seen), 1)
    print("  ⇒ 抽出房间行的栋: %d / %d = %.1f%%（阈值 %.0f%%）%s"
          % (n_hit, len(seen), cov, COV_MIN, "✓" if cov >= COV_MIN else "✗"))
    if full and cov < COV_MIN:
        fails.append("A 台账覆盖率 %.1f%% < %.0f%%" % (cov, COV_MIN))

    # ---- B 正对照：三个独立计数相等 ----
    print("\n== B 正对照（C109 确有台账）==")
    rb = BR.one(C109)
    if "err" in rb:
        print("   ✗ 读失败:", rb["err"]); fails.append("B C109 读失败")
        st = {}
    else:
        st = rb["stats"]
        print("   房间号 %d / 面积文字 %d / 配到 %d / 拒配 %d ⇒ %s"
              % (st["n_id"], st["n_area_text"], st["n_joined"], st["n_far"],
                 "✓ 三数相等且无拒配" if (st["n_id"] == st["n_area_text"] == st["n_joined"]
                                          == N_C109_ROOMS and st["n_far"] == 0) else "✗"))
        if not (st["n_id"] == st["n_area_text"] == st["n_joined"] == N_C109_ROOMS):
            fails.append("B C109 三数不等/≠%d（号 %d 面积文字 %d 配到 %d）"
                         % (N_C109_ROOMS, st["n_id"], st["n_area_text"], st["n_joined"]))
        if st["n_far"] != 0:
            fails.append("B C109 拒配 %d（应 0）" % st["n_far"])

    # ---- C 对照①：把面积文字整体推出图幅网格 ----
    print("\n== C 对照①（面积文字平移 10 km ⇒ 配到应塌到 0）==")
    pools = R.collect(C109)
    _, st0 = R.join(pools)
    _, st1 = R.join(shifted(pools, SHIFT))
    print("   原样 配到 %d ⇒ 平移后 配到 %d %s"
          % (st0["n_joined"], st1["n_joined"], "✓ 塌到 0" if st1["n_joined"] == 0 else "✗ 未塌"))
    if st0["n_joined"] == 0:
        fails.append("C 对照① 在**原样**输入上就为 0 ⇒ 无分辨力（元判据失效）")
    if st1["n_joined"] != 0:
        fails.append("C 对照① 平移 10km 仍配到 %d（应 0）" % st1["n_joined"])

    # ---- D 对照②：把距离闸拿掉，喂已知错的刺激 ----
    print("\n== D 对照②（C001 把配对闸 1500→1e9 ⇒ 用途/单位配到数必须上升）==")
    p1 = R.collect(C001)
    _, dn = R.join(p1)
    _, du = R.join(p1, tol=UNBOUND_TOL)
    print("   有闸 单位配到 %d ⇒ 无闸 %d   （差 %d 个是**凭空贴上去**的）"
          % (dn["n_unit"], du["n_unit"], du["n_unit"] - dn["n_unit"]))
    print("   有闸 用途配到 %d ⇒ 无闸 %d" % (dn["n_use"], du["n_use"]))
    if du["n_unit"] <= dn["n_unit"]:
        fails.append("D 对照② 拿掉闸后单位配到数没涨（%d→%d）⇒ 闸没有分辨力"
                     % (dn["n_unit"], du["n_unit"]))
    if du["n_unit"] == 0:
        fails.append("D 对照② 连无闸都是 0 ⇒ 图上没有可贴的单位文字，本对照无效")

    # ---- F 交叉印证：C006 层段 ----
    print("\n== F 交叉印证（C006 房间号的层段 vs 「11 层 + D1」裁定）==")
    rf = BR.one(C006)
    fl = set(rf.get("stats", {}).get("floors", []))
    print("   C006 层段 %s（%d 层）⇒ %s"
          % (sorted(fl), len(fl), "✓ 与 11+D1 一致" if fl == C006_FLOORS else "✗ 不一致"))
    if fl != C006_FLOORS:
        fails.append("F C006 层段 %s ≠ %s" % (sorted(fl), sorted(C006_FLOORS)))

    print("\n===== 判词 =====")
    if fails:
        print("  FAIL  rc=1   未过项:", fails)
        rc = 1
    else:
        print("  PASS  rc=0   台账覆盖率 %.1f%%（%d/%d）；C109 %d=%d=%d 无拒配；"
              "对照①塌 0、对照② 单位 %d→%d；C006 层段与 11+D1 对上"
              % (cov, n_hit, len(seen), N_C109_ROOMS, N_C109_ROOMS, N_C109_ROOMS,
                 dn["n_unit"], du["n_unit"]))
        rc = 0
    print("  ★ 盲区：本条**只给覆盖率/配对数**，不给「台账正确」结论；也**不判**面积与「按列算的面积」"
          "吻不吻合（模型侧还没建，那一步本条不假装做了）（盲区②）")
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"pass": rc == 0, "full": full, "n_files": len(seen), "n_hit": n_hit,
                   "coverage_pct": cov, "cov_min": COV_MIN,
                   "c109": {"n_id": st.get("n_id"), "n_area_text": st.get("n_area_text"),
                            "n_joined": st.get("n_joined"), "n_far": st.get("n_far")},
                   "ctrl_shift": {"before": st0["n_joined"], "after": st1["n_joined"]},
                   "ctrl_unbound": {"unit_bounded": dn["n_unit"], "unit_unbounded": du["n_unit"],
                                    "use_bounded": dn["n_use"], "use_unbounded": du["n_use"]},
                   "c006_floors": sorted(fl), "fails": fails},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("  写出:", a.json)
    return rc


if __name__ == "__main__":
    sys.exit(main())
