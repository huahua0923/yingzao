# -*- coding: utf-8 -*-
r"""构件库 · 参数化模块。**唯一参数入口 = `rebuild/构件库/参数.json`**。

为什么要这个文件：用户报了三处构件不对（门上面缺、楼梯样式不对、电梯不对），而这三处的
尺寸当时**散落在 `build3d.py` 的十几个模块级常数里**（`DOOR_H` / `GOING_MM` / `WELL_GAP_MM` /
`LANDING_T_M` / `LIFT_T_MM` …），没有一处能回答「该长什么样、我们建的差在哪」。
现在尺寸只有这一份，且**每条都带出处与标注**（实测 / 假设 / 规范 / 旧规范 / 待坐实）——
★ 第 5 个「旧规范」是 2026-10-15 加的：调研回来一批值**有图集出处但那一版已被替代**
  （03G322-1 已被 13G322-1～4 取代）。塞进「规范」是高估（会被当现行要求引用），
  塞进「假设」是低估（明明有出处）—— 所以单开一档：有出处、但不是现行。
这是铁律 018（两个地方写同一个数，一致证明不了它是对的）的正面对策。

★ 本模块只依赖 `shapely` + 标准库，**不 import `build3d`**（否则循环），也不碰
  `trimesh` / `cv2` ⇒ 判据与页面都能轻量地 import 它。

★ 一条**故意没做**的事（写在明处）：`build3d.stair_steps()` 那 ~250 行梯段聚拢逻辑
  **没有**搬进来。它和 `recognize.group_flights` 的判据咬在一起，搬动等于把整链入口闸
  押在一次纯搬家上，而几何一个字都不变。现在只把它的**参数与栏杆**抽到这里 ——
  真正的收益（参数只在一处、栏杆可调）已经拿到。

对外三件：
  `lintel_module(walls, leaves, h_mm)`  → 门头墙 `[(poly, z_rel_m, h_m)]` + 记账
  `rail_strips(...)` / `side_is_walled(...)` → 一段梯段某一侧的栏杆带
  `write_duizhao(rows)`                 → 写 `构件库/对照.json`（字节层）
"""
import io
import json
import math
import os
import sys
import time

import shapely.geometry as sg
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                    # rebuild/
PARAM = os.path.join(ROOT, "构件库", "参数.json")
DUIZHAO = os.path.join(ROOT, "构件库", "对照.json")

_FIELDS = ("值", "单位", "标注", "区间", "出处", "作用")
_MARKS = ("实测", "假设", "规范", "旧规范", "待坐实")

_cache = None


# ------------------------------------------------------------------ 读
def check(d, path="<内存>"):
    r"""schema 自检：只查**形状**，不查数值对不对（数值对不对是判据 J-10.9-02 的事）。

    ★ 三条硬规矩：
      ① 字段必须齐（缺字段的参数会一路变成 `KeyError` 或更糟的 `None`）；
      ② 标「实测」「规范」的**必须给得出出处** —— 没出处的「实测」是手打数；
      ③ 标「待坐实」的**不许有值** —— 「我记得是 280」不算坐实（铁律 103）。
    """
    bad = []
    for cat, block in (d.get("构件") or {}).items():
        for name, spec in block.items():
            miss = [k for k in _FIELDS if k not in spec]
            if miss:
                bad.append("%s/%s 缺字段 %s" % (cat, name, miss))
            mk = spec.get("标注")
            if mk not in _MARKS:
                bad.append("%s/%s 标注=%r 不在 %s" % (cat, name, mk, list(_MARKS)))
                continue
            if mk in ("实测", "规范", "旧规范") and spec.get("值") is not None \
                    and not str(spec.get("出处") or "").strip():
                bad.append("%s/%s 标「%s」却没写出处" % (cat, name, mk))
            if mk == "待坐实" and spec.get("值") is not None:
                bad.append("%s/%s 标「待坐实」却带着值 %r —— 坐实前不许有值"
                           % (cat, name, spec.get("值")))
    if bad:
        raise ValueError("%s 自检不过（%d 条）：\n  " % (path, len(bad))
                         + "\n  ".join(bad))
    return d


def load(fresh=False):
    """读参数.json（带缓存）。★ 缓存的是**自检过的**对象。"""
    global _cache
    if _cache is not None and not fresh:
        return _cache
    with io.open(PARAM, encoding="utf-8") as f:
        d = json.load(f)
    check(d, PARAM)
    _cache = d
    return d


def spec(cat, name):
    """取某个参数的**整个对象**（含标注与出处）—— 对照页要靠它把「假设」标出来。"""
    s = ((load().get("构件") or {}).get(cat) or {}).get(name)
    if s is None:
        raise KeyError("参数.json 里没有 构件.%s.%s" % (cat, name))
    return s


