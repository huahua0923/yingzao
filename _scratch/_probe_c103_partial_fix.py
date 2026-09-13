# -*- coding: utf-8 -*-
r"""c103：「只修那 8 间（区域逐点不变）」够不够让 SU 规格闸门变绿？（**只读，不碰 data/**）

为什么问这一句：
  2026-09-13 自交修复收紧成「只允许区域逐点不变」后，c103 的 11 间里
  **8 间可安全修**（`103-A-0N-04`/`05`，218.3050→218.3050，+0.000 m²），
  **3 间保住了**（A 翼 `103-A-0N-02`，各"修后区域变了 0.3455 m²"）。
  而 c103 是全库**唯一没通过**普查的栋。所以现在必须回答：
    · 那 3 间（区域会变）**是否真的是闸门卡住的原因**？
    · 如果只修 8 间就能过 ⇒ 那 3 间根本不必动，"区域变 0.3455"这件事压根不用请人拍板。
    · 如果只修 8 间仍红 ⇒ 卡点确实在 A 翼 `*02`，那才是需要人工定夺的那一条。

怎么做（三情形对照，全部跑在**临时副本**上）：
  ① `原样`    —— 完全不修，预期**红**（这是"闸门当前是红的"的控制组，防下面两格是空断言）
  ② `修 8 间` —— 用**生产修复脚本本体**（不是抄一遍规则）跑在副本上
  ③ `修满 11` —— ②之后再对残余非法环手工 `buffer(0)` 取最大块外环（=旧版行为）作**阳性对照**
  判据 = `su_spec_floors_fleet.main()` 的返回值（0 通过 / 1 不通过）+ 抛出的异常文本。
  ①必须红、③必须绿，②才是有效答案（否则说明探针没测到真东西）。

两条硬约定：
  · 三情形用**同一个 `-o` 路径名**——`name` 字段派生自 `-o` 文件名，路径一变就不可比（README 铁律 ⑮）。
  · 修 8 间那一步**不是重写判据**，是把 `_fix_self_intersections.py` 的 `BUILDINGS` 猴补到副本上
    调它的 `main()` —— 规则只有一处实现，不存在"探针抄错一版、两边一起错"。

用法：python _scratch/_probe_c103_partial_fix.py
"""
import importlib
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
SRC = os.path.join(ROOT, "data", "buildings", "c103")
TMP = os.path.join(ROOT, "_scratch", "_qa_selfint", "tmp_c103_partial")
OUT = os.path.join(TMP, "_c103_floors_spec.json")      # ★ 三情形同一个 out 名（见 docstring）
ERRLOG = os.path.join(ROOT, "_scratch", "_qa_selfint", "c103_gate_errors.txt")
for p in (os.path.join(ROOT, "backend", "modeling"), os.path.join(ROOT, "_scratch")):
    if p not in sys.path:
        sys.path.insert(0, p)

from shapely.geometry import Polygon                     # noqa: E402


def stage():
    """把 c103 的输入文件复制到临时副本（GLB / 图纸 / 备份一律不搬）。

    ★ 必须带上 `spec.json`：闸门读的是 `G.load_spec()`（= `DATA/spec.json`），
      不是 `profile.json`；缺了它会**静默**落进 `load_spec` 的硬编码兜底（那份兜底
      **没有 `style`**），于是所有墙拿到 `hex_to_rgb(None)`=`#888888`、门拿到默认
      `#8a5a38`，`_categorize` 报「9376 个部件的颜色不在构件类别表里」——
      本探针第一版正是这么把自己的失败当成了 c103 的失败（2026-09-13 判例）。
    """
    shutil.rmtree(TMP, ignore_errors=True)
    dst = os.path.join(TMP, "c103")
    os.makedirs(dst)
    shutil.copytree(os.path.join(SRC, "floors"), os.path.join(dst, "floors"))
    for f in ("rooms.json", "profile.json", "spec.json"):
        p = os.path.join(SRC, f)
        if not os.path.isfile(p):
            raise SystemExit("✗ 源目录缺 %s —— 闸门读它，缺了会静默落进兜底（见 docstring）" % f)
        shutil.copy2(p, os.path.join(dst, f))
    # ★ 硬守卫：把「副本是不是真的带着这份 style」量出来（量真正要用的那件东西）
    st = (json.load(io.open(os.path.join(dst, "spec.json"), encoding="utf-8"))
          .get("style") or {})
    need = ("facade", "inner", "roof", "parapet", "door")
    gone = [k for k in need if not st.get(k)]
    if gone:
        raise SystemExit("✗ 副本 spec.json 的 style 缺 %s —— 跑出来的红不是被测对象的红" % gone)
    return dst


