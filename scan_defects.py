# -*- coding: utf-8 -*-
"""缺陷扫描 scan_defects.py —— 把「哪里不对」变成一张可点的清单（**只读 data/**）。

为什么要有它
------------
仓库里的门禁各测各的，谁都没有把结果送到**图上**：
  * `qa_structural.py` 有 I1–I18，判据硬、带 `pos`，但只落 `_qa/<楼>_qa.txt`（纯文本，
    不看图对不上位置），而且它**不查台账/重复房号**这类「数据一致性」；
  * `qa_defect_census.py` 出 M/W/F/S 四类量，但也是文本排名，且不产出几何；
  * `annotate_defects.py`(8150) 只能**人工**画框，机器发现的错进不去。

于是每次用户问「哪里有问题」，我都得临时写一个脚本重量一遍（这一轮已经写了 8 个），
量完还只在我的终端里 —— **你看不见，只能靠我说**。本脚本把这件事固化成一条流水线：
两套既有门禁 + 五项本轮实测有效的新判据 → **一份带几何的统一清单**。

五项新判据（都是本轮实测抓到了真缺陷、且既有门禁覆盖不到的）
------------------------------------------------------------
  D1 重复房号 / 重复 id
     同层同房号多条、同 id 多条、**同 id 跨层**。实测 c103 42 个跨层重复 id、c104 11 个；
     `floors` 的 id 是逐楼分段编号，同号两条会**共用一个 id**，所以判重不能靠房号也不能靠 id。
  D2 台账 vs 交付 房号集（**先判粒度，再逐间对账**）
     `rooms.json`（台账，另一条管线）与 `floors/floor*.json`（交付）逐层比房号集合。
     实测 c103 F0：交付 8 个房号 / 台账 31 个 —— 交付那一层装的根本不是本层房间。
     ★ 但有的楼台账**一行就是整翼/整层**（c006：`6-A-01-00` 1994.9㎡，交付该层 31 间
       中位 63.4㎡），拿汇总块逐间对账必然报"缺 26 间房"——那是**量具瞄错对象**，
       不是真缺房。所以先算「台账粒度数」，汇总的不逐间比，改报一条说明性 WARN。
  D3 楼层文件完整
     `index.json` 声明的层数 / 编号连续性 vs `floors/` 实际文件。实测 c009 声明 6 层但
     `floor5.json` 不存在（前端 loadFloors 抛错后停在**上一栋**的几何上，最难查的一类）。
  D4 同构平面分组内「房间并集 bbox」必须一致
     ★ 本轮抓 c103 F0 的就是这条。I18 只查**轮廓**同构层是否叠在同一坐标系；房间没查。
     c103 的 F0 与 F1 轮廓**逐点同 sha**，可是房间并集 bbox 差 **10.4 m**：
     F0 (−81.6,−44.6,81.6,42.0) vs F1 (−81.6,−34.2,81.6,37.1)。
     轮廓同构 ⇒ 两层平面一模一样 ⇒ 房间并集 bbox 也必须一样，除非本层房间错帧。
  D5 台账层号哨兵值
     台账 `floor` 出现负数/越界（实测 c009 有 `floor:-1` 4 行 = 哨兵值被当成分组键）。
  D6 房间×墙 同层自洽 vs 跨层（`--deep`，慢）
     同构组内：本层房间对**本层**墙的穿越率 应小于对**同组参考层**墙的穿越率。
     反过来 ⇒ 该层房间其实属于参考层。实测 c103 对角 3.14%/3.04%/3.01% ≪ 非对角 9.5–11.6%。
  D7 并块（一间房**真盖住**同层好几间）
     识别时多间被缝成一间：c033 F1..F5 每层 869.9㎡ **盖住 23/24 间**（= 记忆里的"整层塌陷"）、
     c103 `103-A-0X-02` 3422.5㎡ 盖住 11 间、c104 F0 `104-C-01-10` 751.1㎡ 盖住 3 间。
     ★ 这一档此前 **D0–D6 与 I1–I18 一条都不报** —— 是全库扫出来的空白。
     ★★ 量法错了两次，记在这里免得再犯：射线法在 c006 那条 1305 顶点环上漏报；
        **bbox 覆盖**则虚报 5 倍（全库 99 条只有 16 条站得住）——被"框住"的常常是**走廊**
        （走道天然框住一片房间，但与任何房间交集为 0）。故必须用 shapely 真交集/该间面积。
  D8 交付面积 vs 台账同层同号面积（与形状无关的一把尺）
     `rooms.json`（台账，另一条管线）与交付同一房号的**面积比**。实测中位 1.00（8904 对），
     真错的一侧是 c033 37×、c104 9×、c027 66×，交付远小的另一侧是 c046 3.4/44.4㎡（6 层皆是）。
     98.1% 落在 0.8~1.25；阈值 0.5 / 2.0 落在"轻度差(105+13 条)"与"重度差(37+16 条)"之间。
     ★ 只有它能在**台账逐间**的楼里定量说"这块几何跟图纸不是一回事"；
       台账是汇总行的楼（c006）它没有可比对象，由 D2 出说明 —— 两条判据互补，别只看一条。

判据基线与相对性（★ 上一轮血泪）
--------------------------------
绝对阈值会量产假缺陷：本轮我先用 mtime 把 49/49 栋判成「图旧于数据」，又用"墙穿越率"
把 F0 和 F1 一起判红（后来才发现 **17% 就是本判据的基线** —— F1 这层好数据也是 17%）。
所以这里：D1/D2/D3/D5/D6 是**结构判据**（重复就是重复，无阈值可谈）；
D4 是**分组内相对判据**（同构组自己当基线）。所有记录都带 `metric`，
出报表时同时给**全库命中分布**，让每个数都能被相对读。

产物（**只写 `_qa/`，绝不碰 `data/`**）
  `_qa/defects.json`        统一清单（含 pos / ids / metric），供 8150 叠框与后续修
  `_qa/defect_summary.md`   全库总表（按命中条数排名）
  `_qa/defect_shots/*.png`  `--shots`：命中层的对照图（轮廓+墙+房间，命中房间填红）

用法
  python -u scan_defects.py                 # 全库扫 → 总表
  python -u scan_defects.py c103 c104       # 指定楼，打印逐条
  python -u scan_defects.py --deep          # 加跑 D6（慢）
  python -u scan_defects.py --shots c103    # 出命中层对照图
  python -u scan_defects.py --selftest      # ★正控：每条判据都必须能变红，否则判据是空的
"""
import copy
import json
import os
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [ROOT, os.path.join(ROOT, "backend")]
import qa_structural as Q                                            # noqa: E402  只读复用 I1–I18

BASE = Q.BASE
QA_DIR = Q.QA_DIR
SHOT_DIR = os.path.join(QA_DIR, "defect_shots")
OUT_JSON = os.path.join(QA_DIR, "defects.json")
OUT_MD = os.path.join(QA_DIR, "defect_summary.md")

# 组名只是给人看的分类；阈值出处都写在各自判据里
GROUP = {"D0": "退化", "D1": "重复", "D2": "台账", "D3": "缺层", "D4": "错帧",
         "D5": "台账", "D6": "错帧", "D7": "并块", "D8": "台账"}

TOL_BBOX = 0.5        # D4：同构组内房间并集 bbox 允许差(m)。0.5 = 轮廓取线偏移量级
OVER_K = 3.0          # D4：相对阈值倍数 —— 探出 > 3×组内中位 才算离群（基线自校准）
OVER_ABS = 3.0        # D4：绝对兜底(m)。3 m 沿用仓里既有量级（CENT_SHIFT / SHIFT_M=3）
DUP_CAP = 12          # 每条记录列举多少个具体房号/id（避免清单爆炸）

# D2：台账**粒度**判据 —— 先判"这份台账是逐间的还是汇总的"，再决定要不要逐间对账。
# 为什么需要（c006 实测）：台账一行是整翼/整层块（`6-A-01-00` 1994.9㎡ / `6-B-01-00` 1976.0㎡ /
# `6-C-01-05` 1313.4㎡），交付是逐间（该层 31 间、面积中位 63.4㎡）。拿汇总块对逐间房号，
# 结论必然是"交付有台账无 26 个"——**量具瞄错对象**，不是 c006 真缺 26 间房
# （见记忆 c006-rooms-json-aggregate-pre-shift：35 条整翼/整层、几何停在平移前）。
# ★ 不能用"单条台账块套住几间交付房"来判汇总：实测 c103 F1 台账 30 条**本身是逐间的**，
#   却会被报"一块套住 13 间"——因为 c103 那 8 条错号重复恰好叠在别的房间里
#   （_c103_dup_what_is_there.py 实测 45/45 多余份都站在别的房号的位置上）。
#   那种判法把「台账汇总」与「交付自重叠」两种成因混成一种。
# ⇒ 只用**台账自己那一侧**的量（与交付是否重叠无关），两条同时成立才判汇总：
#     ① 台账条数 ≪ 交付间数（汇总行少）；② 台账面积中位 ≫ 交付面积中位（不可能是同一粒度）。
#   阈值出处（_scratch/_ledger_aggregate_probe2.py 全库 5 栋 D2 楼实测）：
#     汇总侧 c006 条数比 0.12~0.33 / 面积比 4.79~20.72；逐间侧最坏 c103 F5 条数比 0.68、
#     c027 F7 面积比 6.07（但它条数比 1.00，被①挡住）。⇒ 0.6 / 3.0 两侧各有约 2 倍余量。
D2_ROW_RATIO = 0.6    # D2：台账条数 / 交付间数 < 此值 ⇒ 台账行数远少于房间数
D2_AREA_RATIO = 3.0   # D2：且 台账面积中位 / 交付面积中位 > 此值 ⇒ 台账块远大于房间

# D7：并块 —— 一间房**真正盖住**同层好几间别的房（识别时多间被缝成一间）。
# 实测这一档此前 **D0–D6 与 I1–I18 一条都不报**（_scratch/_swallow_probe.py 全库 289 层扫）：
#   c033 F1..F5 每层 869.9㎡（中位 23.9 的 36 倍）盖住 23/24 间（= 记忆里的"整层塌陷"）；
#   c103 F1..F4 `103-A-0X-02` 1537.4㎡ 盖住 7 间、3422.5㎡ 盖住 11 间；
#   c104 F0 `104-C-01-10` 751.1㎡ 盖住 3 间。
# ★★ 判据必须用**真几何**（shapely 交集/该间面积），**bbox 吃住率不行** —— 我在这一档错了两次：
#   ① 第一版用手写射线法（质心在环内）：c006 F0 `6-A-01-09` 有 **1305 个顶点**、其中 881 条边短于
#      1cm（去重后只剩 210 个真顶点），射线法在其中给出"点在环外" ⇒ **漏报** c006；
#   ② 第二版改用 **bbox 覆盖**：全库报 99 条，用 shapely 逐条复核**只有 16 条站得住**
#      （_scratch/_d7_validate.py）。虚报的 83 条是**走廊/剩余空间**，出图一眼就明白
#      （_scratch/_plot_case.py，图在 _qa/case_*.png）：c079 F1 `79-A-02-23` 107.1㎡ 的红线是夹在
#      两排宿舍之间的一条 H 形走道；c006 F0 `6-A-01-09` 695.3㎡ 的红线**贴着每间房的外皮走**
#      （它是 A 翼的走廊+剩余空间，与同翼 12 间面积 882.3㎡ 的并集**交集为 0**）。
#      它们 bbox 盖住一片房间，却与任何房间零重叠 ⇒ **「bbox 覆盖」量的是"框住"，不是"吞并"**，
#      而走廊天然框住一片房间。这一条已用负控②钉住（走廊形必须不报）。
# ★ 也不能只留 D8（台账面积比）：c006 的台账是 35 条整翼/整层汇总行，**没有逐间可比对象**
#   （见 D2 的粒度判据）⇒ 只留 D8 会整栋漏检 c006。两条判据互补，各有各的证据。
# 记录里**列出被吞的房号**并能出图定位，人一眼能核 —— 不要求读者信判据。
MERGE_K = 2.5    # D7：房间面积 ≥ 该层面积中位 × 此值 ⇒ 体量异常大（实测命中 6.8~43 倍）
MERGE_N = 3      # D7：且**真盖住** ≥ N 间别的房间（1~2 间是正常的大房间夹小间）
MERGE_IN = 0.8   # D7："盖住"的定义：别的房间多边形被大房间覆盖的**面积占比**

