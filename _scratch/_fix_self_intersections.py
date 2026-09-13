# -*- coding: utf-8 -*-
r"""修 `floors/floor*.json` 里**自交**的房间多边形（唯一所有者）。

为什么要有这个（实测，不是猜）：
  · 全库 `floors/` 的房间多边形里 **558 个自交（is_valid=False）、分布在 21 栋**
    （c017 250 / c059 72 / c034 48 / c006 51 / c032 36 / c104 20 / c009 17 / c080 17 /
     ny27 12 / c103 11 / c033 8 / c027 7 …；逐间明细见 `_scratch/_probe_selfint_refused.py`）。
  · 后果分两种：
    ① **拦管道**：SU 分层建模的 spec 要判「每块地垫唯一落在哪间房」，用 GEOS 求差集/对称差；
       自交多边形会让 GEOS 抛 `TopologyException: side location conflict`。
       全库只有 c103 恰好撞上（第 2 层房间 `103-A-03-02`），其余 20 栋**现在是通过的**——
       所以判据侧不能"非法即拦"（那是 21 栋大回归），只能在这一层把数据修对。
    ② **几何本身不合法**：交付的 floors 是房间边界**唯一几何源**（网页查看器、导航、SU 都读它），
       自交意味着这个"房间"的边界是自己扎自己的，面积/包含关系都不可信。
  · 修法为什么是 `buffer(0)`：GEOS 的标准"清洗"算子，把自交（细刺、自触、8 字）解成合法的
    （多）多边形。**它会改几何**，所以本脚本逐间报**面积差**。

判据（宁可不改也不改错）：
  ① `buffer(0)` 为空 ⇒ 那**一间**保留原样（说明这个多边形已经不是面了）。
  ② **只有"区域逐点不变"才允许改**：判据是
     `written.symmetric_difference(buffer(0)).area <= REGION_TOL`（默认 1e-6 m²），
     其中 `written` 是**真正要落盘的那条环**（见 ③）。过不了就保留原样、进"保住不改"清单。
     ⇒ 本脚本对已通过建筑的几何是**可证零影响**的：改完的房间区域与改前逐点相同，
       只是从"非法环"变成"合法环"（自触点被拆开）。
  ②′ **人工批准的例外**（`REGION_CHANGE_OK` + `--allow-region-change`）：②拦下的房间里，
     若**有人明确拍板**接受这点几何损失，可逐间列入下表放行。三条硬约定，缺一不放行：
       · 例外表按 **(栋, 层文件, 房号)** 逐条列 —— 不放宽判据，只开一个具名口子；
       · 表里记着**实测损失量**，跑的时候要**对上**（`LOSS_TOL`）—— 数据一变就中止，
         免得"当初批的是 0.3 m²、后来变成 3 m²"没人发现；
       · 必须显式加 `--allow-region-change`，默认一律按 ② 走。
     ★ 2026-09-13 批准（用户拍板"修满 11 间"）：c103 是全库唯一没过 SU 规格闸门的栋，
       实测卡点就是 F2/F3/F4 的 A 翼 `103-A-0N-02`（各 3455.33 m²）自交 ——
       只修其余 8 间（区域不变那批）c103 **仍然红**，修满 11 间才绿。
       代价：每层丢一块 0.3455 m² 的小叶（A 翼末端 (-80.5, 10.3)，与主体仅隔 0.03 m，
       不落在任何别的房间里，修完该处成为地板空洞；占该房 0.01%）。
  ③ **交付格式 `poly` 只有单个外环，表达不了孔** ⇒ `interiors` 非空的**一律不改**。
     并且**只量要落盘的那条环**，不再量 `main_p` —— 杜绝"量一个、写另一个"。
     ★ 2026-09-13 判例（这就是 ② 不能用"面积差 < 1%"的原因）：
       c006/floor1 #31 `6-C-02-05` 的 `buffer(0)` 最大块**带 1 个孔**，
       `.area`=694.5681（已扣孔）而外环 shoelace=**1036.1174**。旧版写的是
       `main_p.exterior.coords` ⇒ **量了 694.5681、写了 1036.1174（+48.7%）**，
       而 1% 面积守卫照旧放行；填掉的孔 341.5493 m² 里正是
       `6-C-02-03` 整间（124.2560）+ `6-C-02-04`（49.1226）—— 等于让一间房盖住两间房。
  ④ `buffer(0)` 出多块 ⇒ 取**最大块**，并标出**丢掉的块数与面积**（不隐瞒）。
     注意 ② 会让"丢块"的房间直接进"保住不改"（丢块 = 区域变了）。
  ⑤ 房间**条数**必须不变（本脚本只换 `poly`，不增不删）。
  ⑥ **逐间跳过，不整层跳过**：这一间不动，同一层其余自交房间照样修。
     （整层跳过会让 c006 另外 19 间能安全修的也一起被丢下，且"全库修完"这句话会盖住它。）
  ⑦ **行尾与缩进照原文探测，不统一改写** —— 包括"原文本来是紧凑单行"这种：
     `read_indent` 返回 `None` 时按紧凑写回。（旧版在单行文件上探测失败后**静默**取
     `indent=1`，把 62 个交付层文件整成缩进版 +18 MB，见 `read_indent` 的注释。）

"保住不改"里另有一类**自相吞并**型（`Ring Self-intersection`，4 层同型）：
  buffer(0) 取最大块等于把房间砍掉 27%~49%（`6-C-08-01` 343.25→174.93）。
  实测 c006 11 间 / c041 1 间 —— 自动改就是**自动丢房间**，只能交人工。

用法：
  python _scratch/_fix_self_intersections.py                 # 全库只报（默认）
  python _scratch/_fix_self_intersections.py --apply         # 全库备份后改写
  python _scratch/_fix_self_intersections.py c103 ny27 --apply
备份：`data/buildings/<name>/.orig/floors.before_selfint/floor*.json`（已存在则不覆盖）。
写盘：先写 `.tmp` 再 `os.replace`（原子）。
"""
import argparse
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
BUILDINGS = os.path.join(ROOT, "data", "buildings")
from shapely.geometry import Polygon        # noqa: E402
from shapely.validation import explain_validity  # noqa: E402