def invalid_now():
    """副本里当前还有几间非法，逐间列号（用来证明"修了几间"不是嘴上说说）。"""
    fd = os.path.join(TMP, "c103", "floors")
    out = []
    for fn in sorted(f for f in os.listdir(fd)
                     if f.startswith("floor") and f.endswith(".json")):
        d = json.load(io.open(os.path.join(fd, fn), encoding="utf-8"))
        for i, r in enumerate(d.get("rooms") or []):
            if not Polygon(r["poly"]).is_valid:
                out.append((fn, i, r.get("number")))
    return out


def fix_with_production_fixer():
    """调**生产脚本本体**跑在副本上（猴补 BUILDINGS，不改 data/）。"""
    mod = importlib.import_module("_fix_self_intersections")
    mod.BUILDINGS = TMP
    old = sys.argv
    sys.argv = ["_fix_self_intersections", "c103", "--apply"]
    try:
        mod.main()
    finally:
        sys.argv = old


def force_fix_rest():
    """阳性对照用：残余非法环手工 buffer(0) 取最大块外环（= 收紧前那版行为）。"""
    fd = os.path.join(TMP, "c103", "floors")
    n = 0
    for fn in sorted(f for f in os.listdir(fd)
                     if f.startswith("floor") and f.endswith(".json")):
        fp = os.path.join(fd, fn)
        d = json.load(io.open(fp, encoding="utf-8"))
        hit = False
        for r in (d.get("rooms") or []):
            g = Polygon(r["poly"])
            if g.is_valid:
                continue
            b = g.buffer(0)
            parts = list(b.geoms) if b.geom_type == "MultiPolygon" else [b]
            m = max(parts, key=lambda q: q.area)
            r["poly"] = [[x, y] for x, y in m.exterior.coords]
            hit = True
            n += 1
        if hit:
            io.open(fp, "w", encoding="utf-8").write(
                json.dumps(d, ensure_ascii=False, indent=2))
    return n


def run_gate():
    """跑规格闸门本体，返回 (rc, 异常文本)。"""
    fleet = importlib.import_module("su_spec_floors_fleet")
    fleet.building_dir = lambda name: os.path.join(TMP, name)   # ★ 只改这一处解析
    old = sys.argv
    sys.argv = ["su_spec_floors_fleet", "c103", "-o", OUT]
    try:
        return fleet.main(), ""
    except Exception as e:                                       # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, str(e))
    finally:
        sys.argv = old


def main():
    print("=== c103 三种情形对照（全部在临时副本 %s 上）===" % TMP)
    rows = []
    for tag, prepare in (("① 原样（控制组，预期红）", None),
                         ("② 只修 8 间（区域逐点不变）", fix_with_production_fixer),
                         ("③ 修满 11 间（阳性对照，预期绿）", fix_with_production_fixer)):
        stage()
        inv0 = invalid_now()
        note = ""
        if prepare:
            prepare()
            if tag.startswith("③"):
                note = "，再手工 buffer(0) 补修 %d 间" % force_fix_rest()
        inv1 = invalid_now()
        rc, err = run_gate()
        verdict = "✓ 绿" if rc == 0 else ("✗ 红（rc=%s）" % rc if rc is not None else "✗ 抛异常")
        rows.append((tag, len(inv0), len(inv1), verdict, err))
        print("\n--- %s ---" % tag)
        print("    非法环 %d 间 → %d 间%s" % (len(inv0), len(inv1), note))
        if inv1:
            print("    残余：%s" % ", ".join("%s #%d %s" % t for t in inv1))
        print("    闸门：%s" % verdict)
        if err:
            print("    %s" % err)

    # ★ 报错原文落盘（终端会把中文/长 Counter 压掉，判据必须看全文）
    with io.open(ERRLOG, "w", encoding="utf-8") as f:
        for tag, a, b, v, e in rows:
            f.write("=== %s ===\n非法 %d→%d  闸门 %s\n%s\n\n" % (tag, a, b, v, e or "(无异常)"))
    print("\n（三种情形的报错原文：%s）" % ERRLOG)

    print("\n=== 结论 ===")
    for tag, a, b, v, _e in rows:
        print("  %-28s 非法 %2d→%2d  %s" % (tag, a, b, v))
    ctl = rows[0][3].startswith("✗") and rows[2][3].startswith("✓")
    print("\n  对照组有效（①红且③绿）：%s" % ("是" if ctl else "**否 —— 本探针无效，别采信 ②**"))
    if ctl:
        print("  ②%s ⇒ %s" % (
            "绿" if rows[1][3].startswith("✓") else "红",
            "只修那 8 间就够，A 翼 3 间**不必动**"
            if rows[1][3].startswith("✓") else
            "卡点确实在 A 翼 `103-A-0N-02`（那 3 间），需人工定夺"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