# D8：交付多边形 与 台账同层同号 的**面积比** —— 两侧各自的量相比，与形状无关。
# 为什么加它：几何类判据已证伪两次（见上）；面积比不依赖形状，且实测能干净分开"真错"与"忠实"：
#   c079/c080 的走道 107.1/107.1 = 1.00×（**图纸本来就这么画**，识别是忠实的，不该报）；
#   c033 869.9/23.4 = 37×、c104 751.1/81.6 = 9×、c027 776.3/11.7 = 66×（真错）。
# 阈值出处（_scratch/_d8_ledger_area_probe.py + _d8_gap_probe.py，全库实测 **8904 对**，中位 1.00）：
#     0.8~1.25×  8733 条（98.1%）　← 正常
#     0.5~0.8×    105 条　　1.25~2.0×   13 条　← 轻度差（不同简化/取线容差），**不定为错**
#     <0.5×        37 条　　≥2.0×        16 条　← 两侧共 **53 条**定为不符
#   ⇒ 阈值 0.5 / 2.0 正好落在这两段"轻度"与"重度"之间（**不是空档** —— 我先前据一条把
#     0.2~1.5 并进"正常"的探针，曾在注释里错写成"0.2~3.15 几乎为空"，已按实测改正）。
#   ★ 边界实例记在案：c046 的 `卫` 22.8/44.3 = 0.515× 恰好**不报**（落在轻度区），
#     若将来把阈值放到 0.6 就会多报 105 条那一档，须先看那 105 条是不是都该报。
# 台账是汇总行的楼**必须跳过**（复用 D2 的 0.6 / 3.0 粒度判据）—— 否则就是拿整翼 1994.9㎡ 去对单间，
#   正是 D2 已修掉的那个错。跳过的楼在 D2 里已有一条"没有逐间台账"的 WARN 说明，不静音。
D8_RATIO_HI = 2.0     # D8：交付面积 / 台账面积 ≥ 此值 ⇒ 交付这块比图纸大得多
D8_RATIO_LO = 0.5     # D8：或 ≤ 此值 ⇒ 交付这块比图纸小得多（被切碎/面积丢失）

# D0：**整层未切分**的判据 —— 该层房间数 ≤ 此值 且 有一间占轮廓 >60%。
# ★ 这条**不看台账**（用户 2026-09-14 指出：台账是一方面，建模过程也重要，不能只看台账）。
#   台账相符只能说明"图纸/台账本来就没细分这一层"，**不能说明模型没问题**：
#   整层一间 ⇒ 建模出的是空盒子，没有内墙、没有门、房间导航无从谈起。
#   实测 c022 F0（1 间 1011.4㎡ = 轮廓 1222.0 的 83%，台账 1188.3㎡ = 0.85×）、
#   F2（1 间 847.6㎡ = 69%，台账 872.5㎡ = 0.97×）—— 同楼 F3~F6 各有 7~8 间、
#   F5 有 19 间 ⇒ 这两层是**全楼唯一的整层单间**，不是这栋楼的正常形态。
#   与 D7 的分工：D7 量"盖住同层别的房间"（整层 1 间时没有"别的房间"可盖，天然不适用）；
#   本判据量"单间占本层轮廓多少"，**不依赖台账、不依赖同层其它房间**。两条互补。
SPLIT_MAX_ROOMS = 3


# ----------------------------------------------------------------- 基础工具
def _median(vs):
    s = sorted(vs)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _ring(poly):
    p = [(round(float(q[0]), 3), round(float(q[1]), 3)) for q in (poly or [])]
    if len(p) > 1 and p[0] == p[-1]:
        p = p[:-1]
    return p


def _shape_rel(a, b):
    """两条房间多边形的几何关系 —— D1 靠它区分「纯重复」与「错号/错位」。

    实测出处（c103 F1..F5）：只报"8 个 id 出现多次"读者看不出该干什么 ——
    有的组两份多边形**逐点相同**（纯重复写入，剔一条即可），
    有的组**形状相同只差一个平移**（Δy=27.16，错位副本），
    有的组**形状都不一样**（c103 `103-A-02-02`：1537㎡ vs 类整幅 3422㎡）。
    三种修法完全不同，所以判据必须把它们分开，不能只给一个计数。
    返回 kind：same=逐点相同／shift=只差平移（附 dx,dy）／diff=形状不同（附各自面积）。
    """
    pa, pb = _ring(a), _ring(b)
    if len(pa) < 3 or len(pb) < 3:
        return {"kind": "empty"}
    if pa == pb:
        return {"kind": "same", "dx": 0.0, "dy": 0.0}
    ax = min(q[0] for q in pa)
    ay = min(q[1] for q in pa)
    bx = min(q[0] for q in pb)
    by = min(q[1] for q in pb)
    # 归一到各自 bbox 左下角再比点集：能同时容忍"起点不同/方向不同"与纯平移
    ra = sorted((round(q[0] - ax, 2), round(q[1] - ay, 2)) for q in pa)
    rb = sorted((round(q[0] - bx, 2), round(q[1] - by, 2)) for q in pb)
    if ra == rb:
        return {"kind": "shift", "dx": round(bx - ax, 2), "dy": round(by - ay, 2)}
    return {"kind": "diff", "areas": [round(outline_area(pa), 1), round(outline_area(pb), 1)]}


def _group_rel(polys):
    """一组（同 id 或同房号）多边形的整体关系：全同 ⇒ same；全只差平移 ⇒ shift；否则 diff。"""
    if len(polys) < 2:
        return {"kind": "single", "desc": ""}
    worst, sh = "same", None
    for other in polys[1:]:
        rel = _shape_rel(polys[0], other)
        if rel["kind"] == "same":
            continue
        if rel["kind"] == "shift":
            sh = rel
            if worst != "diff":
                worst = "shift"
        else:
            worst = "diff"
            other_areas = rel.get("areas") or []
            if worst == "diff" and other_areas:
                sh = {"areas": other_areas}
    if worst == "same":
        return {"kind": "same", "desc": "逐点相同"}
    if worst == "shift":
        return {"kind": "shift", "desc": "错位 Δ=(%+.2f,%+.2f)" % (sh["dx"], sh["dy"])}
    return {"kind": "diff",
            "desc": "形状不同 面积%s" % "/".join("%.0f" % v for v in (sh.get("areas") or []))}


def _dup_breakdown(rooms, key):
    """按 key（number/id）把同层重复分组并判几何关系。返回 (各类计数, 样例串列表)。"""
    groups = defaultdict(list)
    for r in rooms:
        groups[str(r.get(key))].append(r.get("poly") or [])
    kinds = Counter()
    samples = []
    for k, polys in sorted(groups.items()):
        if len(polys) < 2:
            continue
        rel = _group_rel(polys)
        kinds[rel["kind"]] += 1
        if len(samples) < DUP_CAP:
            samples.append("%s(%s)" % (k, rel["desc"]))
    return kinds, samples


def _kind_text(kinds):
    """把分类计数说成人话 —— 只有 same 可以放心剔重，shift/diff 都必须先判真伪。"""
    parts = []
    for k, label in (("same", "逐点相同(纯重复,可剔)"),
                     ("shift", "错位副本(同形状,差平移)"),
                     ("diff", "形状不同(错号/并块)")):
        if kinds.get(k):
            parts.append("%s %d" % (label, kinds[k]))
    return "、".join(parts) or "—"


def _bbox(pts):
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def rooms_bbox(g):
    pts = []
    for r in (g.get("rooms") or []):
        pts.extend((p[0], p[1]) for p in (r.get("poly") or []))
    return _bbox(pts)


def outline_area(o):
    """鞋带公式（_poly 只给 shapely 对象，这里要个不依赖 shapely 的纯数）。"""
    n = len(o or [])
    if n < 3:
        return 0.0
    a = 0.0
    for i in range(n):
        x1, y1 = o[i][0], o[i][1]
        x2, y2 = o[(i + 1) % n][0], o[(i + 1) % n][1]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def rec(ctx, code, sev, floor, title, msg, pos=None, ids=None, metric=None):
    return {"code": code, "sev": sev, "group": GROUP.get(code, "其他"),
            "building": ctx["name"], "floor": floor, "title": title, "msg": msg,
            "pos": [round(pos[0], 2), round(pos[1], 2)] if pos else None,
            "ids": (ids or [])[:DUP_CAP], "metric": metric or {}}


def load_ctx(name):
    """读一栋楼的 floors + 台账 + index 声明。全部只读。"""
    fl = os.path.join(BASE, name, "floors")
    floors = []
    if os.path.isdir(fl):
        for fn in sorted(os.listdir(fl)):
            if not (fn.startswith("floor") and fn.endswith(".json")):
                continue
            try:
                g = json.load(open(os.path.join(fl, fn), encoding="utf-8"))
            except Exception:                                        # noqa: BLE001
                continue
            if "floor" not in g:
                g["floor"] = int("".join(c for c in fn if c.isdigit()) or 0)
            g["_file"] = fn
            floors.append(g)
    floors.sort(key=lambda g: g["floor"])

    ledger, led_ok = [], False
    p = os.path.join(BASE, name, "rooms.json")
    if os.path.exists(p):
        try:
            j = json.load(open(p, encoding="utf-8"))
            ledger = j if isinstance(j, list) else (j.get("rooms") or [])
            led_ok = True
        except Exception:                                            # noqa: BLE001
            pass

    declared = None
    # ★ 层数声明在**全局** data/buildings/index.json（一个 list，每条 {name, floors, dir}），
    # 不是每栋自己的 index.json —— 第一版读的是 data/buildings/<楼>/index.json，实测 c009 那个
    # 文件根本不存在 ⇒ declared 恒为 None ⇒ 「c009 声明 6 层却缺 floor5」这条从来没响过。
    p = os.path.join(BASE, "index.json")
    if os.path.exists(p):
        try:
            j = json.load(open(p, encoding="utf-8"))
            if isinstance(j, list):
                for e in j:
                    if isinstance(e, dict) and e.get("name") == name:
                        v = e.get("floors")
                        if isinstance(v, int):
                            declared = v
                        break
        except Exception:                                            # noqa: BLE001
            pass
    return {"name": name, "floors": floors, "ledger": ledger,
            "ledger_ok": led_ok, "declared": declared}


