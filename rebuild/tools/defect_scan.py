# -*- coding: utf-8 -*-
r"""缺陷扫描 —— 拿 `构件库/缺陷库.json` 逐条量一栋楼的三维出件，**自己点名问题**。

为什么要有它（用户 2026-10-19「多希望你能自己发现做的立体图的问题，你怎么才能建一个
知识库去比对」「dxf 原始和生成后的比对也是一个很好的办法」）：
  过去每个问题都是**用户先在屏幕上看见**、我再去找。缺陷库把「已发生过的问题」固化成
  一条条可复测的判据：症状 → 判据 → 量具 → 修正方向。本脚本只做执行器：
  · 库里 `检测器` 非空的条目，由本文件的同名函数去量；
  · 库里 `闸` 非空的条目，读 `gates/_out/<闸>.<栋>.json`（不在就如实记「未量到」）；
  · 两者都没有的，写「需人看 / 需影像」，不许假装量过（铁律 199）。
  **DXF 原始 vs 生成后**的比对**不在这里重写**：直接调 `overlay_check.compare_building()`
  ——它是全仓唯一实现（铁律 018/174），本文件只读它的率。

输出：gates/_out/defects.<栋>.json（字节层写盘，铁律 79）+ 屏幕一张点名表。
用法：python -X utf8 -I rebuild/tools/defect_scan.py --bid c001
      python -X utf8 -I rebuild/tools/defect_scan.py --bid c001 --no-overlay   # 跳过最慢的一项
退出码：0 没有红 · 1 有红 · 2 缺件 · 4 一条都没量到
★ 盲区：mtime 只说明「文件比代码新/旧」，不说明内容；改了注释也会判过期（宁严勿松）。
"""
from __future__ import annotations

import datetime
import json
import math
import os
import re
import sys
import time

import ezdxf
from shapely.geometry import Polygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import building as B                                                     # noqa: E402
import overlay_check as O                                                # noqa: E402

CAT = os.path.join(CDUT, "rebuild", "构件库", "缺陷库.json")
PARAMS = os.path.join(CDUT, "rebuild", "构件库", "参数.json")
OUT = os.path.join(CDUT, "gates", "_out")

# 默认值只是**兜底**：真正生效的是 `构件库/参数.json::缺陷扫描`（改表不改码）。
# ★ DXF 比对阈值**照抄闸 J-10.8-04**（全仓 376 层实测标定：贴源 min 0.956 / p01 0.976；
#   覆盖 min 0.728 / p05 0.862 / 中位 0.936）。2026-10-19 第一版本文件自拟 0.95/0.90，
#   c001 覆盖 0.946~0.948 全判红 —— 那是**第二个尺子跟第一个打架**，不是缺陷（铁律 018/174）。
DEFAULTS = dict(
    门扇离墙_红_mm=800.0,     # c006 实测 807~1443；c001 最大 511
    门扇离墙_提示_mm=300.0,
    挑空_容差_m2=2.0,
    台阶_残留_m2=1.0,
    # ★ 2026-10-20 按用户令把 D-17 拆成 5 条（漏墙/多墙/偏了/成排/门洞边）。
    #   ★ 这 6 个阈值**故意不在这里写**：唯一真源是 `参数.json::缺陷扫描`，
    #     由 `calibrate_cov_thresholds.py` 从 359 层账本现算写盘（黄=p95、红=p99.5）。
    #     以前在这里抄一份，抄错了（p95 写 0.41%，实测 1.06%）⇒ 62/64 栋黄（铁律 018/174）。
    #     缺键时 `_p` 直接报错并指路，不拿一个自拟的兜底数继续跑。
    dxf_漏墙_黄=None,
    dxf_漏墙_红=None,
    dxf_多墙_黄=None,
    dxf_多墙_红=None,
    dxf_偏了_黄=None,
    dxf_偏了_红=None,
    # ★ 2026-10-20 D-25 层间错位（用户「办公楼副楼 3 楼和 4 楼错开了」）。
    #   这里**允许**留兜底数，和上面 D-17 那 6 个不一样：那 6 个是从 359 层账本现算的
    #   统计阈值（会随账本变），这两个是**语义切点**——实测真错位 590/1085/1400/1700 mm，
    #   对位正常 ≤ 1 mm，150/300 落在空档里，不靠样本重算。真源仍是 `参数.json::缺陷扫描`。
    层间错位_红_mm=300.0,
    层间错位_黄_mm=150.0,
    photo_空足迹_黄=0.35,
    photo_残差_黄_m=4.0,
    检测器开关={},
)

_P = dict(DEFAULTS)


def load_params():
    """读 `参数.json::缺陷扫描`；楼栋级覆盖在 `楼栋.<bid>.缺陷扫描`。"""
    global _P
    _P = dict(DEFAULTS)
    try:
        with open(PARAMS, encoding="utf-8") as fh:
            j = json.load(fh)
    except Exception:                                                    # noqa: BLE001
        return _P
    _P.update(j.get("缺陷扫描") or {})
    return _P


def _p(key, bid=None) -> float:
    """数值参数。`检测器开关` 那种非数值项不要走这里（直接读 `_P`）。

    取不到数就**炸**，不许兜底：D-19/20/21 的阈值只有 `参数.json` 一处真源，
    兜底数一旦写回代码就成了第二处（铁律 018/174），迟早两个数对不上而没人发现。
    """
    v = _P.get(key, DEFAULTS.get(key))
    if isinstance(v, (int, float)):
        return float(v)
    raise TypeError("参数 %s 不是数（%r）—— 跑 rebuild/tools/calibrate_cov_thresholds.py --apply "
                    "写 参数.json::缺陷扫描" % (key, v))


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def _ts(p):
    return time.strftime("%m-%d %H:%M", time.localtime(p)) if p else "—"


def _area_m2(poly_mm2):
    return poly_mm2 / 1e6


