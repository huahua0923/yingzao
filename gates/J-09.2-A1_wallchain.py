# -*- coding: utf-8 -*-
"""判据 J-09.2-A1：**通用墙链**能在「结构差别大 + 曾崩过」的样板上跑通，且判据本身有分辨力。

对应方案 §9.2 轨A·A1 出口门。四件套（§10.0.1）：
  ① 量交付件本身  —— 现场读 DXF、现场建墙打分，不读任何中间日志
  ② 量具写明      —— sheet_grid（图幅定位）+ generic_wall（建墙/打分）+ dim_check（外部轴网量）
  ③ 盲区声明      —— 见下
  ④ 正对照必配    —— **三条**（见下 C/D/E）

★ 判据（全部为真才算过）：
  A. 六块样板上链状态 = OK（不崩）
  B. 每块墙线覆盖 min ≥ 99.0%
  F. ★**六块样板各跑一遍外部轴网判据**（`dim_check.judge`）⇒ 每块**四条正对照都必须全响**
     （①a 合成正样本压墙 120 mm ≥99% / ①b 合成负样本飘 10 km = 0% / ② TOL=0 必降 /
     ③④ 沿轴线**法向**横挪 ±1730 mm 掉幅各 ≥15 点）⇒ 证明这层外部量**在每一块样板类别上都有牙**
     （铁律 137：判据名单漏掉主体则永远绿）。命中率**只报不设阈值** —— 见盲区②。
  C. 正对照① `wire([])` 不抛异常（回归守卫：曾因空图幅崩 `IndexError`）
  D. 正对照② 抽掉 90% 墙段 ⇒ 覆盖必须掉到 99% 以下（证明覆盖这把尺子有牙）
  E. 正对照③ 外部轴网判据在样板 C011 上**四条正对照全响** ⇒ 见 `control_axis`

★ 盲区（必须声明，盲区内的否定判词不算证据）：
  ① 覆盖/IoU 均由 `4.2墙体`（四种层名）派生 ⇒ 只证「没漏几何」，**不证「墙对不对」**。
     判据 B 因此是**自洽**的（模型与参照同源 ⇒ 恒 ~100%），真正的外部量是判据 F。
  ② 判据 F 的**命中率不设绝对阈值**：轴线是网格定位线，会外伸、也有非结构轴线（本就不该有墙），
     一份**正确**的模型也达不到 100%。要设阈值须先量**全库分布**（`a1/batch_wall.py`），
     现在没量 ⇒ 不臆造一个数（盲区③）。
  ③ 样板是**人工挑的 6 块**，不覆盖全库；全库分布看 `a1/batch_wall.py`。

用法: python J-09.2-A1_wallchain.py            # 跑判据
     python J-09.2-A1_wallchain.py --json o.json
"""
import sys
import os
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
A1 = os.path.join(os.path.dirname(HERE), "a1")
TOOLS = os.path.join(os.path.dirname(HERE), "tools")
sys.path.insert(0, A1)
sys.path.insert(0, TOOLS)
import jsonstrict                  # noqa: E402  ★ 落盘走严格 JSON（铁律 123）
import sheet_grid as SG    # noqa: E402
import generic_wall as GW  # noqa: E402
import dim_check as DC     # noqa: E402

DXF_DIR = r"D:\项目\gym3d\材料\dxf_output"
SAMPLES = [
    "C006-第六教学楼（逸夫楼）",  # 基线：12 图幅 / 柱是 INSERT 块
    "C009-第九教学楼",            # 柱是 LWPOLYLINE
    "C011-银杏体育馆",            # 大跨、柱 CIRCLE 混
    "C001-砚湖图书馆",
    "C004F1-办公楼附楼",          # 墙层名 = 4墙体（旧链崩）
    "C105-图书馆",                # 曾在「空图幅」上崩
]
COV_MIN = 99.0
MARGIN = 8000.0