# ----------------------------------------------------------------- 判据
def check_degenerate(ctx):
    """D0 退化房间：点数<3 / 面积为 0 / **整层未切分**。

    前两条是硬缺陷（几何非法）。第三条是**建模过程**的判据，与台账无关：

      · 该层房间数 ≤ SPLIT_MAX_ROOMS 且 有一间占轮廓 >60% ⇒ **ERROR 整层未切分**
        —— 该层建出来是个空盒子：没有内墙、没有门、房间导航无从谈起。
        台账相符**不能**免罪（它只说明"图纸/台账本来就没细分这一层"，
        用户 2026-09-14：台账是一方面，建模过程也重要，不能只看台账）。
      · 该层房间数 > SPLIT_MAX_ROOMS 而某间占轮廓 >60% ⇒ WARN（体量异常），
        指向 D7：多半是并块吞并，但 D7 只认"**真盖住**同层别的房间 ≥3 间"，
        盖 1~2 间或部分覆盖（<80%）的情形由本 WARN 兜住并说明。
      · 台账同号面积在这里只作**上下文**：相符 ⇒ 图纸本身没切；不符 ⇒ 同时与台账不符
        （8.12×/37.21× 那两个就是）。判"相符"复用 D8 的同一组阈值 D8_RATIO_LO/HI
        （全库 8904 对实测标定），**不另立一套** —— 两处对同一件事用不同阈值，
        迟早出现"同一间房 D8 说不符、D0 说忠实"。

    60% 出处：c103 F0 `103-A-01-04` = 4018.7㎡ 对 6735.6㎡ 轮廓 = 59.7%（并块产物）。
    实测（_scratch/_d0_giant_vs_d7.py，D0 原 8 条逐条对台账）：
      c022 F0 1 间 83% / F2 1 间 69%（台账 0.85×/0.97×）⇒ 整层未切分；
      c027 F6 8 间、`27-07-06` 355.8㎡ 覆盖 5 间（2 间 ≥80%、3 间 57~79%，台账 8.12×）；
      c033 F1..F5 24 间、`33-0X-02` 869.9㎡ = 轮廓 100%（台账 37.21×）。
    """
    out = []
    L = _ledger_area_index(ctx) if ctx["ledger_ok"] else {}
    for g in ctx["floors"]:
        F = g["floor"]
        oa = outline_area(g.get("outline") or [])
        n_room = len(g.get("rooms") or [])
        bad, giant = [], []
        for r in (g.get("rooms") or []):
            poly = r.get("poly") or []
            if len(poly) < 3:
                bad.append(str(r.get("number")))
                continue
            a = outline_area(poly)
            if a <= 1e-9:
                bad.append(str(r.get("number")))
            elif oa > 0 and a > 0.6 * oa:
                giant.append((str(r.get("number")), round(a, 1)))
        if bad:
            out.append(rec(ctx, "D0", "ERROR", F, "退化房间（点数<3 或面积为 0）",
                           "%d 间：%s" % (len(bad), "、".join(bad[:DUP_CAP])), ids=bad,
                           metric={"n": len(bad)}))
        for num, a in giant:
            la = L.get((str(F), str(num)))
            # 台账只作上下文，不作免罪：相符说明图纸本身没细分，**不说明模型没问题**
            if la and D8_RATIO_LO < a / la < D8_RATIO_HI:
                ctx_txt = "台账同号 %.1f㎡ = %.2f 倍（**相符 ⇒ 图纸/台账本身就没细分这一层**）" \
                          % (la, a / la)
            elif la:
                ctx_txt = "台账同号 %.1f㎡ = **%.2f 倍**（台账也不符 ⇒ 多半是识别并块）" % (la, a / la)
            else:
                ctx_txt = "（台账无同层同号行，无法互证）"
            if n_room <= SPLIT_MAX_ROOMS:
                out.append(rec(ctx, "D0", "ERROR", F, "整层未切分（单间占满本层）",
                               "该层仅 %d 间房，`%s` 就占 %.1f㎡ / 轮廓 %.1f㎡（%.0f%%）"
                               " ⇒ 建模出的是空盒子（无内墙、无门可依）；%s"
                               % (n_room, num, a, oa, 100 * a / oa if oa else 0, ctx_txt),
                               ids=[num],
                               metric={"n_rooms": n_room, "room_area": a,
                                       "outline_area": round(oa, 1),
                                       "ledger_area": round(la, 1) if la else None}))
            else:
                out.append(rec(ctx, "D0", "WARN", F, "单间占本层轮廓 >60%（体量异常）",
                               "`%s` = %.1f㎡ / 轮廓 %.1f㎡（%.0f%%），该层共 %d 间；%s"
                               " —— 是否并块看 D7（真几何，盖住 ≥3 间才算）"
                               % (num, a, oa, 100 * a / oa if oa else 0, n_room, ctx_txt),
                               ids=[num],
                               metric={"n_rooms": n_room, "room_area": a,
                                       "outline_area": round(oa, 1),
                                       "ledger_area": round(la, 1) if la else None}))
    return out


def check_duplicates(ctx):
    """D1 重复房号 / 重复 id（同层、跨层）。"""
    out = []
    allnum, allid = defaultdict(set), defaultdict(set)
    for g in ctx["floors"]:
        F = g["floor"]
        cn, ci = Counter(), Counter()
        for r in (g.get("rooms") or []):
            cn[str(r.get("number"))] += 1
            ci[str(r.get("id"))] += 1
            allnum[str(r.get("number"))].add(F)
            allid[str(r.get("id"))].add(F)
        dn = {k: v for k, v in cn.items() if v > 1}
        di = {k: v for k, v in ci.items() if v > 1}
        if dn:
            kn, sn = _dup_breakdown(g["rooms"], "number")
            out.append(rec(ctx, "D1", "ERROR", F, "同层重复房号",
                           "%d 个房号出现多次（%s）：%s"
                           % (len(dn), _kind_text(kn), "、".join(sn)),
                           ids=sorted(dn), metric={"n_numbers": len(dn),
                                                   "extra_rows": sum(dn.values()) - len(dn),
                                                   "kinds": dict(kn)}))
        if di:
            ki, si = _dup_breakdown(g["rooms"], "id")
            out.append(rec(ctx, "D1", "ERROR", F, "同层重复 id",
                           "%d 个 id 出现多次（%s）：%s"
                           % (len(di), _kind_text(ki), "、".join(si)),
                           ids=sorted(di), metric={"n_ids": len(di), "kinds": dict(ki)}))
    cn = {k: v for k, v in allnum.items() if len(v) > 1}
    ci = {k: v for k, v in allid.items() if len(v) > 1}
    if cn:
        out.append(rec(ctx, "D1", "ERROR", None, "跨层重复房号",
                       "%d 个房号出现在多层：%s" % (len(cn), "、".join(
                           "%s@%s" % (k, sorted(v)) for k, v in sorted(cn.items())[:DUP_CAP])),
                       ids=sorted(cn), metric={"n_numbers": len(cn)}))
    if ci:
        out.append(rec(ctx, "D1", "ERROR", None, "跨层重复 id",
                       "%d 个 id 出现在多层：%s" % (len(ci), "、".join(
                           "%s@%s" % (k, sorted(v)) for k, v in sorted(ci.items())[:DUP_CAP])),
                       ids=sorted(ci), metric={"n_ids": len(ci)}))
    return out


def check_ledger_vs_floors(ctx):
    """D2 台账房号集 vs 交付房号集（逐层）。台账缺失则跳过并记一条 INFO。

    ★ 先判**粒度**再逐间对账：台账可能是整翼/整层汇总行（c006 实测），逐间对账不适用。
      判据与阈值出处见文件头 D2_ROW_RATIO / D2_AREA_RATIO。汇总的层**不报缺房**，
      收成整栋一条说明性 WARN（不静音 —— 它意味着这栋没有逐间台账可对账）。
    """
    if not ctx["ledger_ok"]:
        return [rec(ctx, "D2", "INFO", None, "无台账 rooms.json",
                    "本楼没有台账，D2 跳过（不臆造缺房）")]
    led = defaultdict(set)
    for r in ctx["ledger"]:
        led[r.get("floor")].add(str(r.get("number")))
    grain = _ledger_grain(ctx)          # ★ 粒度判据只有 _ledger_grain 一份实现（D8 共用）
    out, agg = [], []
    for g in ctx["floors"]:
        F = g["floor"]
        have = {str(r.get("number")) for r in (g.get("rooms") or [])}
        want = led.get(F, set())
        if not want and not have:
            continue
        gi = grain.get(F)
        if gi is not None and gi["aggregate"]:
            agg.append(dict(gi, floor=F))
            continue
        miss = sorted(want - have)
        extra = sorted(have - want)
        if not miss and not extra:
            continue
        # 严重度：**两个方向都算**。c103 F0 是"交付少"（交付 8 / 台账 31 ⇒ 缺 23），
        # 早先只判"交付多"那一侧，于是这条被降成 WARN —— 判据写歪了。
        sev = "ERROR" if (len(miss) > 0.5 * len(want) or len(extra) > 0.5 * len(have)) else "WARN"
        out.append(rec(ctx, "D2", sev, F, "交付房号集与台账不符",
                       "交付 %d 个 / 台账 %d 个；台账有交付无 %d 个%s，交付有台账无 %d 个%s"
                       % (len(have), len(want), len(miss),
                          ("（%s）" % "、".join(miss[:6]) if miss else ""),
                          len(extra), ("（%s）" % "、".join(extra[:6]) if extra else "")),
                       ids=miss + extra,
                       metric={"n_have": len(have), "n_want": len(want),
                               "n_missing": len(miss), "n_extra": len(extra)}))
    if agg:
        # 一条整栋记录，不加 floor（跨层共性）；把**实测比值**写进 msg 与 metric，
        # 让"是汇总行"这个判断本身可被复核，而不是只有我一句话。
        nr0 = min(a["row_ratio"] for a in agg)
        nr1 = max(a["row_ratio"] for a in agg)
        ar0 = min(a["area_ratio"] for a in agg)
        ar1 = max(a["area_ratio"] for a in agg)
        out.append(rec(ctx, "D2", "WARN", None, "台账是整翼/整层汇总行，逐间对账不适用",
                       "%d/%d 层的台账是汇总行（台账每层 %d~%d 条 / 交付 %d~%d 间，"
                       "条数比 %.2f~%.2f、面积中位比 %.2f~%.2f 倍）⇒ 这栋**没有逐间台账**"
                       "可交叉验证房号，不是缺房；要逐间对账须先按间重出台账"
                       % (len(agg), len(ctx["floors"]),
                          min(a["n_ledger"] for a in agg), max(a["n_ledger"] for a in agg),
                          min(a["n_have"] for a in agg), max(a["n_have"] for a in agg),
                          nr0, nr1, ar0, ar1),
                       metric={"n_agg_floors": len(agg), "n_floors": len(ctx["floors"]),
                               "floors": [a["floor"] for a in agg],
                               "row_ratio": [nr0, nr1], "area_ratio": [ar0, ar1]}))
    return out


def check_floor_files(ctx):
    """D3 楼层文件完整（声明 vs 实际；编号连续性）。"""
    out = []
    got = sorted(g["floor"] for g in ctx["floors"])
    if not got:
        return [rec(ctx, "D3", "ERROR", None, "没有任何楼层文件", "floors/ 下没有 floor*.json")]
    holes = [n for n in range(got[0], got[-1] + 1) if n not in got]
    if holes:
        out.append(rec(ctx, "D3", "ERROR", None, "楼层编号不连续",
                       "缺 F%s（实有 F%s..F%s）" % (holes, got[0], got[-1]),
                       metric={"holes": holes, "have": len(got)}))
    d = ctx["declared"]
    if d is not None and d != len(got):
        out.append(rec(ctx, "D3", "ERROR", None, "index.json 声明层数与实际文件数不符",
                       "声明 %d 层 / 实际 %d 个文件（前端载入会抛错并停在上一栋的几何上）"
                       % (d, len(got)), metric={"declared": d, "have": len(got)}))
    if got and got[0] != 0:
        out.append(rec(ctx, "D3", "WARN", None, "首层不是 F0", "最低层是 F%d" % got[0]))
    return out


