# -*- coding: utf-8 -*-
"""楼层 `outline` 字段的**唯一**编解码口 + 外壳线 + 多块轮廓推导。

为什么单独一个模块：`outline` 是全链路共用的一等交付量（楼板 / 外墙环带 / 布窗 / 房间
围合 / 导航 / QA / GLB），而**「一层 = 一个连通环」这个假设在真实建筑上不成立**：
  · c086 香樟园6号公寓 F3/F4/F5：三层以上是**两栋塔楼**，中间是空的（图纸 x 中段一条
    折线都没有，见 `_scratch/_d_c086_src_panels.png`）。`_biggest_outline` 的
    `max(area)` 只留东翼 843㎡，`outline_unify` 又拿 F0 的整片 2055㎡ 顶上去 →
    模型上中间那团凭空出现，用户标注「没有这个」「没有」（F3/F4/F5 三连）。
  · 同族的 c079/c083/c085（两块 257.8㎡ 完全相等）、c080/c084（三块 258.2㎡）、
    c072/c073、c033/c034、c103/c104 —— 全库实测 **21 栋 53 层**有多块楼层
    （`_scratch/_de_multiblock_census.log`）。
  · c086 F1「阳台」（用户标注 src/wall_missing）：阳台栏板（三块配对矩形，厚 0.17/0.20m）
    配对完全正确，但 F1 用的是**统一基准轮廓**（F0 的那片，北边界 y=28.12），阳台探到
    y=30.97 在轮廓外 → `interior_mask = 外墙 holes[0]`（1940.24㎡，同一片）把栏板裁成
    0.0000㎡。E 根因与 D 同根：**轮廓丢块**。

交付编码（**为什么不是「outline 直接写成多环」**）：`qa_structural.py` 的 `_poly()` 是
`Polygon(coords)`，20 多处直接读 `outline`；改成多环它**当场抛异常**，整套 QA 门禁作废；
而给它主块一块，另一块上的房间/柱/墙**全被判「在轮廓外」**（c086 F3 实测 ERROR 0→66，
`_qa/c086_qa.txt`，同一份墙体在 HEAD 上是 0 ERROR —— 真回归，不是门禁变严）。
用户明令「不改 qa_structural.py」（门禁是诚实的裁判，不许挪球门），所以**编码要迁就读法**：

  "outline":       [[x, y], ...]                  ← **单环，恒为完整足迹**
      单块楼层 = 那一块的外环（历史编码逐字节不变）
      多块楼层 = 「钥匙孔」环：块与块之间加一条 `NECK_W` 宽的窄桥，焊成一个连通环
  "outline_parts": [ [[x,y],...], [[x,y],...] ]   ← **精确分块**（面积降序），只在多块时写

  · QA 读 `outline`：单块楼层行为不变；多块楼层拿到的是「块 ∪ 10cm 窄桥」——
    面积 = 各块之和 + 0.1m×桥长（c086 F3：1688.0 → 1688.9㎡，+0.05%），
    房间/柱/墙**全部落在环内**，于是 QA 的 I1/I3/I4/I10 按真几何判，不再误报。
  · 真消费者一律走 `floor_outline(fl)`：有 `outline_parts` 就**用精确块**（看不到窄桥），
    否则用 `outline`。不许再写 `Polygon(fl["outline"])`。
  · 窄桥只活在 QA 那一份里，不参与任何建模（楼板/女儿墙/房间/导航都不读它）。

  · `outline_shell()` 替 `.exterior`（多块没有单数 exterior）；`as_outline()` 解「一个环」。
  · 块表先过 `_blocks_clean`（滤退化薄片/点片 —— 它们是"焊不起来"的真病根，见
    `MIN_BLOCK_THIN`）；万一仍焊不成，`outline` 退回主块，但**照写 `outline_parts` 并出声**，
    绝不静默丢块（2026-09-23 修：旧版静默写 `[]`，c113 三层因此各丢几十块）。

编码自动判别（只看 `raw[0][0]` 是不是点）也保留：单环 `[[x,y],...]` / 多环 `[[[x,y]...],...]`。
`outline_parts` 的元素一律按**单环**解（逐个喂 `as_outline`，别整个列表喂进去 —— 两个环的
列表会被误判成单环）。旧编码 `outline_more`（本模块 2026-09-12 上午的版本，主块+次块）
在 `floor_outline()` 里仍可读，只为过渡期已写出的产物。
"""
from shapely.affinity import translate as _translate
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import nearest_points, unary_union