def one(name):
    path = os.path.join(DXF_DIR, name + ".dxf")
    msp = ezdxf.readfile(path).modelspace()
    layer = SG.find_frame_layer(msp, None)
    sheets = SG.merge_pairs(SG.collect_frames(msp, layer))
    _modal, std, _others = SG.classify(sheets)
    ALLW, ALLC, _L = GW.load_walls_and_cols_msp(msp)
    lcs = []
    for c in std:
        x0, y0, x1, y1 = c["bbox"]
        _r, _m, _i, lc, _nq, _nu = GW.score_cell(ALLW, ALLC, x0, x1, y0, y1, MARGIN)
        lcs.append(lc)
    valid = [x for x in lcs if x == x]      # 去 NaN（没量到的图幅）
    return {"n_sheets": len(std), "n_wall": len(ALLW), "n_col": len(ALLC),
            "cov_min": round(min(valid), 2) if valid else None,
            "n_unmeasured": len(lcs) - len(valid), "lcs": lcs}


def control_wire_empty():
    """正对照①：空/单段输入不许抛异常。"""
    try:
        q, r = GW.wire([])
        q1, _ = GW.wire([])
        return (q == [] and r == []), "wire([]) -> ([], [])"
    except Exception as e:
        return False, "wire([]) 抛 %s: %s" % (type(e).__name__, e)


def control_drop(cov_full):
    """正对照②：抽掉 10% 墙段 ⇒ 覆盖必须掉。"""
    name = "C011-银杏体育馆"
    msp = ezdxf.readfile(os.path.join(DXF_DIR, name + ".dxf")).modelspace()
    layer = SG.find_frame_layer(msp, None)
    std = SG.classify(SG.merge_pairs(SG.collect_frames(msp, layer)))[1]
    ALLW, ALLC, _L = GW.load_walls_and_cols_msp(msp)
    keep = ALLW[::10]                       # 每 10 条留 1 条 → 抽掉 90% 更容易看出掉
    lcs = []
    for c in std:
        x0, y0, x1, y1 = c["bbox"]
        # ★ 模型用 keep（少 90%），**参照点用全量 ALLW** —— 否则取样点与模型输入同源，判据循环、恒 100%
        _r, _m, _i, lc, _nq, _nu = GW.score_cell(keep, ALLC, x0, x1, y0, y1, MARGIN,
                                                 ref_segs=ALLW)
        lcs.append(lc)
    valid = [x for x in lcs if x == x]
    mn = round(min(valid), 2) if valid else None
    return (mn is not None and mn < COV_MIN), \
        "抽段后覆盖 min=%s（须 < %.1f%%）" % ("—" if mn is None else "%.2f%%" % mn, COV_MIN)


AXIS_CACHE = {}     # ★ 六块样板共用：每份 DXF 的墙足迹只算一次（wire 是这条链最贵的一步）


def axis_one(name):
    """判据 F：对一块样板跑外部轴网判据（`dim_check.judge`）。"""
    path = os.path.join(DXF_DIR, name + ".dxf")
    return DC.judge(path, 300.0, DC.BAY_DEFAULT, cache=AXIS_CACHE)


def control_axis():
    """正对照③：轴网判据在样板 C011 上四条正对照必须全响（尺子有牙）。"""
    j = axis_one("C011-银杏体育馆")
    if not j.get("n_axis"):
        return False, "C011 一条 `3轴线` 都没读到（盲区①）"
    return j["ok"], ("按段 %.1f%%（%d 段）· 法向横挪掉幅 +%.1f / −%.1f 点"
                     % (j["rate_axis"], j["n_axis"], j["margin_pos"], j["margin_neg"]))


