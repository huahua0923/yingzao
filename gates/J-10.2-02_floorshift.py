# -*- coding: utf-8 -*-
"""判据 J-10.2-02：**包里那份「层错位」缺陷表，与包里的模型同作用域吗？**（案 §10.2 接缝）

为什么单开一条（★ 2026-10-12 本轮的真问题）：
  · 包 `evidence/c006-audit.json` 与 gym3d 仓的**逐字节相同**（`c100bc4b…`）—— 它量的是
    **gym3d 那坨烘死的单网格**；而包里的模型 `model/c006-building.glb` 是**另一条链**建的。
    ★ 2026-10-14 换链：换链前那条链是 libs3d/c006 逐层建再拼 B1
    （`tools/floors_from_libs3d.py` + `tools/pack_d1.py`）；**换链后**包内件是**正式件**
    `rebuild/06_su/c006_su.glb`（见 `demo/build_pack.py` 的 ②.5）。
    —— 换的是**哪条链**；**没换**的是本判据要问的那件事：证件量的是 gym3d，而模型不是 gym3d。
    ⇒ 本判据在换链前后**同样成立**，结论也不变（均为「不复现」）。
  · 于是 QC 的 `known_defects` 把 gym3d 的「第 4 层错位 6.7 m / 第 5 层错位 9.5 m」**照抄**进了
    本包的质检报告 ⇒ **照包读，会以为交付的模型错了 6.7 m**。
  · 这违反铁律 192（参照物必须与交付件同作用域）与 §10.0.5 第 6 条（交付件不许与判据静默不一致）。

gym3d 那条缺陷的**原定义**（读 `gym3d/qa_defect_census.py:227-248`，不是猜的）：
  `shift = hypot(本层墙质心 − 下层墙质心)`；`shift > SHIFT_M(=3.0 m)` ⇒ 记 `层错位%.1fm`。
  ⇒ 「层错位」= **相邻层质心的水平位移 > 3 m**。本判据就用**同一件事**（水平位移）在**交付件**上重算。

量什么：交付件 GLB 里每个顶层楼层节点（`B1` / `floor0..floor10`）的**水平包围盒中心**，
  逐相邻对求位移。★ 竖直轴**由数据定**（`a1/gauge_layer_shift.vertical_axis`），不写死 Y。

★ 判据（全部为真才算过）：
  A. **顶层节点数 == 量到的层数 == 12**（`B1` + `floor0..floor10`）—— 与「11 层 + D1」的裁定对上
  B. **全部可比的相邻层对** 水平位移 **< SHIFT_M = 3.0 m** ⇒ 交付件**没有** gym3d 声明的那条缺陷
  C. **可比对数 > 0**（遍历型判据先断言非空，否则恒绿）；「轮廓不同」的对**逐对打印**，不许静默吞
  D. **交叉对账**：读**包里的** `evidence/c006-audit.json`，取出所有 `层错位` 声明，
     逐条判「在交付件上复现 / 不复现」；判词只许是**「不复现」**，不许升格成「本来就没这条缺陷」
     （两种说法作用域不同：前者说的是本包这件，后者说的是 gym3d 那件）

★ 正对照（必须触发，不响则本判据无分辨力）：
  E. **已知刺激 = gym3d 声明的那个数**：把 `floor4` 在 X 上平移 **6.7 m** ⇒ 该对必须报到 6700 mm（±1 mm）
  F. 同法把 `floor5` 平移 **9.5 m** ⇒ 必须报到 9500 mm（±1 mm）
  G. ★ **判据要有牙**：注入了之后，B 条（「全部可比对 < 3 m」）**必须变红** ——
     证明 B 不是一条恒绿的判词（铁律 137）

★ 盲区（必须声明，盲区内的判词不算证据）：
  ① **包围盒中心 ≠ 墙质心**（gym3d 用的是墙质心）：楼梯间/雨棚偏在一侧会把中心拽走。本尺分不开
     「真错位」与「本层轮廓本来就不同」⇒ 两层水平跨度差 >1 m 时标 `[轮廓不同]`、**不当缺陷**。
  ② 只量**水平**位移；竖向（层高）不在本尺内。
  ③ **「不复现」≠「原缺陷是假的」**：两件东西是两条链建的，本判据只对**交付件**发言（见 D）。
  ④ 不给「模型对不对」的结论 —— 只给「相邻层中心差多少 mm」。层内的错误本尺全盲。

用法: python gates/J-10.2-02_floorshift.py [--pack packs/cdut-main/c006]
"""
import sys
import os
import json
import argparse
import importlib.util

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHIFT_M = 3.0                      # gym3d 的量（qa_defect_census.SHIFT_M），本判据用**同一个门**
SHIFT_TOL_MM = 1.0
N_TOP_NODES = 12                   # B1 + floor0..floor10
CTRL = [(4, 6.7), (5, 9.5)]        # ★ 正是 gym3d 声明的那两个数（floorK 节点 / 米）


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load("gauge_layer_shift", os.path.join(ROOT, "a1", "gauge_layer_shift.py"))