# 一个「块」要有实体足迹：≥2㎡，且 ≥ 最大块的 2%。
# 2㎡ 挡的是孤岛符号（门垛/洁具/构造线被 buffer 出来的小片）；2% 挡的是
# 「主块很大、旁边挂一小片」时的比例噪声（c022 F2 的 20.4㎡ 次块是真块，
# 22.2㎡/1030㎡ 那种才是噪声——两条阈值都要过）。
MIN_BLOCK_AREA = 2.0
MIN_BLOCK_FRAC = 0.02
# 块间最大间距：超过这个距离的「次块」不是本层的另一块，而是**同一张图上画的另一栋
# 楼/重复副本**（floor.py:402 判例：公寓首层把同层画两遍，左右各一栋，间距 341m）。
# 真实多块楼层（双塔共裙楼、双翼公寓）块间距都是几十米内 —— c086 两翼间 25m。
MAX_BLOCK_GAP = 60.0
# 「钥匙孔」窄桥（见模块头）：多块楼层交付 `outline` 时用来把块焊成一个连通环，
# 好让只认单环的 QA 看得见整层。取值只影响 QA 的面积/包含判定，不参与建模：
#   太窄 → 2 位小数取整 / buffer(0) 清洗有把它折叠成相切（进而裂成两块）的风险
#   太宽 → 白白给 QA 的板面积灌水
# 0.10m 下：c086 F3 的桥长 ~25m，只多 2.5㎡（+0.15%），而 10cm 远小于任何真实构件。
NECK_W = 0.10

# 一个「块」还得有**实体厚度**：`thin = 2A/P`（≈平均厚度，见 `_blocks_clean`）。低于本值
# 的不是楼板块，是 buffer/取整造出来的碎片 —— 墙带被 buffer 后残留的薄片、退化点片。
# 为什么必须在这一层滤：`_blocks_sorted` 只挡 `area > 1e-9`，而 `outline_fields` 拿到的
# `slab_poly` 是多道 union→填外环**之后**的产物，退化块会一路带进来。c113 F3 实测 38 块里
# **34 块**是这种（0.02~0.48㎡ / thin 0.06~0.14，含 17 个零面积点片）：它们与真块相切，
# `_mst_edges` 于是给出**距离 0** 的边，而 `_neck_quad` 对距离 0 返回 None（"已相接，不用桥"）
# ⇒ 没有任何桥 ⇒ union 仍是 MultiPolygon ⇒ 触发下面那条"焊不起来"的回退，
# 该层 827.8㎡ 只交付 432.9㎡（丢 37 块 394.9㎡，含 366.9㎡ 椭圆观众厅）。
# 定 0.25m 的依据：远小于任何真实楼板块的尺度，又高于"墙厚 0.2~0.3m 量级被 buffer 出来的
# 薄片"—— 实测 c113 F0/F2/F3 丢掉 thin<0.25 的碎片后**一次就焊成单块**（824.3㎡）。
# 最大块**永远保留**（见 `_blocks_clean`）：滤完不可能为空，不会把"全丢"当成"没块"。
MIN_BLOCK_THIN = 0.25