REGION_TOL = 1e-6       # 修后区域与 buffer(0) 的**对称差上限**（m²）
#                        只允许"区域逐点不变"的清洗；任何真改几何的一律交人工（见 ②）
LOSS_TOL = 5e-4         # 例外房间的**实测损失量**与下表记录值的允许偏差（m²）

# ★ 人工批准的例外（见 docstring ②′）。**不放宽判据，只开具名口子**：
#   key = (栋, 层文件名, 房号)，value = 实测对称差（m²，跑的时候要对上）。
REGION_CHANGE_OK = {
    ("c103", "floor2.json", "103-A-03-02"): 0.345510,
    ("c103", "floor3.json", "103-A-04-02"): 0.345510,
    ("c103", "floor4.json", "103-A-05-02"): 0.345510,
}


def read_indent(raw):
    """照原文探测缩进；**紧凑单行**返回 `None`（`json.dumps` 的默认分隔符就是原文那种）。

    `raw` 是 **bytes**（`open(fp,"rb").read()`）—— 模式必须也是 bytes，
    否则 `TypeError: cannot use a string pattern on a bytes-like object`。

    ★ 2026-09-13 判例（本文件自己的错）：旧版是 `rb'\\n(\\s+)"'`，在**单行文件**上匹配不到，
    于是 `return 1` —— **静默把紧凑 JSON 整成缩进版**：62 个交付层文件 19.4 MB → 35.9 MB
    （×1.85），语义没变但格式全变、行数 0 → 7 万行。**"匹配不到" ≠ "缩进是 1"，
    也可能是根本没有缩进**；格式探测失败时的正确动作是**别动格式**，不是挑一个默认值。
    另一处同型：`( *)` 而不是 `(\\s+)` —— 否则 indent=0 的多行文件会被悄悄"补"上缩进。
    """
    if b"\n" not in raw:
        return None
    m = re.search(rb'\n( *)"', raw)
    return len(m.group(1)) if m else 1


