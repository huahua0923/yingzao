# -*- coding: utf-8 -*-
"""洞口与宿主墙的关系（门 / 窗 ↔ 墙）—— 对标 BIM 的 hosted element。

**为什么单开一个模块**（2026-09-11，《算法与流程·对标四族·重构.md》§5.3）：

1. 挖洞这件事原先有两个实现（`floor.py` 里 recognize 阶段挖一次、`_wall_thin_batch._punch_doors`
   内墙重建后又挖一次），改一处漏一处；
2. 门/窗只记了自己的位置，没记**它开在哪面墙上**。没有宿主关系，墙一重建洞就悬空
   （BIM 导出 IFC 丢宿主 = 门悬空，是同一个坑）；
3. 挖洞本身是**幂等**的（`difference` 天然幂等），所以「挖两遍」几何上无害 —— 有害的是
   **没有登记宿主**、以及**没有一道门禁去量「洞到底挖穿了没有」**。

本模块只做两件事：登记宿主、挖洞。不做判门（那是 `geometry.detect_doors` 的事）。
"""
from shapely.geometry import Polygon

# 洞口中心到宿主墙的距离上限（米）。超过 = 悬空洞口（图纸符号飘在空处/墙重建后错位），
# 登记为 unresolved 而不是硬配一个远处的墙。ny27 实测门心到墙中位 0.36、最大 < 0.6。
HOST_MAX_DIST = 0.60


def _poly(w):
    """墙 dict → 多边形；非法返回 None。

    带洞时先试构造式；构造式对「洞不落在壳内」的坏数据会抛异常 —— 退到逐洞 difference
    （`_door_punch_apply` 一贯的写法），而不是直接返回 None。**返回 None 的后果是这道墙
    被静默跳过、门洞挖不穿**，所以两条路都必须试完才认输。
    """
    p = w.get("poly")
    if not p or len(p) < 3:
        return None
    holes = [h for h in (w.get("holes") or []) if len(h) >= 4]
    try:
        g = Polygon(p, holes) if holes else Polygon(p)
    except Exception:                                          # noqa: BLE001
        try:
            g = Polygon(p)
            for h in holes:
                g = g.difference(Polygon(h))
        except Exception:                                      # noqa: BLE001
            return None
    if not g.is_valid:
        g = g.buffer(0)
    return None if g.is_empty else g


def _host_of(walls, geom):
    """内部：→ (墙 dict, 距离, 墙多边形)。找不到 / 太远返回 (None, dist, None)。"""
    c = geom.centroid
    best = (None, float("inf"), None)
    for w in walls:
        g = _poly(w)
        if g is None:
            continue
        d = 0.0 if g.covers(c) else g.distance(c)
        if d < best[1]:
            best = (w, d, g)
    if best[0] is None or best[1] > HOST_MAX_DIST:
        return (None, best[1], None)
    return best


def ensure_wall_ids(walls, F):
    """给没有 id 的墙补一个稳定的 id（按下标），返回补了几个。

    **为什么必须有**：宿主登记靠 id 指墙。墙没有 id 时，`host_of` 会找到一个 0.43m 处的
    墙却因为 `w.get("id") is None` 把它当成「没找到」—— 于是 30 道门全被报成悬空门，
    而真相是「墙找到了、只是没名字」。**指标撒谎比指标红更危险**，所以这里补名，
    `register_hosts` 里再留一条 host_without_id 的独立分支，让这类问题永远红得出来。

    已有 id 的墙不动（recognize 的 `w{F}-{n}`、薄墙化的 `w{F}-i{n}` 都保留）。
    补出来的用 `w{F}-a{n}`（a = auto），下标不重复即稳定 —— 交付楼层是 JSON 列表，顺序稳定。
    """
    used = {w.get("id") for w in walls if w.get("id")}
    n = 0
    for i, w in enumerate(walls):
        if w.get("id"):
            continue
        cand = "w%d-a%d" % (F, i)
        while cand in used:
            cand += "x"
        w["id"] = cand
        used.add(cand)
        n += 1
    return n


def wall_poly(w):
    """公开别名（`_poly`）—— 门禁/渲染等外部消费者必须与挖洞逻辑看到同一份墙多边形，
    各写一份「墙 dict → Polygon」正是 P2 要断掉的重复。"""
    return _poly(w)