def as_outline(raw):
    """`outline` 字段 → Polygon / MultiPolygon。空 / 非法 → 空 Polygon。"""
    parts = []
    for ring in _rings(raw):
        if len(ring) < 3:
            continue
        try:
            p = Polygon(ring)
        except Exception:                                                   # noqa: BLE001
            continue
        if not p.is_valid:
            p = p.buffer(0)
        for q in ([p] if p.geom_type == "Polygon" else
                  [g for g in getattr(p, "geoms", []) if g.geom_type == "Polygon"]):
            if not q.is_empty and q.area > 1e-9:
                parts.append(q)
    if not parts:
        return Polygon()
    if len(parts) == 1:
        return parts[0]
    return unary_union(parts)


def outline_json(g, ndigits=3):
    """(Multi)Polygon → 环列表。块数 1 → 单环；≥2 → 多环。

    ⚠️ 交付字段**不用**这个（会撞 QA 的 `Polygon(coords)`）；写出走 `outline_fields()`。
    这里留给「环 ↔ 环」的内部转换（如 `roof.wingRoof` 就是多环列表）。
    """
    ps = _blocks_sorted(g)
    rings = [_ring_json(p, ndigits) for p in ps]
    if len(rings) == 1:
        return rings[0]
    return rings


def outline_fields(g, norm=None, ctx=None):
    """(Multi)Polygon → 交付字段 {"outline": 单环, "outline_parts": [精确块环...]}。

    单块：`outline` = 那块外环，`outline_parts` = 空列表（调用方**不写这个键**）
          → floor JSON 与历史逐字节一致（`norm` 传 floor.py 原有的 `_dedupe(r2(...))`，
          连取整口径都一样，可直接 diff 验证）。
    多块：`outline` = 钥匙孔单环（`bridge_ring`），`outline_parts` = 各块外环（面积降序）。

    `ctx` 只用于日志（`"[c113 F3]"` 之类），不参与几何。
    """
    ps = _blocks_clean(g)
    if not ps:
        return {"outline": [], "outline_parts": []}
    if len(ps) == 1:
        d = {"outline": _ring_json(ps[0], norm), "outline_parts": []}
        # 内院/天井（2026-09-15）：有内环才写这个键 —— 无内环的楼产物**逐字节不变**。
        if ps[0].interiors:
            d["outline_holes"] = [_ring_json(Polygon(h), norm) for h in ps[0].interiors]
            d["outline"] = _ring_json(ps[0], norm)      # 外环照旧（兼容只认单环的旧消费者）
        return d
    ring = bridge_ring(ps)
    if ring is None or ring.is_empty:
        # 焊不成单块 —— **必须出声**（旧版这里没有一行日志，于是"丢块 + 填平内院"这个
        # 双向的错在交付件里躺了很久都没人知道）。注意这一支**仍然照写 `outline_parts`**：
        # 旧版写 `[]`，等于把"本层有多个块"这件事也一并丢掉，消费者只能看到主块
        # ⇒ 楼板/女儿墙/导航全跟着错；照写则几何是对的，只有 QA 那一份（读 `outline`）
        # 看不见非主块上的房间/柱/墙 —— 那正是"焊不起来"的代价，但要**说出来**。
        print(u"    [%s] ⚠ 轮廓多块焊不成单环：%d 块（最大 %.1f㎡）⇒ 交付退回主块；"
              u"outline_parts 已照写，本层 QA 对非主块的判据失效"
              % (ctx or "outline", len(ps), ps[0].area))
        return {"outline": _ring_json(ps[0], norm),
                "outline_parts": [_ring_json(p, norm) for p in ps]}
    d = {"outline": _ring_json(ring, norm),
         "outline_parts": [_ring_json(p, norm) for p in ps]}
    _holes = []
    for p in ps:
        _holes.extend(_ring_json(Polygon(h), norm) for h in p.interiors)
    if _holes:
        d["outline_holes"] = _holes
    return d