def _geom(rec):
    try:
        g = Polygon(rec["ring"], rec.get("holes") or []).buffer(0)
    except Exception:                                                    # noqa: BLE001
        return None
    return None if g.is_empty else g


def _load_json(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                    # noqa: BLE001
        return None


class Ctx:
    def __init__(self, bid):
        self.bid = bid
        self.root = B.root_for(bid)
        self.prof = B.profile(bid)
        self.cont_dir = os.path.join(self.root, "06_su", "contours")
        self.idx = os.path.join(self.cont_dir, "index.json")
        self.build_p = os.path.join(self.root, "05_build", "build.json")
        self.floors = []
        self.cont = {}
        self.build = None
        if os.path.exists(self.idx):
            with open(self.idx, encoding="utf-8") as fh:
                self.floors = [f["floor"] for f in json.load(fh)]
            for nm in self.floors:
                p = os.path.join(self.cont_dir, nm + ".json")
                if os.path.exists(p):
                    with open(p, encoding="utf-8") as fh:
                        self.cont[nm] = json.load(fh)
        self.build = _load_json(self.build_p)
        self.dxfs = {}
        for nm in self.floors:
            p = os.path.join(self.root, "01_cad", "raw", nm + ".dxf")
            self.dxfs[nm] = p if os.path.exists(p) else None

    def recs(self, floor, layer):
        return [r for r in (self.cont.get(floor) or {}).get("polys", [])
                if r.get("layer") == layer]

    def geoms(self, floor, layer):
        return [g for g in (_geom(r) for r in self.recs(floor, layer)) if g is not None]


# ---------------------------------------------------------------- 检测器
def det_stale(ctx):
    """D-12 出件静默过期：代码/源图/上游件比下游件新。"""
    out = []
    code = [os.path.join(HERE, f) for f in
            ("build3d.py", "export_contours.py", "redraw.py",
             "recognize_voids.py", "recognize_semantics.py", "door_rule.py")]
    newest = max((_mtime(p), p) for p in code)
    cases = [
        ("建件", ctx.build_p, newest),
        ("轮廓", ctx.idx, (_mtime(ctx.build_p), ctx.build_p)),
        ("GLB", os.path.join(ctx.root, "06_su", B.out_name(ctx.bid) + "_fc.glb"),
         (_mtime(ctx.idx), ctx.idx)),
    ]
    for nm, down, (up_t, up_p) in cases:
        if not os.path.exists(down):
            out.append(dict(层="全栋", 读数="%s 不在" % nm, 级别="提示",
                            证据=down, 位置=None))
            continue
        if up_t > _mtime(down):
            out.append(dict(层="全栋", 级别="红", 证据=down, 位置=None,
                            读数="%s %s 旧于 %s %s（差 %.1f h）"
                                 % (nm, _ts(_mtime(down)),
                                    os.path.basename(up_p), _ts(up_t),
                                    (up_t - _mtime(down)) / 3600.0)))
    raw = [p for p in ctx.dxfs.values() if p]
    if raw and os.path.exists(ctx.build_p):
        rnew = max((_mtime(p), p) for p in raw)
        if rnew[0] > _mtime(ctx.build_p):
            out.append(dict(层="全栋", 级别="红", 证据=rnew[1], 位置=None,
                            读数="源图 %s 比建件新（%.1f h）"
                                 % (os.path.basename(rnew[1]),
                                    (rnew[0] - _mtime(ctx.build_p)) / 3600.0)))
    return out


def det_slab_missing(ctx):
    out = []
    for nm in ctx.floors:
        sl = ctx.recs(nm, "SLAB")
        sa = sum(_area_m2(g.area) for g in ctx.geoms(nm, "SLAB"))
        waa = sum(_area_m2(g.area) for g in ctx.geoms(nm, "WALL"))
        if not sl:
            out.append(dict(层=nm, 级别="红", 读数="SLAB 0 块",
                            证据="contours/%s.json" % nm))
        elif sa < waa:
            out.append(dict(层=nm, 级别="红", 读数="楼板 %.1f m² < 墙 %.1f m²" % (sa, waa),
                            证据="contours/%s.json" % nm))
    return out


def _src_door_candidates(path):
    """源图里有没有**可能是门**的几何：门层实体 / INSERT 块 / 弧。

    ★ 2026-10-20 c004f1 4 层实测：该层 DXF 只有 `4墙体` 折线与几个 MTEXT，
      一个门符号都没有（识别器也印「三种画法各 0 樘：这一层图上没有可认的门」），
      而 D-11 只要「有墙、门洞 0」就报黄 ⇒ 把**设计上就没有门**的层报成漏认。
    ★ 盲区（铁律 158）：门画在墙层上当两条直线、又没有弧时，这里认不出 ⇒ 仍报黄
      （宁可保留一次假警报，也不把真漏认洗白）。
    """
    if not path or not os.path.exists(path):
        return None                                        # 量不到，不当成 False
    try:
        d = ezdxf.readfile(path)
    except Exception:                                     # noqa: BLE001
        return None
    for e in d.modelspace():
        t = e.dxftype()
        if t == "INSERT":
            return True
        if t == "ARC":
            return True
        if "门" in (e.dxf.layer or ""):
            return True
    return False


_GEO = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "INSERT", "SOLID", "HATCH"}
_SRC_CACHE = {}


