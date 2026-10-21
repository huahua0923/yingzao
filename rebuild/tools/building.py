# -*- coding: utf-8 -*-
r"""楼栋档案 —— 链上各步「这一栋长什么样」的**唯一一份**配置。

为什么要有：2026-10-17 之前整条链（切图/识别/建件/轮廓/SU/装包）的楼名、层名、层数、
图层白名单、出件名**全是 c006 的硬编码**。做第二栋楼（理化楼 c005）时若把这些值散着改，
c006 的件与闸会跟着漂 —— 而用户的口径是「**一处改动跑一档**、c006 零回归」。

★ 两条环境变量（都不设 = 现在的 c006 行为，一字不变）：
    CDUT_BUILDING=c005            选楼栋档案
    CDUT_REBUILD_ROOT=<dir>       数据根（默认 = 本仓 rebuild/）
  C005 的产物全落 `rebuild/c005/`，c006 的 `rebuild/01_cad` 等目录与全部闸基线不动。

★ 档案里**不许写层高**：层高的唯一真源是 `rebuild/构件库/参数.json::共用/层高`
  （`J-10.9-05` 盯的就是这件事）。这里只说「有几层、叫什么、哪层是顶层」。

调用方：
    sheet_windows.py / export_sheet.py / recognize.py / redraw.py /
    build3d.py / export_contours.py / su_obj_to_glb.py / run_chain.py

用法：
    import building as B
    B.ROOT        # 数据根（绝对路径）
    B.BID         # 楼栋 id
    B.profile()   # 本楼档案 dict
    B.floor_names()  # ["1层", …]（地上层，自下而上）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REBUILD = os.path.dirname(HERE)                       # …/rebuild
# ★ 2026-10-17：本文件会被**搬到 ASCII 暂存区**跟着跑（freecadcmd 不认非 ASCII 的脚本路径，
#   搬之前 `__file__` 推出来的 …/rebuild 就没了）⇒ 允许用 CDUT_PROFILE 显式指档案。
#   不设 = 现在的行为，一字不变。
PROFILE = os.environ.get("CDUT_PROFILE") or os.path.join(REBUILD, "构件库", "楼栋.json")

ROOT = os.environ.get("CDUT_REBUILD_ROOT") or REBUILD
BID = os.environ.get("CDUT_BUILDING") or "c006"

_CACHE = {}


def all_profiles():
    if "all" not in _CACHE:
        with open(PROFILE, encoding="utf-8") as f:
            _CACHE["all"] = json.load(f)
    return _CACHE["all"]


def _derive_floors(p):
    """档案没写 `floor_names` ⇒ 从**标题栏 ACAD_TABLE**现读（层名确实写在图上，
    不手打一份可能与图不一致的清单）。返回 {"floor_names":[…], "basement":…}。

    ★ 判读不到就抛，不返回空表（铁律 199：「没读到」不许同形于「这栋没层」）。
    ★ 有多个地下层时本函数不猜 —— 档案目前只支持一个 `basement`。
    """
    if "floor_from_title" not in sys.modules:
        sys.path.insert(0, HERE)
    import floor_from_title as FT                                     # noqa: E402
    res = FT.read_sheets(p["src_dxf"])
    if not res["n_with_floor"]:
        raise AssertionError("%s 标题栏读到 0 层：档案没写 floor_names，图上也没读到 ⇒ 不猜"
                             % (p.get("title") or p.get("src_dxf")))
    under = [s["floor"] for s in res["sheets"] if s["ordinal"] < 0]
    ground = [s["floor"] for s in res["sheets"] if s["ordinal"] > 0]
    if len(under) > 1:
        raise AssertionError("%s 标题栏读到 %d 个地下层 %s ⇒ 档案只支持一个 basement，不猜"
                             % (p.get("title") or "", len(under), under))
    return {"floor_names": ground, "basement": under[0] if under else None,
            "_floors_from": "title(%d 张)" % res["n_with_floor"]}


def profile(bid=None):
    b = bid or BID
    p = all_profiles()[b]
    if p.get("floor_names"):
        return p                                       # 显式写着 ⇒ 一字不动（c005/c006 走这里）
    if "_derived" not in _CACHE:
        _CACHE["_derived"] = {}
    if b not in _CACHE["_derived"]:
        _CACHE["_derived"][b] = _derive_floors(p)
    q = dict(p)
    q.update(_CACHE["_derived"][b])
    return q


_LYR = {}


def _layer_census(src):
    """源图图层表 + 每层实体数（**一次**读全图，进程内缓存）。

    ★ 2026-10-17：65 栋楼的普查实测墙层有 `4.2墙体`（101 张图）与 `4墙体`（5 张）、
      柱层有 `4.1结构柱`（40 张）与 `4.1柱子`（1 张）两种写法。这三个名字原先在
      recognize/redraw/build_rooms 里各写死一份 ⇒ 碰上另一种写法的图，识别会读到 **0 条墙线**，
      症状不是报错，是「这栋楼建出来是空的」（铁律 018/183）。
    """
    if src not in _LYR:
        import ezdxf
        doc = ezdxf.readfile(src)
        cnt = {}
        for e in doc.modelspace():
            cnt[e.dxf.layer] = cnt.get(e.dxf.layer, 0) + 1
        _LYR[src] = cnt
    return _LYR[src]


def layer(kind, default):
    """墙/柱/门图层：档案里显式写了就用；没写就**从源图图层表现认**。

    认定规则（都用实体数当分辨力，同名候选里取实体最多的那一层）：
      wall   : 层名含「墙体」；没有则取以「墙」结尾的
      column : 层名含「柱」
      door   : **与墙同层** —— 这批图的**门符号画在墙层上**，层名含「门」的层是
               「4.3门窗」「4.3门标注」这类**文字注释层**，不是几何。
    ★ 认不到墙层**抛异常**，不静默返回默认值 —— 「这一栋没墙」与「我没认出来」不许同形。
    ★★ 2026-10-18（用户令「很多建筑需要你自检一下」）：原来 door 取「层名含『门』且实体最多」
       的那一层，选到 `4.3门窗`(c007) / `4.3门标注`(c075) —— 这两层**没进 keep_layers、
       导出后 raw 里根本不存在** ⇒ 逐层认到 **0 樘门**，而墙层上其实有 239 / 277 樘。
       症状与「图上没画门」同形（铁律 158/199）。现在门层恒等于墙层，另两个量具逐栋复核：
       `audit_components.py` 逐层数墙层上的符号/弧/块，`build.json::n_door_void` 数实际抠出的洞。
    """
    p = profile()
    key = {"wall": "wall_layer", "column": "col_layer", "door": "door_layer"}[kind]
    if p.get(key):
        return p[key]
    cnt = _layer_census(p["src_dxf"])
    # ★ 选出来的层**必须在 keep_layers 里**：识别读的是导出后的 `01_cad/raw`，
    #   只在源图存在的层在 raw 里是空的（c007/c075 的病根）。没写 keep_layers 的
    #   老档案（c006）不套这条 —— 它走块路径、不用层名。
    keep = p.get("keep_layers")
    kept = (lambda n: n in keep) if keep else (lambda n: True)
    if kind == "wall":
        cand = [n for n in cnt if "墙体" in n] or [n for n in cnt if n.endswith("墙")]
        cand = [n for n in cand if kept(n)]
    elif kind == "column":
        cand = [n for n in cnt if "柱" in n and kept(n)]
    else:
        return layer("wall", default)
    if not cand:
        if kind == "wall":
            raise AssertionError("%s 源图里认不出墙层（含「墙体」或以「墙」结尾的层）：%s"
                                 % (p.get("title") or p["src_dxf"], sorted(cnt)[:40]))
        return default
    return max(cand, key=lambda n: cnt[n])


def keep_layer(suffix, default=None):
    """`keep_layers` 里按后缀（再放宽到「包含」）认唯一的台账层，如「面积」。
    命中不唯一 ⇒ 返回 `default`（调用方自己决定这是不是致命）。"""
    keep = profile().get("keep_layers") or []
    hit = [n for n in keep if n.endswith(suffix)] or [n for n in keep if suffix in n]
    return hit[0] if len(hit) == 1 else default


def floor_names(bid=None):
    """地上层名，自下而上（下标 i ⇒ z0 = i × 层高）。"""
    return list(profile(bid)["floor_names"])


def top_floor(bid=None):
    return profile(bid).get("top_floor") or floor_names(bid)[-1]


def out_name(bid=None):
    """出件名前缀：c006_white / c005_white / c006_su / c005_su。"""
    return profile(bid).get("output") or (bid or BID)


def root_for(bid=None):
    """这栋楼的**数据根**：c006 用 `rebuild/` 本身（历史默认），其余各自 `rebuild/<bid>/`。

    ★ 2026-10-18（用户「地下一楼也没有出来」）：这条规则原先**只写在** `run_chain_bid.py`
      的 `_root_for()` 里，而 `demo/build_pack_bid.py` 自己写了一份 `REB = rebuild/<bid>` ——
      ⇒ 给 c006 装包时找的是 `rebuild/c006/06_su/c006_fc.glb`（**这个目录不存在**），
      装包一步 rc=4，**c006 从来没进过共用装包器**：包还是 2026-10-17 那版
      `demo/build_pack.py`（11 份基线、没有 B1）⇒ 查看器地下一层一片色块都没有。
      现在只留这一份，两个调用方都调它（铁律 183：修好一个错法只算改了一半）。
    """
    b = bid or BID
    return REBUILD if b == "c006" else os.path.join(REBUILD, b)


# ★ 2026-10-19（实测踩到）：只写 `CDUT_BUILDING=c072`、不写 `CDUT_REBUILD_ROOT` 时，
#   `B.ROOT` 仍是 `rebuild/`（c006 的根）⇒ build_rooms 拿着 c072 的名义**静默跑完 c006**，
#   把 c006 的 房间表.json 又写了一遍，c072 一个字节没出。症状是「跑成功了、库还是只有一栋」。
#   现在 ROOT 跟随 BID 推导；显式给了 CDUT_REBUILD_ROOT 仍以它为准（c006 结果与旧行为一字不差）。
ROOT = os.environ.get("CDUT_REBUILD_ROOT") or root_for(BID)
