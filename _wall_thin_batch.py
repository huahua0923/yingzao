# -*- coding: utf-8 -*-
"""R11/R12 宿舍公寓簇内墙解融批量(仅处理与 c031 同构的安全子集)。
前置(c031 验证过的假设): 非冻结 + 有薄外墙环(net outer<=14% outline, 且外墙带洞) + 内墙 blob
     (并集覆盖率 cover>20% **或** 并集平均厚度 t>0.30m —— 见 is_blob_floor())。
逐层 .orig 备份 -> 双线配对重建内墙 -> 数值验收 -> 不通过自动回滚该层。
安全门槛: 不符合前置的楼整栋跳过(不碰), 报告留给逐栋人工。冻结楼 c006/c009/c103/c104 永不碰。
验收(逐层，权威是 verify_floor() 的返回式): A 内墙条数>8  B 净覆盖<=20%  C 无单墙>楼板40%
     D 门贴墙>=85%(若该层有门)  E 房∩墙**均值<=10%**(若该层有房)
"""
import json, glob, os, sys, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer.profile import floor_of, to_local
from backend.recognizer.floor import expand_shared_sheets
from backend.recognizer import geometry as G
from backend.recognizer import openings
from backend.recognizer import stairs as _stairs
from backend.recognizer.component_library import is_door_symbol_pts
from backend.recognizer import curve_walls as CW
from backend.recognizer import outline as OUT
from shapely.geometry import Polygon, Point, LineString, box
from shapely.ops import unary_union

# 名单的**唯一来源**是 backend/paths.py（2026-09-14 收敛；见那里的注释）。
from backend.paths import FROZEN_BUILDINGS as FROZEN  # noqa: E402

ALL = sorted(os.listdir(r"D:\gym3d\data\buildings"))


def dump_floor(fp, fl):
    """交付楼层 JSON 的唯一写入口：**先写临时文件再原子替换**。

    直接 `open(fp, "w")` 会在序列化失败时把交付文件截成半截 —— 2026-09-12 门表里混进一个
    shapely Polygon，`json.dump` 抛 TypeError，c019/floor5.json 当场被截断（180KB 半截）。
    临时文件 + `os.replace` 让「写失败」退化成「文件没变」，最坏也只是重跑一次。
    """
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(fl, f, ensure_ascii=False)
    os.replace(tmp, fp)


def safe_union(polys):
    clean = []
    for P in polys:
        if P is None or P.is_empty:
            continue
        if not P.is_valid:
            P = P.buffer(0)
        if not P.is_valid or P.is_empty:
            continue
        clean.append(P)
    if not clean:
        return None
    try:
        U = unary_union(clean)
    except Exception:
        # 退而求其次逐个 buffer 后并
        U = None
        for P in clean:
            U = P if U is None else U.union(P.buffer(0))
    return U

# blob 的第二个判据：内墙并集平均厚度 t = 2*面积/周长（并集周长含两侧，故系数 2）。
# 全库交付态普查（_scratch/_o_blob_thickness_census.py，295 层）实测：真薄墙层 t 全 ≤0.22m，
# 团块层全 ≥0.42m，中间是**空档**；0.30 两边各留 ~1.4 倍余量。
BLOB_MEAN_THICKNESS = 0.30

