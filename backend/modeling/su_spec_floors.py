# -*- coding: utf-8 -*-
"""理化楼：GLB 管道 → **分层** SU 建体 spec（房间地垫按用途分色 + 注释表）。

与 `su_spec.py` 的关系：同一个机制（`SuRecorder` 换掉 `G.MeshBuilder`，调**同一个**
`main()`），所以 SU 里的楼与交付 GLB 逐构件同源。本文件是它的**子类**，只多三件事：

  ① 每个部件带 `band` / `floor` 分带 —— `band = ⌊z0/floor_h + 1e-6⌋`，与
     `build_model.rb` 的 `BAND` **同一个式子**（两侧必须同式，否则组会串层）。
     `band ≥ 层数` 归屋顶（band=-1）。分带正确性靠**逐带锚点**反证：楼板 1 块、
     结构柱 == 图上的柱数、玻璃 == 窗数、窗框 == 4×窗数、地垫 == 房间数。
  ② 房间地垫按**用途**改色（`build_rooms()` 铺的 118 块 C_SLAB 地垫 → 13 类用途色），
     识别 + 硬校验见 `_recolor_rooms`，不猜。
  ③ 出 `rooms_label[]` / `meta.groups` / `meta.purposeColors` 供 SU 侧直接建注释与分组。

**为什么要硬校验**：`build_rooms()` 是管道里唯一按房间铺几何的地方，但它不带任何
标识（颜色与楼板同为 C_SLAB、kind 同为 wall、col_side 同为 None），只能按
「厚度 == ROOM_PAD」认。认错了不会报错、只会静默给错房间上色，所以宁可中止。

用法: python backend/modeling/su_spec_floors.py [-o 输出.json]
"""
import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
for p in (BACKEND, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shapely.geometry import Polygon                                        # noqa: E402
from glb_common import (MeshBuilder, C_SLAB, C_GLASS, C_FRAME, C_COLUMN,   # noqa: E402
                        C_STAIR, C_WALL, C_DOOR)
import build_standard_glb as G                                              # noqa: E402
from su_spec import SuRecorder, hexc, shoelace                              # noqa: E402

DEFAULT_OUT = os.path.join(ROOT, "_scratch", "su_jobs", "_lihua_floors_spec.json")

# 13 类用途 → 4 族配色。族内靠明度/彩度区分，**与建筑自身九色错开**
# （#a4533d 立面 / #cfc9bd 室内 / #ece6dc 楼板 / #6b5a4a 屋面 / #6a4a40 女儿墙 /
#  #789cb8 玻璃 / #c2c7ce 窗框 / #5c3a1e 门 / #d0c198 楼梯 / #9aa2b0 柱 / #80848e 默认墙）。
PURPOSE_COLOR = {
    # 实验族：冷蓝绿
    "实验室":       "#1f7a99",
    "实验辅助用房": "#38a0b8",
    "实验准备室":   "#155f78",
    "实验专用库房": "#6cc3d4",
    # 办公族：暖黄橙
    "教师工作室":   "#c8871f",
    "办公室":       "#e0a63c",
    "其他办公用房": "#a06a12",
    "学生工作室":   "#f0c766",
    # 会议研讨族：紫红
    "研讨室":       "#9a4a84",
    "会议室":       "#b56a9e",
    "报告厅":       "#74305f",
    # 辅助后勤族：灰绿
    "值班室":       "#6b7d74",
    "资料室":       "#97a99f",
}
PURPOSE_FAMILY = {
    "实验室": "实验", "实验辅助用房": "实验", "实验准备室": "实验", "实验专用库房": "实验",
    "教师工作室": "办公", "办公室": "办公", "其他办公用房": "办公", "学生工作室": "办公",
    "研讨室": "会议", "会议室": "会议", "报告厅": "会议",
    "值班室": "辅助", "资料室": "辅助",
}

# 构件类别 —— SU 侧一个类别一个 Tag（`yz构件-墙`），关掉「墙」「窗」两个 Tag
# 就是「墙体隐藏、窗户隐形」的每层平面。顺序即 Tag 顺序（建筑构件在前，房间在后）。
CAT_ORDER = ["墙", "窗", "门", "楼梯", "柱", "楼板", "地垫", "屋顶", "场地", "其他"]

# 场地/散水（**只在 SU 侧**，不进交付 GLB）：首层轮廓外扩一圈的环形板，顶面齐 z=0
# （首层楼板底面那个标高）。为什么要有它：原来「地面」= 首层楼板自己，从外侧看不出
# 建筑坐落在什么上。环形的**内边界**贴着楼板外皮，所以两者不共面、也不重叠。
C_SITE = "#7d766b"
SITE_CAT = "场地"
SITE_SUB = "场地"
SITE_WIDTH = 1.5                     # 散水/场地宽度（m）
SITE_THICK = 0.15                    # 板厚（m），z ∈ [-0.15, 0]


class VerifyError(Exception):
    """验收不通过 —— 不写盘，把实测数字打出来让人看。"""


def band_of(z0, floor_h):
    """与 `build_model.rb` 的 BAND 同一式子（浮点直接整除会把 4.2k/4.2 分错层）。"""
    return int(math.floor(z0 / floor_h + 1e-6))


def color_areas(parts):
    """逐色解析面积 —— 与 `_scratch/_a0_glb_color_check.py:spec_areas` 同一算法。

    那条链已在 ny27 上验到 spec 与交付 GLB 逐色 0.00%（只有两个色差 1 个最低位），
    所以这里拿它当「SU 里的楼 == 交付 GLB」的对账口径：侧面按 `edgeCols` 逐边取色，
    上下盖按 `cap` 算两块（洞要减掉），整件单色时侧面也用 `cap`。
    """
    a = defaultdict(float)
    for p in parts:
        h = p["z1"] - p["z0"]
        a[p["cap"]] += 2 * shoelace(p["ext"]) - sum(2 * shoelace(hn) for hn in p["holes"])
        rings = [(p["ext"], p["edgeCols"])] if p["edgeCols"] else []
        rings += [(hn, cc) for hn, cc in zip(p["holes"], p["holeEdgeCols"])]
        if not rings:                                    # 整件单色
            for ring in [p["ext"]] + p["holes"]:
                for i in range(len(ring)):
                    x1, y1 = ring[i]
                    x2, y2 = ring[(i + 1) % len(ring)]
                    a[p["cap"]] += math.hypot(x2 - x1, y2 - y1) * h
            continue
        for ring, cols in rings:
            for i, c in enumerate(cols):
                x1, y1 = ring[i]
                x2, y2 = ring[(i + 1) % len(ring)]
                a[c] += math.hypot(x2 - x1, y2 - y1) * h
    return a


class FloorRecorder(SuRecorder):
    """SuRecorder + 分带 + 房间用途分色 + 注释表。"""

    last = None

    def __init__(self):
        super().__init__()
        self.labels = []
        self.fails = []
        self.notes = []
        FloorRecorder.last = self

    # ---- ① 分带 ----
    def _band(self, floors, S):
        fh = S.get("floor_h", 4.2)
        n = len(floors)
        # 层号必须与数组下标一致：band 是按**下标**算的（z = i*floor_h），
        # 而楼层组/房间表是按**层号**取的，两者不等就会整层错位。不等就不干。
        bad = [(i, f["floor"]) for i, f in enumerate(floors) if f["floor"] != i]
        if bad:
            raise VerifyError("楼层号与下标不一致（band 会错位）: %s" % bad)
        for p in self.parts:
            b = band_of(p["z0"], fh)
            p["band"] = b
            p["floor"] = b if b < n else -1       # -1 = 屋顶
            # SU 侧的顶层组名直接由 spec 给（Ruby 侧不再自己算层号，免得两处式子漂移）
            p["group"] = "屋顶" if b >= n else "F%d" % b
        self.fh = fh

    # ---- ② 房间地垫识别 + 改色 ----
    def _recolor_rooms(self, floors):
        """地垫 = kind 为 wall（`build_rooms` 走的是 add_region）+ 无逐边色 + 厚度 == ROOM_PAD。

        三条一起才认，缺一条都可能吃到墙/门过梁（它们的厚度是 win_sill/win_h/
        wall_h-win_top/door_h 那些量级，与 0.05 不沾边）。认完还要对到具体房间上。
        """
        pad_th = G.ROOM_PAD                                  # 不写死 0.05，跟着管道走
        idx = [i for i, p in enumerate(self.parts)
               if p["kind"] == "wall" and not p["edgeCols"]
               and abs((p["z1"] - p["z0"]) - pad_th) < 1e-9]
        exp = sum(len(f["rooms"]) for f in floors)
        if len(idx) != exp:
            raise VerifyError("地垫识别失败：命中 %d 块，楼层数据里共 %d 间房" % (len(idx), exp))

        by_band = defaultdict(list)
        for i in idx:
            by_band[self.parts[i]["band"]].append(i)

        exact = 0
        for b, floor in enumerate(floors):
            rooms = floor["rooms"]
            if len(by_band[b]) != len(rooms):
                raise VerifyError("第 %d 层地垫 %d 块 != 房间 %d 间"
                                  % (b, len(by_band[b]), len(rooms)))
            polys = [Polygon(r["poly"]) for r in rooms]
            hit = Counter()
            for i in by_band[b]:
                p = self.parts[i]
                pg = Polygon(p["ext"], p["holes"])
                # 判据①：点集完全相同（_clean 只去共线点、不改点集，故差集应为 0）
                same = [k for k, rp in enumerate(polys)
                        if pg.symmetric_difference(rp).area < 1e-9]
                if len(same) == 1:
                    k = same[0]
                    exact += 1
                else:
                    # 判据②：代表点（保证在图形内）落在房内 + 面积相对差 < 1e-6
                    pt = pg.representative_point()
                    cand = [k for k, rp in enumerate(polys)
                            if rp.contains(pt)
                            and abs(pg.area - rp.area) <= 1e-6 * max(1.0, rp.area)]
                    if len(cand) != 1:
                        raise VerifyError("第 %d 层地垫 #%d（面积 %.4f m²）匹配到 %d 个房间，"
                                          "无法唯一归属" % (b, i, pg.area, len(cand)))
                    k = cand[0]
                hit[k] += 1
                r = rooms[k]
                pu = r.get("purpose") or "未标注"
                col = PURPOSE_COLOR.get(pu)
                if col is None:
                    raise VerifyError("第 %d 层房间 %s 的用途「%s」不在配色表里"
                                      % (b, r.get("number"), pu))
                p["cap"] = col
                p["purpose"] = pu
                p["roomNo"] = r.get("number")
                pt = pg.representative_point()
                self.labels.append({"floor": b, "number": r.get("number"), "purpose": pu,
                                    "dept": None, "color": col,
                                    "cent": [round(pt.x, 3), round(pt.y, 3)],
                                    "area": round(pg.area, 3)})
            missing = [k for k in range(len(rooms)) if hit[k] == 0]
            twice = [k for k, c in hit.items() if c > 1]
            if missing or twice:
                raise VerifyError("第 %d 层房间-地垫不是一一对应：未匹配 %s 重复 %s"
                                  % (b, [rooms[k].get("number") for k in missing],
                                     [rooms[k].get("number") for k in twice]))
        self.exact_pads = exact
        self.pad_area = sum(l["area"] for l in self.labels)

    # ---- ②b 构件类别（SU 侧每类一个 Tag）----
    def _categorize(self, S):
        """给每个部件定 `cat` —— SU 侧据此分 Tag，实现「墙/窗一键隐藏」。

        判据只用**管道自己发出来的颜色**：`style`（facade/inner/roof/parapet/glass/door，
        每栋楼 profile 不同）∪ glb_common 的 C_SLAB/C_FRAME/C_STAIR/C_COLUMN/C_WALL/C_GLASS。
        不写死某个楼的色值 —— 换楼换 profile，这张表跟着走。
        厚度 == ROOM_PAD 的**先按地垫认**（它的 cap 是用途色，不在建筑色表里）；
        认不出的颜色**中止**，不静默落进「其他」（静默落进去 = 用户点了「隐藏窗户」窗户还在）。
        """
        st = S.get("style") or {}
        # 颜色 → 类别。这张表必须**单值**：一个颜色只能属于一个类别。理由在 SU 侧那条链上
        # （`build_floors.rb` 的材质回填）：SU 在合并/切分共面面时会**新造面**，新面默认落在
        # Layer0、丢掉了身份，唯一还能读出身份的就是**材质**。颜色若一码两用，回填就是猜。
        # 原来是 setdefault（先到先得）—— 那正是静默猜，改成如实报冲突。
        pairs = [(hexc(C_SLAB), "楼板", "楼板"), (hexc(C_FRAME), "窗", "窗框"),
                 (hexc(C_GLASS), "窗", "玻璃"), (hexc(C_STAIR), "楼梯", "楼梯"),
                 (hexc(C_COLUMN), "柱", "柱"), (hexc(C_WALL), "墙", "墙"),
                 (hexc(C_DOOR), "门", "门"), (C_SITE.lower(), SITE_CAT, SITE_SUB)]
        for key, cat, sub in (("facade", "墙", "外墙"), ("inner", "墙", "内墙"),
                              ("wall", "墙", "墙"), ("roof", "屋顶", "屋面"),
                              ("parapet", "屋顶", "女儿墙"), ("glass", "窗", "玻璃"),
                              ("door", "门", "门")):
            c = st.get(key)
            if c:
                pairs.append((c.lower(), cat, sub))
        table = {}
        subs = {}
        clash = Counter()
        sub_clash = Counter()
        for c, cat, sub in pairs:
            if table.get(c, cat) != cat:
                clash[(c, table[c], cat)] += 1
            if subs.get(c, sub) != sub:
                sub_clash[(c, subs[c], sub)] += 1
            table[c] = cat
            subs[c] = sub
        if clash:
            raise VerifyError("构件类别表里有**一个颜色两个类别**：%s —— 颜色一码两用，"
                              "SU 侧就没法按材质把新造的面归回去（宁可中止也不猜）"
                              % dict(clash))
        if sub_clash:
            raise VerifyError("同一个颜色被派了两个二级组名：%s（二级组名撞车会让"
                              "两色重新落回一个容器，SU 会把它们的共面面合并掉）"
                              % dict(sub_clash))
        # 用途色是地垫专用：撞上建筑色同样会一码两用
        pad_clash = {pu: c for pu, c in PURPOSE_COLOR.items() if c.lower() in table}
        if pad_clash:
            raise VerifyError("用途色与建筑色撞了：%s（用途地垫要能单凭材质认出来）"
                              % pad_clash)
        if len(set(PURPOSE_COLOR.values())) != len(PURPOSE_COLOR):
            raise VerifyError("用途配色表里有重复颜色 —— 两个用途同色就认不出用途了")
        self.cat_table = table
        self.sub_table = subs

        pad_th = G.ROOM_PAD
        unknown = Counter()
        for p in self.parts:
            if p["kind"] == "wall" and not p["edgeCols"] \
                    and abs((p["z1"] - p["z0"]) - pad_th) < 1e-9:
                p["cat"] = "地垫"
                continue
            cat = table.get((p["cap"] or "").lower())
            p["cat"] = cat or "其他"
            if cat is None:
                unknown[p["cap"]] += 1
        self.cat_counts = Counter(p["cat"] for p in self.parts)
        self.cat_by_band = defaultdict(Counter)
        for p in self.parts:
            self.cat_by_band[p["band"]][p["cat"]] += 1
        # 类别表没认出来的：颜色不在表里 ⇒ 中止（要么补表，要么是管道换了配色）
        if unknown:
            raise VerifyError("有 %d 个部件的颜色不在构件类别表里（%s）—— "
                              "类别表跟着 style 走，不要猜" % (sum(unknown.values()), dict(unknown)))

    # ---- ②c 二级组名（SU 侧的容器键）----
    def _sub_names(self):
        """每个部件的二级组名 `sub` —— SU 侧按它建**二级组**（一个名字一个容器）。

        为什么必须比「类别」更细：SU 只在**同一个容器内**才合并共面/贴面的面，而合并会把
        被盖住的那块**整个删掉**（实测：屋面板下盖面 921.3 m² 被女儿墙下盖面顶掉）。
        同一个类别里有两种东西时（屋面 slab / 女儿墙、玻璃 / 窗框、外墙 / 内墙），
        只按类别分组 = 它俩还在一个容器里 = 白分。名字取语义名（来自 `_categorize` 的表），
        用途地垫取 `地垫-<用途>`。

        同类别内两色撞成同一个名字（例如 style.glass 与 C_GLASS 不同色但都叫「玻璃」）会让
        两色重新落回一个容器 —— 不静默：这对名字都改带色号（`窗-789cb8`），并写进 notes。
        """
        used = defaultdict(set)
        for p in self.parts:
            if p.get("purpose"):
                p["sub"] = "地垫-" + p["purpose"]
            else:
                p["sub"] = self.sub_table.get((p["cap"] or "").lower()) or p["cat"]
            if not p["sub"].startswith("地垫-"):
                used[(p["cat"], p["sub"])].add((p["cap"] or "").lower())
        rename = {k: sorted(v) for k, v in used.items() if len(v) > 1}
        if rename:
            self.notes.append("⚠ 二级组名撞车（同类别同名字不同颜色）→ 改带色号：%s" % rename)
        for p in self.parts:
            if (p["cat"], p["sub"]) in rename:
                p["sub"] = "%s-%s" % (p["cat"], (p["cap"] or "").lstrip("#").lower())
        self.sub_counts = Counter(p["sub"] for p in self.parts)

    # ---- ②d 场地/散水（SU-only 的那一圈）----
    def _add_site(self):
        """首层轮廓外扩 `SITE_WIDTH` 一圈的**环形板**，自成一个顶层组。

        为什么是环不是整块：整块的顶面会和首层楼板底面**整面共面**（虽然不同容器不会合并，
        但渲染会闪），而且会把首层楼板底面盖住 —— 用户要看的正是「地面」那一块。
        环的内边界贴着楼板外皮，外边界在场地里，两者既不共面也不重叠。
        """
        f0 = [p for p in self.parts
              if p.get("group") == "F0" and p["kind"] == "slab" and p["cap"] == hexc(C_SLAB)]
        if len(f0) != 1:
            raise VerifyError("首层楼板不唯一（%d 块），场地环没法定位 —— 不猜" % len(f0))
        foot = Polygon(f0[0]["ext"], f0[0]["holes"] or [])
        try:
            ring = foot.buffer(SITE_WIDTH, join_style=2).difference(foot)
        except Exception as e:                                   # noqa: BLE001
            raise VerifyError("首层轮廓外扩 %.2f m 失败：%s" % (SITE_WIDTH, e))
        if ring.geom_type != "Polygon" or ring.is_empty:
            raise VerifyError("场地环不是单个多边形（%s）—— 首层轮廓被外扩拆碎了，不猜"
                              % ring.geom_type)
        # 环形面积的量级判据只能按**周长**算：环面积 = 周长×宽度（尖角外扩只多不少），
        # 拿它跟足迹面积比是错的（1863 m² 的楼足迹能外扩出 430 m² 的环，这很正常）。
        lw = foot.length * SITE_WIDTH
        if not (0.9 * lw <= ring.area <= 3.0 * lw):
            raise VerifyError("场地环面积 %.2f m² 与「周长×宽」%.2f m² 不成比例"
                              "（周长 %.1f m）—— 外扩没做对，不猜"
                              % (ring.area, lw, foot.length))
        rd = lambda r: [[round(x, 6), round(y, 6)] for x, y in r.coords[:-1]]   # noqa: E731
        ext = rd(ring.exterior)
        holes = [rd(r) for r in ring.interiors]
        self.parts.append({
            "ext": ext, "holes": holes, "z0": -SITE_THICK, "z1": 0.0,
            "cap": C_SITE, "edgeCols": [], "holeEdgeCols": [], "edgeN": [], "holeEdgeN": [],
            "kind": "site", "cat": SITE_CAT, "sub": SITE_SUB,
            "band": -1, "floor": -1, "group": SITE_CAT,
            "vol": round(ring.area * SITE_THICK, 6),
            "nf": 2 + len(ext) + sum(len(h) for h in holes),
        })
        self.cat_counts[SITE_CAT] += 1
        self.sub_counts[SITE_SUB] += 1
        self.site = {"area": round(ring.area, 3), "width": SITE_WIDTH,
                     "thick": SITE_THICK, "pts": len(ext)}


    # ---- 单位（rooms.json 是唯一带 dept 的地方，floors 里的房间是精简快照）----
    def _fill_dept(self, floors):
        path = os.path.join(G.DATA, "rooms.json")
        if not os.path.exists(path):
            self.notes.append("rooms.json 不存在 → 单位留空")
            return
        rows = json.load(open(path, encoding="utf-8"))
        idx = {}
        dup = 0
        for r in rows:
            k = (int(r["floor"]), r.get("number"))
            if k in idx:
                dup += 1
            idx[k] = r
        got = miss = 0
        for lab in self.labels:
            r = idx.get((lab["floor"], lab["number"]))
            if r is None:
                miss += 1
                continue
            lab["dept"] = r.get("dept")
            got += 1
        self.notes.append("单位回填 %d/%d（按 层号+房间号 取，rooms.json %d 行%s）"
                          % (got, len(self.labels), len(rows),
                             "，重复键 %d" % dup if dup else ""))
        if miss:
            self.notes.append("⚠ %d 个房间在 rooms.json 里找不到（单位留空）" % miss)

    # ---- ③ 逐带锚点校验 ----
    def _verify(self, floors, S):
        """逐带反证分带正确：每带的构件数必须等于**该层图上**的构件数。

        「楼板」只数楼板色（C_SLAB）的那种 —— 顶层带里还会合法地出现**翼楼屋面**
        （`wingRoof`，z0 = 顶层楼板标高，按 z0 分带理所当然落在顶层带），
        所以不能按 kind 数「所有 slab」，否则顶层永远多报 2 块。
        """
        n = len(floors)
        ROOF = n                                   # 屋顶带的键 = 层数（不是 -1）
        glass_hex, frame_hex, slab_hex = hexc(C_GLASS), hexc(C_FRAME), hexc(C_SLAB)

        def per_band(pred):
            c = Counter()
            for p in self.parts:
                if pred(p):
                    c[p["band"]] += 1
            return c

        slab_is_floor = per_band(lambda p: p["kind"] == "slab" and p["cap"] == slab_hex)
        slab_all = per_band(lambda p: p["kind"] == "slab")
        col = per_band(lambda p: p["cap"] == hexc(C_COLUMN))
        gs = per_band(lambda p: p["cap"] == glass_hex)
        fr = per_band(lambda p: p["cap"] == frame_hex)
        pad = per_band(lambda p: "purpose" in p)
        self.band_counts = Counter(p["band"] for p in self.parts)
        self.roof_key = ROOF
        self.anchors = {}
        for b, floor in enumerate(floors):
            want = {"楼板": 1, "柱": len(floor["columns"]),
                    "玻璃": len(floor["windows"]), "窗框": 4 * len(floor["windows"]),
                    "地垫": len(floor["rooms"])}
            got = {"楼板": slab_is_floor[b], "柱": col[b], "玻璃": gs[b],
                   "窗框": fr[b], "地垫": pad[b]}
            self.anchors["F%d" % b] = {"want": want, "got": got}
            for k in want:
                if want[k] != got[k]:
                    self.fails.append("F%d %s: 实得 %d != 应得 %d" % (b, k, got[k], want[k]))
        # 屋顶带：屋面板恰好 1 块；该带其余部件是女儿墙
        self.anchors["屋顶"] = {"want": {"屋面板": 1}, "got": {"屋面板": slab_all[ROOF]}}
        if slab_all[ROOF] != 1:
            self.fails.append("屋顶 屋面板: 实得 %d != 应得 1" % slab_all[ROOF])
        if self.band_counts[ROOF] == 0:
            self.notes.append("⚠ 屋顶带（band>=%d）没有部件 —— 检查是否漏了屋面板/女儿墙" % n)
        wing = slab_all[ROOF - 1] - slab_is_floor[ROOF - 1]
        if wing:
            self.notes.append("顶层带含 %d 块翼楼屋面（wingRoof，z0=顶层楼板标高，按 z0 分带归顶层）" % wing)

    # ---- 输出端 ----
    def export_glb(self, path):
        floors = G.load_floors()
        S = G.load_spec() or {}
        self._band(floors, S)
        self._recolor_rooms(floors)
        self._categorize(S)
        self._sub_names()
        self._add_site()
        self._fill_dept(floors)
        self._verify(floors, S)
        if self.fails:
            self._report(floors)
            raise VerifyError("逐带锚点校验不通过（%d 条），未写盘" % len(self.fails))
        shim = super().export_glb(path)         # 父类：原子写 + 返回 _Shim
        self._augment(path, floors, S)
        self._report(floors)
        return shim

    def _augment(self, path, floors, S):
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        groups = {}
        for b in range(len(floors)):
            groups["F%d" % b] = self.band_counts[b]
        groups["屋顶"] = self.band_counts[self.roof_key]
        if getattr(self, "site", None):
            groups[SITE_CAT] = 1
        spec["meta"].update({
            "groups": groups,
            "groupOrder": ["F%d" % b for b in range(len(floors))] + ["屋顶"]
                          + ([SITE_CAT] if getattr(self, "site", None) else []),
            # 二级组名（SU 侧一个名字一个容器）与场地参数
            "subCounts": {k: v for k, v in self.sub_counts.items()},
            "siteColor": C_SITE, "siteCat": SITE_CAT, "siteRing": getattr(self, "site", None),
            "rooms_label": self.labels,
            "catOrder": CAT_ORDER,
            "catCounts": {c: self.cat_counts[c] for c in CAT_ORDER if self.cat_counts[c]},
            # 颜色 → 类别：SU 侧 explode 时会新造面（新面落在 Layer0、身份丢失），
            # 唯一还能读出身份的只有**材质名**，靠这张表把新面归回类别 Tag。
            "catColors": dict(self.cat_table),
            "padCat": "地垫", "padMatPrefix": "yz用途-",
            "purposeColors": PURPOSE_COLOR,
            "purposeFamily": PURPOSE_FAMILY,
            "windowsIncluded": bool(G.INCLUDE_SYNTHETIC_WINDOWS),
            "floorH": S.get("floor_h", 4.2),
            "padThickness": G.ROOM_PAD,
            "bandRule": "floor(z0/floor_h + 1e-6); >=%d → 屋顶" % len(floors),
        })
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        os.replace(tmp, path)

    # ---- 验收数字（人看的那一份）----
    def _report(self, floors):
        parts = self.parts
        nf = sum(p["nf"] for p in parts)
        print("【总】部件 %d  预期体积 %.3f m³  预期面数 %d  漏记三角面 %d"
              % (len(parts), sum(p["vol"] for p in parts), nf, self.dropped))
        print("      分带: " + "  ".join(
            "%s=%d" % ("屋顶" if b == self.roof_key else "F%d" % b, c)
            for b, c in sorted(self.band_counts.items()) if b >= 0))
        if getattr(self, "site", None):
            s = self.site
            print("      场地: 首层轮廓外扩 %.2f m 的环形板 %.1f m²（厚 %.2f，顶面齐 z=0），"
                  "自成一个顶层组" % (s["width"], s["area"], s["thick"]))
        sub_band = defaultdict(Counter)
        for p in self.parts:
            if p["band"] >= 0:
                sub_band[p["band"]][p["sub"]] += 1
        print("      二级组（SU 侧容器）: " + "  ".join(
            "%s[%s]" % ("屋顶" if b == self.roof_key else "F%d" % b,
                        " ".join("%s%d" % (s, n) for s, n in sorted(sub_band[b].items())))
            for b in sorted(sub_band)))
        print()
        print("【地垫】命中 %d 块（点集精确命中 %d，判据②兜住 %d）  地垫总面积 %.2f m²"
              % (len(self.labels), self.exact_pads, len(self.labels) - self.exact_pads,
                 self.pad_area))
        for n in self.notes:
            print("      ·", n)
        print()
        print("【构件类别（SU 侧一类一个 Tag）】" + "  ".join(
            "%s=%d" % (c, self.cat_counts[c]) for c in CAT_ORDER if self.cat_counts[c]))
        print("  " + "  ".join("%s:%s" % ("屋顶" if b == self.roof_key else "F%d" % b,
                                          "/".join("%s%d" % (c, n) for c, n in
                                                   sorted(self.cat_by_band[b].items(),
                                                          key=lambda kv: CAT_ORDER.index(kv[0]))))
                               for b in sorted(self.cat_by_band) if b >= 0))
        print()
        print("【逐带锚点】")
        for k, v in self.anchors.items():
            got, want = v["got"], v["want"]
            flag = "OK " if all(got[n] == want[n] for n in want) else "✗  "
            print("  %s%-4s " % (flag, k) + "  ".join(
                "%s %d/%d" % (n, got[n], want[n]) for n in want))
        if self.fails:
            print()
            print("【不通过】")
            for f in self.fails:
                print("  ✗", f)
        print()
        print("【逐用途】")
        cnt, area = Counter(), defaultdict(float)
        for lab in self.labels:
            cnt[lab["purpose"]] += 1
            area[lab["purpose"]] += lab["area"]
        for pu in sorted(cnt, key=lambda x: (-cnt[x], x)):
            print("  %-14s %-4s %3d 间  %9.1f m²  %s"
                  % (pu, PURPOSE_FAMILY.get(pu, "?"), cnt[pu], area[pu], PURPOSE_COLOR[pu]))
        print("  合计 %d 间  %.1f m²" % (sum(cnt.values()), sum(area.values())))
        print()
        print("【逐色面积（解析，口径同 _a0_glb_color_check）】")
        ca = color_areas(parts)
        for k, v in sorted(ca.items(), key=lambda x: -x[1]):
            tag = ""
            if k in PURPOSE_COLOR.values():
                tag = "  ← 用途色" + ("（本行面积 = 地垫 %d 块）" % len(self.labels))
            print("  %-9s %10.1f m²%s" % (k, v, tag))
        print("  %-9s %10.1f m²" % ("TOTAL", sum(ca.values())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # 交付档位：`data/lihua-building.glb` 里实测有玻璃 #789cb8 1705.7 m²、窗框 #c2c7ce
    # 1350.7 m²、柱 #9aa2b0 68.0 m²（= F0 的 8 根，4×0.5×4.0 + 0.25×2 = 8.5 m²/根）——
    # 三色都对得上当前 floors/*.json ⇒ 交付件是**带合成窗**建的。合成窗占 windows 的
    # 100%（313/313），所以这个开关取错 = SU 里一扇窗都没有。
    G.DATA = os.path.join(ROOT, "data")          # 注册表楼：数据就在 data/ 根下（非 data/buildings/）
    G.OUT = a.out
    G.INCLUDE_SYNTHETIC_WINDOWS = True           # 实测交付档位，见上
    G.SKIP_FLOORS = set()
    G.MeshBuilder = FloorRecorder
    try:
        G.main()
    except VerifyError as e:
        print("\n✗ 验收不通过：%s" % e, file=sys.stderr)
        return 1
    finally:
        G.MeshBuilder = MeshBuilder
    b = FloorRecorder.last
    print("\n→ %s（%d 部件）" % (a.out, len(b.parts) if b else -1))
    return 1 if (b and b.fails) else 0


if __name__ == "__main__":
    sys.exit(main())