def _src_col_candidates(path):
    """源图里有没有**画在柱层上的几何**（层名含「柱」，与 `B.layer("column", …)` 同一规则）。

    ★ 2026-10-20：全仓 240 条 D-11 黄里 **239 条是「柱=0」**。实测 c004 / c004f1 / c017 / c025
      的源图**根本没有柱层**（c025 1 层只有 4墙体 / 3轴线 / 5面积 / 6房间号 / 7使用单位），
      识别器当然认 0 根 —— 那是**图上的事实**，不是漏认。拿「图上没画」去报件的黄，
      等于拿一把量不到东西的尺子判人有病（铁律 158/199）。
    ★ 盲区（铁律 158）：柱画在墙层上当实心矩形、没有单独柱层时，这里认不出 ⇒ 仍报黄
      （宁可留假警报，也不把真漏认洗白）。
    ★ 只数**几何实体**：`4.3柱标注` 这类层上只有 MTEXT，不能算「画了柱」。
    """
    if not path or not os.path.exists(path):
        return None                                        # 量不到，不当成 False
    key = (path, os.path.getmtime(path))
    if key in _SRC_CACHE:
        return _SRC_CACHE[key]
    try:
        d = ezdxf.readfile(path)
    except Exception:                                     # noqa: BLE001
        return None
    hit = any(e.dxftype() in _GEO and "柱" in (e.dxf.layer or "") for e in d.modelspace())
    _SRC_CACHE[key] = hit
    return hit


def det_component_zero(ctx):
    out = []
    for f in (ctx.build or {}).get("floors") or []:
        if not f.get("n_wall"):
            continue
        for k, nm in (("n_door_void", "门洞"), ("n_col", "柱")):
            if f.get(k) == 0:
                lvl, extra = "黄", ""
                if k == "n_door_void":
                    has = _src_door_candidates(ctx.dxfs.get(f["floor"]))
                    if has is False:
                        lvl, extra = "提示", "；源图该层没有任何门符号/块/弧 ⇒ 不是漏认"
                    elif has is None:
                        extra = "；源图读不出（量不到，不当成没有门）"
                else:
                    has = _src_col_candidates(ctx.dxfs.get(f["floor"]))
                    if has is False:
                        lvl, extra = "提示", "；源图该层没有柱层几何 ⇒ 柱 0 根是图上的事实，不是漏认"
                    elif has is None:
                        extra = "；源图读不出（量不到，不当成没有柱）"
                out.append(dict(层=f["floor"], 级别=lvl,
                                读数="%s = 0（墙 %d 块）%s" % (nm, f["n_wall"], extra),
                                证据="05_build/build.json"))
    return out


def det_leaf_off_wall(ctx):
    """D-04 门扇立在房间里：门扇到**所有竖向构件**的距离。

    ★ 2026-10-19 第一版只量到 WALL，c006 报 46 条红（858~1443 mm），我据此说过「几何错」。
      逐条查实：**每一条都贴着柱子/楼梯/电梯/过梁**（距离 0）—— 门挂在柱边、开在楼梯口，
      都是合法的。把 WALL 并集当唯一参照物，红的是尺子不是门（铁律 158/192）：
      参照物退化成「只有墙」时，它会把唯一该保护的「门贴构件」判成错。
      现在参照物 = WALL ∪ COL ∪ STAIR ∪ LIFT ∪ LINTEL，并记下贴的是哪一类。
    """
    layers = ("WALL", "COL", "STAIR", "LIFT", "LINTEL")
    out = []
    for nm in ctx.floors:
        U = {}
        for lay in layers:
            gs = ctx.geoms(nm, lay)
            if gs:
                U[lay] = unary_union(gs)
        D = [(r, _geom(r)) for r in ctx.recs(nm, "DOOR")]
        D = [(r, g) for r, g in D if g is not None]
        if not U or not D:
            continue
        for r, g in D:
            d, hit = min(((g.distance(u), k) for k, u in U.items()),
                         key=lambda t: t[0])
            if d > _p('门扇离墙_提示_mm'):
                c = g.centroid
                out.append(dict(层=nm, 级别=("红" if d > _p('门扇离墙_红_mm') else "提示"),
                                读数="门扇离最近竖向构件 %s 有 %.0f mm" % (hit, d),
                                位置=[round(c.x, 0), round(c.y, 0)],
                                证据="contours/%s.json::%s" % (nm, r.get("id"))))
    return out


def det_void_unapplied(ctx):
    """D-10 挑空没扣：**洞环与楼板/屋面求交**，仍被盖住 = 洞没打穿。

    ★ 2026-10-19 第一版写成 `楼板 ≈ 语义.plate_m2 − 洞`，c001 四层全红（差 −130/−124/
      −106/−33 m²）。查实：`语义.json::plate_m2`（2层 3384.0）与轮廓 SLAB（2953.2）**不是
      同一个量**（分区口径 vs 轮廓口径），拿两个估计器互减，红的是参照物不是缺陷
      （铁律 158/194）。改成直接判**空间关系**：洞环里若还有 SLAB/ROOF ⇒ 洞没扣。
      c001 实测：2/3/5层 ∩=0.000，4层 ∩=0.001（斜边离散）⇒ 干净。
    """
    vj = _load_json(os.path.join(ctx.root, "02_recognize", "挑空.json"))
    if not vj:
        return []
    out = []
    for f in vj.get("层") or []:
        nm = f.get("层")
        holes = f.get("洞") or []
        if not holes:
            continue
        is_roof = nm == "屋面"
        fl = ctx.floors[-1] if is_roof else nm
        lay = "ROOF" if is_roof else "SLAB"
        if fl not in ctx.cont:
            out.append(dict(层=nm, 级别="提示", 读数="轮廓里没有 %s ⇒ 未量到" % fl,
                            证据="06_su/contours/index.json"))
            continue
        base = unary_union(ctx.geoms(fl, lay))
        if base.is_empty:
            out.append(dict(层=nm, 级别="提示", 读数="%s 层没有 %s 记录" % (fl, lay),
                            证据="contours/%s.json" % fl))
            continue
        for h in holes:
            g = _geom({"ring": h.get("ring") or []})
            if g is None:
                continue
            a = h.get("洞_m2") or _area_m2(g.area)
            ov = _area_m2(g.intersection(base).area)
            if ov > max(_p('挑空_容差_m2'), 0.01 * a):
                out.append(dict(层=nm, 级别="红",
                                读数="洞 %.1f m² 仍被 %s 盖住 %.1f m² ⇒ 没打穿"
                                     % (a, lay, ov),
                                证据="contours/%s.json" % fl))
    return out