def is_blob_floor(fl):
    """该层内墙是不是「融成一团」需要重建 —— 判据：并集覆盖率 cov>20% **或** 平均厚度 t>0.30m。

    原判据是 `cov>20 且 (内墙条数<=8 或 有单墙>35%楼板)`。后半句是照**少量大块**的宿舍 blob
    画像写的，会漏掉「**多块中等**」的 blob：c009 第 1 层 17 块、cov 59.2%、最大块 2472㎡
    只占楼板 30.5%（阈值 35%），两个条件都不成立 → 不重建 → 交付里留着一层 4797㎡ 的「内墙」，
    而用户实拍俯视图里那一层是教室+院子，根本不长这样。

    全楼普查（_scratch/_dbg_blob_census.py，逐层跑 49 栋）显示改成 cov>20 单独之后
    **只多认出 6 层**：c009 F1 与 c103 F0~F4，cov 全在 54~59%；而真薄墙楼层实测 cov 只有
    6.5~8.2% —— 判别两边各有 2.5 倍余量，没有任何一层被误伤，也没有一层从「是」翻成「否」。

    **2026-09-12 加 t 判据（c034 F1~F3 判例）**：cov 是**相对量**（分母=本层轮廓），于是
    「大楼真薄墙」与「小楼真厚墙」会挤进同一段区间 —— 小楼天然偏高（ny28 一层 181㎡、15 道
    真内墙，cov 15%），高楼真薄墙偏低（6~8%），判别的安全边际被楼大小吃掉。c034 F1~F3 的团
    被轮廓裁成 299㎡/1565㎡ = **19.1%，离阈值只差 1.1 个百分点**，于是没被判成 blob，重建
    **根本没被尝试过**，交付里留着 5 块大团（每块是「一层内区填实、房间挖成洞」的多边形，
    最大一块 bbox 7.8m×23.4m）。探针（_scratch/_o_blob_probe.py，只读不写盘）实测：这三层
    交给重建就是 355 块薄墙 / 净覆盖 8.4% / 单块最大 9.8㎡ / 门贴墙 100% / 房∩墙 0.0%，
    稳过门禁。t 是**绝对量**、与楼大小无关，正是为了补上这个洞。

    放宽的代价为零：重建若不通过 `verify_floor` 就 `continue`，交付文件一个字节都不动
    （= 保持现状），所以「多尝试」只可能变好、不会变坏。
    """
    inn = [w for w in fl["walls"] if w["type"] == "inner"]
    ol = OUT.floor_outline(fl)          # 多块楼层：主块 ∪ 次块（覆盖度分母要全足迹）
    if not inn or not ol.is_valid or ol.area < 1:
        return False
    U = safe_union([Polygon(w["poly"]) for w in inn])
    if U is None:
        return False
    if 100 * U.area / ol.area > 20:
        return True
    return U.length > 0 and 2 * U.area / U.length > BLOB_MEAN_THICKNESS

PAPER_MIN_DIM = 0.08


def _is_paper(P):
    """「纸皮」= 图纸上不存在的残条，不是墙。

    判据（任一成立即纸皮）：
      · `2*面积/周长 < 0.05` —— 退化到没有厚度可言；
      · bbox 短边 < 0.08m **且** `2*面积/周长 < 0.12` —— 一条几厘米厚的窄条。
    两条都要求「窄」，是因为 `2A/P` 对**非矩形**（L 形/T 形接点残片）会低估：ny27 w0-i16
    bbox 2.94×0.24、`2A/P`=0.091，但短边 0.24 是实打实的墙 —— 只看 `2A/P` 会把它误杀。
    实测本案（ny27 F0 南立面）：w0-i0..i4 短边 0.015~0.068、`2A/P` 0.011~0.064 → 全部命中；
    同一层真墙短边全 ≥0.10 → 一条不误伤。

    来历：合成外墙环内皮(y=−8.60)与图纸真外墙内皮(y=−8.518)差 8cm，配对出的真墙矩形被
    环的洞裁剩 6cm 残条，当内墙交付（用户 2026-09-12：「内墙 · 1层内墙 #5，为啥会有，
    前面说过，内墙和外墙不能重复出现」）。
    """
    if P.length <= 0:
        return True
    thin = 2 * P.area / P.length
    if thin < 0.05:
        return True
    x0, y0, x1, y1 = P.bounds
    return min(x1 - x0, y1 - y0) < PAPER_MIN_DIM and thin < 0.12