def p(cat, name):
    """取参数**值**。

    ★ 取不到就**抛异常**，绝不返回 `None`。静默的 None 会一路变成 0（或 NaN）然后
      在几何里表现为「这个构件本来就没有」—— 与「参数忘了填」同形（铁律 199）。
    """
    s = spec(cat, name)
    v = s["值"]
    if v is None:
        raise ValueError("构件.%s.%s 标的是「%s」，还不能拿来算。出处：%s"
                         % (cat, name, s["标注"], s["出处"]))
    return v


def mark(cat, name):
    """标注（实测/假设/规范/待坐实）—— 页面与判词都要照它写，不许自己编一个口径。"""
    return spec(cat, name)["标注"]


def _mm(cat, name):
    return float(p(cat, name))


# ------------------------------------------------------------------ 几何小工具
def polys_of(geom):
    """任意 shapely 几何 → 多边形列表（把 GeometryCollection / MultiPolygon 摊平）。

    ★ 为什么要这个：`intersection` / `difference` 的结果类型**由输入决定**，
      有时是 Polygon、有时是 GeometryCollection（还夹着 LineString）——
      直接拿去 `_extrude` 会在最后一个元素上炸（铁律 199：崩了与没量到要分开写）。
    """
    if geom is None or geom.is_empty:
        return []
    t = geom.geom_type
    if t == "Polygon":
        return [geom] if geom.area > 0 else []
    if t in ("MultiPolygon", "GeometryCollection"):
        out = []
        for g in geom.geoms:
            out.extend(polys_of(g))
        return out
    return []


def thin_open(poly, r):
    r"""**开运算**（先缩 r 再胀 r）削掉比 `2r` 还薄的部分 → 单块列表（可能为空/多块）。

    ★ 为什么要这一步（2026-10-15 实测）：`缺口 ∩ 超出门扇 ∩ 离墙上限` 是**三条不同偏移曲线**
      的交（栅格轮廓的台阶边 + `keep` 的斜接边 + `near` 的斜接边），近乎相切处会切出碎边 ——
      实测 地下1层 8 块 / 1层 32 块 / 2层 27 块带 < 6.25 mm 的边（最短 1.500 mm），
      低于入口闸 J-10.8-00 的 ⑪ 阈值，而 SU 对碎边会**自旋挂死**（`su_step2_build.rb`
      的 clean_ring 注释记着这个失败模式）。

    ★★ 试过两条没走通的路，都留在这儿免得下一个人重走（铁律 183）：
      ① **闭运算**（先胀后缩）**对这类碎边是盲的** —— δ 从 1 试到 16，那条 1.5 mm 的边
         一字不动（它不是凹槽，是两条近乎共线的长边之间夹的**薄舌尖**）；
      ② **按最小面积损失逐个删折点**（自己写的那版）**会把件改坏** —— 删掉舌尖的两个端点
         之后，剩下两条边在同一条直线上**来回走**，环退化成零宽针 ⇒ 1层 出现 21 个
         「6 个点只有 4 个互异、面积 0.000」的环，比原病更糟。DELETE 掉折点 ≠ 削掉舌尖。
      ⇒ 只有**开运算**是对的：它把「薄」这件事当成几何本身削掉，不是当成顶点问题。

    实测代价（δ=4，12 层全量）：**零碎边**；每层丢 9–11 块**整块比 8 mm 还薄的**薄片
    （那不是门头，是三条偏移曲线相切留下的渣）；少数块被切成 2 块。丢掉的块**必须记账**。
    """
    q = poly.buffer(-r, join_style=2).buffer(r, join_style=2)
    return [g for g in polys_of(q) if g.area > 0]


def min_edge(poly):
    """环的最短边长（mm）。**含洞环**——洞上的碎边一样会让 SU 挂。"""
    m = float("inf")
    for rr in [poly.exterior] + list(poly.interiors):
        c = list(rr.coords)
        for i in range(len(c) - 1):
            d = math.hypot(c[i + 1][0] - c[i][0], c[i + 1][1] - c[i][1])
            if d < m:
                m = d
    return m