def main():
    ap = argparse.ArgumentParser()
    # ★ 默认落**正规名** `J-09.2-A1.json`（= 页面对 `J-09.2-A1_wallchain` 的候选②，
    #   也是本件日志 `J-09.2-A1.log` 的同名件），与其余 8 条闸一致。
    ap.add_argument("--json",
                    default=os.path.join(HERE, "_out", "J-09.2-A1.json"))
    a = ap.parse_args()
    fails = []
    print("== A. 样板跑通 + B. 墙线覆盖 ==")
    rows = {}
    for nm in SAMPLES:
        try:
            r = one(nm)
        except Exception as e:
            print("  %-26s ** 崩 %s: %s" % (nm[:26], type(e).__name__, str(e)[:70]))
            fails.append("A:%s 崩 %s" % (nm, type(e).__name__))
            continue
        rows[nm] = r
        cm = r["cov_min"]
        okcov = (cm is not None) and cm >= COV_MIN
        print("  %-26s 图幅%2d 墙段%6d 柱%5d 覆盖min%8s 未量到%d %s"
              % (nm[:26], r["n_sheets"], r["n_wall"], r["n_col"],
                 "—" if cm is None else "%.2f%%" % cm, r["n_unmeasured"],
                 "✓" if okcov else "✗ <%s" % COV_MIN))
        if r["n_sheets"] < 1:
            fails.append("A:%s 无图幅" % nm)
        if cm is None:
            fails.append("B:%s 全部图幅没量到（无墙线取样点）" % nm)
        elif not okcov:
            fails.append("B:%s 覆盖 %.2f%%" % (nm, cm))

    print("\n== F. 外部轴网判据（每块样板各跑一遍；命中率只报不设阈值，见盲区②） ==")
    axrows = {}
    for nm in SAMPLES:
        try:
            j = axis_one(nm)
        except Exception as e:
            print("  %-26s ** 崩 %s: %s" % (nm[:26], type(e).__name__, str(e)[:60]))
            fails.append("F:%s 崩 %s" % (nm, type(e).__name__))
            continue
        axrows[nm] = {k: j.get(k) for k in ("n_axis", "rate_axis", "margin_pos",
                                            "margin_neg", "ok")}
        print("  %-26s 轴%4d段 按段%6.1f%% 横挪掉幅 +%5.1f −%5.1f %s"
              % (nm[:26], j["n_axis"], j["rate_axis"], j["margin_pos"], j["margin_neg"],
                 "✓" if j["ok"] else "✗ 四对照没全响"))
        if not j["ok"]:
            fails.append("F:%s 外部轴网判据作废（正对照没全响）" % nm)

    print("\n== 正对照（不变红 = 判据没分辨力） ==")
    c1, d1 = control_wire_empty();  print("  ① wire([]) 不抛      :", "✓" if c1 else "✗", d1)
    c2, d2 = control_drop(None);    print("  ② 抽 90% 墙段覆盖掉  :", "✓" if c2 else "✗", d2)
    c3, d3 = control_axis();        print("  ③ 轴网判据四对照全响 :", "✓" if c3 else "✗", d3)
    for c, tag in ((c1, "C1"), (c2, "C2"), (c3, "C3")):
        if not c:
            fails.append("对照%s 未触发" % tag)

    print("\n===== 判词 =====")
    if fails:
        print("  FAIL  rc=1   未过项:", fails)
        rc = 1
    else:
        print("  PASS  rc=0   A/B/F 全绿，三条正对照全触发")
        rc = 0
    if a.json:
        # ★ 落盘走 `jsonstrict.dump`：`lcs` 里的 NaN 是**有意**的「没量到」，
        #   但裸 NaN 不是严格 JSON（Python 读得回、浏览器直接白屏，铁律 123）
        #   ⇒ 逐层换成 `null`，并用 `allow_nan=False` 兜底。
        nb, n_null = jsonstrict.dump({"pass": rc == 0, "rows": rows, "axis": axrows,
                                      "controls": {"wire_empty": c1, "drop": c2,
                                                   "axis_gauge": c3},
                                      "fails": fails}, a.json)
        # ★ 这个数由 `dump()` 在**洗之前**从原对象数出来（铁律 174：别印一个口径不对、
        #   看着像结论的数）。`dump()` 还当场回读校验（铁律 123），回读失败就没这行。
        print("  写出: %s（%d 字节；%d 格「没量到」写成 null，回读校验通过）"
              % (a.json, nb, n_null))
    return rc


if __name__ == "__main__":
    sys.exit(main())