def floor_outline(fl):
    """floor dict（或裸环列表）→ Polygon / MultiPolygon = 本层**真实**足迹。

    有 `outline_parts`（多块楼层）→ 精确各块的并（**不含**钥匙孔窄桥）；
    否则 → `outline`（单块楼层就是本层足迹）。
    旧的 `outline_more`（主块+次块编码）仍可读，只为过渡期产物。

    **所有消费者读 outline 都从这里读**。空 / 非法 → 空 Polygon。
    """
    if fl is None:
        return Polygon()
    if isinstance(fl, (Polygon, MultiPolygon)):
        return fl
    if hasattr(fl, "get"):
        raw = fl.get("outline")
        exact = fl.get("outline_parts")
        more = fl.get("outline_more")
    else:
        raw, exact, more = fl, None, None
    if exact:                               # 精确块优先，窄桥不进模型
        geoms = [as_outline(r) for r in exact]
        geoms = [g for g in geoms if not g.is_empty]
        if geoms:
            return geoms[0] if len(geoms) == 1 else unary_union(geoms).buffer(0)
    parts = []
    main = as_outline(raw)
    # 内院/天井：把 outline_holes 作为内环挂回外环（2026-09-15 新增；旧产物没有这个键 → 行为不变）
    _holed = None
    if hasattr(fl, "get"):
        _hrs = fl.get("outline_holes") or []
        if _hrs and not main.is_empty:
            _hs = []
            for r in _hrs:
                try:
                    h = Polygon(r)
                except Exception:                                      # noqa: BLE001
                    continue
                if not h.is_valid:
                    h = h.buffer(0)
                if not h.is_empty and h.area > 1e-9:
                    _hs.append(list(h.exterior.coords))
            if _hs:
                try:
                    _cand = Polygon(list(main.exterior.coords), _hs)
                    if not _cand.is_valid:
                        _cand = _cand.buffer(0)
                    if not _cand.is_empty:
                        _holed = _cand
                except Exception:                                      # noqa: BLE001
                    _holed = None
    if _holed is not None:
        return _holed
    if not main.is_empty:
        parts.append(main)
    for ring in (more or []):               # 旧编码：每个元素**恰好一个环**（见模块头）
        e = as_outline(ring)
        if not e.is_empty:
            parts.append(e)
    if not parts:
        return Polygon()
    if len(parts) == 1:
        return parts[0]
    return unary_union(parts).buffer(0)


def bridge_ring(blocks, w=NECK_W, inset=0.10, rounds=3):
    """块列表 → **单环**（块与块之间用 `w` 宽的窄桥焊成连通面）。

    为什么必须连通：`qa_structural.py` 的 `_poly()` = `Polygon(coords)` 只认一个环，
    给它主块一块，其余块上的房间/柱/墙全被判「在轮廓外」。窄桥让整层在几何上连通，
    面积只多 `w × Σ桥长`（0.1m 量级），而**窄桥不参与建模**（消费者读 `outline_parts`）。

    桥的构造：对块做最小生成树（Prim，按最近点距离），每条树边取两块最近点对
    `nearest_points`，沿连线方向造一条 w 宽、两端各**探进块内 `inset`** 的矩形。
    探进去是必须的：只相切的话 `unary_union` 会判成两块（导出环仍是 MultiPolygon）。

    一轮焊不完时**最多再试 `rounds-1` 轮**：拿 union 出来的碎块当新块、把桥加宽一倍重焊
    （碎块常常是"桥与块错开了零点几毫米"的产物，加宽即合）。这是**安全网**，不是主修 ——
    c113 那种 38 块的真正病根是块表里混着退化碎片，已由 `_blocks_clean` 在校前滤掉；
    加宽只在退化到"确实有几块差一点点接不上"时才生效，且每轮 w 翻倍、最多 0.4m，
    对 QA 的面积影响仍有界。返回 None 表示轮数用尽仍裂着（调用方退回主块 + 出声）。
    """
    ps = [p for p in blocks if p is not None and not p.is_empty and p.area > 1e-9]
    if not ps:
        return Polygon()
    if len(ps) == 1:
        return ps[0]
    try:
        for _ in range(max(1, rounds)):
            geoms = list(ps)
            for a, b in _mst_edges(ps):
                q = _neck_quad(a, b, w, inset)
                if q is not None:
                    geoms.append(q)
            u = unary_union(geoms)
            if u.geom_type == "Polygon":
                return Polygon(u.exterior)      # 外环填实：与 blocks_to_outline 同口径
            ps = _blocks_sorted(u)              # 还裂着：拿碎块当新块，加宽重焊
            if len(ps) < 2:
                return None
            w *= 2.0
        return None
    except Exception:                                                       # noqa: BLE001
        return None