def heal_short_edges(poly, floor_mm, tol_max=16.0, area_max=50.0):
    r"""把环上短于 `floor_mm` 的碎边用 **Douglas-Peucker 简化**收掉 → `(poly, 改了没, 最小边)`。

    ★★ 为什么开运算之后还要这一道（2026-10-15 实测）：`thin_open` 只能在**薄**这个维度上
      削东西，它对**凹角上的斜切**是恒等的 —— 缩 r 把角切深、胀 r 再斜接回来，逐位还原。
      实测的就是这种角：`near` 在墙带轮廓的 45° 阶梯凸角上做斜接/斜切，切出**一段 45° 的
      短边**（1层 5.0253 mm = 3.6·√2；2层 2.5456 mm = 1.8·√2），而**块就是被这条边切的**
      ⇒ 短边直接进环。清边半径从 2 扫到 12，那条边一字不动（恒等）就是证据。
      ★ 换连接方式只是换一个角犯病：`near` 用 mitre ⇒ 1层 22 块坏；换 bevel ⇒ 1层 0 坏、
        2~4层 6 块坏。**同一个错法换个函数仍会再犯**（铁律 183），所以收口放在**最后**。

    ★ 为什么不自己删折点：那一版实测把环退化成零宽针（见 `thin_open` 的 docstring）。
      这里用 shapely 自己的 `simplify(preserve_topology=True)`，而且**逐块验证**：
        · 结果非空、是单个 Polygon、`is_valid`（不会自交）；
        · 最短边**确实** ≥ `floor_mm`（不是"大概"）；
        · 面积变化 ≤ `area_max` mm²（收掉一段 5 mm 斜切约 6 mm²，而真门头 ≳ 1.6e5 mm²）。
      任一条不满足就把 `tol` 乘 1.5 再试，试到 `tol_max` 还不成就**原样返回**并且**如实报**
      （第三项返回值 = 没治好时的真实最短边）。**不许静默改件**。
      ★ `area_max` 是**绝对数与万分之一取大**：实测 2/3/4 层各有 2 块缝合后的大块（94 万 mm²），
        tol=3.125 收掉斜切的同时也会削掉墙带轮廓的 25 mm 台阶尖，面积变化 **133 mm²**
        （占 0.014%）—— 拿 50 mm² 的绝对线卡它，就会把「治得好」误报成「治不好」。
        万分之一那条线对 94 万 mm² 的块 = 94 mm²，仍卡得住 688 mm²（tol=10.547）那种越治越大的。
    """
    if poly is None or poly.is_empty:
        return poly, False, 0.0
    m0 = min_edge(poly)
    if m0 >= floor_mm:
        return poly, False, m0
    # ★★ 2026-10-15 第三次放宽：`lim` 再加一条**由分辨率推出来**的绝对线 `8·floor²`（= RES²/2，
    #    RES = 4·floor —— 闸 ⑪ 的阈值 6.25 就是 RES/4，同一个 RES）。
    #    为什么：上面那条 `1e-4·面积` 的**形状是错的** —— 碎边收口要动多大面积，与块多大**无关**，
    #    它被**分辨率**卡死（一次最多啃掉墙带上一个 25 mm 台阶）。
    #    实测（230571 mm² 的门头块，224 扇线弧门带出来的那批）：tol=3.125 **就治好**（残最短边
    #    2.5126 → 35.3553 = 25√2），**面积只动 92.0 mm² = 0.040%**，而当时 lim = max(50, 23) = 50
    #    ⇒ 被误判「治不好」，2 块原样进环、把入口闸 ⑪ 拦红。再往上扫到 tol=15.82 才动 533 mm²
    #    （那才是**真的**削掉了 25√2 那道台阶，该拒）。
    #    ⇒ `lim = max(50, 1e-4·面积, 8·floor²) = 312.5`：收得下 92（3.4 倍余量）与本文档记的 133，
    #      仍卡得住 533/688 那种越治越大的。放宽只会让它在**更小的 tol** 上接受 ⇒ 形变更小。
    lim = max(area_max, 1e-4 * poly.area, 8.0 * floor_mm * floor_mm)
    tol = floor_mm / 2.0
    while tol <= tol_max:
        q = poly.simplify(tol, preserve_topology=True)
        if (not q.is_empty and q.geom_type == "Polygon" and q.is_valid
                and abs(q.area - poly.area) <= lim
                and min_edge(q) >= floor_mm):
            return q, True, min_edge(q)
        tol *= 1.5
    return poly, False, m0


def write_duizhao(rows, extra=None):
    r"""写 `构件库/对照.json`。

    ★ **字节层写盘**（铁律 79）：文本模式在 Windows 上会把 `\n` 翻成 `\r\n`，
      文件每行 +1 字节，读起来像「写好了」。
    """
    d = {"schema": "构件对照 · 生成物（由 parts_lib.write_duizhao 写出；页面只读它）",
         "生成时刻": time.strftime("%Y-%m-%d %H:%M:%S"),
         "层": [r["层"] for r in rows],
         "构件": rows}
    if extra:
        d.update(extra)
    blob = json.dumps(d, ensure_ascii=False, indent=2, sort_keys=False)
    tmp = DUIZHAO + ".tmp"
    with io.open(tmp, "wb") as f:
        f.write(blob.encode("utf-8"))
    os.replace(tmp, DUIZHAO)
    return DUIZHAO, len(blob.encode("utf-8")), d["生成时刻"]