def check_iso_group_rooms(ctx):
    """D4 同构平面分组内，房间并集必须落在**本层轮廓**里 —— 抓整层房间错帧。

    ★ 判据怎么定出来的（第一版是空断言、第二版被基线淹，都记下来防复发）
    第一版写的是"组内房间并集 bbox 取**众数**当参考，离群者报错"。跑正控时**没变红**，
    查下去有两处错：
      ① c103 的同构组只有 {F0,F1} 两层，两层 bbox 正好**互不相同** ⇒ 没有众数
         （`n_ref < 2`）⇒ 直接 continue，判据永远不响 —— 是个**空断言**；
      ② 更要命的是它在**原始 c103 上命中 0 条**，而 c103 F0 正是要抓的那个。
    ⇒ 改成拿**轮廓**当不变参考：`_shape_key` 相等 ⇒ 这层平面与别层同构、平面是重复的，
      那么**房间并集 bbox 必须落在本层轮廓 bbox 内**。这是逐层判据，两层组也成立，
      而且参考量（轮廓）与待检量（房间）来路不同，不是自证。
    c103 F0：房间并集 y −44.6…42.0 vs 轮廓 y −39.6…40.0 ⇒ 上下各探出 5.0 / 2.0 m
    c103 F1：房间并集 y −34.2…37.1 ⊂ 轮廓 ⇒ 不报（同组、同轮廓，只有 F0 报）

    ★★ 第二版的错：拿 **0.5 m 绝对阈值**判 —— c027 被命中 7 层，逐层量出来是
       f1/f2/f3/f4/f7 与 f5/f6（**两个不同的同构组**）探出量**逐位相同**的
       右+0.55 上+0.90（f7 的 −9.49 是**负**分量 = 房间缩在轮廓底边内侧 9.49 m，
       不是"下探"；我把负分量的绝对值当成探出量读错过一次，见 _scratch/_probe_c027_d4.py）。
      ⇒ 七层、跨两组、数值一模一样 —— 这**不可能是逐层的缺陷**，只能是**轮廓**被整体
        裁内了 0.55/0.90（outline-simplify-chord-bulge 那一族：凹角外切、台阶磨圆再拉直）。
      绝对阈值于是把 7 个正常层判红 —— 与「墙穿越量 17% 是基线」同一个坑：
      **基线不为零的量不能用绝对阈值**。
      ★ 修完后 D4 全库 49 栋命中 **0** 条 —— 这不是判据失效，是它原先那 7 条**全是假阳**。
        它现在只在"组内某一层与其余层显著不同"时响（正控里 2 条变异用例可复现变红）。
    ⇒ 阈值改成两侧取严：
         相对：protrusion > 3 × 组内中位数（组自己给自己定基线，基线多高都不怕）
         绝对：protrusion ≥ 3.0 m（独立于组的兜底；3 m 沿用仓里既有量级约定
               —— qa_structural 的 CENT_SHIFT=3.0、qa_defect_census 的 SHIFT_M=3）
       实测：c027 组中位 0.90 ⇒ 相对阈 2.70，只有 f7(9.49) 越线（f5 的 1.89 不越）；
             c103 {F0:5.0, F1:0} 中位 2.50 ⇒ 相对阈 7.50 拦不住，但**绝对阈 3.0 抓住 F0** ✓
      这条判据现在两个方向都硬：组内一致偏高不报（那是轮廓的事），单层突出必报。

    只在「同构层数 ≥2」的层上判：不同构的层（门厅/独层/退台）不进组，不误报。
    """
    groups = defaultdict(list)
    for g in ctx["floors"]:
        k = Q._shape_key(g.get("outline") or [])
        if k:
            groups[k].append(g)
    out = []
    for key, gs in groups.items():
        if len(gs) < 2:
            continue
        # 先算全组的探出量，才能拿组自己定基线
        item = []
        for g in gs:
            rb, ob = rooms_bbox(g), _bbox([(p[0], p[1]) for p in (g.get("outline") or [])])
            if not rb or not ob:
                continue
            # 房间并集超出轮廓多少（正数=探出）
            over = (ob[0] - rb[0], ob[1] - rb[1], rb[2] - ob[2], rb[3] - ob[3])
            item.append((g, rb, ob, over, max(over)))
        if not item:
            continue
        for g, rb, ob, over, worst in item:
            # ★ 基线必须**留一（leave-one-out）**：拿"除自己以外"的组员算中位。
            #   用全组中位时，二元组会自己污染自己的基线 —— c103 的同构组恰好就是
            #   {F0,F1} 两层，n=2 的中位 = 两者均值，离群者把自己那一半抬进来：
            #   实测 F0 顶出 2.00 / F1 顶出 0.40 ⇒ 中位 1.20 ⇒ 阈 3.60 > 2.00 ⇒ **本该报的报不出来**。
            #   留一后：F0 看其余 [0.40] ⇒ 阈 1.20 ⇒ 2.00 > 1.20 命中；F1 看 [2.00] ⇒ 阈 6.00 ⇒ 不报。
            #   这同时保住了"只挑最极端的那个"，不会把整组一起判红。
            others = [w for gg, _r, _o, _ov, w in item if gg is not g]
            med = _median(others) if others else 0.0
            thr = max(TOL_BBOX, OVER_K * med)
            if worst <= thr and worst < OVER_ABS:
                continue
            out.append(rec(ctx, "D4", "ERROR", g["floor"], "同构层房间并集探出本层轮廓",
                           "本层轮廓与同组 %d 层同构（平面重复），房间并集却探出轮廓 "
                           "左%.2f 下%.2f 右%.2f 上%.2f m（最大 %.2f，其余层中位 %.2f，"
                           "阈值 %.2f）—— 房间没跟轮廓走（整层错帧）"
                           % (len(gs) - 1, over[0], over[1], over[2], over[3],
                              worst, med, thr),
                           pos=((rb[0] + rb[2]) / 2, (rb[1] + rb[3]) / 2),
                           metric={"rooms_bbox": [round(v, 2) for v in rb],
                                   "outline_bbox": [round(v, 2) for v in ob],
                                   "over": [round(v, 2) for v in over],
                                   "worst": round(worst, 2),
                                   "group_median": round(med, 2),
                                   "thr": round(thr, 2),
                                   "group_size": len(gs)}))
    return out


def check_ledger_sentinel(ctx):
    """D5 台账层号哨兵值（负数/越界）。"""
    if not ctx["ledger_ok"]:
        return []
    got = [g["floor"] for g in ctx["floors"]]
    hi = max(got) if got else 0
    bad = Counter(r.get("floor") for r in ctx["ledger"]
                  if not isinstance(r.get("floor"), int) or r.get("floor") < 0
                  or r.get("floor") > hi)
    if not bad:
        return []
    return [rec(ctx, "D5", "WARN", None, "台账层号是哨兵值/越界",
                "层号 %s 各 %s 行 —— 哨兵值被当分组键会产出假楼层"
                % (list(bad), [bad[k] for k in bad]),
                metric={"floors": {str(k): v for k, v in bad.items()},
                        "max_real_floor": hi})]


def check_merged_rooms(ctx):
    """D7 并块：一间房**真盖住**同层好几间（识别时多间被缝成一间）。

    判据与阈值出处见文件头 MERGE_K / MERGE_N / MERGE_IN（含两次证伪：射线法与 bbox 都不可用）。
    性能：只对「面积 ≥ K×该层中位」的少数候选算交集（典型每层 1~5 间），
    且**不做 bbox 粗筛** —— 粗筛会漏掉"盖住 80~90% 但不完全"的边角情形，
    而正确性（不漏报）比这点速度重要（本仓已被"量程滤掉待检对象"咬过多次）。
    """
    from shapely.geometry import Polygon

    def mk(pts):
        """多边形；无效时 buffer(0) 修（c006 那条 1305 顶点环必须修才可用）。失败返回 None。"""
        try:
            s = Polygon(pts)
            if not s.is_valid:
                s = s.buffer(0)
        except Exception:                                            # noqa: BLE001
            return None
        return s if (not s.is_empty and s.area > 0) else None

    out = []
    for g in ctx["floors"]:
        rooms = []
        for r in (g.get("rooms") or []):
            pts = [(p[0], p[1]) for p in (r.get("poly") or [])]
            if len(pts) < 3:
                continue
            a = outline_area(pts)
            b = _bbox(pts)
            if a <= 0 or not b:
                continue
            rooms.append({"r": r, "pts": pts, "b": b, "a": a, "s": None})
        if len(rooms) < 5:
            continue
        md = _median([x["a"] for x in rooms])
        if md <= 0:
            continue
        for x in rooms:
            if x["a"] < MERGE_K * md:
                continue
            x["s"] = mk(x["pts"])
            if x["s"] is None:
                continue
            sw = []
            for y in rooms:
                if y is x:
                    continue
                if y["s"] is None:
                    s2 = mk(y["pts"])
                    y["s"] = s2 if s2 is not None else False
                if y["s"] is False:
                    continue
                try:
                    frac = x["s"].intersection(y["s"]).area / y["a"]
                except Exception:                                    # noqa: BLE001
                    continue
                if frac >= MERGE_IN:
                    sw.append(str(y["r"].get("number")))
            if len(sw) >= MERGE_N:
                # ★ `_bbox` 的约定是 **(minx, miny, maxx, maxy)** —— 顺手写成 (minx,maxx,miny,maxy)
                #   会让下面四个数全部错位；变量名带上坐标含义，不写 x0/x1/y0/y1（本仓踩过多次）。
                bx0, by0, bx1, by1 = x["b"]
                out.append(rec(ctx, "D7", "ERROR", g["floor"], "并块：一间房盖住同层多间",
                               "`%s` 面积 %.1f㎡（该层中位 %.1f 的 %.1f 倍）**真盖住**同层 %d 间：%s"
                               " —— 多半是识别时多间被缝成一间（该层共 %d 间）"
                               % (x["r"].get("number"), x["a"], md, x["a"] / md, len(sw),
                                  "、".join(sorted(sw)[:DUP_CAP]), len(rooms)),
                               pos=((bx0 + bx1) / 2.0, (by0 + by1) / 2.0),
                               ids=[str(x["r"].get("number"))] + sorted(sw),
                               metric={"area": round(x["a"], 1), "floor_median": round(md, 1),
                                       "ratio": round(x["a"] / md, 2), "n_swallowed": len(sw),
                                       "n_floor_rooms": len(rooms)}))
    return out


def _ledger_grain(ctx):
    """逐层判台账**粒度**：这层的台账是逐间的，还是整翼/整层汇总行。

    判据与阈值出处见文件头 D2_ROW_RATIO / D2_AREA_RATIO。**D2 与 D8 共用这一份实现**
    （两份实现必然漂移，本仓已有先例）。
    返回 {floor: {"aggregate": bool, "n_ledger": int, "n_have": int,
                  "row_ratio": float, "area_ratio": float}}
    """
    led_ar, led_n = defaultdict(list), defaultdict(int)
    for r in ctx["ledger"]:
        led_ar[r.get("floor")].append(outline_area(r.get("boundary") or []))
        led_n[r.get("floor")] += 1
    grain = {}
    for g in ctx["floors"]:
        F = g["floor"]
        da = [a for a in (outline_area(r.get("poly") or []) for r in (g.get("rooms") or [])) if a > 0]
        if not da:
            continue
        la = [a for a in led_ar.get(F, []) if a > 0]
        nr = led_n.get(F, 0) / float(len(da))
        ar = (_median(la) / _median(da)) if (la and _median(da) > 0) else 0.0
        grain[F] = {"aggregate": bool(nr < D2_ROW_RATIO and ar > D2_AREA_RATIO),
                    "n_ledger": len(la), "n_have": len(g.get("rooms") or []),
                    "row_ratio": round(nr, 2), "area_ratio": round(ar, 2)}
    return grain