def _mst_edges(ps):
    """块 → 最小生成树的边（Prim，边权 = 两块最近点距离）。

    n 不保证小：`outline_fields` 拿到的是**多道 union→填外环之后**的块表，实测 c113 F3
    到过 38 块（旧注释写「n 很小（≤4）」—— 假设早被打破，见 `MIN_BLOCK_THIN` 那段）。
    退化块已由 `_blocks_clean` 在校前滤掉，所以这里的边距不再出现"距离 0 却接不上"。
    """
    n = len(ps)
    done, edges = [0], []
    while len(done) < n:
        best = None
        for i in done:
            for j in range(n):
                if j in done:
                    continue
                d = ps[i].distance(ps[j])
                if best is None or d < best[0]:
                    best = (d, i, j)
        if best is None:
            break
        edges.append((ps[best[1]], ps[best[2]]))
        done.append(best[2])
    return edges


def _neck_quad(a, b, w, inset):
    """两块之间那条 w 宽的矩形（沿最近点连线，两端各探进块内 inset）。

    空几何直接返回 None：`nearest_points` 遇到空几何会**抛**
    `ValueError: The second input geometry is empty`（实测：块先 `buffer(+r).buffer(-r)`
    闭合运算后，退化碎片会变成空 Polygon）—— 抛出去会一路掀掉整层识别的结果，
    而"这块没桥可搭"本来就该由调用方按 None 处理。
    """
    if a is None or b is None or a.is_empty or b.is_empty:
        return None
    pa, pb = nearest_points(a, b)
    dx, dy = pb.x - pa.x, pb.y - pa.y
    L = (dx * dx + dy * dy) ** 0.5
    if L < 1e-9:                            # 两块已相交/重合：不用桥
        return None
    ux, uy = dx / L, dy / L                 # 连线方向
    nx, ny = -uy * w / 2.0, ux * w / 2.0    # 连线法向的半宽
    a0 = (pa.x - ux * inset, pa.y - uy * inset)
    b0 = (pb.x + ux * inset, pb.y + uy * inset)
    quad = [(a0[0] + nx, a0[1] + ny), (b0[0] + nx, b0[1] + ny),
            (b0[0] - nx, b0[1] - ny), (a0[0] - nx, a0[1] - ny)]
    q = Polygon(quad)
    return q if q.is_valid and not q.is_empty else None


def shift(g, dx, dy):
    """平移（跨层复用轮廓：过渡层楼板 = 源楼层轮廓按 cy 差平移）。"""
    if g is None or g.is_empty:
        return g
    return _translate(g, xoff=dx, yoff=dy)


def _blocks_sorted(g):
    """(Multi)Polygon → 实体块列表，面积降序。已建好的 outline 不再过滤（上游已滤）。"""
    if g is None or g.is_empty:
        return []
    ps = [g] if g.geom_type == "Polygon" else \
        [q for q in getattr(g, "geoms", []) if q.geom_type == "Polygon"]
    ps = [p for p in ps if not p.is_empty and p.area > 1e-9]
    ps.sort(key=lambda p: p.area, reverse=True)
    return ps