def _interior_mask(fl, oline):
    """内墙裁剪域 = 轮廓 − **交付外墙本体**（外扩 0.01 再减）。

    对**新旧两套交付产物都成立**，所以是全库唯一的一条：
      · 旧产物：外墙是`outline.buffer(-outer_t)` 合成环（一个带大孔的环）→
        `轮廓 − 环` 就是环的那个孔，与旧写法「取所有孔之并」逐值同义；
      · 新产物（recognize 读图成图，见 [[ny27-unified-drawing-scheme]]）：外墙就是图上配出的
        真矩形，没有孔 → `轮廓 − 真外墙` 才对；旧写法会退到「轮廓内缩 0.16」这个写死的厚度，
        已与 recognize 不一致。
    取**本体**而不是「孔」还有一处必要：多块楼层（双塔/双翼，全库 21 栋 53 层）每块各有一圈
    外墙，只取第一面的孔会把其余块的配对墙整片裁掉（c086 F1 阳台栏板被裁成 0.0000㎡ 就是这条）。

    只用来判「是不是内墙」，不新增任何墙；退化时回落到轮廓内缩 0.16。
    """
    outs = []
    for w in fl["walls"]:
        if w["type"] != "outer":
            continue
        try:
            op = Polygon(w["poly"], w.get("holes") or [])
        except Exception:                                              # noqa: BLE001
            continue
        if not op.is_valid:
            op = op.buffer(0)
        if not op.is_empty and op.area > 1e-6:
            outs.append(op)
    mask = None
    if outs:
        mask = oline.difference(unary_union(outs).buffer(0.01)).buffer(0)
    if mask is None or mask.is_empty or mask.area < 1.0:
        mask = oline.buffer(-0.16)
    return mask if mask.is_valid else mask.buffer(0)