def read_newline(raw):
    """照原文探测行尾（本仓 profile.json 出过 CRLF/LF 混杂的坑，不统一改写）。"""
    return "\r\n" if b"\r\n" in raw else "\n"


def pick(name):
    base = os.path.join(BUILDINGS, name)
    fd = os.path.join(base, "floors")
    return base, fd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="排除的栋（按名）—— 例如 c103 的房间嵌套处置未定，先不动")
    ap.add_argument("--apply", action="store_true", help="真写盘（默认只报）")
    ap.add_argument("--allow-region-change", action="store_true",
                    help="放行 REGION_CHANGE_OK 里逐条列明的人工例外（默认一律按②走）")
    a = ap.parse_args()

    names = a.names
    if not names:
        names = sorted(n for n in os.listdir(BUILDINGS)
                       if os.path.isdir(os.path.join(BUILDINGS, n, "floors")))
    if a.exclude:
        names = [n for n in names if n not in set(a.exclude)]
        print("[排除] %s\n" % " ".join(sorted(a.exclude)))

    n_bld = n_flr = n_room = 0
    a_before = a_after = 0.0
    kept_back = []          # 逐间**保住不改**（超限 / 空面），必须报出来
    approved = []           # 走例外表放行的（**改了区域**，必须单独报，不许混进"零影响"那批）
    for name in names:
        base, fd = pick(name)
        if not os.path.isdir(fd):
            print("✗ %s 没有 floors/ 目录" % name)
            continue
        files = sorted(f for f in os.listdir(fd)
                       if f.startswith("floor") and f.endswith(".json"))
        plan = []       # (fn, raw, doc, 可修清单, 保住清单)
        for fn in files:
            fp = os.path.join(fd, fn)
            raw = open(fp, "rb").read()
            doc = json.loads(raw.decode("utf-8"))
            rooms = doc.get("rooms") or []
            todo, kept = [], []
            for i, r in enumerate(rooms):
                g = Polygon(r["poly"])
                if g.is_valid:
                    continue
                why = explain_validity(g)[:50]
                b = g.buffer(0)
                if b.is_empty:
                    kept.append((i, r.get("number"), g.area, None,
                                 "buffer(0) 是空面（已不是面）"))
                    continue
                parts = list(b.geoms) if b.geom_type == "MultiPolygon" else [b]
                main_p = max(parts, key=lambda q: q.area)
                lost = sum(q.area for q in parts) - main_p.area
                # ★ 「写什么就量什么」：交付 `poly` 只有**一个外环**，表达不了孔。
                #   所以先把**真正要落盘的那条环**造出来，此后一律量它。
                #   （量 main_p.area 会漏掉孔：2026-09-13 判例见模块 docstring ③。）
                written = Polygon([[round(x, 9), round(y, 9)]
                                   for x, y in main_p.exterior.coords])
                if main_p.interiors:
                    kept.append((i, r.get("number"), g.area, written.area,
                                 "修后带 %d 个孔（合计 %.4f m²）—— 交付 `poly` 只有单个外环，"
                                 "填孔会盖住别人，交人工"
                                 % (len(main_p.interiors),
                                    sum(Polygon(h).area for h in main_p.interiors))))
                    continue
                sd = written.symmetric_difference(b).area
                if sd > REGION_TOL:
                    ok = (a.allow_region_change
                          and (name, fn, str(r.get("number"))) in REGION_CHANGE_OK)
                    if ok:
                        rec = REGION_CHANGE_OK[(name, fn, str(r.get("number")))]
                        if abs(sd - rec) > LOSS_TOL:
                            kept.append((i, r.get("number"), g.area, written.area,
                                         "例外表放行的损失量对不上：表里记 %.6f、"
                                         "实测 %.6f（>%.0e）—— 数据变了，**中止不写**，"
                                         "重新量过再拍板" % (rec, sd, LOSS_TOL)))
                            continue
                        todo.append((i, r.get("number"), g.area, written.area,
                                     len(parts), lost, why, written))
                        approved.append((fn, i, r.get("number"), sd, g.area, written.area))
                        continue
                    kept.append((i, r.get("number"), g.area, written.area,
                                 "修后区域变了 %.6f m²（>%.0e）—— 不只是拆自触点，"
                                 "是真改几何（丢块 %.4f m²），交人工"
                                 "%s" % (sd, REGION_TOL, lost,
                                         "（在例外表里，但没加 --allow-region-change）"
                                         if (name, fn, str(r.get("number"))) in REGION_CHANGE_OK
                                         else "")))
                    continue
                todo.append((i, r.get("number"), g.area, written.area,
                             len(parts), lost, why, written))
            for i, num, oa, na, why in kept:
                kept_back.append("%s/%s #%d %s：%s" % (name, fn, i, num, why))
            if todo:
                plan.append((fn, raw, doc, todo, kept))

        if not plan:
            continue
        print("=== %s ===" % name)
        for fn, raw, doc, todo, kept in plan:
            print("  %s %s 自交 %d 间（本层另 %d 间保住不改）"
                  % ("✎" if a.apply else "·", fn, len(todo), len(kept)))
            for i, num, oa, na, _np, _lost, why, _w in todo:
                print("      #%-3d %-14s %9.4f → %9.4f （%+.3f m²）  %s"
                      % (i, num, oa, na, na - oa, why))
            n_flr += 1
            n_room += len(todo)
            a_before += sum(t[2] for t in todo)
            a_after += sum(t[3] for t in todo)
            for i, _num, _oa, _na, _np, _lost, _why, written in todo:
                doc["rooms"][i]["poly"] = [[round(x, 9), round(y, 9)]
                                           for x, y in written.exterior.coords]
            # ★ 无论是否 --apply，都把**待写内容构造一遍**（不写盘）。
            #   理由：dry-run 必须真的跑过写盘那条路，否则 read_indent / read_newline /
            #   json.dumps 这一串只在 apply 时才**首次**执行 —— 2026-09-13 正是这个缺口，
            #   让 read_indent 的 bytes/str 不匹配在 dry-run 全绿之后于 apply 首跑崩掉。
            out = json.dumps(doc, ensure_ascii=False, indent=read_indent(raw))
            out = out.replace("\n", read_newline(raw)) if read_newline(raw) == "\r\n" else out
            if not a.apply:
                continue
            bk = os.path.join(base, ".orig", "floors.before_selfint")
            os.makedirs(bk, exist_ok=True)
            dst = os.path.join(bk, fn)
            if not os.path.exists(dst):
                with open(dst, "wb") as f:
                    f.write(raw)
            tmp = os.path.join(fd, fn) + ".tmp"
            with io.open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(out)
            os.replace(tmp, os.path.join(fd, fn))
        n_bld += 1

    ok_b = sum(t[4] for t in approved)          # 例外那几间**改前**面积
    ok_a = sum(t[5] for t in approved)          # 例外那几间**改后**面积
    print("\n合计：%d 栋 / %d 层 / %d 间房修自交" % (n_bld, n_flr, n_room))
    print("      · 零影响（区域逐点不变）%d 间，面积 %.4f → %.4f m²（%+.4f，%+.4f%%）"
          % (n_room - len(approved), a_before - ok_b, a_after - ok_a,
             (a_after - ok_a) - (a_before - ok_b),
             100 * ((a_after - ok_a) - (a_before - ok_b)) / (a_before - ok_b)
             if a_before - ok_b else 0))
    if approved:
        print("      · 例外放行（区域真变）  %d 间，面积 %.4f → %.4f m²（%+.4f m²）"
              % (len(approved), ok_b, ok_a, ok_a - ok_b))
        print("\n⚠ 走例外表放行的 %d 间（**区域真变了**，人工拍板过的，别当零影响）：" % len(approved))
        for fn, i, num, sd, ob, oa in approved:
            print("   %s #%d %s：对称差 %.6f m²（%.4f → %.4f）" % (fn, i, num, sd, ob, oa))
    if kept_back:
        print("\n✗ 保住不改的 %d 间（宁可不改也不改错，**需人看**）：" % len(kept_back))
        for r in kept_back:
            print("   %s" % r)
    print("\n%s" % ("已写盘" if a.apply else "未写盘（加 --apply 才写）"))


if __name__ == "__main__":
    main()