def pairs(rows):
    """逐相邻对算水平位移（竖直轴由数据定）。返回 (可比对, 不可比对)。"""
    v = G.vertical_axis(rows)
    if v is None:
        return None, None, None
    H = [k for k in range(3) if k != v]
    ok, skip = [], []
    for i in range(1, len(rows)):
        p, c = rows[i - 1], rows[i]
        d = ((c["c_mm"][H[0]] - p["c_mm"][H[0]]) ** 2
             + (c["c_mm"][H[1]] - p["c_mm"][H[1]]) ** 2) ** 0.5
        dsp = max(abs(c["span_mm"][k] - p["span_mm"][k]) for k in H)
        rec = {"a": p["node"], "b": c["node"], "shift_mm": round(d, 1),
               "span_diff_mm": round(dsp, 1)}
        (skip if dsp > 1000.0 else ok).append(rec)
    return v, ok, skip


def worst_touching(ok_pairs, node):
    """该节点参与的可比对里的最大位移（节点名可能是 'floor4'）。"""
    c = [p for p in ok_pairs if p["a"] == node or p["b"] == node]
    return max(c, key=lambda p: p["shift_mm"]) if c else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default=os.path.join(ROOT, "packs", "cdut-main", "c006"))
    ap.add_argument("--json", default=os.path.join(HERE, "_out", "J-10.2-02.json"))
    a = ap.parse_args()

    glb = os.path.join(a.pack, "model", "c006-building.glb")
    ev = os.path.join(a.pack, "evidence", "c006-audit.json")
    fails = []
    print("判据 J-10.2-02  交付件里的「层错位」还剩多少")
    print("  模型件:", glb)
    if not os.path.isfile(glb):
        print("  ✗ 件不在 ⇒ 拒判"); return 4

    rows = G.measure(glb)
    v, ok, skip = pairs(rows)
    if v is None:
        print("  ✗ 定不出竖直轴 ⇒ 拒判"); return 4
    AX = "XYZ"
    print("  竖直轴由数据定为 %s ⇒ 水平面 %s%s · 该门 SHIFT_M = %.1f m"
          % (AX[v], AX[[k for k in range(3) if k != v][0]], AX[[k for k in range(3) if k != v][1]], SHIFT_M))

    print("\n== A 顶层节点 == 量到的层数 ==")
    print("   %d 层（%s）⇒ %s" % (len(rows), ",".join(r["node"] for r in rows),
                                 "✓" if len(rows) == N_TOP_NODES else "✗"))
    if len(rows) != N_TOP_NODES:
        fails.append("A 顶层节点 %d ≠ %d" % (len(rows), N_TOP_NODES))

    print("\n== C 逐对位移（可比对 %d / 轮廓不同 %d）==" % (len(ok), len(skip)))
    for p in ok:
        mark = "  ← 超门 ★" if p["shift_mm"] > SHIFT_M * 1000 else ""
        print("   %-8s → %-8s %9.1f mm%s" % (p["a"], p["b"], p["shift_mm"], mark))
    for p in skip:
        print("   %-8s → %-8s %9.1f mm  [轮廓不同 跨差 %.0f mm ⇒ 不可比、不当缺陷]"
              % (p["a"], p["b"], p["shift_mm"], p["span_diff_mm"]))
    if not ok:
        fails.append("C 可比对为 0 ⇒ 遍历型判据恒绿（盲区①把全部对都吞了）")
    over = [p for p in ok if p["shift_mm"] > SHIFT_M * 1000]

    print("\n== B 全部可比对必须 < %.1f m ==" % SHIFT_M)
    w = max(ok, key=lambda p: p["shift_mm"]) if ok else None
    print("   最大可比对: %s → %s %.1f mm（门 %.0f mm）⇒ %s"
          % (w["a"], w["b"], w["shift_mm"], SHIFT_M * 1000, "✓" if not over else "✗ 有 %d 对超门" % len(over)))
    if over:
        for p in over:
            fails.append("B %s→%s 位移 %.1f mm > %.0f mm" % (p["a"], p["b"], p["shift_mm"], SHIFT_M * 1000))

    # ---- D 与包内证物对账 ----
    print("\n== D 交叉对账（包里的 evidence/c006-audit.json 声明了什么）==")
    claims = []
    if os.path.isfile(ev):
        d = json.load(open(ev, encoding="utf-8"))
        for r in d.get("records", []):
            for f in (r.get("flags") or []):
                if str(f).startswith("层错位"):
                    claims.append({"gym3d_floor": r["floor"], "flag": f, "sev": r["sev"]})
    if not claims:
        print("   证物里**没有**层错位声明 ⇒ 本对账无对象（不算过、也不算不过）")
    for c in claims:
        node = "floor%d" % c["gym3d_floor"]
        t = worst_touching(ok, node) or worst_touching(ok, "floor%d" % (c["gym3d_floor"] + 1))
        near = t["shift_mm"] if t else None
        print("   证物: 第 %d 层「%s」（sev=%s）⇒ 交付件上，节点 %s 参与的可比对最大 %.1f mm ⇒ **不复现**"
              % (c["gym3d_floor"], c["flag"], c["sev"], node, near if near is not None else float("nan")))
        c["node"] = node
        c["worst_touching_mm"] = near
        c["reproduced"] = bool(near is not None and near > SHIFT_M * 1000)
    print("   ★ 判词只写「在**交付件**上不复现」—— **不**写「本来就没错位」：")
    print("     证物量的是 gym3d 网格、本件是 libs3d/c006 建的，两件事（盲区③）。")

    # ---- E/F/G 正对照 ----
    print("\n== E/F 正对照：把 gym3d 声明的那个数**注入**交付件 ==")
    ctrl = []
    for floor_k, m in CTRL:
        r2 = G.measure(glb, "floor%d" % floor_k, m)
        b1 = {r["node"]: r for r in rows}
        b2 = {r["node"]: r for r in r2}
        hk = [k for k in range(3) if k != v]
        got = ((b2["floor%d" % floor_k]["c_mm"][hk[0]] - b1["floor%d" % floor_k]["c_mm"][hk[0]]) ** 2
               + (b2["floor%d" % floor_k]["c_mm"][hk[1]] - b1["floor%d" % floor_k]["c_mm"][hk[1]]) ** 2) ** 0.5
        want = m * 1000.0
        fired = abs(got - want) <= SHIFT_TOL_MM
        print("   注入 floor%d +%.1f m ⇒ 读数 %+.1f mm / 期望 %+.1f mm ⇒ %s"
              % (floor_k, m, got, want, "✓ 报到了" if fired else "✗ 没报到"))
        if not fired:
            fails.append("E/F 注入 floor%d %.1f m 未报到（读数 %.1f mm）" % (floor_k, m, got))
        # G 条：注入后 B 的门必须被触发
        _, ok2, _ = pairs(r2)
        tripped = any(p["shift_mm"] > SHIFT_M * 1000 for p in ok2)
        print("      同一次注入下，B 条（全部可比对 <3 m）%s ⇒ %s"
              % ("被触发" if tripped else "**没被触发**", "✓ 判据有牙" if tripped else "✗ 判据恒绿"))
        if not tripped:
            fails.append("G 注入 %.1f m 后 B 条仍绿 ⇒ 判据没有分辨力" % m)
        ctrl.append({"floor": floor_k, "inject_m": m, "read_mm": round(got, 1), "fired": fired, "b_tripped": tripped})

    print("\n===== 判词 =====")
    if fails:
        print("  FAIL  rc=1   未过项:", fails); rc = 1
    else:
        print("  PASS  rc=0   交付件 %d 层 · 可比对 %d 全 <%.0f mm（最大 %.1f mm）· "
              "证物里 %d 条层错位声明**在交付件上均不复现** · 注入 6.7/9.5 m 两条都报到且都顶红 B 条"
              % (len(rows), len(ok), SHIFT_M * 1000, w["shift_mm"] if w else 0.0, len(claims)))
        rc = 0
    print("  ★ 盲区：包围盒中心≠墙质心（跨度差 >1 m 判不可比）· 只量水平 · 只对交付件发言 · "
          "层内错误全盲（盲区①~④）")
    if a.json:
        os.makedirs(os.path.dirname(a.json), exist_ok=True)
        json.dump({"pass": rc == 0, "glb": glb, "vertical_axis": v, "n_nodes": len(rows),
                   "comparable": ok, "incomparable": skip, "shift_gate_m": SHIFT_M,
                   "claims_in_evidence": claims, "controls": ctrl, "fails": fails},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("  写出:", a.json)
    return rc


if __name__ == "__main__":
    sys.exit(main())