def rebuild_floor(fl, p, raw, F):
    """返回新内墙列表; 失败返回 None。raw = 该层 DXF 墙线(已 to_local)。"""
    oline = OUT.floor_outline(fl)
    # 楼梯踏步线/休息平台线（2 点水平短段，同 y 聚 >=4）与踏步端点连线不是墙：不剔除会
    # 与相邻踏步（间距 0.3m ∈ wall_min~wall_max）配成 0.3m 假墙塞满楼梯井（用户「楼梯识别成
    # 内墙」根因，同 _derive_paired_walls_and_outline 的剔除）。在「多段线粒度」先剔再拆段。
    _tread_idx = G._stair_tread_indices(raw)
    _mid_idx, _band_idx = G._stair_mid_band_indices(raw, _tread_idx,
                                                   getattr(p, "wall_min", 0.08))
    # 三样都不是墙，也不该落进配对：
    #  · 踏布线 / 踏步端点连线（含休息平台线）—— 老根因「楼梯识别成内墙」；
    #  · 楼梯中缝三线整组 —— 用户 c018「内墙 #94 这个些不对，这个位置就是楼梯的位置」，
    #    这块 0.20×3.20 的带就是两跑之间的分界/扶手；
    #  · 洁具开口小矩形（和墙同图层）—— 用户 c018「这代表厕所，不用画了」。
    _fix_idx = G.fixture_indices(raw, getattr(p, "fixture_max", 0.8))
    _drop = set(_tread_idx) | set(_mid_idx) | set(_band_idx) | _fix_idx
    _keep = [loc for i, loc in enumerate(raw) if i not in _drop]
    segs = G._flatten_wall_segments(_keep)
    if not segs:
        return None
    rects, singles = G.pair_wall_faces(segs, p)
    if getattr(p, "pair_curved", False):
        # 斜墙/曲墙(opt-in): 轴对齐段已由上面配走, 这里只吃斜段, 两边不重叠。
        # 厚度取两皮实测间距(该楼无 wall_thicknesses snap 时不冲突; 有 snap 的楼不启用本项)。
        _axis2, _diag = CW._flatten_all_segments(_keep)
        cr, cs = CW.pair_curved_faces(_diag, p)
        rects = list(rects) + list(cr)
        singles = list(singles) + list(cs)
    # 内墙裁剪域 = 轮廓 − 交付外墙本体。外墙由 recognize 照图交付（用户 2026-09-12
    # 「你不能臆想的创造墙，而是严格按照图纸来」「建筑的做法全部用一个方案，没有特殊」），
    # 这里只判「这条配对矩形是不是内墙」，不新增/改写任何外墙。
    interior_mask = _interior_mask(fl, oline)
    inner_walls = []
    rect_area = 0.0; total_area = 0.0
    for poly, t in rects:
        pc = poly.intersection(interior_mask).buffer(0)
        if pc.is_empty:
            continue
        for P in ([pc] if pc.geom_type == "Polygon" else list(pc.geoms)):
            if P.area > 0.03 and not _is_paper(P):
                rect_area += P.area
                inner_walls.append({"type": "inner",
                                    "poly": [[round(x, 3), round(y, 3)] for x, y in P.exterior.coords][:-1],
                                    "holes": [], "thickness": round(t, 2), "height": 4.2})
    for s in singles:
        pc = LineString(s).buffer(p.single_wall_t / 2).intersection(interior_mask).buffer(0)
        if pc.is_empty:
            continue
        for P in ([pc] if pc.geom_type == "Polygon" else list(pc.geoms)):
            if P.area > 0.03 and not _is_paper(P):
                inner_walls.append({"type": "inner",
                                    "poly": [[round(x, 3), round(y, 3)] for x, y in P.exterior.coords][:-1],
                                    "holes": [], "thickness": round(p.single_wall_t, 2), "height": 4.2})
    # 顺序铁律：墙定稿 → 盒归位到宿主墙 → 挖洞 → 给 id。
    # 盒归位要在挖洞之前：门洞盒是「门心到轮廓的距离」定的，门开在与轮廓平行的内墙上时
    # 盒会整块落在内墙之外（c019 F0 实测 10 扇），外墙被挖穿而门仍旧夹在内墙里。
    probe = [w for w in fl["walls"] if w.get("type") != "inner"] + inner_walls
    n_fix = openings.repair_boxes(probe, fl.get("doors") or [])
    if n_fix:
        print("   %s F%d 门洞盒归位到宿主墙 %d 扇" % (p.name, F, n_fix))
    # 挖洞在给 id 之前：punch 会把一面墙切成两段，两段都 `dict(w)` 继承同一个 id →
    # 重 id 会让两道门指到同一个墙名上。id 给完之后 process() 里还会重登记一次宿主。
    inner_walls = _punch_doors(inner_walls, fl)
    for i, w in enumerate(inner_walls):
        w["id"] = "w%d-i%d" % (F, i)
    total_area = sum(Polygon(w["poly"]).area for w in inner_walls)
    rect_share = (rect_area / total_area) if total_area else 0
    return inner_walls, rect_share