def det_step_as_wall(ctx):
    steps = (ctx.prof or {}).get("台阶") or []
    out = []
    for st in steps:
        r = st.get("rect") or []
        if len(r) != 4:
            continue
        box = Polygon([(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])])
        tot, where = 0.0, []
        for nm in ctx.floors:
            for rec in ctx.recs(nm, "WALL"):
                g = _geom(rec)
                if g is None:
                    continue
                a = _area_m2(g.intersection(box).area)
                if a > 0.01:
                    tot += a
                    where.append((nm, round(a, 2), rec.get("id")))
        if tot > _p('台阶_残留_m2'):
            out.append(dict(层=where[0][0] if where else "全栋", 级别="红",
                            读数="台阶框内仍有墙 %.2f m²（%s）" % (tot, where[:3]),
                            位置=[(r[0] + r[2]) / 2, (r[1] + r[3]) / 2],
                            证据="构件库/楼栋.json::台阶"))
    return out


def det_wall_thickness(ctx):
    """D-13 墙厚读数（提示级）：2A/P 全栋中位。

    ★ 档案里**没有**声明墙厚（`楼栋.json` 无该键）⇒ 没有真值可比，只能报读数本身；
      逐层报 12 行会把表冲成噪声，所以合成一条（铁律 174：同名的量只留一个）。
    """
    ts = []
    for nm in ctx.floors:
        for g in ctx.geoms(nm, "WALL"):
            if g.area / 1e6 >= 0.5 and g.length > 1:
                ts.append(2.0 * g.area / g.length)
    if not ts:
        return []
    ts.sort()
    return [dict(层="全栋", 级别="提示",
                 读数="墙厚中位 %.0f mm（n=%d；档案无声明墙厚，无法比真值）"
                      % (ts[len(ts) // 2], len(ts)),
                 证据="contours/*.json")]


def det_wall_diagonal(ctx):
    """D-02/D-05 孤立斜墙片（提示级）：面积 0.05~3 m²、长宽比 ≥2、方向偏离轴 15°~75°。"""
    out = []
    for nm in ctx.floors:
        hits = []
        for rec in ctx.recs(nm, "WALL"):
            g = _geom(rec)
            if g is None:
                continue
            a = g.area / 1e6
            if not (0.05 <= a <= 3.0):
                continue
            rr = g.minimum_rotated_rectangle
            xs = list(rr.exterior.coords)
            d1 = math.dist(xs[0], xs[1])
            d2 = math.dist(xs[1], xs[2])
            if min(d1, d2) < 1:
                continue
            ang = math.degrees(math.atan2(xs[1][1] - xs[0][1],
                                          xs[1][0] - xs[0][0])) % 90
            if 15 < ang < 75 and max(d1, d2) / min(d1, d2) >= 2:
                c = g.centroid
                hits.append([rec.get("id"), round(a, 2), round(ang, 1),
                             round(c.x), round(c.y)])
        if hits:
            out.append(dict(层=nm, 级别="提示",
                            读数="孤立斜墙片 %d 块（需人看）" % len(hits),
                            位置=[hits[0][3], hits[0][4]],
                            证据="contours/%s.json 例：%s" % (nm, hits[:3])))
    return out


def _cov_rows(ctx):
    """一栋**只量一次**：`overlay_check.cov_causes` 逐层。

    ★ 2026-10-20 用户令「按原因拆 5 条」：D-17 原来一层只出一个合并读数，
      漏墙/多墙/偏移/台阶/门洞边混在一个黄里，看不懂也没法修。
      拆开后 5 条共用这一次量测（`ctx._cov` 缓存），不许各跑一遍（铁律 174）。
    """
    cache = getattr(ctx, "_cov", None)
    if cache is not None:
        return cache
    dm, dw, st = O.door_mode_of(ctx.bid), O.drawing_of(ctx.bid), O.steps_of(ctx.bid)
    rows = []
    for nm in ctx.floors:
        gp = os.path.join(ctx.cont_dir, nm + ".dxf")
        rp = os.path.join(ctx.root, "01_cad", "raw", nm + ".dxf")
        if not (os.path.exists(gp) and os.path.exists(rp)):
            rows.append({"层": nm, "ok": False,
                         "why": "缺件：%s" % ("轮廓" if not os.path.exists(gp) else "原始")})
            continue
        try:
            r = O.cov_causes(gp, rp, door_mode=dm, drawing=dw, steps=st)
        except Exception as ex:                                     # noqa: BLE001
            rows.append({"层": nm, "ok": False, "why": "量不出：%s: %s" % (type(ex).__name__, ex)})
            continue
        r["层"] = nm
        rows.append(r)
    ctx._cov = rows
    return rows


def _cov_rate(ctx, key, num, den):
    """逐层读一个原因点数的占比，按阈值出红/黄；缺件的层写「未量到」。"""
    hi, mid = float(_p(key + "_红")), float(_p(key + "_黄"))
    out = []
    for r in _cov_rows(ctx):
        if not r.get("ok"):
            out.append(dict(层=r.get("层"), 级别="提示",
                            读数="比对未量到：%s" % r.get("why"), 证据="overlay_check.cov_causes"))
            continue
        d = r.get(den) or 0
        if not d:
            continue
        x = (r.get(num) or 0) / d
        lvl = ("红" if x >= hi else "黄" if x >= mid else None)
        if lvl:
            out.append(dict(层=r["层"], 级别=lvl,
                            读数="%s %d / %s %d = %.2f%%（阈值 黄 %.1f%% / 红 %.1f%%）"
                                 % (num, r.get(num) or 0, den, d, 100 * x,
                                    100 * mid, 100 * hi),
                            位置=None, 证据="overlay_check.cov_causes"))
    return out


def det_cov_missing(ctx):
    """D-19 漏墙：源图上有、生成件 1 m 内什么都没有。"""
    return _cov_rate(ctx, "dxf_漏墙", "无件", "源点")


def det_cov_extra(ctx):
    """D-20 多墙：生成件上有、源图 300 mm 内没有（凭空多出来的墙）。"""
    return _cov_rate(ctx, "dxf_多墙", "多墙点", "生成点")


def det_cov_offset(ctx):
    """D-21 墙偏了：源图上有，生成件在 0.3~1 m 外（墙在，位置/厚度不对）。"""
    return _cov_rate(ctx, "dxf_偏了", "偏了", "源点")


def det_cov_steps(ctx):
    """D-22 成排踏步线：源图上一排等距等长线（台阶/踏步），件里没有对应。

    ★ 只出**提示**：这类线按用户 2026-10-18 的令「台阶从墙带扣掉」，
      本来就不该有墙；它进账是为了说清覆盖率分母里有多少不是墙，
      同时盯着「成排线在楼里 ⇒ 可能是楼梯间没建梯」这一类真缺陷。
    """
    out = []
    for r in _cov_rows(ctx):
        if not r.get("ok") or not (r.get("成排") or 0):
            continue
        out.append(dict(层=r["层"], 级别="提示",
                        读数="成排踏步线 %d 点（占源点 %.2f%%）—— 不是墙，覆盖率的假漏来源"
                             % (r["成排"], 100.0 * r["成排"] / (r.get("源点") or 1)),
                        位置=None, 证据="overlay_check._ladder_count"))
    return out


def det_cov_door(ctx):
    """D-23 门洞边：源图墙线贴着生成门扇 —— 洞口本来就不该有墙。"""
    out = []
    for r in _cov_rows(ctx):
        if not r.get("ok") or not (r.get("门洞边") or 0):
            continue
        out.append(dict(层=r["层"], 级别="提示",
                        读数="门洞边 %d 点（占源点 %.2f%%）—— 洞口侧壁，不该算漏墙"
                             % (r["门洞边"], 100.0 * r["门洞边"] / (r.get("源点") or 1)),
                        位置=None, 证据="overlay_check.cov_causes"))
    return out


def det_room_area(ctx):
    """D-24 房间面片面积 ≠ 图上面积：一整片过道/梯厅被当成一间房。

    为什么要有它（用户 2026-10-20「香樟园5号公寓这个杂物间有 100 多平方，你把过道识别成
    杂物间了」）：包里的房 `poly` = **整片连通空闲区**（楼板 − 墙带），不是按图上面积切的；
    `stated_m2` 是图上写的面积。房间的墙在图上没闭合（门洞补条没补上/墙断口），这一片就把
    房间和走廊并成一个分区 ⇒ 一个 9.9 m² 的杂物间被画成 155 m²。
    ★ 为什么以前的面积判据没抓到：`build_rooms` 面积核对**只算「墙定」片**，
      容量裁停片的「算得面积」被裁到图上面积（9.81 vs 9.9 看着一致），
      而包里落的是真实面片（铁律 018：同名的两个数，活下来的那个不是你以为的那个）。
    ★ 分母 / 阈值：比值 = 面片面积 ÷ 图上面积（不是 m² 差：墙中线 vs 净面积的 ~20% 口径差
      随房间大小走）。黄红由 `calibrate_room_area.py` 从全仓 9622 间现算，写在
      `参数.json::房间面积_黄/红`；这里**不写兜底数**（铁律 018/174）。
    """
    hi, mid = _p("房间面积_红"), _p("房间面积_黄")
    # 数据根可指到备份包（迭代账要用「改前」那一份真读数比，不许凭记忆写）
    base = os.path.join(os.environ.get("CDUT_PACK_DIR") or os.path.join(CDUT, "packs", "cdut-main"),
                        ctx.bid, "baseline", "floors")
    files = []
    for nm in os.listdir(base) if os.path.isdir(base) else []:
        m = re.match(r"^floor(\d+)\.json$", nm)
        if m:
            files.append((int(m.group(1)), os.path.join(base, nm)))
    if not files:
        return None                                   # None = 没量到（不是「全绿」）
    out = []
    for _k, fp in sorted(files):
        try:
            with open(fp, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception as ex:                                        # noqa: BLE001
            out.append(dict(层="floor%s" % _k, 级别="提示",
                            读数="读不出：%s: %s" % (type(ex).__name__, ex), 证据=fp))
            continue
        worst = None
        n_room = n_over = n_under = n_multi = 0
        for r in d.get("rooms") or []:
            st, poly = r.get("stated_m2"), r.get("poly")
            if not st or not poly or len(poly) < 3:
                continue
            # ★ 多房号共用一区（开敞区）：分母只有一个号的图上面积，算不出对的比值。
            #   不量，但要说出来有多少间没量（铁律 199：没量到 ≠ 0）。
            if len(r.get("numbers") or ()) > 1:
                n_multi += 1
                continue
            try:
                a = Polygon(poly).area
            except Exception:                                          # noqa: BLE001
                continue
            if a <= 0:
                continue
            q = a / st
            n_room += 1
            n_over += int(q >= mid)
            n_under += int(q < 0.8)
            if worst is None or q > worst[0]:
                worst = (q, r, a)
        if not n_room:
            out.append(dict(层=d.get("floor") or "floor%s" % _k, 级别="提示",
                            读数="这一层 0 间有图上面积 ⇒ 量不到（不是 0 间超标）", 证据=fp))
            continue
        if worst is None:                     # n_room>0 时不可能，写出来只为让类型收敛
            continue
        q, r, a = worst
        lvl = "红" if q >= hi else "黄" if q >= mid else None
        tail = "；另有面片<0.8× 的 %d 间" % n_under if n_under else ""
        read = ("%d/%d 间面片 ≥%.2f×：最差 %s %s 面片 %.1f m² / 图上 %s m² = %.1f×%s%s"
                % (n_over, n_room, mid,
                   r.get("number") or "(无房号)", r.get("purpose") or "",
                   a, r.get("stated_m2"), q, tail,
                   "；多房号共用一区 %d 间未量" % n_multi if n_multi else ""))
        if lvl:
            _pl = r.get("poly") or []
            out.append(dict(层=d.get("floor") or "floor%s" % _k, 级别=lvl, 读数=read,
                            位置=list(_pl[0]) if _pl else None,
                            证据="%s::%s" % (os.path.relpath(fp, CDUT), r.get("number"))))
    return out


def _ring_pts(recs, layers, step=150.0):
    """轮廓记录 → 打点（沿边每 150 mm 一点）。"""
    pts = []
    for r in recs:
        if r.get("layer") not in layers:
            continue
        ring = r.get("ring") or []
        n = len(ring)
        for i in range(n):
            x0, y0 = ring[i][0], ring[i][1]
            x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
            d = math.hypot(x1 - x0, y1 - y0)
            k = max(1, int(d / step))
            for j in range(k):
                t = j / k
                pts.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return pts


def _stair_centers_cont(recs, cluster=3000.0):
    """轮廓里的 STAIR 是一级一块 ⇒ 先按 3 m 聚成「一座楼梯」，再取每座的包围盒中心。"""
    cs = []
    for r in recs:
        if r.get("layer") != "STAIR":
            continue
        ring = r.get("ring") or []
        if not ring:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        cs.append(((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0))
    if not cs:
        return []
    parent = list(range(len(cs)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            if math.hypot(cs[i][0] - cs[j][0], cs[i][1] - cs[j][1]) <= cluster:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[ra] = rb
    grp = {}
    for i in range(len(cs)):
        grp.setdefault(find(i), []).append(cs[i])
    out = []
    for g in grp.values():
        xs = [p[0] for p in g]
        ys = [p[1] for p in g]
        out.append(((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0))
    return out


def _col_centers_cont(recs):
    """轮廓里的 COL 逐根取包围盒中心（一根柱一个记录）。"""
    out = []
    for r in recs:
        if r.get("layer") != "COL":
            continue
        ring = r.get("ring") or []
        if not ring:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        out.append(((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0))
    return out


def det_floor_offset(ctx):
    """D-25 层间平面基准不一致：相邻两层整层错开（用户「办公楼副楼 3 楼和 4 楼错开了」）。

    为什么以前的判据全绿：墙/房/门/面积量的都是**同一张图内部**的相对关系；没有任何一条
    把两层摆到同一基准上比。切图幅又把「窗口角」当楼栋原点 ⇒ 源图里某张图放偏了，
    那一层整体平移，单层内部一丝不乱。

    量具：`sheet_register.solve_sheets`（与修配准的**同一个**定案函数，铁律 018/174）。
      锚 = 柱心（≥3 根且配对率 ≥50% 才用）> 楼梯 > 文字点阵；墙族互相关逐边旁证。
      `enforce_fft=False`：两条尺子打架**不判红黄**，只出提示交人看
      （2026-10-20 实测：c004 的柱心/墙族都说 0、楼梯区说 478 ⇒ 记红就是把尺子的毛病算到楼头上）。
    阈值：`参数.json::缺陷扫描.层间错位_红_mm`（默认 300 mm）。
      依据：实测真错位 590/1085/1400/1700 mm，正常对位 ≤ 1 mm —— 300 mm 落在空档里。
    """
    import sheet_register as SR
    hi = _p("层间错位_红_mm")
    mid = _p("层间错位_黄_mm")
    names = [nm for nm in ctx.floors if ctx.cont.get(nm)]
    if len(names) < 2:
        return None                                   # 只有一层 ⇒ 量不到（不是没问题）
    pts = [_ring_pts((ctx.cont[nm].get("polys") or []),
                     ("WALL", "PARAPET", "COL", "LINTEL", "DOOR")) for nm in names]
    stairs = [_stair_centers_cont(ctx.cont[nm].get("polys") or []) for nm in names]
    # 柱心：刚体、逐层一样多 ⇒ 有柱就以柱定案（柱不定案时 solve_sheets 自己按比例作废）
    cols = [_col_centers_cont(ctx.cont[nm].get("polys") or []) for nm in names]
    try:
        rows, _ = SR.solve_sheets(names, pts, stairs, enforce_fft=False, cols=cols)
    except SystemExit as ex:
        return [dict(层="全栋", 级别="提示", 读数="量不了：%s" % ex, 证据=ctx.idx)]
    out = []
    for r in rows:
        dx, dy = r["dx_mm"], r["dy_mm"]
        d = max(abs(dx), abs(dy))
        nm = r["floor"]
        if r["anchor"] == "none":
            # 没有锚：FFT 只是旁证，不判红黄；但要把读数说出来（不许当成 0）
            fx, fy = r["fft_dx"], r["fft_dy"]
            if max(abs(fx), abs(fy)) >= hi:
                out.append(dict(层=nm, 级别="提示",
                                读数=("无楼梯/文字锚 ⇒ 未定案；墙族互相关说 (%+.0f,%+.0f) mm，"
                                      "只报不判（需人看）" % (fx, fy)),
                                证据="%s::contours/%s.json" % (os.path.relpath(ctx.root, CDUT), nm)))
            continue
        if d < mid:
            continue
        tail = "；★ %s" % r["conflict"] if r.get("conflict") else ""
        if r.get("conflict"):
            # 两条尺子打架 ⇒ **不判红黄**，只点名交人看（2026-10-20：c004 柱/墙都说 0、
            # 楼梯区说 478，若照判红，是把尺子的毛病记到楼头上）
            out.append(dict(层=nm, 级别="提示",
                            读数=("未定案：锚=%s 说偏 (%+.0f,%+.0f) mm，另一把尺子不同意，需人看%s"
                                  % (r["anchor"], dx, dy, tail)),
                            位置=None,
                            证据="%s::01_cad/raw/%s.dxf" % (os.path.relpath(ctx.root, CDUT), nm)))
            continue
        lvl = "红" if d >= hi else "黄"
        out.append(dict(层=nm, 级别=lvl,
                        读数=("整层相对相邻层偏 (%+.0f,%+.0f) mm（锚=%s，梯%d）%s"
                              % (dx, dy, r["anchor"], r["stairs"], tail)),
                        位置=None,
                        证据="%s::01_cad/raw/%s.dxf" % (os.path.relpath(ctx.root, CDUT), nm)))
    return out


def det_photo(ctx):
    """D-18 照片（2024 航拍 DSM）与三维件对不上。

    ★ 这是**唯一一条不经过 CAD 的证据链**：DXF 与生成件同错时，别的判据全绿，只有它会响。
    ★ 读数分三块，**不许混成一个 bool**（铁律 198）：
        · 配准：锚点处足迹内外高差、诊断最佳平移（只报不用）；
        · 高度：只比「两边都立着」的格，δ 吸收绝对高程差；
        · 空足迹：足迹内 DSM 判为地面的格占比 —— 这是「足迹比实体大」，不是高度差。
    ★ 阈值在 `参数.json::照片比对`，2026-10-19 **尚未标定**（只有 c001/c006 两栋），
      所以现在一律出「提示」，只报读数；等样本够了再落红黄。
    """
    import compare_photo as P
    r = P.run(ctx.bid, verbose=False)
    if not r.get("data"):
        return [dict(层="全栋", 级别="提示", 读数="未量到：%s" % r.get("why"),
                     证据="参数.json::照片比对")]
    d = r["data"]
    g, h = d["配准"], d["高度"]
    bs = g.get("诊断最佳平移") or {}
    f = [dict(层="全栋", 级别="提示",
              读数="配准 rot %.1f°（%s）· 足迹内外高差 %+.1f m · "
                   "诊断最佳平移 dE %+.0f dN %+.0f（%+.1f m）"
                   % (g["rot_deg"], g["rot_来源"], g["足迹内外高差_m"],
                      bs.get("dE_m", 0), bs.get("dN_m", 0), bs.get("高差_m", 0)),
              证据="rebuild/_work/photo_%s.json" % ctx.bid)]
    if h.get("残差中位_m") is not None:
        lvl = "提示"
        med = h["残差中位_m"]
        if med is not None and med > _p("photo_残差_黄_m"):
            lvl = "黄"
        f.append(dict(层="全栋", 级别=lvl,
                      读数="高度残差中位 %.2f / P90 %.2f m · 超 %.0f m 占 %.1f%% · "
                           "δ %+.2f m（%d 格）"
                           % (h["残差中位_m"], h["残差P90_m"], h["超差阈_m"],
                              100 * h["超差占比"], h["竖向偏移_m"], h["比较格数"]),
                      证据="photo_%s.json::高度" % ctx.bid))
    if h.get("空足迹占比") is not None:
        lvl = "黄" if h["空足迹占比"] > _p("photo_空足迹_黄") else "提示"
        f.append(dict(层="全栋", 级别=lvl,
                      读数="空足迹 %.1f%% —— 足迹内 DSM 判为地面"
                           % (100 * h["空足迹占比"]),
                      证据="photo_%s.json::高度.空足迹占比" % ctx.bid))
    hs = ((d.get("热点") or {}).get("条") or [])
    for i, q in enumerate(hs[:3], 1):
        f.append(dict(层="热点%d" % i, 级别="提示",
                      读数="E %.0f N %.0f · %d 格 · 残差中位 %.1f m · 模型 %.1f / 影像 %.1f m"
                           "（%s）"
                           % (q["E"], q["N"], q["格数"], q["残差中位_m"],
                              q["模型高_m"], q["影像高_m"],
                              # 符号 = 影像 − 模型 − δ ⇒ 负 = 模型更高
                              "模型偏高" if q["符号中位_m"] < 0 else "模型偏低"),
                      证据="photo_%s.json::热点（定位只报读数，阈未标定）" % ctx.bid))
    pv = d.get("伪证") or {}
    if not pv.get("通过"):
        f.append(dict(层="全栋", 级别="提示",
                      读数="伪证未通过：人为挪 %s 后读数没有变差 ⇒ 这一项分辨力不足"
                           % (pv.get("人工平移_m"),),
                      证据="photo_%s.json::伪证" % ctx.bid))
    return f


DETECTORS = {
    "stale_chain": det_stale,
    "slab_missing": det_slab_missing,
    "component_zero": det_component_zero,
    "leaf_off_wall": det_leaf_off_wall,
    "void_unapplied": det_void_unapplied,
    "step_as_wall": det_step_as_wall,
    "wall_thickness": det_wall_thickness,
    "wall_diagonal": det_wall_diagonal,
    "cov_missing": det_cov_missing,
    "cov_extra": det_cov_extra,
    "cov_offset": det_cov_offset,
    "cov_steps": det_cov_steps,
    "cov_door": det_cov_door,
    "room_area": det_room_area,
    # ★ 2026-10-20 D-25：量的是**跨层**关系，其余所有检测器量的都是单层内部。
    "floor_offset": det_floor_offset,
    "photo_dsm": det_photo,
}

# 这 5 条共用一次 cov_causes，`--no-overlay` 要一起跳
COV_DETECTORS = ("cov_missing", "cov_extra", "cov_offset", "cov_steps", "cov_door")


# ---------------------------------------------------------------- 执行
def run(bid, use_overlay=True, use_photo=True):
    load_params()
    with open(CAT, encoding="utf-8") as fh:
        cat = json.load(fh)
    ctx = Ctx(bid)
    if not ctx.floors:
        print("★ %s 没有轮廓 index：%s ⇒ 全部「未量到」" % (bid, ctx.idx))
        return 2
    print("楼栋 %s · 数据根 %s · %d 层" % (bid, ctx.root, len(ctx.floors)))
    res = []
    for e in cat["条"]:
        det, gate = e.get("检测器"), e.get("闸")
        item = dict(id=e["id"], 名=e["名"], 可测=e.get("可测"),
                    方向=e.get("方向"), findings=[], 状态=None)
        if det:
            switch = _P.get("检测器开关")
            switch = switch if isinstance(switch, dict) else {}
            if det in COV_DETECTORS and not use_overlay:
                item["状态"] = "跳过（--no-overlay）"
            elif det == "photo_dsm" and not use_photo:
                item["状态"] = "跳过（--no-photo）"
            elif switch.get(det) is False:
                item["状态"] = "关闭（参数.json::检测器开关）"
            elif det not in DETECTORS:
                item["状态"] = "检测器缺：%s" % det
            else:
                t0 = time.time()
                try:
                    fs = DETECTORS[det](ctx)
                    # ★ 检测器返回 None = **量具没数据可量**（不是「全绿」）。
                    #   铁律 199：没量到 ≠ 0；把它记成「已量、0 条」就是拿绿冒充没看。
                    item["状态"] = "未量到（检测器没有可量对象）" if fs is None else "已量"
                    item["findings"] = fs or []
                    item["耗时_s"] = round(time.time() - t0, 1)
                except Exception as ex:                                  # noqa: BLE001
                    item["状态"] = "崩了：%s: %s" % (type(ex).__name__, ex)
        elif gate:
            gp = os.path.join(OUT, "%s.%s.json" % (gate, bid))
            v = _load_json(gp)
            if v is None:
                item["状态"] = "未量到（没跑闸 %s）" % gate
            else:
                ps = v.get("pass")
                item["状态"] = "闸 %s：%s" % (
                    gate, "pass" if ps is True else "FAIL" if ps is False else "未量到")
                # ★ 2026-10-19 实测：`_verdict.parse_items` 把**以规则号开头的测量行**
                #   一律记成 status=fail（J-10.10-12 PASS 时那 3 条是读数不是红）
                #   ⇒ 不能拿 items 判红。只认 pass 位；FAIL 时从 run.txt 里取 `✗` 行。
                if ps is False:
                    rt = v.get("run_txt")
                    lines = []
                    if rt and os.path.exists(rt):
                        with open(rt, encoding="utf-8") as fh:
                            lines = [ln.rstrip("\n") for ln in fh]
                    for ln in lines:
                        s = ln.strip()
                        if s.startswith("✗"):
                            item["findings"].append(
                                dict(层="全栋", 级别="红",
                                     读数=s.lstrip("✗ ").strip(), 证据=rt))
                    if not item["findings"]:
                        item["findings"].append(
                            dict(层="全栋", 级别="红",
                                 读数="闸判 FAIL 但没有 ✗ 行（见 run_txt）", 证据=rt))
        else:
            item["状态"] = "需人看 / 需影像"
        res.append(item)

    red = sum(1 for i in res for f in i["findings"] if f.get("级别") == "红")
    warn = sum(1 for i in res for f in i["findings"] if f.get("级别") == "黄")
    note = sum(1 for i in res for f in i["findings"] if f.get("级别") == "提示")
    measured = sum(1 for i in res
                   if i["状态"] == "已量" or str(i["状态"]).startswith("闸"))
    out = dict(
        schema="cdut3d-defects-scan/1",
        bid=bid, 数据根=ctx.root,
        measured_at=datetime.datetime.now().isoformat(timespec="seconds"),
        合计=dict(条=len(res), 已量=measured, 红=red, 黄=warn, 提示=note),
        盲区=[
            "mtime 只说明文件新旧，不说明内容（改注释也会判过期，宁严勿松）",
            "门扇离墙用 WALL 并集，不区分「门洞本来就该通」",
            "DXF 比对只量 WALL/COL/STAIR 结构面，窗/檐口不在其中",
        ],
        条=res,
    )
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "defects.%s.json" % bid)
    with open(p, "wb") as fh:                                            # 字节层（铁律 79）
        fh.write(json.dumps(out, ensure_ascii=False, indent=1,
                            allow_nan=False).encode("utf-8"))

    for i in res:
        if not i["findings"]:
            mark = {"已量": "·", "跳过": "…"}.get(i["状态"], "?")
            print("  %s %s %-28s %s" % (mark, i["id"], i["名"], i["状态"]))
            continue
        by = {}
        for f in i["findings"]:
            by[f["级别"]] = by.get(f["级别"], 0) + 1
        print("  ★ %s %-28s %s %s" % (i["id"], i["名"], i["状态"],
                                       " ".join("%s%d" % (k, v) for k, v in by.items())))
        for f in sorted(i["findings"], key=lambda t: t["级别"] != "红")[:4]:
            print("      [%s] %s %s%s" % (
                f["级别"], f["层"], f["读数"],
                "" if not f.get("位置") else "  @%s" % f["位置"]))
        if len(i["findings"]) > 4:
            print("      …另有 %d 条" % (len(i["findings"]) - 4))
    crashed = [i["id"] for i in res if str(i["状态"]).startswith("崩了")]
    print("合计：%d 条 ⇒ 红 %d · 黄 %d · 提示 %d ⇒ %s"
          % (len(res), red, warn, note, p))
    if crashed:
        # ★ 检测器崩了 ≠ 这一项通过（铁律 199）；有红照报红，但不许再报「全绿」
        print("★ 检测器崩了：%s ⇒ 这几条**没量到**（不是没有缺陷）" % "、".join(crashed))
        return 1 if red else 4
    return 1 if red else 0


def main(argv):
    bid = None
    if "--bid" in argv:
        bid = argv[argv.index("--bid") + 1]
    bid = bid or os.environ.get("CDUT_BUILDING") or "c006"
    return run(bid, use_overlay="--no-overlay" not in argv,
               use_photo="--no-photo" not in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