def _ledger_is_aggregate(ctx):
    """台账是否**整栋都是汇总行**（没有逐间可比对象）—— D8 用它决定跳不跳。

    过半层都是汇总 ⇒ 这栋没有逐间台账。返回说明用的 metric dict；有逐间可比对象则返回 None。
    """
    gr = _ledger_grain(ctx)
    n_use = len(gr)
    agg = [v for v in gr.values() if v["aggregate"]]
    if n_use and len(agg) >= max(1, int(0.5 * n_use)):
        return {"n_agg_floors": len(agg), "n_floors": n_use,
                "row_ratio": [min(a["row_ratio"] for a in agg),
                              max(a["row_ratio"] for a in agg)],
                "area_ratio": [min(a["area_ratio"] for a in agg),
                               max(a["area_ratio"] for a in agg)]}
    return None


def _ledger_area_index(ctx):
    """`{(层, 房号): 台账面积}`（同键多行取最大）。

    **D8 与 D0 共用这一份实现** —— D0 的体量判据要拿台账同号面积来判"忠实还是并块"，
    若各写一份，两处的键（`str(floor)` 还是 int、缺 number 怎么办）迟早漂移
    （本仓"D2/D8 共用 _ledger_grain"就是为同一原因收口的）。
    """
    idx = {}
    for r in ctx["ledger"]:
        a = outline_area(r.get("boundary") or [])
        if a <= 0:
            continue
        k = (str(r.get("floor")), str(r.get("number")))
        if a > idx.get(k, 0):
            idx[k] = a
    return idx


def check_ledger_area_mismatch(ctx):
    """D8：交付多边形面积 与 台账同层同号面积**不符**（两侧各自的量相比，与形状无关）。

    判据与阈值出处见文件头 D8_RATIO_HI / D8_RATIO_LO（全库 8904 对，中位 1.00，空档 0.2~3.15）。
    台账是汇总行的楼跳过（由 D2 出说明，不在这里静音重复）。
    """
    if not ctx["ledger_ok"]:
        return []
    agg = _ledger_is_aggregate(ctx)
    if agg is not None:
        return []
    L = _ledger_area_index(ctx)
    out = []
    for g in ctx["floors"]:
        F = g["floor"]
        for r in (g.get("rooms") or []):
            k = (str(F), str(r.get("number")))
            if k not in L:
                continue
            va = outline_area(r.get("poly") or [])
            la = L[k]
            if va <= 0 or la <= 0:
                continue
            rt = va / la
            if D8_RATIO_LO < rt < D8_RATIO_HI:
                continue
            dirn = "大" if rt >= D8_RATIO_HI else "小"
            out.append(rec(ctx, "D8", "ERROR", F, "交付房间面积与台账不符",
                           "`%s` 交付 %.1f㎡ / 台账 %.1f㎡ = **%.2f 倍**（交付比图纸%s %.1f 倍）"
                           " —— 台账里同层同号的房间是另一块几何"
                           % (r.get("number"), va, la, rt, dirn,
                              rt if rt >= 1 else 1.0 / rt),
                           ids=[str(r.get("number"))],
                           metric={"delivery_area": round(va, 1), "ledger_area": round(la, 1),
                                   "ratio": round(rt, 3)}))
    return out


def check_room_wall_deep(ctx):
    """D6 同构组内：本层房间对**本层**墙的穿越率 应小于对同组参考层墙的穿越率。

    反过来 ⇒ 本层房间其实属于参考层（房间被换成别的层了，墙没换）。
    实测 c103 对角 3.14/3.04/3.01% ≪ 非对角 9.5–11.6%（判据能分辨，非空断言）。
    """
    from shapely.geometry import Polygon, LineString
    from shapely.ops import unary_union

    def wall_union(g):
        ls = []
        for w in (g.get("walls") or []):
            p = [(q[0], q[1]) for q in (w.get("poly") or [])]
            for i in range(len(p) - 1):
                ls.append(LineString([p[i], p[i + 1]]))
            if len(p) > 2 and (p[0] != p[-1]):
                ls.append(LineString([p[-1], p[0]]))
        return unary_union(ls) if ls else None

    def cross(rooms, walls):
        if walls is None or walls.is_empty:
            return None
        tot = 0.0
        for r in rooms:
            p = Polygon([(q[0], q[1]) for q in (r.get("poly") or [])])
            if not p.is_valid:
                p = p.buffer(0)
            inner = p.buffer(-0.05)
            if inner.is_empty:
                continue
            inter = walls.intersection(inner)
            if not inter.is_empty and inter.geom_type in ("LineString", "MultiLineString"):
                tot += inter.length
        return tot

    groups = defaultdict(list)
    for g in ctx["floors"]:
        k = Q._shape_key(g.get("outline") or [])
        if k:
            groups[k].append(g)
    out = []
    for key, gs in groups.items():
        if len(gs) < 2:
            continue
        gs = [g for g in gs if g.get("rooms") and g.get("walls")]
        if len(gs) < 2:
            continue
        ref = max(gs, key=lambda g: len(g["rooms"]))
        rw = wall_union(ref)
        if not rw.length:
            continue
        for g in gs:
            if g is ref:
                continue
            own, oth = cross(g["rooms"], wall_union(g)), cross(g["rooms"], rw)
            if own is None or oth is None or not own:
                continue
            if oth < own * 0.6:      # 对别层的墙反而贴得多 ⇒ 房间属于别层
                out.append(rec(ctx, "D6", "ERROR", g["floor"], "本层房间疑似属于同构的别层",
                               "本层房间对**本层**墙穿越 %.1f m，对 F%d 墙只 %.1f m "
                               "—— 房间被换成 F%d 的了，墙没换"
                               % (own, ref["floor"], oth, ref["floor"]),
                               metric={"cross_own": round(own, 1),
                                       "cross_ref": round(oth, 1),
                                       "ref_floor": ref["floor"]}))
    return out


CHECKS = [check_degenerate, check_duplicates, check_ledger_vs_floors, check_floor_files,
          check_iso_group_rooms, check_ledger_sentinel, check_merged_rooms,
          check_ledger_area_mismatch]
DEEP = [check_room_wall_deep]


def scan(name, deep=False):
    ctx = load_ctx(name)
    recs = []
    for fn in (CHECKS + (DEEP if deep else [])):
        try:
            recs.extend(fn(ctx) or [])
        except Exception as e:                                       # noqa: BLE001
            recs.append(rec(ctx, fn.__name__, "INFO", None, "判据自身异常（不算命中）",
                            "%s: %s" % (type(e).__name__, e)))
    # 复用 qa_structural 的 I1–I18（只读调用，不改它）
    try:
        floors, fs = Q.check_building(name, False)
        for f in (fs or []):
            recs.append({"code": f.inv, "sev": f.severity, "group": "结构",
                         "building": name, "floor": f.floor, "title": f.inv,
                         "msg": f.msg, "pos": [round(f.pos[0], 2), round(f.pos[1], 2)]
                         if f.pos else None, "ids": [], "metric": {}})
    except Exception as e:                                           # noqa: BLE001
        recs.append(rec(ctx, "QA", "INFO", None, "qa_structural 调用异常",
                        "%s: %s" % (type(e).__name__, e)))
    return ctx, recs


def summary(recs):
    """按楼汇总：ERROR/WARN 数 + 命中的判据码。"""
    per = defaultdict(lambda: {"ERROR": 0, "WARN": 0, "INFO": 0, "codes": Counter()})
    for r in recs:
        d = per[r["building"]]
        d[r["sev"]] = d.get(r["sev"], 0) + 1
        d["codes"][r["code"]] += 1
    return per


# qa_structural 源码里**自己写明 by design** 的码：
#   I11 门宿主盒（全库 22461 道门只有 1187 道带盒子）、I17 待办楼梯井（28 栋）、
#   I9 每层 INFO（295 条纯噪声）。它们不是"没检出问题"，是"这批数据都这样"。
# 注：这只是**加注**，不改变计数、不隐藏条目 —— 见 triage() 的 docstring。
QA_BY_DESIGN = {"I11", "I17", "I9"}
PREV_FRAC = 1.0 / 3.0     # 命中栋数 ≥ 总栋数 1/3 ⇒ 系统性，单列


def _sevlabel(sv):
    """级别的**如实**写法：同时有 ERROR 和 WARN 就都写出来，不取"最高那个"。

    ★ 早先这里写的是 `"ERROR" if sv.get("ERROR") else "WARN"` —— 一个码只要有**一条** ERROR，
      整行就被标成 ERROR，而"条目"列是**全部**记录数。实测后果：D2 显示「ERROR 11 条」
      真实是 1 ERROR + 10 WARN，I3 显示「ERROR 11 条」真实是 3 + 8。
      用户正是按这个数字判断"有几件事要修"，高估 5~10 倍 —— 而"让问题看得见"的前提是
      数字本身不能骗人，否则清单看一眼就不敢信了。
    """
    e, w = sv.get("ERROR", 0), sv.get("WARN", 0)
    if e and w:
        return "%dE/%dW" % (e, w)
    return "ERROR" if e else "WARN"


def triage(recs, total):
    """按**命中栋数**把判据码分成「个别」（可逐栋修）与「普遍」（系统性，得整仓决策）。

    为什么必须分：第一版总表里 341 条 WARN 中 I17×140（23 栋）、I11×87（14 栋）、
    I9×295 把 79 条可操作 ERROR 整个盖住 —— 用户看到一屏噪声，等于什么都没看见。
    ★ 分档**主判据是算出来的**（prevalence = 该码命中了几个不同的楼），
      不是人工挑名单：某个码一旦在 ≥1/3 的楼上命中，它就不是"这栋楼坏了"，
      而是"这批数据都这样"，逐栋报告里没有可操作性。by-design 名单只用来加注。
    这样新出现一个普遍缺陷时（比如某码突然在 20 栋上响）也会自动落进「普遍」栏，
    不会被当成 20 条孤立缺陷。
    """
    by = defaultdict(lambda: {"recs": 0, "buildings": set(), "sev": Counter(), "sample": ""})
    for r in recs:
        if r["sev"] == "INFO":
            continue
        d = by[r["code"]]
        d["recs"] += 1
        d["buildings"].add(r["building"])
        d["sev"][r["sev"]] += 1
        if not d["sample"]:
            d["sample"] = "%s：%s" % (r["building"], r["msg"][:80])
    act, sysm = [], []
    thr = max(2.0, PREV_FRAC * total)
    for code, d in by.items():
        row = {"code": code, "recs": d["recs"], "prevalence": len(d["buildings"]),
               "buildings": sorted(d["buildings"]), "sev": dict(d["sev"]),
               "sample": d["sample"], "by_design": code in QA_BY_DESIGN}
        (sysm if (row["prevalence"] >= thr or row["by_design"]) else act).append(row)
    act.sort(key=lambda r: (-r["sev"].get("ERROR", 0), -r["prevalence"], r["code"]))
    sysm.sort(key=lambda r: (-r["prevalence"], r["code"]))
    return act, sysm