def _blocks_clean(g):
    """`_blocks_sorted` + **去退化**：只留"能当楼板块"的，面积降序。

    判据两条（都是"这不可能是一块楼板"的量级，不是调出来的系数）：
      · `area >= MIN_BLOCK_AREA`（2㎡，与 `blocks_of` 上游同一条门槛，口径一致）；
      · `2A/P >= MIN_BLOCK_THIN`（0.25m，≈平均厚度 —— 拦 buffer/取整留下的薄片）。
    **最大块永远保留**：滤成空会把"这一层全被当成退化片"误报成"这层没有块"，
    而`outline_fields` 空块会写出 `outline: []`（真·坏数据）；保最大块最坏也只是
    回退到"只有一块"，与历史行为同量级。

    为什么与 `_blocks_sorted` 分开：`_blocks_sorted` 是**通用**分块（`outline_json`、
    `outline_fields` 之外的调用方也在用），它只保证"有面积的都算"；"哪些够格当楼板块"
    是交付口径，只在 `outline_fields` 这一层判。
    """
    ps = _blocks_sorted(g)
    if not ps:
        return []
    keep = [ps[0]]
    for p in ps[1:]:
        if p.area < MIN_BLOCK_AREA:
            continue
        if 2.0 * p.area / max(p.length, 1e-9) < MIN_BLOCK_THIN:
            continue
        keep.append(p)
    return keep


def _ring_json(p, norm=None):
    """单个 Polygon 外环 → 点表。**带闭合点**（交付里 outline 首尾同点，历史如此）。"""
    cs = [tuple(q) for q in p.exterior.coords]
    if norm is not None:
        return [[float(x), float(y)] for x, y in norm(cs)]
    return [[float(round(x, 3)), float(round(y, 3))] for x, y in cs]


def outline_shell(g):
    """轮廓的**外壳线**：单块 = `Polygon.exterior`；多块 = 各块外环的并。

    替 `.exterior` 用。注意是**外环**不是 `.boundary`：`boundary` 含天井/内院的内环，
    拿它判「墙贴不贴轮廓」会把内院边上的墙从内墙翻成外墙 —— 语义变了，不是本次要动的。
    """
    if g is None or g.is_empty:
        return None
    if g.geom_type == "Polygon":
        return g.exterior
    lines = [p.exterior for p in g.geoms if p.geom_type == "Polygon" and not p.is_empty]
    if not lines:
        return None
    return lines[0] if len(lines) == 1 else unary_union(lines)


def blocks_of(region, close_r=0.0):
    """一个 union 出来的面 → 本层**所有**实体块（面积降序）。

    `region` 是墙/填充 union（已 buffer(0) 清洗）。`close_r` 与生产同口径：先闭运算
    把碎带桥接成整块（c006 LINE 约定墙角点把墙带断成几十段），再分块。

    只保留「够大」且「离已保留的块 ≤ MAX_BLOCK_GAP」的块：前者滤孤岛符号，后者滤
    同一张图上画的另一栋（重复副本）。**两块面积完全相等不是丢弃理由** —— c079/c083/
    c085 的双翼就是 257.8㎡ 对 257.8㎡（镜像，不是平移副本），按面积去重会把整翼删掉。
    """
    if region is None or region.is_empty:
        return []
    if close_r > 0:
        region = region.buffer(close_r).buffer(-close_r)
    ps = [region] if region.geom_type == "Polygon" else \
        [p for p in region.geoms if p.geom_type == "Polygon"]
    ps = [p for p in ps if not p.is_empty and p.area > 1e-9]
    if not ps:
        return []
    ps.sort(key=lambda p: p.area, reverse=True)
    keep = [ps[0]]
    floor_area = max(MIN_BLOCK_AREA, ps[0].area * MIN_BLOCK_FRAC)
    for p in ps[1:]:
        if p.area < floor_area:
            continue
        if min(p.distance(q) for q in keep) > MAX_BLOCK_GAP:
            continue                      # 另一栋楼 / 重复副本，不是本层的块
        keep.append(p)
    return keep