def host_of(walls, geom):
    """洞口 → 宿主墙 (wall_id, dist, kind)。

    取「墙面到洞口中心的距离」最小者（洞口在墙里时为 0）。
    找不到（> HOST_MAX_DIST）返回 (None, dist, None) —— 调用方应把它记进 unresolved。
    **找到墙但墙没有 id** 时返回 (None, dist, kind) —— dist 会在阈值内，调用方据此
    分辨「太远，真悬空」和「找到了但没名字」（见 ensure_wall_ids）。
    """
    w, d, _ = _host_of(walls, geom)
    if w is None:
        return (None, d, None)
    return (w.get("id"), d, w.get("type"))


def place_box_on_host(walls, door, depth=None, reach=1.5, max_ratio=1.30):
    """把门洞盒改设在**宿主墙**上；返回新盒，判不出发向时返回 None。

    门 = gap 不是 hole：盒必须横穿门所开的那面墙。先前盒由「门心到轮廓的距离」定
    （< 外墙厚+余量 就算外门、盒外缘贴轮廓挖外墙，见 `floor._door_boxes`）；门若其实开在
    一道离轮廓 0.3~0.4m 的**内墙**上，盒就整块落在内墙之外 —— 外墙被挖穿、内墙纹丝不动，
    门依旧夹在墙里。c019 F0 实测 10 扇（离轮廓 0.364~0.371，宿主是内墙 x11，盒与该墙
    重叠 0.00000 ㎡）。**开在哪面墙，盒就挖哪面墙** —— 这正是宿主关系该有的用途。

    做法：取宿主墙在门心附近 1.5m 内的局部形状，用其最小外接矩形定墙的走向；盒沿走向
    取门宽、垂直走向取「墙局部厚度 + 0.06」保证挖穿。斜墙/弧墙（最小外接矩形远小于其
    轴对齐包围盒）返回 None，交由调用方保留原盒 —— 轴对齐盒在斜墙上一刀会切歪。
    """
    from shapely.geometry import Point, box as _box
    p = Point(float(door["x"]), float(door["y"]))
    w, dist, g = _host_of(walls, p)
    if g is None:
        return None
    loc = g.intersection(p.buffer(reach))
    if loc.is_empty:
        return None
    mrr = loc.minimum_rotated_rectangle
    bx0, by0, bx1, by1 = mrr.bounds
    bb = (bx1 - bx0) * (by1 - by0)
    if mrr.area <= 1e-9 or bb > max_ratio * mrr.area:
        return None
    thick = min(bx1 - bx0, by1 - by0)
    d = max(float(depth or 0.0), thick + 0.06)
    half = float(door["w"]) / 2
    if (bx1 - bx0) >= (by1 - by0):                 # 墙沿 X：盒宽 X、深 Y，贴墙中线
        cy = (by0 + by1) / 2
        return _box(p.x - half, cy - d / 2, p.x + half, cy + d / 2)
    cx = (bx0 + bx1) / 2                           # 墙沿 Y：盒宽 Y、深 X
    return _box(cx - d / 2, p.y - half, cx + d / 2, p.y + half)


def box_misses_host(walls, door):
    """门洞盒是否**完全没切到**它的宿主墙（= 门还被那面墙封着）。"""
    from shapely.geometry import Point, box as _box
    p = Point(float(door["x"]), float(door["y"]))
    w, dist, g = _host_of(walls, p)
    if g is None or dist > 0.05:
        return False                    # 门心不在墙上：不是「盒放错墙」这一类问题
    try:
        b = _box(float(door["bx0"]), float(door["by0"]),
                 float(door["bx1"]), float(door["by1"]))
    except (KeyError, TypeError, ValueError):
        return False
    return g.intersection(b).area <= 1e-6


def repair_boxes(walls, doors):
    """盒没切到宿主墙的门，把盒挪到宿主墙上（就地改 bx0..by1）。返回修好的门数。

    只修**错墙**这一类（宿主墙一点没被切到）：盒本来就在正确墙上的门一个字节都不动 ——
    已交付并验过的楼（ny27 全 6 层 0 命中）重跑本函数是空操作。
    """
    n = 0
    for d in doors:
        if not all(k in d for k in ("bx0", "by0", "bx1", "by1")):
            continue
        if not box_misses_host(walls, d):
            continue
        old = None
        try:
            from shapely.geometry import box as _box
            b = _box(float(d["bx0"]), float(d["by0"]), float(d["bx1"]), float(d["by1"]))
            old = min(b.bounds[2] - b.bounds[0], b.bounds[3] - b.bounds[1])
        except Exception:                                          # noqa: BLE001
            pass
        nb = place_box_on_host(walls, d, depth=old)
        if nb is None or nb.is_empty:
            continue
        # 只写 bx0..by1（可序列化的 float）—— **不要把 shapely 对象存进门表**：本函数在
        # `_wall_thin_batch` 里是对**已反序列化的交付门表**就地改，存了 Polygon 之后下一次
        # `json.dump(fl)` 直接 TypeError，而 `open(fp,"w")` 已经把交付文件截断成 0 字节
        # （2026-09-12 c019/floor5.json 实测被截断，靠 .orig/floors.before_pairfix 才救回来）。
        d["bx0"], d["by0"], d["bx1"], d["by1"] = nb.bounds
        # 盒换了墙，「是不是外门」也跟着换 —— 直接读宿主墙的类型，不再靠门心到轮廓的距离猜。
        from shapely.geometry import Point
        hw, _, _ = _host_of(walls, Point(float(d["x"]), float(d["y"])))
        if hw is not None:
            d["outer"] = (hw.get("type") == "outer")
        n += 1
    return n