def _punch_doors(inner_walls, fl):
    """把门洞从内墙里挖穿（门 = **gap 不是 hole**）。

    recognize 阶段 `_door_boxes` 已把「门洞盒」（深 = max(外墙厚,内墙厚)+0.05 > 墙厚）算好
    写在每个门的 bx0..by1。本函数把盒从重建出来的内墙上减掉 —— 否则 pair_wall_faces 配出的
    内墙是连续的，门板被封在实心墙里 = 用户报的「门有的夹在墙里看不到」。

    **实现已统一到 `recognizer.openings.punch_walls`**（2026-09-11）：原先这里和 `floor.py`
    各有一份挖洞代码，改一处漏一处。挖洞是幂等的，所以「挖两遍」几何上无害；有害的是有两份
    实现。本地保留同名薄封装，是为了不惊动调用点与既有验证脚本。

    只在门带 bx0..by1 时生效：旧交付楼层没有这些字段 → no-op。
    """
    boxes = []
    for dd in fl.get("doors") or []:
        try:
            boxes.append(box(float(dd["bx0"]), float(dd["by0"]), float(dd["bx1"]), float(dd["by1"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not boxes:
        return inner_walls
    return openings.punch_walls(inner_walls, boxes)


def finalize_floor(fl, F):
    """墙定稿后的**唯一**收尾口：登记门窗宿主（BIM 的 hosted element）。

    任何改写 `fl["walls"]` 的地方都必须走这里 —— `process()` 重建内墙后、`_wall_thin_force`
    强制重跑后。先前 `_wall_thin_force` 就是漏了这一口的第二个所有者（墙换了、宿主还指着旧
    id），这正是 P2 要断掉的「两份实现改一处漏一处」。

    楼梯井道 `shaft` **不在这里**：它是跨层量，必须等全楼写盘后统一算一次
    （`refresh_shafts`）。逐层算完就写会把跨层并集切碎。

    返回悬空门数（宿主墙在 0.60m 外的门）。
    """
    return openings.register_hosts(fl.get("doors") or [], fl["walls"], F)


def refresh_shafts(name):
    """全楼写盘后刷新楼梯井道（`stairs.attach_shafts_to_floors` 的唯一调用口）。

    `stairwells[i]["shaft"]` 是「踏步盒四向扩到墙，再跨层取并集」，两件事都要求墙已经定稿、
    且**全部**楼层都在手上：逐层算会把井道切成每层各一半（c027 顶层只画了到达的那一跑）。
    楼板洞（`build_slab`）与围合判据都读它，所以这里是墙定稿之后、产物交付之前的最后一刀。

    返回 (改了井道的楼层数, 合并出的井道组数)。
    """
    fd = os.path.join(r"D:\gym3d\data\buildings\%s" % name, "floors")
    floors = []
    for fp in sorted(glob.glob(os.path.join(fd, "floor*.json"))):
        fl = json.load(open(fp, encoding="utf-8"))
        floors.append([fp, fl, _shaft_snapshot(fl)])
    if not any(fl.get("stairwells") for _, fl, _ in floors):
        return 0, 0
    # ★ 先按**已定稿的墙**重算井，再挂井道 —— 顺序不能反（根因 B，见 _recompute_stairwells）
    _recompute_stairwells(name, floors)
    ngroups = _stairs.attach_shafts_to_floors([fl for _, fl, _ in floors])
    n = 0
    for fp, fl, before in floors:
        if _shaft_snapshot(fl) == before:
            continue                      # 没变就不重写，别把交付文件的排版搅乱
        dump_floor(fp, fl)
        n += 1
    if n:
        print("   %s 井道刷新 %d 层 / %d 口井 —— 楼板洞已变，**需重建 GLB**" % (name, n, ngroups))
    return n, ngroups


def _shaft_snapshot(fl):
    """井道刷新「变了没有」的比对口径：井列表 + 每口井的 shaft。"""
    return [(s.get("x0"), s.get("x1"), s.get("yBot"), s.get("yTop"),
             repr(s.get("shaft"))) for s in (fl.get("stairwells") or [])]


def _recompute_stairwells(name, floors):
    """★ 用**已定稿的墙**重算每层 `stairwells`（根因 B）。

    为什么必须重算：`rebuild_floor` 只换 `fl["walls"]`，`stairwells` 还是 recognize 那一刻
    用**旧墙**算的快照。墙换了、井记录没换，`attach_shafts_to_floors` 就拿着旧井去扩墙，
    扩出来的 `shaft` 与真墙错位（只读模拟：ny27 `w0-i21` 与井重叠 2.04m → 重算后 0.24m）。
    楼梯井的定义就是**踏步线包围盒**，而踏步线在墙线里 —— 墙一变它必然要跟着变。

    ⚠️ 必须喂**模型空间 mm 原始线**：`detect_stairwells` 内部自己做 `floor_of` / `to_local`。
    `wall_lines_by_floor` 出来的是**局部米**的线，喂进去 `floor_of` 全落到 F0，
    其余各层一律 0 口井（静默失效）。这里走 `classify(doc.modelspace(), p)[0]` 拿原始线，
    与 `floor.py:439` 的调用完全同源。

    只在**已经有井记录**的楼上跑（调用方已守卫）：不主动给「原先判为无井」的楼层塞井，
    免得凭空引入假井。返回改动的楼层数（仅用于日志）。
    """
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    walls_dxf = classify.classify(doc.modelspace(), p)[0]
    n = 0
    for fp, fl, _ in floors:
        if not fl.get("outline"):
            continue
        F = int(os.path.basename(fp)[5:-5])
        oline = OUT.floor_outline(fl)
        if not oline.is_valid:
            oline = oline.buffer(0)
        ws = [s for s in G.detect_stairwells(F, walls_dxf, p)
              if Point((s["x0"] + s["x1"]) / 2,
                       (s["yBot"] + s["yTop"]) / 2).distance(oline) <= 1.0]
        if ws != (fl.get("stairwells") or []):
            fl["stairwells"] = ws
            n += 1
    if n:
        print("   %s 楼梯井按定稿墙重算：%d 层记录已陈旧" % (name, n))
    return n


def verify_floor(fl, inner_walls, oline, ol_area):
    innerU = safe_union([Polygon(w["poly"]) for w in inner_walls]) if inner_walls else None
    inner_area = innerU.area if innerU else 0
    cover = 100 * inner_area / ol_area
    big = sum(1 for w in inner_walls if Polygon(w["poly"]).area > 0.4 * ol_area)
    otherU = safe_union([Polygon(w["poly"]) for w in fl["walls"] if w["type"] != "inner"]) if any(w["type"] != "inner" for w in fl["walls"]) else None
    if innerU is not None:
        wallU = innerU if otherU is None else safe_union([innerU, otherU])
    else:
        wallU = otherU
    nd = len(fl.get("doors", []))
    dgood_pct = 100
    if wallU is not None and nd:
        # <1.0m: 覆盖「门在洞中」直到 2m 双开门洞(中点距墙端<=1.0m); 真漏墙/浮门仍>1.0m 被拒
        dgood_pct = 100 * sum(1 for dd in fl["doors"] if wallU.distance(Point(dd["x"], dd["y"])) < 1.0) / nd
    ov_mean = 0
    rooms = [r for r in fl.get("rooms", []) if len(r.get("poly", [])) >= 3]
    if rooms and innerU is not None:
        vals = []
        for r in rooms:
            try:
                P = Polygon(r["poly"])
            except Exception:
                continue
            if P.is_valid and P.area > 0.5:
                vals.append(100 * P.intersection(innerU).area / P.area)
        ov_mean = sum(vals) / len(vals) if vals else 0
    ok = (len(inner_walls) > 8 and cover <= 20 and big == 0 and dgood_pct >= 85 and ov_mean <= 10)
    return ok, len(inner_walls), cover, big, dgood_pct, ov_mean

def wall_lines_by_floor(p, walls_dxf):
    """按楼层分墙线(本地米坐标)，并剔除「门符号」折线。

    门符号(门扇线 + 门垛的闭合环)和墙同图层，会被 pair_wall_faces 配成一块
    ~0.9~1.5m × 0.10~0.24m 的假墙，正盖在门洞位置上 —— 用户报的「门有的夹在墙里
    看不到」的根因(c019 每层约 285 块)。判门只看折线形状、不依赖这里，剔除不影响门识别。
    """
    out = {}
    for w in walls_dxf:
        cx = sum(a for a, b in w) / len(w)
        cy = sum(b for a, b in w) / len(w)
        F = int(round(floor_of(p, cx, cy)))
        loc = [(float(a), float(b)) for a, b in [to_local(p, a, b, F) for a, b in w]]
        if is_door_symbol_pts(loc):
            continue
        out.setdefault(F, []).append(loc)
    return out


def process(name):
    d = r"D:\gym3d\data\buildings\%s" % name
    fd = os.path.join(d, "floors")
    if not os.path.isdir(fd):
        return None, "无 floors"
    # 先找 blob 层(轻量, 不 classify): 无 blob 直接跳过
    blob_floors = []
    all_floors = []
    for fp in sorted(glob.glob(os.path.join(fd, "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        all_floors.append((fp, F, fl))
        if is_blob_floor(fl):
            blob_floors.append((fp, F))
    if not all_floors:
        return None, "无楼层"
    # P2 收尾：门宿主登记。已薄的楼层不走重建，但墙早已定稿，只需补 id 与宿主字段 —— 不补
    # 的话「门开在哪面墙上」这条链断在交付物里（P2 门禁会红）。
    # 只对**有门洞盒**的楼做：其余楼的门还没有盒子（识别链早于门洞盒特性），登记了也无从指起，
    # 等它们重跑识别链时自然补上（YAGNI，不做 49 栋的空写）。
    n_fin = 0
    if any("bx0" in dd for _, _, f in all_floors for dd in (f.get("doors") or [])):
        for fp, F, fl in all_floors:
            if is_blob_floor(fl):
                continue                      # 重建路径里会登记
            try:
                n_orphan = finalize_floor(fl, F)
            except Exception as e:             # noqa: BLE001
                print("   %s F%d 宿主登记异常：%s" % (name, F, str(e)[:70]))
                continue
            dump_floor(fp, fl)
            n_fin += 1
            if n_orphan:
                print("   %s F%d 悬空门 %d 个（已记 unresolved）" % (name, F, n_orphan))
    if not blob_floors:
        refresh_shafts(name)
        return ([], [], n_fin), None
    # 前置: 薄外墙环(用首层判断)
    first = all_floors[0][2]
    ol = OUT.floor_outline(first)
    outers = [w for w in first["walls"] if w["type"] == "outer"]
    if not outers:
        return None, "无外墙类型(跳过-需逐栋分析)"
    try:
        onet = sum(Polygon(w["poly"]).area - sum(Polygon(h).area for h in w.get("holes", [])) for w in outers)
    except Exception:
        onet = 1e9
    if ol.is_valid and ol.area > 1 and onet / ol.area > 0.14:
        return None, "外墙net>14%或非薄环(跳过-需逐栋分析)"
    # 一次性 classify 并按层分墙线
    try:
        p = load_profile(name)
        doc = ezdxf.readfile(p.dxf)
    except Exception as e:
        return None, "DXF读失败 %s" % e
    msp = doc.modelspace()
    walls_dxf, doors, stairs, cols = classify.classify(msp, p)
    # 一张图描述多层（profile.sheet_floors）：这里必须跟 recognize 并同一刀。
    # 薄墙重建是**直接从 DXF 原始折线**分层的（wall_lines_by_floor），用的是 recognize 之前
    # 的墙；若不并，第 0 张图的墙线会被分到已不存在的层 0、整批丢掉 —— 等于把 recognize 刚并进
    # 1/2 层的圆厅墙又抹掉，而且外层看不出（薄墙重建只换内墙，不报错）。
    walls_dxf, doors, stairs, cols = expand_shared_sheets(p, walls_dxf, doors, stairs, cols)
    raw_by_floor = wall_lines_by_floor(p, walls_dxf)

    bak = os.path.join(d, ".orig", "floors.before_wallthin")
    os.makedirs(bak, exist_ok=True)
    ok_f, fail_f = [], []
    for fp, F in blob_floors:
        fl = json.load(open(fp, encoding="utf-8"))
        try:
            if not os.path.exists(os.path.join(bak, os.path.basename(fp))):
                shutil.copy2(fp, os.path.join(bak, os.path.basename(fp)))
            inner_walls, rect_share = rebuild_floor(fl, p, raw_by_floor.get(F, []), F)
            if inner_walls is None:
                fail_f.append((F, "无墙线")); continue
            olf = OUT.floor_outline(fl)
            ok, nw, cover, big, dgood, ovm = verify_floor(fl, inner_walls, olf, olf.area)
            if not (ok and rect_share >= 0.30):
                fail_f.append((F, "nw=%d cov=%.0f%% big=%d door=%.0f%% ov=%.1f%% rect=%.0f%%"
                               % (nw, cover, big, dgood, ovm, 100 * rect_share)))
                continue
            keep = [w for w in fl["walls"] if w["type"] != "inner"]
            fl["walls"] = keep + inner_walls
            # 墙定稿 → 重登记门宿主（内墙换了 id，recognize 时的宿主登记已失效）。
            # 顺序铁律：先定墙、再登记宿主，最后才让房间读这份墙（见 §4 新流程）。
            n_orphan = finalize_floor(fl, F)
            if n_orphan:
                print("   %s F%d 悬空门 %d 个（已记 unresolved）" % (name, F, n_orphan))
            dump_floor(fp, fl)
            ok_f.append((F, nw, cover))
        except Exception as e:
            fail_f.append((F, "异常:%s" % str(e)[:60]))
    refresh_shafts(name)                   # 全楼写盘后统一算井道（跨层并集）
    return (ok_f, fail_f, n_fin), None


if __name__ == "__main__":
    # 逐栋：python -u _wall_thin_batch.py ny27 c019
    # 全量：python -u _wall_thin_batch.py --all
    # 先前这里忽略 argv、无条件遍历全部 48 栋 —— README 却写着「<name>」，照文档敲一次就是
    # 全仓写盘。改成显式二选一，不给「敲了参数却跑全量」的机会。
    argv = [a for a in sys.argv[1:] if a.strip()]
    if not argv:
        print(__doc__)
        print("用法: python -u _wall_thin_batch.py <楼> [<楼>...]   |   --all")
        sys.exit(2)
    if argv == ["--all"]:
        names = [n for n in ALL if n not in FROZEN]
    else:
        names = [n for n in argv if n != "--all"]
        bad = [n for n in names if n not in ALL]
        if bad:
            sys.exit("未知楼名: %s" % ", ".join(bad))

    summary = []
    for name in names:
        res, err = process(name)
        if err is not None:
            summary.append((name, "SKIP", err))
            continue
        ok_f, fail_f, n_fin = res
        if ok_f:
            summary.append((name, "FIXED %d层" % len(ok_f),
                            "样例cover: " + ",".join("%.0f%%" % c for _, _, c in ok_f[:3])
                            + ("；另登记宿主 %d 层" % n_fin if n_fin else "")))
        elif n_fin:
            summary.append((name, "宿主 %d层" % n_fin, "无 blob 层（已是交付墙），仅补门宿主"))
        elif fail_f:
            summary.append((name, "SKIP", "全部blob层失败(已回滚)"))
        else:
            # 无 blob 层、无门洞盒 → process() 直接 refresh_shafts() 返回 ([], [], 0)。
            # 原先这个分支落到上面那句「全部blob层失败(已回滚)」—— 把「无事可做」报成
            # 「全失败并已回滚」，纯误报（2026-09-12 B 铺开 9 栋逐栋如此）。
            summary.append((name, "SKIP", "无待办（无 blob 层、无门洞盒）"))
        if fail_f:
            print("  %s 失败回滚层: %s" % (name, fail_f[:4]), flush=True)

    print("\n==== 批量结果 ====")
    for name, st, note in summary:
        print("%-6s %-14s %s" % (name, st, note))