def blocks_to_outline(blocks, keep_holes=False):
    """块列表 → (Multi)Polygon。

    `keep_holes=False`（默认，历史口径）：每块取外环**填实** —— 轮廓是**足迹**，不留内院洞。
    这条口径是为「同层双塔/双翼 + 井洞」那批图定的（那时墙 union 的里腔是识别碎片，填掉才对）。

    `keep_holes=True`（2026-09-15 新增，按楼开关 profile.keep_courtyard_holes）：**保留内环**。
    回字形平面的**内院/天井**是真实存在的，填实会让楼板凭空多出整片面积 —— 实测：
      c072/c073 每层 +1200㎡（内院带 `x[-28.9,34.5] y[-9.7,11.1]`，一个房间都没有）、
      c103 每层 +1253~1291㎡、c009 也有同款叠加；对账用的**图纸自带面积表**里这些内院
      是不计面积的，所以差值正好等于内院面积。
    """
    outs = []
    for p in blocks:
        if keep_holes and p.interiors:
            # **只在"真内院"留洞**（2026-09-15 c072 实测）：留洞判据 = 洞面积 < 45% 块面积。
            #   内院（回字形平面中央那圈）实测 1318.7/4480 = 29% ✓ 留；
            #   而"整层内部"那种洞（F5/F6）占比 >45%，一留洞楼板就只剩一圈薄环（c072 F5
            #   4118 → 633㎡）✗ 自动排除 ⇒ 保外环填实。
            #
            # ⚠️ 2026-09-23 **试过加一道「内环合计」闸门，A/B 实测不成立、已回退** —— 别再走这条路。
            #   动机是真缺陷：c002/c003（用户判例「南北翼楼」）十层平面每层被挖成蕾丝，
            #   交付轮廓/图纸建筑面积 0.61~0.69、F8/F9 只剩 0.13~0.21。
            #   想用 `sum(内环) >= 0.45 * p.area ⇒ 内环全丢（回到填实）` 修掉。实测
            #   （量具 `_scratch/_kch_ab.py`，配"该好的/不该动的"两组对照）：
            #     · 要修的 c002/c003 确实好了：各 8/10 层 0.61~0.69 → 1.00 ✓
            #     · 无关的 c054、以及本就没这个开关的 c006/c019 **28 层逐位 +0.0** ✓
            #     · 但回字形 c072/c073 **每层 +912.3 ㎡、比值 1.09 → 1.37** ✗
            #       —— 内院被填掉，正是本函数 docstring 里"填实让楼板凭空多出整片面积"那条。
            #   **为什么必然咬到 c072**：闸门的分母 `p.area` 是块的**净值**，而墙线 buffer
            #   并出来的块，净值就是**墙体材料**本身 —— 实测 c072 F0 主块 外环 4545.4㎡、
            #   净值只有 508.9㎡。于是"内环合计 ≥ 45% 净值"对**每一个墙梳块**都成立，
            #   这道闸门实际等于"墙梳分支一律不留洞"，与"按分支收窄"是同一件事换了个写法
            #   （那条也实测回退过）。**根因是分母选错了量：洞是「外环」的子集，不是「净值」的子集。**
            #   ⇒ 真要修 c002/c003，得先能**分开"房间格"与"内院"**（尺寸分布 / 内部有没有房间标注），
            #     而不是拿一个面积比一刀切。在此之前保持原口径。
            _hs = [h for h in p.interiors if Polygon(h).area < 0.45 * p.area]
            o = Polygon(p.exterior, _hs) if _hs else Polygon(p.exterior)
        else:
            o = Polygon(p.exterior)
        if not o.is_valid:
            o = o.buffer(0)
        if not o.is_empty and o.area > 1e-9:
            outs.append(o)
    if not outs:
        return Polygon()
    if len(outs) == 1:
        return outs[0]
    return unary_union(outs)


def _rings(raw):
    """字段 → 环列表。自动判别单环 / 多环编码。"""
    if not raw:
        return []
    first = raw[0]
    if not first:
        return []
    if isinstance(first[0], (list, tuple)):      # 多环编码
        rings = list(raw)
    else:                                        # 单环编码
        rings = [raw]
    return [[tuple(q) for q in ring] for ring in rings if len(ring) >= 3]