def register_hosts(doors, walls, F=None):
    """给门表就地回填宿主墙字段；返回悬空门数。

    墙一重建（`_wall_thin_batch`）宿主 id 就变了 —— 所以**每次墙定稿后都要重跑本函数**，
    这正是「单源墙」要的顺序：墙定稿 → 登记宿主 → 挖洞。

    返回的「悬空门」只算 `no_host`（墙在 0.60m 外，图纸符号真飘着）。`host_without_id`
    （墙够近但没 id）**不计入**悬空数，但会写进 `unresolved` 并在这里 `print` 报警 ——
    它不是几何问题，是登记链断了。F 给定时顺带补 id（见 ensure_wall_ids）。
    """
    if F is not None:
        ensure_wall_ids(walls, F)
    else:
        # 没给楼层号也得补，否则整批门都会被误报成悬空。
        used = {w.get("id") for w in walls if w.get("id")}
        for w in walls:
            if not w.get("id"):
                cand = "w-a%d" % len(used)
                while cand in used:
                    cand += "x"
                w["id"] = cand
                used.add(cand)
    n_orphan = n_noid = 0
    for d in doors:
        for k in ("wallId", "hostKind", "hostDist", "unresolved"):
            d.pop(k, None)
        if not all(k in d for k in ("bx0", "by0", "bx1", "by1")):
            continue
        from shapely.geometry import box as _box
        try:
            b = _box(float(d["bx0"]), float(d["by0"]), float(d["bx1"]), float(d["by1"]))
        except (TypeError, ValueError):
            continue
        wid, dist, kind = host_of(walls, b)
        d["hostDist"] = round(float(dist), 3)
        if wid is not None:
            d["wallId"] = wid
            d["hostKind"] = kind or ""
        elif dist <= HOST_MAX_DIST:
            d["unresolved"] = "host_without_id"
            n_noid += 1
        else:
            d["unresolved"] = "no_host"
            n_orphan += 1
    if n_noid:
        print("    [警告] 门宿主墙无 id：%d 道（登记链断了，不是悬空门）" % n_noid)
    return n_orphan


def _ring(coords):
    """坐标序列 → 规范化环：舍入到 mm + 起点旋到字典序最小顶点 + 去重。

    **为什么旋转起点**：shapely 的 `difference` 是重新 node 过的，几何一模一样但环的起点
    会转（实测：挖两遍对称差面积 0.000e+00，142/142 道墙的顶点序列却全不同）。顶点序列
    就是 GLB 的字节顺序，所以「几何相同、字节不同」—— 规范化后 `punch_walls` 变成真幂等，
    「这面墙挖过没有」不再影响产物字节。
    """
    pts = []
    for x, y in coords:
        q = (round(float(x), 3), round(float(y), 3))
        if not pts or q != pts[-1]:
            pts.append(q)
    while len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) > 1:
        k = min(range(len(pts)), key=lambda i: pts[i])
        pts = pts[k:] + pts[:k]
    return [[a, b] for a, b in pts]


def _snap_out(b):
    """盒压到毫米网格，边界**向外**取整。

    墙顶点存的是毫米网格值，盒边却是满精度小数 —— 两者不在同一张网格上时，差集会留下一
    条亚毫米薄片，再挖一次重新 node 就变样（c019 F4 实测 1.7e-4㎡、F0 3.3e-3㎡）。
    对齐之后挖洞**逐字节幂等**（实测 c019 F0/F4/F5 + ny27 F0/F1 最大差 0.00e+00）。

    向外取整（min 向下、max 向上）而不是四舍五入：宁可多挖半毫米，**绝不少挖** ——
    少挖会在门洞里留下一层薄膜，把本该连通的房间从门口封回两半。
    """
    import math
    from shapely.geometry import box as _box
    x0, y0, x1, y1 = b.bounds
    return _box(math.floor(x0 * 1000) / 1000.0, math.floor(y0 * 1000) / 1000.0,
                math.ceil(x1 * 1000) / 1000.0, math.ceil(y1 * 1000) / 1000.0)