# ----------------------------------------------------------------- 正控
def selftest():
    """★ 每条判据都必须能变红 —— 否则它就是空断言（本轮已踩过两次）。"""
    name = "c103" if os.path.isdir(os.path.join(BASE, "c103")) else \
        sorted(os.listdir(BASE))[0]
    base_ctx = load_ctx(name)
    if not base_ctx["floors"]:
        print("正控无法进行：%s 没有楼层" % name)
        return 1
    fails = []

    def mut(m):
        c = copy.deepcopy(base_ctx)
        m(c)
        return c

    def first_room(c):
        for g in c["floors"]:
            if g.get("rooms"):
                return g, g["rooms"][0]
        return None, None

    cases = []

    def case(fn, label, m):
        cases.append((fn, label, mut(m)))

    def m_dup(c):
        g, r = first_room(c)
        g["rooms"].append(copy.deepcopy(r))

    def m_dup_id(c):
        g, r = first_room(c)
        r2 = copy.deepcopy(r)
        r2["number"] = str(r.get("number")) + "-X"
        g["rooms"].append(r2)

    def m_ledger(c):
        if not c["ledger"]:
            c["ledger"] = [{"floor": c["floors"][0]["floor"], "number": "假-房-号",
                            "boundary": [[0, 0], [1, 0], [1, 1]]}]
            c["ledger_ok"] = True
        else:
            c["ledger"].append({"floor": c["floors"][0]["floor"], "number": "假-房-号",
                                "boundary": [[0, 0], [1, 0], [1, 1]]})

    def m_hole(c):
        if len(c["floors"]) > 1:
            c["floors"] = [g for g in c["floors"] if g["floor"] != c["floors"][1]["floor"]]

    def m_declared(c):
        c["declared"] = len(c["floors"]) + 3

    def m_frame(c):
        # 把某层房间整体平移 5m（同构组内必现形）
        for g in c["floors"][1:]:
            if g.get("rooms"):
                for r in g["rooms"]:
                    r["poly"] = [[p[0], p[1] + 5.0] for p in r["poly"]]
                return
        first_room(c)[1]["poly"] = [[p[0], p[1] + 5.0] for p in first_room(c)[1]["poly"]]

    def m_deg(c):
        first_room(c)[1]["poly"] = [[0, 0], [1, 1]]

    def m_sent(c):
        if not c["ledger"]:
            m_ledger(c)
        c["ledger"].append({"floor": -1, "number": "哨兵", "boundary": [[0, 0], [1, 0], [1, 1]]})

    def _group_floors(c):
        groups = defaultdict(list)
        for g in c["floors"]:
            k = Q._shape_key(g.get("outline") or [])
            if k:
                groups[k].append(g)
        return max(groups.values(), key=len) if groups else []

    def _push_union_top(g, ob_top, amount):
        """把该层房间并集里**最高的那间**的顶抬到 ob_top+amount。

        ★ 这里量的是"顶出量"，不是"平移量" —— 上一版我用**整体平移**做变异，
          平移会把一侧推出去、同时把对侧收回来，`max(over)` 可能原地不动 ⇒ 用例不红。
          平移与"突出"不是一件事，变异必须**造出突出**才测得到这条判据。
        """
        rs = [r for r in (g.get("rooms") or []) if len(r.get("poly") or []) >= 3]
        if not rs:
            return
        r = max(rs, key=lambda rr: max(p[1] for p in rr["poly"]))
        top = max(p[1] for p in r["poly"])
        r["poly"] = [[p[0], (ob_top + amount) if abs(p[1] - top) < 1e-9 else p[1]]
                     for p in r["poly"]]

    def m_over_uniform(c):
        """同构组各层房间并集**一致**顶出轮廓 0.4m —— 组内一致 = 轮廓基线的形态，
        **不该报**（锁 c027 那次把 4 层 0.90m 基线全判红的误报）。"""
        for g in _group_floors(c):
            ob = _bbox([(p[0], p[1]) for p in (g.get("outline") or [])])
            if ob:
                _push_union_top(g, ob[3], 0.4)

    def m_over_relative(c):
        """同上前提全组 0.4m，但**某一层**顶出 2.0m —— 2.0 < 绝对兜底 3.0，
        所以唯一能抓住它的是相对阈值（3×组中位 0.4 = 1.2），专测那条分支。"""
        m_over_uniform(c)
        gs = _group_floors(c)
        ob = _bbox([(p[0], p[1]) for p in (gs[0].get("outline") or [])]) if gs else None
        if gs and ob:
            _push_union_top(gs[0], ob[3], 2.0)

    case(check_duplicates, "D1 同层重复房号", m_dup)
    case(check_duplicates, "D1 重复 id", m_dup_id)
    case(check_ledger_vs_floors, "D2 台账多一间", m_ledger)
    case(check_floor_files, "D3 楼层编号有洞", m_hole)
    case(check_floor_files, "D3 声明数不符", m_declared)
    case(check_iso_group_rooms, "D4 同构层房间错帧", m_frame)
    case(check_iso_group_rooms, "D4 组内孤层突出(相对阈)", m_over_relative)
    case(check_degenerate, "D0 退化房间", m_deg)
    case(check_ledger_sentinel, "D5 台账哨兵层", m_sent)
    # 反向用例：必须**不**变红的（否则就是误报）
    neg_cases = [(check_iso_group_rooms, "D4 全组同幅偏移（基线，不许报）", m_over_uniform)]

    print("正控：%s（%d 层）" % (name, len(base_ctx["floors"])))
    for fn, label, c in cases:
        try:
            got = fn(c) or []
        except Exception as e:                                       # noqa: BLE001
            got = []
            print("  ✗ %-24s 判据抛异常 %s: %s" % (label, type(e).__name__, e))
        if got:
            print("  ✓ %-24s 变红 → %s" % (label, got[0]["code"]))
        else:
            print("  ✗ %-24s **没变红 = 空断言**" % label)
            fails.append(label)
    # 分类能力自检：D1 必须能**分清**三种重复 —— 只报"8 个 id 出现多次"不算分清，
    # 因为剔重、改号、改几何是三种完全不同的修法（c103 三种都真实存在）。
    # 实测：c103 F1..F5 每组重复都落在 shift（错位 Δy=27.16）或 diff（1537㎡ vs 3422㎡）。
    def kinds_of(m):
        rs = check_duplicates(mut(m)) or []
        return (rs[0].get("metric", {}).get("kinds", {}) if rs else {}) or {}

    def m_same(c):
        g, r = first_room(c)
        g["rooms"].append(copy.deepcopy(r))

    def m_shift(c):
        g, r = first_room(c)
        r2 = copy.deepcopy(r)
        r2["poly"] = [[p[0], p[1] + 5.0] for p in r2["poly"]]
        g["rooms"].append(r2)

    def m_diff(c):
        g, r = first_room(c)
        r2 = copy.deepcopy(r)
        x0, y0 = r2["poly"][0][0], r2["poly"][0][1]
        r2["poly"] = [[x0, y0], [x0 + 7.0, y0], [x0 + 7.0, y0 + 3.0]]
        g["rooms"].append(r2)

    print()
    for label, m, want in (("逐点相同的重复", m_same, "same"),
                           ("只差平移的副本", m_shift, "shift"),
                           ("形状不同的同号", m_diff, "diff")):
        ks = kinds_of(m)
        if ks.get(want):
            print("  ✓ D1 分类 %-14s → %s" % (label, dict(ks)))
        else:
            print("  ✗ D1 分类 %-14s **没归到 %s**（实测 %s）" % (label, want, dict(ks)))
            fails.append("D1 分类 " + label)
    # D2 粒度判据的**两侧守卫**。★ 只写正控是不够的：把"汇总台账不报缺房"做过头，
    #   就会连**真**的房号不符一起静音 —— 那种"改完世界安静了"正是最危险的假绿。
    #   正控：台账换成每层 1 条整层块 ⇒ 必须认出汇总、只报"不适用"、**不许**报缺房；
    #   负控：逐间台账里改错一个房号 ⇒ 必须照常报出 miss/extra，**不许**被粒度判据吞掉。
    def d2_of(m):
        return check_ledger_vs_floors(mut(m)) or []

    def m_agg(c):
        c["ledger"], c["ledger_ok"] = [], True
        for g in c["floors"]:
            pts = [p for r in (g.get("rooms") or []) for p in (r.get("poly") or [])]
            if len(pts) < 3:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            c["ledger"].append({"floor": g["floor"], "number": "整层汇总",
                                "boundary": [[min(xs), min(ys)], [max(xs), min(ys)],
                                             [max(xs), max(ys)], [min(xs), max(ys)]]})

    def m_per_room_one_wrong(c):
        c["ledger"], c["ledger_ok"] = [], True
        g = next(x for x in c["floors"] if x.get("rooms"))
        for i, r in enumerate(g["rooms"]):
            c["ledger"].append({"floor": g["floor"],
                                "number": ("假-房-号" if i == 0 else str(r.get("number"))),
                                "boundary": [list(p) for p in (r.get("poly") or [])]})

    rs = d2_of(m_agg)
    if len(rs) == 1 and "汇总行" in rs[0]["title"]:
        print("  ✓ D2 粒度  汇总台账 → 报「不适用」，不报缺房（条数比/面积比 %s）"
              % {k: rs[0]["metric"][k] for k in ("row_ratio", "area_ratio")})
    else:
        print("  ✗ D2 粒度  汇总台账 **没认出**（报出 %s）" % ([r["title"] for r in rs][:3] or "空"))
        fails.append("D2 粒度 汇总台账")
    rs = d2_of(m_per_room_one_wrong)
    if any(r["metric"].get("n_missing") for r in rs) and not any("汇总行" in r["title"] for r in rs):
        print("  ✓ D2 粒度  逐间台账改错一号 → 照常报错（没被静音）")
    else:
        print("  ✗ D2 粒度  逐间台账改错一号 **被静音了**（报出 %s）" % [r["title"] for r in rs])
        fails.append("D2 粒度 逐间台账不被静音")
    # D7 并块的两侧守卫。★ 用**合成 ctx**，不去变异 c103 —— 这是实测教训：
    #   拿 c103 当基座时，"体量大但不该报"的负控抓到的是 c103 F1 **自己**那条真并块
    #   （`103-A-02-02` 1537.4㎡ 吞 7 间），负控永远"误报"，其实是基座自带缺陷在污染用例
    #   —— 与"假绿/假红"同一个根源：用例的基座必须干净。
    def synth(rooms):
        return {"name": "synth", "floors": [{"floor": 0, "rooms": rooms}]}

    def mk(rects):
        return [{"id": i, "number": "S-%02d" % i,
                 "poly": [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]}
                for i, (x0, y0, x1, y1) in enumerate(rects)]

    # 正控：5 间 10×10 + 1 间 100×100 盖住全场 ⇒ 必须报
    rs = check_merged_rooms(synth(mk([(0, 0, 10, 10), (20, 0, 30, 10), (0, 20, 10, 30),
                                      (20, 20, 30, 30), (40, 0, 50, 10),
                                      (-10, -10, 90, 90)]))) or []
    if rs:
        print("  ✓ D7 并块  一间吃住同层多间 → 变红（%s 吞 %d 间，%.0f 倍中位）"
              % (rs[0]["ids"][0], rs[0]["metric"]["n_swallowed"], rs[0]["metric"]["ratio"]))
    else:
        print("  ✗ D7 并块  **没变红 = 空断言**")
        fails.append("D7 并块")
    # 负控①：同样一大间（16 倍中位）但只吃住 1 间（< MERGE_N）⇒ 不许报
    rs = check_merged_rooms(synth(mk([(0, 0, 40, 40), (0, 0, 10, 10),
                                      (100, 100, 110, 110), (120, 100, 130, 110),
                                      (100, 120, 110, 130), (120, 120, 130, 130)]))) or []
    if rs:
        print("  ✗ D7 并块  **误报**：体量大但只吃住 1 间 → 不该报（%s）" % rs[0]["msg"][:60])
        fails.append("D7 大房间不误报")
    else:
        print("  ✓ D7 并块  体量大但没吃住好几间 → 不报（正确）")
    # 负控②：同层不足 5 间（小层/独层）⇒ 判据不适用，不许报
    rs = check_merged_rooms(synth(mk([(0, 0, 90, 90), (0, 0, 10, 10), (20, 20, 30, 30)]))) or []
    if rs:
        print("  ✗ D7 并块  **误报**：该层只有 3 间，判据不该适用（%s）" % rs[0]["msg"][:60])
        fails.append("D7 小层不误报")
    else:
        print("  ✓ D7 并块  该层不足 5 间 → 不适用，不报（正确）")
    # 负控③（★ 这条就是 bbox 版虚报 5 倍的回归守卫）：**走廊形** —— 一个 C 形/环廊
    #   包围住 5 间小房，它的 **bbox 盖住全场**、面积是该层中位的 28 倍，
    #   但它的**面积与任何一间房都不重叠**（房间落在它凹进去的缺口里）。
    #   bbox 版判据会报（实测全库虚报 83/99 条就是这么来的）；真几何版必须不报。
    #   对应现实：c006 F0 `6-A-01-09` 695.3㎡、c079 F1 `79-A-02-23` 107.1㎡ 都是这个形状。
    C = [[0, 0], [100, 0], [100, 100], [90, 100], [90, 10], [10, 10], [10, 100], [0, 100], [0, 0]]
    holes = [(20, 20, 30, 30), (40, 20, 50, 30), (60, 20, 70, 30),
             (20, 50, 30, 60), (40, 50, 50, 60)]
    rooms = [{"id": 0, "number": "廊", "poly": [[float(a), float(b)] for a, b in C]}]
    rooms += mk(holes)
    rs = check_merged_rooms(synth(rooms)) or []
    if rs:
        print("  ✗ D7 并块  **误报走廊形**：大而框住几间但零重叠 → 不该报（%s）" % rs[0]["msg"][:60])
        fails.append("D7 走廊形不误报")
    else:
        print("  ✓ D7 并块  走廊形（bbox 盖全场、交集为 0）→ 不报（正确；bbox 版会在这里虚报）")
    # 负控④：大房间只盖住每间邻居的 **50%**（< MERGE_IN）⇒ 不报。守 MERGE_IN 不被放松。
    rs = check_merged_rooms(synth(mk([(0, 0, 15, 20), (10, 0, 20, 10), (10, 10, 20, 20),
                                      (10, 20, 20, 30), (10, 30, 20, 40)]))) or []
    if rs:
        print("  ✗ D7 并块  **误报**：只盖住邻居 50%%，低于 %.2f ⇒ 不该报" % MERGE_IN)
        fails.append("D7 部分覆盖不误报")
    else:
        print("  ✓ D7 并块  只盖住邻居一半（< %.2f）→ 不报（正确）" % MERGE_IN)
    # D8 的两侧守卫：面积比这把尺必须能红；且**忠于图纸的走道不许红**（c079/c080 实测 1.00×）。
    def synth_led(rooms, ledger):
        return {"name": "synth", "ledger": ledger, "ledger_ok": True, "declared": None,
                "floors": [{"floor": 0, "rooms": rooms}]}

    def one(rects):
        return mk(rects)[0]

    def led1(poly):
        return [{"floor": 0, "number": "S-00", "boundary": [list(p) for p in poly]}]

    r0 = one([(0, 0, 10, 10)])                       # 交付 100㎡
    rs = check_ledger_area_mismatch(synth_led([r0], led1([[0, 0], [2, 0], [2, 5], [0, 5], [0, 0]])))
    if rs:
        print("  ✓ D8 面积比  交付 100㎡ / 台账 10㎡ → 变红（%.1f×）" % rs[0]["metric"]["ratio"])
    else:
        print("  ✗ D8 面积比  **没变红 = 空断言**")
        fails.append("D8 面积比不符")
    rs = check_ledger_area_mismatch(synth_led([r0], led1(r0["poly"]))) or []
    if rs:
        print("  ✗ D8 面积比  **误报**：交付与台账同一块 ⇒ 不该报")
        fails.append("D8 相符不误报")
    else:
        print("  ✓ D8 面积比  交付与台账同面积 → 不报（正确）")
    # 负控：**大而忠实的走道**（c079 F1 107.1㎡ / c080 F1 106.9㎡ 实测就是 1.00×）——
    #   它与交付同面积，图纸本来就这么画，识别是忠实的 ⇒ 必须不报（否则又去报 79 条走道）。
    big = one([(0, 0, 100, 50)])
    rs = check_ledger_area_mismatch(synth_led([big], led1(big["poly"]))) or []
    if rs:
        print("  ✗ D8 面积比  **误报忠实走道**：图纸同面积的大空间 → 不该报")
        fails.append("D8 忠实走道不误报")
    else:
        print("  ✓ D8 面积比  大而忠实（与台账同面积）→ 不报（正确）")
    # 负控：台账是**整栋汇总行**时 D8 必须跳过（没有逐间可比对象）——否则就是拿整翼对单间。
    def m_agg2(c):
        c["ledger"], c["ledger_ok"] = [], True
        for g in c["floors"]:
            pts = [p for r in (g.get("rooms") or []) for p in (r.get("poly") or [])]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            c["ledger"].append({"floor": g["floor"], "number": "整层汇总",
                                "boundary": [[min(xs), min(ys)], [max(xs), min(ys)],
                                             [max(xs), max(ys)], [min(xs), max(ys)]]})
    c2 = {"name": "s", "ledger": [], "ledger_ok": True, "declared": None,
          "floors": [{"floor": 0, "rooms": mk(
              [(0, 0, 10, 10), (20, 0, 30, 10), (0, 20, 10, 30),
               (20, 20, 30, 30), (40, 0, 50, 10)])}]}
    m_agg2(c2)
    rs = check_ledger_area_mismatch(c2) or []
    if rs:
        print("  ✗ D8 面积比  **误报**：汇总台账没有逐间可比对象（报出 %d 条）" % len(rs))
        fails.append("D8 汇总台账跳过")
    else:
        print("  ✓ D8 面积比  台账是整栋汇总行 → 跳过（正确，由 D2 出说明）")
    # D0 体量判据的守卫。★ 这条我**先写错过一次**：第一版让它"台账同号面积相符就不报"，
    #   把 c022 F0/F2（整层 1 间）静音了。用户 2026-09-14 指出「台账是一方面，建模的过程也是
    #   重要的，不能只看台账」—— 整层一间就是空盒子，台账相符只说明"图纸本来就没细分"，
    #   **不说明模型没问题**。所以现在：台账相符也照报（只是分成"图纸未细分"那种说明）。
    #   三个用例把三条支路钉死，并对「层内房间数」这条分档做正反两侧守卫。
    def mask(n):
        """错开的 n 间小房（都远小于 60% 轮廓），用来把层内房间数做到 n。"""
        return [(200 + 12 * i, 0, 208 + 12 * i, 8) for i in range(n)]

    def big_ctx(led, others=0):
        """轮廓 100×100 + 一间 80×80（占 64% > 60%）+ others 间小房（撑层内房间数）。"""
        return {"name": "synth", "ledger": led, "ledger_ok": True, "declared": None,
                "floors": [{"floor": 0, "outline": [[0, 0], [100, 0], [100, 100], [0, 100]],
                            "rooms": mk([(10, 10, 90, 90)] + mask(others))}]}

    def d0_of(c):
        return [r for r in (check_degenerate(c) or []) if "整层" in r["title"] or "体量" in r["title"]]

    def split_led(n):
        return led1([[0, 0], [n, 0], [n, n], [0, n], [0, 0]])

    # ① 整层 1 间、台账无行 ⇒ 必须报 ERROR 整层未切分
    rs = d0_of(big_ctx([]))
    if rs and rs[0]["sev"] == "ERROR":
        print("  ✓ D0 体量  整层 1 间、台账无行 → ERROR 整层未切分")
    else:
        print("  ✗ D0 体量  **没变红 = 空断言**（%s）" % (rs[0]["msg"][:70] if rs else "无记录"))
        fails.append("D0 整层未切分·无台账行")
    # ② 整层 1 间、台账**不符** ⇒ 必须报，且说明里点出"台账也不符"
    rs = d0_of(big_ctx(split_led(10)))          # 台账 100㎡ vs 交付 6400㎡ = 64×
    if rs and rs[0]["sev"] == "ERROR" and "台账也不符" in rs[0]["msg"]:
        print("  ✓ D0 体量  整层 1 间、台账 100㎡ vs 6400㎡（64 倍）→ ERROR，且注明台账也不符")
    else:
        print("  ✗ D0 体量  **没变红或没注明台账不符**（%s）" % (rs[0]["msg"][:70] if rs else "无记录"))
        fails.append("D0 整层未切分·台账不符")
    # ③ ★ 核心守卫（用户指正的那一点）：台账**相符**（80×80 对 80×80）⇒ **照样要报**，
    #    只把说明改成"图纸本身就没细分"。这里若变成"不报"就是我又把建模问题静音了。
    rs = d0_of(big_ctx(split_led(80)))
    if rs and rs[0]["sev"] == "ERROR" and "本身就没细分" in rs[0]["msg"]:
        print("  ✓ D0 体量  整层 1 间、**台账相符** → 仍报 ERROR（注明图纸本身未细分）")
    else:
        print("  ✗ D0 体量  **台账相符就静音了**（用户明确反对「只看台账」）：%s"
              % (rs[0]["msg"][:70] if rs else "无记录"))
        fails.append("D0 台账相符仍须报整层未切分")
    # ④ 反侧：层内房间数**够多**（8 间 + 一间 64%）⇒ 只能出 WARN 体量异常，不许判"整层未切分"
    rs = d0_of(big_ctx([], others=7))
    if rs and rs[0]["sev"] == "WARN":
        print("  ✓ D0 体量  层内 8 间、一间占 64% → WARN 体量异常（不误判整层未切分）")
    else:
        print("  ✗ D0 体量  **分档错了**：层内 8 间却出 %s"
              % (rs[0]["sev"] if rs else "无记录"))
        fails.append("D0 层内房间数分档")
    # 反向用例：这些用例变红就是**误报**（判据把正常数据也判了）
    for fn, label, c in [(fn, lb, mut(m)) for fn, lb, m in neg_cases]:
        try:
            got = fn(c) or []
        except Exception as e:                                       # noqa: BLE001
            got = [{"code": "异常", "msg": str(e)}]
        if got:
            print("  ✗ %-24s **误报** → %s" % (label, got[0].get("msg", got[0])[:90]))
            fails.append(label)
        else:
            print("  ✓ %-24s 不报（正确）" % label)
    # 负控：未变异的原始数据上跑一遍，把命中**如实打出来**。
    # ★ 这里不写"应该是几条" —— 我上一版就在这句里写死了「c103 D4 应为 1」，而实测是 0：
    #   c103 交付的 F0 只有 8 间（F1 的副本），并集本来就落在轮廓里；真正缺的是
    #   「台账 31 间 vs 交付 8 间」= D2 管的事。**预测写进断言里就会变成假的预期**。
    base_recs = [r for fn in CHECKS for r in (fn(base_ctx) or [])]
    by = Counter(r["code"] for r in base_recs)
    print("  · 负控/实测：原始 %s 上命中 %s"
          % (name, dict(sorted(by.items())) or "无"))
    for r in base_recs:
        if r["code"] == "D2":
            print("      D2 f%s：交付 %d / 台账 %d（缺 %d、多 %d）"
                  % (r["floor"], r["metric"]["n_have"], r["metric"]["n_want"],
                     r["metric"]["n_missing"], r["metric"]["n_extra"]))
    print("\n%s" % ("全部判据都能变红 ✓" if not fails else
                    "★ 有 %d 条判据没变红（空断言）：%s" % (len(fails), fails)))
    return 1 if fails else 0


