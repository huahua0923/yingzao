# -*- coding: utf-8 -*-
r"""按楼生成 SU 分层建模规格 —— 理化楼那条链（`su_spec_floors.py`）的**按楼泛化**。

为什么单开一个文件而不是改 `su_spec_floors.py`：
  · 冻结约定（调试好的代码不再动）+ 理化楼那份 spec 是**可逐字节复现的验收基准**
    （sha256 `c67ba3e8a19a…`）。把泛化写成新文件，原文件的 `main()` 一个字节不动，
    "理化楼没变"这件事才有意义。本文件**不修改** su_spec_floors.py 的任何内容，
    只在运行时替换它的两个模块级色表 + 复用它的 `FloorRecorder`。

跟 `su_spec_floors.main()` 的三处差别（其余逐行同构）：
  ① `G.DATA` 按楼名解析：理化楼是注册表楼（数据在 `data/` 根下），其余在 `data/buildings/<name>/`；
  ② 用途色表**只注入该栋实际用到的用途**，取值来自 `purpose_palette.json`
     （该表由 `_scratch/_purpose_palette_dump.py` 从网页查看器取数 —— 归族与配色的规则
     只有 `frontend/building.html` 那一处实现，见该文件 1854 行注释）；
     ⚠ 注入顺序**先按原 13 键的既有顺序**、再补其余（字典序）—— 因为
     `meta.purposeColors` 是按 dict 顺序写进 JSON 的，键序一变字节就变，复现门会假红。
  ③ 加 `name` 入参（照抄父类 `su_spec.py:234` 的写法）。

用法:
  python backend/modeling/su_spec_floors_fleet.py lihua
  python backend/modeling/su_spec_floors_fleet.py ny27 -o D:/gym3d/_scratch/su_jobs/_ny27_floors_spec.json
"""
import argparse
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
for p in (BACKEND, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import build_standard_glb as G      # noqa: E402
import su_spec_floors as SF         # noqa: E402
from glb_common import MeshBuilder  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.errors import GEOSException  # noqa: E402


def _geos_meas(a, b, op, label):
    """跑一次 GEOS 量算（`a.<op>(b)`），**把 TopologyException 翻译成人话**。

    为什么不能"多边形非法就拦"：全库 `floors/*.json` 的房间多边形里，
    自交的共 **558 个、分布在 22 栋**（c006 51、c017 250、c059 72、c034 48、c104 20、
    c009 17、c080 17、ny27 12、c103 11…），而这 22 栋**现在全部通过**管道 ——
    GEOS 只在**恰好撞上**某个运算时才抛（c103 第 2 层撞上了，ny27 的 12 个没撞上）。
    所以只能"抛出的那一刻说清楚是哪间房"，不能一刀切成"非法即拦"（那是 22 栋大回归）。

    `label` 是被算的那间房的房号 —— 报错要指名道姓，否则又是一条把人带偏的信息
    （早先把"0 个 / ≥2 个"混成一句"不是任何房间的地垫"，实测把自己带偏过一次）。
    """
    try:
        return getattr(a, op)(b)
    except GEOSException as e:                                   # noqa: BLE001
        raise SF.VerifyError(
            "GEOS 判不动「%s」：%s —— 该房多边形自交（全库 558 个，多数能过），"
            "这一块恰好撞上，先修数据不猜" % (label, str(e)[:90]))

PALETTE = os.path.join(HERE, "purpose_palette.json")

# 注入顺序的基准：原色表的既有键序（**不能改**，见模块头 ②）
_ORIG_ORDER = list(SF.PURPOSE_COLOR.keys())

# 房间缺用途时 `_recolor_rooms` 会把它写成字符串「未标注」（不是空串）
NO_PURPOSE = "未标注"


def building_dir(name):
    """理化楼是注册表楼（数据在 data/ 根下，无 profile.json），其余在 data/buildings/<name>/。"""
    if name in ("lihua", "理化楼"):
        return os.path.join(ROOT, "data")
    return os.path.join(ROOT, "data", "buildings", name)


def used_purposes(floors_dir):
    """该栋 floors 里**实际出现**的用途串（含「未标注」这条归一化后的键）。"""
    P = set()
    for f in sorted(os.listdir(floors_dir)):
        if not (f.startswith("floor") and f.endswith(".json")):
            continue
        with io.open(os.path.join(floors_dir, f), encoding="utf-8") as fh:
            d = json.load(fh)
        for r in (d.get("rooms") or []):
            P.add((r.get("purpose") or NO_PURPOSE) or NO_PURPOSE)
    return P


def palette_for(used, pal):
    """按「原 13 键顺序 → 其余字典序」拼出该栋用的两张表。缺失即中止（不猜）。"""
    colors, families = pal["colors"], pal["families"]
    # ★ 键名归一：取表脚本是从 floors 的 `purpose` 原值收集的，空用途在那里是**空串**；
    #   而 `su_spec_floors._recolor_rooms` 把空用途归一成**字符串「未标注」**才去查表。
    #   不映射的话，任何有"没填用途的房间"的楼都会在这里被自己的守卫挡下。
    key = lambda p: ("" if p == NO_PURPOSE else p)          # noqa: E731
    missing = sorted(p for p in used if key(p) not in colors)
    if missing:
        raise SystemExit(
            "✗ 用途表缺这些串：%s\n"
            "  取表脚本是 _scratch/_purpose_palette_dump.py；新数据带来新词时应重跑它，"
            "并让 _purpose_color_guard.py 的 G3 白名单做一次显式决策。" % missing)
    order = [p for p in _ORIG_ORDER if p in used] + sorted(used - set(_ORIG_ORDER))
    return ({p: colors[key(p)] for p in order}, {p: families[key(p)] for p in order})


class FleetFloorRecorder(SF.FloorRecorder):
    r"""`su_spec_floors.FloorRecorder` 的全库版：**只覆写四条判据里被实测证伪的那些**。

    覆写清单（每条都有实测出处，不是为了「宽容」而宽容）：
      · `_add_site`      —— 首层楼板 2 块（c073；标准管道 `su_spec.py` 出一模一样的 2 块，
                            即交付几何本来的样子）
      · `_recolor_rooms` —— 一块地垫被三角化拆成多块（c041/c006/c009，逐块查证每块都 100%
                            落在某间房内、同房间各块面积精确加和 == 房间面积）
      · `_verify`        —— 只摘掉上面两条对应的失配，其余一条不放
    父类其余判据一字不动（`_band` / `_categorize` / 逐带锚点校验的其它项）。
    """

    # ---- ②d 场地/散水（首层楼板可能不止一块）----
    def _add_site(self):
        r"""`su_spec_floors._add_site` 的宽容版：原版要求「首层楼板恰好 1 块」才敢定位场地环。

        实测 c073 的首层楼板是 **2 块**（标准管道 `su_spec.py` 出的一样，即交付几何本来的样子
        —— 同上一条「一层平面分成两个分离区域」）。这里改成：取该带全部同标高楼板色部件的
        **并集**当足迹。并集仍然是一块（两块本就不相交，且都在首层平面上），环形外扩的
        几何含义不变。

        其余判据一字不动：仍要求楼板都在**同一标高**、外扩环必须是**单个** Polygon、
        环面积仍按「周长×宽」量级卡。
        """
        f0 = [p for p in self.parts
              if p.get("group") == "F0" and p["kind"] == "slab"
              and p["cap"] == SF.hexc(SF.C_SLAB)]
        if not f0:
            raise SF.VerifyError("首层一块楼板色部件都没有，场地环没法定位 —— 不猜")
        if not self._same_level(f0):
            raise SF.VerifyError("首层楼板有 %d 块但不在同一标高（z=%s）—— 是数错了层，不是分离平面"
                                 % (len(f0), sorted({(round(p["z0"], 3), round(p["z1"], 3))
                                                     for p in f0})))
        polys = [Polygon(p["ext"], p["holes"] or []) for p in f0]
        foot = polys[0] if len(polys) == 1 else unary_union(polys)
        try:
            ring = foot.buffer(SF.SITE_WIDTH, join_style=2).difference(foot)
        except Exception as e:                                   # noqa: BLE001
            raise SF.VerifyError("首层轮廓外扩 %.2f m 失败：%s" % (SF.SITE_WIDTH, e))
        if ring.geom_type != "Polygon" or ring.is_empty:
            raise SF.VerifyError("场地环不是单个多边形（%s）—— 首层轮廓被外扩拆碎了，不猜"
                                 % ring.geom_type)
        # ★ 旧判据「环面积 vs 周长×宽」只在**凸形**上成立，梳子形必然假阳性：
        #   ny28 实测 0.655、ny29 实测 0.650（都跌破 0.9 的闸门），而它们的环完全正确 ——
        #   梳齿窄缝不足 2×SITE_WIDTH 时，向外扩会被相邻的齿吃掉，真环面积天然远小于该估计
        #   （ny28 足迹 181.3 m² 却有 589.8 m 周长，本身就是"薄梳子"）。
        #   换成**形状无关**的判据：「凡离轮廓 0.9×W 以内的外扩面，必须已被环盖住」。
        #   自证：五栋（含两种形状）实测 leak 恒为 0.000000 m²；把宽度改成 W/3、或把差集写反，
        #   leak 立刻变正 —— 判据能红，不是空断言。
        #   它管不到的：外扩**过大**（写成 2W）—— 旧判据同样管不到（比值 2.0 仍在 0.9~3.0 窗口内），
        #   而宽度是具名常量、不随形状变，故不另设形状无关的上界（那会引入新的假阳性）。
        if SF.SITE_WIDTH <= 0:
            raise SF.VerifyError("SITE_WIDTH=%r 不是正数，场地环没意义" % SF.SITE_WIDTH)
        eps = 1e-6 * max(1.0, ring.area)
        leak = foot.buffer(0.9 * SF.SITE_WIDTH, join_style=1).difference(foot).difference(ring).area
        if leak > eps:
            raise SF.VerifyError("场地环没盖住离轮廓 0.9×%.2f m 以内的外扩面（漏 %.2f m²）"
                                 "—— 外扩没做对，不猜" % (SF.SITE_WIDTH, leak))
        back = ring.intersection(foot).area
        if back > eps:
            raise SF.VerifyError("场地环压回轮廓里（%.2f m²）—— 差集写反了，不猜" % back)
        rd = lambda r: [[round(x, 6), round(y, 6)] for x, y in r.coords[:-1]]   # noqa: E731
        ext = rd(ring.exterior)
        holes = [rd(r) for r in ring.interiors]
        self.parts.append({
            "ext": ext, "holes": holes, "z0": -SF.SITE_THICK, "z1": 0.0,
            "cap": SF.C_SITE, "edgeCols": [], "holeEdgeCols": [], "edgeN": [], "holeEdgeN": [],
            "kind": "site", "cat": SF.SITE_CAT, "sub": SF.SITE_SUB,
            "band": -1, "floor": -1, "group": SF.SITE_CAT,
            "vol": round(ring.area * SF.SITE_THICK, 6),
            "nf": 2 + len(ext) + sum(len(h) for h in holes),
        })
        self.cat_counts[SF.SITE_CAT] += 1
        self.sub_counts[SF.SITE_SUB] += 1
        self.site = {"area": round(ring.area, 3), "width": SF.SITE_WIDTH,
                     "thick": SF.SITE_THICK, "pts": len(ext)}
        # ★ 自证字段**只在首层楼板不止一块时**才加：`self.site` 是要写进 spec 的，
        #   无条件加就等于给**每一栋**的 spec 多一个键 —— 理化楼/ny27 这些单块楼
        #   的复现门（sha256 逐字节）立刻变红，而它们本来一个字都不该动。
        #   单块时本方法必须与父类**逐字节等价**，这一条是比"跑得通"更硬的约束。
        if len(f0) > 1:
            self.site["f0_slabs"] = len(f0)

    r"""`su_spec_floors.FloorRecorder` 的地垫判据**宽容版**（只覆写 `_recolor_rooms`）。

    为什么原版会假红：原版要求「地垫块数 == 房间数」，且逐块与房间**一一对应**。
    但房间边界多边形若有自触/自相交，三角化会把**同一间房**拆成 N 块地垫 ——
    实测 c041 的 `41-06-04`（300.14 m²）被拆成 167.39 + 132.75，两份相加**正好等于**房间面积；
    c006 全栋多 41 块、c009 多 2 块，逐块查证**每一块都 100% 落在某间房之内**，零杂物。

    ⇒ 假红的不是"混进了非地垫"，而是"一间房落了多块"。所以本版把判据换成**两条更强的**：
      ① 每一块地垫都必须**被某间房包含**（`pg - room` 面积 ~0）—— 非地垫混入照样被抓，
         而且比原版的"唯一归属"更严：原版允许块与房间只按代表点+面积匹配，
         本版要求块整体在房内；
      ② 每间房的地垫**面积合计必须等于房间面积** —— 这是"恰好覆盖一次"的等价表述，
         块数多了少了都会被抓（漏一块则合计偏小，混进一块则合计偏大）。

    房间与地垫的**多对一**因此被允许，但**多对多**、漏配、混入一律中止。
    理化楼（全库唯一 1:1 的基准）走这条路径的输出与原来**逐字节相同** ——
    单块时 `sum([a])==a`、`max` 取到唯一那块，故质心/面积/标签一条不差。

    备份自证：`self.split_rooms` 记下有几间房被拆过，`self.exact_pads` 与原来同义。
    """

    def _recolor_rooms(self, floors):
        pad_th = G.ROOM_PAD                                  # 不写死 0.05，跟着管道走
        idx = [i for i, p in enumerate(self.parts)
               if p["kind"] == "wall" and not p["edgeCols"]
               and abs((p["z1"] - p["z0"]) - pad_th) < 1e-9]
        by_band = defaultdict(list)
        for i in idx:
            by_band[self.parts[i]["band"]].append(i)

        exact = 0
        split_rooms = 0
        self.pad_rooms_band = Counter()                      # 逐带：**拿到地垫的房间数**（不是块数）
        for b, floor in enumerate(floors):
            rooms = floor["rooms"]
            polys = [Polygon(r["poly"]) for r in rooms]
            pieces = defaultdict(list)                       # 房间下标 → [(部件下标, 多边形)]
            for i in by_band.get(b, []):
                p = self.parts[i]
                pg = Polygon(p["ext"], p["holes"])
                # 判据①：点集相同（_clean 只去共线点、不改点集，故差集应为 0）。
                # ★ 容差为什么是「相对 1e-6」而不是绝对 1e-9：地垫是从房间多边形**生成**的，
                #   两者之间只该有**浮点往返噪声**（spec 里坐标按浮点写出、读回再建面），
                #   相对量级 ~1e-7。c103 实测：1537.4470 m² 的房间，地垫与它差 0.0001 m²
                #   （相对 6.5e-8），用绝对 1e-9 判就成了「差集不为 0」→ 掉进判据② →
                #   报成「没有唯一落在哪间房」——**假警报，且把人往数据问题上带偏**。
                #   1e-6 是本模块自己的既有档位（L143 场地环、L242 面积合计都用它），三处一致。
                #   重复房间仍然抓得住：两份逐点相同的房会让 `same` 有 2 个元素 → len!=1 →
                #   照旧落进判据② 报错（c041 的病症就是这么报出来的，见 _scratch/_dedup_floor_rooms.py）。
                same = [k for k, rp in enumerate(polys)
                        if _geos_meas(pg, rp, "symmetric_difference",
                                      str(rooms[k].get("number"))).area
                        <= 1e-6 * max(1.0, rp.area)]
                if len(same) == 1:
                    k = same[0]
                    exact += 1
                else:
                    # 判据②（宽容版）：整块必须**落在**某一间房之内。
                    # 用差集而不是代表点 —— 自触房间被切开后，碎块的代表点未必还在房里。
                    inside = [k for k, rp in enumerate(polys)
                              if _geos_meas(pg, rp, "difference",
                                            str(rooms[k].get("number"))).area
                              <= 1e-6 * max(1.0, pg.area)]
                    if len(inside) != 1:
                        # 0 个和 ≥2 个是**两种病**，报错必须分开说（这条信息是给人指路的，
                        # 早先混成一句「不是任何房间的地垫」把人往容差上带，实测走错过一次）：
                        #   · 0 个 = 没有任何一间房装得下它 —— 地垫与房间多边形不同源（生成/清理不一致）
                        #   · ≥2 个 = 装得下它的房不止一间 —— **房间嵌套或重复**（数据问题），
                        #     典型：一间大房把若干小房整个包住（c103 A 翼），或两份逐点相同的房（c041）
                        if not inside:
                            raise SF.VerifyError(
                                "第 %d 层地垫 #%d（面积 %.4f m²）不落在**任何**一间房里"
                                "—— 地垫与房间多边形不同源，中止" % (b, i, pg.area))
                        raise SF.VerifyError(
                            "第 %d 层地垫 #%d（面积 %.4f m²）落在 %d 间房里（该唯一）："
                            "%s —— 房间**嵌套或重复**，数据问题，不猜"
                            % (b, i, pg.area, len(inside),
                               [str(rooms[k].get("number")) for k in inside[:8]]))
                    k = inside[0]
                pieces[k].append((i, pg))

            missing = [k for k in range(len(rooms)) if not pieces.get(k)]
            if missing:
                raise SF.VerifyError("第 %d 层有 %d 间房没有地垫：%s"
                                     % (b, len(missing),
                                        [rooms[k].get("number") for k in missing][:10]))

            for k, r in enumerate(rooms):
                ps = pieces[k]
                tot = sum(pg.area for _, pg in ps)           # 单块时 == 该块面积（逐字节同原版）
                ra = polys[k].area
                if abs(tot - ra) > 1e-6 * max(1.0, ra):
                    raise SF.VerifyError(
                        "第 %d 层房间 %s 的地垫面积合计 %.4f m² != 房间面积 %.4f m²"
                        "（差 %.4f，%d 块）—— 覆盖不全或混进了别的东西"
                        % (b, r.get("number"), tot, ra, tot - ra, len(ps)))
                if len(ps) > 1:
                    split_rooms += 1
                self.pad_rooms_band[b] += 1                  # 这间房有地垫了（不管几块）
                pu = r.get("purpose") or "未标注"
                # ★ 必须走 SF. —— 色表是运行时打在 SF 模块上的（见 main），
                #   本类定义在 fleet 模块，直接写 PURPOSE_COLOR 会 NameError
                col = SF.PURPOSE_COLOR.get(pu)
                if col is None:
                    raise SF.VerifyError("第 %d 层房间 %s 的用途「%s」不在配色表里"
                                         % (b, r.get("number"), pu))
                for i, _pg in ps:                            # 同一间房的每一块都上同一个色
                    self.parts[i]["cap"] = col
                    self.parts[i]["purpose"] = pu
                    self.parts[i]["roomNo"] = r.get("number")
                # 注释只出**一条**/房间（拆成多块时取最大那块的代表点，别在房里叠两条标注）
                i0, pg0 = max(ps, key=lambda t: t[1].area)
                pt = pg0.representative_point()
                self.labels.append({"floor": b, "number": r.get("number"), "purpose": pu,
                                    "dept": None, "color": col,
                                    "cent": [round(pt.x, 3), round(pt.y, 3)],
                                    "area": round(tot, 3)})

        self.exact_pads = exact
        self.pad_area = sum(l["area"] for l in self.labels)
        self.split_rooms = split_rooms

    # ---- ③ 逐带锚点校验（只放宽「地垫」与「楼板」两项，各自窄口径）----
    def _slab_pieces(self, band, cap=None):
        """某带里 kind==slab 的部件（cap 给定时只算该颜色）。"""
        out = []
        for p in self.parts:
            if p["band"] != band or p["kind"] != "slab":
                continue
            if cap is not None and (p["cap"] or "").lower() != cap:
                continue
            out.append(p)
        return out

    @staticmethod
    def _same_level(ps):
        """这些楼板是否**同一标高**（z0/z1 全等）—— 同标高才可能是"一层的平面分成几块"，
        不同标高就是在数别层的东西，属真错位，绝不放行。"""
        return len({(round(p["z0"], 6), round(p["z1"], 6)) for p in ps}) == 1

    def _verify(self, floors, S):
        r"""`su_spec_floors._verify` 的两条锚点都假定「一层的平面是**一块**」，
        对这两类楼是假阳性（都实测坐实过）：

        · 「地垫 == 房间数」—— 同一间房的多边形自触被三角化拆成多块地垫
          （c041 的 `41-06-04` 300.14 m² → 167.39 + 132.75；c006 多 41 块、c009 多 2 块，
          逐块查证**每块都 100% 落在某间房内**）。
        · 「楼板 == 1 块 / 屋面板 == 1 块」—— 裙楼之上分成**两个分离区域**的楼
          （c079 在 z=12.6/16.8/21.0 各 2 块，**标准管道** `su_spec.py` 出的交付规格
          一模一样，即交付几何本来的样子，不是 SU 层引入的）。

        放宽刻意做窄 —— 先跑父类原封不动的校验，再**只**从 `self.fails` 里摘掉：

          地垫：① 实得 > 应得（偏少 = 有房没垫上，绝不放行）
                ② 该带「拿到地垫的**房间**数」== 应得（每间房都有垫，只是有的房有几块）

          楼板：① 实得 > 应得且应得 == 1
                ② 该带楼板色部件**数与实得一致**（不是数漏了别的）
                ③ 这些楼板**同一标高**（见 `_same_level`）

        摘掉的逐条记进 `self.pads_split_dropped` / `self.slabs_multi_dropped`，
        `.out` 与 stdout 都如实印出来 —— 「放宽了几条、为什么」不许静默。
        """
        super()._verify(floors, S)
        if not self.fails:
            return
        slab_hex = SF.hexc(SF.C_SLAB)
        keep, pad_drop, slab_drop = [], [], []
        for f in self.fails:
            m = re.match(r"\AF(\d+) 地垫: 实得 (\d+) != 应得 (\d+)\Z", f)
            if m:
                b, got, want = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if got > want and self.pad_rooms_band.get(b, 0) == want:
                    pad_drop.append((f, "该带 %d 间房都拿到地垫，多出的 %d 块是同房被三角化拆开"
                                     % (want, got - want)))
                    continue
            m = re.match(r"\AF(\d+) 楼板: 实得 (\d+) != 应得 1\Z", f)
            if m:
                b, got = int(m.group(1)), int(m.group(2))
                ps = self._slab_pieces(b, slab_hex)
                if got > 1 and len(ps) == got and self._same_level(ps):
                    slab_drop.append((f, "该带 %d 块楼板同标高 z=[%.3f,%.3f]（本层平面是"
                                      "两个分离区域，交付几何即如此）"
                                      % (got, ps[0]["z0"], ps[0]["z1"])))
                    continue
            m = re.match(r"\A屋顶 屋面板: 实得 (\d+) != 应得 1\Z", f)
            if m:
                got = int(m.group(1))
                ps = self._slab_pieces(self.roof_key)
                if got > 1 and len(ps) == got and self._same_level(ps):
                    slab_drop.append((f, "屋顶 %d 块屋面板同标高 z=[%.3f,%.3f]（两个分离区域"
                                      "各自有屋面）" % (got, ps[0]["z0"], ps[0]["z1"])))
                    continue
            keep.append(f)
        self.fails = keep
        self.pads_split_dropped = pad_drop
        self.slabs_multi_dropped = slab_drop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", default="lihua")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    name = a.name
    base = building_dir(name)
    fdir = os.path.join(base, "floors")
    if not os.path.isdir(fdir):
        raise SystemExit("✗ 没有楼层目录：%s" % fdir)
    out = a.out or os.path.join(ROOT, "_scratch", "su_jobs", "_%s_floors_spec.json" % name)

    with io.open(PALETTE, encoding="utf-8") as f:
        pal = json.load(f)
    used = used_purposes(fdir)
    col, fam = palette_for(used, pal)

    SF.PURPOSE_COLOR = col        # ← 运行时替换模块级色表（FloorRecorder 在调用时读全局）
    SF.PURPOSE_FAMILY = fam
    G.DATA = base
    G.OUT = out
    G.INCLUDE_SYNTHETIC_WINDOWS = True    # 全库 49 栋 profile 都是 glb_windows=true（理化楼无 profile）
    G.SKIP_FLOORS = set()
    G.MeshBuilder = FleetFloorRecorder
    print("[%s] data=%s" % (name, base))
    print("[%s] 用途 %d 种注入色表（原表外 %d 种）%s"
          % (name, len(col), len([p for p in col if p not in _ORIG_ORDER]),
             "" if used else " —— 本栋无房间，地垫与注释都为空"))
    try:
        G.main()
    except SF.VerifyError as e:
        print("\n✗ 验收不通过：%s" % e, file=sys.stderr)
        return 1
    finally:
        G.MeshBuilder = MeshBuilder
    b = FleetFloorRecorder.last
    if b:
        n_pad = len(getattr(b, "pads_split_dropped", []))
        n_slab = len(getattr(b, "slabs_multi_dropped", []))
        if getattr(b, "split_rooms", 0) or n_pad or n_slab:
            print("[%s] 放宽 %d 条锚点：地垫 %d 条（%d 间房被三角化拆成多块，面积合计已逐间对上）、"
                  "楼板/屋面板 %d 条（同标高的分离区域，交付几何即如此）"
                  % (name, n_pad + n_slab, n_pad, getattr(b, "split_rooms", 0), n_slab))
    return 1 if (b and b.fails) else 0


if __name__ == "__main__":
    sys.exit(main())