def punch_walls(walls, boxes, min_area=0.03):
    """把洞口盒从墙里挖掉 —— 门 = **gap 不是 hole**（挖穿成两段，不是在内墙上开个洞）。

    **幂等**：同一组盒子挖两次 == 挖一次（环起点规范化 + 盒对齐毫米网格，见 `_ring`/`_snap_out`）；
    没被碰到的墙原样返回，连舍入都不做。所以调用方不必关心「这面墙是不是已经挖过」。

    `walls` 是墙 dict 列表；返回新的墙 dict 列表（不原地改）。碎屑（<= min_area）丢弃。
    门的 bx0..by1 字段按原样保留（渲染层拿它补门头过梁），只有挖洞用的掩膜被对齐。
    """
    if not boxes:
        return list(walls)
    from shapely.ops import unary_union
    clean = [b for b in boxes if b is not None and not b.is_empty and b.is_valid]
    if not clean:
        return list(walls)
    box_u = unary_union([_snap_out(b) for b in clean])
    if box_u.is_empty:
        return list(walls)
    out = []
    for w in walls:
        g = _poly(w)
        if g is None:
            out.append(w)
            continue
        if not g.intersects(box_u):
            out.append(w)                       # 没碰到：原样返回，不重排顶点
            continue
        try:
            cut = g.difference(box_u)
            if not cut.is_valid:
                cut = cut.buffer(0)
        except Exception:                                      # noqa: BLE001
            out.append(w)
            continue
        if cut.is_empty:
            continue
        parts = [q for q in ([cut] if cut.geom_type == "Polygon" else list(cut.geoms))
                 if q.area > min_area]
        # 大到小排：最大的一块**继承原 id**（窗的 wallId 正指着它，不能被改走），其余各块另给
        # 唯一 id。全都继承会让 `build_walls` 把窗匹配到**每一块**（窗被复制到所有碎片上）——
        # 这正是 `_door_punch_apply` 当初单开一份 punch 的原因，现在收回到这里。
        parts.sort(key=lambda q: (-q.area, q.bounds))
        for k, q in enumerate(parts):
            nw = dict(w)
            if k and w.get("id"):
                nw["id"] = "%s#%d" % (w["id"], k)
            nw["poly"] = _ring(q.exterior.coords)
            nw["holes"] = [h for h in (_ring(i.coords) for i in q.interiors) if len(h) >= 3]
            out.append(nw)
    return out


def buried_doors(walls, doors):
    """门心落在墙身上的门数 —— 「门夹在实心墙里看不到」的**直接**判据。

    与 `punch_through_rates` 的分工：那个量「洞口还剩多少墙」，这个量「门扇在不在墙里」。
    门开在墙交叉/墙端时，洞口大半是空的、门心却仍落在墙上 —— 这种情况以本判据为准
    （`_door_punch_apply` 的 dry-run 报表用的也是它，两边必须是同一个定义）。

    用墙 union 上的 `covers` 而不是「逐个墙 `contains`」：门心正落在两片墙共用的面上时，
    逐墙判会两边都不算、把一扇压在墙里的门漏掉；union 之后那条缝是内部，`covers` 为真。
    """
    from shapely.geometry import Point
    from shapely.ops import unary_union
    gs = [g for g in (_poly(w) for w in walls) if g is not None]
    if not gs:
        return 0
    W = unary_union(gs)
    n = 0
    for d in doors:
        try:
            p = Point(float(d["x"]), float(d["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        if W.covers(p):
            n += 1
    return n


def punch_through_rates(walls, boxes):
    """一组洞口盒的「挖穿率」= 盒内没有墙的面积占比。1.0 = 彻底挖穿。

    门禁用：洞没挖穿 → 房间会从残留的墙缝/墙里漏（见 §7 P1 的接头缝问题）。
    **墙只 union 一次** —— 逐洞 union 是 O(洞×墙)，c006 一层 702 道门会跑成分钟级。
    """
    from shapely.ops import unary_union
    if not boxes:
        return []
    gs = [g for g in (_poly(w) for w in walls) if g is not None]
    if not gs:
        return [1.0] * len(boxes)
    W = unary_union(gs)
    out = []
    for b in boxes:
        if b is None or b.is_empty or b.area <= 0:
            out.append(1.0)
            continue
        out.append(1.0 - W.intersection(b).area / b.area)
    return out


def punch_through_rate(walls, door_box):
    """单个洞口的挖穿率；批量请用 punch_through_rates。"""
    return punch_through_rates(walls, [door_box])[0]