# ----------------------------------------------------------------- 出图
def shots(name, recs, ctx, only_error=True):
    """命中层的对照图：轮廓(红) + 墙(灰) + 房间(命中填红/其余蓝虚线)，并标出 pos。

    默认**只画有 ERROR 的层** —— 341 条 WARN 里 I17×140 / I11×87 是整仓待办，
    全画出来会有几百张图，把 73 条可操作 ERROR 淹掉（这正是用户抱怨"看不见"的成因）。
    要看全部加 `--shots-all`。

    这是**唯一不需要标定**的出图路线：图形直接在世界坐标里画（房间/墙/轮廓都是同一
    坐标系的交付几何），所以不存在「世界坐标 → PNG 归一化」那一步 —— 交付图
    `dxf_plan/*.png` 是 `_dxf_cad_render.py` 用 `bbox_inches="tight"` 出的，
    PNG 范围 ≠ axes limits，往那上面叠机器框必须让渲染器吐 sidecar，本脚本不碰那条线。
    返回本次生成的文件名列表（供 index.json 与网页引用）。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt                                  # noqa: E402
    # 中文字体：与 _dxf_cad_render.py:20、_scratch/render_floor_pngs.py:33 同一套写法。
    # 不设就是**标题全是方框**（实测第一版 c103_F0.png 的标题 `命中：D1、D2` 全糊成 □），
    # 一张读不出字的缺陷图等于没出。
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DengXian"]
    plt.rcParams["axes.unicode_minus"] = False

    def keep(r):
        if r["building"] != name or r["sev"] == "INFO":
            return False
        return (not only_error) or r["sev"] == "ERROR"

    hit = defaultdict(set)
    pos = defaultdict(list)
    for r in recs:
        if not keep(r):
            continue
        hit[r["floor"]].add(r["code"])
        if r.get("pos"):
            pos[r["floor"]].append((r["code"], r["pos"]))
    # 全楼命中（floor=None，如 D1 跨层/D3）时画到所有层
    allf = {g["floor"] for g in ctx["floors"]}
    for r in recs:
        if keep(r) and r["floor"] is None:
            for f in allf:
                hit[f].add(r["code"])
    if not hit:
        print("  %s 无可操作命中，不出图" % name)
        return []
    os.makedirs(SHOT_DIR, exist_ok=True)
    made = []
    for g in ctx["floors"]:
        F = g["floor"]
        if F not in hit:
            continue
        fig, ax = plt.subplots(figsize=(13, 10))
        for w in (g.get("walls") or []):
            p = [(q[0], q[1]) for q in (w.get("poly") or [])]
            if len(p) > 1:
                ax.plot([q[0] for q in p], [q[1] for q in p], color="#c8c8c8", lw=0.7, zorder=1)
        codes = sorted(hit[F])
        # 该层要标红的房号：本层命中的 ids + **全楼命中(floor=None)记录的 ids**
        # （后者原先被 `rr["floor"] == F` 挡掉，于是 c103 F0 那张图上一个红房间都没有 ——
        #   跨层重复 900035@[0,1] 恰恰要在这两层上都标出来）
        badset = set()
        for rr in recs:
            if not keep(rr):
                continue
            if rr["floor"] is None or rr["floor"] == F:
                badset.update(str(i) for i in (rr.get("ids") or []))
        for r in (g.get("rooms") or []):
            p = [(q[0], q[1]) for q in (r.get("poly") or [])]
            if len(p) < 3:
                continue
            bad = str(r.get("number")) in badset
            col = "#d81b60" if bad else "#1565c0"
            ax.plot([q[0] for q in p] + [p[0][0]], [q[1] for q in p] + [p[0][1]],
                    color=col, lw=1.0, ls="-" if bad else "--",
                    alpha=1.0 if bad else 0.45, zorder=3 if bad else 2)
            if bad:
                c = Q._poly(p).centroid
                ax.text(c.x, c.y, "%s" % r.get("number"), fontsize=6,
                        ha="center", va="center", color=col, zorder=6)
        o = [(q[0], q[1]) for q in (g.get("outline") or [])]
        if len(o) > 2:
            ax.plot([q[0] for q in o] + [o[0][0]], [q[1] for q in o] + [o[0][1]],
                    color="#d00000", lw=1.8, zorder=5)
        for code, p in pos.get(F, []):
            ax.plot(p[0], p[1], marker="x", ms=9, mew=2, color="#ff6d00", zorder=7)
            ax.text(p[0], p[1], code, fontsize=8, color="#ff6d00", zorder=7)
        ax.set_title("%s F%d 命中：%s" % (name, F, "、".join(codes)), fontsize=12)
        ax.set_aspect("equal", adjustable="box")
        ax.axis("off")
        fn = "%s_F%d.png" % (name, F)
        fig.savefig(os.path.join(SHOT_DIR, fn),
                    dpi=88, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        made.append(fn)
    # 撤掉本楼**这次没再生成**的旧图：缺陷修好后旧图会留在目录里冒充现状
    # （与「续渲按文件名认完成度」同族的坑：目录只能反映最后一次扫描的结论）。
    for stale in sorted(x for x in os.listdir(SHOT_DIR)
                        if x.startswith(name + "_F") and x.endswith(".png")
                        and x not in made):
        try:
            os.remove(os.path.join(SHOT_DIR, stale))
        except OSError:
            pass
    print("  → %s/%s_F*.png（%d 张）" % (SHOT_DIR, name, len(made)))
    return made


# ----------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    deep = "--deep" in args
    do_self = "--selftest" in args
    args = [a for a in args if not a.startswith("--")]
    if do_self:
        return selftest()

    shots_mode = "--shots" in sys.argv
    only_error = "--shots-all" not in sys.argv
    names = args or sorted(d for d in os.listdir(BASE)
                           if os.path.isdir(os.path.join(BASE, d))
                           and os.path.exists(os.path.join(BASE, d, "profile.json")))
    verbose = bool(args)
    os.makedirs(QA_DIR, exist_ok=True)
    allrecs = []
    made = []
    for nm in names:
        try:
            ctx, recs = scan(nm, deep=deep)
        except Exception as e:                                       # noqa: BLE001
            print("  %-8s 扫描异常 %s: %s" % (nm, type(e).__name__, e))
            continue
        allrecs.extend(recs)
        per = Counter((r["code"], r["sev"]) for r in recs if r["sev"] != "INFO")
        nerr = sum(v for (c, s), v in per.items() if s == "ERROR")
        nwarn = sum(v for (c, s), v in per.items() if s == "WARN")
        tag = "✓" if not per else " "
        print("  %s %-8s 层%-3d  ERROR %-3d WARN %-3d  %s"
              % (tag, nm, len(ctx["floors"]), nerr, nwarn,
                 "、".join("%s×%d" % (c, v) for (c, s), v in sorted(per.items()) if s == "ERROR")))
        if verbose:
            for r in recs:
                if r["sev"] == "INFO":
                    continue
                print("      [%s] %-4s f%-4s %s" % (r["sev"], r["code"],
                                                    r["floor"], r["msg"][:110]))
        if shots_mode:
            made.extend(shots(nm, recs, ctx, only_error=only_error))

    if shots_mode:
        # 图索引：网页靠它决定哪一层有对照图，避免 <img> 404 破图。
        # 目录里可能还有别的楼上次留下的图 ⇒ 索引按**目录实际存在**来写（自洽，不靠预测）。
        idx = sorted(x for x in os.listdir(SHOT_DIR) if x.endswith(".png")) \
            if os.path.isdir(SHOT_DIR) else []
        t2 = os.path.join(SHOT_DIR, "index.json") + ".tmp"
        with open(t2, "w", encoding="utf-8") as fh:
            json.dump({"shots": idx, "made": len(made)}, fh, ensure_ascii=False, indent=1)
        os.replace(t2, os.path.join(SHOT_DIR, "index.json"))
        print("  对照图共 %d 张 → %s" % (len(idx), os.path.join(SHOT_DIR, "index.json")))

    tmp = OUT_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(allrecs, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_JSON)

    per = summary(allrecs)
    rows = sorted(per.items(), key=lambda kv: (-kv[1].get("ERROR", 0), -kv[1].get("WARN", 0),
                                               kv[0]))
    act, sysm = triage(allrecs, len(names))
    lines = ["# 缺陷总表（scan_defects.py 自动生成）", "",
             "共 %d 栋。**先看「一、要动手的」**；「二、系统性」是整仓待办，"
             "不是某一栋的新信号。" % len(names), "",
             "级别列的 `1E/10W` = 该码 1 条 ERROR、10 条 WARN（条目列是两者之和）。", "",
             "## 一、要动手的（命中栋数少 ⇒ 逐栋可修）", "",
             "| 码 | 级别 | 条目 | 命中栋数 | 说明 | 样例 |", "|---|---|---|---|---|---|"]
    for r in act:
        sev = _sevlabel(r["sev"])
        lines.append("| %s | %s | %d | **%d** | %s | %s |" % (
            r["code"], sev, r["recs"], r["prevalence"],
            "、".join(r["buildings"][:6]) + ("…" if len(r["buildings"]) > 6 else ""),
            r["sample"].replace("|", "/")))
    lines += ["", "## 二、系统性（命中 ≥1/3 栋，或 qa_structural 标注 by design）", "",
              "| 码 | 级别 | 条目 | 命中栋数 | by design | 样例 |", "|---|---|---|---|---|---|"]
    for r in sysm:
        sev = _sevlabel(r["sev"])
        lines.append("| %s | %s | %d | %d | %s | %s |" % (
            r["code"], sev, r["recs"], r["prevalence"],
            "是" if r["by_design"] else "", r["sample"].replace("|", "/")))
    lines += ["", "## 三、逐栋", "", "| 楼 | ERROR | WARN | 命中的判据 |", "|---|---|---|---|"]
    for nm, d in rows:
        if not d.get("ERROR") and not d.get("WARN"):
            continue
        lines.append("| %s | %d | %d | %s |" % (
            nm, d.get("ERROR", 0), d.get("WARN", 0),
            "、".join("%s×%d" % (c, v) for c, v in sorted(d["codes"].items()))))
    clean = [nm for nm, d in rows if not d.get("ERROR") and not d.get("WARN")]
    lines += ["", "干净（0 ERROR/0 WARN）：**%d** 栋%s" % (
        len(clean), ("：" + "、".join(clean)) if clean else ""), "",
        "判据码：D0 退化／D1 重复／D2 台账（先判粒度）／D3 缺层／D4 同构层错帧／"
        "D5 台账哨兵／D6 房间属别层(需 --deep)／D7 并块（一间**真盖住**同层多间，真几何）／"
        "D8 交付面积 vs 台账同号面积比（≥2× 或 ≤0.5×，台账汇总的楼跳过）／"
        "I1–I18 见 qa_structural.py"]
    tmp = OUT_MD + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, OUT_MD)

    nerr = sum(1 for r in allrecs if r["sev"] == "ERROR")
    nwarn = sum(1 for r in allrecs if r["sev"] == "WARN")
    print("\n合计 %d 栋：ERROR %d 条 / WARN %d 条" % (len(names), nerr, nwarn))
    print("\n一、要动手的（命中栋数少）：")
    for r in act:
        print("   %-4s %-9s %3d 条 / %2d 栋  %s"
              % (r["code"], _sevlabel(r["sev"]), r["recs"], r["prevalence"],
                 "、".join(r["buildings"]) if len(r["buildings"]) <= 8
                 else "、".join(r["buildings"][:8]) + "…"))
    print("\n二、系统性（整仓待办，不是某栋的新信号）：")
    for r in sysm:
        print("   %-4s %-9s %3d 条 / %2d 栋  %s"
              % (r["code"], _sevlabel(r["sev"]), r["recs"], r["prevalence"],
                 "(qa_structural 标注 by design)" if r["by_design"] else ""))
    print("\n→ %s\n→ %s" % (OUT_JSON, OUT_MD))
    return 0


if __name__ == "__main__":
    sys.exit(main())