# ------------------------------------------------------------------ 门头墙
def lintel_module(walls, leaves, h_mm, r=None, keep_r=None, door_h_mm=None,
                  near_wall=None, diag=None):
    r"""门头墙 = （闭运算从墙带里补出来的那块）∩（门扇外扩 `keep_r` 以内）。

    ★ 为什么锚在**门扇**上，而不是锚在「墙带上的断口」上 —— 这是量了三轮才定下来的
      （`rebuild/_scratch/probe_doorgap.py` 的 docstring 留着三把作废的尺子）：

      实测（1层/3层，1014 扇门）：墙带是**栅格掩膜的轮廓**（`redraw.geometry` 里
      `cv2.findContours(wmask, RETR_CCOMP)` 的产物），它的**内洞就是房间**。
      所以「门那里那道缺口」在几何上不是一个孤立的断口，而是**房间轮廓上的一段**。
      直接对墙带做闭运算，补出来的是**任何** ≤ 2r 的空档 —— 连房间与房间之间的
      隔断间距都算：v1 尺子实测 1层 r=800 补出 **510 个「不含门」的块**，长边
      33.4 / 24.4 / 22.2 m，而且各档 r 之间**不单调**。

      ⇒ 加一道**只有门才有**的约束：落点必须落在门扇外扩 `keep_r` 之内。
        这个约束是**构造保证**的：走道上没有门扇 ⇒ 闭运算无论补出什么，都留不下来。
        （★★ 2026-10-15 **更正**：本文件早先写着「门扇 = 门扇 + 四分之一圆开启弧的最小
          外接矩形，恒为正方形 731×731」—— **实测是错的**。1 层 142 扇门里 136 扇的面积
          **恒为 27422 mm² = 731.25 × 37.5**，就是一个**垂直于墙面、伸进房间的薄板**，
          没有那道弧。所以门扇沿墙方向只占 37.5 mm ⇒ `keep_r` 必须够大（600），
          否则补出来的门头只有 800 mm 宽，比 2700 的门洞窄一大截；
          而「填不到走道」不是靠 `keep_r` 小来保证的，是靠「有门才填」这个构造。）

    入参：`walls` = 墙带多边形们（mm）；`leaves` = 门扇多边形们（mm）；`h_mm` = 层高。
    返回：`([(poly, z_rel_m, h_m)], diag)`，`z_rel_m` = 底面相对层底（米），
          契约与 `build3d.stair_steps` **逐字段相同**。

    ★ `diag` 里的数**必须往上报**（铁律 158）：补出来的缺口有几个、其中几个真的有门、
      超限丢掉几个。少一个字段，下一个人就会以为「补出来的都有门」。
    """
    r_ = float(r if r is not None else _mm("门", "门头墙_闭环半径"))
    kr = float(keep_r if keep_r is not None else _mm("门", "门头墙_超出门扇"))
    nw = float(near_wall if near_wall is not None else _mm("门", "门头墙_离墙上限"))
    clean = _mm("门", "门头墙_清边半径")
    edge_floor = _mm("共用", "环_最短边下限")
    min_blk = float(p("门", "门头墙_最小块"))
    seam = float(_mm("门", "门头墙_缝合"))
    dh = float(door_h_mm if door_h_mm is not None else _mm("门", "洞高"))
    leaf_mm = _mm("门", "门扇长")
    box = diag if diag is not None else {}

    W = unary_union([w for w in (walls or []) if w is not None and not w.is_empty])
    L = unary_union([x for x in (leaves or []) if x is not None and not x.is_empty])
    if W.is_empty or L.is_empty:
        box.update({"缺口": 0, "含门": 0, "无门": 0, "块": 0, "超限丢弃": 0,
                    "说明": "没有墙带或没有门扇 ⇒ 不补"})
        return [], box

    # 闭运算：先胀 r 再缩 r —— 直角件用 mitre（join_style=2），补出来的块才是方的
    closed = W.buffer(r_, join_style=2).buffer(-r_, join_style=2)
    gaps = polys_of(closed.difference(W))

    keep = L.buffer(kr, join_style=2)
    # ★★ 门头墙**必须落在墙带厚度范围内**：闭运算补出来的块会连带把房间区域一起补进来
    #    （r=1800 时 1 层实测有一块 2.2 m² 的，正是门 #2/#3/#4 那个 2700 洞口共用的），
    #    所以再乘一道「离墙带 ≤ nw」。补出来的槽（墙厚那一档，实测 240）留得住，
    #    伸进房间的部分被切掉。
    # ★★ 这一道**必须用 bevel(3)，不许用 mitre(2)**（2026-10-15 实测，这是入口闸 ⑪ 的最后
    #    一个卡点）：`near` 只是把块**夹到墙带附近**的一道掩膜，它的角长什么样本来就无所谓；
    #    可是 mitre 在这些角上会切出 **5.0253 mm 的 45° 斜切**（实测 1 层 22 块中招）。
    #    斜切的来历：W 的轮廓是**45° 阶梯**（墙本身斜着走，`4.2墙体` 轮廓上有
    #    35.355=25√2、106.066=75√2 这种段），`W.buffer(250, join_style=2)` 在阶梯的
    #    凸角上做斜接，斜接边被相邻的短段挤住 ⇒ 落成一小段 45° 边，**而这块边是块的
    #    边界**（块在 near 边上被切），于是 5.0253 就成了环上的最短边，低于 6.25。
    #    两个反证：① `mitre_limit` 从 5 调到 100 **一字不动** ⇒ 不是 GEOS 的斜接上限；
    #    ② 清边半径从 2 扫到 12，**最短边恒为 5.0253**（1 层 22 块）—— 因为这是个**凹角**，
    #       而开运算在凹角上是恒等（缩 r 把角切深、胀 r 再斜接回来，逐位还原）。
    #    实测四选一（1 层，判据 = 环最短边 < 6.25 的块数）：
    #      mitre 22 坏 / round(qs=8) 5 坏 / **bevel 0 坏** / round(qs=2) 0 坏；
    #      四者块数**同为 139** ⇒ 换连接方式**不动覆盖**（不是拿"少建几块"换来的绿）。
    #    取 bevel：它的斜切长度 ∝ nw（250），够长；round 要挑 quad_segs，多一个旋钮。
    near = W.buffer(nw, join_style=3)
    # ★ 面积上限：一个门头墙再大也不该超过「门扇 + 两侧各 keep_r」×（2·keep_r）
    cap = (leaf_mm + 2.0 * kr) * (2.0 * kr)
    pieces, over, hit = [], 0, 0
    pre = []
    # ★ 清边的账**分两趟各记一份**（铁律 174：两次不同处置不能共用一个计数，
    #   否则「缝合后清掉的」与「缝合前清掉的」长得一模一样，看不出是哪一步在削件）。
    thin1 = {"丢块": 0, "丢面积": 0.0, "裂块": 0, "改面积": 0}
    thin2 = {"丢块": 0, "丢面积": 0.0, "裂块": 0, "改面积": 0}

    # ★ 清碎边（`门头墙_清边半径`）：布尔交是**三条不同偏移曲线**的交 —— 栅格轮廓的
    #   台阶边 + `keep` 的斜接边 + `near` 的斜接边。三者近乎相切处会切出小折，低于入口闸
    #   ⑪ 的阈值 6.25 mm，而 SU 对碎边会**自旋挂死**（`su_step2_build.rb` 的 clean_ring
    #   注释记着这个失败模式）。做法与两条走不通的路见 `thin_open` 的 docstring。
    def _clean(ps, acc):
        out = []
        for s in ps:
            qs = thin_open(s, clean)
            if not qs:
                # 整块比 2·clean 还薄 ⇒ 它不是门头，是偏移曲线相切留下的渣。记账丢掉。
                acc["丢块"] += 1
                acc["丢面积"] += s.area
                continue
            if len(qs) > 1:
                acc["裂块"] += 1
            for q in qs:
                if q.area < s.area - 1.0 or len(qs) > 1:
                    acc["改面积"] += 1
                out.append(q)
        return out

    def _cap(ps):
        """面积上限只在**一处**核（超限的块记账丢掉，不静默）。"""
        nonlocal over
        r = []
        for q in ps:
            if q.area > cap:
                over += 1
            else:
                r.append(q)
        return r

    for g in gaps:
        ps = polys_of(g.intersection(keep).intersection(near))
        if not ps:
            continue
        hit += 1
        pre.extend([s for s in ps if s.area <= cap])   # 清边**前**的同一把尺子
        pieces.extend(_clean(ps, thin1))
    pieces = _cap(pieces)

    # ★★ 「含门 151」与「门扇 142」是**两个同名的量**（铁律 174）：一个缺口可以被
    #    两扇门的外扩同时够到 ⇒ 缺口数 ≥ 门扇数**不能**推出「每扇门都有门头」。
    #    所以这里**逐扇门**问一次：你头顶上到底有没有块？（这才是用户报的那件事。）
    #    判据 J-10.9-01 量的也是这一条，不是缺口数。
    def _cov(ps):
        # ★★ 判据换了两轮，两轮都留下读数（2026-10-15）：
        #    ① 旧版：块外扩 1 mm、`intersects` 门扇就算有门头 ⇒ **假绿**。1 层实测有 11 扇
        #       门头顶上只剩一块 **400 mm² 量级的碎渣**，照样记「有门头」。
        #    ② 试过「门头并集 ∩ **门扇footprint** 面积占比 ≥ 0.8」⇒ **错得离谱**，实测
        #       1014 扇只 56 扇达标。根因：源图里的门扇是**开门状态的扇叶** —— 731 那一维
        #       **伸进房间**、37.5 那一维才沿墙；门头在墙里（厚 240），两者只交
        #       240×37.5 ≈ 9000 mm²，占 27422 的 0.33，**恒达不到 0.8**。判据的参照物
        #       与被测的东西不在同一个位置上（铁律 192），所以它对「有没有门头」全盲。
        #    ③ 现在这把：**面积下限 + 相邻**。真门头 = 墙厚 240 × 洞宽 ≥700 ≳ 1.6e5 mm²；
        #       实测碎渣在 4e2 mm² 量级 —— 两者差两个数量级，中间取 `门头墙_最小块`。
        #       这一把的**分辨力是喂出来的**：old 判据下 1 层「有门头 135」，
        #       加面积下限后同一批数据掉到 124（那 11 扇就是只剩碎渣的）。
        big = [g for g in ps if g.area >= min_blk]
        if not big:
            return 0
        tl = [g.buffer(1.0, join_style=2) for g in big]
        k = 0
        for lf in (leaves or []):
            if lf is None or lf.is_empty:
                continue
            if any(lf.buffer(1.0, join_style=2).intersects(t) for t in tl):
                k += 1
        return k

    # ★★ 缝合（`门头墙_缝合`）：清完边之后，门头块与墙带之间常留一条**5~25 mm 的缝** ——
    #    实测 1层 有 16 扇门「贴着墙（d墙=0）但最近的够大块在 5~25 mm 外」，就是这条缝。
    #    缝的来路：墙带轮廓是栅格掩膜的轮廓（`cv2.findContours`），而闭运算/布尔求交
    #    都在连续域里做 ⇒ 两者的边界在近乎相切处不重合。三维里这条缝就是**门头悬空**
    #    （用户说的「门上面的缺失」的一种形态：不是没有，是没接上）。
    #    修法：逐块外扩 `门头墙_缝合`，与「离墙 ≤ nw」的带求交 ⇒ 门头**咬进墙里**；
    #    外扩可能让相邻块碰到一起 ⇒ 直接并成一块（顺带把 ⑫ 同类重叠也一并消化）。
    def _stitch(ps):
        if seam <= 0 or not ps:
            return list(ps), 0
        u = unary_union([g.buffer(seam, join_style=2) for g in ps]).intersection(near)
        st = [g for g in polys_of(u) if g.area > 0]
        keep = [g for g in st if g.area <= cap]
        return keep, len(st) - len(keep)

    pieces, over2 = _stitch(pieces)
    over += over2
    # ★★ 缝合**之后**再清一遍（2026-10-15）：清边必须是**最后一道**算子。
    #    实测（读 `06_su/contours/1层.json` 里两条 FAIL 环的最短边）：
    #      F01-LINTEL-001  5.0912 mm  (27705.000,16008.600)->(27708.600,16005.000)
    #      F01-LINTEL-059  4.1725 mm  (62154.400,55702.100)->(62151.400,55705.000)
    #    两条都是 **45° 斜切**（Δx=Δy=3.6 / 2.95，5.0912=3.6·√2）—— 只有 `join_style=2`
    #    的斜接边会切出斜边，而**缝合那一步本身就新增一道斜接**（逐块 buffer(seam) 再
    #    与 `near` 求交）。所以清边放在缝合前，缝合会把已经清干净的地方重新切出碎边
    #    （铁律 183：同一个错法换个算子仍会再犯）。
    pieces = _cap(_clean(pieces, thin2))
    # ★★ 最后一道：收边（`heal_short_edges`）。必须**最后** —— 它前面每一个算子
    #    （清边 / 缝合 / 面积上限）都可能再切出新短边，清边在缝合前就只能管到缝合前。
    #    下限取自 `参数.json` 的 `环_最短边下限`（6.25），与入口闸 ⑪ 是**同一个数** ——
    #    闸那边会反过来核这一条，两处不等就当场判红（铁律 018）。
    n_heal, n_stub, heal_min = 0, 0, []
    hs = []
    for q in pieces:
        q2, ch, m2 = heal_short_edges(q, edge_floor)
        if ch:
            n_heal += 1
        elif m2 < edge_floor:
            n_stub += 1
            heal_min.append(round(m2, 4))
        hs.append(q2)
    pieces = hs
    # ★★ 「漏了几扇」必须带**主语与成因**（铁律 196）：这个数里有几扇是清边削掉的、
    #    有几扇是闭运算本来就没补出来的。同一把尺子跑两遍（清边前 / 清边后），
    #    差值才归清边 —— 只有一个读数时，「清边致漏」与「本来就漏」长得一模一样。
    #    ★ 清边前那一趟也**走同一套缝合**，否则差值里混进了缝合的收益，
    #      「清边致漏」会被算成负数或虚低（同一个量两把尺子，铁律 194）。
    cov_pre = _cov(_stitch(pre)[0])
    cov = _cov(pieces)
    n_leaf = len([x for x in (leaves or []) if x is not None and not x.is_empty])

    # ★★ 漏掉的那几扇**要指名**（铁律 174：计数只能取自独立清单）。逐扇量三个数：
    #    离墙带着多远、离最近的**够大的**门头块多远、门扇自己多大。
    #    「距墙 3.2 m」和「距墙 0.1 m 但块不够大」是**两种病**，混成一个数就没法治。
    miss = []
    big_tl = [(g, g.buffer(1.0, join_style=2)) for g in pieces if g.area >= min_blk]
    for lf in (leaves or []):
        if lf is None or lf.is_empty:
            continue
        pp = lf.buffer(1.0, join_style=2)          # ★ 不叫 `p`：那会遮住取参数的 p()
        if any(pp.intersects(t) for _, t in big_tl):
            continue
        dW = lf.distance(W) if not W.is_empty else -1.0
        dP = min((lf.distance(g) for g, _ in big_tl), default=-1.0)
        # ★ 带上质心（源图 mm 坐标）：不指名坐标就只能说「漏了 20 扇」，
        #   指得出坐标才能去源图上看**是不是同一处**（2~6 层各 4 扇、数字逐层相同
        #   ⇒ 几乎是同一处固定构件）。（铁律 174：计数要取自独立清单）
        _c = lf.centroid
        miss.append([round(dW, 1), round(dP, 1), round(lf.area, 1),
                     int(round(_c.x)), int(round(_c.y))])

    areas = sorted(s.area for s in pieces)
    z_rel = dh / 1000.0
    h = h_mm / 1000.0 - z_rel
    out = [(s, round(z_rel, 4), round(h, 4)) for s in pieces] if h > 0 else []
    box.update({"缺口": len(gaps), "缺口含门": hit, "缺口无门": len(gaps) - hit,
                "块": len(out), "超限丢弃": over, "闭环半径": r_, "超出门扇": kr,
                "离墙上限": nw, "清边半径": clean, "缝合": seam,
                "缝合丢超限": over2,
                "清边丢块": thin1["丢块"], "清边丢面积_mm2": round(thin1["丢面积"], 1),
                "清边裂块": thin1["裂块"], "清边改面积块": thin1["改面积"],
                "缝合后清边丢块": thin2["丢块"],
                "缝合后清边丢面积_mm2": round(thin2["丢面积"], 1),
                "缝合后清边裂块": thin2["裂块"],
                "缝合后清边改面积块": thin2["改面积"],
                "收边下限": edge_floor, "收边治了": n_heal, "收边没治好": n_stub,
                "收边没治好的最短边": (heal_min[:10] if heal_min else []),
                "面积上限": round(cap, 1),
                "门扇": n_leaf, "有门头": cov, "漏了": n_leaf - cov,
                "有门头_清边前": cov_pre, "清边致漏": cov_pre - cov,
                "漏明细_距墙_距块_面积": (miss[:20] if miss else []),
                "漏明细_截断": (len(miss) > 20),
                # ★★ 漏掉的门**按实测的 `d墙` 分两类**（不手打名单，铁律 103）：
                #    贴墙 ⇔ 源图那面墙是**实心**的（两面墙线连续、只留门垛线）
                #            ⇒ 门头其实**不缺**，缺的是**门洞**（门被墙埋着）；
                #    离墙 ⇔ 源图那段墙**整段没有线**（1层/2层 都已回源 DXF 坐实）
                #            ⇒ 没有墙可挂门头。
                #    两种病治法相反，混成一个数就没法治。
                "漏_贴墙": len([m for m in miss if m[0] <= 1.0]),
                "漏_离墙": len([m for m in miss if m[0] > 1.0]),
                "块面积_mm2": ([round(areas[0], 1), round(areas[len(areas) // 2], 1),
                                round(areas[-1], 1)] if areas else None),
                "面积合计_m2": round(sum(s.area for s in pieces) / 1e6, 3)})
    notes = []
    if over:
        notes.append("★ 有 %d 块超过面积上限 %.0f mm² 被丢 —— 要么 keep_r 太大，要么闭运算"
                     "在走道口上架了桥。**这不是静默通过**" % (over, cap))
    if len(gaps) != hit:
        notes.append("补出的 %d 个缺口里 %d 个附近没有门扇 ⇒ 按构造丢弃"
                     % (len(gaps), len(gaps) - hit))
    if n_leaf and cov < n_leaf:
        notes.append("★★ %d/%d 扇门**头顶上没有补出块** —— 这就是用户报的「门上面的缺失」"
                     "还剩下的部分，不许当它不存在" % (n_leaf - cov, n_leaf))
    if n_stub:
        notes.append("★ 收边**没治好** %d 块（残最短边 %s）—— 它们会原样进环、被入口闸 ⑪ 拦下；"
                     "这是**如实报**，不是静默放行" % (n_stub, heal_min[:10]))
    if notes:
        box["说明"] = " ｜ ".join(notes)
    return out, box


# ------------------------------------------------------------------ 楼梯栏杆
def side_is_walled(probe, prep_walls, tol):
    r"""这块「栏杆该站的位置」外扩后碰得到墙带吗？碰得到 ⇒ 贴墙 ⇒ 不立栏杆。

    ★ 为什么要问墙：白模里梯段两边常常都是墙，闭着眼两侧都立栏杆 = 把栏杆**插进墙里**，
      远看像多了两道墙；两侧都不立 = 用户说的「楼梯样式不对」原样保留。
      判据只用**外扩 tol 后与墙带相交**这一条，`tol` 是 `参数.json` 里的假设值。
    """
    if prep_walls is None:
        return False
    for pg in polys_of(probe.buffer(tol, join_style=2)):
        if prep_walls.intersects(pg):
            return True
    return False


def rail_strips(off_a, off_b, par_lo, par_hi, z_m, h_m, xy):
    r"""一段梯段某一侧的**栏杆带** → `[(poly, z_rel_m, h_m)]`（世界 mm 坐标）。

    `xy(off, par) -> (x, y)` 由调用方给（`build3d` 的 `_xy` 手里有基向量）。
    `par_lo/par_hi` 是栏杆在 par 方向上占的那一条（已经含厚度）；
    立在 `z_m` 标高、高 `h_m` 米。
    """
    if off_b - off_a <= 0 or par_hi - par_lo <= 0:
        return []
    quad = [xy(off_a, par_lo), xy(off_b, par_lo), xy(off_b, par_hi), xy(off_a, par_hi)]
    poly = sg.Polygon(quad)
    if not poly.is_valid or poly.area <= 0:
        return []
    return [(poly, round(z_m, 4), round(h_m, 4))]


def rail_span(par_edge, inward, t):
    """沿 `par_edge` 那条边、朝 `inward`（+1/−1）方向长 `t` 厚 —— 返回 (lo, hi)。

    ★ 栏杆**不悬空**：贴着梯段的边往**里**长，所以它的外侧面与梯段侧面共面。
    """
    if inward > 0:
        return (par_edge, par_edge + t)
    return (par_edge - t, par_edge)


def rail_probe(par_edge, inward, t, off_a, off_b, xy):
    """「栏杆该站的位置」的探针多边形（用来问墙：这里贴不贴墙）。"""
    lo, hi = rail_span(par_edge, inward, max(t, 1.0))
    quad = [xy(off_a, lo), xy(off_b, lo), xy(off_b, hi), xy(off_a, hi)]
    return sg.Polygon(quad)


def self_test():
    """`python rebuild/tools/parts_lib.py` —— 只验参数表读得进、自检过得去。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    d = load(fresh=True)
    n = sum(len(b) for b in (d.get("构件") or {}).values())
    print("参数.json OK：构件 %d 组 · 参数 %d 条" % (len(d["构件"]), n))
    for cat, block in d["构件"].items():
        got = [k for k in block if block[k]["值"] is not None]
        wait = [k for k in block if block[k]["值"] is None]
        print("  %-4s 有值 %2d 条 · 待坐实 %2d 条%s"
              % (cat, len(got), len(wait),
                 ("　待坐实：" + "、".join(wait)) if wait else ""))
    return 0


if __name__ == "__main__":
    sys.exit(self_test())
